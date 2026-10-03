# Deep-RCA — Evaluation Methodology

Two evaluation surfaces. Keep them straight — conflating them breaks the core
experimental constraint.

## A. In-loop `EvaluatorAgent` (BLIND — no ground truth)

Runs inside the live workflow. Sees only the same **projection** the Investigator
sees. Judges the investigation's *internal* quality and emits exactly one decision.

### Challenge rubric (each critique tagged with a category)

1. **Evidence sufficiency** — is the proposed/leading hypothesis backed by enough
   provenanced evidence, or is it assertion?
2. **Causal validity** — do claimed cause→effect links correspond to real
   dependency edges and a plausible mechanism?
3. **Temporal consistency** — do timestamps order cause before effect?
4. **Contradictions** — is there unresolved contradicting evidence?
5. **Alternative hypotheses** — have competing hypotheses been falsified or just
   ignored?
6. **Unsupported assertions** — claims with no evidence id behind them.

### Decision policy

- `CONTINUE` — material gaps remain and budget allows productive next steps.
- `CONCLUDE` — a hypothesis has sufficient, non-contradicted support with a valid,
  temporally-consistent causal path, and alternatives are addressed.
- `ESCALATE` — evidence cannot resolve the question (needed signal unavailable),
  contradictions are irreducible, or budget is exhausted without convergence.

Output = `Evaluation{decision, critiques[], rationale, unresolved_contradictions[]}`.
**Never contains ground truth.**

## B. Offline Evaluation Framework (the ONLY GT consumer)

Runs **after** the investigation is frozen. Imports the GT loader (`eval/ground_truth`).
Consumes a frozen `Investigation` (which contains no GT) + the GT triple. Produces
benchmark metrics. **Results never return to a live investigation.**

### Correctness metrics (vs ops-lite GT)

| Metric | Definition |
|---|---|
| **Localization accuracy** | each GT `root_service` is the origin/leaf of the proposed `CausalPath` (exact) |
| **Localization top-k** | GT `root_service` appears among top-k suspected services |
| **Fault-type accuracy** | proposed fault type matches GT `chaos_types` |
| **Multi-fault recall** | fraction of GT `n_required_faults` localized |
| **Causal-path validity** | every proposed edge exists in topology + is temporally monotonic |
| **Temporal alignment** | proposed fault time within tolerance of GT injection time |

### Process / quality metrics (no GT needed)

| Metric | Definition |
|---|---|
| Evidence sufficiency | proposed cause has ≥1 provenanced, non-contradicted support |
| Hypotheses falsified | count moved to `refuted` with contradicting evidence |
| Contradiction resolution | fraction of raised contradictions resolved |
| Steps-to-solution | workflow iterations to CONCLUDE |
| Tool efficiency | useful evidence per tool call; total cost/tokens |
| Escalation precision/recall | ESCALATE vs incidents genuinely unsolvable from available evidence |

### Isolation assertions (run on EVERY evaluation)

1. **Static:** import-graph check — no `src/deeprca/**` → `eval/**` edge.
2. **Runtime:** scan the Investigator projection, tool results, and final ledger for
   any GT value (`root_services`, `chaos_types`, injection timing). Any hit = test
   failure.
3. **Identity:** the Investigator's managed identity cannot resolve the GT store
   (negative-access test in Phase 7; asserted logically from Phase 1).

## Reporting

Per-incident scorecard + aggregate (Phase 6) with per-system (`hs`/`ts`) breakdown.
Reproducibility: pinned model version, fixed seeds, replayable reducer; every score
reproducible from the frozen `Investigation` + GT.

## Phase-1 evaluation scope

Single incident. Produce: localization (exact + top-k), fault-type accuracy,
causal-path validity, plus the isolation assertions. Pass criteria encoded in
`tests.json`.
