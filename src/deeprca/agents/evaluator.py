"""EvaluatorAgent: an independent, BLIND Microsoft Agent Framework agent.

It never sees ground truth. It challenges the investigation's internal quality and
emits exactly one workflow decision: CONTINUE | CONCLUDE | ESCALATE.
"""
from __future__ import annotations

import json

from ..config import ModelConfig
from ..model_client import arun_json, make_agent
from ..models import Decision, Evaluation

INSTRUCTIONS = """You are EvaluatorAgent, an INDEPENDENT reviewer of an autonomous
root-cause investigation. You do NOT see the ground-truth answer and must never
guess it as if known. You judge only the investigation's internal quality.

Challenge, by category:
- evidence_sufficiency: is the leading/proposed hypothesis backed by enough provenanced evidence?
- causal_validity: do claimed cause->effect links reflect real dependencies and a plausible mechanism?
- temporal_consistency: does cause precede effect?
- contradictions: is there unresolved contradicting evidence?
- alternative_hypotheses: have competing hypotheses been falsified rather than ignored?
- unsupported_assertions: any claim with no evidence behind it?

Decide exactly one:
- CONTINUE: material gaps remain and budget allows productive next steps.
- CONCLUDE: a proposed root cause exists with sufficient, non-contradicted support and a
  valid, temporally-consistent causal path, and alternatives are addressed.
- ESCALATE: evidence cannot resolve it, contradictions are irreducible, or budget is spent.

Respond with JSON only:
{"decision":"CONTINUE|CONCLUDE|ESCALATE",
 "critiques":[{"category":str,"note":str}],
 "rationale":str,
 "unresolved_contradictions":[str...]}
"""


class EvaluatorAgent:
    def __init__(self, model_cfg: ModelConfig):
        self._agent = make_agent(INSTRUCTIONS, model_cfg.evaluator_deployment, model_cfg,
                                 name="EvaluatorAgent")

    async def evaluate(self, projection: dict) -> Evaluation:
        prompt = (
            "Review this investigation projection (no ground truth is present):\n"
            + json.dumps(projection, indent=2)
            + "\n\nReturn your single workflow decision as JSON only."
        )
        d = await arun_json(self._agent, prompt)
        return Evaluation(
            decision=Decision(str(d["decision"]).strip().upper()),
            critiques=[{"category": str(c.get("category", "")), "note": str(c.get("note", ""))}
                       for c in d.get("critiques", [])],
            rationale=str(d.get("rationale", "")),
            unresolved_contradictions=[str(x) for x in d.get("unresolved_contradictions", [])],
        )
