"""
Agent 1 -- the Delegator.

Responsibilities:
  - Parse raw report text into one or more discrete ailments
  - Classify each ailment's specialty + severity
  - Re-classify a case when a specialist hands it back unresolved,
    incorporating the specialist's feedback
"""
from typing import List
from ..schemas import ClassificationItem
from ..llm_backends import LLMBackend
from ..utils import extract_json
from .. import config

SYSTEM_PROMPT = f"""You are a medical intake triage assistant. Return a JSON list of ailments \
found in the patient report. For each ailment, output an object with exactly these fields:
- ailment_type: short description of the condition
- specialty: one of {config.SPECIALTIES}
- severity: one of "minor", "major", "severe"
- symptoms: list of relevant symptom strings extracted from the report
- reasoning: 1-2 sentence clinical justification for the specialty and severity chosen

Rules:
- "severe" means immediate/emergency attention is required.
- If a report describes more than one distinct ailment, return multiple objects.
- Output ONLY the JSON list, no other text.
"""

REASSESS_SYSTEM_PROMPT = f"""You are a medical intake triage assistant performing a RE-ASSESSMENT. \
A specialist reviewed this case and could not determine a treatment plan. Reconsider the ailment, \
possibly reclassifying its specialty and/or severity based on the specialist's feedback. Return a JSON \
object with exactly these fields: ailment_type, specialty (one of {config.SPECIALTIES}), \
severity ("minor"|"major"|"severe"), symptoms (list of strings), reasoning (why you changed or \
kept the classification). Output ONLY the JSON object, no other text."""


def classify_report(backend: LLMBackend, raw_text: str) -> List[ClassificationItem]:
    user_prompt = f"Patient report:\n\n{raw_text}"
    raw = backend.complete(SYSTEM_PROMPT, user_prompt)
    data = extract_json(raw)
    items = [ClassificationItem(**d) for d in data]
    for item in items:
        if item.specialty not in config.SPECIALTIES:
            item.specialty = "general_medicine"
        if item.severity not in config.SEVERITY_ORDER:
            item.severity = "major"  # fail safe toward more caution, not less
    return items


def reassess_case(backend: LLMBackend, case: ClassificationItem, feedback: str) -> ClassificationItem:
    user_prompt = (
        f"Original ailment: {case.ailment_type}\n"
        f"Original specialty: {case.specialty}\n"
        f"Original severity: {case.severity}\n"
        f"Symptoms: {case.symptoms}\n\n"
        f"Specialist feedback (why no treatment plan could be determined):\n{feedback}"
    )
    raw = backend.complete(REASSESS_SYSTEM_PROMPT, user_prompt)
    data = extract_json(raw)
    updated = ClassificationItem(
        case_id=case.case_id,  # keep same case_id so retry_counts track correctly
        ailment_type=data.get("ailment_type", case.ailment_type),
        specialty=data.get("specialty", case.specialty),
        severity=data.get("severity", case.severity),
        symptoms=data.get("symptoms", case.symptoms),
        reasoning=data.get("reasoning", ""),
        prior_feedback=feedback,
    )
    if updated.specialty not in config.SPECIALTIES:
        updated.specialty = "general_medicine"
    if updated.severity not in config.SEVERITY_ORDER:
        updated.severity = case.severity
    return updated
