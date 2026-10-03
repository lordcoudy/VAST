"""Read the original cancelled CI ZIP/log only; never execute repository tests."""
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import time
import zipfile

sys.dont_write_bytecode = True
ROOT = Path("/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec")
HERE = ROOT / "artifacts/benchmark_recovery_20260930"
PREFIX = "artifacts/benchmark_recovery_20260930/cpu-ci-run-36656805742/"
sys.path.insert(0, str(HERE))
from verify_checkout_byte_freeze_v9 import Held, process_observation, require, write_new

SELECTED = {"native-configure.json", "native-build.json", "native-build.stdout",
    "tracked-source.before.json", "specification-inventory.json", "unittest.original.log"}
SOURCE_NAMES = (
    ".github/workflows/ci.yml", ".gitignore", "scripts/run_ci_checks.py",
    "tests/test_analytics_model_contract.py", "scripts/analytics_model_contract.py",
    "configs/checkpoint_analytics_models_openvino.yaml", "tests/test_analytics_peer_identity.py",
    "scripts/checkpoint_gstreamer_analytics_sidecar.py",
    "tests/test_backend_publication_output_transaction_production_v3.py",
    "scripts/backend_publication_output_transaction_production_v3.py",
    "scripts/backend_publication_process_supervisor_v3.py",
    "scripts/backend_publication_launcher_invocation_v3.py",
    "tests/fixtures/backend_publication_v3_process_fixture.py",
)

with Held(ROOT) as held:
    archive_name = PREFIX + "original-artifact.zip"
    archive_pin = held.pin(archive_name)
    require(archive_pin["size_bytes"] == 895268 and archive_pin["sha256"] ==
        "f58af824528480bd059d3e3f762fdbb579edd3a86f4644354a630483657c6425", "original CI ZIP identity")
    raw = held.raw(archive_name)
    selected, inventory = {}, []
    with zipfile.ZipFile(io.BytesIO(raw), "r") as archive:
        infos = archive.infolist()
        require(len(infos) == 106 and sum(row.file_size for row in infos) <= 16777216, "ZIP cardinality/total bound")
        names = set()
        for row in infos:
            path = PurePosixPath(row.filename)
            mode = row.external_attr >> 16
            require(row.filename not in names and row.filename == path.as_posix() and not path.is_absolute()
                and ".." not in path.parts and "\\" not in row.filename and ":" not in row.filename
                and "\0" not in row.filename and not row.is_dir()
                and stat.S_IFMT(mode) in (0, stat.S_IFREG) and not stat.S_ISLNK(mode)
                and row.file_size <= 2097152 and row.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
                and not row.flag_bits & 1, "ZIP member unsafe/unsupported/oversize")
            names.add(row.filename)
            digest, size = hashlib.sha256(), 0
            body = bytearray() if row.filename in SELECTED else None
            with archive.open(row, "r") as stream:
                while chunk := stream.read(65536):
                    size += len(chunk)
                    require(size <= row.file_size and size <= 2097152, "ZIP decoded member bound")
                    digest.update(chunk)
                    if body is not None:
                        body.extend(chunk)
            require(size == row.file_size, "ZIP member decoded size")
            inventory.append({"member": row.filename, "size_bytes": size, "compressed_size_bytes": row.compress_size,
                "sha256": digest.hexdigest(), "unix_mode": mode, "crc32": row.CRC})
            if body is not None:
                selected[row.filename] = bytes(body)
        require(SELECTED <= names, "original diagnostic members missing")
    before = json.loads(selected["tracked-source.before.json"])
    source_pins, current_source_observations = [], []
    commit = "1f19a1eb8f8a9f24ba6e6e6f8e4915dc735e2085"
    argv = ["git", "--git-dir=/mnt/e/STUDY/VAST/.git/worktrees/fix-benchmark-preparations-spec",
        "--work-tree=" + str(ROOT), "cat-file", "--batch"]
    git = subprocess.run(argv, input="".join(commit + ":" + name + "\n" for name in SOURCE_NAMES).encode("ascii"),
        cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20,
        env=dict(os.environ, GIT_OPTIONAL_LOCKS="0"), check=False)
    require(git.returncode == 0 and len(git.stdout) <= 2097152 and not git.stderr, "original source blob read failed")
    original_blob_observation = {"argv": argv, "returncode": git.returncode,
        "stdout": {"size_bytes": len(git.stdout), "sha256": hashlib.sha256(git.stdout).hexdigest()},
        "stderr": {"size_bytes": len(git.stderr), "sha256": hashlib.sha256(git.stderr).hexdigest()},
        "timeout_seconds": 20}
    cursor = 0
    for name in SOURCE_NAMES:
        end = git.stdout.index(b"\n", cursor)
        oid, kind, size_text = git.stdout[cursor:end].split()
        require(kind == b"blob" and len(oid) == 40 and size_text.isdigit(), "original Git blob framing")
        size = int(size_text)
        body = git.stdout[end + 1:end + 1 + size]
        require(len(body) == size and git.stdout[end + 1 + size:end + 2 + size] == b"\n", "original blob size")
        cursor = end + 2 + size
        original_pin = {"path": name, "size_bytes": size, "sha256": hashlib.sha256(body).hexdigest()}
        require({key: original_pin[key] for key in ("size_bytes", "sha256")} == before[name],
            "exact original commit blob differs from original hosted manifest")
        actual = held.pin(name)
        require(held.raw(name).replace(b"\r\n", b"\n") == body.replace(b"\r\n", b"\n"),
            "current diagnostic source has semantic changes; use original-only analysis")
        source_pins.append(original_pin)
        current_source_observations.append({"current_physical_descriptor": actual,
            "original_commit_descriptor": original_pin, "exact_physical_equal": actual == original_pin,
            "CR_at_EOL_equivalent": held.raw(name).replace(b"\r\n", b"\n") == body.replace(b"\r\n", b"\n")})
    require(cursor == len(git.stdout), "extra original Git blob records")
    job_name = PREFIX + "original-job.log"
    log = held.raw(job_name).decode("utf-8", "strict")
    api = json.loads(held.raw(PREFIX + "job-api-observation.v1.json"))
    observed_job = api["response"]["structuredContent"]["jobs"][0]
    require(observed_job["id"] == 109702786688 and observed_job["run_id"] == 36656805742
        and observed_job["status"] == "completed" and observed_job["conclusion"] == "cancelled", "original job state")
    test_log = selected["unittest.original.log"].decode("utf-8", "strict")
    entries = []
    for number, line in enumerate(test_log.splitlines(), 1):
        match = re.fullmatch(r"(\S+) \(([^)]+)\) \.\.\. (.*)", line)
        require(match is not None, "unexpected original unittest log line")
        entries.append({"ordinal": number, "test_id": match[2], "method": match[1],
            "status": match[3].split(" ", 1)[0] if match[3] else "unfinished",
            "original_status": match[3]})
    counts = {status: sum(row["status"] == status for row in entries)
        for status in ("ok", "skipped", "FAIL", "ERROR", "unfinished")}
    require(len(entries) == 134 and counts == {"ok": 120, "skipped": 2, "FAIL": 2, "ERROR": 9, "unfinished": 1},
        "original observed test counts")
    native = {name: json.loads(selected[name]) for name in ("native-configure.json", "native-build.json")}
    require(all(row["returncode"] == 0 and row["timed_out"] is False for row in native.values()), "native build not successful")
    require("2026-09-30T03:17:55.9156581Z ##[error]The operation was canceled." in log
        and "Terminate orphan process: pid (3376) (python)" in log, "original cancellation/cleanup observations")
    require("report.json" not in names and "tracked-source.after.json" not in names, "terminal reports unexpectedly present")
    held.pin(Path(__file__).relative_to(ROOT).as_posix())
    held.verify()
    report = {
        "schema_version": 1, "artifact_kind": "vast_closed_cpu_ci_artifact_diagnosis_v1", "accepted": False,
        "classification": "original cancelled hosted CPU evidence, bounded local read only; no rerun or cause assertion",
        "run_id": 36656805742, "job_id": 109702786688, "commit": "1f19a1eb8f8a9f24ba6e6e6f8e4915dc735e2085",
        "original_archive": archive_pin, "original_job_log": held.pin(job_name),
        "original_job_api_observation": held.pin(PREFIX + "job-api-observation.v1.json"),
        "zip_safety": {"extracted_members": 0, "member_count": len(inventory),
            "decoded_total_bytes": sum(row["size_bytes"] for row in inventory),
            "limits": {"members": 256, "per_member_bytes": 2097152, "decoded_total_bytes": 16777216},
            "all_member_crc_reads_completed": True, "no_duplicate_escape_symlink_encryption": True},
        "member_inventory": inventory, "native_commands": native, "observed_test_counts": counts,
        "observed_failed_and_error_tests": [row for row in entries if row["status"] in ("FAIL", "ERROR")],
        "observed_skips": [row for row in entries if row["status"] == "skipped"],
        "unfinished_test": dict(entries[-1], source_file="tests/test_backend_publication_output_transaction_production_v3.py",
            source_line=588, last_log_line=test_log.splitlines()[-1]),
        "missing_original_terminal_members": ["report.json", "tracked-source.after.json"],
        "cancellation": {"original_job_status": "completed", "original_job_conclusion": "cancelled",
            "original_log_timestamp": "2026-09-30T03:17:55.9156581Z", "orphan_python_pid": 3376,
            "workflow_timeout_minutes": 90, "driver_step_started": "2026-09-30T01:48:40.3748781Z",
            "per_test_start_and_duration_unknown": True},
        "source_grounded_prerequisites_and_limits": [
            {"finding": "repository-manifest test unconditionally validates ignored model XML/BIN files",
                "test": "tests/test_analytics_model_contract.py:190",
                "config": "configs/checkpoint_analytics_models_openvino.yaml:28",
                "validator": "scripts/analytics_model_contract.py:70", "ignore": ".gitignore:27",
                "evidence": "all eight configured model/weight paths lie under models/; model files are absent from the tracked-source manifest; workflow installs CPU packages but contains no model provisioning step",
                "scope": "concrete clean-checkout prerequisite gap; original exception traceback is unavailable"},
            {"finding": "peer-observer test mocks Docker but reads the actual kernel osrelease and expects a WSL2 profile",
                "test": "tests/test_analytics_peer_identity.py:246",
                "reader": "scripts/checkpoint_gstreamer_analytics_sidecar.py:1380",
                "marker_validator": "scripts/checkpoint_gstreamer_analytics_sidecar.py:1224",
                "scope": "concrete host-dependent test; actual hosted kernel bytes and original exception are not in this artifact"},
            {"finding": "POSIX production tests execute actual held Python/fixture and Linux user/mount/PID namespace setup",
                "test_setup": "tests/test_backend_publication_output_transaction_production_v3.py:78",
                "unfinished_method": "tests/test_backend_publication_output_transaction_production_v3.py:588",
                "namespace": "scripts/backend_publication_process_supervisor_v3.py:2344",
                "durable_owner_wait": "scripts/backend_publication_process_supervisor_v3.py:3206",
                "process_monitor": "scripts/backend_publication_process_supervisor_v3.py:3239",
                "frozen_child_timeout_ms": 600000,
                "scope": "requires actual host namespace, privilege-drop, procfs and held-executable custody; runner capability probe/traceback/stack absent, so no root-cause claim"},
            {"finding": "driver runs full unittest discovery in process and writes failure tracebacks/report only after suite returns",
                "driver": "scripts/run_ci_checks.py:232", "result": "scripts/run_ci_checks.py:110",
                "terminal_report": "scripts/run_ci_checks.py:255",
                "scope": "no outer suite deadline or per-test timestamp/stack dump; forced cancellation leaves preceding failures without details"}],
        "diagnostic_recommendation": "Before changing test selection or adding skips, capture immediate bounded failure tracebacks and current-test timestamps/stack for focused diagnostics; preserve mandatory CPU native regressions and distinguish fixture tests from declared real environment prerequisites.",
        "cause_status": "unknown exact blocking instruction and earlier exception causes; cancellation and incomplete last test are observed",
        "original_diagnostic_source_blobs_equal_hosted_manifest": source_pins,
        "current_physical_diagnostic_source_observations": current_source_observations,
        "original_commit_blob_read": original_blob_observation,
        "preserved_first_reader_failure": {
            "observer": held.pin("artifacts/benchmark_recovery_20260930/diagnose_closed_cpu_ci_artifact_v1.py"),
            "stdout": held.pin("artifacts/benchmark_recovery_20260930/closed-cpu-ci-artifact-diagnosis.v1.stdout.log"),
            "stderr": held.pin("artifacts/benchmark_recovery_20260930/closed-cpu-ci-artifact-diagnosis.v1.stderr.log"),
            "original_tool_chunk": "d8e735", "original_tool_exit_code": 1,
            "reason": "current physical .gitignore differs from hosted source bytes",
            "original_json_emitted": False},
        "validated_inputs": held.witnesses(), "controller": process_observation(os.getpid()), "observed_at_ns": time.time_ns(),
    }
    print(json.dumps(write_new(HERE / "closed-cpu-ci-artifact-diagnosis.v2.json", report), sort_keys=True))
