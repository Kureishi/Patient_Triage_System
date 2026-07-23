"""
Data contracts shared between agents. Using Pydantic so every hand-off
between Agent 1 (delegator) and Agent 2..N (specialists) is validated,
structured data -- not free-form prose the graph has to re-parse.
"""
from __future__ import annotations
from typing import List, Optional, Dict, TypedDict
from pydantic import BaseModel, Field
import uuid


class ClassificationItem(BaseModel):
    """One ailment extracted from a report, routed to one specialty."""
    case_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    ailment_type: str
    specialty: str
    severity: str  # "minor" | "major" | "severe"
    symptoms: List[str] = Field(default_factory=list)
    reasoning: str = ""
    # carries specialist feedback back into the delegator on reassessment
    prior_feedback: Optional[str] = None


class SpecialistVerdict(BaseModel):
    case_id: str
    specialty: str
    resolved: bool  # True = treatment plan produced, False = "can't determine"
    treatment_plan: Optional[str] = None
    reasoning: str = ""


class EscalatedCase(BaseModel):
    case_id: str
    ailment_type: str
    specialty: str
    severity: str
    reason: str  # why it's being escalated to a human physician


class CaseState(TypedDict, total=False):
    patient_id: str
    source_file: str
    raw_text: str

    # priority queue of ailments awaiting a specialist, sorted by severity
    pending_queue: List[ClassificationItem]
    # the ailment currently being handed to a specialist
    current_case: Optional[ClassificationItem]

    # retry_counts[case_id] = number of reassessment loops so far
    retry_counts: Dict[str, int]

    all_classifications: List[ClassificationItem]
    verdicts: List[SpecialistVerdict]
    escalations: List[EscalatedCase]
    audit_log: List[str]

    # transient routing keys used between the specialist and reassess nodes;
    # must be declared here or LangGraph will silently drop them between steps
    _last_outcome: Optional[str]
    _feedback: Optional[str]
