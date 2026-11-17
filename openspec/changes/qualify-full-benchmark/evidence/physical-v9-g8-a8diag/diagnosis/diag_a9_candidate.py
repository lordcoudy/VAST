"""Amendment 9 diagnostic (non-qualifying, read-only): stock policy pilot validator on all 32 attempt-4
cells with two candidate corrections applied from outside: (1) expected_streams=6 for the sidecar
revalidation; (2) decisions of frames whose ingress terminal is not `completed` are not calibration
samples (as in the resource validator). (2) is emulated by filtering the decision JSONL rows the
validator reads; their counts per cell are reported. Nothing is written under the root.
usage: python -B -E -s diag_a9_candidate.py"""
import csv
import functools
import json
import sys
import traceback
from pathlib import Path

ROOT = Path("/mnt/e/STUDY/VAST/tmp/qfb-root-20261007a")
sys.path.insert(0, str(ROOT / "scripts"))
import benchmark_contract  # noqa: E402
import publication_policy_qualification as ppq  # noqa: E402
import publication_policy_qualification_fragments_from_authority_v2 as fv2  # noqa: E402

INDEX = ROOT / "artifacts/publication_policy_qualification_index_v2_qfb_20261008e_a8diag/checkpoint_policy_qualification_index.v2.json"
stock_sidecars = benchmark_contract.validate_required_sidecars
benchmark_contract.validate_required_sidecars = functools.wraps(stock_sidecars)(
    lambda *args, **kwargs: stock_sidecars(*args, **{"expected_streams": 6, **kwargs}))
stock_read = ppq._read_jsonl
excluded: dict[str, int] = {}


def completed_only(path: Path) -> list[dict]:
    completed = {row["trace_id"] for row in csv.DictReader((path.parent / "ingress_ledger.csv").open(newline=""))
                 if row["terminal_status"] == "completed"}
    rows = stock_read(path)
    kept = [row for row in rows if str(row.get("trace_id")) in completed]
    excluded[str(path.parent)] = len(rows) - len(kept)
    return kept


ppq._read_jsonl = completed_only
index = json.loads(INDEX.read_bytes())
policy = ppq._load_policy_contract()
dataset = ppq._verify_descriptor(ROOT, index["dataset_manifest"], "dataset manifest", forbid_hardlinks=True)
manifest, bindings = ppq._derive_fragment_bound_manifest(
    index["bindings"], project_root=ROOT, policy=policy,
    fragment_validator=fv2.validate_publication_policy_qualification_fragment_from_authority_v2)
result: dict = {"cells": {}}
decisions, traces = set(), set()
for pilot in index["pilots"]:
    key = (pilot["system"], pilot["resource"], pilot["codec"], pilot["topology_kind"])
    arm = str((ROOT / pilot["evidence"]["frames"]["path"]).parent)
    try:
        rows = ppq._default_pilot_validator(pilot, {"project_root": ROOT, "policy": policy, "capability_manifest": manifest,
                                                    "bindings": bindings, "dataset_manifest": dataset})
        samples = ppq._validate_samples(rows, pilot_key=key, branches=tuple(policy.ANALYTICS_BRANCHES),
                                         minimum_samples=int(policy.MIN_CALIBRATION_SAMPLES),
                                         global_decisions=decisions, global_traces=traces)
        result["cells"]["/".join(key)] = {"status": "accepted", "samples": len(samples), "excluded_dropped": excluded.get(arm)}
    except Exception as error:
        result["cells"]["/".join(key)] = {"status": "refused", "error": f"{type(error).__name__}: {error}"[:600],
                                          "where": [f"{Path(f.filename).name}:{f.lineno}" for f in traceback.extract_tb(error.__traceback__)][-3:],
                                          "excluded_dropped": excluded.get(arm)}
statuses = [cell["status"] for cell in result["cells"].values()]
result["accepted"], result["refused"] = statuses.count("accepted"), statuses.count("refused")
print(json.dumps(result, indent=1))
