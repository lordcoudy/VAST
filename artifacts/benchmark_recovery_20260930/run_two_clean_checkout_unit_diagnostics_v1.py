"""Exactly two reviewed existing unit methods; artifact-only bounded observer."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import unittest

sys.dont_write_bytecode = True
PROJECT = Path("/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec")
HERE = PROJECT / "artifacts/benchmark_recovery_20260930"
CLONE = Path("/var/tmp/vast-byte-freeze-caea5419c030-false-64a1af1d712b")
PYTHON = Path("/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python")
OUT = HERE / "clean-checkout-two-unit-diagnostics-v1"
TESTS = (
    ("test_analytics_model_contract", "AnalyticsModelContractTests", "test_repository_manifest_is_complete_and_hash_bound"),
    ("test_analytics_peer_identity", "AnalyticsPeerIdentityAuthorityTests", "test_observer_reads_exact_proc_file_and_small_docker_projection"),
)


def child():
    attempted = []
    def audit(event, arguments):
        if event in {"subprocess.Popen", "socket.connect", "socket.bind", "os.system", "os.fork", "os.exec"}:
            attempted.append(event)
            raise RuntimeError("Unexpected external launch/network event in reviewed unit diagnostic: " + event)
    sys.addaudithook(audit)
    suite = unittest.TestSuite()
    for name, cls, method in TESTS:
        path = CLONE / "tests" / (name + ".py")
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        if Path(module.__file__).resolve(strict=True) != path:
            raise RuntimeError("foreign explicit test source")
        loaded = unittest.defaultTestLoader.loadTestsFromName(cls + "." + method, module)
        ids = [test.id() for test in loaded]
        if ids != [name + "." + cls + "." + method]:
            raise RuntimeError("explicit unittest ID mismatch")
        suite.addTests(loaded)
    result = unittest.TextTestRunner(verbosity=2, stream=sys.stderr).run(suite)
    source_files = sorted({str(Path(module.__file__).resolve()) for module in list(sys.modules.values())
        if getattr(module, "__file__", None) and Path(module.__file__).resolve().is_relative_to(CLONE)})
    payload = {"tests_run": result.testsRun, "successful": result.wasSuccessful(),
        "failures": [{"test_id": test.id(), "traceback": trace} for test, trace in result.failures],
        "errors": [{"test_id": test.id(), "traceback": trace} for test, trace in result.errors],
        "skips": [{"test_id": test.id(), "reason": reason} for test, reason in result.skipped],
        "unexpected_external_launch_events": attempted, "loaded_clone_source_files": source_files,
        "sys_executable": sys.executable, "python": sys.version,
        "isolated": sys.flags.isolated, "dont_write_bytecode": sys.dont_write_bytecode,
        "actual_osrelease": Path("/proc/sys/kernel/osrelease").read_text("ascii").strip()}
    print(json.dumps(payload, sort_keys=True))
    return 0 if result.wasSuccessful() else 1


def controller():
    sys.path.insert(0, str(HERE))
    from verify_checkout_byte_freeze_v9 import Held, canonical, directory_identity, process_observation, require, write_new
    require(PROJECT.resolve(strict=True) == PROJECT and CLONE.resolve(strict=True) == CLONE, "aliased diagnostic roots")
    OUT.mkdir(mode=0o755, exist_ok=False)
    with Held(PROJECT) as evidence, Held(CLONE) as source, Held(Path("/")) as external:
        proof_name = "artifacts/benchmark_recovery_20260930/byte-freeze-fresh-checkouts.v7.autocrlf-false.json"
        require(evidence.pin(proof_name)["sha256"] ==
            "0ce5450ecfd0829b548ca765b337164ce3268d87317dcd5b618025a33388f432", "original clone proof changed")
        proof = json.loads(evidence.raw(proof_name))
        require(proof["project_root"] == str(CLONE) and proof["source_commit"] ==
            "caea5419c0302fc60183544de86f4e879346b7d0" and proof["core_autocrlf"] == "false", "original clone scope")
        audit = json.loads(evidence.raw("artifacts/benchmark_recovery_20260930/packaging-source-rollforward.v4.json"))
        frozen = audit["final_actual_source_manifest"]["project_sources"] + proof["controller_LF_metadata_pins"]
        require(len(frozen) == 175 and not (CLONE / "models").exists(), "source scope/model directory changed")
        before = [source.pin(row["path"]) for row in frozen]
        require(before == frozen, "original frozen source/controller bytes changed")
        extra = ["tests/" + name + ".py" for name, _, _ in TESTS]
        extra += ["scripts/analytics_model_contract.py", "scripts/benchmark_contract.py",
            "configs/checkpoint_analytics_models_openvino.yaml", ".gitignore", ".git/HEAD"]
        for name in extra:
            source.pin(name)
        require(source.raw(".git/HEAD").decode("ascii").strip() == proof["source_commit"], "clone detached HEAD differs")
        script_name = Path(__file__).relative_to(PROJECT).as_posix()
        script_pin = evidence.pin(script_name)
        interpreter = external.pin(PYTHON.relative_to("/").as_posix())
        report = {"schema_version": 1, "artifact_kind": "vast_two_clean_checkout_unit_diagnostics_v1",
            "accepted": False, "classification": "local WSL unit reproduction, not an Ubuntu hosted CI cause or model/image grant",
            "source_commit": proof["source_commit"], "original_clone_proof": evidence.pin(proof_name),
            "clone_root": str(CLONE), "clone_identity_before": directory_identity(CLONE.lstat()),
            "observer": script_pin, "interpreter": dict(interpreter, path=str(PYTHON)),
            "test_ids": [".".join(row) for row in TESTS],
            "prelaunch_inspection": {
                "models_directory_exists": False,
                "model_method": "YAML and absent artifact file/hash checks only; no download/inference",
                "peer_method": "its actual injected CompletedProcess runner supplies the sole Docker call; real kernel proc read only",
                "audit_guard": "unexpected subprocess/network/fork/exec events fail closed; no unit expectation is mocked by this observer"},
            "source_before": before, "controller": process_observation(os.getpid())}
        argv = [str(PYTHON), "-I", "-B", str(Path(__file__)), "--child"]
        write_new(OUT / "dispatch.v1.json", dict(report, argv=argv, combined_timeout_seconds=30))
        began = time.monotonic()
        process = subprocess.Popen(argv, cwd=CLONE, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        child_identity = process_observation(process.pid)
        timed_out = False
        try:
            stdout, stderr = process.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(process.pid, signal.SIGKILL)
            stdout, stderr = process.communicate(timeout=5)
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
        raw_refs = {}
        for channel, body in (("stdout", stdout), ("stderr", stderr)):
            target = OUT / (channel + ".original.log")
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o444)
            with os.fdopen(fd, "wb") as stream:
                stream.write(body)
                stream.flush()
                os.fsync(stream.fileno())
            raw_refs[channel] = {"path": str(target), "size_bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}
        members = []
        for leaf in Path("/proc").iterdir():
            if leaf.name.isdigit():
                observed = process_observation(int(leaf.name))
                if observed.get("pgid") == process.pid:
                    members.append(observed)
        report["original_execution"] = {"argv": argv, "child": child_identity, "cwd": str(CLONE),
            "returncode": process.returncode, "timed_out": timed_out, "elapsed_s": time.monotonic() - began,
            "combined_timeout_seconds": 30, "original_group_terminal_members": members, **raw_refs}
        completed = not timed_out and not members and len(stdout) <= 1048576 and len(stderr) <= 1048576
        outcome = json.loads(stdout) if completed and process.returncode in (0, 1) else None
        require(outcome is not None and outcome["tests_run"] == 2 and outcome["unexpected_external_launch_events"] == []
            and outcome["isolated"] == 1 and outcome["dont_write_bytecode"] is True, "unit diagnostic did not complete its exact reviewed scope")
        report["actual_unittest_result"] = outcome
        for filename in outcome["loaded_clone_source_files"]:
            source.pin(Path(filename).relative_to(CLONE).as_posix())
        source.verify()
        external.verify()
        evidence.verify()
        after = []
        for row in frozen:
            digest, size = source.hash_fd(source.files[row["path"]][0])
            after.append({"path": row["path"], "size_bytes": size, "sha256": digest})
        require(after == before and directory_identity(CLONE.lstat()) == report["clone_identity_before"], "source/root drift")
        report["source_after"] = after
        report["original_source_controller_bytes_unchanged"] = True
        report["loaded_and_declared_source_witnesses"] = source.witnesses()
        report["evidence_witnesses"] = evidence.witnesses()
        report["external_interpreter_witnesses"] = external.witnesses()
        report["local_diagnostic_complete"] = True
        report["observed_at_ns"] = time.time_ns()
        print(json.dumps(write_new(OUT / "execution.v1.json", report), sort_keys=True))


if __name__ == "__main__":
    if sys.argv[1:] == ["--child"]:
        raise SystemExit(child())
    if sys.argv[1:]:
        raise SystemExit("unsupported diagnostic argv")
    controller()
