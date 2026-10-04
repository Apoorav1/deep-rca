"""Evidence Plane adapter over the ADLS Gen2 telemetry lake.

Constructed with ONLY the evidence account. It has no knowledge of the ground-truth
store. This is the sole data path the Investigator's tools use.
"""
from __future__ import annotations

import io
import json
from functools import lru_cache
from typing import Any

import pandas as pd
import pyarrow.parquet as pq


class EvidenceLake:
    def __init__(self, account: str, credential: Any, filesystem: str = "telemetry"):
        # Imported lazily so unit tests that never touch Azure don't need the SDK.
        from azure.storage.filedatalake import DataLakeServiceClient

        self.account = account
        self.filesystem = filesystem
        self._svc = DataLakeServiceClient(
            f"https://{account}.dfs.core.windows.net", credential=credential
        )
        self._fs = self._svc.get_file_system_client(filesystem)

    def source_uri(self, case: str, leaf: str) -> str:
        return (
            f"abfss://{self.filesystem}@{self.account}.dfs.core.windows.net"
            f"/cases/{case}/{leaf}"
        )

    def _read_bytes(self, path: str) -> bytes:
        return self._fs.get_file_client(path).download_file().readall()

    def list_cases(self) -> list[str]:
        """Discover incident case ids present in the evidence lake (cases/<id>/)."""
        try:
            paths = self._fs.get_paths(path="cases", recursive=False)
            return sorted(p.name.rsplit("/", 1)[-1] for p in paths if getattr(p, "is_directory", False))
        except Exception:
            return []

    def read_env(self, case: str) -> dict:
        return json.loads(self._read_bytes(f"cases/{case}/env.json"))

    @lru_cache(maxsize=64)
    def read_table(self, case: str, name: str) -> pd.DataFrame:
        """name e.g. 'abnormal_metrics', 'normal_traces', 'abnormal_logs'."""
        data = self._read_bytes(f"cases/{case}/{name}.parquet")
        return pq.read_table(io.BytesIO(data)).to_pandas()
