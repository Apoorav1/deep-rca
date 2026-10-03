"""Offline scorer: compares a FROZEN Investigation against ground truth.

This is the only component that reads GT. Its output is a scorecard; it never flows
back into a live investigation.
"""
from __future__ import annotations

from typing import Any

from .ground_truth import GroundTruth


def _lower_set(xs) -> set[str]:
    return {str(x).strip().lower() for x in xs if str(x).strip()}


def score(inv: Any, gt: GroundTruth) -> dict:
    prc = getattr(inv, "proposed_root_cause", None)
    proposed = _lower_set(prc.root_services) if prc else set()
    gts = _lower_set(gt.root_services)
    suspected = proposed | _lower_set(h.suspected_service for h in inv.hypotheses if h.suspected_service)

    localization_exact = bool(gts) and proposed == gts
    localization_hit = bool(proposed & gts)
    localization_topk = bool(gts) and gts.issubset(suspected)
    multi_fault_recall = (len(proposed & gts) / len(gts)) if gts else 0.0

    ft = (prc.fault_type or "").strip().lower() if prc else ""
    fault_type_acc = ft in _lower_set(gt.chaos_types) if ft else False

    path = prc.causal_path if prc else None
    path_valid = bool(path and path.is_temporally_monotonic() and path.is_graph_valid())

    return {
        "case": inv.case_name,
        "concluded_state": inv.state.value,
        "proposed_root_services": sorted(proposed),
        "fault_type_proposed": ft or None,
        "metrics": {
            "localization_exact": localization_exact,
            "localization_hit": localization_hit,
            "localization_topk": localization_topk,
            "multi_fault_recall": round(multi_fault_recall, 3),
            "fault_type_accuracy": fault_type_acc,
            "causal_path_valid": path_valid,
        },
        "process": {
            "hypotheses": len(inv.hypotheses),
            "hypotheses_refuted": sum(1 for h in inv.hypotheses if h.status.value == "refuted"),
            "tool_calls": len(inv.tool_calls),
            "evidence": len(inv.evidence_store),
            "steps": inv.step,
            "evaluations": len(inv.evaluations),
        },
        "ground_truth": {"root_services": gt.root_services, "chaos_types": gt.chaos_types,
                         "n_required_faults": gt.n_required_faults},
    }


def isolation_scan(texts: list[str], gt: GroundTruth, gt_account: str) -> list[str]:
    """Return GT-channel markers that leaked into the Investigator-visible text.

    We look for artifacts that could ONLY appear if ground truth leaked: the GT storage
    account name, GT filenames, and the injection UUIDs. Service names are NOT scanned —
    they appear legitimately in telemetry and naming the culprit is the goal, not a leak.
    """
    markers = [gt_account.lower(), "label.json", "injection.json", "causal_graph.json"]
    for key in ("task_id", "trace_id", "id"):
        v = gt.injection.get(key)
        if v:
            markers.append(str(v).lower())
    blob = "\n".join(texts).lower()
    return [m for m in markers if m and m in blob]
