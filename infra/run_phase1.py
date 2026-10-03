"""Phase-1 end-to-end runner: one incident, GT hidden, autonomous investigation,
then OFFLINE comparison to ground truth. Prints + saves a scorecard.

Requires env from infra/runtime.env and `az login`. Run:
  set -a; source infra/runtime.env; set +a
  PYTHONPATH=src python infra/run_phase1.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from azure.identity import DefaultAzureCredential

from deeprca.agents import EvaluatorAgent, InvestigatorAgent
from deeprca.config import RuntimeConfig
from deeprca.evidence import EvidenceLake, load_incident
from deeprca.projection import build_projection
from deeprca.state import BlobLedgerStore
from deeprca.workflow import run_investigation


async def main() -> int:
    cfg = RuntimeConfig.from_env()
    case = os.environ["DEEPRCA_CASE"]
    cred = DefaultAzureCredential()

    lake = EvidenceLake(cfg.evidence_account, cred, cfg.evidence_filesystem)
    incident = load_incident(lake, case)
    assert not hasattr(incident, "root_services"), "Incident must not carry GT"
    print(f"== INCIDENT {incident.case_name} system={incident.system} ==")

    investigator = InvestigatorAgent(cfg.model)
    evaluator = EvaluatorAgent(cfg.model)
    store = BlobLedgerStore(cfg.state_account, cred, cfg.state_container)

    inv = await run_investigation(incident, lake, investigator, evaluator, store=store)
    print(f"== loop finished: state={inv.state.value} step={inv.step} "
          f"hypotheses={len(inv.hypotheses)} tool_calls={len(inv.tool_calls)} "
          f"evidence={len(inv.evidence_store)} evaluations={len(inv.evaluations)} ==")

    # Persistence: reload the authoritative ledger from the store.
    reloaded = store.load(inv.id)
    print(f"== ledger reloaded from blob: version={reloaded.version} "
          f"matches={reloaded.model_dump_json()==inv.model_dump_json()} ==")

    if inv.proposed_root_cause:
        print("PROPOSED root_services:", inv.proposed_root_cause.root_services,
              "fault:", inv.proposed_root_cause.fault_type)

    # ---------------- OFFLINE EVAL PLANE (the only GT access) ----------------
    from eval.gt_store import read_ground_truth
    from eval.scorer import isolation_scan, score

    gt = read_ground_truth(os.environ["DEEPRCA_GT_ACCOUNT"], case, cred)
    scorecard = score(inv, gt)

    proj_json = json.dumps(build_projection(incident, inv))
    leaks = isolation_scan([proj_json, inv.model_dump_json()], gt, os.environ["DEEPRCA_GT_ACCOUNT"])
    scorecard["isolation"] = {"gt_markers_leaked": leaks, "clean": not leaks}

    out = Path("eval/scorecards"); out.mkdir(parents=True, exist_ok=True)
    (out / f"{case}.json").write_text(json.dumps(scorecard, indent=2))
    print("\n== SCORECARD ==")
    print(json.dumps(scorecard, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
