"""
Agent 2..N -- Specialist agents.

Rather than one hard-coded class per specialty, this is a single generic
node whose behavior is parameterized by `case.specialty` at call time --
each specialty gets its own system prompt context, but the code path,
schema, and hand-back-to-delegator logic are shared.
"""
from ..schemas import ClassificationItem, SpecialistVerdict
from ..llm_backends import LLMBackend
from ..utils import extract_json


def build_system_prompt(specialty: str) -> str:
    pretty = specialty.replace("_", " ")
    return f"""You are a {pretty} specialist physician reviewing a patient case for consultation. \
Given the ailment, symptoms, and severity, determine a treatment plan. Return a JSON object with \
exactly these fields:
- resolved: true if you can confidently propose a treatment plan, false if the information given \
  is insufficient or outside what a {pretty} specialist can resolve alone
- treatment_plan: the recommended plan (string), or null if resolved is false
- reasoning: your clinical reasoning, or if resolved is false, exactly what additional information \
  or reclassification is needed

Output ONLY the JSON object, no other text."""


def consult_specialist(backend: LLMBackend, case: ClassificationItem) -> SpecialistVerdict:
    system_prompt = build_system_prompt(case.specialty)
    user_prompt = (
        f"Ailment: {case.ailment_type}\n"
        f"Severity: {case.severity}\n"
        f"Symptoms: {case.symptoms}\n"
        f"Prior classification reasoning: {case.reasoning}\n"
    )
    if case.prior_feedback:
        user_prompt += f"\nNote: this case was previously reassessed. Feedback from earlier attempt: {case.prior_feedback}\n"

    raw = backend.complete(system_prompt, user_prompt)
    data = extract_json(raw)
    return SpecialistVerdict(
        case_id=case.case_id,
        specialty=case.specialty,
        resolved=bool(data.get("resolved", False)),
        treatment_plan=data.get("treatment_plan"),
        reasoning=data.get("reasoning", ""),
    )
