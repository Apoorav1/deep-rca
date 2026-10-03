"""Reducer is pure, versioned, and the only ledger mutator."""
from datetime import datetime, timedelta

import pytest

from deeprca.models import Evidence, EvidenceKind, Investigation, Provenance, TimeWindow
from deeprca.state import (
    LinkEvidence,
    ProposeHypothesisAction,
    RecordEvidence,
    RequestEvidence,
    apply,
)
from deeprca.models import HypothesisStatus

T0 = datetime(2026, 5, 1, 17, 19, 7)
WIN = TimeWindow(start=T0, end=T0 + timedelta(minutes=5))


def _inv():
    return Investigation(incident_id="inc_1", case_name="batch-x")


def test_reducer_is_pure_and_versioned():
    inv = _inv()
    nxt = apply(inv, ProposeHypothesisAction(statement="s", falsification_test="f"))
    assert inv.version == 0 and len(inv.hypotheses) == 0  # original untouched
    assert nxt.version == 1 and len(nxt.hypotheses) == 1


def test_evidence_flow_links_provenance_to_tool_call():
    inv = apply(_inv(), RequestEvidence(tool="query_metrics", args={"service": "profile"}))
    tc = inv.tool_calls[0]
    ev = Evidence(kind=EvidenceKind.METRIC, observation="error_rate spike",
                  provenance=Provenance(tool_call_id=tc.id, source_uri="adls://x",
                                        query="q", retrieved_at=T0, time_range=WIN))
    inv = apply(inv, RecordEvidence(tool_call_id=tc.id, evidence=[ev], cost=0.01))
    assert inv.evidence_store[0].id == ev.id
    assert inv.tool_calls[0].result_evidence_ids == [ev.id]
    assert inv.cost_spent == pytest.approx(0.01)


def test_record_evidence_rejects_provenance_mismatch():
    inv = apply(_inv(), RequestEvidence(tool="query_metrics"))
    tc = inv.tool_calls[0]
    bad = Evidence(kind=EvidenceKind.METRIC, observation="x",
                   provenance=Provenance(tool_call_id="WRONG", source_uri="a", query="q",
                                         retrieved_at=T0, time_range=WIN))
    with pytest.raises(ValueError):
        apply(inv, RecordEvidence(tool_call_id=tc.id, evidence=[bad]))


def test_link_evidence_updates_both_sides_and_status():
    inv = apply(_inv(), ProposeHypothesisAction(statement="profile down", falsification_test="f"))
    inv = apply(inv, RequestEvidence(tool="query_metrics"))
    tc = inv.tool_calls[0]
    ev = Evidence(kind=EvidenceKind.METRIC, observation="spike",
                  provenance=Provenance(tool_call_id=tc.id, source_uri="x", query="q",
                                        retrieved_at=T0, time_range=WIN))
    inv = apply(inv, RecordEvidence(tool_call_id=tc.id, evidence=[ev]))
    hid = inv.hypotheses[0].id
    inv = apply(inv, LinkEvidence(hypothesis_id=hid, supporting=[ev.id],
                                  new_status=HypothesisStatus.SUPPORTED))
    h = inv.hypotheses[0]
    assert h.supporting_evidence == [ev.id] and h.status == HypothesisStatus.SUPPORTED

    with pytest.raises(ValueError):  # cannot link unknown evidence
        apply(inv, LinkEvidence(hypothesis_id=hid, contradicting=["ev_nope"]))
