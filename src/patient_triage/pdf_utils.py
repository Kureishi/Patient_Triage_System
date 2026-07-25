"""
PDF I/O: reading patient report PDFs, writing final recommendation PDFs.
"""
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
import pdfplumber

# A page with fewer than this many characters of extracted text is treated
# as "no real text layer" -- either a scanned/photographed page, or one
# that's essentially blank. Real report pages run to hundreds of characters,
# so this comfortably avoids false positives on legitimate short pages while
# still catching truly empty/scanned ones.
MIN_TEXT_CHARS_PER_PAGE = 20


def extract_text_from_pdf(path: str, ocr_language: str = "eng") -> str:
    """
    Extracts text from a PDF, falling back to OCR (per page) for any page
    that has no meaningful text layer -- i.e. scanned or photographed pages.
    Pages with a normal text layer are never OCR'd; this only kicks in for
    the pages that actually need it, and only if the OCR extras are
    installed (see the 'ocr' optional dependency group + a system
    tesseract-ocr install).
    """
    text_parts = []
    scanned_page_indices = []

    with pdfplumber.open(path) as pdf:
        for i, page in enumerate(pdf.pages):
            page_text = (page.extract_text() or "").strip()
            if len(page_text) < MIN_TEXT_CHARS_PER_PAGE:
                scanned_page_indices.append(i)
                text_parts.append(None)  # filled in by OCR below, if needed
            else:
                text_parts.append(page_text)

    if scanned_page_indices:
        text_parts = _ocr_fill_pages(path, text_parts, scanned_page_indices, ocr_language)

    text = "\n".join(t for t in text_parts if t).strip()
    if not text:
        raise ValueError(
            f"No extractable text found in {path}, even after attempting OCR "
            f"on every page. The file may be blank, corrupted, or too low-"
            f"resolution/low-contrast for OCR to read."
        )
    return text


def _ocr_fill_pages(path: str, text_parts: list, page_indices: list, ocr_language: str) -> list:
    """
    Rasterizes each listed page (via PyMuPDF -- no system Poppler dependency
    needed, unlike pdf2image) and runs Tesseract OCR on it (via pytesseract,
    which does need the tesseract-ocr binary installed on the system).
    Imports are lazy so the base install doesn't require any of this unless
    a scanned PDF is actually encountered.
    """
    try:
        import fitz  # PyMuPDF
        import pytesseract
        from PIL import Image
        import io
    except ImportError as e:
        raise ImportError(
            "This PDF appears to be scanned/image-based (no text layer on "
            f"{len(page_indices)} page(s)), but OCR support isn't installed. "
            "Install it with: pip install patient-triage[ocr]"
        ) from e

    try:
        doc = fitz.open(path)
        for i in page_indices:
            pixmap = doc[i].get_pixmap(dpi=300)
            image = Image.open(io.BytesIO(pixmap.tobytes("png")))
            ocr_text = pytesseract.image_to_string(image, lang=ocr_language).strip()
            text_parts[i] = ocr_text
        doc.close()
    except pytesseract.TesseractNotFoundError as e:
        raise RuntimeError(
            "pytesseract is installed, but the tesseract-ocr binary itself "
            "isn't on this system's PATH. Install it with your OS package "
            "manager, e.g. `apt-get install tesseract-ocr` on Debian/Ubuntu "
            "or `brew install tesseract` on macOS."
        ) from e

    return text_parts


SEVERITY_COLORS = {
    "severe": colors.HexColor("#B00020"),
    "major": colors.HexColor("#E08600"),
    "minor": colors.HexColor("#2E7D32"),
}


def generate_recommendation_pdf(output_path: str, patient_id: str, source_file: str,
                                 verdicts, escalations, audit_log):
    """
    verdicts: list of SpecialistVerdict-like dicts {case_id, specialty, resolved, treatment_plan, reasoning}
    escalations: list of EscalatedCase-like dicts {case_id, ailment_type, specialty, severity, reason}
    audit_log: list[str]
    """
    doc = SimpleDocTemplate(output_path, pagesize=letter,
                             topMargin=0.75 * inch, bottomMargin=0.75 * inch,
                             title=f"Treatment Recommendation - {patient_id}",
                             author="Patient Triage System")
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("TitleX", parent=styles["Title"], fontSize=18)
    h2 = ParagraphStyle("H2", parent=styles["Heading2"], spaceBefore=14)
    body = styles["BodyText"]
    small = ParagraphStyle("Small", parent=styles["BodyText"], fontSize=8, textColor=colors.grey)

    story = []
    story.append(Paragraph("Treatment Recommendation Report", title_style))
    story.append(Spacer(1, 6))
    story.append(Paragraph(f"<b>Patient ID:</b> {patient_id}", body))
    story.append(Paragraph(f"<b>Source report:</b> {source_file}", body))
    story.append(Spacer(1, 12))

    story.append(Paragraph("Specialist Recommendations", h2))
    if not verdicts:
        story.append(Paragraph("No resolved specialist recommendations.", body))
    for v in verdicts:
        specialty = v["specialty"].replace("_", " ").title()
        story.append(Paragraph(f"<b>{specialty}</b> &mdash; Case {v['case_id']}", styles["Heading3"]))
        story.append(Paragraph(f"<b>Treatment plan:</b> {v.get('treatment_plan') or 'N/A'}", body))
        story.append(Paragraph(f"<b>Clinical reasoning:</b> {v.get('reasoning', '')}", body))
        story.append(Spacer(1, 8))

    if escalations:
        story.append(Paragraph("Escalated to Human Physician Review", h2))
        data = [["Case ID", "Ailment", "Specialty", "Severity", "Reason"]]
        for e in escalations:
            data.append([e["case_id"], e["ailment_type"], e["specialty"].replace("_", " ").title(),
                         e["severity"].upper(), e["reason"]])
        t = Table(data, colWidths=[0.7*inch, 1.6*inch, 1.2*inch, 0.8*inch, 2.2*inch])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#333333")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        story.append(t)
        story.append(Spacer(1, 12))

    story.append(Paragraph("Audit Trail (classification / reassessment history)", h2))
    for entry in audit_log:
        story.append(Paragraph(entry, small))

    story.append(Spacer(1, 16))
    story.append(Paragraph(
        "This report was generated by an automated triage prototype and is intended "
        "for clinical decision support only. It does not replace evaluation by a "
        "licensed physician.", small))

    doc.build(story)
