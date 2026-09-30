"""CPU repository checks. GPU/model acceptance requires separate physical evidence."""
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.metadata
import json
import os
import platform
from pathlib import Path
import re
import shutil
import signal
import stat
import subprocess
import sys
import time
import unittest

# A file import also works for fixture imports under Python -I.
import importlib.util
_observer_spec = importlib.util.spec_from_file_location(
    "vast_ci_external_observer", Path(__file__).with_name("ci_external_test_observer_v1.py"))
_observer = importlib.util.module_from_spec(_observer_spec)
_observer_spec.loader.exec_module(_observer)
_selection_spec = importlib.util.spec_from_file_location(
    'vast_ci_selection', Path(__file__).with_name('ci_test_selection_v1.py'))
_selection = importlib.util.module_from_spec(_selection_spec)
_selection_spec.loader.exec_module(_selection)
_profile_spec = importlib.util.spec_from_file_location(
    'vast_ci_userns_profile', Path(__file__).with_name('ci_userns_profile_v1.py'))
_profile = importlib.util.module_from_spec(_profile_spec)
_profile_spec.loader.exec_module(_profile)


ROOT = Path(__file__).resolve().parents[1]
TARGETS = (
    "vast_native_gst_probe", "vast_checkpoint_source", "gstadaptivescheduler",
    "gstvastanalyticsterminal", "gstvastanalyticsqueue", "gstvastcheckpointprefixqueue",
)
REQUIRED_TESTS = frozenset(
    "test_checkpoint_analytics_execution_client_cpp."
    "CheckpointAnalyticsExecutionClientCppTest." + name
    for name in (
        "test_native_client_regression", "test_native_policy_topology_regression",
        "test_native_reset_queue_level_regression",
    )
)
HARDWARE_GAPS = (
    "Hosted CPU tests do not execute NVIDIA decode or the packaged SDK runtimes.",
    "Skipped hardware/data tests do not prove model parity, native paired execution, "
    "qualification, Q4, storage or the full benchmark.",
    "Final scientific conformance and archived completion require separately reviewed "
    "physical evidence bound to the actual source closure.",
)


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def canonical_python() -> str:
    """Keep the actual interpreter version; remove only launcher path aliases."""
    if sys.version_info[:3] != (3, 12, 3) or sys.implementation.name != "cpython":
        raise RuntimeError("CI requires the original CPython3.12.3")
    path = Path(sys.executable).resolve(strict=True)
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or not os.access(path, os.X_OK):
        raise RuntimeError("canonical CI executable is not a single-link regular executable")
    return str(path)


def validate_repository_import_origins() -> None:
    """Reject foreign project modules even when a package was already imported."""
    project_names = {p.stem for p in (ROOT / "scripts").glob("*.py")}
    for name, module in tuple(sys.modules.items()):
        if module is None:
            continue
        top = name.split(".", 1)[0]
        if not (top in {"tests", "deploy"} or top.startswith("test_") or top in project_names):
            continue
        origins = []
        if getattr(module, "__file__", None):
            origins.append(module.__file__)
        origins.extend(getattr(module, "__path__", ()))
        try:
            contained = origins and all(Path(p).resolve(strict=True).is_relative_to(ROOT) for p in origins)
        except OSError:
            contained = False
        if not contained:
            raise RuntimeError(f"imported project module outside fixed repository: {name}")


def gstreamer_factory_facts(output: Path, absolute_deadline_ns: int) -> dict:
    """gst-inspect loads each original required factory; retain its raw metadata."""
    executable = shutil.which("gst-inspect-1.0")
    if executable is None:
        raise RuntimeError("gstreamer1.0-tools is required for loaded-factory facts")
    facts = {}
    for factory in ("appsrc", "queue", "videoconvert"):
        name = "factory-" + factory
        observed = command([str(Path(executable).resolve(strict=True)), factory], output, name, 10,
                           absolute_deadline_ns)
        with (output / (name + ".stdout")).open('rb') as stream:
            raw = stream.read(64*1024+1)
        if len(raw) > 64 * 1024 or b"Factory Details:" not in raw or b"Plugin Details:" not in raw:
            raise RuntimeError(f"missing or oversized loaded-factory metadata: {factory}")
        match = re.search(rb"^\s+Filename\s+(.+)$", raw, re.MULTILINE)
        if match is None:
            raise RuntimeError(f"loaded factory has no physical plugin filename: {factory}")
        plugin = Path(os.fsdecode(match.group(1).strip())).resolve(strict=True)
        before = plugin.stat()
        if not stat.S_ISREG(before.st_mode) or before.st_size > 16 * 1024 * 1024:
            raise RuntimeError("loaded plugin is not a bounded regular file")
        digest = hashlib.sha256()
        with plugin.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                if time.monotonic_ns() >= absolute_deadline_ns:
                    raise RuntimeError("original job deadline reached during plugin hashing")
                digest.update(block)
        after = plugin.stat()
        epoch_fields = ('st_dev','st_ino','st_mode','st_nlink','st_size','st_uid','st_gid','st_mtime_ns','st_ctime_ns')
        if any(getattr(before, key) != getattr(after, key) for key in epoch_fields):
            raise RuntimeError("loaded plugin changed during observation")
        facts[factory] = {"command": observed, "stdout_sha256": hashlib.sha256(raw).hexdigest(),
                          "stdout_size_bytes": len(raw), "plugin": {
                              "path": str(plugin), "size_bytes": before.st_size,
                              "sha256": digest.hexdigest(), "device": before.st_dev,
                              "inode": before.st_ino}}
    return facts


def namespace_diagnostic(output, python, absolute_deadline_ns):
    spec = importlib.util.spec_from_file_location('ci_namespace', ROOT/'scripts/ci_namespace_diagnostic_v1.py')
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    return helper.observe_namespace_setup_v1(output_dir=output, python=python,
                                            absolute_deadline_ns=absolute_deadline_ns)


def tracked_paths(root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z"], cwd=root, check=True, capture_output=True,
        timeout=30,
    )
    return [os.fsdecode(item) for item in result.stdout.split(b"\0") if item]


def manifest(root: Path, paths: list[str], absolute_deadline_ns=None) -> dict[str, dict[str, object]]:
    result = {}
    for relative in paths:
        if absolute_deadline_ns is not None and time.monotonic_ns() >= absolute_deadline_ns:
            raise RuntimeError("original job deadline reached while inventorying sources")
        path = root / relative
        if path.is_symlink() or not path.is_file():
            raise RuntimeError(f"tracked path is not a regular file: {relative}")
        before = path.stat()
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                if absolute_deadline_ns is not None and time.monotonic_ns() >= absolute_deadline_ns:
                    raise RuntimeError("original job deadline reached while hashing sources")
                digest.update(block)
        after = path.stat()
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns
        ):
            raise RuntimeError(f"tracked path changed while hashing: {relative}")
        result[relative] = {"size_bytes": before.st_size, "sha256": digest.hexdigest()}
    return result


def source_changes(before: dict, after: dict) -> list[str]:
    return sorted(path for path in before.keys() | after.keys()
                  if before.get(path) != after.get(path))


def verify_committed_bytes(root: Path, paths: list[str], absolute_deadline_ns=None) -> None:
    """Check raw checkout bytes against HEAD, independently of Git's stat cache."""
    object_format = subprocess.run(
        ["git", "rev-parse", "--show-object-format"], cwd=root, check=True,
        capture_output=True, text=True, timeout=10,
    ).stdout.strip()
    if object_format not in ("sha1", "sha256"):
        raise RuntimeError("unsupported Git object hash format")
    tree = subprocess.run(["git", "ls-tree", "-rz", "HEAD"], cwd=root,
                          check=True, capture_output=True, timeout=30).stdout
    expected = {}
    for row in tree.split(b"\0"):
        if not row:
            continue
        metadata, name = row.split(b"\t", 1)
        mode, kind, oid = metadata.split()
        if kind != b"blob" or mode not in (b"100644", b"100755"):
            raise RuntimeError("CI source tree contains a nonregular tracked object")
        expected[os.fsdecode(name)] = oid.decode("ascii")
    if set(expected) != set(paths):
        raise RuntimeError("tracked path inventory differs from HEAD")
    for relative, oid in expected.items():
        if absolute_deadline_ns is not None and time.monotonic_ns() >= absolute_deadline_ns:
            raise RuntimeError("original job deadline reached while verifying commit bytes")
        path = root / relative
        size = path.stat().st_size
        digest = hashlib.new(object_format)
        digest.update(f"blob {size}\0".encode("ascii"))
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                if absolute_deadline_ns is not None and time.monotonic_ns() >= absolute_deadline_ns:
                    raise RuntimeError("original job deadline reached while verifying commit bytes")
                digest.update(block)
        if digest.hexdigest() != oid:
            raise RuntimeError(f"raw checkout bytes differ from HEAD: {relative}")


class RecordedResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.successes: list[str] = []
        self.started: dict[str, float] = {}
        self.outcomes: dict[str, str] = {}

    def event(self, name, test, **facts):
        self.stream.writeln("\n" + json.dumps({"event": name, "test_id": test.id(),
                                              "monotonic_ns": time.monotonic_ns(), **facts},
                                             sort_keys=True))
        self.stream.flush()

    def startTest(self, test):
        self.started[test.id()] = time.monotonic()
        self.event("test_started", test)
        super().startTest(test)
        self.stream.flush()

    def stopTest(self, test):
        super().stopTest(test)
        self.event("test_terminal", test, outcome=self.outcomes.get(test.id(), "unknown"),
                   elapsed_s=time.monotonic() - self.started.pop(test.id()))

    def immediate_trace(self, event, test, trace):
        self.event(event, test)
        self.stream.writeln(trace)
        self.stream.flush()

    def addSuccess(self, test):
        self.successes.append(test.id())
        self.outcomes.setdefault(test.id(), "success")
        super().addSuccess(test)

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.outcomes.setdefault(test.id(), "failure")
        self.immediate_trace("test_failure", test, self.failures[-1][1])

    def addError(self, test, err):
        super().addError(test, err)
        self.outcomes[test.id()] = "error"
        self.immediate_trace("test_error", test, self.errors[-1][1])

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        if err is not None:
            failure = issubclass(err[0], test.failureException)
            if failure:
                self.outcomes.setdefault(test.id(), "failure")
            else:
                self.outcomes[test.id()] = "error"
            trace = (self.failures if failure else self.errors)[-1][1]
            self.immediate_trace("subtest_failure" if failure else "subtest_error", subtest, trace)

    def addSkip(self, test, reason):
        self.outcomes.setdefault(test.id(), "skip")
        super().addSkip(test, reason)

    def addExpectedFailure(self, test, err):
        super().addExpectedFailure(test, err)
        self.outcomes.setdefault(test.id(), "expected_failure")
        self.immediate_trace("test_expected_failure", test, self.expectedFailures[-1][1])

    def addUnexpectedSuccess(self, test):
        self.outcomes[test.id()] = "unexpected_success"
        super().addUnexpectedSuccess(test)


def host_facts() -> dict:
    """Diagnostic observation only; no environment dump or namespace probe."""
    executable = Path(sys.executable).resolve(strict=True)
    info = executable.stat()
    facts = {
        "python": sys.version, "executable": sys.executable,
        "executable_realpath": str(executable),
        "executable_stat": {name: getattr(info, name) for name in
                            ("st_dev", "st_ino", "st_mode", "st_nlink", "st_size", "st_uid", "st_gid")},
        "uid": os.getuid() if hasattr(os, "getuid") else None,
        "gid": os.getgid() if hasattr(os, "getgid") else None,
        "kernel_release": platform.release(),
        "api_available": {name: hasattr(os, name) for name in
                          ("unshare", "fork", "pidfd_open", "CLONE_NEWUSER", "CLONE_NEWNS", "CLONE_NEWPID")},
        "process_status": {}, "namespace_sysctls": {},
    }
    try:
        with Path("/proc/self/status").open("rb") as stream:
            raw = stream.read(16 * 1024 + 1)
        if len(raw) > 16 * 1024:
            raise ValueError("process status diagnostic exceeds 16KiB")
        selected = {"CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb", "NoNewPrivs", "Seccomp"}
        facts["process_status"] = {key: value.strip() for line in raw.decode("ascii").splitlines()
                                   if ":" in line for key, value in [line.split(":", 1)] if key in selected}
    except (OSError, ValueError) as exc:
        facts["process_status"] = {"unavailable": f"{type(exc).__name__}: {exc}"}
    for name in ("unprivileged_userns_clone", "apparmor_restrict_unprivileged_userns", "max_user_namespaces"):
        path = Path("/proc/sys") / ("user" if name == "max_user_namespaces" else "kernel") / name
        try:
            with path.open("rb") as stream:
                raw = stream.read(129)
            if len(raw) > 128 or not raw.strip().isdigit():
                raise ValueError("namespace sysctl diagnostic is not a bounded integer")
            facts["namespace_sysctls"][name] = {"path": str(path), "value": raw.decode("ascii").strip()}
        except (OSError, ValueError) as exc:
            facts["namespace_sysctls"][name] = {"path": str(path), "unavailable": f"{type(exc).__name__}: {exc}"}
    if len((json.dumps(facts, indent=2, sort_keys=True) + "\n").encode("utf8")) > 16 * 1024:
        raise RuntimeError("host facts diagnostic exceeds 16KiB")
    return facts


def run_test_suite(suite, stream):
    return unittest.TextTestRunner(stream=stream, verbosity=2, resultclass=RecordedResult).run(suite)


def discovered_test_ids(suite):
    ids = []
    for case in suite:
        if isinstance(case, unittest.TestSuite):
            ids.extend(discovered_test_ids(case))
        else:
            ids.append(case.id())
    return sorted(ids)


def suite_child(output: Path, trace_fd: int, event_fd: int, stop_fd: int, expected_profile=None) -> int:
    """Exactly one fresh child discovers the unchanged complete suite."""
    report = {"successful": False}
    profile_observation = None
    try:
        profile_observation = _profile.observe_suite_profile_v1(expected_profile)
        with _observer.child_trace_handler(trace_fd, event_fd, stop_fd) as observation:
            sys.path.insert(0, str(ROOT))
            validate_repository_import_origins()
            suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern="test_*.py")
            report['discovered_ids'] = discovered_test_ids(suite)
            discovered = report['discovered_ids']
            validate_repository_import_origins()
            suite, selection_report = _selection.select_portable_suite_v1(suite, project_root=ROOT)
            with (output / "unittest.original.log").open("w", encoding="utf-8") as stream:
                result = run_test_suite(suite, stream)
            report = suite_report(result)
            report['discovered_ids'] = discovered
            report['selection'] = selection_report
            report['portable_skip_audit'] = _selection.validate_portable_skips_v1(result.skipped, selection_report)
            validate_repository_import_origins()
        if observation["failure"]:
            report["successful"] = False
            report["observer_failure"] = observation["failure"]
    except BaseException as exc:
        report["successful"] = False
        report["child_failure"] = f"{type(exc).__name__}: {exc}"
    finally:
        report['profile_observation'] = profile_observation
        write_json(output / "unittest-child.report.json", report)
        os.close(trace_fd)
        os.close(event_fd)
        os.close(stop_fd)
    return 0 if report["successful"] else 1


def suite_report(result: RecordedResult) -> dict:
    return {
        "tests_run": result.testsRun,
        "successful_test_ids": result.successes,
        "skips": [{"test_id": test.id(), "reason": reason}
                  for test, reason in result.skipped],
        "failures": [{"test_id": test.id(), "traceback": trace}
                     for test, trace in result.failures],
        "errors": [{"test_id": test.id(), "traceback": trace}
                   for test, trace in result.errors],
        "expected_failures": [test.id() for test, _ in result.expectedFailures],
        "unexpected_successes": [test.id() for test in result.unexpectedSuccesses],
        "missing_required_successes": sorted(REQUIRED_TESTS - set(result.successes)),
        "successful": result.wasSuccessful() and result.testsRun > 0
                      and REQUIRED_TESTS <= set(result.successes),
    }


def command(argv: list[str], output: Path, name: str, timeout: int, absolute_deadline_ns=None) -> dict:
    began = time.monotonic()
    with (output / (name + ".stdout")).open("wb") as stdout, (
        output / (name + ".stderr")
    ).open("wb") as stderr:
        process = subprocess.Popen(argv, cwd=ROOT, stdin=subprocess.DEVNULL,
                                   stdout=stdout, stderr=stderr, start_new_session=True)
        timed_out = False
        cleanup_error = None
        try:
            remaining = timeout if absolute_deadline_ns is None else min(
                timeout, max(0, (absolute_deadline_ns - time.monotonic_ns()) / 1e9))
            process.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(process.pid, signal.SIGKILL)
            remaining = 10 if absolute_deadline_ns is None else min(
                10, max(0, (absolute_deadline_ns - time.monotonic_ns()) / 1e9))
            try:
                process.wait(timeout=remaining)
            except subprocess.TimeoutExpired as exc:
                cleanup_error = f"{type(exc).__name__}: owned command terminal unavailable within remaining job budget"
    observation = {"argv": argv, "returncode": process.returncode, "timed_out": timed_out,
                   "elapsed_s": time.monotonic() - began, "cleanup_error": cleanup_error}
    write_json(output / (name + ".json"), observation)
    if timed_out or process.returncode or cleanup_error:
        raise RuntimeError(f"{name} failed: see its original stdout/stderr")
    return observation


def specification_inventory(root: Path) -> dict:
    inventories = []
    for path in sorted((root / "openspec").rglob("spec.md")):
        requirements = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("### Requirement: "):
                requirements.append({"name": line.removeprefix("### Requirement: "),
                                     "scenarios": []})
            elif line.startswith("#### Scenario: "):
                if not requirements:
                    raise RuntimeError(f"scenario precedes a requirement in {path}")
                requirements[-1]["scenarios"].append(line.removeprefix("#### Scenario: "))
        inventories.append({"path": path.relative_to(root).as_posix(),
                            "requirements": requirements})
    return {"inventory": inventories, "behavior_conformance": "requires reviewed evidence map",
            "hardware_gaps": HARDWARE_GAPS}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-commit")
    parser.add_argument("--job-started-monotonic-ns", type=int)
    parser.add_argument("--suite-child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--trace-fd", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--event-fd", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--stop-fd", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--expected-profile", help=argparse.SUPPRESS)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    if args.suite_child:
        if args.trace_fd is None or args.event_fd is None or args.stop_fd is None or args.expected_commit is not None:
            raise RuntimeError("invalid internal suite-child invocation")
        return suite_child(output, args.trace_fd, args.event_fd, args.stop_fd, args.expected_profile)
    if args.expected_profile is not None:
        parser.error('--expected-profile is internal to the original suite child')
    if args.expected_commit is None:
        parser.error("--expected-commit is required for the original CI parent")
    if output == ROOT or ROOT in output.parents:
        raise RuntimeError("CI outputs must be outside the source checkout")
    output.mkdir(parents=True, exist_ok=False)
    began = time.monotonic()
    started_ns = args.job_started_monotonic_ns or time.monotonic_ns()
    if started_ns <= 0 or started_ns > time.monotonic_ns():
        raise RuntimeError("invalid original job monotonic start")
    absolute_deadline_ns = started_ns + 90 * 60 * 1_000_000_000
    report = {"kind": "vast_cpu_ci_checks_v1", "successful": False,
              "hardware_acceptance": False, "hardware_gaps": HARDWARE_GAPS}
    before = None
    paths = []
    try:
        python = canonical_python()
        report["canonical_python"] = python
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                                check=True, capture_output=True, text=True, timeout=10).stdout.strip()
        report["commit"] = commit
        if commit != args.expected_commit:
            raise RuntimeError("checked-out commit differs from the requested PR/push commit")
        paths = tracked_paths(ROOT)
        before = manifest(ROOT, paths, absolute_deadline_ns)
        verify_committed_bytes(ROOT, paths, absolute_deadline_ns)
        write_json(output / "tracked-source.before.json", before)
        report["raw_checkout_bytes_match_commit"] = True
        report["python"] = sys.version
        report["packages"] = sorted(
            [{"name": dist.metadata["Name"], "version": dist.version}
             for dist in importlib.metadata.distributions()],
            key=lambda row: row["name"].casefold(),
        )
        write_json(output / "specification-inventory.json", specification_inventory(ROOT))
        checked_python = []
        checked_bash = []
        for relative in paths:
            if time.monotonic_ns() >= absolute_deadline_ns:
                raise RuntimeError("original job deadline reached during syntax checks")
            if not relative.startswith(("scripts/", "tests/", "deploy/")):
                continue
            if relative.endswith(".py"):
                ast.parse((ROOT / relative).read_bytes(), filename=relative)
                checked_python.append(relative)
            elif relative.endswith(".sh"):
                subprocess.run(["bash", "-n", str(ROOT / relative)], check=True, timeout=15)
                checked_bash.append(relative)
        report["python_syntax"] = checked_python
        report["bash_syntax"] = checked_bash
        command([python, "-I", "-B", str(ROOT / "scripts/prepare_ci_model_assets.py"),
                 "--output-dir", str(output / "model-acquisition")],
                output, "model-assets", 590, absolute_deadline_ns)
        build = output / "build"
        command(["cmake", "-S", str(ROOT), "-B", str(build),
                 "-DCMAKE_BUILD_TYPE=Release", "-DVAST_BUILD_CUSTOM_CUDA_QT=OFF",
                 "-DCMAKE_RUNTIME_OUTPUT_DIRECTORY=" + str(build / "bin"),
                 "-DCMAKE_LIBRARY_OUTPUT_DIRECTORY=" + str(build / "lib")],
                output, "native-configure", 120, absolute_deadline_ns)
        command(["cmake", "--build", str(build), "--parallel", "2", "--target", *TARGETS],
                output, "native-build", 600, absolute_deadline_ns)
        report["built_targets"] = TARGETS
        report["gstreamer_factories"] = gstreamer_factory_facts(output, absolute_deadline_ns)
        report["gstreamer_packages"] = command(
            ['dpkg-query', '-W', '-f=${Package}=${Version}\n', 'gstreamer1.0-plugins-base',
             'gstreamer1.0-tools'], output, 'gstreamer-packages', 10, absolute_deadline_ns)
        write_json(output / "host-facts.original.json", host_facts())
        report['namespace_diagnostic'] = namespace_diagnostic(output/'namespace-diagnostic', python,
                                                              absolute_deadline_ns)
        if not report['namespace_diagnostic']['capture_completed']:
            raise RuntimeError('original namespace diagnostic capture/cleanup failed')
        with _profile.held_ci_userns_profile_v1(diagnostic_dir=output/'namespace-diagnostic',
                diagnostic=report['namespace_diagnostic'], python=python,
                output_dir=output/'namespace-profile', job_start_ns=started_ns,
                absolute_deadline_ns=absolute_deadline_ns) as profile:
            report['namespace_profile'] = profile['report']
            expected = (['--expected-profile', profile['expected_profile']]
                        if profile['expected_profile'] is not None else [])
            report["observer"] = _observer.observe_test_child(
                lambda trace_fd, event_fd, stop_fd: [python, "-I", "-B", str(Path(__file__).resolve()),
                    "--suite-child", "--output-dir", str(output), "--trace-fd", str(trace_fd),
                    "--event-fd", str(event_fd), "--stop-fd", str(stop_fd), *expected],
                output_dir=output / "external-test-observer",
                absolute_deadline_ns=profile['suite_deadline_ns'])
        child_report_path = output / "unittest-child.report.json"
        if child_report_path.is_file():
            report["unittest"] = json.loads(child_report_path.read_text(encoding="utf-8"))
        else:
            report["unittest"] = {"successful": False, "missing_child_report": True}
        if not report["observer"]["successful"]:
            raise RuntimeError("original full-suite child/observer failed; see original lifecycle/trace")
        if not report["unittest"]["successful"]:
            raise RuntimeError("test discovery failed or a required native regression did not pass")
        report["successful"] = True
    except Exception as exc:
        report["failure"] = f"{type(exc).__name__}: {exc}"
    finally:
        try:
            if before is not None:
                after = manifest(ROOT, tracked_paths(ROOT), absolute_deadline_ns)
                write_json(output / "tracked-source.after.json", after)
                report["changed_tracked_paths"] = source_changes(before, after)
                if report["changed_tracked_paths"]:
                    report["successful"] = False
                    report["source_integrity_failure"] = "tracked files changed during CPU checks"
        except Exception as exc:
            report["successful"] = False
            report["source_integrity_failure"] = f"{type(exc).__name__}: {exc}"
        report["elapsed_s"] = time.monotonic() - began
        report["job_started_monotonic_ns"] = started_ns
        report["absolute_deadline_ns"] = absolute_deadline_ns
        if time.monotonic_ns() >= absolute_deadline_ns:
            report["successful"] = False
            report["deadline_failure"] = "original 90-minute job deadline exceeded"
        write_json(output / "report.json", report)
    if time.monotonic_ns() >= absolute_deadline_ns:
        return 1
    print(json.dumps({"successful": report["successful"], "report": str(output / "report.json")}))
    return 0 if report["successful"] else 1


if __name__ == "__main__":
    sys.exit(main())
