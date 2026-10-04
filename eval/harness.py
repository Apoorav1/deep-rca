"""Batch evaluation harness (offline plane). Runs autonomous investigations over a
set of cases and aggregates the scorecards. Ground truth is read only here.

  set -a; source infra/runtime.env; set +a
  PYTHONPATH="src;." python eval/harness.py <case1> <case2> ...
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

from azure.identity import DefaultAzureCredential

from deeprca.agents import EvaluatorAgent, InvestigatorAgent
from deeprca.config import RuntimeConfig
from deeprca.evidence import EvidenceLake, load_incident
from deeprca.projection import build_projection
from deeprca.workflow import run_investigation

from eval.gt_store import read_ground_truth
from eval.scorer import isolation_scan, score


async def run_cases(cases: list[str]) -> list[dict]:
    cfg = RuntimeConfig.from_env()
    cred = DefaultAzureCredential()
    gt_account = os.environ["DEEPRCA_GT_ACCOUNT"]
    results = []
    for case in cases:
        lake = EvidenceLake(cfg.evidence_account, cred, cfg.evidence_filesystem)
        inc = load_incident(lake, case)
        inv = await run_investigation(inc, lake, InvestigatorAgent(cfg.model),
                                      EvaluatorAgent(cfg.model))
        gt = read_ground_truth(gt_account, case, cred)
        card = score(inv, gt)
        leaks = isolation_scan([json.dumps(build_projection(inc, inv)), inv.model_dump_json()],
                               gt, gt_account)
        card["isolation_clean"] = not leaks
        results.append(card)
        m = card["metrics"]
        print(f"{case[:28]:28}  proposed={card['proposed_root_services']!s:24} "
              f"gt={gt.root_services!s:20} HIT={m['localization_hit']} "
              f"ftype={m['fault_type_accuracy']} path_valid={m['causal_path_valid']} "
              f"iso_clean={card['isolation_clean']}")
    return results


def aggregate(results: list[dict]) -> dict:
    n = len(results) or 1
    agg = {
        "n_cases": len(results),
        "localization_hit_rate": round(sum(r["metrics"]["localization_hit"] for r in results) / n, 3),
        "localization_exact_rate": round(sum(r["metrics"]["localization_exact"] for r in results) / n, 3),
        "fault_type_acc_rate": round(sum(r["metrics"]["fault_type_accuracy"] for r in results) / n, 3),
        "causal_path_valid_rate": round(sum(r["metrics"]["causal_path_valid"] for r in results) / n, 3),
        "isolation_clean_rate": round(sum(r["isolation_clean"] for r in results) / n, 3),
    }
    return agg


def main() -> int:
    cases = sys.argv[1:] or [os.environ["DEEPRCA_CASE"]]
    results = asyncio.run(run_cases(cases))
    agg = aggregate(results)
    print("\n== AGGREGATE ==")
    print(json.dumps(agg, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
