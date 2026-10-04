"""Projection: the deterministic, read-only view the agents see.

This is the ONLY window the LLM has into the investigation. It is built from the
Incident (no GT fields) and the Investigation ledger (no GT). It must never contain
ground truth. Keeping construction here makes that auditable in one place.
"""
from __future__ import annotations

from ..evidence.tools import TOOLS
from ..knowledge import domain_knowledge
from ..models import Incident, Investigation


def _evidence_digest(inv: Investigation, limit: int = 12) -> list[dict]:
    out = []
    for ev in inv.evidence_store[-limit:]:
        out.append({
            "id": ev.id,
            "kind": ev.kind.value,
            "observation": ev.observation[:300],
            "from_tool_call": ev.provenance.tool_call_id,
        })
    return out


def build_projection(incident: Incident, inv: Investigation, *,
                     include_knowledge: bool = True, tool_names: list[str] | None = None) -> dict:
    tools = list(TOOLS.values()) if tool_names is None else [TOOLS[n] for n in tool_names if n in TOOLS]
    proj = {
        "incident": {
            "case": incident.case_name,
            "system": incident.system,
            "namespace": incident.namespace,
            "abnormal_window": [incident.abnormal_window.start.isoformat(),
                                incident.abnormal_window.end.isoformat()],
            "normal_window": [incident.normal_window.start.isoformat(),
                              incident.normal_window.end.isoformat()],
            "symptoms": incident.symptoms,
        },
        "available_tools": [
            {"name": s.name, "description": s.description, "parameters": s.parameters}
            for s in tools
        ],
        "hypotheses": [
            {
                "id": h.id,
                "statement": h.statement,
                "suspected_service": h.suspected_service,
                "suspected_fault_type": h.suspected_fault_type,
                "status": h.status.value,
                "falsification_test": h.falsification_test,
                "supporting_evidence": h.supporting_evidence,
                "contradicting_evidence": h.contradicting_evidence,
            }
            for h in inv.hypotheses
        ],
        "evidence": _evidence_digest(inv),
        "tool_calls_made": len(inv.tool_calls),
        "proposed_root_cause": (
            None if inv.proposed_root_cause is None else {
                "root_services": inv.proposed_root_cause.root_services,
                "fault_type": inv.proposed_root_cause.fault_type,
                "confidence": inv.proposed_root_cause.confidence,
            }
        ),
        "budget": {"step": inv.step, "max_steps": inv.max_steps,
                   "cost_spent": inv.cost_spent, "cost_budget": inv.cost_budget},
    }
    if include_knowledge:
        proj["knowledge"] = domain_knowledge()
    return proj
