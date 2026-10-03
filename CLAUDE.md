# Deep-RCA — Project Rules (CLAUDE.md)

Deep-RCA is an experimental, long-running **autonomous root-cause investigation**
system built on Microsoft Azure. It investigates OpenRCA incidents using a
hypothesis-driven loop. It is **not** a chatbot.

This file is the contract every contributor (human or agent) must honor. The full
design lives in `docs/`. Status lives in `progress.md`. Acceptance tests live in
`tests.json`.

---

## Non-negotiable invariants

These are enforced by construction **and** by tests. A change that violates any of
them is a bug, no matter how convenient.

1. **Ground-truth isolation.** OpenRCA ground truth (ops-lite `root_services`,
   `chaos_types`, injection timing) lives only in the **offline evaluation plane**,
   in a storage account + Key Vault + managed identity that the Investigator and the
   in-loop Evaluator have **no grant to and no network path to**. Nothing under
   `src/deeprca/` may import from `eval/`. CI fails on violation.

2. **The ledger is the single source of truth.** The authoritative investigation
   state is the typed, persisted `Investigation` aggregate. **LLM conversation
   history is never authoritative** — it is an ephemeral per-step scratchpad.
   Dropping all conversation history must never lose investigation state.

3. **Two evaluation surfaces, only one sees ground truth.**
   - **In-loop `EvaluatorAgent` is blind** to ground truth. It critiques the
     investigation's internal quality and emits exactly one decision:
     `CONTINUE` | `CONCLUDE` | `ESCALATE`.
   - **The offline Evaluation Framework** is the only component with GT access. It
     scores a *frozen* final `Investigation`. Its output **never** flows back into a
     live investigation.

4. **Provenance is mandatory.** Every `Evidence` object carries provenance
   (tool_call_id, source_uri, query, retrieved_at, time_range). No provenance → not
   evidence.

5. **Every hypothesis tracks both sides.** Each `Hypothesis` carries
   `supporting_evidence[]` **and** `contradicting_evidence[]` and a
   `falsification_test`.

6. **Every root-cause conclusion carries a `CausalPath`** that is graph-valid
   (edges exist in the dependency topology) and temporally monotonic.

7. **The LLM only ever sees a projection.** Agents receive a deterministic,
   read-only *projection* of the ledger — never raw ground truth, never the
   `eval/` package.

---

## Separation of concerns (four stores, never merged)

| Store | Contains | Who reads | Who writes |
|---|---|---|---|
| **System knowledge** | ontology, KG, runbooks, SLOs | Investigator (read) | build pipeline |
| **Retrieved evidence** | telemetry pulled via tools | Investigator (read) | tool layer |
| **Investigation state** | the ledger (hypotheses, evidence, tool calls, causal path) | Investigator + blind Evaluator (via projection) | reducer only |
| **Benchmark ground truth** | ops-lite answers + timing | **offline eval only** | GT loader |

---

## Typed models (no untyped dicts crossing boundaries)

`Incident`, `Evidence`, `Hypothesis`, `Investigation`, `ToolCall`, `CausalPath`,
`Evaluation`, `Escalation`. Defined in `src/deeprca/models/`. Validated with
pydantic. Full schemas in `docs/architecture.md`.

---

## Tech + platform decisions (confirmed)

- **Language:** Python.
- **Cloud:** real Azure, region **East US** (`eastus`).
- **Models:** Azure AI **Foundry** project
  `https://rcadeeptestfoundary.services.ai.azure.com/api/projects/RCADeepTest`
  (subscription `2d2f7b83-f938-442c-8cd8-36a3d02596c1`, tenant
  `51d9d9f0-d948-441c-b4e8-9231c85029af`). MSDN / Visual Studio Enterprise — mind
  the spending cap.
- **Runtime agents:** Microsoft **Agent Framework**.
- **Long-running execution:** Agent Framework **Durable Extension** (Phase 5+).
- **Phase-1 footprint (default, pending final confirm):** leaner — ADLS Gen2
  lakehouse (OneLake-swap-ready) + Cosmos DB serverless + Foundry, to avoid Fabric
  capacity cost on MSDN. Fabric capacity introduced in Phase 2.

---

## How we work

- **Vertical slices.** Each phase is a thin end-to-end slice that runs and is tested.
- **No phase N+1 before phase N tests pass.** Phase 1 gates on `tests.json` green.
- **Keep `progress.md` current** after every meaningful change.
- **Secrets** via Key Vault + Managed Identity. Never commit secrets. Separate
  identities per plane (Investigator identity must not resolve the GT store).
- **Cost discipline** (MSDN): prefer serverless/consumption SKUs; tear down idle
  capacity; enforce token/step/cost budgets inside investigations.
- **Reproducibility:** pin model versions, seed sampling, keep the reducer pure and
  replayable.

## Repository map

```
src/deeprca/  models/ state/ evidence/ knowledge/ agents/ workflow/ projection/
eval/         ground_truth/ scorer.py harness.py      # OFFLINE — isolated
tests/        unit/ integration/ isolation/
docs/         architecture.md ontology.md evaluation.md
```

CI rule: `src/deeprca/**` importing `eval/**` is a hard failure.
