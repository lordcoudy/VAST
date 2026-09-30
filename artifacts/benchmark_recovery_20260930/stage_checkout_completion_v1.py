"""Stage only closed checkout evidence and progress documents."""
from pathlib import Path
import hashlib
import subprocess

root = Path.cwd()
base = root / "artifacts/benchmark_recovery_20260930"
assert subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip() == "caea5419c0302fc60183544de86f4e879346b7d0"
initial_staged = subprocess.check_output(["git", "diff", "--cached", "--name-only"], text=True).splitlines()
change = "openspec/changes/fix-benchmark-preparations-spec/"
docs = ["BENCHMARK_RECOVERY_PLAN.md"] + [change + name for name in (
    "tasks.md", "implementation-validation.md", "conformance-progress.md",
    "image-invalidation.md", "preparation-plan.md", "verification-plan.md")]
files = [Path(__file__).resolve()]
for name in (
    "update_checkout_progress_v1.py", "apply_controller_lf_attributes_v1.py",
    "verify_checkout_byte_freeze_v9.py", "byte_freeze_tiny_git_controller_regression_v3.py",
    "capture_corrected_checkout_terminal_v1.py", "inspect_unchanged_native_worker_images_v1.py",
    "capture_unchanged_image_inspection_terminal_v1.py", "controller-lf-verifier-next-api.v2.md",
    "checkout-byte-freeze-independent-review.v4.json", "unchanged-image-metadata-independent-review.v1.json",
    "byte-freeze-attributes-preparation.v2.json", "byte-freeze-attributes-preparation.attempt-01.stderr.log",
):
    files.append(base / name)
for prefix in (
    "controller-lf-attributes-preparation.v1.", "byte-freeze-tiny-git-controller-regression.v3.",
    "byte-freeze-fresh-checkouts.v7.", "byte-freeze-corrected-closed-execution.v1.",
    "unchanged-native-worker-live-inspection.v1.", "unchanged-native-worker-live-inspection.closed.v1.",
):
    matches = sorted(base.glob(prefix + "*"))
    assert matches
    files.extend(matches)
directory = base / "unchanged-native-worker-live-inspection-v1"
assert directory.is_dir()
files.extend(path for path in directory.rglob("*") if path.is_file() and "__pycache__" not in path.parts)
for name in ("original-artifact.zip", "original-job.log", "job-api-observation.v1.json"):
    files.append(base / "cpu-ci-run-36656805742" / name)
paths = sorted(set(docs + [path.relative_to(root).as_posix() for path in files]))
assert len(paths) < 100
assert set(initial_staged) <= set(paths)
assert all((root / name).is_file() and not (root / name).is_symlink() for name in paths)
assert not any("decoder-research-implementation-v2/" in name or "decoder-research-attempt-02/" in name for name in paths)
pins = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in paths}
subprocess.run(["git", "add", "--", *docs], check=True)
subprocess.run(["git", "add", "-f", "--", *[name for name in paths if name not in docs]], check=True)
staged = subprocess.check_output(["git", "diff", "--cached", "--name-only"], text=True).splitlines()
assert set(staged) <= set(paths) and set(docs) <= set(staged)
assert ".gitattributes" not in staged
assert not any(name.startswith(("scripts/", "deploy/", "tests/", ".github/")) for name in staged)
for name, expected in pins.items():
    assert hashlib.sha256((root / name).read_bytes()).hexdigest() == expected
    raw = subprocess.check_output(["git", "show", ":" + name])
    assert hashlib.sha256(raw).hexdigest() == expected, "index bytes differ: " + name
for name in ("proposal.md", "design.md", "specs/benchmark-launch-preparation/spec.md"):
    relative = change + name
    expected = subprocess.check_output(["git", "show", "47e432f2b5c09f750a55f7eb0164d84cc4d7e658:" + relative])
    assert (root / relative).read_bytes() == expected
raw_log = "artifacts/benchmark_recovery_20260930/cpu-ci-run-36656805742/original-job.log"
subprocess.run(["git", "-c", "core.whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol",
                "diff", "--cached", "--check", "--", *[name for name in paths if name != raw_log]], check=True)
print(f"Closed checkout/progress stage: {len(staged)} owned paths, {len(docs)} progress documents; all physical/index bytes equal, core requirements/design unchanged47e.")
