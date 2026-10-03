"""Build a typed Incident from the Evidence Plane only (env.json + derived system).

Reads NOTHING from ground truth and NOTHING from the ops-lite GT-summary row.
"""
from __future__ import annotations

from datetime import datetime, timezone

from ..models import Incident, TimeWindow
from .adls_adapter import EvidenceLake


def _epoch(s: str | int) -> datetime:
    return datetime.fromtimestamp(int(s), tz=timezone.utc)


def load_incident(lake: EvidenceLake, case: str) -> Incident:
    env = lake.read_env(case)
    namespace = env["NAMESPACE"]
    system = "".join(c for c in namespace if c.isalpha())  # "hs34" -> "hs"
    return Incident(
        case_name=case,
        system=system,
        namespace=namespace,
        normal_window=TimeWindow(start=_epoch(env["NORMAL_START"]), end=_epoch(env["NORMAL_END"])),
        abnormal_window=TimeWindow(start=_epoch(env["ABNORMAL_START"]), end=_epoch(env["ABNORMAL_END"])),
        symptoms=["service health degraded during the abnormal window vs the normal baseline"],
    )
