"""Stage the exact reviewed observer amendment; leave implementation unstaged."""
from pathlib import Path
import hashlib
import json
import subprocess

root = Path.cwd()
git = ["git", "-c", "core.longpaths=true"]
base = "artifacts/benchmark_recovery_20260930/"
assert subprocess.check_output(git + ["rev-parse", "HEAD"], text=True).strip() == "9ad1a52b38cd5028de6b04bcc08192309ef192cf"
assert not subprocess.check_output(git + ["diff", "--cached", "--name-only"])
review_path = base + "decision24-independent-planning-review-v1/review.v1.json"
raw = (root / review_path).read_bytes()
assert len(raw) == 3958 and hashlib.sha256(raw).hexdigest() == "a9169bb917466155be1af549fa22e0f160ecd69b0043b4e9698e512370c6b948"
review = json.loads(raw)
assert review["reviewable"] is True and not review["findings"]
planning = list(review["after_pins"])
for path, expected in review["after_pins"].items():
    data = (root / path).read_bytes()
    assert len(data) == expected["size_bytes"] and hashlib.sha256(data).hexdigest() == expected["sha256"], path
owned = planning + [base + "stage_decision24_planning_v1.py"]
for directory in ("decision24-planning-originals-v1", "decision24-planning-amendment-v1",
                  "decision24-independent-planning-review-v1", "cpu-ci-5f-independent-forensics-v1"):
    files = sorted(p for p in (root / base / directory).rglob("*") if p.is_file()
                   and "__pycache__" not in p.parts and p.suffix != ".pyc")
    assert files, directory
    owned.extend(p.relative_to(root).as_posix() for p in files)
assert len(owned) == len(set(owned))
physical = {path: (root / path).read_bytes() for path in owned}
subprocess.run(git + ["add", "-f", "--", *owned], check=True)

def index_bytes(paths):
    result = subprocess.run(git + ["cat-file", "--batch"], input="".join(":" + p + "\n" for p in paths).encode(),
                            stdout=subprocess.PIPE, check=True).stdout
    offset, values = 0, {}
    for path in paths:
        end = result.index(b"\n", offset)
        header = result[offset:end].split()
        assert len(header) == 3 and header[1] == b"blob", (path, header)
        size = int(header[2]); offset = end + 1
        values[path] = result[offset:offset + size]; offset += size
        assert result[offset:offset + 1] == b"\n"
        offset += 1
    assert offset == len(result)
    return values

carriers = []
for path, staged in index_bytes(owned).items():
    if staged != physical[path]:
        assert path.startswith(base) and path not in planning
        blob = subprocess.check_output(git + ["hash-object", "-w", "--stdin"], input=physical[path]).decode().strip()
        subprocess.run(git + ["update-index", "--add", "--cacheinfo", "100644," + blob + "," + path], check=True)
        carriers.append({"path": path, "sha256": hashlib.sha256(physical[path]).hexdigest(), "blob": blob})
note = base + "decision24-original-byte-carriers.v1.md"
assert not (root / note).exists()
(root / note).write_bytes(("# Decision24 original byte carriers\n\n"
    "Exact reviewed planning, snapshots and retained forensic originals were staged without source or attribute changes. "
    "Only the following original paths required unfiltered Git blob import: " + json.dumps(carriers, sort_keys=True) +
    ".\n\nRetained original and appended raw slices retain their original whitespace. "
    "Current planning, reviews and this staging helper use the normal whitespace check.\n").encode())
subprocess.run(git + ["add", "-f", "--", note], check=True)
owned.append(note)
physical[note] = (root / note).read_bytes()
assert set(subprocess.check_output(git + ["diff", "--cached", "--name-only"], text=True).splitlines()) == set(owned)
assert index_bytes(owned) == physical
subprocess.run(git + ["diff", "--cached", "--check", "--", *planning,
                     base + "stage_decision24_planning_v1.py", review_path, note], check=True)
print(json.dumps({"owned_paths": len(owned), "physical_index_equal": True,
                  "unfiltered_original_imports": carriers, "decision24_code_started": False}, sort_keys=True))
