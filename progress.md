# Deep-RCA — Progress

Living status log. Update after every meaningful change.

## Current state: PHASE 3 COMPLETE ✅ — accuracy solved (24/24 tests green)

### Phase 3 (knowledge plane, accuracy) — DONE 2026-10-03, no new Azure cost
Added `src/deeprca/knowledge/` (fault signatures + localization heuristic = ontology-as-code,
injected into the projection, GT-free). New Evidence tools: `pod_health` (deployment
available<desired = PodFailure signature — the decisive signal), `detect_silent_services`
(span disappearance), topology now from the NORMAL baseline (silent services stay visible),
de-noised `query_metrics`. Investigator prompt now applies "root = pod-level failure; a silent
service with pods still available is a CASCADED victim, not the root".

Result over 3 hs PodFailure incidents (eval/harness.py): **localization_exact 1.0, fault_type 1.0,
causal_path_valid 1.0, isolation_clean 1.0** — up from the Phase-1 miss.
- batch-...SWG9FS -> geo,profile (exact)
- batch-...GPT3   -> profile,recommendation (exact)
- batch-...QJT3A  -> profile,search (exact)
tests.json Phase-3 gate GREEN. Causal-path builder now synthesizes missing nodes + backfills
edge provenance from collected evidence.

Batch harness: eval/harness.py <case...>. Additional incidents loaded into Azure for the eval.

---

## PHASE 1 COMPLETE ✅ — 20/20 tests green (incl. live Azure integration)

Phase-1 vertical slice runs end-to-end on Azure: loads one incident (GT hidden),
exposes telemetry via 4 tools, Investigator (Agent Framework / Foundry gpt-4.1) forms
competing hypotheses, makes 3+ evidence tool calls, maintains a persistent Blob-backed
ledger, proposes a root cause with a valid causal path, blind Evaluator decides
CONTINUE/CONCLUDE/ESCALATE, and the OFFLINE scorer compares to GT. Runtime isolation
scan: zero GT markers leaked. `tests.json` gate = GREEN.

Last run: proposed `search`/`AppBug`; GT is `geo`+`profile`/`PodFailure` (localization miss).
EXPECTED: faulted pods were killed so their telemetry is MISSING; a naive investigator
blames the loudest erroring caller. Reasoning about absent telemetry + topology is the
job of Phase 3 (knowledge graph/ontology) and Phase 4 (sharper Evaluator). Phase-1
acceptance = working autonomous pipeline, not accuracy.

Artifacts: eval/scorecards/<case>.json. Runner: infra/run_phase1.py.
Live demo (step-by-step narration + GT reveal): infra/demo_phase1.py
  (PYTHONIOENCODING=utf-8 PYTHONPATH="src;." .venv/Scripts/python infra/demo_phase1.py).
Key gotchas recorded: api_version must be "preview" (Responses API); single asyncio
event loop for all agent calls; MSYS_NO_PATHCONV for az --scope.

### Next (Phase 2 — do NOT start until approved): real Evidence Plane on Fabric/OneLake,
Cosmos for state, richer tool suite. Then Phase 3 knowledge plane (the accuracy lever).

---

## Phase 1 — pure-Python core (done 10/10) + Azure provisioning + agents

### Phase 1 progress (2026-10-03)
- Repo scaffold + `pyproject.toml` + venv (`.venv`) — pydantic/pytest/pyarrow/pandas.
- Typed models (`src/deeprca/models/core.py`): Incident (no GT fields, extra=forbid),
  Evidence (mandatory Provenance), Hypothesis (both sides + falsification_test),
  ToolCall, CausalPath (graph-valid + temporally-monotonic checks), Investigation
  (ledger, versioned), Evaluation/Escalation (blind), enums + state machine.
- Pure reducer + typed actions (`src/deeprca/state/`) — only ledger mutator; versioned.
- Offline GT loader isolated in `eval/ground_truth/` (reads label/injection/causal_graph).
- Isolation import-ban test (`tests/isolation/`) + model/reducer unit tests.
- **pytest: 10 passed.** tests.json: p1-evidence-provenance=pass,
  p1-hypothesis-both-sides=pass, p1-hide-ground-truth=static-pass.

### Azure provisioning — DONE (2026-10-03, leaner footprint, eastus, RG=RCADeepTest)
Resource names in `infra/azure-resources.env`.
- Evidence lake (ADLS Gen2) `deeprcaevidd41408`, filesystem `telemetry`.
- Isolated GT store `deeprcagtd41408`, container `ground-truth`.
- State store (Blob ledger) `deeprcastated41408`, container `investigations`.
- Identities: `deeprca-investigator-mi` (6e2691a4…), `deeprca-eval-mi` (ea4acd4e…).
- RBAC: investigator → evidence(Reader)+state(Contributor)+Foundry(OpenAI User);
  eval → Foundry(OpenAI User)+GT(Reader). **Verified: investigator has ZERO roles on GT store.**
- Foundry `RCADeepTestFoundary` / deployment `gpt-4.1` (pre-existing).

Adaptations (vs original plan):
- **Cosmos → Azure Blob** for Phase-1 ledger (East US Cosmos region-access restricted on MSDN).
  Cosmos deferred to Phase 2.
- **App Insights deferred to Phase 5** (not needed for Phase-1 acceptance).
- Git-Bash gotcha: `--scope /subscriptions/...` gets path-mangled by MSYS; use
  `MSYS_NO_PATHCONV=1` for az RBAC commands.

Local-execution isolation note: Phase-1 runs locally use the dev az credential, so runtime
isolation is enforced by CONSTRUCTION (the Investigator storage client is never handed the GT
account URL/credential) + the import-ban + a runtime GT-content scan. Production isolation is the
MI RBAC above (verified). Negative-access test (investigator identity DENIED on GT) = Phase 7.

### Next: data load (1 incident) → evidence tools → Investigator+Evaluator (Agent Framework/Foundry) → offline scorer → run tests.json.

---

## Phase 0 (design docs) — DONE

**Date:** 2026-10-03

### Done
- Inspected `anon-ops/ops-lite` (455 scenarios; scenario GT metadata, not telemetry).
- Agreed design decisions:
  - Language: **Python**
  - Cloud: **real Azure**, region **East US**
  - Models: **Azure AI Foundry** project `RCADeepTest`
    (`https://rcadeeptestfoundary.services.ai.azure.com/api/projects/RCADeepTest`)
  - Subscription `2d2f7b83-f938-442c-8cd8-36a3d02596c1` (MSDN / Visual Studio Enterprise),
    tenant `51d9d9f0-d948-441c-b4e8-9231c85029af`
  - Telemetry: **user will supply** OpenRCA raw telemetry (schema/location TBD)
  - Runtime agents: **Microsoft Agent Framework**; durable via Durable Extension (Phase 5)
- Authored Phase 0 docs: `CLAUDE.md`, `docs/architecture.md`, `docs/ontology.md`,
  `docs/evaluation.md`, `progress.md`, `tests.json`.

### Azure facts (discovered 2026-10-03, auth live)
- Resource group **`RCADeepTest`** exists in **eastus**.
- Foundry account **`RCADeepTestFoundary`** (AIServices), eastus.
- Model deployment: **`gpt-4.1`** (v2025-04-14, GlobalStandard, cap 1450) — the only one.
  Phase 1 runs Investigator + blind Evaluator on it (independent prompts/config).
  Phase 4 recommendation: add a 2nd/different model for the Evaluator (reduce correlated errors).

### Data contract (RESOLVED 2026-10-03 — ops-lite = "OpenRCA 2.0")
Per case: `cases/<name>/` where `<name>` = ops-lite `name` (the join key).
- **Visible (Evidence Plane):**
  - `env.json` → `NAMESPACE`, `NORMAL_START/END`, `ABNORMAL_START/END` (epoch secs). Incident window.
  - `normal_*` vs `abnormal_*` parquet for `metrics`, `metrics_histogram`, `metrics_sum`, `logs`, `traces`.
  - Telemetry schemas (OpenTelemetry-style):
    - metrics: time, metric, value, service_name, attr.k8s.*, attr.source_workload, attr.destination_workload
    - traces: time, trace_id, span_id, parent_span_id, span_name, attr.span_kind, service_name,
      duration, attr.status_code, attr.k8s.*, attr.http.*
    - logs: time, trace_id, span_id, level, service_name, message, attr.k8s.*, attr.template_id, attr.log_template
  - **Topology is DERIVED from telemetry** (trace parent/child across services; metric source/destination
    workloads) — the Investigator never reads label.json service_edges.
- **Ground truth (ISOLATE — offline only):** `label.json` (faults=answer), `injection.json`
  (injected faults + times), `causal_graph.json` (propagation graph), AND the ops-lite parquet
  columns `root_services`/`chaos_types`/`n_injected_faults`/`n_required_faults` (GT summary).
  → Investigator loads Incident from `env.json` + `system` ONLY; never reads the ops-lite row.

### Open blockers (gate Phase 1 provisioning/code)
- ⏳ **Footprint choice**: leaner Phase-1 (ADLS + Cosmos serverless, no Fabric capacity)
  vs full-Fabric-now. Default assumed: **leaner**. (Only remaining blocker.)
- ⏳ **Isolation Y/N**: boundary above is self-evident from the data; awaiting explicit OK.

### Next actions (once unblocked)
1. Re-auth; auto-discover Foundry region + deployments; confirm footprint.
2. Scaffold repo (`pyproject.toml`, `src/deeprca/`, `eval/`, `tests/`) + CI import-ban rule.
3. Provision Phase-1 Azure (East US): Foundry wiring, ADLS lakehouse, Cosmos serverless,
   isolated GT storage + KV + MIs, App Insights.
4. Implement typed models → ledger+reducer → 3 telemetry tools → investigator →
   offline scorer → isolation tests.
5. Run Phase-1 acceptance (`tests.json`). Do not start Phase 2 until green.

## Phase log
- **Phase 0** — design docs: IN PROGRESS.
- **Phase 1** — thin vertical slice: NOT STARTED.
- **Phases 2–7** — NOT STARTED.
