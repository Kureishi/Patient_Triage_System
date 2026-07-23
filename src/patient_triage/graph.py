"""
Graph wiring for the triage system, built with LangGraph so the
hand-back-to-delegator loop is a first-class cycle in the
state graph rather than bolted-on control flow.

Flow:

  intake --(queue empty?)--> compose --> END
     |
     v (queue has cases)
  pop_next --> specialist --(resolved/escalated & queue empty)--> compose --> END
                   |            (resolved/escalated & queue non-empty)--> pop_next
                   |
                   +--(unresolved, retries left)--> reassess --> pop_next
"""
import functools
from langgraph.graph import StateGraph, END

from . import config
from .schemas import CaseState, EscalatedCase
from .agents.delegator import classify_report, reassess_case
from .agents.specialist import consult_specialist


def _sorted_queue(items):
    return sorted(items, key=lambda c: config.SEVERITY_ORDER[c.severity])


def node_intake(state: CaseState, backend) -> dict:
    items = classify_report(backend, state["raw_text"])
    audit = list(state.get("audit_log", []))
    for it in items:
        audit.append(
            f"[INTAKE] Case {it.case_id}: '{it.ailment_type}' -> {it.specialty} "
            f"({it.severity.upper()}). {it.reasoning}"
        )
    return {
        "pending_queue": _sorted_queue(items),
        "all_classifications": items,
        "retry_counts": {},
        "verdicts": [],
        "escalations": [],
        "audit_log": audit,
    }


def node_pop_next(state: CaseState) -> dict:
    queue = list(state["pending_queue"])
    current = queue.pop(0)  # highest priority (severe first) due to sorted insertion
    return {"pending_queue": queue, "current_case": current}


def node_specialist(state: CaseState, backend) -> dict:
    case = state["current_case"]
    verdict = consult_specialist(backend, case)

    audit = list(state["audit_log"])
    retry_counts = dict(state.get("retry_counts", {}))
    verdicts = list(state["verdicts"])
    escalations = list(state["escalations"])

    if verdict.resolved:
        verdicts.append(verdict)
        audit.append(f"[{case.specialty.upper()}] Case {case.case_id} RESOLVED. {verdict.reasoning}")
        outcome = "resolved"
        feedback = None
    else:
        attempts = retry_counts.get(case.case_id, 0)
        audit.append(
            f"[{case.specialty.upper()}] Case {case.case_id} UNRESOLVED "
            f"(attempt {attempts + 1}/{config.MAX_REASSESSMENT_ATTEMPTS}). Feedback: {verdict.reasoning}"
        )
        retry_counts[case.case_id] = attempts + 1
        if attempts + 1 >= config.MAX_REASSESSMENT_ATTEMPTS:
            escalations.append(EscalatedCase(
                case_id=case.case_id, ailment_type=case.ailment_type,
                specialty=case.specialty, severity=case.severity,
                reason=f"Exceeded {config.MAX_REASSESSMENT_ATTEMPTS} reassessment attempts. "
                       f"Last specialist feedback: {verdict.reasoning}",
            ))
            audit.append(f"[ESCALATION] Case {case.case_id} routed to human physician review.")
            outcome = "escalated"
            feedback = None
        else:
            outcome = "needs_reassessment"
            feedback = verdict.reasoning

    result = {
        "verdicts": verdicts,
        "escalations": escalations,
        "retry_counts": retry_counts,
        "audit_log": audit,
        "_last_outcome": outcome,
    }
    if feedback is not None:
        result["_feedback"] = feedback
    return result


def node_reassess(state: CaseState, backend) -> dict:
    """This is the hand-back-to-Agent-1 step (requirement 4)."""
    case = state["current_case"]
    feedback = state.get("_feedback", "")
    updated = reassess_case(backend, case, feedback)

    queue = _sorted_queue(list(state["pending_queue"]) + [updated])
    audit = list(state["audit_log"])
    audit.append(
        f"[REASSESS] Case {updated.case_id} reclassified -> {updated.specialty} "
        f"({updated.severity.upper()}). {updated.reasoning}"
    )
    all_class = list(state["all_classifications"]) + [updated]
    return {
        "pending_queue": queue,
        "audit_log": audit,
        "all_classifications": all_class,
        "current_case": None,
    }


def node_compose(state: CaseState) -> dict:
    # PDF generation happens outside the graph (needs an output path);
    # this node just marks the terminal state.
    return {}


def _queue_check(state: CaseState) -> str:
    return "pop_next" if state.get("pending_queue") else "compose"


def _after_specialist(state: CaseState) -> str:
    if state.get("_last_outcome") == "needs_reassessment":
        return "reassess"
    return "pop_next" if state.get("pending_queue") else "compose"


def build_graph(backend):
    g = StateGraph(CaseState)
    g.add_node("intake", functools.partial(node_intake, backend=backend))
    g.add_node("pop_next", node_pop_next)
    g.add_node("specialist", functools.partial(node_specialist, backend=backend))
    g.add_node("reassess", functools.partial(node_reassess, backend=backend))
    g.add_node("compose", node_compose)

    g.set_entry_point("intake")
    g.add_conditional_edges("intake", _queue_check, {"pop_next": "pop_next", "compose": "compose"})
    g.add_edge("pop_next", "specialist")
    g.add_conditional_edges(
        "specialist", _after_specialist,
        {"reassess": "reassess", "pop_next": "pop_next", "compose": "compose"},
    )
    g.add_edge("reassess", "pop_next")
    g.add_edge("compose", END)
    return g.compile()
