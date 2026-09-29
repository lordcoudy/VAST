"""Read historical native CSVs through the new stock cohort adapter.

This observation does not execute or accept a new benchmark operation.
"""
from pathlib import Path
import csv
import datetime
import hashlib
import json
import os
import sys
import traceback
import yaml

root = Path.cwd()
sys.path.insert(0, str(root / "scripts"))
from checkpoint_gstreamer_runtime import build_publication_pair_plans
from publication_policy_qualification_execution_closure_v1 import _operational_measured_ingress_v1

output = Path(__file__).parent
receipt = output / "attempt-01.observation.v1.json"
if receipt.exists():
    raise SystemExit("Preserve the original observation; do not rerun it.")

def descriptor(path):
    raw = path.read_bytes()
    return {"path": str(path), "size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}

config = yaml.safe_load((root / "configs/experiments.yaml").read_bytes())
datasets = yaml.safe_load((root / "configs/datasets.yaml").read_bytes())["datasets"]
names = ("frames.csv", "ingress_ledger.csv", "frame_events.csv", "resource_events.csv",
    "policy_decisions.csv", "drop_counters.csv", "topology_events.csv", "branch_terminals.csv",
    "stage_contracts.csv", "reset_evidence.csv", "publication_policy_decisions.jsonl")
source_names = ("scripts/publication_policy_qualification_execution_closure_v1.py",
    "scripts/benchmark_contract.py", "scripts/topology_contract.py",
    "scripts/checkpoint_runtime_plan.py", "scripts/checkpoint_gstreamer_runtime.py",
    "scripts/publication_physical_io_v1.py", "configs/experiments.yaml", "configs/datasets.yaml")
before_sources = [descriptor(root / name) for name in source_names]
rows = []
for system in ("openvino_gva", "gstreamer_custom"):
    plan = build_publication_pair_plans(config=config, datasets=datasets, system=system, codec="h264")["baseline"]
    plan_path = output / (system + ".source-plan.json")
    raw = (json.dumps(plan, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")
    with plan_path.open("xb") as stream:
        stream.write(raw)
    for resource in ("cpu", "gpu"):
        directory = root / "artifacts/fix_benchmark_preparations_20260928g/qualification_control" / (
            "precheck_" + system + "_" + resource + "_h264_independent_processes/evidence")
        before = [descriptor(directory / name) for name in names]
        with (directory / "ingress_ledger.csv").open(newline="") as stream:
            original = next(csv.DictReader(stream))
        operation = {"run_id": original["run_id"], "system": system,
            "scenario": "checkpoint_independent_processes_baseline", "streams": 6,
            "policy": resource + "_only", "descriptors": {"source_plan": descriptor(plan_path)}}
        try:
            result = _operational_measured_ingress_v1(root=root, operation=operation,
                directory=directory, ingress_descriptor=descriptor(directory / "ingress_ledger.csv"))
            observation = {"status": "stock_cohort_read_succeeded", "canonical_frame_count": len(result)}
        except Exception:
            observation = {"status": "stock_cohort_read_failed", "original_exception": traceback.format_exc()}
        after = [descriptor(directory / name) for name in names]
        rows.append({"system": system, "resource": resource, "operation": operation,
            "historical_files": before, "historical_files_after": after,
            "historical_files_unchanged": before == after, **observation})
after_sources = [descriptor(root / name) for name in source_names]
value = {"schema_version": 1, "artifact_kind": "vast_historical_original_cohort_adapter_observation_v1",
    "observed_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(), "uid": os.getuid(),
    "gid": os.getgid(), "python_executable": sys.executable, "source_files": before_sources,
    "source_files_after": after_sources, "sources_unchanged": before_sources == after_sources,
    "observations": rows, "new_execution": False, "qualification_acceptance": False,
    "publication_acceptance": False}
raw = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")
with receipt.open("xb") as stream:
    stream.write(raw)
print(json.dumps({"receipt": str(receipt.relative_to(root)), "sha256": hashlib.sha256(raw).hexdigest(),
    "results": [{key: row[key] for key in ("system", "resource", "status")} for row in rows]}))
raise SystemExit(0 if all(row["status"] == "stock_cohort_read_succeeded" and
    row["historical_files_unchanged"] for row in rows) and before_sources == after_sources else 1)
