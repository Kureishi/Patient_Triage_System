"""
Shared "process one report" logic, used by both the CLI batch processor
(main.py) and the web UI (web/app.py), so there's exactly one code path
from PDF-in to PDF-out.
"""
import os
from .pdf_utils import extract_text_from_pdf, generate_recommendation_pdf
from .db import log_event


def process_report(graph_app, pdf_path: str, output_dir: str, conn=None) -> str:
    """
    Runs one patient report PDF through the triage graph and writes the
    recommendation PDF to output_dir. Returns the output file path.
    """
    patient_id = os.path.splitext(os.path.basename(pdf_path))[0]
    raw_text = extract_text_from_pdf(pdf_path)

    initial_state = {
        "patient_id": patient_id,
        "source_file": os.path.basename(pdf_path),
        "raw_text": raw_text,
        "pending_queue": [],
        "current_case": None,
        "retry_counts": {},
        "all_classifications": [],
        "verdicts": [],
        "escalations": [],
        "audit_log": [],
    }

    final_state = graph_app.invoke(initial_state, config={"recursion_limit": 100})

    if conn is not None:
        log_event(conn, patient_id, os.path.basename(pdf_path), "-", "run_complete",
                   f"{len(final_state['verdicts'])} resolved, {len(final_state['escalations'])} escalated")

    out_path = os.path.join(output_dir, f"{patient_id}_recommendation.pdf")
    generate_recommendation_pdf(
        out_path,
        patient_id=patient_id,
        source_file=os.path.basename(pdf_path),
        verdicts=[v.model_dump() for v in final_state["verdicts"]],
        escalations=[e.model_dump() for e in final_state["escalations"]],
        audit_log=final_state["audit_log"],
    )
    return out_path
