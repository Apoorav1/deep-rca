"""Pure reducer: (Investigation, Action) -> Investigation.

Returns a NEW Investigation (deep copy) with version bumped. The ledger is the
single source of truth; this is the only code path that changes it. Being pure +
deterministic makes investigations replayable and testable.
"""
from __future__ import annotations

from datetime import datetime, timezone

from ..models import Hypothesis, Investigation, ToolCall
from .actions import (
    Action,
    LinkEvidence,
    ProposeHypothesisAction,
    ProposeRootCauseAction,
    RecordEvaluation,
    RecordEvidence,
    RequestEvidence,
    SetEscalation,
    SetState,
    Tick,
)


def apply(inv: Investigation, action: Action) -> Investigation:
    nxt = inv.model_copy(deep=True)

    if isinstance(action, ProposeHypothesisAction):
        nxt.hypotheses.append(
            Hypothesis(
                statement=action.statement,
                falsification_test=action.falsification_test,
                suspected_service=action.suspected_service,
                suspected_fault_type=action.suspected_fault_type,
            )
        )

    elif isinstance(action, RequestEvidence):
        nxt.tool_calls.append(
            ToolCall(tool=action.tool, args=action.args, started=datetime.now(timezone.utc))
        )

    elif isinstance(action, RecordEvidence):
        tc = next((t for t in nxt.tool_calls if t.id == action.tool_call_id), None)
        if tc is None:
            raise ValueError(f"unknown tool_call_id {action.tool_call_id}")
        for ev in action.evidence:
            # Enforce provenance linkage back to the originating tool call.
            if ev.provenance.tool_call_id != tc.id:
                raise ValueError("evidence provenance.tool_call_id mismatch")
            nxt.evidence_store.append(ev)
            tc.result_evidence_ids.append(ev.id)
        tc.ended = datetime.now(timezone.utc)
        nxt.cost_spent += action.cost

    elif isinstance(action, LinkEvidence):
        hyp = nxt.hypothesis_by_id(action.hypothesis_id)
        if hyp is None:
            raise ValueError(f"unknown hypothesis {action.hypothesis_id}")
        known = {e.id for e in nxt.evidence_store}
        for eid in action.supporting + action.contradicting:
            if eid not in known:
                raise ValueError(f"cannot link unknown evidence {eid}")
        for eid in action.supporting:
            if eid not in hyp.supporting_evidence:
                hyp.supporting_evidence.append(eid)
        for eid in action.contradicting:
            if eid not in hyp.contradicting_evidence:
                hyp.contradicting_evidence.append(eid)
        if action.new_status is not None:
            hyp.status = action.new_status
        if action.new_posterior is not None:
            hyp.posterior = action.new_posterior

    elif isinstance(action, ProposeRootCauseAction):
        nxt.proposed_root_cause = action.root_cause

    elif isinstance(action, SetState):
        nxt.state = action.state

    elif isinstance(action, RecordEvaluation):
        nxt.evaluations.append(action.evaluation)

    elif isinstance(action, SetEscalation):
        nxt.escalation = action.escalation

    elif isinstance(action, Tick):
        nxt.step += 1

    else:  # pragma: no cover - exhaustive by construction
        raise TypeError(f"unknown action {type(action)!r}")

    nxt.version += 1
    return nxt
