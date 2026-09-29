"""Stage an explicit recovery scope while preserving unrelated working files."""
from pathlib import Path
import hashlib
import json
import subprocess
import sys

root = Path.cwd()
scripts = ["checkpoint_admission", "checkpoint_deepstream_container_runtime_v3",
    "checkpoint_deepstream_publication_runtime_v3", "checkpoint_gstreamer_analytics_sidecar",
    "checkpoint_gstreamer_publication_runtime_v3", "checkpoint_gstreamer_runtime",
    "checkpoint_native_policy_runtime", "checkpoint_openvino_gva_publication_runtime_v3",
    "checkpoint_runtime", "checkpoint_savant_container_runtime_v3", "checkpoint_savant_publication_runtime_v3",
    "full_resource_qualification", "full_resource_qualification_index_v1",
    "publication_guardian_accepted_policy_preprocessing_contract_v1", "publication_policy_qualification",
    "publication_policy_qualification_execution_closure_v1", "publication_policy_qualification_execution_code_closure_v1",
    "publication_policy_qualification_index_v2", "publication_policy_qualification_pilot_executor_v2",
    "publication_policy_qualification_runtime_inputs_v2", "publication_operational_stock_operations_v1",
    "publication_operational_runtime_context_v1", "publication_operational_request_reconciliation_v1",
    "publication_operational_request_domain_v1", "publication_operational_process_custody_v1",
    "publication_operational_container_custody_v1", "publication_operational_capture_plan_v1",
    "publication_guardian_operational_recorder_v1", "publication_benchmark_native_diagnostic_v1"]
tests = ["checkpoint_operational_admission_guard_v1", "publication_operational_pilot_custody_v1",
    "publication_operational_execution_binding_v1", "publication_operational_container_custody_v1",
    "publication_operational_capture_plan_v1", "publication_operational_boundary_v1",
    "publication_guardian_operational_recorder_v1", "publication_benchmark_native_diagnostic_v1",
    "publication_operational_runtime_input_binding_v1", "publication_operational_runtime_context_v1",
    "publication_operational_request_domain_v1", "publication_operational_process_custody_v1",
    "publication_operational_stock_request_v1", "publication_operational_stock_operations_v1",
    "publication_operational_wrapper_composition_v1", "publication_worker_termination_facts_v1",
    "publication_runtime_original_process_hooks_v1", "qualification_complete_operational_promotion_gate_v1",
    "qualification_operational_closure_cold_gate_v1", "publication_policy_qualification",
    "full_resource_qualification", "publication_policy_qualification_index_v2", "full_resource_qualification_index_v1",
    "publication_guardian_accepted_policy_preprocessing_contract_v1"]
paths = [*("scripts/" + name + ".py" for name in scripts),
    *("tests/test_" + name + ".py" for name in tests),
    "deploy/deepstream/checkpoint/Dockerfile.runtime", "deploy/deepstream/checkpoint/runtime-source-allowlist.txt",
    "deploy/gstreamer_custom/publication/Dockerfile", "deploy/gstreamer_custom/publication/runtime-source-allowlist.txt",
    "deploy/openvino_gva/publication/Dockerfile", "deploy/openvino_gva/publication/runtime-source-allowlist.txt",
    "deploy/savant/publication/Dockerfile", "deploy/savant/publication/runtime-source-allowlist.txt",
    "BENCHMARK_RECOVERY_PLAN.md", "openspec/changes/fix-benchmark-preparations-spec/tasks.md"]
assert len(paths) == len(set(paths)) and all((root / name).is_file() for name in paths)
before = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
assert before == "0cf5f946100db8d3844ae1b6352058eada5f6f92"
resume = sys.argv[1:] == ["--resume-stage"]
already = set(subprocess.check_output(["git", "diff", "--cached", "--name-only"], text=True).splitlines())
assert all(name in paths or name.startswith("artifacts/benchmark_recovery_20260929/") for name in already)
assert resume or not already
source_files = [{"path": name, "size_bytes": len(raw := (root / name).read_bytes()),
    "sha256": hashlib.sha256(raw).hexdigest()} for name in paths]
value = {"schema_version": 1, "artifact_kind": "vast_explicit_owned_recovery_source_freeze_v1",
    "head_before": before, "branch": "codex/fix-benchmark-preparations-spec", "source_files": source_files,
    "owned_evidence_directory": "artifacts/benchmark_recovery_20260929",
    "excluded_unrelated_dirty_files_are_preserved": True, "image_build_started": False,
    "benchmark_started": False, "qualification_acceptance": False, "publication_acceptance": False}
path = Path(__file__).parent / "owned-source-freeze.v1.json"
raw = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")
if resume:
    assert path.read_bytes() == raw
else:
    with path.open("xb") as stream:
        stream.write(raw)
if sys.argv[1:] in (["--stage"], ["--resume-stage"]):
    subprocess.run(["git", "add", "--", *paths], check=True)
    evidence = sorted(file.relative_to(root).as_posix() for file in path.parent.rglob("*")
        if file.is_file() and "__pycache__" not in file.parts and file.suffix != ".pyc")
    subprocess.run(["git", "add", "-f", "--", *evidence], check=True)
    staged = set(subprocess.check_output(["git", "diff", "--cached", "--name-only"], text=True).splitlines())
    assert all(name in paths or name.startswith("artifacts/benchmark_recovery_20260929/") for name in staged)
    for row in source_files:
        index_bytes = subprocess.check_output(["git", "show", ":" + row["path"]])
        assert hashlib.sha256(index_bytes).hexdigest() == row["sha256"], row["path"] + " index/source bytes differ"
    subprocess.run(["git", "-c", "core.whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol",
        "diff", "--cached", "--check", "--", *paths], check=True)
    print(json.dumps({"source_files": len(paths), "staged_files": len(staged),
        "freeze_sha256": hashlib.sha256(raw).hexdigest(), "index_source_bytes_identical": True}))
else:
    assert not sys.argv[1:]
    print(json.dumps({"freeze_sha256": hashlib.sha256(raw).hexdigest(), "staged": False}))
