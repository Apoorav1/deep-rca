"""The core investigation loop (the state machine of docs/architecture.md s7).

Observe -> hypothesize -> plan evidence -> collect -> update ledger -> evaluate ->
(continue | conclude | escalate). The Investigator proposes typed actions; the reducer
applies them; the blind Evaluator gates conclusion. Ground truth is never present here.
"""
from __future__ import annotations

from datetime import datetime

from ..agents import EvaluatorAgent, InvestigatorAgent
from ..evidence import EvidenceLake, run_tool
from ..models import (
    CausalEdge,
    CausalNode,
    CausalPath,
    Decision,
    Escalation,
    HypothesisStatus,
    Incident,
    InvestigationState,
    Investigation,
    ProposedRootCause,
)
from ..projection import build_projection
from ..state import (
    LinkEvidence,
    ProposeHypothesisAction,
    ProposeRootCauseAction,
    RecordEvaluation,
    RecordEvidence,
    RequestEvidence,
    SetEscalation,
    SetState,
    Tick,
    apply,
)

MIN_HYPOTHESES = 2
MIN_TOOL_CALLS = 3
MAX_TOOL_CALLS = 7


def _parse_ts(v, default: datetime) -> datetime:
    try:
        if isinstance(v, (int, float)):
            from datetime import timezone
            return datetime.fromtimestamp(int(v), tz=timezone.utc)
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except Exception:
        return default


def _nudge(inv: Investigation) -> str:
    linked = any(h.supporting_evidence or h.contradicting_evidence for h in inv.hypotheses)
    if len(inv.hypotheses) < MIN_HYPOTHESES:
        return f"Propose at least {MIN_HYPOTHESES} competing hypotheses before gathering evidence."
    if len(inv.tool_calls) < MIN_TOOL_CALLS:
        return (f"Gather evidence with tools (need >= {MIN_TOOL_CALLS}; so far "
                f"{len(inv.tool_calls)}). Then link evidence to hypotheses.")
    if inv.proposed_root_cause is None:
        if len(inv.tool_calls) >= MAX_TOOL_CALLS or linked:
            return ("You have enough evidence. Do NOT request more. Link your strongest "
                    "evidence to a hypothesis if not done, then IMMEDIATELY return action "
                    "'propose_root_cause' with root_services, fault_type and a causal_path "
                    "whose edges cite evidence_ids from the projection.")
        return ("Link collected evidence to hypotheses (supporting/contradicting, update "
                "status). You may do 1-2 more targeted tool calls, then propose a root cause.")
    return "Refine or confirm the proposed root cause; address alternatives and contradictions."


def _build_root_cause(d: dict, incident: Incident) -> ProposedRootCause:
    cp = d.get("causal_path", {}) or {}
    default_ts = incident.abnormal_window.start
    nodes = [CausalNode(entity=str(n.get("entity", "")),
                        fault_or_effect=str(n.get("fault_or_effect", "")),
                        timestamp=_parse_ts(n.get("timestamp"), default_ts))
             for n in cp.get("nodes", [])]
    edges = [CausalEdge(source=str(e.get("source", "")), target=str(e.get("target", "")),
                        mechanism=str(e.get("mechanism", "")),
                        evidence_ids=[str(x) for x in e.get("evidence_ids", [])])
             for e in cp.get("edges", [])]
    return ProposedRootCause(
        causal_path=CausalPath(nodes=nodes, edges=edges),
        root_services=[str(s) for s in d.get("root_services", [])],
        fault_type=d.get("fault_type"),
        confidence=float(d.get("confidence", 0.5)),
        rationale=str(d.get("rationale", "")),
    )


async def run_investigation(
    incident: Incident,
    lake: EvidenceLake,
    investigator: InvestigatorAgent,
    evaluator: EvaluatorAgent,
    store=None,
    max_steps: int = 24,
    observer=None,
) -> Investigation:
    def emit(kind: str, data: dict) -> None:
        if observer:
            try:
                observer(kind, data)
            except Exception:
                pass  # display/observer errors must never affect the investigation

    inv = Investigation(incident_id=incident.id, case_name=incident.case_name, max_steps=max_steps)
    inv = apply(inv, SetState(state=InvestigationState.OBSERVING))
    emit("start", {"case": incident.case_name, "system": incident.system})

    while inv.step < inv.max_steps:
        inv = apply(inv, Tick())
        proj = build_projection(incident, inv)
        try:
            raw = await investigator.decide(proj, nudge=_nudge(inv))
        except Exception:  # malformed model output: retry next step
            continue
        act = str(raw.get("action", "")).strip()

        if act == "propose_hypothesis":
            inv = apply(inv, ProposeHypothesisAction(
                statement=str(raw.get("statement", "")),
                falsification_test=str(raw.get("falsification_test", "n/a")),
                suspected_service=raw.get("suspected_service"),
                suspected_fault_type=raw.get("suspected_fault_type")))
            h = inv.hypotheses[-1]
            emit("hypothesis", {"step": inv.step, "id": h.id, "statement": h.statement,
                                "suspected_service": h.suspected_service,
                                "suspected_fault_type": h.suspected_fault_type,
                                "falsification_test": h.falsification_test})

        elif act == "request_evidence":
            # Cap evidence gathering so the investigation converges to a proposal.
            if inv.proposed_root_cause is None and len(inv.tool_calls) >= MAX_TOOL_CALLS:
                continue
            tool = str(raw.get("tool", ""))
            args = raw.get("args", {}) or {}
            inv = apply(inv, RequestEvidence(tool=tool, args=args))
            tc = inv.tool_calls[-1]
            evid = None
            try:
                evid = run_tool(tool, lake, incident, tc.id, args)
                inv = apply(inv, RecordEvidence(tool_call_id=tc.id, evidence=evid, cost=0.01))
            except Exception as e:
                inv.tool_calls[-1].status = f"error: {e}"[:200]
                emit("tool_error", {"step": inv.step, "tool": tool, "error": str(e)[:160]})
            if evid:  # emit AFTER the try so display issues never look like tool errors
                emit("evidence", {"step": inv.step, "tool": tool, "args": args,
                                  "observation": evid[0].observation if evid else "",
                                  "evidence_ids": [e.id for e in evid]})

        elif act == "link_evidence":
            status = raw.get("new_status")
            try:
                inv = apply(inv, LinkEvidence(
                    hypothesis_id=str(raw.get("hypothesis_id", "")),
                    supporting=[str(x) for x in raw.get("supporting", [])],
                    contradicting=[str(x) for x in raw.get("contradicting", [])],
                    new_status=HypothesisStatus(status) if status else None))
                emit("link", {"step": inv.step, "hypothesis_id": str(raw.get("hypothesis_id", "")),
                              "supporting": raw.get("supporting", []),
                              "contradicting": raw.get("contradicting", []), "new_status": status})
            except Exception:
                continue  # bad ids: skip; nudge will steer

        elif act == "propose_root_cause":
            if len(inv.hypotheses) < MIN_HYPOTHESES or len(inv.tool_calls) < MIN_TOOL_CALLS:
                continue  # guardrail: too early; nudge will redirect
            inv = apply(inv, ProposeRootCauseAction(root_cause=_build_root_cause(raw, incident)))
            inv = apply(inv, SetState(state=InvestigationState.PROPOSE_ROOT_CAUSE))
            prc = inv.proposed_root_cause
            emit("propose", {"step": inv.step, "root_services": prc.root_services,
                             "fault_type": prc.fault_type, "confidence": prc.confidence,
                             "rationale": prc.rationale,
                             "path_edges": [(e.source, e.target) for e in prc.causal_path.edges]})
        else:
            continue

        if store:
            store.save(inv)

        # Blind evaluation once a root cause exists.
        if inv.proposed_root_cause is not None:
            ev = await evaluator.evaluate(build_projection(incident, inv))
            inv = apply(inv, RecordEvaluation(evaluation=ev))
            emit("evaluation", {"step": inv.step, "decision": ev.decision.value,
                                "rationale": ev.rationale, "n_critiques": len(ev.critiques)})
            if ev.decision == Decision.CONCLUDE:
                inv = apply(inv, SetState(state=InvestigationState.CONCLUDED))
                break
            if ev.decision == Decision.ESCALATE:
                inv = apply(inv, SetEscalation(escalation=Escalation(
                    reason=ev.rationale or "Evaluator escalated.",
                    open_questions=ev.unresolved_contradictions,
                    state_snapshot_ref=inv.id,
                    suggested_human_actions=["Review evidence sufficiency and contradictions."])))
                inv = apply(inv, SetState(state=InvestigationState.ESCALATED))
                break
            # CONTINUE: keep iterating within budget.

    if inv.state not in (InvestigationState.CONCLUDED, InvestigationState.ESCALATED):
        inv = apply(inv, SetState(state=InvestigationState.BUDGET_EXHAUSTED))
    if store:
        store.save(inv)
    return inv
