"""Ground-truth loader. Importable ONLY from within the ``eval`` package.

In Phase 1 this reads from a local isolated directory; in Azure it reads from the
isolated Storage account that the Investigator's managed identity cannot resolve.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class GroundTruth:
    case_name: str
    system: str
    root_services: list[str]
    chaos_types: list[str]
    n_required_faults: int
    causal_graph: dict = field(default_factory=dict)
    injection: dict = field(default_factory=dict)


def load_ground_truth(case_dir: str | Path) -> GroundTruth:
    """Load GT for one case from its isolated directory (label/injection/causal_graph)."""
    d = Path(case_dir)
    label = json.loads((d / "label.json").read_text())
    injection = json.loads((d / "injection.json").read_text())
    causal = json.loads((d / "causal_graph.json").read_text())
    faults = label.get("faults", [])
    required = [f for f in faults if f.get("role") == "required"]
    return GroundTruth(
        case_name=label["case"],
        system=label["system"],
        root_services=sorted({f["service"] for f in required}),
        chaos_types=sorted({f["chaos_type"] for f in required}),
        n_required_faults=len(required),
        causal_graph=causal,
        injection=injection,
    )
