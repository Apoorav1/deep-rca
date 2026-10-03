"""InvestigatorAgent: a Microsoft Agent Framework agent that, given a read-only
projection of the ledger, emits exactly ONE typed next action.

It never sees ground truth. It never mutates the ledger directly — the reducer does.
"""
from __future__ import annotations

import json

from ..config import ModelConfig
from ..model_client import arun_json, make_agent

INSTRUCTIONS = """You are InvestigatorAgent in an autonomous root-cause investigation
of a microservice incident. You are rigorous, hypothesis-driven, and skeptical. You
reason from telemetry evidence only — you are NOT told the answer.

Method: observe -> form competing hypotheses -> decide what evidence would FALSIFY each
-> call a tool to gather it -> link evidence (supporting/contradicting) -> reject or
strengthen hypotheses -> only then propose a root cause with a causal path.

Key domain insight: a service hit by PodFailure often STOPS emitting spans/metrics
(its data goes missing) while its callers show errors/latency. Missing telemetry from a
dependency is itself strong evidence. Topology is derived from traces and may omit a
fully-failed service — reason about who depends on the silent/erroring service.

Always respond with a SINGLE JSON object, no prose, matching one of:
{"action":"propose_hypothesis","statement":str,"falsification_test":str,"suspected_service":str,"suspected_fault_type":str}
{"action":"request_evidence","tool":str,"args":{...}}
{"action":"link_evidence","hypothesis_id":str,"supporting":[evidence_id...],"contradicting":[evidence_id...],"new_status":"proposed|supported|weakened|refuted"}
{"action":"propose_root_cause","root_services":[str...],"fault_type":str,"rationale":str,"confidence":0..1,
 "causal_path":{"nodes":[{"entity":str,"fault_or_effect":str,"timestamp":iso8601}],
                "edges":[{"source":str,"target":str,"mechanism":str,"evidence_ids":[str...]}]}}

Rules: form at least TWO competing hypotheses before gathering evidence. Make at least
THREE evidence-gathering tool calls across the investigation. Do not propose a root
cause until hypotheses are backed by linked evidence. Entities in causal_path nodes
should look like "service|<name>". Use evidence_ids that exist in the projection.
"""


class InvestigatorAgent:
    def __init__(self, model_cfg: ModelConfig):
        self._agent = make_agent(INSTRUCTIONS, model_cfg.investigator_deployment, model_cfg,
                                 name="InvestigatorAgent")

    async def decide(self, projection: dict, nudge: str = "") -> dict:
        prompt = (
            "Current investigation state (projection):\n"
            + json.dumps(projection, indent=2)
            + ("\n\nGUIDANCE: " + nudge if nudge else "")
            + "\n\nChoose the single best next action. Respond with JSON only."
        )
        return await arun_json(self._agent, prompt)
