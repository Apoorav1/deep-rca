"""Knowledge plane (Phase 3): system knowledge the Investigator reasons WITH.

This is domain knowledge, not ground truth — it contains no incident answers. It
encodes fault signatures and a localization heuristic derived from the ontology
(docs/ontology.md). In later phases this is materialized in Fabric Ontology + a
knowledge graph + Foundry IQ retrieval; here it is curated in-process.
"""
from __future__ import annotations

FAULT_SIGNATURES = {
    "PodFailure": {
        "telemetry_pattern": (
            "The targeted service STOPS emitting spans/metrics (its span count drops to ~0) and "
            "k8s.deployment.available falls below k8s.deployment.desired (pods unavailable); "
            "container.ready drops and/or restarts increase. Its CALLERS show errors/latency."
        ),
        "decisive_signal": "pod_health: deployment.available < desired for the failed service.",
    },
    "CPUStress": {
        "telemetry_pattern": "Service keeps emitting telemetry but cpu.usage saturates and latency rises sharply; errors may rise. Pods stay available.",
        "decisive_signal": "query_metrics: large cpu.usage increase with latency ratio >> 1, deployment still available.",
    },
    "NetworkDelay": {
        "telemetry_pattern": "Callers of the affected service see large latency increases and timeouts; the service itself still emits telemetry and pods stay available.",
        "decisive_signal": "query_traces: latency ratio >> 1 on edges into the service, no pod failure.",
    },
    "ConfigError/AppBug": {
        "telemetry_pattern": "Service keeps emitting telemetry and pods stay available, but error_rate rises and error logs spike.",
        "decisive_signal": "query_logs + query_traces: elevated errors while pods remain available and spans continue.",
    },
}

LOCALIZATION_HEURISTIC = (
    "Localize to the DEEPEST independently-failed node, not the loudest erroring caller. "
    "A service that is merely erroring or slow is often a VICTIM of a failed dependency. "
    "Steps: (1) get_topology for the dependency graph; (2) detect_silent_services; (3) pod_health. "
    "A service with pod-level failure (deployment.available < desired) is a ROOT cause. "
    "A service that went silent but whose deployment stayed fully available is usually a CASCADED "
    "victim (it lost upstream traffic), NOT the root. When several services fail, report those with "
    "the pod-level failure signature as the root cause(s), and map propagation along the dependency "
    "graph from each root to the observed symptoms."
)


def domain_knowledge() -> dict:
    """Compact knowledge payload injected into the agent projection (GT-free)."""
    return {
        "fault_signatures": FAULT_SIGNATURES,
        "localization_heuristic": LOCALIZATION_HEURISTIC,
    }
