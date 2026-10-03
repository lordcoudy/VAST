"""Freeze only the coherent planning amendment and closed owned evidence."""
from pathlib import Path
import hashlib
import json
import subprocess

root = Path.cwd()
expected_head = "a5b3812457cc2eddfd19eaf7687a4e868a7d085b"
head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
assert head == expected_head
assert not subprocess.check_output(["git", "diff", "--cached", "--name-only"], text=True).strip()
change = "openspec/changes/fix-benchmark-preparations-spec/"
owned = ["BENCHMARK_RECOVERY_PLAN.md", *[change + name for name in (
    "proposal.md", "design.md", "tasks.md", "specs/benchmark-launch-preparation/spec.md",
    "verification-plan.md", "preparation-plan.md", "implementation-validation.md",
    "image-invalidation.md", "conformance-progress.md")]]
rows = []
for name in owned:
    raw = (root / name).read_bytes()
    rows.append({"path": name, "size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
evidence_root = Path(__file__).parent
evidence = sorted(path.relative_to(root).as_posix() for path in evidence_root.rglob("*")
                  if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc")
manifest = evidence_root / "scientific-checkout-planning-freeze.v1.json"
assert not manifest.exists()
value = {"schema_version": 1, "artifact_kind": "vast_exact_scientific_checkout_planning_freeze_v1",
         "head_before": head, "branch": "codex/fix-benchmark-preparations-spec",
         "planning_files": rows, "closed_owned_evidence_paths": evidence,
         "dependent_source_edit_started": False, "decoder_research_started": False,
         "qualification_acceptance": False, "publication_acceptance": False,
         "unrelated_dirty_paths_preserved": True}
with manifest.open("xb") as stream:
    stream.write((json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii"))
evidence.append(manifest.relative_to(root).as_posix())
subprocess.run(["git", "add", "--", *owned], check=True)
subprocess.run(["git", "add", "-f", "--", *evidence], check=True)
staged = subprocess.check_output(["git", "diff", "--cached", "--name-only"], text=True).splitlines()
assert all(path in owned or path.startswith("artifacts/benchmark_recovery_20260930/") for path in staged)
assert ".gitattributes" not in staged
assert not any(path.startswith(("scripts/", "deploy/", "tests/", ".github/")) for path in staged)
for row in rows:
    raw = subprocess.check_output(["git", "show", ":" + row["path"]])
    assert hashlib.sha256(raw).hexdigest() == row["sha256"], "planning/index bytes differ: " + row["path"]
subprocess.run(["git", "diff", "--cached", "--check", "--", *owned], check=True)
print(json.dumps({"head_before": head, "staged_paths": len(staged), "planning_files": len(rows),
                  "index_planning_bytes_identical": True, "planning_whitespace_check_passed": True,
                  "no_dependent_source_or_research_launched": True}))
