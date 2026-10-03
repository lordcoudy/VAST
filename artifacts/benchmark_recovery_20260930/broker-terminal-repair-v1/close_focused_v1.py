"""Close the finite original broker unit evidence; read-only except new report."""
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent

def read(path):
    return json.loads(path.read_bytes())

def pin(path):
    value = path.read_bytes()
    return {"path": str(path.relative_to(ROOT)), "size_bytes": len(value),
            "sha256": hashlib.sha256(value).hexdigest()}

registry_path = ROOT / "artifacts/benchmark_recovery_20260930/packaging-source-rollforward.v4.json"
registry = read(registry_path)
audit = read(HERE / "pre-edit-dependency-audit.v1.json")
final = HERE / "attempt-06-final"
execution = read(final / "execution.json")
assert execution["returncode"] == 0 and not execution["timed_out"]
after = read(final / "source-after.json")
assert after == read(final / "source-before.json")
source165 = registry["final_actual_source_manifest"]["project_sources"]
host78 = registry["host_execution_code_closure"]["exact_project_source_pins"]
for expected in source165 + host78:
    actual = after[expected["path"]]
    assert (actual["size_bytes"], actual["sha256"]) == (expected["size_bytes"], expected["sha256"])
for name, expected in audit["all9_allowlists"].items():
    actual = pin(ROOT / name)
    assert (actual["size_bytes"], actual["sha256"]) == (expected["size_bytes"], expected["sha256"])

quiescence = []
for attempt in sorted(HERE.glob("attempt-*")):
    terminal = attempt / "execution.json"
    if not terminal.exists():
        continue
    records = [(terminal, read(terminal)["original_pid"])]
    for path in sorted((attempt / "original-fixtures").glob("*/child-terminal.json")):
        records.append((path, read(path)["pid"]))
    for path in sorted((attempt / "original-fixtures").glob("*/journal/broker-owner.json")):
        records.append((path, read(path)["broker_pid"]))
    for path, pid in records:
        absent = not Path(f"/proc/{pid}").exists()
        try:
            os.killpg(pid, 0)
        except ProcessLookupError:
            group_absent = True
        else:
            group_absent = False
        assert absent and group_absent, (str(path), pid)
        quiescence.append({"original_terminal": pin(path), "pid": pid,
                           "pid_absent": absent, "same_id_process_group_absent": group_absent})

owned = [pin(ROOT / name) for name in (
    "scripts/backend_publication_process_supervisor_v3.py",
    "tests/test_backend_publication_broker_terminal_v3.py",
)]
inputs = [pin(path) for path in sorted(HERE.rglob("*"))
          if path.is_file() and path.name != "closed-focused-summary.v1.json"]
report = {
    "schema_version": 1,
    "artifact_kind": "vast_broker_terminal_focused_repair_evidence_v1",
    "reviewed_planning_commit": "9c514a60d644c8c3ecd637eb83185a59aa2a5e01",
    "review_reference": "https://github.com/lordcoudy/VAST/pull/2#issuecomment-5906191857",
    "owned_sources": owned, "registry": pin(registry_path),
    "final_original_execution": pin(final / "execution.json"),
    "final_original_log": pin(final / "stderr"),
    "focused_tests": 11, "unit_returncode": 0,
    "unchanged_source165_count": len(source165), "unchanged_host78_count": len(host78),
    "unchanged_source165_aggregate_sha256": registry["final_actual_source_manifest"]["aggregate_sha256"],
    "source_image_intersection": {"source165": False, "host78": False, "all9_allowlists": False},
    "execution_allowance_ms": 600000, "cleanup_margin_ms": 15000, "terminal_settle_s": 0.2,
    "original_quiescence": quiescence,
    "preserved_attempts": {
        "attempt01": "capture limit failure before dispatch; no tests launched",
        "attempt02_03": "actual RED tests plus original journal-parent fixture race; retained",
        "attempt04": "meaningful old-path RED; real normal completion pass; stdout-only parent watchdog killed after8s without lowering ABI",
        "attempt05": "eight focused tests green on repaired source",
        "attempt06": "eleven focused tests green; real authorization/hash/held-custody negatives added",
    },
    "invalidated_authority": "Original full-production broker/source descriptors and CI source manifests must renew. Prior hosted failures remain historical; unchanged scoped165/78/image identities do not authorize repaired full production execution.",
    "limitations": ["No full-suite, hosted-Ubuntu, image/model/parity or publication acceptance.",
                    "Injected EPERM is explicitly a unit fixture; hosted setup errno and exit139 cause remain unknown.",
                    "Current WSL real namespace synthetic completion passed; it is not inference or a grant.",
                    "Quiescent failed stdout is retained diagnostic material and never accepted as durable authority."],
    "physical_evidence": inputs, "closed_at_unix_ns": time.time_ns(),
    "accepted": False, "publication_ready": False,
}
path = HERE / "closed-focused-summary.v1.json"
with path.open("xb") as output:
    output.write((json.dumps(report, sort_keys=True, separators=(",", ":")) + "\n").encode())
    output.flush()
    os.fsync(output.fileno())
print(json.dumps(pin(path)))
