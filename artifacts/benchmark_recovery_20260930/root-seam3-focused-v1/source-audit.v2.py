"""Read-only actual dependency audit and author source-review receipt."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT / "artifacts/benchmark_recovery_20260930"
sys.path.insert(0, str(ROOT / "scripts"))
from publication_image_build_v1 import publication_image_build_plan
from publication_qualification_image_refreeze_v1 import qualification_image_refreeze_plan
from publication_policy_qualification_execution_code_closure_v1 import _discover_sources

OWNED = (
    "scripts/publication_gstreamer_component_runtime_v1.py",
    "tests/test_publication_gstreamer_component_runtime_v1.py",
    "scripts/publication_owned_staging_cleanup_v1.py",
    "scripts/publication_policy_qualification_execution_code_closure_v1.py",
    "deploy/gstreamer_custom/publication/Dockerfile",
    "deploy/gstreamer_custom/publication/runtime-source-allowlist.txt",
)


def facts(path):
    raw = path.read_bytes()
    return {"path": path.relative_to(ROOT).as_posix(), "size_bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest()}


destination = BASE / "root-seam3-author-review-v2"
destination.mkdir(exist_ok=False)
before = {path: facts(ROOT / path) for path in OWNED}
execution_path = BASE / "root-seam3-focused-v1/attempt-03-final/execution.json"
execution = json.loads(execution_path.read_bytes())
assert execution["returncode"] == 0 and not execution["timed_out"]
assert execution["source_before_after_equal"] and all(execution["quiescence"].values())
assert all(execution["after"][path] == {k: row[k] for k in ("size_bytes", "sha256")}
           for path, row in before.items())

native = publication_image_build_plan(project_root=ROOT,
    registry_path=ROOT / "configs/publication_image_build_v1.json")
prior = json.loads((BASE / "gstreamer-component-seam1-v1/implementation-summary.v1.json").read_bytes())
prior_rows = {row["name"]: row for row in prior["unchanged_native3_worker2"]}
native_rows = []
for row in native["images"]:
    hashes = {key: row[key] for key in ("source_set_sha256", "dependency_set_sha256", "build_context_sha256")}
    assert hashes == prior_rows[row["name"]]["hashes"]
    assert len(row["relative_paths"]) == prior_rows[row["name"]]["member_count"]
    native_rows.append({"name": row["name"], "hashes": hashes, "member_count": len(row["relative_paths"]),
                        "current_source_context_equal": True, "current_live_image_verified": False})

runtime_plan = qualification_image_refreeze_plan(project_root=ROOT,
    registry_path=ROOT / "configs/publication_qualification_image_refreeze_v1.json")
selected = next(row for row in runtime_plan["systems"] if row["system"] == "gstreamer_custom")
allowlist_path = ROOT / "deploy/gstreamer_custom/publication/runtime-source-allowlist.txt"
allowlist = [line for line in allowlist_path.read_text().splitlines() if line and not line.startswith("#")]
docker_raw = (ROOT / "deploy/gstreamer_custom/publication/Dockerfile").read_text()
assert all(path in docker_raw for path in allowlist if path != "deploy/gstreamer_custom/publication/Dockerfile")
new_imports = ("scripts/publication_gstreamer_component_authority_v1.py",
               "scripts/publication_guardian_component_preprocessing_contract_v1.py")
assert all(path in allowlist for path in new_imports)
host_sources = [facts(path) for _module, path in _discover_sources(ROOT)]
assert all(path in {row["path"] for row in host_sources} for path in (
    "scripts/publication_gstreamer_component_cli_v1.py", "scripts/publication_gstreamer_component_runtime_v1.py",
    "scripts/publication_gstreamer_component_authority_v1.py", "scripts/publication_gstreamer_component_inputs_v1.py",
    "scripts/publication_guardian_component_preprocessing_contract_v1.py"))

# This is the historical committed blob, not a fabricated pre-edit physical capture.
old = subprocess.run(["git", "-c", "core.longpaths=true", "show",
    "ded811a8043575e7a93cf0bbc28696ac53667d3c:scripts/publication_owned_staging_cleanup_v1.py"],
    cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True).stdout
original_path = destination / "owned-staging-ded811a8-original-committed.raw"
original_path.write_bytes(old)
assert before == {path: facts(ROOT / path) for path in OWNED}
receipt = {
    "schema_version": 1, "artifact_kind": "vast_root_component_executor_source_author_review_v1",
    "planning_commit": "9ad1a52b38cd5028de6b04bcc08192309ef192cf",
    "review_authorization": "https://github.com/lordcoudy/VAST/pull/2#issuecomment-5907711751",
    "owned_sources": before, "frozen_for_independent_review": True,
    "focused_execution": facts(execution_path), "tests": 24, "unittest_elapsed_s": 3.688,
    "original_pid": execution["dispatch"]["pid"], "controller_elapsed_s": execution["elapsed_s"],
    "source_before_after_equal": True, "original_quiescence": execution["quiescence"],
    "raw_channels": [facts(execution_path.parent / name) for name in ("stdout.bin", "stderr.bin")],
    "host_closure_actual_sources": host_sources,
    "selected_runtime_source_plan": selected,
    "selected_runtime_actual_sources": [facts(ROOT / path) for path in allowlist],
    "new_selected_imports": list(new_imports), "native3_worker2": native_rows,
    "owned_staging_historical_blob": facts(original_path),
    "initial_capture_limits": [
        "First direct failing fixture/API test was tool-output-only with no persistent original PID/source channels; no retrospective capture is asserted.",
        "Attempts01/02 retain original outer WSL channels/exit code but no original inner PID/source inventory; attempt03 supplies the actual final24 scoped custody.",
        "OwnedStaging optional bound was added without a physical pre-edit inventory; the exact historical committed blob is separately retained and labeled."],
    "self_review": [
        "Reuse the exact original native runtime-input factories and reconstruct all selected inputs on read, rather than accepting a caller-sealed runtime dictionary.",
        "Hold actual selected input leaves, generated preprocessing, all guardian journals and original child/hardware evidence through receipt creation; reject same-byte replacement.",
        "Use original process/container custody, acceptance preparation and all-phase reconciliation without invoking a full-run finalizer or aggregate qualification grant.",
        "Compare the original measurement schedule fingerprints; cohort IDs are arm-local and include run/time, so requiring identical cohort strings would reject every honest pair.",
        "Export observed completed latency ECDF and separate deadline/drop/coverage metrics, with null ratios for non-positive denominators; one pair supports no population inference."],
    "limits": [
        "No actual selected image rebuild, live worker/guardian/model/GPU or benchmark measurement occurs in these unit/dependency checks.",
        "Local units explicitly replace costly live image/service acceptance; actual original runtime execution/cold validation is still required.",
        "Other three runtime images share changed modules and remain historical/ineligible; their missing new imports are not silently granted by selected packaging.",
        "Native3/worker2 physical source contexts remain exact; current daemon image identities still require original inspection.",
        "New component source paths are outside historical165 attributes; actual index/commit byte equality must be checked independently."],
    "publication_ready": False, "qualification_ready": False, "hardware_acceptance": False,
}
target = destination / "review.v1.json"
with target.open("x", encoding="utf-8", newline="\n") as output:
    json.dump(receipt, output, sort_keys=True, separators=(",", ":")); output.write("\n")
print(json.dumps({"receipt": facts(target), "host_source_count": len(host_sources),
                  "selected_runtime_source_count": len(allowlist), "native3_worker2_equal": True}))
