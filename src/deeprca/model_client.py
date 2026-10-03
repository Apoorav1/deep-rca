"""Microsoft Agent Framework chat-client + agent factory for Deep-RCA.

Both the Investigator and the (blind) Evaluator are Agent Framework ``Agent`` objects
backed by an ``OpenAIChatClient`` pointed at the Azure/Foundry endpoint with AAD.
"""
from __future__ import annotations

import json
import re
from typing import Any

from azure.identity import DefaultAzureCredential

from .config import ModelConfig


def make_agent(instructions: str, deployment: str, model_cfg: ModelConfig, name: str):
    from agent_framework import Agent
    from agent_framework.openai import OpenAIChatClient

    client = OpenAIChatClient(
        model=deployment,
        azure_endpoint=model_cfg.endpoint,
        api_version=model_cfg.api_version,
        credential=DefaultAzureCredential(),
    )
    return Agent(client, instructions=instructions, name=name)


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", text).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"no JSON object in model output: {text[:200]!r}")
    return json.loads(text[start : end + 1])


async def arun_json(agent, prompt: str) -> dict[str, Any]:
    """Run an Agent Framework agent and parse a JSON object reply.

    Async so the whole investigation shares ONE event loop (the Agent Framework chat
    client binds its async HTTP pool to the running loop; a loop-per-call closes it).
    """
    resp = await agent.run(prompt)
    return _extract_json(resp.text)
