"""One-off setup loader: push an OpenRCA 2.0 (ops-lite) case into Azure.

  telemetry (normal_*/abnormal_* parquet + env.json) -> EVIDENCE lake (ADLS fs `telemetry`)
  ground truth (label.json, injection.json, causal_graph.json) -> ISOLATED GT store

This is an ADMIN setup tool (not part of the Investigator runtime and not under
src/deeprca). It is the only place that writes both planes, and it uses account keys.
The Investigator never runs this and never sees the GT destination.

Usage:
  python infra/load_incident.py <CASE_NAME> \
      --evidence-account <acct> --evidence-key <key> \
      --gt-account <acct> --gt-key <key>
"""
from __future__ import annotations

import argparse
import sys
import urllib.request

from azure.storage.blob import BlobServiceClient
from azure.storage.filedatalake import DataLakeServiceClient

HF_BASE = "https://huggingface.co/datasets/anon-ops/ops-lite/resolve/main/cases"

TELEMETRY_FILES = [
    "env.json",
    "normal_metrics.parquet", "abnormal_metrics.parquet",
    "normal_metrics_sum.parquet", "abnormal_metrics_sum.parquet",
    "normal_metrics_histogram.parquet", "abnormal_metrics_histogram.parquet",
    "normal_logs.parquet", "abnormal_logs.parquet",
    "normal_traces.parquet", "abnormal_traces.parquet",
]
GROUND_TRUTH_FILES = ["label.json", "injection.json", "causal_graph.json"]


def _download(case: str, fname: str) -> bytes:
    url = f"{HF_BASE}/{case}/{fname}"
    with urllib.request.urlopen(url) as r:
        return r.read()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("case")
    ap.add_argument("--evidence-account", required=True)
    ap.add_argument("--evidence-key", required=True)
    ap.add_argument("--gt-account", required=True)
    ap.add_argument("--gt-key", required=True)
    a = ap.parse_args()

    dl = DataLakeServiceClient(
        f"https://{a.evidence_account}.dfs.core.windows.net", credential=a.evidence_key
    )
    fs = dl.get_file_system_client("telemetry")
    print(f"[telemetry -> evidence lake] cases/{a.case}/")
    for f in TELEMETRY_FILES:
        data = _download(a.case, f)
        fc = fs.get_file_client(f"cases/{a.case}/{f}")
        fc.upload_data(data, overwrite=True)
        print(f"  uploaded {f} ({len(data)} bytes)")

    bs = BlobServiceClient(
        f"https://{a.gt_account}.blob.core.windows.net", credential=a.gt_key
    )
    print(f"[ground truth -> ISOLATED store] {a.case}/")
    for f in GROUND_TRUTH_FILES:
        data = _download(a.case, f)
        bc = bs.get_blob_client("ground-truth", f"{a.case}/{f}")
        bc.upload_blob(data, overwrite=True)
        print(f"  uploaded {f} ({len(data)} bytes)")

    print("DONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
