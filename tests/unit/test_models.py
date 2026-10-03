"""Unit tests for typed models (tests.json: p1-evidence-provenance,
p1-hypothesis-both-sides, and Incident-has-no-GT)."""
from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError

from deeprca.models import (
    CausalEdge,
    CausalNode,
    CausalPath,
    Evidence,
    EvidenceKind,
    Hypothesis,
    Incident,
    Provenance,
    TimeWindow,
)

T0 = datetime(2026, 5, 1, 17, 19, 7)
T1 = T0 + timedelta(minutes=5)
WIN = TimeWindow(start=T0, end=T1)


def _prov(tc="tc_1"):
    return Provenance(tool_call_id=tc, source_uri="adls://evidence/x", query="q",
                      retrieved_at=T1, time_range=WIN)


def test_evidence_requires_provenance():
    with pytest.raises(ValidationError):
        Evidence(kind=EvidenceKind.METRIC, observation="spike")  # no provenance
    ev = Evidence(kind=EvidenceKind.METRIC, observation="spike", provenance=_prov())
    assert ev.provenance.tool_call_id == "tc_1"


def test_hypothesis_tracks_both_sides_and_requires_falsification():
    with pytest.raises(ValidationError):
        Hypothesis(statement="profile is down")  # missing falsification_test
    h = Hypothesis(statement="profile is down", falsification_test="check profile error_rate")
    assert h.supporting_evidence == [] and h.contradicting_evidence == []


def test_incident_has_no_root_cause_fields():
    inc = Incident(case_name="batch-x", system="hs", namespace="hs34",
                   normal_window=WIN, abnormal_window=WIN)
    assert not hasattr(inc, "root_services")
    with pytest.raises(ValidationError):  # extra='forbid'
        Incident(case_name="b", system="hs", namespace="hs34",
                 normal_window=WIN, abnormal_window=WIN, root_services=["profile"])


def test_causal_path_validity_and_monotonicity():
    n1 = CausalNode(entity="service|profile", fault_or_effect="unavailable", timestamp=T0)
    n2 = CausalNode(entity="service|frontend", fault_or_effect="erroring", timestamp=T1)
    good = CausalPath(
        nodes=[n1, n2],
        edges=[CausalEdge(source="service|profile", target="service|frontend",
                          mechanism="dependency call fails", evidence_ids=["ev_1"])],
    )
    assert good.is_temporally_monotonic()
    assert good.is_graph_valid({("service|profile", "service|frontend")})
    # edge without evidence is invalid
    bad = CausalPath(nodes=[n1, n2],
                     edges=[CausalEdge(source="service|profile", target="service|frontend",
                                       mechanism="x", evidence_ids=[])])
    assert not bad.is_graph_valid()
    # reversed time is non-monotonic
    rev = CausalPath(nodes=[n1, n2],
                     edges=[CausalEdge(source="service|frontend", target="service|profile",
                                       mechanism="x", evidence_ids=["ev_1"])])
    assert not rev.is_temporally_monotonic()
