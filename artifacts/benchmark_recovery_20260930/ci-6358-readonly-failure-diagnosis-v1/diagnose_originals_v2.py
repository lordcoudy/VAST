"""Fixed original archive/source comparison; no tests, project imports or engines."""
import collections
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
RETAIN = ROOT / "artifacts/benchmark_recovery_20260930/ci-6358-original-retention-v1"
COMMIT = "6358c42cf1b969fb7ac2aa7be51929c3da46b9af"
OLD_COMMIT = "2f40946589254b3698eebedadb4b9d578f297deb"
RUN = 36743387786

def seal(value):
    return {**value, "sha256": hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()}

def descriptor(path):
    raw = Path(path).read_bytes()
    return {"path": Path(path).relative_to(ROOT).as_posix(), "size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}

def save(path, value):
    with Path(path).open("xb") as stream:
        stream.write(json.dumps(value, sort_keys=True, indent=2).encode() + b"\n")
        stream.flush()
        os.fsync(stream.fileno())

def epoch(info):
    return [info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns]

class OriginalArchive:
    def __init__(self, path, expected_sha):
        self.path = path
        self.fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        self.original = epoch(os.fstat(self.fd))
        assert stat.S_ISREG(self.original[2]) and self.original[3] == 1 and self.original == epoch(path.lstat())
        self.stream = os.fdopen(self.fd, "rb", closefd=False)
        self.descriptor = descriptor(path)
        assert self.descriptor["sha256"] == expected_sha
        self.archive = zipfile.ZipFile(self.stream)
        self.entries = {}
        self.verify()
    def verify(self):
        assert self.original == epoch(os.fstat(self.fd)) == epoch(self.path.lstat())
    def read(self, name, maximum=4 * 1024 * 1024):
        info = self.archive.getinfo(name)
        assert 0 <= info.file_size <= maximum
        raw = self.archive.read(info)
        assert len(raw) == info.file_size
        self.entries[name] = {"archive": self.descriptor, "entry": name, "size_bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(), "crc32": info.CRC, "complete_original_read_crc_verified": True}
        self.verify()
        return raw
    def document(self, name):
        return json.loads(self.read(name))
    def close(self):
        self.verify()
        self.archive.close()
        self.stream.close()
        os.close(self.fd)

metadata = json.loads((RETAIN / "provider-metadata.v1.json").read_bytes())
assert metadata["run_id"] == RUN and metadata["source_commit"] == COMMIT
assert all(row["workflow_run"]["head_sha"] == COMMIT for row in metadata["artifacts"])
cpu = OriginalArchive(RETAIN / (str(RUN) + "-cpu/original-artifact.zip"),
                      "8d2eef0bcdcf0dbfcf3dad801deb91c9c4c3ab525ebd0453d797f9e29fdcbf8f")
host = OriginalArchive(RETAIN / (str(RUN) + "-host/original-artifact.zip"),
                       "b5b2dd9b54a1e2974969bb8a53d449ced217f0f9703b2440ae9311a93f3d3c2e")
old = OriginalArchive(ROOT / "artifacts/benchmark_recovery_20260930/ci-2f409-original-retention-v1/36735694943-cpu/original-artifact.zip",
                      "91dc59e7be790e0515259c424d5ae8ab956f6c931b7df383897a7f225ae36a33")
archives = (cpu, host, old)
try:
    current = cpu.document("unittest-child.report.json")
    previous = old.document("unittest-child.report.json")
    runner, prior_runner = cpu.document("report.json"), old.document("report.json")
    host_report = host.document("report.json")
    assert runner["commit"] == COMMIT
    cpu_before, cpu_after = cpu.document("tracked-source.before.json"), cpu.document("tracked-source.after.json")
    host_before, host_after = host.document("tracked-source.before.json"), host.document("tracked-source.after.json")
    assert cpu_before == cpu_after == host_before == host_after
    old_index_path = ROOT / "artifacts/benchmark_recovery_20260930/ci-2f409-readonly-failure-diagnosis-v1/failure-index.v1.json"
    old_review_path = ROOT / "artifacts/benchmark_recovery_20260930/ci-2f409-readonly-failure-diagnosis-v1/review.v1.json"
    previous_index = json.loads(old_index_path.read_bytes())
    prior_groups = {(row["category"], row["test_id"]): row["group"] for row in previous_index["rows"]}
    raw_log = cpu.read("unittest.original.log")
    failures = []
    for category in ("errors", "failures"):
        for ordinal, row in enumerate(current[category]):
            group = prior_groups.get((category, row["test_id"]), "new_original_failure_not_previously_classified")
            failures.append({"category": category, "test_id": row["test_id"], "group": group,
                "report_pointer": "/" + category + "/" + str(ordinal),
                "original_report": cpu.entries["unittest-child.report.json"],
                "traceback_sha256": hashlib.sha256(row["traceback"].encode()).hexdigest(),
                "original_final_exception": row["traceback"].strip().splitlines()[-1], "traceback": row["traceback"]})
    normalize = lambda value: value.split(" (", 1)[0]
    def methods(rows):
        return {normalize(row["test_id"]) for row in rows}
    old_errors, new_errors = methods(previous["errors"]), methods(current["errors"])
    old_failures, new_failures = methods(previous["failures"]), methods(current["failures"])
    allowed = {(row["test_id"], row["reason"]) for row in current["selection"]["allowed_portable_skips"]}
    unapproved = [row for row in current["skips"] if (row["test_id"], row["reason"]) not in allowed]
    assert current["skips"] == previous["skips"]
    assert current["selection"]["integration_declarations"] == previous["selection"]["integration_declarations"]
    new_discovered = sorted(set(current["discovered_ids"]) - set(previous["discovered_ids"]))
    assert len(new_discovered) == 2 and set(new_discovered) <= set(current["successful_test_ids"])
    assert not (set(previous["discovered_ids"]) - set(current["discovered_ids"]))
    assert not (new_errors - old_errors) and new_failures == old_failures
    native = json.loads(old_review_path.read_bytes())["original_cpu"]["mandatory_native_actual_success_ids"]
    assert set(native) <= set(current["successful_test_ids"])
    assert len(native) == 3 and not current["missing_required_successes"]
    observer = cpu.document("external-test-observer/terminal.v1.json")
    events = [json.loads(line) for line in cpu.read("external-test-observer/events.original.jsonl").splitlines()]
    responses = [json.loads(line) for line in cpu.read("external-test-observer/responses.original.jsonl").splitlines()]
    cpu.read("external-test-observer/launch.v1.json")
    cpu.read("external-test-observer/trace.original.log")
    namespace = cpu.document("namespace-diagnostic/capture.json")
    policy_denial = cpu.document("namespace-diagnostic/kernel-denial.json")
    kernel = cpu.document("namespace-diagnostic/kernel-query/capture.json")
    setup_events = [json.loads(line) for line in cpu.read("namespace-diagnostic/stdout.raw").splitlines()]
    cpu.read("namespace-diagnostic/stderr.raw")
    kernel_stdout = cpu.read("namespace-diagnostic/kernel-query/stdout.raw")
    kernel_stderr = cpu.read("namespace-diagnostic/kernel-query/stderr.raw")
    cpu.document("native-configure.json")
    cpu.document("native-build.json")
    acquisition = {"cpu": cpu.document("model-acquisition/report.json"),
                   "host": host.document("model-acquisition/report.json")}
    # Extract only committed source bytes needed for the finite diagnosis.
    paths = ("scripts/run_ci_checks.py", "scripts/ci_namespace_diagnostic_v1.py",
        "scripts/backend_publication_process_supervisor_v3.py", "scripts/ci_test_selection_v1.py",
        ".ci/integration-test-selection.v1.json", "tests/test_publication_gstreamer_component_runtime_v1.py",
        "tests/test_publication_operational_container_custody_v1.py")
    requests = [COMMIT + ":" + path for path in paths] + [OLD_COMMIT + ":" + paths[-1]]
    completed = subprocess.run(["/usr/bin/git", "--git-dir=/mnt/e/STUDY/VAST/.git/worktrees/fix-benchmark-preparations-spec",
        "--work-tree=" + str(ROOT), "cat-file", "--batch"], input=("\n".join(requests) + "\n").encode(),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30, check=True)
    assert not completed.stderr and len(completed.stdout) < 2 * 1024 * 1024
    offset, blobs = 0, {}
    for request in requests:
        end = completed.stdout.index(b"\n", offset)
        header = completed.stdout[offset:end].split()
        assert len(header) == 3 and header[1] == b"blob"
        size = int(header[2]); raw = completed.stdout[end + 1:end + 1 + size]
        assert len(raw) == size and completed.stdout[end + 1 + size:end + 2 + size] == b"\n"
        offset = end + 2 + size
        blobs[request] = raw
    assert offset == len(completed.stdout)
    source_refs = []
    for path in paths:
        raw = blobs[COMMIT + ":" + path]
        expected = {"sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw)}
        assert cpu_before[path] == expected
        target = OUT / "committed-source" / path
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        source_refs.append({"git_commit": COMMIT, "path": path, **expected,
            "matches_original_hosted_before_after": True, "snapshot": descriptor(target)})
    assert blobs[COMMIT + ":" + paths[-1]] == blobs[OLD_COMMIT + ":" + paths[-1]]
    namespace_source = blobs[COMMIT + ":scripts/ci_namespace_diagnostic_v1.py"].decode()
    source_anchors = [{"line": ordinal, "text": line.strip()} for ordinal, line in enumerate(namespace_source.splitlines(), 1)
        if any(token in line for token in ("journalctl", "--grep=", "sys_admin", "_observe_child", "sudo", "setgroups", "_enter_linux_namespaces"))]
    index = {"schema_version": 1, "kind": "vast_ci6358_original_finite_failure_index_v1", "accepted": False,
        "run_id": RUN, "source_commit": COMMIT, "rows": failures,
        "original_skips": current["skips"], "allowed_portable_skips": current["selection"]["allowed_portable_skips"],
        "exact_unapproved_skips": unapproved,
        "declared_unexecuted_integrations": current["selection"]["integration_declarations"],
        "raw_log": cpu.entries["unittest.original.log"], "report": cpu.entries["unittest-child.report.json"]}
    save(OUT / "failure-index.v1.json", seal(index))
    counts = {"discovered": len(current["discovered_ids"]), "portable": current["selection"]["counts"]["portable"],
        "integrations_unexecuted": current["selection"]["counts"]["integration"], "tests_run": current["tests_run"],
        "successful_method_ids": len(current["successful_test_ids"]), "error_rows": len(current["errors"]),
        "distinct_error_method_ids": len(new_errors), "failure_rows": len(current["failures"]),
        "skip_rows": len(current["skips"]), "original_allowed_skip_declarations": len(allowed),
        "original_unapproved_skips": len(unapproved), "groups": dict(collections.Counter(row["group"] for row in failures))}
    assert len(current["successful_test_ids"]) + len(new_errors) + len(new_failures) + len(current["skips"]) == current["tests_run"]
    review = {"schema_version": 1, "kind": "vast_ci6358_readonly_finite_diagnosis_v1", "accepted": False,
        "status": "closed_original_source_and_archive_review_only", "source_commit": COMMIT, "run_id": RUN,
        "provider_metadata": descriptor(RETAIN / "provider-metadata.v1.json"),
        "decoded_original_job_logs": [descriptor(RETAIN / (name + "-decoded-job.log")) for name in ("cpu", "host")],
        "original_retention_terminal": descriptor(RETAIN / "download-terminal.v1.json"),
        "original_archive_descriptors": {name: archive.descriptor for name, archive in (("cpu", cpu), ("host", host), ("prior_cpu", old))},
        "original_entry_descriptors": {"cpu": cpu.entries, "host": host.entries},
        "source_evidence": source_refs, "original_namespace_source_anchors": source_anchors,
        "failure_index": descriptor(OUT / "failure-index.v1.json"), "prior_diagnosis": descriptor(old_review_path),
        "prior_failure_index": descriptor(old_index_path), "counts": counts,
        "comparison": {"new_discovered_and_successful_ids": new_discovered,
            "no_removed_discovered_ids": True, "no_new_error_or_failure_method_ids": True,
            "prior_error_now_original_success": sorted(old_errors - new_errors),
            "prior_error_now_success_source_bytes_identical": True,
            "unapproved_skip_id_reason_pairs_identical": True, "nine_integration_declarations_identical": True,
            "prior_cpu_elapsed_s": prior_runner["elapsed_s"], "current_cpu_elapsed_s": runner["elapsed_s"],
            "elapsed_difference_s": runner["elapsed_s"] - prior_runner["elapsed_s"],
            "timing_limitation": "This is original hosted-job elapsed time; no storage, namespace, model or benchmark timing cause is inferred."},
        "original_cpu": {key: runner[key] for key in ("commit", "elapsed_s", "failure", "built_targets", "canonical_python", "python",
            "changed_tracked_paths", "raw_checkout_bytes_match_commit", "successful", "hardware_acceptance")},
        "mandatory_native_actual_success_ids": native,
        "original_child_failure": current["child_failure"], "missing_required_successes": current["missing_required_successes"],
        "original_source_before_after_equal": cpu_before == cpu_after == host_before == host_after,
        "original_tracked_source_count": len(cpu_before), "original_host_report": host_report,
        "original_namespace": namespace, "original_policy_denial": policy_denial,
        "original_kernel_query": kernel, "original_kernel_query_stdout_bytes": len(kernel_stdout),
        "original_kernel_query_stderr_bytes": len(kernel_stderr), "original_setup_events": setup_events,
        "original_external_observer": observer,
        "original_observer_counts": {"event_types": dict(collections.Counter(row["event"] for row in events)),
            "response_records": len(responses), "trace_bytes": observer["trace_bytes"],
            "no_one_to_one_or_timely_signal_claim": True},
        "model_acquisition_originals": acquisition,
        "actionable_new_differences": ["Two committed cold-provider/header boundary tests were newly discovered and passed; they do not execute a physical benchmark.",
            "The previously failing GVA-three-field container fixture passed this original run with identical test bytes. This is an original outcome difference, not proof its prior parent-epoch race was fixed.",
            "The same 88 actual skips still include eight undeclared identity/reason pairs under the original 80-row manifest; the original child fails that exact gate. Pending new 88-row declarations are not used retroactively.",
            "No new failing method appeared: all remaining fixture and namespace/broker rows are already in the finite 2f diagnosis; keep the current owned finite repairs, no additional blanket skip or broad rewrite."],
        "causality_limits": ["This independent namespace probe again completed CLONE_NEWUSER unshare, then failed opening /proc/self/setgroups with EACCES13. It is not evidence unshare itself failed.",
            "The original sudo/journalctl query was killed after immediate /proc/3990/exe owner observation EACCES; original stdout/stderr are empty and timeout is false. Longer execution time would not repair that demonstrated ownership boundary.",
            "No original kernel denial records were obtained; unconfined was observed before setup, with no exact post-unshare policy/denial join. AppArmor/usernamespace policy cause is unproven.",
            "The original suite child exited1 without signal139, no forcedSIGTERM/SIGKILL; original observer does not establish all descendant quiescence. Earlier139 cause remains unproven.",
            "Per-test durable journals/setup syscalls for the 45 namespace/broker rows were not retained in this ZIP. Do not attribute every row to the independent probe's errno.",
            "The current uncommitted direct-journal/privilege-aware diagnostic repair is absent from source6358 and supplies no evidence about this run."],
        "retention_tool_observations": ["Metadata btoa helper failed before its filesystem call; no original metadata file was created by that failed invocation.",
            "Decoded-log helper failed on unavailable TextEncoder after its first host chunk was written. The 7002-byte prefix was retained, then remaining same retrieved original text was appended with length guards; no log prefix or ZIP was overwritten."],
        "scope": {"tests_executed_by_reviewer": False, "workflow_retry_cancel_or_mutation": None,
            "production_or_test_source_edited": False, "engine_namespace_model_or_native_query": False,
            "full_ci_success_claim": False, "hardware_acceptance_claim": False}}
    save(OUT / "review.v1.json", seal(review))
    print(json.dumps({"review": descriptor(OUT / "review.v1.json"), "failure_index": descriptor(OUT / "failure-index.v1.json"),
        "counts": counts, "original_zips_and_sources_unchanged": True}))
finally:
    for archive in archives:
        archive.close()
