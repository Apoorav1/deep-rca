"""Evidence Plane tools. The ONLY way the Investigator touches telemetry.

Each tool compares the normal baseline vs the abnormal window and returns compact,
bounded ``Evidence`` objects with mandatory provenance. Tools never read ground truth.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

import pandas as pd

from ..models import Evidence, EvidenceKind, Incident, Provenance
from .adls_adapter import EvidenceLake


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict           # JSON schema for args
    fn: Callable
    kind: EvidenceKind


def _prov(lake: EvidenceLake, inc: Incident, tool_call_id: str, leaf: str, query: str) -> Provenance:
    return Provenance(
        tool_call_id=tool_call_id,
        source_uri=lake.source_uri(inc.case_name, leaf),
        query=query,
        retrieved_at=datetime.now(timezone.utc),
        time_range=inc.abnormal_window,
    )


def _is_error_status(s: Any) -> bool:
    if s is None:
        return False
    return "ERROR" in str(s).upper()


# --------------------------------------------------------------------------- #
# query_metrics
# --------------------------------------------------------------------------- #
def query_metrics(lake, inc, tool_call_id, service: str | None = None, top: int = 8) -> list[Evidence]:
    norm = lake.read_table(inc.case_name, "normal_metrics")
    abn = lake.read_table(inc.case_name, "abnormal_metrics")
    if service:
        norm = norm[norm["service_name"] == service]
        abn = abn[abn["service_name"] == service]

    def agg(df):
        if df.empty:
            return pd.Series(dtype=float)
        return df.groupby(["service_name", "metric"])["value"].mean()

    n, a = agg(norm), agg(abn)
    joined = pd.concat([n.rename("normal"), a.rename("abnormal")], axis=1).fillna(0.0)
    # Drop near-constant infra counters (filesystem/memory capacity, limits) that swamp ranking.
    mag = joined[["normal", "abnormal"]].abs().max(axis=1)
    name_bad = joined.index.get_level_values("metric").astype(str).str.contains(
        "capacity|limit|available|allocatable", case=False, regex=True)
    # Exclude byte/IO counters that swamp relative-change ranking and mislead RCA.
    name_bad = name_bad | joined.index.get_level_values("metric").astype(str).str.contains(
        "memory|filesystem|rss|working_set|page_faults|network|bytes", case=False, regex=True)
    joined = joined[(mag < 1e9) & (~name_bad)]
    joined["delta"] = joined["abnormal"] - joined["normal"]
    joined["rel"] = joined["delta"] / joined["normal"].abs().replace(0, 1e-9)
    ranked = joined.reindex(joined["rel"].abs().sort_values(ascending=False).index).head(top)
    rows = [
        {"service": idx[0], "metric": idx[1], "normal": round(float(r.normal), 4),
         "abnormal": round(float(r.abnormal), 4), "rel_change": round(float(r.rel), 3)}
        for idx, r in ranked.iterrows()
    ]
    obs = ("Largest metric shifts (abnormal vs normal): "
           + "; ".join(f"{x['service']}/{x['metric']} {x['rel_change']:+.2f}x" for x in rows[:5])
           ) if rows else "No metric data for the requested scope."
    return [Evidence(kind=EvidenceKind.METRIC, observation=obs,
                     payload={"ranked": rows, "service_filter": service},
                     confidence=0.6,
                     provenance=_prov(lake, inc, tool_call_id, "abnormal_metrics.parquet",
                                      f"metrics delta service={service} top={top}"))]


# --------------------------------------------------------------------------- #
# query_traces
# --------------------------------------------------------------------------- #
def query_traces(lake, inc, tool_call_id, service: str | None = None, top: int = 8) -> list[Evidence]:
    norm = lake.read_table(inc.case_name, "normal_traces")
    abn = lake.read_table(inc.case_name, "abnormal_traces")

    def summarize(df):
        if df.empty:
            return pd.DataFrame()
        df = df.copy()
        df["is_error"] = df["attr.status_code"].map(_is_error_status)
        if "attr.http.response.status_code" in df.columns:
            http = pd.to_numeric(df["attr.http.response.status_code"], errors="coerce").fillna(0)
            df["is_error"] = df["is_error"] | (http >= 500)
        g = df.groupby("service_name")
        return pd.DataFrame({
            "requests": g.size(),
            "error_rate": g["is_error"].mean(),
            "mean_dur": g["duration"].mean(),
        })

    n, a = summarize(norm), summarize(abn)
    if a.empty:
        return [Evidence(kind=EvidenceKind.TRACE, observation="No trace data.",
                         provenance=_prov(lake, inc, tool_call_id, "abnormal_traces.parquet", "traces"))]
    j = a.join(n, rsuffix="_norm", how="left").fillna(0.0)
    j["err_increase"] = j["error_rate"] - j.get("error_rate_norm", 0.0)
    j["lat_ratio"] = j["mean_dur"] / j.get("mean_dur_norm", j["mean_dur"]).replace(0, 1e-9)
    if service:
        j = j[j.index == service]
    j = j.sort_values(["err_increase", "lat_ratio"], ascending=False).head(top)
    rows = [{"service": idx, "requests": int(r.requests),
             "error_rate": round(float(r.error_rate), 3),
             "error_rate_increase": round(float(r.err_increase), 3),
             "latency_ratio_vs_normal": round(float(r.lat_ratio), 2)} for idx, r in j.iterrows()]
    obs = ("Services by error-rate increase: "
           + "; ".join(f"{x['service']} err+{x['error_rate_increase']:+.2f} lat x{x['latency_ratio_vs_normal']}"
                       for x in rows[:5])) if rows else "No trace anomalies."
    return [Evidence(kind=EvidenceKind.TRACE, observation=obs,
                     payload={"ranked": rows, "service_filter": service}, confidence=0.65,
                     provenance=_prov(lake, inc, tool_call_id, "abnormal_traces.parquet",
                                      f"trace error/latency service={service}"))]


# --------------------------------------------------------------------------- #
# query_logs
# --------------------------------------------------------------------------- #
def query_logs(lake, inc, tool_call_id, service: str | None = None, top: int = 8) -> list[Evidence]:
    abn = lake.read_table(inc.case_name, "abnormal_logs")
    if abn.empty:
        return [Evidence(kind=EvidenceKind.LOG, observation="No logs.",
                         provenance=_prov(lake, inc, tool_call_id, "abnormal_logs.parquet", "logs"))]
    df = abn.copy()
    df["sev"] = df["level"].astype(str).str.upper()
    bad = df[df["sev"].isin(["ERROR", "CRITICAL", "FATAL", "WARN", "WARNING"])]
    if service:
        bad = bad[bad["service_name"] == service]
    counts = bad.groupby("service_name").size().sort_values(ascending=False).head(top)
    samples = {s: bad[bad["service_name"] == s]["message"].astype(str).head(2).tolist()
               for s in counts.index}
    rows = [{"service": s, "error_log_count": int(c), "samples": samples[s]} for s, c in counts.items()]
    obs = ("Error/warn log volume by service: "
           + "; ".join(f"{x['service']}={x['error_log_count']}" for x in rows[:5])) if rows else "No error logs."
    return [Evidence(kind=EvidenceKind.LOG, observation=obs,
                     payload={"ranked": rows, "service_filter": service}, confidence=0.55,
                     provenance=_prov(lake, inc, tool_call_id, "abnormal_logs.parquet",
                                      f"error logs service={service}"))]


# --------------------------------------------------------------------------- #
# get_topology  (derived from NORMAL traces so a service that later goes silent
# still appears in the dependency graph; NOT from ground truth)
# --------------------------------------------------------------------------- #
def get_topology(lake, inc, tool_call_id) -> list[Evidence]:
    df = lake.read_table(inc.case_name, "normal_traces")
    edges: set[tuple[str, str]] = set()
    if not df.empty and {"span_id", "parent_span_id", "service_name"}.issubset(df.columns):
        svc = dict(zip(df["span_id"], df["service_name"]))
        for _, r in df.iterrows():
            caller = svc.get(r.get("parent_span_id"))
            callee = r["service_name"]
            if caller and callee and caller != callee:
                edges.add((caller, callee))
    edge_list = sorted([list(e) for e in edges])
    services = sorted({s for e in edges for s in e})
    obs = (f"Baseline service dependency graph ({len(services)} services, {len(edge_list)} edges; "
           f"caller->callee): " + "; ".join(f"{a}->{b}" for a, b in edge_list[:16])
           ) if edge_list else "No topology derivable."
    return [Evidence(kind=EvidenceKind.TOPOLOGY, observation=obs,
                     payload={"edges": edge_list, "services": services}, confidence=0.7,
                     provenance=_prov(lake, inc, tool_call_id, "normal_traces.parquet",
                                      "service dependency graph from normal-window trace parent/child"))]


# --------------------------------------------------------------------------- #
# detect_silent_services  (telemetry disappearance = failure or lost traffic)
# --------------------------------------------------------------------------- #
def detect_silent_services(lake, inc, tool_call_id, drop_threshold: float = 0.15) -> list[Evidence]:
    nt = lake.read_table(inc.case_name, "normal_traces")
    at = lake.read_table(inc.case_name, "abnormal_traces")
    nc = nt.groupby("service_name").size() if not nt.empty else {}
    ac = at.groupby("service_name").size() if not at.empty else {}
    dropped = []
    for s in (nc.index if hasattr(nc, "index") else []):
        n = int(nc[s]); a = int(ac.get(s, 0))
        if n >= 20 and a < drop_threshold * n:
            dropped.append({"service": s, "normal_spans": n, "abnormal_spans": a,
                            "drop_pct": round(1 - a / n, 3)})
    dropped.sort(key=lambda d: d["drop_pct"], reverse=True)
    obs = ("Services whose spans largely DISAPPEARED in the abnormal window (failure or lost "
           "upstream traffic): " + ", ".join(f"{d['service']} ({d['normal_spans']}->{d['abnormal_spans']})"
                                              for d in dropped)) if dropped else "No services went silent."
    return [Evidence(kind=EvidenceKind.TRACE, observation=obs, payload={"silent": dropped},
                     confidence=0.8,
                     provenance=_prov(lake, inc, tool_call_id, "normal_traces.parquet|abnormal_traces.parquet",
                                      "span-count disappearance normal vs abnormal"))]


# --------------------------------------------------------------------------- #
# pod_health  (deployment availability / readiness / restarts = PodFailure signature)
# --------------------------------------------------------------------------- #
def pod_health(lake, inc, tool_call_id) -> list[Evidence]:
    nm = lake.read_table(inc.case_name, "normal_metrics")
    am = lake.read_table(inc.case_name, "abnormal_metrics")

    def mbs(df, metric):
        d = df[df["metric"] == metric]
        return d.groupby("service_name")["value"].mean() if not d.empty else {}

    avail_a, desired_a = mbs(am, "k8s.deployment.available"), mbs(am, "k8s.deployment.desired")
    ready_a = mbs(am, "k8s.container.ready")
    rn, ra = mbs(nm, "k8s.container.restarts"), mbs(am, "k8s.container.restarts")
    failed = []
    idx = avail_a.index if hasattr(avail_a, "index") else []
    for s in idx:
        av = float(avail_a.get(s))
        des = float(desired_a.get(s, 1.0)) if hasattr(desired_a, "get") else 1.0
        if des and av < des:  # fewer pods available than desired => pod-level failure
            failed.append({"service": s, "available": round(av, 2), "desired": round(des, 2),
                           "ready": round(float(ready_a.get(s)), 2) if hasattr(ready_a, "get") and ready_a.get(s) is not None else None,
                           "restart_delta": round(float(ra.get(s, 0)) - float(rn.get(s, 0)), 2) if hasattr(ra, "get") else None})
    failed.sort(key=lambda f: f["available"])
    obs = ("Pod-level FAILURE signature (deployment.available < desired) in: "
           + ", ".join(f"{f['service']} (avail {f['available']}/{f['desired']})" for f in failed)
           ) if failed else "No pod-level failures detected (all deployments fully available)."
    return [Evidence(kind=EvidenceKind.METRIC, observation=obs, payload={"failed_pods": failed},
                     confidence=0.9,
                     provenance=_prov(lake, inc, tool_call_id, "abnormal_metrics.parquet",
                                      "deployment availability/readiness/restarts"))]


# --------------------------------------------------------------------------- #
# registry
# --------------------------------------------------------------------------- #
_SVC_PARAM = {"service": {"type": "string", "description": "optional service name filter"}}

TOOLS: dict[str, ToolSpec] = {
    "query_metrics": ToolSpec("query_metrics",
        "Compare metric values (abnormal vs normal) and rank the largest shifts, optionally for one service.",
        {"type": "object", "properties": _SVC_PARAM}, query_metrics, EvidenceKind.METRIC),
    "query_traces": ToolSpec("query_traces",
        "Rank services by error-rate increase and latency ratio (abnormal vs normal).",
        {"type": "object", "properties": _SVC_PARAM}, query_traces, EvidenceKind.TRACE),
    "query_logs": ToolSpec("query_logs",
        "Count error/warn log volume per service during the abnormal window, with samples.",
        {"type": "object", "properties": _SVC_PARAM}, query_logs, EvidenceKind.LOG),
    "get_topology": ToolSpec("get_topology",
        "Baseline service dependency graph (caller->callee) from normal-window traces; includes "
        "services that later go silent.",
        {"type": "object", "properties": {}}, get_topology, EvidenceKind.TOPOLOGY),
    "detect_silent_services": ToolSpec("detect_silent_services",
        "Find services whose telemetry (spans) largely disappeared in the abnormal window vs "
        "normal — a strong failure / lost-traffic signal.",
        {"type": "object", "properties": {}}, detect_silent_services, EvidenceKind.TRACE),
    "pod_health": ToolSpec("pod_health",
        "Per-service pod health: deployment available-vs-desired, container readiness and restart "
        "deltas. available<desired is the PodFailure signature and distinguishes a killed service "
        "(root) from one that merely lost traffic (cascaded victim).",
        {"type": "object", "properties": {}}, pod_health, EvidenceKind.METRIC),
}


def run_tool(name: str, lake: EvidenceLake, inc: Incident, tool_call_id: str, args: dict | None = None) -> list[Evidence]:
    if name not in TOOLS:
        raise KeyError(f"unknown tool {name}")
    args = {k: v for k, v in (args or {}).items() if v not in (None, "")}
    return TOOLS[name].fn(lake, inc, tool_call_id, **args)
