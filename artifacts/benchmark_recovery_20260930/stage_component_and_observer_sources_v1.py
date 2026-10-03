"""Freeze exact reviewed owned sources and retained originals, preserving dirt."""
from pathlib import Path
import hashlib
import json
import subprocess

root = Path.cwd()
git = ["git", "-c", "core.longpaths=true"]
base = "artifacts/benchmark_recovery_20260930/"
assert subprocess.check_output(git + ["rev-parse", "HEAD"], text=True).strip() == "ded811a8043575e7a93cf0bbc28696ac53667d3c"
assert not subprocess.check_output(git + ["diff", "--cached", "--name-only"])
reviews = {
    "gstreamer-component-seam1-independent-review-v1/review.v1.json": "97f32ed9bc75b2c81d2e37e3b19d0ae246f45de7a1bb46c94aec08441ded1385",
    "component-seam2-independent-review-v1/review.v1.json": "2ec2a04b9e88e1e545054615c5352b67d1ca82c2bcf844d52abc4f94717ef22f",
    "component-cli-independent-review-v1/review.v1.json": "f93ba77187e10bc0231d3b06b83c2118c5406194930678cc13e69c456e7f1927",
    "component-runtime-independent-review-v1/review.v1.json": "59f1ceb74d02887780ef798ebf2073bddbbf861233c41f65fb9d2a931dc3e10a",
    "decision24-ci-independent-review-v1/review.v1.json": "44fa9941b35c64f03947c5719382e559df85278afd6901b7444357d81b49f962",
}
for path, expected in reviews.items():
    assert hashlib.sha256((root / base / path).read_bytes()).hexdigest() == expected, path
expected_sources = {}
def include(rows):
    for row in rows:
        name = row["path"]
        expected = {key: row[key] for key in ("size_bytes", "sha256")}
        assert name not in expected_sources or expected_sources[name] == expected
        expected_sources[name] = expected
seam1 = json.loads((root / base / "gstreamer-component-seam1-v1/implementation-summary.v1.json").read_bytes())
include([row for row in seam1["modules"] if row["author_owned"]])
include(json.loads((root / base / "component-seam2-final-review-v1/review.v1.json").read_bytes())["source_files"])
include(json.loads((root / base / "component-cli-focused-v1/self-review.v1.json").read_bytes())["owned_sources"].values())
include(json.loads((root / base / "root-seam3-author-review-v2/review.v1.json").read_bytes())["owned_sources"].values())
include(json.loads((root / base / "decision24-ci-author-review-v1/review.v2.json").read_bytes())["source_files"])
assert len(expected_sources) == 23
for path, row in expected_sources.items():
    raw = (root / path).read_bytes()
    assert len(raw) == row["size_bytes"] and hashlib.sha256(raw).hexdigest() == row["sha256"], path
owned = list(expected_sources) + ["BENCHMARK_RECOVERY_PLAN.md", "openspec/changes/fix-benchmark-preparations-spec/tasks.md",
    base + "stage_component_and_observer_sources_v1.py"]
directories = (
    "gstreamer-component-seam1-preparation-v1", "gstreamer-component-seam1-v1",
    "gstreamer-component-seam1-independent-review-v1", "component-seam2-pre-edit-v1",
    "component-seam2-focused-v1", "component-seam2-self-review-v1", "component-seam2-final-review-v1",
    "component-seam2-independent-review-v1", "component-cli-focused-v1", "component-cli-independent-review-v1",
    "gstreamer-component-seam3-preparation-v1", "root-seam3-focused-v1", "root-seam3-author-review-v2",
    "component-runtime-independent-review-v1", "component-selected-packaging-pre-edit-v1",
    "component-packaged-import-smoke-v1", "decision24-ci-pre-edit-v1", "decision24-ci-focused-v1",
    "decision24-ci-author-review-v1", "decision24-ci-independent-review-v1",
)
for directory in directories:
    files = sorted(p for p in (root / base / directory).rglob("*") if p.is_file()
                   and "__pycache__" not in p.parts and p.suffix != ".pyc")
    assert files, directory
    owned.extend(p.relative_to(root).as_posix() for p in files)
assert len(owned) == len(set(owned))
physical = {path: (root / path).read_bytes() for path in owned}
subprocess.run(git + ["add", "-f", "--", *owned], check=True)

def blobs(paths, prefix=":"):
    raw = subprocess.run(git + ["cat-file", "--batch"], input="".join(prefix + p + "\n" for p in paths).encode(),
                         stdout=subprocess.PIPE, check=True).stdout
    offset, result = 0, {}
    for path in paths:
        end = raw.index(b"\n", offset)
        header = raw[offset:end].split()
        assert len(header) == 3 and header[1] == b"blob", (path, header)
        size = int(header[2]); offset = end + 1
        result[path] = raw[offset:offset + size]; offset += size
        assert raw[offset:offset + 1] == b"\n"
        offset += 1
    assert offset == len(raw)
    return result

carriers = []
for path, staged in blobs(owned).items():
    if staged != physical[path]:
        assert path.startswith(base) and path not in expected_sources, path
        blob = subprocess.check_output(git + ["hash-object", "-w", "--stdin"], input=physical[path]).decode().strip()
        subprocess.run(git + ["update-index", "--add", "--cacheinfo", "100644," + blob + "," + path], check=True)
        carriers.append({"path": path, "sha256": hashlib.sha256(physical[path]).hexdigest(), "blob": blob})
note = base + "component-observer-original-byte-carriers.v1.md"
assert not (root / note).exists()
(root / note).write_bytes(("# Component and observer original byte carriers\n\n"
    "Current23 reviewed source/test paths use their normal Git staging with exact physical/index equality. "
    "Only these original retained artifact paths required unfiltered blob import: " + json.dumps(carriers, sort_keys=True) +
    ". No production source or attribute rule was rewritten to import an original artifact.\n").encode())
subprocess.run(git + ["add", "-f", "--", note], check=True)
owned.append(note); physical[note] = (root / note).read_bytes()
report_path = base + "component-observer-source-freeze.v1.json"
assert not (root / report_path).exists()
report = {"schema_version": 1, "artifact_kind": "vast_component_observer_reviewed_source_freeze_v1",
    "previous_head": "ded811a8043575e7a93cf0bbc28696ac53667d3c", "owned_sources": expected_sources,
    "independent_reviews": reviews,
    "owned_originals": {p: {"size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
                        for p, raw in physical.items()},
    "unfiltered_original_imports": carriers, "hardware_acceptance": False, "full_ci_acceptance": False,
    "future_campaigns_executed": False, "unrelated_dirt_preserved": True}
(root / report_path).write_bytes((json.dumps(report, sort_keys=True, separators=(",", ":")) + "\n").encode())
subprocess.run(git + ["add", "-f", "--", report_path], check=True)
owned.append(report_path); physical[report_path] = (root / report_path).read_bytes()
assert set(subprocess.check_output(git + ["diff", "--cached", "--name-only"], text=True).splitlines()) == set(owned)
assert blobs(owned) == physical
subprocess.run(git + ["diff", "--cached", "--check", "--", *expected_sources,
                     "BENCHMARK_RECOVERY_PLAN.md", "openspec/changes/fix-benchmark-preparations-spec/tasks.md",
                     base + "stage_component_and_observer_sources_v1.py", note, report_path], check=True)
print(json.dumps({"owned_paths": len(owned), "reviewed_sources": len(expected_sources),
                  "physical_index_equal": True, "unfiltered_original_imports": len(carriers)}))
