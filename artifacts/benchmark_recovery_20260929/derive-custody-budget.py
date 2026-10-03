"""Source-derived supplement; no execution or publication authority."""
from pathlib import Path
import hashlib
import json
import resource
import sys

root = Path.cwd()
sys.path.insert(0, str(root / "scripts"))
import publication_operational_process_custody_v1 as process
import publication_operational_container_custody_v1 as container
import publication_operational_request_reconciliation_v1 as cold

names = ("scripts/publication_operational_process_custody_v1.py",
    "scripts/publication_operational_container_custody_v1.py",
    "scripts/publication_policy_qualification_execution_closure_v1.py",
    "scripts/publication_operational_request_reconciliation_v1.py",
    "scripts/publication_operational_stock_operations_v1.py",
    "scripts/publication_benchmark_native_diagnostic_v1.py",
    "scripts/publication_policy_qualification_execution_code_closure_v1.py")
sources = [{"path": name, "size_bytes": len(raw := (root / name).read_bytes()),
    "sha256": hashlib.sha256(raw).hexdigest()} for name in names]
per_call = process.MAX_LAUNCH_BYTES + process.MAX_TERMINAL_BYTES
process_bytes = process.MAX_CALLS * per_call + process.MAX_RECEIPT_BYTES
container_bytes = container.MAX_COMMANDS * (container.MAX_FACT_BYTES +
    2 * container.MAX_OUTPUT_FACT_BYTES) + 2 * container.MAX_FACT_BYTES + 65
transfer_bytes = 4 * process.MAX_TRANSFER_METADATA_BYTES
per_operation = process_bytes + container_bytes + transfer_bytes
# Successful process custody: receipt/original/context + two leaves/call,
# four transfer metadata leaves, final native domain, up to one engine/call.
# Successful container custody: reservation/receipt/CID + three leaves/command.
# The full cold controller holds only accepted four-command container captures.
per_operation_leaves = 3 + 2 * process.MAX_CALLS + 4 + 1 + process.MAX_CALLS + 3 + 3 * 4
fd_bound = 37 * per_operation_leaves + 1024
soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
assert fd_bound < soft
value = {"schema_version": 1, "artifact_kind": "vast_source_derived_original_custody_budget_v1",
    "source_files": sources,
    "scope": "supplement_to_frozen_operational_budget_not_runtime_acceptance",
    "supersedes": {"path": "artifacts/benchmark_recovery_20260929/custody-budget-supplement.v1.json",
        "reason": "Independent review corrected two output facts per container observation and removed nonexistent raw process capture files from disk/FD counts."},
    "operational_budget": {"path": "artifacts/benchmark_recovery_20260929/operational-budget-proof.v1.json",
        "sha256": hashlib.sha256((root / "artifacts/benchmark_recovery_20260929/operational-budget-proof.v1.json").read_bytes()).hexdigest()},
    "bounds": {"original_operations": 37, "process_calls_per_operation": process.MAX_CALLS,
        "process_capture_bytes_per_stdout_or_stderr": process.MAX_CAPTURE_BYTES,
        "process_captures_are_digest_only_terminal_fields": True,
        "process_namespace_bytes_per_operation": process_bytes,
        "container_observations_per_operation_including_failed_cleanup": container.MAX_COMMANDS,
        "container_namespace_bytes_per_operation": container_bytes,
        "transfer_metadata_bytes_per_operation": transfer_bytes,
        "custody_namespaces_bytes_per_operation": per_operation,
        "all_37_custody_namespaces_bytes": 37 * per_operation,
        "guardian_and_native_journal_caps_are_separate": True,
        "successful_cold_operation_leaf_upper_bound": per_operation_leaves,
        "cold_37_leaf_fds_plus_1024_controller_allowance": fd_bound,
        "observed_rlimit_nofile_soft": soft, "observed_rlimit_nofile_hard": hard},
    "cold_memory_design": ["No 37 decoded process/container summaries or frame maps are retained.",
        "Original CLI stdout/stderr and final native domain are streamed and digest-checked.",
        "Controller retains descriptors, epochs and file descriptors through the final join.",
        "Container cold validator reads one bounded observation at a time.",
        "Existing fixed-key index budgets and temporary-file limits remain unchanged."],
    "physical_limits": ["This supplement is a namespace worst case, not a measured full-run storage requirement.",
        "Q4 and full-run disk admission must include these separate namespaces.",
        "No new model inference, container build, qualification or benchmark was run.",
        "Serialized bounds do not establish a total process RSS measurement."],
    "publication_authority": False}
raw = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")
path = Path(__file__).parent / "custody-budget-supplement.v2.json"
with path.open("xb") as stream:
    stream.write(raw)
print(json.dumps({"path": str(path.relative_to(root)), "sha256": hashlib.sha256(raw).hexdigest(),
    "worst_case_bytes": 37 * per_operation, "fd_bound": fd_bound, "observed_soft_limit": soft}))
