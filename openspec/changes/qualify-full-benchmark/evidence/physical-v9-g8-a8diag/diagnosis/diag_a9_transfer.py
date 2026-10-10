"""Amendment 9 diagnostic (non-qualifying, read-only): for every GPU pilot cell of attempt 4, count the
native GPU decisions whose (trace_id, branch) has no positive `transfer` resource interval, and describe
the transfer intervals that do exist. usage: python -B -E -s diag_a9_transfer.py"""
import collections
import csv
import json
from pathlib import Path

PILOTS = Path("/mnt/e/STUDY/VAST/tmp/qfb-root-20261007a/artifacts/publication_policy_qualification_pilot_v2_qfb_20261008e")
result = {}
for arm in sorted(p for p in PILOTS.glob("*/gpu/*/*") if p.is_dir() and "." not in p.name):
    cell = "/".join(arm.relative_to(PILOTS).parts)
    transfer = collections.defaultdict(float)
    components = collections.Counter()
    zero_transfer = 0
    with (arm / "resource_intervals.csv").open(newline="") as handle:
        for row in csv.DictReader(handle):
            components[row["component"]] += 1
            if row["component"] == "transfer":
                duration = float(row["duration_ns"])
                zero_transfer += duration <= 0
                transfer[(row["trace_id"], row["branch_id"])] += duration
    decisions = [json.loads(line) for line in (arm / "publication_policy_decisions.jsonl").read_text().splitlines() if line.strip()]
    gpu = [d for d in decisions if d.get("selected_resource") == "gpu"]
    missing = [d for d in gpu if transfer.get((str(d.get("trace_id")), str(d.get("branch"))), 0.0) <= 0]
    by_branch = collections.Counter(str(d.get("branch")) for d in missing)
    result[cell] = {
        "decisions": len(decisions), "gpu_decisions": len(gpu), "gpu_without_transfer": len(missing),
        "missing_by_branch": dict(by_branch), "interval_components": dict(components),
        "transfer_rows_nonpositive": zero_transfer,
        "missing_examples": [{k: d.get(k) for k in ("decision_id", "trace_id", "branch")} for d in missing[:3]],
    }
print(json.dumps(result, indent=1))
