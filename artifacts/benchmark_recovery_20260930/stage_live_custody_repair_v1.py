"""Stage only the reviewed live-interface repair and its immutable evidence."""
from pathlib import Path
import hashlib
import json
import subprocess

root = Path.cwd()
expected_head = "7f3dfa42858c85d6e3db2cb1274dd13af35696c9"
head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
assert head == expected_head
assert not subprocess.check_output(["git", "diff", "--cached", "--name-only"], text=True).strip()
owned = ["scripts/publication_operational_container_custody_v1.py",
         "scripts/publication_operational_process_custody_v1.py",
         "tests/test_publication_operational_container_custody_v1.py",
         "tests/test_publication_operational_process_custody_v1.py",
         "BENCHMARK_RECOVERY_PLAN.md"]
previous = json.loads((root / "artifacts/benchmark_recovery_20260929/owned-source-freeze.v1.json").read_bytes())
rows = []
for prior in previous["source_files"]:
    raw = (root / prior["path"]).read_bytes()
    row = {"path": prior["path"], "size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    if prior["path"] not in owned:
        assert row == prior, "unreviewed owned source drift: " + prior["path"]
    rows.append(row)
assert len(rows) == 63
value = {"schema_version": 1, "artifact_kind": "vast_explicit_owned_recovery_source_rollforward_v1",
         "head_before": head, "branch": "codex/fix-benchmark-preparations-spec",
         "changed_owned_paths": owned, "source_files": rows,
         "physical_source_scope": "63 explicit owned paths; other build inputs have separate physical manifests",
         "previous_build_is_historical_for_its_original_bytes": True,
         "new_image_build_started": False, "model_workload_started": False,
         "qualification_acceptance": False, "publication_acceptance": False,
         "unrelated_dirty_paths_preserved": True}
freeze = Path(__file__).parent / "owned-source-rollforward.v1.json"
with freeze.open("xb") as stream:
    stream.write((json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii"))
subprocess.run(["git", "add", "--", *owned], check=True)
evidence = sorted(path.relative_to(root).as_posix() for path in freeze.parent.rglob("*")
                  if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc")
subprocess.run(["git", "add", "-f", "--", *evidence], check=True)
staged = subprocess.check_output(["git", "diff", "--cached", "--name-only"], text=True).splitlines()
assert all(path in owned or path.startswith("artifacts/benchmark_recovery_20260930/") for path in staged)
for row in rows:
    raw = subprocess.check_output(["git", "show", ":" + row["path"]])
    assert hashlib.sha256(raw).hexdigest() == row["sha256"], "source/index bytes differ: " + row["path"]
subprocess.run(["git", "diff", "--cached", "--check", "--", *owned], check=True)
print(json.dumps({"head_before": head, "staged_paths": len(staged), "owned_source_files": len(rows),
                  "index_source_bytes_identical": True, "owned_source_whitespace_check_passed": True,
                  "original_evidence_bytes_are_not_reformatted": True, "changed_owned_paths": owned}))
