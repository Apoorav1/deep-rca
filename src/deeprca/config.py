"""Runtime configuration for the Investigator/Evaluator planes.

CRITICAL: this config exposes ONLY the evidence lake, the state store, and the model
endpoint. It deliberately has NO ground-truth fields. GT configuration lives solely in
``eval`` (eval/gt_store.py). Keeping GT out of this module is part of isolation-by-construction.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ModelConfig:
    endpoint: str
    api_version: str
    investigator_deployment: str
    evaluator_deployment: str


@dataclass(frozen=True)
class RuntimeConfig:
    evidence_account: str          # ADLS Gen2 account (evidence lake)
    evidence_filesystem: str
    state_account: str             # Blob account (ledger)
    state_container: str
    model: ModelConfig

    @staticmethod
    def from_env() -> "RuntimeConfig":
        g = os.environ.get
        return RuntimeConfig(
            evidence_account=g("DEEPRCA_EVIDENCE_ACCOUNT", ""),
            evidence_filesystem=g("DEEPRCA_EVIDENCE_FS", "telemetry"),
            state_account=g("DEEPRCA_STATE_ACCOUNT", ""),
            state_container=g("DEEPRCA_STATE_CONTAINER", "investigations"),
            model=ModelConfig(
                endpoint=g("DEEPRCA_MODEL_ENDPOINT", ""),
                api_version=g("DEEPRCA_MODEL_API_VERSION", "2024-10-21"),
                investigator_deployment=g("DEEPRCA_INVESTIGATOR_DEPLOYMENT", "gpt-4.1"),
                evaluator_deployment=g("DEEPRCA_EVALUATOR_DEPLOYMENT", "gpt-4.1"),
            ),
        )
