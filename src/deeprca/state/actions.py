"""Typed actions an agent may emit. Agents never mutate the ledger directly;
they return one of these and the reducer applies it. (docs/architecture.md s6)
"""
from __future__ import annotations

from typing import Any, Literal, Union

from pydantic import BaseModel, Field

from ..models import (
    Escalation,
    Evaluation,
    Evidence,
    HypothesisStatus,
    InvestigationState,
    ProposedRootCause,
)


class ProposeHypothesisAction(BaseModel):
    kind: Literal["propose_hypothesis"] = "propose_hypothesis"
    statement: str
    falsification_test: str
    suspected_service: str | None = None
    suspected_fault_type: str | None = None


class RequestEvidence(BaseModel):
    kind: Literal["request_evidence"] = "request_evidence"
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)


class RecordEvidence(BaseModel):
    """Attach tool output (already a typed Evidence) to the ledger + its tool call."""

    kind: Literal["record_evidence"] = "record_evidence"
    tool_call_id: str
    evidence: list[Evidence]
    cost: float = 0.0


class LinkEvidence(BaseModel):
    """Link evidence to a hypothesis as supporting/contradicting and update status."""

    kind: Literal["link_evidence"] = "link_evidence"
    hypothesis_id: str
    supporting: list[str] = Field(default_factory=list)
    contradicting: list[str] = Field(default_factory=list)
    new_status: HypothesisStatus | None = None
    new_posterior: float | None = None


class ProposeRootCauseAction(BaseModel):
    kind: Literal["propose_root_cause"] = "propose_root_cause"
    root_cause: ProposedRootCause


class SetState(BaseModel):
    kind: Literal["set_state"] = "set_state"
    state: InvestigationState


class RecordEvaluation(BaseModel):
    kind: Literal["record_evaluation"] = "record_evaluation"
    evaluation: Evaluation


class SetEscalation(BaseModel):
    kind: Literal["set_escalation"] = "set_escalation"
    escalation: Escalation


class Tick(BaseModel):
    """Advance the step counter (budget meter)."""

    kind: Literal["tick"] = "tick"


Action = Union[
    ProposeHypothesisAction,
    RequestEvidence,
    RecordEvidence,
    LinkEvidence,
    ProposeRootCauseAction,
    SetState,
    RecordEvaluation,
    SetEscalation,
    Tick,
]
