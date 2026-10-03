"""Read ground truth from the ISOLATED GT store. Part of the offline eval plane only.

Imported by nothing under src/deeprca (enforced by the import-ban test).
"""
from __future__ import annotations

import json
from typing import Any

from .ground_truth import GroundTruth


def read_ground_truth(account: str, case: str, credential: Any,
                      container: str = "ground-truth") -> GroundTruth:
    from azure.storage.blob import BlobServiceClient

    svc = BlobServiceClient(f"https://{account}.blob.core.windows.net", credential=credential)

    def rd(name: str) -> dict:
        data = svc.get_blob_client(container, f"{case}/{name}").download_blob().readall()
        return json.loads(data)

    label, injection, causal = rd("label.json"), rd("injection.json"), rd("causal_graph.json")
    required = [f for f in label.get("faults", []) if f.get("role") == "required"]
    return GroundTruth(
        case_name=label["case"],
        system=label["system"],
        root_services=sorted({f["service"] for f in required}),
        chaos_types=sorted({f["chaos_type"] for f in required}),
        n_required_faults=len(required),
        causal_graph=causal,
        injection=injection,
    )
