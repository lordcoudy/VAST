"""Stage only reviewed Decision23 planning and closed original evidence."""
from pathlib import Path
import hashlib
import json
import subprocess

root = Path.cwd()
git = ["git", "-c", "core.longpaths=true"]
base = "artifacts/benchmark_recovery_20260930/"
change = "openspec/changes/fix-benchmark-preparations-spec/"
assert subprocess.check_output(git + ["rev-parse", "HEAD"], text=True).strip() == "5f78da4c2c8dde5c9fd5c42ab8d05dcb2b589659"
assert not subprocess.check_output(git + ["diff", "--cached", "--name-only"])
planning = ["BENCHMARK_RECOVERY_PLAN.md"] + [change + p for p in (
    "proposal.md", "design.md", "tasks.md", "specs/benchmark-launch-preparation/spec.md", "verification-plan.md")]
review_path = base + "component-release-planning-independent-review-v1/review.v1.json"
review_raw = (root / review_path).read_bytes()
assert len(review_raw) == 9725 and hashlib.sha256(review_raw).hexdigest() == "7413495221c775c0c3ee9a446e59f42318bc0fe4fa0fe31d62a6163094551f74"
owned = planning + [base + "amend_selected_release_planning_v1.py", base + "stage_decision23_planning_v1.py"]
for dirname in ("decision22-planning-originals-v1", "decoder-research-attempt-05", "decoder-research-attempt05-original-controller", "decoder-attempt05-postterminal-observation-v1", "decoder-attempt05-independent-failed-review-v1", "component-release-planning-independent-review-v1", "cpu-ci-run-36687928235"):
    files = sorted(p for p in (root / base / dirname).rglob("*") if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc")
    assert files, dirname
    owned.extend(p.relative_to(root).as_posix() for p in files)
assert len(owned) == len(set(owned))
pins = {p: (len((root / p).read_bytes()), hashlib.sha256((root / p).read_bytes()).hexdigest()) for p in owned}
subprocess.run(git + ["add", "-f", "--", *owned], check=True)

def read_index(paths):
    request = "".join(":" + p + "\n" for p in paths).encode()
    proc = subprocess.Popen(git + ["cat-file", "--batch"], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    raw, _ = proc.communicate(request)
    assert proc.returncode == 0
    offset = 0
    result = {}
    for path in paths:
        end = raw.index(b"\n", offset)
        header = raw[offset:end].split()
        assert len(header) == 3 and header[1] == b"blob", (path, header)
        size = int(header[2]); offset = end + 1
        result[path] = raw[offset:offset + size]
        offset += size
        assert raw[offset:offset + 1] == b"\n"
        offset += 1
    assert offset == len(raw)
    return result

normalized = []
for path, staged in read_index(owned).items():
    physical = (root / path).read_bytes()
    if staged != physical:
        assert path.startswith(base) and path not in planning, path
        blob = subprocess.check_output(git + ["hash-object", "-w", "--stdin"], input=physical).decode().strip()
        subprocess.run(git + ["update-index", "--add", "--cacheinfo", "100644," + blob + "," + path], check=True)
        normalized.append({"path": path, "size_bytes": len(physical), "sha256": hashlib.sha256(physical).hexdigest(), "unfiltered_git_blob": blob})
note = base + "decision23-original-byte-carriers.v1.md"
assert not (root / note).exists()
text = "# Decision23 original evidence byte carriers\n\nOnly the exact closed original artifact paths below needed unfiltered Git blob import to retain their physical bytes under existing text attributes. No source, planning file, attribute or original evidence bytes were rewritten.\n\n" + "\n".join("- `" + row["path"] + "`: " + str(row["size_bytes"]) + " bytes, SHA256 `" + row["sha256"] + "`, blob `" + row["unfiltered_git_blob"] + "`." for row in normalized) + "\n\nWhitespace in retained raw job/process/map/error logs and Decision22 snapshots is original provenance; current five planning artifacts, plan and new helpers require the normal whitespace check.\n"
(root / note).write_bytes(text.encode())
subprocess.run(git + ["add", "-f", "--", note], check=True)
owned.append(note)
staged = subprocess.check_output(git + ["diff", "--cached", "--name-only"], text=True).splitlines()
assert set(staged) == set(owned), (set(staged) - set(owned), set(owned) - set(staged))
for path, raw in read_index(owned).items():
    assert raw == (root / path).read_bytes(), path
    if path in pins:
        assert (len(raw), hashlib.sha256(raw).hexdigest()) == pins[path], path
subprocess.run(git + ["diff", "--cached", "--check", "--", *planning, base + "amend_selected_release_planning_v1.py", base + "stage_decision23_planning_v1.py", review_path, note], check=True)
print(json.dumps({"owned_staged_paths": len(owned), "all_physical_index_bytes_equal": True, "unfiltered_original_imports": normalized, "production_source_started": False}, sort_keys=True))
