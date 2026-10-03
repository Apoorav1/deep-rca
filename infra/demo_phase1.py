"""Deep-RCA Phase-1 LIVE DEMO.

Narrates one autonomous investigation step-by-step (hypotheses, tool calls + findings,
evaluator verdicts, final proposal), then reveals ground truth from the OFFLINE plane
and prints the scorecard. Compute runs locally against the Azure evidence lake / state
store / Foundry model.

  set -a; source infra/runtime.env; set +a
  PYTHONPATH="src;." python infra/demo_phase1.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

# Windows consoles default to cp1252; force UTF-8 so box-drawing/arrows render.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from azure.identity import DefaultAzureCredential

from deeprca.agents import EvaluatorAgent, InvestigatorAgent
from deeprca.config import RuntimeConfig
from deeprca.evidence import EvidenceLake, load_incident
from deeprca.projection import build_projection
from deeprca.state import BlobLedgerStore
from deeprca.workflow import run_investigation

C = {"b": "\033[1m", "d": "\033[2m", "g": "\033[32m", "y": "\033[33m",
     "r": "\033[31m", "c": "\033[36m", "m": "\033[35m", "x": "\033[0m"}


def line(ch="─", n=74):
    print(C["d"] + ch * n + C["x"])


def observer(kind: str, data: dict):
    s = data.get("step", "")
    if kind == "start":
        line("=")
        print(f"{C['b']}DEEP-RCA INVESTIGATION  case={data['case']}  system={data['system']}{C['x']}")
        print(f"{C['d']}Ground truth is hidden from the Investigator and the Evaluator.{C['x']}")
        line("=")
    elif kind == "hypothesis":
        print(f"\n{C['m']}[{s:>2}] HYPOTHESIS{C['x']} {C['b']}{data['statement']}{C['x']}")
        print(f"      suspect: {C['y']}{data['suspected_service']}{C['x']} / "
              f"{data['suspected_fault_type']}   {C['d']}falsify: {data['falsification_test']}{C['x']}")
    elif kind == "evidence":
        a = f"({data['args']})" if data.get("args") else ""
        print(f"\n{C['c']}[{s:>2}] TOOL {C['b']}{data['tool']}{C['x']}{C['c']}{a}{C['x']}")
        print(f"      {C['g']}→{C['x']} {data['observation'][:200]}")
    elif kind == "tool_error":
        print(f"\n{C['r']}[{s:>2}] TOOL {data['tool']} error: {data['error']}{C['x']}")
    elif kind == "link":
        print(f"{C['d']}[{s:>2}] link evidence -> hyp {data['hypothesis_id']}  "
              f"support={data['supporting']} contra={data['contradicting']} status={data['new_status']}{C['x']}")
    elif kind == "propose":
        line()
        print(f"{C['b']}[{s:>2}] PROPOSED ROOT CAUSE{C['x']}  "
              f"services={C['y']}{data['root_services']}{C['x']}  fault={data['fault_type']}  "
              f"conf={data['confidence']}")
        print(f"      causal path: {' , '.join(f'{a}->{b}' for a, b in data['path_edges'])}")
        print(f"      {C['d']}{data['rationale'][:240]}{C['x']}")
    elif kind == "evaluation":
        col = {"CONCLUDE": C["g"], "ESCALATE": C["r"], "CONTINUE": C["y"]}.get(data["decision"], "")
        print(f"      {C['b']}EVALUATOR (blind):{C['x']} {col}{data['decision']}{C['x']}  "
              f"{C['d']}{data['rationale'][:150]}{C['x']}")


async def main() -> int:
    cfg = RuntimeConfig.from_env()
    case = os.environ["DEEPRCA_CASE"]
    cred = DefaultAzureCredential()
    lake = EvidenceLake(cfg.evidence_account, cred, cfg.evidence_filesystem)
    incident = load_incident(lake, case)
    store = BlobLedgerStore(cfg.state_account, cred, cfg.state_container)

    inv = await run_investigation(incident, lake, InvestigatorAgent(cfg.model),
                                  EvaluatorAgent(cfg.model), store=store, observer=observer)

    line("=")
    print(f"{C['b']}FINAL STATE: {inv.state.value}{C['x']}  "
          f"(steps={inv.step}, hypotheses={len(inv.hypotheses)}, "
          f"tool_calls={len(inv.tool_calls)}, evaluations={len(inv.evaluations)})")

    # Persistence proof
    reloaded = store.load(inv.id)
    ok = reloaded.model_dump_json() == inv.model_dump_json()
    print(f"Ledger persisted to blob and reloaded byte-identical: "
          f"{C['g'] if ok else C['r']}{ok}{C['x']}")

    # ---------- OFFLINE PLANE: reveal GT + score ----------
    from eval.gt_store import read_ground_truth
    from eval.scorer import isolation_scan, score
    gt = read_ground_truth(os.environ["DEEPRCA_GT_ACCOUNT"], case, cred)
    card = score(inv, gt)
    leaks = isolation_scan([json.dumps(build_projection(incident, inv)), inv.model_dump_json()],
                           gt, os.environ["DEEPRCA_GT_ACCOUNT"])
    line("=")
    print(f"{C['b']}GROUND TRUTH (revealed only now, by the offline plane){C['x']}")
    print(f"  root services: {C['g']}{gt.root_services}{C['x']}   fault: {gt.chaos_types}")
    prc = inv.proposed_root_cause
    print(f"  investigator said: {C['y']}{prc.root_services if prc else None}{C['x']} / "
          f"{prc.fault_type if prc else None}")
    m = card["metrics"]
    hit = C["g"] + "HIT" + C["x"] if m["localization_hit"] else C["r"] + "MISS" + C["x"]
    print(f"\n  localization: {hit}   fault_type_acc={m['fault_type_accuracy']}   "
          f"causal_path_valid={C['g']}{m['causal_path_valid']}{C['x']}")
    print(f"  GT-isolation leak scan: {C['g']+'CLEAN' if not leaks else C['r']+str(leaks)}{C['x']}")
    line("=")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
