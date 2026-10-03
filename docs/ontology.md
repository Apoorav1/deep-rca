# Deep-RCA — Domain Ontology

The ontology is **system knowledge** (the Knowledge Plane). It lets the Investigator
reason about *plausible fault propagation* without ever being told the answer. In
Phase 3 it is materialized as a Fabric Ontology item and a knowledge graph; in
Phase 1 it is an in-process typed graph built from topology data.

It is grounded in the `anon-ops/ops-lite` dataset we inspected (455 scenarios,
systems `hs` ≈ hotel-reservation, `ts` ≈ train-ticket; chaos such as `PodFailure`).

## Entities

| Entity | Key properties | Notes |
|---|---|---|
| `System` | id, name (`hs`,`ts`,…) | the target microservice system |
| `Service` | id, name, system | unit of deployment/logic |
| `Pod` | id, service, node | running replica |
| `Node` / `Host` | id, zone | compute host |
| `Deployment` | id, service, version, at | rollout event |
| `ConfigChange` | id, target, at, diff | config mutation |
| `Metric` | id, service, name, unit | e.g. latency_p99, error_rate, cpu |
| `LogStream` | id, service, level | structured logs |
| `TraceSpan` | id, trace_id, service, op, start, dur, status | distributed trace span |
| `FaultType` | name | `PodFailure`, `CPUStress`, `NetworkDelay`, … |
| `Incident` | id, system, window, symptoms | the thing under investigation |
| `SLO` | id, service, objective | breach defines a symptom |
| `Alert` | id, source, at | fired signal |

## Relationships

| Relation | From → To | Meaning |
|---|---|---|
| `DEPENDS_ON` | Service → Service | call/data dependency (the topology graph) |
| `RUNS` | Pod → Service | pod hosts a service replica |
| `SCHEDULED_ON` | Pod → Node | placement |
| `MEASURES` | Metric → Service | metric observes a service |
| `EMITS` | Service → LogStream / TraceSpan | observability output |
| `AFFECTS` | FaultType → Service / Pod | a fault acts on a target |
| `PROPAGATES_TO` | Service → Service | **causal** symptom spread (derived) |
| `MANIFESTS_AS` | Incident → Symptom | observable effect |
| `VIOLATES` | Symptom → SLO | breach linkage |

Topology properties used by scoring and reasoning: `n_service_edges` (count of
`DEPENDS_ON` edges) and `longest_service_path` (dependency depth) — both present in
ops-lite and both consumable by the Investigator (they are structure, not answers).

## Dataset → ontology mapping

| ops-lite field | Maps to | Visibility |
|---|---|---|
| `system` | `System` | Evidence/Knowledge (visible) |
| topology (`n_service_edges`, `longest_service_path`) | `DEPENDS_ON` graph props | visible |
| `root_services` | `Service` targeted by injected fault | **GROUND TRUTH — offline only** |
| `chaos_types` | `FaultType` injected | **GROUND TRUTH — offline only** |
| `n_injected_faults`, `n_required_faults` | cardinality of the answer | **GROUND TRUTH — offline only** |
| injection timing | fault timestamp | **GROUND TRUTH — offline only** |

The visible half (system + dependency topology + telemetry) is what the Investigator
reasons over. The `(root_services, chaos_types, timing)` triple **is** the answer and
lives only in the offline evaluation plane.

## How the ontology is used

- **Hypothesis generation:** candidate root services are suspected along
  `DEPENDS_ON` / `PROPAGATES_TO` paths that could explain observed symptoms.
- **Causal-path validation:** a proposed `CausalPath` edge must correspond to a real
  `DEPENDS_ON` (or justified `PROPAGATES_TO`) relation and respect temporal order.
- **Evidence planning:** the ontology tells the Investigator which `Metric` /
  `TraceSpan` / `LogStream` to pull next to falsify a hypothesis.

## Fabric Ontology materialization (Phase 3)

Entities/relations above become the Fabric Ontology schema; instances are populated
from OneLake topology + telemetry tables; the KG (Azure AI Search / Cosmos Gremlin)
indexes it for retrieval by the Investigator's knowledge tools. Exact Fabric Ontology
and Foundry IQ APIs to be verified against current product docs at Phase 3 (tracked
as a risk).
