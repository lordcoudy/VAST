#!/usr/bin/env python3
"""Run one original CPU/GPU GStreamer pair, then stop and cold-check it."""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import shutil
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

from publication_physical_io_v1 import PhysicalRootCustodyV1
from publication_operational_request_domain_v1 import payload_with_sha256_v1
from publication_operational_request_reconciliation_v1 import _PinnedFile

RESERVE_BYTES = 20 * 1024**3
FREE_FLOOR_BYTES = 20 * 1024**3
CHANNEL_BYTES = 1024 * 1024
METADATA_BYTES = 1024 * 1024
STARTUP_SECONDS = 120.0
STOP_SECONDS = 60.0
PAIR_SECONDS = 2100.0
TERMINAL_FILENAME = "component_cli_terminal.v1.json"
INPUT_NAMES = ("capability_manifest_path", "calibration_path", "model_parity_receipt_path",
               "runtime_image_receipt_path", "worker_freeze_receipt_path", "execution_code_closure_path")


def _require(condition, message):
    if not condition:
        raise RuntimeError(message)


def _absolute(root, path):
    raw = Path(path)
    if not raw.is_absolute():
        raw = root / raw
    _require(raw == Path(os.path.abspath(raw)) and raw.resolve(strict=True) == raw,
             "component CLI path is unavailable or traverses an alias")
    return raw


def _error(error):
    return {"type": type(error).__name__, "message": str(error)[:4096]}


def _epoch(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


def _write_channel(custody, output, name, payload):
    from publication_guardian_preprocessing_contract_v1 import DirectoryFdCustodyV1
    custody.verify()
    with DirectoryFdCustodyV1.open_existing(output, label="original guardian raw channels") as held:
        identity = held.write_exclusive(name, payload, mode=0o400)
        held.assert_owned(name, identity)
    custody.verify()
    return {"path": str(output / name), "size_bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest()}


def _pin_file(path, maximum):
    """Bound the first original read before retaining a held cold-reader pin."""
    path = Path(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        original = os.fstat(fd)
        _require(stat.S_ISREG(original.st_mode) and original.st_nlink == 1
                 and 0 < original.st_size <= maximum, "component source pin is not bounded/unique")
        digest = hashlib.sha256()
        size = 0
        while block := os.read(fd, min(1024*1024, maximum + 1 - size)):
            size += len(block)
            _require(size <= maximum, "component source grew beyond bound")
            digest.update(block)
        _require(_epoch(original) == _epoch(os.fstat(fd)) == _epoch(path.lstat()), "component original source changed")
        descriptor = {"path":str(path),"size_bytes":size,"sha256":digest.hexdigest()}
        pin = _PinnedFile(path, descriptor, limit=maximum)
        if pin.before != _epoch(original):
            pin.close()
            raise RuntimeError("component source identity changed before held pin")
        pin.descriptor = descriptor
        return pin
    finally:
        os.close(fd)


def _free_space(output, scratch):
    facts = []
    for path in dict.fromkeys((output, scratch)):
        usage = shutil.disk_usage(path)
        info = path.stat()
        _require(usage.total >= RESERVE_BYTES and usage.free >= FREE_FLOOR_BYTES,
                 "component volume capacity/free operational floor is insufficient")
        facts.append({"path": str(path), "device": info.st_dev, "inode": info.st_ino,
                      "total_bytes": usage.total, "free_bytes": usage.free})
    return facts


@contextlib.contextmanager
def _scratch_reserve_v1(*, project_root, scratch_namespace, output_dir):
    """Keep an actually allocated reserve, never a remote-capacity attestation."""
    del project_root
    _require(os.name == "posix" and hasattr(os, "posix_fallocate"),
             "component scratch reservation requires POSIX allocation")
    namespace = Path(scratch_namespace)
    base = namespace.parent
    with PhysicalRootCustodyV1.open(base, label="component scratch volume") as custody:
        _require(not os.path.lexists(namespace), "component scratch namespace is occupied")
        custody.ensure_directory_owned(namespace, label="new component scratch namespace")
        _free_space(Path(output_dir), namespace)
        path = namespace / "operational-reserve.v1.bin"
        parent_fd = os.open(namespace, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        fd = -1
        primary = None
        evidence = {"path": str(path), "reserved_bytes": RESERVE_BYTES, "released": False}
        try:
            named_parent = namespace.lstat()
            _require((named_parent.st_dev, named_parent.st_ino) ==
                     (os.fstat(parent_fd).st_dev, os.fstat(parent_fd).st_ino), "scratch parent changed")
            fd = os.open(path.name, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                         0o600, dir_fd=parent_fd)
            initial = os.fstat(fd)
            evidence["original_inode"] = [initial.st_dev, initial.st_ino]
            os.posix_fallocate(fd, 0, RESERVE_BYTES)
            os.fsync(fd)
            os.fsync(parent_fd)
            opened = os.fstat(fd)
            named = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
            _require(_epoch(opened) == _epoch(named) and stat.S_ISREG(opened.st_mode)
                     and opened.st_nlink == 1 and opened.st_size == RESERVE_BYTES
                     and opened.st_blocks * 512 >= RESERVE_BYTES,
                     "component scratch reserve was not physically allocated")
            evidence.update(size_bytes=opened.st_size, allocated_bytes=opened.st_blocks * 512,
                            original_epoch=list(_epoch(opened)), filesystems=_free_space(Path(output_dir), namespace))
            try:
                yield evidence
            except BaseException as error:
                primary = error
                raise
            finally:
                try:
                    custody.verify()
                    _require(_epoch(os.fstat(fd)) == _epoch(path.lstat()) == _epoch(opened),
                             "component reserve no longer names its original inode/epoch")
                except BaseException as error:
                    if primary is None:
                        raise
                    primary.add_note("component reserve verification also failed: " + str(error))
        except BaseException as error:
            primary = error
            evidence["failure"] = _error(error)
            error.component_reservation = evidence
            raise
        finally:
            try:
                if fd >= 0:
                    current = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
                    _require((current.st_dev, current.st_ino) == (initial.st_dev, initial.st_ino)
                             and stat.S_ISREG(current.st_mode) and current.st_nlink == 1,
                             "component reserve replacement is preserved")
                    custody.unlink_owned_identity(path, (initial.st_dev, initial.st_ino),
                                                  label="release exact original component reserve")
                    evidence["released"] = True
            except BaseException as error:
                evidence["cleanup_error"] = _error(error)
                if primary is None:
                    raise
                primary.add_note("component reserve cleanup also failed: " + str(error))
            finally:
                if fd >= 0:
                    os.close(fd)
                os.close(parent_fd)


class _GuardianProcess:
    """One original existing guardian CLI; authentication and workers stay there."""
    def __init__(self, *, project_root, component_authority_path, preprocessing_contract_path,
                 preprocessing_receipt_path, operational_context_path, runtime_dir, front_socket,
                 evidence_root, deadline):
        from publication_gstreamer_component_authority_v1 import load_component_authority_v1
        from checkpoint_gstreamer_analytics_sidecar import (
            PRODUCTION_MAX_CONNECTIONS_MINIMUM, PRODUCTION_MAX_REQUESTS_PER_CONNECTION_MINIMUM,
            PRODUCTION_MAX_TOTAL_REQUESTS_MINIMUM)
        root = Path(project_root)
        source = load_component_authority_v1(project_root=root, component_authority_path=component_authority_path)
        projection = source["worker_projection"]
        engine = Path(source["environment"]["engine"]["path"])
        self.engine_descriptor = source["environment"]["engine"]
        self.engine_pin = None
        self.environment = os.environ.copy()
        self.environment["PATH"] = str(engine.parent) + os.pathsep + self.environment.get("PATH", "")
        self.environment["DOCKER_HOST"] = "unix://" + source["environment"]["engine_socket"]["path"]
        self.environment.pop("DOCKER_CONTEXT", None)
        _require(engine.name == "docker" and shutil.which("docker", path=self.environment["PATH"]) == str(engine),
                 "guardian docker executable does not bind the selected engine")
        script = root / "scripts/checkpoint_gstreamer_analytics_sidecar.py"
        entry = "import runpy,sys;sys.path.insert(0," + repr(str(root / "scripts")) + ");runpy.run_path(" + repr(str(script)) + ",run_name='__main__')"
        self.argv = [sys.executable, "-I", "-B", "-c", entry, "--production-guardian",
            "--project-root", str(root), "--config", str(root / projection["execution_config"]["path"]),
            "--binding-set", str((root / projection["binding_set"]["index"]["path"]).parent),
            "--policy-capability-manifest", str(root / source["capability_manifest_descriptor"]["path"]),
            "--preprocessing-contract", str(preprocessing_contract_path),
            "--preprocessing-contract-receipt", str(preprocessing_receipt_path),
            "--operational-accounting-context", str(operational_context_path),
            "--runtime-dir", str(runtime_dir), "--front-socket", str(front_socket),
            "--evidence-root", str(evidence_root), "--max-connections", str(PRODUCTION_MAX_CONNECTIONS_MINIMUM),
            "--max-requests-per-connection", str(PRODUCTION_MAX_REQUESTS_PER_CONNECTION_MINIMUM),
            "--max-total-requests", str(PRODUCTION_MAX_TOTAL_REQUESTS_MINIMUM),
            "--startup-timeout-seconds", str(STARTUP_SECONDS), "--shutdown-timeout-seconds", "10"]
        self.authority_path = Path(evidence_root) / "service_authority.v1.json"
        self.lifecycle_path = Path(evidence_root) / "service_lifecycle.v1.json"
        self.deadline = deadline
        self.process = None
        self.pidfd = -1
        self.readers = []
        self.authority = None
        self.owner = None
        self.authority_pin = None
        self.last_observation = {}

    def _adopt_authority(self):
        from checkpoint_gstreamer_analytics_sidecar import query_publication_sidecar_guardian_v1
        if self.authority is not None or not os.path.lexists(self.authority_path):
            return
        pin = _pin_file(self.authority_path, METADATA_BYTES)
        try:
            authority = pin.object(METADATA_BYTES)
            _require(authority["owner_process"] == self.owner, "guardian readiness is not the original child")
            _require(query_publication_sidecar_guardian_v1(authority, timeout_s=min(5, self._remaining())) == authority,
                     "guardian live control authority differs")
            self.authority, self.authority_pin = authority, pin
        except BaseException:
            pin.close()
            raise

    def _remaining(self):
        remaining = self.deadline - time.monotonic()
        _require(remaining > 0, "component pair original deadline exceeded")
        return remaining

    def start(self):
        from backend_publication_process_supervisor_v3 import _BoundedPipeReader
        from checkpoint_gstreamer_analytics_sidecar import _process_starttime_ticks
        _require(self.process is None, "component guardian is one-shot")
        if getattr(self, "engine_descriptor", None) is not None:
            self.engine_pin = _pin_file(Path(self.engine_descriptor["path"]), 256*1024*1024)
            _require(self.engine_pin.descriptor == self.engine_descriptor, "guardian original selected engine differs")
            self.engine_pin.check()
        self.process = subprocess.Popen(self.argv, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True,
            env=getattr(self, "environment", None))
        self.last_observation.update(argv=self.argv, original_child_pid=self.process.pid,
            original_process_group=self.process.pid, boot_id=Path("/proc/sys/kernel/random/boot_id").read_text().strip())
        for name in ("stdout", "stderr"):
            reader = _BoundedPipeReader(name="component-guardian-" + name,
                                       pipe=getattr(self.process, name), limit=CHANNEL_BYTES)
            self.readers.append(reader)
            reader.start()
        self.pidfd = os.pidfd_open(self.process.pid, 0)
        self.owner = {"pid": self.process.pid, "proc_stat_starttime_ticks": _process_starttime_ticks(self.process.pid),
                      "uid": os.getuid(), "gid": os.getgid()}
        self.last_observation["owner_process"] = self.owner
        startup = min(self.deadline, time.monotonic() + STARTUP_SECONDS)
        while time.monotonic() < startup:
            self.check()
            self._adopt_authority()
            if self.authority is not None:
                return self.authority_path
            time.sleep(0.02)
        raise RuntimeError("original component guardian readiness timed out")

    def _signal_original(self, signum):
        if self.process is not None and self.process.poll() is None:
            if self.pidfd >= 0:
                signal.pidfd_send_signal(self.pidfd, signum)
            else:
                # The unreaped direct Popen child cannot have its PID reused.
                self.process.send_signal(signum)

    def check(self):
        self._remaining()
        _require(self.process is not None and self.process.poll() is None, "original component guardian exited")
        _require(not any(r.overflow or r.error is not None for r in self.readers),
                 "original component guardian capture failed")
        if self.authority_pin is not None:
            self.authority_pin.check()
        if getattr(self, "engine_pin", None) is not None:
            self.engine_pin.check()

    def close(self):
        from backend_publication_process_supervisor_v3 import _posix_group_exists
        from checkpoint_gstreamer_analytics_sidecar import (
            request_publication_sidecar_guardian_stop_v1, wait_publication_sidecar_guardian_stop_v1,
            _assert_guardian_stop_ack_matches_lifecycle_v1)
        deadline = min(self.deadline, time.monotonic() + STOP_SECONDS)
        errors = []
        authenticated = False
        lifecycle = None
        def remaining():
            value = deadline - time.monotonic()
            _require(value > 0, "original guardian cleanup deadline exceeded")
            return value
        try:
            self._adopt_authority()
            if self.authority is not None:
                self.authority_pin.check()
                ack = request_publication_sidecar_guardian_stop_v1(self.authority, timeout_s=min(5, remaining()))
                lifecycle = wait_publication_sidecar_guardian_stop_v1(self.authority, timeout_s=remaining())
                _assert_guardian_stop_ack_matches_lifecycle_v1(ack, lifecycle, expected_authority=self.authority)
                authenticated = True
            elif self.process is not None and self.process.poll() is None:
                # During start(), KeyboardInterrupt reaches existing owner.start's
                # BaseException cleanup. SIGTERM has no such pre-readiness handler.
                self._signal_original(signal.SIGINT)
            if self.process is not None:
                self.process.wait(timeout=remaining())
        except BaseException as error:
            errors.append(_error(error))
            if self.process is not None and self.process.poll() is None:
                try:
                    self._signal_original(signal.SIGINT)
                    self.process.wait(timeout=min(10, remaining()))
                except BaseException as interrupt_error:
                    errors.append(_error(interrupt_error))
                    try:
                        self._signal_original(signal.SIGKILL)
                        self.process.wait(timeout=remaining())
                    except BaseException as kill_error:
                        errors.append(_error(kill_error))
        finally:
            for reader in self.readers:
                reader.join(max(0, deadline - time.monotonic()))
                if reader.thread.is_alive() or not reader.eof or reader.overflow or reader.error is not None:
                    errors.append({"type": "CaptureFailure", "message": reader.name + " missing original bounded EOF"})
                if reader.thread.is_alive():
                    reader.stop()
                else:
                    reader.pipe.close()
            if self.authority_pin is not None:
                try:
                    self.authority_pin.check()
                except BaseException as error:
                    errors.append(_error(error))
                finally:
                    self.authority_pin.close()
            if self.pidfd >= 0:
                os.close(self.pidfd)
                self.pidfd = -1
            if getattr(self, "engine_pin", None) is not None:
                try:
                    self.engine_pin.check()
                    self.last_observation["original_engine"] = self.engine_pin.descriptor
                    self.last_observation["original_engine_socket"] = self.environment["DOCKER_HOST"]
                except BaseException as error:
                    errors.append(_error(error))
                finally:
                    self.engine_pin.close()
        group_absent = self.process is not None and not _posix_group_exists(self.process.pid)
        quiescent = group_absent and self.process.returncode is not None
        if time.monotonic() > deadline:
            errors.append({"type": "DeadlineFailure", "message": "guardian cleanup exceeded original absolute deadline"})
        self.last_observation.update(authenticated_stop=authenticated, process_quiescent=quiescent,
            returncode=None if self.process is None else self.process.returncode,
            container_cleanup_verified=bool(authenticated and lifecycle is not None and
                lifecycle["status"] == "clean_stop_nonpublication" and quiescent and not errors),
            cleanup_errors=errors, stdout=self.readers[0].payload() if self.readers else b"",
            stderr=self.readers[1].payload() if len(self.readers) > 1 else b"")
        return self.last_observation


def _dependencies():
    from publication_gstreamer_component_inputs_v1 import materialize_component_authority_v1
    from publication_guardian_component_preprocessing_contract_v1 import materialize_component_guardian_preprocessing_contract_v1
    from publication_gstreamer_component_runtime_v1 import (prepare_component_capture_plan_v1,
        materialize_component_runtime_v1, execute_component_operation_v1, cold_component_pair_v1)
    return SimpleNamespace(source=materialize_component_authority_v1, capture=prepare_component_capture_plan_v1,
        preprocessing=materialize_component_guardian_preprocessing_contract_v1, guardian=_GuardianProcess,
        runtime=materialize_component_runtime_v1, execute=execute_component_operation_v1,
        cold=cold_component_pair_v1, reserve=_scratch_reserve_v1)


def run_component_pair_v1(*, project_root, resource, output_dir, scratch_root,
        capability_manifest_path, calibration_path, model_parity_receipt_path,
        runtime_image_receipt_path, worker_freeze_receipt_path, execution_code_closure_path,
        container_engine=Path("/usr/bin/docker"), container_engine_socket=Path("/var/run/docker.sock"),
        _dependencies=None):
    """No resume/retry option: each command owns a fresh single resource pair."""
    _require(resource in ("cpu", "gpu"), "component CLI resource is not CPU/GPU")
    deps = _dependencies or globals()["_dependencies"]()
    started_ns, deadline = time.time_ns(), time.monotonic() + PAIR_SECONDS
    input_paths = dict(zip(INPUT_NAMES, (capability_manifest_path, calibration_path, model_parity_receipt_path,
        runtime_image_receipt_path, worker_freeze_receipt_path, execution_code_closure_path)))
    with PhysicalRootCustodyV1.open(project_root, label="component CLI original project") as custody, contextlib.ExitStack() as stack:
        root = custody.root
        output = Path(output_dir)
        if not output.is_absolute():
            output = root / output
        _require(output.is_relative_to(root) and output != root and not os.path.lexists(output),
                 "component CLI output is occupied or outside project")
        scratch_base = _absolute(root, scratch_root)
        scratch_namespace = scratch_base / ("vast-component-" + hashlib.sha256(str(output).encode()).hexdigest()[:16])
        _require(not os.path.lexists(scratch_namespace), "component CLI scratch/socket namespace is occupied")
        pins = {}
        for name, raw_path in input_paths.items():
            path = _absolute(root, raw_path)
            _require(path.is_relative_to(root), "component CLI source input escaped project")
            descriptor, _ = custody.read_descriptor(path, label="component CLI selected input", maximum=16*1024*1024)
            descriptor["path"] = str(path)
            held = _PinnedFile(path, descriptor, limit=16*1024*1024)
            held.descriptor = descriptor
            stack.callback(held.close)
            pins[name] = held
            input_paths[name] = path
        launch_pins = {}
        source_paths = [Path(__file__).absolute(), Path(sys.executable).resolve(strict=True)]
        if _dependencies is None:
            source_paths.append(root / "scripts/checkpoint_gstreamer_analytics_sidecar.py")
        for path in dict.fromkeys(source_paths):
            pin = _pin_file(path, 256*1024*1024)
            stack.callback(pin.close)
            launch_pins[str(path)] = pin
        custody.ensure_directory_owned(output, label="new component CLI output")
        guardian = None
        cleanup = {}
        primary = None
        cleanup_errors = []
        pair = None
        reserve = None
        common = {}
        try:
            with deps.reserve(project_root=root, scratch_namespace=scratch_namespace, output_dir=output) as reserve:
                source = deps.source(project_root=root, resource=resource, output_dir=output / "source",
                    container_engine=container_engine, container_engine_socket=container_engine_socket, **input_paths)
                authority_path = Path(source["authority_path"])
                capture = deps.capture(project_root=root, component_authority_path=authority_path,
                    execution_code_closure_path=input_paths["execution_code_closure_path"],
                    output_dir=output / "operations", guardian_output_dir=output / "guardian-operational")
                capture_path = Path(capture["descriptor"]["path"])
                if not capture_path.is_absolute():
                    capture_path = root / capture_path
                context_path = Path(capture["value"]["guardian_context"]["path"])
                if not context_path.is_absolute():
                    context_path = root / context_path
                preprocessing = deps.preprocessing(project_root=root, component_authority_path=authority_path,
                    operational_context_path=context_path, output_dir=output / "preprocessing")
                common = dict(project_root=root, component_authority_path=authority_path, capture_plan_path=capture_path,
                    preprocessing_contract_path=preprocessing["contract_path"],
                    preprocessing_receipt_path=preprocessing["receipt_path"],
                    analytics_socket_path=scratch_namespace / "guardian" / "analytics-execution.sock",
                    scratch_root=scratch_namespace)
                _require(len(os.fsencode(common["analytics_socket_path"])) < 108, "component socket path exceeds Unix bound")
                guardian = deps.guardian(project_root=root, component_authority_path=authority_path,
                    preprocessing_contract_path=common["preprocessing_contract_path"],
                    preprocessing_receipt_path=common["preprocessing_receipt_path"],
                    operational_context_path=context_path, runtime_dir=scratch_namespace / "guardian",
                    front_socket=common["analytics_socket_path"], evidence_root=output / "guardian", deadline=deadline)
                try:
                    common["guardian_authority_path"] = guardian.start()
                    runtime = deps.runtime(**common, output_dir=output / "runtime")
                    records = runtime["receipt"]["bundles"]
                    _require(len(records) == 2 and len({row["operation_id"] for row in records}) == 2,
                             "component runtime does not bind exactly two distinct original operations")
                    _require([row["operation_id"] for row in records] ==
                             [row["operation_id"] for row in capture["value"]["native_contexts"]],
                             "component runtime changed the original paired execution order")
                    arms, bundle_paths = [], []
                    for row in records:
                        guardian.check()
                        _require(time.monotonic() < deadline, "component original pair deadline exceeded")
                        for pin in (*pins.values(), *launch_pins.values()):
                            pin.check()
                        path = Path(row["descriptor"]["path"])
                        if not path.is_absolute():
                            path = root / path
                        result = deps.execute(**common, runtime_bundle_path=path, operation_id=row["operation_id"])
                        arms.append(Path(result["descriptor"]["path"]))
                        bundle_paths.append(path)
                except BaseException as error:
                    primary = error
                    raise
                finally:
                    try:
                        cleanup = guardian.close()
                        _require(cleanup.get("authenticated_stop") is True and cleanup.get("process_quiescent") is True
                            and cleanup.get("container_cleanup_verified") is True and cleanup.get("returncode") == 0,
                            "original guardian closure is unsuccessful or unknown")
                    except BaseException as error:
                        cleanup = getattr(guardian, "last_observation", cleanup)
                        cleanup_errors.append(_error(error))
                        if primary is None:
                            raise
                        primary.add_note("component guardian cleanup also failed: " + str(error))
                pair = deps.cold(**common, runtime_bundle_paths=bundle_paths, arm_result_paths=arms,
                    guardian_lifecycle_path=guardian.lifecycle_path, output_dir=output / "cold-pair")
                for pin in (*pins.values(), *launch_pins.values()):
                    pin.check()
                custody.verify()
                _require(time.monotonic() < deadline, "component original pair deadline exceeded before terminal")
        except BaseException as error:
            primary = primary or error
            if reserve is None:
                reserve = getattr(error, "component_reservation", None)
        finally:
            if reserve is not None and reserve.get("released") is not True:
                cleanup_errors.append({"type": "ReserveFailure", "message": "original reserve release unverified"})
            terminal = {"schema_version": 1, "artifact_kind": "vast_gstreamer_component_cli_terminal_v1",
                "resource": resource, "status": "failed" if primary is not None or cleanup_errors else "component_pair_complete",
                "started_at_ns": started_ns, "terminal_at_ns": time.time_ns(), "deadline_seconds": PAIR_SECONDS,
                "primary_error": None if primary is None else _error(primary), "cleanup_errors": cleanup_errors,
                "guardian_cleanup_verified": cleanup.get("container_cleanup_verified") is True and not cleanup_errors,
                "guardian_observation": {k:v for k,v in cleanup.items() if k not in ("stdout", "stderr")},
                "capacity_reservation": reserve, "input_pins": {k:{"descriptor":pin.descriptor,"epoch":list(pin.before)} for k,pin in pins.items()},
                "launch_source_pins": {k:{"descriptor":pin.descriptor,"epoch":list(pin.before)} for k,pin in launch_pins.items()},
                "original_executable_argv_path": sys.executable,
                "component_pairs": 1 if primary is None and not cleanup_errors and pair else 0,
                "pair_result": None if pair is None else pair["descriptor"], "qualification_eligible": False,
                "q4_eligible": False, "publication_ready": False, "full_run_eligible": False,
                "qualification_cells": 0, "q4_runs": 0, "full_arms": 0}
            try:
                for name in ("stdout", "stderr"):
                    payload = cleanup.get(name, b"")
                    _require(type(payload) is bytes and len(payload) <= CHANNEL_BYTES, "guardian raw channel exceeds bound")
                    terminal["guardian_" + name] = _write_channel(custody, output, "guardian." + name + ".log", payload)
                sealed = payload_with_sha256_v1(terminal)
                raw = json.dumps(sealed, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode() + b"\n"
                _require(len(raw) <= METADATA_BYTES, "component CLI terminal exceeds metadata bound")
                custody.write_exclusive(output / TERMINAL_FILENAME, raw, label="component CLI original terminal last")
                try:
                    if primary is None:
                        for pin in (*pins.values(), *launch_pins.values()):
                            pin.check()
                    _require(time.monotonic() < deadline, "component terminal closed after its original deadline")
                    custody.verify()
                except BaseException as late_error:
                    companion = payload_with_sha256_v1({"schema_version":1,
                        "artifact_kind":"vast_component_cli_late_failure_v1", "status":"failed",
                        "publication_ready":False, "error":_error(late_error),
                        "original_terminal_sha256":hashlib.sha256(raw).hexdigest()})
                    custody.write_exclusive(output / "component_cli_late_failure.v1.json",
                        json.dumps(companion,sort_keys=True,separators=(",", ":")).encode()+b"\n",
                        label="original component CLI late failure")
                    raise
            except BaseException as error:
                if primary is None:
                    raise
                primary.add_note("component terminal persistence also failed: " + str(error))
        if primary is not None:
            raise primary
        _require(not cleanup_errors, "component CLI cleanup failed")
        return {"terminal_path": output / TERMINAL_FILENAME, "pair": pair}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("project_root", "output_dir", "scratch_root", *INPUT_NAMES):
        parser.add_argument("--" + name.replace("_", "-"), type=Path, required=True)
    parser.add_argument("--resource", choices=("cpu", "gpu"), required=True)
    parser.add_argument("--container-engine", type=Path, default=Path("/usr/bin/docker"))
    parser.add_argument("--container-engine-socket", type=Path, default=Path("/var/run/docker.sock"))
    try:
        result = run_component_pair_v1(**vars(parser.parse_args(argv)))
    except (RuntimeError, ValueError, OSError, KeyError) as error:
        print("component pair failed: " + str(error)[:4096], file=sys.stderr)
        return 78
    print(json.dumps({"terminal_path": str(result["terminal_path"]), "pair": result["pair"]["descriptor"]},
                     sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
