"""Phase-1 acceptance: the full vertical slice against Azure.

Runs one autonomous investigation (GT hidden) and asserts every Phase-1 requirement
in tests.json. Opt-in: skipped unless the Azure runtime env is configured and
`az login` is active. Run:

  set -a; source infra/runtime.env; set +a
  pytest tests/integration -m azure -q
"""
from __future__ import annotations

import asyncio
import json
import os

import pytest

pytestmark = [pytest.mark.azure, pytest.mark.integration]

_REQUIRED = ["DEEPRCA_EVIDENCE_ACCOUNT", "DEEPRCA_STATE_ACCOUNT", "DEEPRCA_MODEL_ENDPOINT",
             "DEEPRCA_GT_ACCOUNT", "DEEPRCA_CASE"]
if any(not os.environ.get(k) for k in _REQUIRED):
    pytest.skip("Azure runtime env not configured (source infra/runtime.env)",
                allow_module_level=True)


@pytest.fixture(scope="module")
def result():
    from azure.identity import DefaultAzureCredential
    from deeprca.agents import EvaluatorAgent, InvestigatorAgent
    from deeprca.config import RuntimeConfig
    from deeprca.evidence import EvidenceLake, load_incident
    from deeprca.state import BlobLedgerStore
    from deeprca.workflow import run_investigation

    cfg = RuntimeConfig.from_env()
    case = os.environ["DEEPRCA_CASE"]
    cred = DefaultAzureCredential()
    lake = EvidenceLake(cfg.evidence_account, cred, cfg.evidence_filesystem)
    incident = load_incident(lake, case)
    store = BlobLedgerStore(cfg.state_account, cred, cfg.state_container)
    inv = asyncio.run(run_investigation(
        incident, lake, InvestigatorAgent(cfg.model), EvaluatorAgent(cfg.model), store=store))
    return {"cfg": cfg, "case": case, "cred": cred, "incident": incident,
            "inv": inv, "store": store}


def test_p1_load_incident(result):
    inc = result["incident"]
    assert inc.case_name == result["case"]
    assert not hasattr(inc, "root_services") and not hasattr(inc, "chaos_types")


def test_p1_hypotheses(result):
    assert len(result["inv"].hypotheses) >= 2
    assert all(h.falsification_test for h in result["inv"].hypotheses)


def test_p1_three_tool_calls_linked_to_evidence(result):
    inv = result["inv"]
    ok = [tc for tc in inv.tool_calls if tc.result_evidence_ids]
    assert len(ok) >= 3, f"need >=3 tool calls that produced evidence, got {len(ok)}"


def test_p1_evidence_provenance(result):
    for ev in result["inv"].evidence_store:
        p = ev.provenance
        assert p.tool_call_id and p.source_uri and p.query and p.retrieved_at and p.time_range


def test_p1_hypothesis_both_sides_fields(result):
    for h in result["inv"].hypotheses:
        assert hasattr(h, "supporting_evidence") and hasattr(h, "contradicting_evidence")


def test_p1_propose_root_cause_with_valid_path(result):
    prc = result["inv"].proposed_root_cause
    assert prc is not None and prc.root_services
    assert prc.causal_path.is_temporally_monotonic()
    assert prc.causal_path.is_graph_valid()


def test_p1_blind_evaluator_decision(result):
    from deeprca.models import Decision
    inv = result["inv"]
    assert inv.evaluations, "evaluator must have run"
    assert all(e.decision in set(Decision) for e in inv.evaluations)


def test_p1_persistent_ledger_survives_reload(result):
    inv, store = result["inv"], result["store"]
    reloaded = store.load(inv.id)
    assert reloaded.model_dump_json() == inv.model_dump_json()


def test_p1_offline_compare_produces_scorecard(result):
    from eval.gt_store import read_ground_truth
    from eval.scorer import score
    gt = read_ground_truth(os.environ["DEEPRCA_GT_ACCOUNT"], result["case"], result["cred"])
    card = score(result["inv"], gt)
    assert "metrics" in card and "localization_hit" in card["metrics"]
    assert "causal_path_valid" in card["metrics"]


def test_p1_no_gt_leak_runtime(result):
    from deeprca.projection import build_projection
    from eval.gt_store import read_ground_truth
    from eval.scorer import isolation_scan
    inv = result["inv"]
    gt = read_ground_truth(os.environ["DEEPRCA_GT_ACCOUNT"], result["case"], result["cred"])
    proj = json.dumps(build_projection(result["incident"], inv))
    leaks = isolation_scan([proj, inv.model_dump_json()], gt, os.environ["DEEPRCA_GT_ACCOUNT"])
    assert leaks == [], f"ground-truth markers leaked into Investigator-visible data: {leaks}"
