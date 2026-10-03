"""Persist the authoritative Investigation ledger to Azure Blob storage.

The ledger — not conversation history — is the source of truth. Saving/reloading it
proves investigation state survives process restarts independently of any LLM context.
"""
from __future__ import annotations

from typing import Any

from ..models import Investigation


class BlobLedgerStore:
    def __init__(self, account: str, credential: Any, container: str = "investigations"):
        from azure.storage.blob import BlobServiceClient

        self._svc = BlobServiceClient(
            f"https://{account}.blob.core.windows.net", credential=credential
        )
        self._container = container

    def save(self, inv: Investigation) -> None:
        bc = self._svc.get_blob_client(self._container, f"{inv.id}.json")
        bc.upload_blob(inv.model_dump_json(indent=2).encode("utf-8"), overwrite=True)

    def load(self, inv_id: str) -> Investigation:
        bc = self._svc.get_blob_client(self._container, f"{inv_id}.json")
        return Investigation.model_validate_json(bc.download_blob().readall())
