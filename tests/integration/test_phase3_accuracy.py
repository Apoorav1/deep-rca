"""Phase-3 acceptance: the knowledge plane yields correct localization.

Runs one autonomous investigation and asserts the Investigator localizes the true
root-cause services and fault type (via pod-health / silent-service / topology
reasoning) with a valid causal path and clean GT isolation. Opt-in (needs Azure).

  set -a; source infra/runtime.env; set +a
  pytest tests/integration/test_phase3_accuracy.py -m azure -q
"""
from __future__ import annotations

import asyncio
import json
import os

import pytest

pytestmark = [pytest.mark.azure, pytest.mark.integration]

_REQUIRED = ["DEEPRCA_EVIDENCE_ACCOUNT", "DEEPRCA_MODEL_ENDPOINT", "DEEPRCA_GT_ACCOUNT", "DEEPRCA_CASE"]
if any(not os.environ.get(k) for k in _REQUIRED):
    pytest.skip("Azure runtime env not configured", allow_module_level=True)


@pytest.fixture(scope="module")
def scored():
    from azure.identity import DefaultAzureCredential
    from deeprca.agents import EvaluatorAgent, InvestigatorAgent
    from deeprca.config import RuntimeConfig
    from deeprca.evidence import EvidenceLake, load_incident
    from deeprca.projection import build_projection
    from deeprca.workflow import run_investigation
    from eval.gt_store import read_ground_truth
    from eval.scorer import isolation_scan, score

    cfg = RuntimeConfig.from_env()
    case = os.environ["DEEPRCA_CASE"]
    cred = DefaultAzureCredential()
    lake = EvidenceLake(cfg.evidence_account, cred, cfg.evidence_filesystem)
    inc = load_incident(lake, case)
    inv = asyncio.run(run_investigation(inc, lake, InvestigatorAgent(cfg.model),
                                        EvaluatorAgent(cfg.model)))
    gt = read_ground_truth(os.environ["DEEPRCA_GT_ACCOUNT"], case, cred)
    card = score(inv, gt)
    leaks = isolation_scan([json.dumps(build_projection(inc, inv)), inv.model_dump_json()],
                           gt, os.environ["DEEPRCA_GT_ACCOUNT"])
    return {"card": card, "leaks": leaks}


def test_p3_localization_hit(scored):
    assert scored["card"]["metrics"]["localization_hit"] is True


def test_p3_fault_type_accuracy(scored):
    assert scored["card"]["metrics"]["fault_type_accuracy"] is True


def test_p3_causal_path_valid(scored):
    assert scored["card"]["metrics"]["causal_path_valid"] is True


def test_p3_isolation_clean(scored):
    assert scored["leaks"] == []
