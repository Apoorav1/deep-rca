# Deep-RCA — Architecture

Status: design approved for Phase 0. Phase 1 provisioning pending re-auth + inputs.

## 1. Purpose

Autonomous, multi-step, **hypothesis-driven** root-cause investigation of OpenRCA
incidents. Not a chatbot. The system observes an incident, generates competing
hypotheses, gathers falsifying evidence through tools, maintains a persistent
hypothesis ledger, proposes a root cause with a causal path, and submits it to an
independent evaluator that decides `CONTINUE` / `CONCLUDE` / `ESCALATE`.

## 2. The two foundational principles

### 2.1 Ledger-as-truth (the LLM is a stateless step function)

The authoritative state is the typed, persisted `Investigation` aggregate. Each loop
step:

1. Build a deterministic **projection** (read-only view) from the ledger.
2. Call an agent → it returns a **typed action** (not prose state).
3. A **pure reducer** applies the action → next ledger version.
4. **Checkpoint** the ledger.

Conversation history is a per-step scratchpad and is discarded. This makes the loop
replayable, testable, and durable, and prevents "the model forgot" from corrupting
state.

### 2.2 Two evaluation surfaces — only one sees ground truth

| | In-loop `EvaluatorAgent` | Offline Evaluation Framework |
|---|---|---|
| Sees ground truth? | **No** | Yes (only this) |
| Runs | inside the live workflow | after freeze, offline |
| Judges | internal quality: evidence sufficiency, causal/temporal validity, contradictions, alternatives, unsupported assertions | correctness vs GT (localization, fault-type, path validity) |
| Output | one decision: `CONTINUE`/`CONCLUDE`/`ESCALATE` | benchmark metrics |
| Feeds back into loop? | yes (drives transition) | **never** |

This resolves the apparent tension in the spec: the Evaluator is independent and
in-loop, yet ground truth stays exclusively in the offline framework.

## 3. Planes (strict separation)

```
                 CONTROL PLANE  (Agent Framework durable workflow)
                 Investigator ⇄ reducer ⇄ blind Evaluator ⇄ HITL
                      │ reads projection        │ typed action
        ┌─────────────┼──────────────┬──────────┘
        ▼             ▼              ▼
 KNOWLEDGE PLANE  INVESTIGATION   EVIDENCE PLANE
 ontology/KG/     STATE (ledger,  telemetry tools only
 Foundry IQ       Cosmos)         (ADLS→Fabric/OneLake)
 (read-only)      (reducer-write) (read-only)
        │
        ▼ frozen Investigation (no GT inside)
 ╔═══════════════════════════════════════════╗
 ║ OFFLINE EVAL PLANE (air-gapped)            ║
 ║ GT store (ops-lite) + scorer → metrics     ║
 ╚═══════════════════════════════════════════╝
```

The Investigator tool layer holds credentials for Evidence + Knowledge planes only.
It has no binding — hidden or read-only — to the GT store.

## 4. Repository structure

```
deep-rca/
  pyproject.toml  CLAUDE.md  progress.md  tests.json
  docs/ architecture.md ontology.md evaluation.md
  src/deeprca/
    models/       incident, evidence, hypothesis, investigation,
                  toolcall, causalpath, evaluation, escalation
    state/        ledger store + pure reducers + checkpointing
    evidence/     Evidence Plane: tools + data adapters
                    local_parquet_adapter (dev) · adls_adapter · fabric_adapter
    knowledge/    ontology, KG, retrieval (Foundry IQ / Azure AI Search)
    agents/       investigator.py · evaluator.py (blind)
    projection/   ledger → agent-context view (ONLY thing the LLM sees)
    workflow/     Agent Framework workflow graph + durable wiring
  eval/           ground_truth/ (imported ONLY here) · scorer.py · harness.py
  tests/          unit/ integration/ isolation/
```

CI: `src/deeprca/**` may not import `eval/**`; `eval/ground_truth` importable only
within `eval/`.

## 5. Typed data model

All pydantic. Boundaries never pass untyped dicts.

- **Incident** — `id`, `system`, `window{start,end}`, `symptoms[]`,
  `affected_slos[]`. *No root-cause fields.*
- **Evidence** — `id`, `kind{metric|log|trace|topology|deploy|config}`, `payload`,
  **`provenance{tool_call_id, source_uri, query, retrieved_at, time_range}`**
  (non-nullable), `observation`, `confidence`.
- **Hypothesis** — `id`, `statement`, `suspected_service`, `suspected_fault_type`,
  `status{proposed|supported|weakened|refuted}`, `supporting_evidence[]`,
  `contradicting_evidence[]`, `falsification_test`, `posterior`.
- **ToolCall** — `id`, `tool`, `args`, `result_evidence_ids[]`, `started`, `ended`,
  `cost`, `status`.
- **CausalPath** — `nodes[]{entity, fault_or_effect, timestamp}`,
  `edges[]{from, to, mechanism, evidence_ids[]}`; graph-valid + temporally monotonic.
- **Investigation** (aggregate root) — `id`, `incident_id`, `state`, `hypotheses[]`,
  `evidence_store[]`, `tool_calls[]`, `proposed_root_cause?{CausalPath, confidence}`,
  `step`, `budget`, `evaluations[]`, `escalation?`.
- **Evaluation** — `decision{CONTINUE|CONCLUDE|ESCALATE}`, `critiques[]` (tagged by
  rubric category), `rationale`, `unresolved_contradictions[]`. **No GT.**
- **Escalation** — `reason`, `open_questions[]`, `state_snapshot_ref`,
  `suggested_human_actions[]`.

## 5a. Evidence-Plane data contract (OpenRCA 2.0 / ops-lite)

Each incident is a case directory `cases/<name>/` (`<name>` = ops-lite `name` = join key).

**Visible telemetry** (baseline `normal_*` vs incident `abnormal_*`), OpenTelemetry-style:

- `metrics`: `time, metric, value, service_name, attr.k8s.{node,namespace,pod,container,…},
  attr.source_workload, attr.destination_workload`
- `traces`: `time, trace_id, span_id, parent_span_id, span_name, attr.span_kind, service_name,
  duration, attr.status_code, attr.k8s.*, attr.http.*`
- `logs`: `time, trace_id, span_id, level, service_name, message, attr.k8s.*,
  attr.template_id, attr.log_template`
- `env.json`: `NAMESPACE`, `NORMAL_START/END`, `ABNORMAL_START/END` (epoch secs) → incident window.

**Topology is derived from telemetry** (trace parent/child across `service_name`; metric
`source_workload`→`destination_workload`), not read from ground truth.

**Phase-1 Evidence-Plane tools** (≥3 required): `query_metrics(service?,metric?,window)`,
`query_traces(service?,status?,window)`, `query_logs(service?,level?,window)`, and
`get_topology(window)` (derived). Each returns `Evidence` with mandatory provenance.

**Ground truth (isolated, offline only):** `label.json`, `injection.json`,
`causal_graph.json`, **and** the ops-lite parquet GT columns
(`root_services`, `chaos_types`, `n_injected_faults`, `n_required_faults`). The Investigator
builds its `Incident` from `env.json` + `system` only and never reads the ops-lite row.

## 6. Agent state model

- Authoritative = `Investigation` ledger (Cosmos, checkpointed).
- Projection = deterministic read-only view: active hypotheses + their evidence,
  recent tool results (bounded/summarized), open contradictions, remaining budget.
- Agent output = typed action: `ProposeHypothesis`, `RequestEvidence(tool,args)`,
  `UpdateLedger(links)`, `ProposeRootCause(CausalPath)`.
- Reducer = pure function `(ledger, action) -> ledger`. Testable + replayable.

## 7. Workflow / state machine

```
INITIALIZED → OBSERVING → HYPOTHESIZING → EVIDENCE_PLANNING
  → COLLECTING → LEDGER_UPDATE → EVALUATION
      decision CONTINUE → (budget?) HYPOTHESIZING | ESCALATED
      decision CONCLUDE → PROPOSE_ROOT_CAUSE → EVALUATION(final) → CONCLUDED
      decision ESCALATE → ESCALATED (HITL)
  terminal: CONCLUDED | ESCALATED | BUDGET_EXHAUSTED
```

Implemented as an Agent Framework workflow graph (executors = states, typed edges =
transitions). Each iteration = one durable checkpoint of the ledger (Durable
Extension, Phase 5), enabling pause-for-human and crash-resume.

## 8. Azure components by phase

| Concern | Service | Phase |
|---|---|---|
| Models | Azure AI Foundry (existing project) | 1 |
| Evidence lake | ADLS Gen2 (OneLake-swap-ready) → Fabric/OneLake | 1 → 2 |
| State store | Cosmos DB serverless | 1 |
| GT isolation | separate Storage + Key Vault + distinct MIs | 1 |
| Observability | Application Insights + OpenTelemetry | 1 |
| Knowledge retrieval | Foundry IQ / Azure AI Search | 3 |
| Ontology | Fabric Ontology | 3 |
| Knowledge graph | Azure AI Search / Cosmos Gremlin | 3 |
| Durable execution | Agent Framework Durable Extension + Durable Task Scheduler | 5 |
| Agent hosting | Azure Container Apps | 5 |

## 9. Phased plan (summary; see §7 of the approved design)

1. **Thin slice** — one incident, GT hidden, ≥3 tool calls, persistent ledger,
   propose root cause, offline compare. Real Azure (leaner footprint).
2. **Real Evidence Plane** on Fabric/OneLake + full tool suite.
3. **Knowledge Plane** — ontology + Foundry IQ + KG.
4. **Rigorous blind Evaluator** — falsification + decision policy.
5. **Durable long-running + HITL** via Durable Extension.
6. **Full benchmark scale** (all 455 scenarios) + batch harness.
7. **Hardening** — GT-isolation red-team, cost/safety, reproducibility.

## 10. Major risks

GT leakage (highest) · LLM-memory-as-state · product/API churn (Agent Framework
Durable, Foundry IQ, Fabric Ontology) · correlation≠causation · telemetry
volume/cost · non-determinism · evaluator circularity · MSDN spending cap ·
raw-telemetry availability/shape.
