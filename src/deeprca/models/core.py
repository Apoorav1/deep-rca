"""Core typed models. See docs/architecture.md section 5.

Invariants enforced here (CLAUDE.md):
  - Evidence provenance is mandatory (non-optional field).
  - Hypothesis tracks BOTH supporting and contradicting evidence + a falsification test.
  - Incident has NO root-cause fields.
  - CausalPath exposes graph-validity + temporal-monotonicity checks.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator
from uuid import uuid4


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


# --------------------------------------------------------------------------- #
# Enums
# --------------------------------------------------------------------------- #
class EvidenceKind(str, Enum):
    METRIC = "metric"
    LOG = "log"
    TRACE = "trace"
    TOPOLOGY = "topology"
    DEPLOY = "deploy"
    CONFIG = "config"


class HypothesisStatus(str, Enum):
    PROPOSED = "proposed"
    SUPPORTED = "supported"
    WEAKENED = "weakened"
    REFUTED = "refuted"


class InvestigationState(str, Enum):
    INITIALIZED = "INITIALIZED"
    OBSERVING = "OBSERVING"
    HYPOTHESIZING = "HYPOTHESIZING"
    EVIDENCE_PLANNING = "EVIDENCE_PLANNING"
    COLLECTING = "COLLECTING"
    LEDGER_UPDATE = "LEDGER_UPDATE"
    EVALUATION = "EVALUATION"
    PROPOSE_ROOT_CAUSE = "PROPOSE_ROOT_CAUSE"
    CONCLUDED = "CONCLUDED"
    ESCALATED = "ESCALATED"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"


class Decision(str, Enum):
    CONTINUE = "CONTINUE"
    CONCLUDE = "CONCLUDE"
    ESCALATE = "ESCALATE"


# --------------------------------------------------------------------------- #
# Value objects
# --------------------------------------------------------------------------- #
class TimeWindow(BaseModel):
    start: datetime
    end: datetime

    @field_validator("end")
    @classmethod
    def _end_after_start(cls, v: datetime, info):
        start = info.data.get("start")
        if start is not None and v < start:
            raise ValueError("TimeWindow.end must be >= start")
        return v


class Provenance(BaseModel):
    """Mandatory on every Evidence. No provenance -> not evidence."""

    tool_call_id: str
    source_uri: str
    query: str
    retrieved_at: datetime
    time_range: TimeWindow


# --------------------------------------------------------------------------- #
# Incident  (NO root-cause fields by design)
# --------------------------------------------------------------------------- #
class Incident(BaseModel):
    id: str = Field(default_factory=lambda: _id("inc"))
    case_name: str                 # ops-lite `name`, the join key
    system: str                    # e.g. "hs", "ts"
    namespace: str
    normal_window: TimeWindow
    abnormal_window: TimeWindow    # the incident window under investigation
    symptoms: list[str] = Field(default_factory=list)
    affected_slos: list[str] = Field(default_factory=list)

    # Guard: forbid accidental GT fields sneaking in.
    model_config = {"extra": "forbid"}


# --------------------------------------------------------------------------- #
# Evidence
# --------------------------------------------------------------------------- #
class Evidence(BaseModel):
    id: str = Field(default_factory=lambda: _id("ev"))
    kind: EvidenceKind
    provenance: Provenance          # REQUIRED
    observation: str                # what this evidence shows, in words
    payload: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)


# --------------------------------------------------------------------------- #
# Hypothesis
# --------------------------------------------------------------------------- #
class Hypothesis(BaseModel):
    id: str = Field(default_factory=lambda: _id("hyp"))
    statement: str
    suspected_service: str | None = None
    suspected_fault_type: str | None = None
    status: HypothesisStatus = HypothesisStatus.PROPOSED
    supporting_evidence: list[str] = Field(default_factory=list)   # evidence ids
    contradicting_evidence: list[str] = Field(default_factory=list)
    falsification_test: str                                        # REQUIRED
    posterior: float = Field(ge=0.0, le=1.0, default=0.5)


# --------------------------------------------------------------------------- #
# ToolCall
# --------------------------------------------------------------------------- #
class ToolCall(BaseModel):
    id: str = Field(default_factory=lambda: _id("tc"))
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    result_evidence_ids: list[str] = Field(default_factory=list)
    started: datetime | None = None
    ended: datetime | None = None
    cost: float = 0.0
    status: str = "ok"


# --------------------------------------------------------------------------- #
# Causal path
# --------------------------------------------------------------------------- #
class CausalNode(BaseModel):
    entity: str                 # e.g. "service|profile" or "span|frontend::HTTP /hotels"
    fault_or_effect: str        # e.g. "unavailable", "erroring", "root_fault"
    timestamp: datetime


class CausalEdge(BaseModel):
    source: str                 # CausalNode.entity
    target: str
    mechanism: str              # why source causes target
    evidence_ids: list[str] = Field(default_factory=list)


class CausalPath(BaseModel):
    nodes: list[CausalNode]
    edges: list[CausalEdge]

    def is_temporally_monotonic(self) -> bool:
        """Each edge's source timestamp must be <= its target timestamp."""
        ts = {n.entity: n.timestamp for n in self.nodes}
        for e in self.edges:
            if e.source in ts and e.target in ts and ts[e.source] > ts[e.target]:
                return False
        return True

    def is_graph_valid(self, dependency_edges: set[tuple[str, str]] | None = None) -> bool:
        """Every edge must connect declared nodes; if a dependency graph is
        supplied, each edge must correspond to a real (or justified) dependency."""
        entities = {n.entity for n in self.nodes}
        for e in self.edges:
            if e.source not in entities or e.target not in entities:
                return False
            if not e.evidence_ids:
                return False
        if dependency_edges is not None:
            for e in self.edges:
                if (e.source, e.target) not in dependency_edges:
                    return False
        return True


class ProposedRootCause(BaseModel):
    causal_path: CausalPath
    root_services: list[str]
    fault_type: str | None = None
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    rationale: str = ""


# --------------------------------------------------------------------------- #
# Evaluation / Escalation  (blind: never carry ground truth)
# --------------------------------------------------------------------------- #
class Evaluation(BaseModel):
    decision: Decision
    critiques: list[dict[str, str]] = Field(default_factory=list)  # {category, note}
    rationale: str = ""
    unresolved_contradictions: list[str] = Field(default_factory=list)
    at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Escalation(BaseModel):
    reason: str
    open_questions: list[str] = Field(default_factory=list)
    state_snapshot_ref: str | None = None
    suggested_human_actions: list[str] = Field(default_factory=list)
    at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# --------------------------------------------------------------------------- #
# Investigation  (the authoritative ledger / aggregate root)
# --------------------------------------------------------------------------- #
class Investigation(BaseModel):
    id: str = Field(default_factory=lambda: _id("inv"))
    incident_id: str
    case_name: str
    state: InvestigationState = InvestigationState.INITIALIZED
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    evidence_store: list[Evidence] = Field(default_factory=list)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    proposed_root_cause: ProposedRootCause | None = None
    evaluations: list[Evaluation] = Field(default_factory=list)
    escalation: Escalation | None = None
    step: int = 0
    max_steps: int = 20
    cost_budget: float = 5.0
    cost_spent: float = 0.0
    version: int = 0               # bumped by the reducer on every applied action

    # -- convenience lookups (read-only) --
    def evidence_by_id(self, eid: str) -> Evidence | None:
        return next((e for e in self.evidence_store if e.id == eid), None)

    def hypothesis_by_id(self, hid: str) -> Hypothesis | None:
        return next((h for h in self.hypotheses if h.id == hid), None)

    def budget_remaining(self) -> bool:
        return self.step < self.max_steps and self.cost_spent < self.cost_budget
