"""Optional original-container observations and exact-CID cleanup.

This helper never launches measurement or substitutes its result. The stock
wrapper owns its original Docker run; only separately bounded info/inspect/stop
commands use that same held engine and socket here.
"""
from __future__ import annotations

import copy
from contextlib import contextmanager
import datetime
import hashlib
import os
from pathlib import Path
import re
import selectors
import signal
import stat
import subprocess
import time
import uuid

from publication_operational_process_custody_v1 import (
    current_original_engine_capture_v1, original_process_validator_v1,
)
from publication_operational_request_domain_v1 import (
    canonical_json_v1, payload_with_sha256_v1, strict_json_object_v1,
    validate_descriptor_v1,
)
from publication_physical_io_v1 import PhysicalRootCustodyV1

MAX_FACT_BYTES = 65536
MAX_OUTPUT_BYTES = 16384
MAX_OUTPUT_FACT_BYTES = 131072
MAX_COMMANDS = 8
LABEL = "vast.operational-custody"
PROJECTION = ('{"Id":{{json .Id}},"Name":{{json .Name}},"Image":{{json .Image}},'
    '"Created":{{json .Created}},"Running":{{json .State.Running}},'
    '"OOMKilled":{{json .State.OOMKilled}},"ExitCode":{{json .State.ExitCode}},'
    '"Pid":{{json .State.Pid}},"StartedAt":{{json .State.StartedAt}},'
    '"FinishedAt":{{json .State.FinishedAt}},'
    '"Operation":{{json (index .Config.Labels "' + LABEL + '")}}}')
STATE_FIELDS = {"Id", "Name", "Image", "Created", "Running", "OOMKilled",
    "ExitCode", "Pid", "StartedAt", "FinishedAt", "Operation"}
RESERVATION_FIELDS = {"schema_version", "artifact_kind", "operation_id", "original_operation",
    "native_context", "container_image", "controller", "name", "label", "reserved_at_ns",
    "cidfile", "engine", "engine_socket", "daemon_id", "sha256"}
COMMAND_FIELDS = {"schema_version", "artifact_kind", "operation_id", "seq", "role", "argv",
    "child", "executable_observation", "engine", "engine_socket", "started_at_ns", "terminal_at_ns", "returncode",
    "timed_out", "capture_exceeded", "capture_drain_failed", "stdout", "stderr", "sha256"}
RECEIPT_FIELDS = {"schema_version", "artifact_kind", "operation_id", "original_operation", "native_context",
    "container_image", "reservation", "cidfile", "container_id", "cid_source", "commands",
    "terminal_command_seq", "measurement_returncode", "status", "failure", "started_at_ns",
    "finished_at_ns", "accepted", "publication_ready", "sha256"}


def _require(ok, message):
    if not ok:
        raise ValueError(message)


def _epoch(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size,
        info.st_mtime_ns, info.st_ctime_ns)


def _owner(pid):
    raw = Path(f"/proc/{pid}/stat").read_text()
    values = raw[raw.rfind(")") + 2:].split()
    status = Path(f"/proc/{pid}/status").read_text().splitlines()
    identities = {line.split(":", 1)[0]: line.split()[1:] for line in status if ":" in line}
    again = Path(f"/proc/{pid}/stat").read_text()
    repeated = again[again.rfind(")") + 2:].split()
    _require((values[1], values[19]) == (repeated[1], repeated[19])
        and int(identities["Pid"][0]) == pid, "original command process identity changed during observation")
    return {"pid": pid, "proc_stat_starttime_ticks": int(values[19]),
        "uid": int(identities["Uid"][0]), "gid": int(identities["Gid"][0]),
        "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        "ppid": int(values[1])}


def _engine(pin):
    path = Path(pin.path)
    _require(path.is_absolute() and path.resolve(strict=True) == path,
        "container observer engine path is not physical")
    info = os.fstat(pin.fd)
    _require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1
        and _epoch(info) == _epoch(path.lstat()), "container observer held engine drifted")
    digest, offset = hashlib.sha256(), 0
    while offset < info.st_size:
        part = os.pread(pin.fd, min(65536, info.st_size - offset), offset)
        _require(bool(part) and info.st_size <= 256 * 1024 * 1024, "container observer engine size invalid")
        digest.update(part)
        offset += len(part)
    _require(offset == pin.size and digest.hexdigest() == pin.sha256
        and _epoch(os.fstat(pin.fd)) == _epoch(info), "container observer engine bytes drifted")
    return {"path": str(path), "size_bytes": pin.size, "sha256": pin.sha256,
        "device": info.st_dev, "inode": info.st_ino, "mode": info.st_mode,
        "owner_uid": info.st_uid, "owner_gid": info.st_gid,
        "fd": pin.fd, "proc_path": pin.proc_path}


def _socket(value):
    _require(type(value) is dict and set(value) == {"path", "device", "inode", "owner_uid", "owner_gid"},
        "container observer socket fields invalid")
    path = Path(value["path"])
    info = path.lstat()
    _require(path.is_absolute() and path.resolve(strict=True) == path and stat.S_ISSOCK(info.st_mode)
        and (info.st_dev, info.st_ino, info.st_uid, info.st_gid) == tuple(value[key]
        for key in ("device", "inode", "owner_uid", "owner_gid")), "container observer socket drifted")
    return copy.deepcopy(value)


def _read_cid(path):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            before = os.fstat(fd)
            _require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
                and before.st_uid == os.getuid() and 64 <= before.st_size <= 65,
                "original CID file custody invalid")
            raw = os.read(fd, 66)
            _require(_epoch(before) == _epoch(os.fstat(fd)) == _epoch(Path(path).lstat()),
                "original CID file changed while reading")
        finally:
            os.close(fd)
    except OSError as error:
        raise ValueError("original CID file is not exact regular bytes") from error
    _require(re.fullmatch(b"[0-9a-f]{64}\n?", raw) is not None, "original CID file is malformed")
    return raw[:64].decode("ascii"), raw


def _confirmed_absent(returncode, stdout, stderr, identifier):
    # The pinned Docker CLI emits one empty formatted output line even when
    # ContainerInspect returns exact NotFound; retain that byte unchanged.
    if type(returncode) is not int or returncode != 1 or stdout not in (b"", b"\n"):
        return False
    prefixes = ("Error response from daemon: No such container: ", "Error: No such object: ",
        "Error: No such container: ")
    return stderr in tuple((prefix + identifier + "\n").encode("ascii") for prefix in prefixes)


def _timestamp_ns(value):
    _require(type(value) is str, "original container creation timestamp missing")
    match = re.fullmatch(r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.(\d{1,9}))?Z", value)
    _require(match is not None, "original container creation timestamp invalid")
    seconds = int(datetime.datetime.fromisoformat(match[1] + "+00:00").timestamp())
    return seconds * 1000000000 + int((match[2] or "").ljust(9, "0"))


def _state(raw, reservation, identifier, observed_at_ns):
    value = strict_json_object_v1(raw, max_bytes=MAX_OUTPUT_BYTES)
    _require(set(value) == STATE_FIELDS and re.fullmatch(r"[0-9a-f]{64}", str(value["Id"]))
        and value["Name"] == "/" + reservation["name"]
        and value["Operation"] == reservation["label"]
        and value["Image"] == reservation["container_image"]["image_id"]
        and (identifier == reservation["name"] or value["Id"] == identifier),
        "observed container is not the reserved original")
    _require(type(value["Running"]) is bool and type(value["OOMKilled"]) is bool
        and type(value["ExitCode"]) is int and type(value["Pid"]) is int and value["Pid"] >= 0,
        "observed original container terminal fields invalid")
    created = _timestamp_ns(value["Created"])
    _require(reservation["reserved_at_ns"] <= created <= observed_at_ns,
        "observed container predates original reservation")
    for key in ("StartedAt", "FinishedAt"):
        _timestamp_ns(value[key])
    return value


def _successful_terminal(value, observed_at_ns):
    _require(value["Running"] is False and value["Pid"] == 0
        and value["ExitCode"] == 0 and value["OOMKilled"] is False,
        "original container failed or remains running")
    _require(_timestamp_ns(value["Created"]) <= _timestamp_ns(value["StartedAt"])
        <= _timestamp_ns(value["FinishedAt"]) <= observed_at_ns,
        "original container successful terminal timestamp order invalid")


class _Inactive:
    receipt_descriptor = None

    def __init__(self, argv):
        self.argv = argv

    def completed(self, returncode):
        pass


class _ContainerCustody:
    def __init__(self, capture, engine, socket, argv):
        _require(type(argv) is tuple and argv[:1] == ("run",)
            and "--cidfile" not in argv and "--name" not in argv,
            "original measurement container arguments invalid")
        self.capture, self.engine_pin = capture, engine
        self.engine, self.socket = _engine(engine), _socket(socket)
        self.started = time.time_ns()
        self.root = capture.output_dir / "container-custody"
        _require(not os.path.lexists(self.root), "original container reservation already exists")
        capture.custody.ensure_directory(self.root, label="original container custody")
        self.root_fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        self.root_identity = _epoch(os.fstat(self.root_fd))[:4]
        try:
            self.commands, self.failure, self.receipt_descriptor = [], None, None
            self.measurement_returncode, self.cid, self.cid_source, self.cid_descriptor = None, None, None, None
            self.terminal_seq = None
            self.cidfile = self.root / "measurement.cid"
            self.name = "vast-op-" + uuid.uuid4().hex
            label = hashlib.sha256(canonical_json_v1({"operation_id": capture.operation_id,
                "original_operation": capture.original_operation_descriptor,
                "native_context": capture.native_context_descriptor, "name": self.name,
                "controller": capture.controller})).hexdigest()
            self.reservation = {"schema_version": 1, "artifact_kind": "vast_original_container_reservation_v1",
                "operation_id": capture.operation_id, "original_operation": capture.original_operation_descriptor,
                "native_context": capture.native_context_descriptor, "container_image": capture.container_image,
                "controller": capture.controller, "name": self.name, "label": label,
                "reserved_at_ns": self.started, "cidfile": str(self.cidfile),
                "engine": self.engine, "engine_socket": self.socket, "daemon_id": None}
            daemon = self._command("daemon_before", ("info", "--format", "{{json .ID}}"))
            self.daemon = self._daemon(daemon)
            self.reservation["daemon_id"] = self.daemon
            empty = self._command("reservation_absence", self._inspect_argv(self.name))
            _require(self._absent(empty, self.name), "reserved original container name already exists or cannot be checked")
            _require(self.failure is None, "container reservation persistence failed")
            self.reservation_descriptor = self._write("reservation.v1.json", self.reservation)
            self.argv = ("run", "--cidfile", str(self.cidfile), "--name", self.name,
                "--label", LABEL + "=" + label, *argv[1:])
        except BaseException:
            os.close(self.root_fd)
            raise

    def _verify(self):
        self.capture.verify()
        _require(_epoch(os.fstat(self.root_fd))[:4] == self.root_identity
            == _epoch(self.root.lstat())[:4], "original container directory custody drifted")
        _require(_engine(self.engine_pin) == self.engine and _socket(self.socket) == self.socket,
            "original container engine binding drifted")

    def _write(self, name, value, maximum=MAX_FACT_BYTES):
        self._verify()
        raw = canonical_json_v1(payload_with_sha256_v1(value)) + b"\n"
        _require(len(raw) <= maximum, "original container fact exceeds byte bound")
        descriptor = self.capture.custody.write_exclusive(self.root / name, raw,
            label="original container fact", mode=0o444)
        descriptor["path"] = str(self.root / name)
        return descriptor

    def _output(self, name, raw):
        # Ordinary JSON preserves actual UTF-8 bytes, including empty output;
        # the shared physical writer deliberately disallows empty artifacts.
        content = raw.decode("utf-8")
        _require(content.encode("utf-8") == raw and len(raw) <= MAX_OUTPUT_BYTES,
            "original container command output is not bounded UTF-8")
        return self._write(name, {"schema_version": 1,
            "artifact_kind": "vast_original_container_command_output_v1", "content": content,
            "size_bytes": len(raw), "content_sha256": hashlib.sha256(raw).hexdigest()}, MAX_OUTPUT_FACT_BYTES)

    @staticmethod
    def _inspect_argv(identifier):
        return ("container", "inspect", "--format", PROJECTION, identifier)

    @staticmethod
    def _absent(result, identifier):
        return not any(result[key] for key in ("timed_out", "capture_exceeded", "capture_drain_failed")) \
            and _confirmed_absent(result["returncode"], result["stdout"], result["stderr"], identifier)

    @staticmethod
    def _daemon(result):
        _require(result["returncode"] == 0 and result["stderr"] == b""
            and not any(result[key] for key in ("timed_out", "capture_exceeded", "capture_drain_failed")),
            "original engine daemon identity unavailable")
        import json
        value = json.loads(result["stdout"])
        _require(type(value) is str and bool(re.fullmatch(r"[A-Za-z0-9:-]{1,128}", value)),
            "original engine daemon identity invalid")
        return value

    def _command(self, role, argv):
        """Observe/stop only through the original held CLI; never measure here."""
        self._verify()
        _require(len(self.commands) < MAX_COMMANDS, "original container command count exhausted")
        seq, start = len(self.commands) + 1, time.time_ns()
        process = subprocess.Popen([self.engine_pin.proc_path, *argv], executable=self.engine_pin.proc_path,
            cwd="/", env={"DOCKER_HOST": "unix://" + self.socket["path"], "LANG": "C",
            "LC_ALL": "C", "PATH": "/usr/bin:/bin"}, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=True,
            pass_fds=(self.engine_pin.fd,), start_new_session=True)
        captures, exceeded, timeout, drain_failed, child = {"stdout": bytearray(), "stderr": bytearray()}, False, False, False, None
        executable_observation = None
        deadline = time.monotonic() + 15
        try:
            child = _owner(process.pid)
            _require(child["ppid"] == self.capture.controller["pid"]
                and all(child[key] == self.capture.controller[key] for key in ("uid", "gid", "boot_id")),
                "container command child ownership drifted")
            try:
                executable = os.stat(f"/proc/{process.pid}/exe")
                _require((executable.st_dev, executable.st_ino) == (self.engine["device"], self.engine["inode"]),
                    "container command held executable drifted")
                executable_observation = "observed_held_executable"
            except FileNotFoundError:
                raw = Path(f"/proc/{process.pid}/stat").read_text()
                values = raw[raw.rfind(")") + 2:].split()
                _require(values[0] == "Z" and int(values[19]) == child["proc_stat_starttime_ticks"],
                    "container command executable observation unavailable for live child")
                executable_observation = "unavailable_original_child_zombie"
            with selectors.DefaultSelector() as selector:
                for name, stream in (("stdout", process.stdout), ("stderr", process.stderr)):
                    os.set_blocking(stream.fileno(), False)
                    selector.register(stream, selectors.EVENT_READ, name)
                while selector.get_map() or process.poll() is None:
                    if time.monotonic() >= deadline or exceeded:
                        timeout = not exceeded
                        break
                    for key, _ in selector.select(.05):
                        part = os.read(key.fd, 65536)
                        if not part:
                            selector.unregister(key.fileobj)
                        elif len(captures[key.data]) + len(part) > MAX_OUTPUT_BYTES:
                            exceeded = True
                            captures[key.data].extend(part[:MAX_OUTPUT_BYTES - len(captures[key.data])])
                        else:
                            captures[key.data].extend(part)
                drain_failed = bool(selector.get_map())
        finally:
            try:
                if process.poll() is None:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except OSError:
                        process.kill()
                process.wait(timeout=10)
            finally:
                for stream in (process.stdout, process.stderr):
                    try:
                        stream.close()
                    except OSError:
                        pass
        result = {"returncode": process.returncode, "stdout": bytes(captures["stdout"]),
            "stderr": bytes(captures["stderr"]), "timed_out": timeout,
            "capture_exceeded": exceeded, "capture_drain_failed": drain_failed, "seq": seq,
            "terminal_at_ns": time.time_ns()}
        descriptor = None
        try:
            stdout = self._output(f"command_{seq:02d}.stdout", result["stdout"])
            stderr = self._output(f"command_{seq:02d}.stderr", result["stderr"])
            descriptor = self._write(f"command_{seq:02d}.v1.json", {"schema_version": 1,
                "artifact_kind": "vast_original_container_engine_observation_v1", "operation_id": self.capture.operation_id,
                "seq": seq, "role": role, "argv": [self.engine_pin.proc_path, *argv], "child": child,
                "executable_observation": executable_observation,
                "engine": self.engine, "engine_socket": self.socket, "started_at_ns": start,
                "terminal_at_ns": result["terminal_at_ns"], "returncode": result["returncode"],
                "timed_out": timeout, "capture_exceeded": exceeded, "capture_drain_failed": drain_failed,
                "stdout": stdout, "stderr": stderr})
        except BaseException:
            self.failure = self.failure or "container_observation_persistence_failed"
        self.commands.append(descriptor)
        return result

    def completed(self, returncode):
        _require(type(returncode) is int, "original measurement status must be actual integer")
        self.measurement_returncode = returncode

    def finish(self, body_error):
        if body_error is not None or self.measurement_returncode != 0:
            self.failure = self.failure or "original_measurement_failed"
        try:
            if os.path.lexists(self.cidfile):
                try:
                    self.cid, raw = _read_cid(self.cidfile)
                    self.cid_source = "original_cidfile"
                    observed, captured = self.capture.custody.read_descriptor(self.cidfile,
                        label="original measurement CID bytes", maximum=65, capture=True)
                    observed["path"] = str(self.cidfile)
                    _require(raw == captured, "original CID bytes changed")
                    self.cid_descriptor = observed
                except BaseException:
                    self.cid, self.cid_descriptor = None, None
                    self.failure = self.failure or "original_cidfile_invalid"
            if self.cid is None:
                recovered = self._command("recover_original_cid", self._inspect_argv(self.name))
                _require(recovered["returncode"] == 0 and recovered["stderr"] == b""
                    and not any(recovered[key] for key in ("timed_out", "capture_exceeded", "capture_drain_failed")),
                    "original CID unavailable after launch")
                self.cid = _state(recovered["stdout"], self.reservation, self.name, recovered["terminal_at_ns"])["Id"]
                self.cid_source = "reserved_name_observation"
                self.failure = self.failure or "original_cidfile_missing"
            before = self._command("original_terminal", self._inspect_argv(self.cid))
            if self._absent(before, self.cid):
                self.terminal_seq = before["seq"]
            else:
                _require(before["returncode"] == 0 and before["stderr"] == b""
                    and not any(before[key] for key in ("timed_out", "capture_exceeded", "capture_drain_failed")),
                    "original container terminal observation failed")
                state = _state(before["stdout"], self.reservation, self.cid, before["terminal_at_ns"])
                if state["Running"]:
                    self.failure = self.failure or "original_container_survived_cli"
                    stopped = self._command("stop_original_cid", ("container", "stop", "--time", "5", self.cid))
                    _require(stopped["returncode"] == 0 and stopped["stderr"] == b""
                        and stopped["stdout"] == (self.cid + "\n").encode()
                        and not any(stopped[key] for key in ("timed_out", "capture_exceeded", "capture_drain_failed")),
                        "original exact-CID stop failed")
                    after = self._command("after_owned_stop", self._inspect_argv(self.cid))
                    _require(self._absent(after, self.cid) or (after["returncode"] == 0
                        and after["stderr"] == b"" and not any(after[key] for key in
                        ("timed_out", "capture_exceeded", "capture_drain_failed"))
                        and _state(after["stdout"], self.reservation, self.cid, after["terminal_at_ns"])["Running"] is False),
                        "original container remained live after exact-CID cleanup")
                    self.terminal_seq = after["seq"]
                else:
                    _successful_terminal(state, before["terminal_at_ns"])
                    self.terminal_seq = before["seq"]
            after_daemon = self._command("daemon_after", ("info", "--format", "{{json .ID}}"))
            _require(self._daemon(after_daemon) == self.daemon, "original daemon identity changed")
        except BaseException:
            self.failure = self.failure or "original_container_custody_failed"
        value = {"schema_version": 1, "artifact_kind": "vast_original_container_custody_v1",
            "operation_id": self.capture.operation_id, "original_operation": self.capture.original_operation_descriptor,
            "native_context": self.capture.native_context_descriptor, "container_image": self.capture.container_image,
            "reservation": self.reservation_descriptor, "cidfile": self.cid_descriptor,
            "container_id": self.cid, "cid_source": self.cid_source, "commands": self.commands,
            "terminal_command_seq": self.terminal_seq, "measurement_returncode": self.measurement_returncode,
            "status": "complete_original_container_custody" if self.failure is None else "failed_original_container_custody",
            "failure": self.failure, "started_at_ns": self.started, "finished_at_ns": time.time_ns(),
            "accepted": False, "publication_ready": False}
        self.receipt_descriptor = self._write("original_container_custody.v1.json", value)
        self.capture.container_receipt_descriptor = copy.deepcopy(self.receipt_descriptor)
        _require(self.failure is None, "original container custody failed: " + str(self.failure))

    def close(self):
        os.close(self.root_fd)


@contextmanager
def measurement_container_custody_v1(engine, engine_socket, argv):
    capture = current_original_engine_capture_v1()
    if capture is None:
        yield _Inactive(argv)
        return
    owned = _ContainerCustody(capture, engine, engine_socket, argv)
    error = None
    try:
        try:
            yield owned
        except BaseException as original:
            error = original
            raise
        finally:
            try:
                owned.finish(error)
            except BaseException as cleanup_error:
                if error is None:
                    raise
                note = "Original container custody failed: " + str(cleanup_error)
                note_adder = getattr(error, "add_note", None)
                if callable(note_adder):
                    note_adder(note)
                else:
                    error.__notes__ = [*getattr(error, "__notes__", ()), note]
    finally:
        owned.close()


def original_container_validator_v1(*, project_root, receipt_path, expected_descriptor=None,
        process_receipt_path, expected_process_descriptor=None, operation_id,
        original_operation_descriptor, native_context_descriptor, expected_container_image):
    """Cold physical proof of one original CLI and its exact container terminal."""
    process = original_process_validator_v1(project_root=project_root,
        receipt_path=process_receipt_path, expected_descriptor=expected_process_descriptor,
        operation_id=operation_id, original_operation_descriptor=original_operation_descriptor,
        native_context_descriptor=native_context_descriptor, expected_container_image=expected_container_image)
    launch, terminal = process["measurement"]["launch"], process["measurement"]["terminal"]
    with PhysicalRootCustodyV1.open(project_root, label="cold original container custody") as io:
        retained = []

        def read(descriptor, maximum=MAX_FACT_BYTES):
            validate_descriptor_v1(descriptor)
            _require(descriptor["size_bytes"] <= maximum, "container descriptor exceeds physical bound")
            fd = os.open(descriptor["path"], os.O_RDONLY | os.O_NOFOLLOW)
            try:
                epoch = _epoch(os.fstat(fd))
                _require(stat.S_ISREG(epoch[2]) and epoch[3] == 1,
                    "original container input is not single-link regular bytes")
                actual, raw = io.read_descriptor(descriptor["path"], label="original container physical fact",
                    maximum=maximum, capture=True)
                actual["path"] = descriptor["path"]
                _require(actual == descriptor and epoch == _epoch(os.fstat(fd))
                    == _epoch(Path(descriptor["path"]).lstat()), "original container physical descriptor mismatch")
                retained.append((copy.deepcopy(descriptor), maximum, epoch))
            finally:
                os.close(fd)
            return raw

        def fact(descriptor, fields, kind, maximum=MAX_FACT_BYTES):
            value = strict_json_object_v1(read(descriptor, maximum), max_bytes=maximum)
            _require(set(value) == fields and type(value["schema_version"]) is int
                and value["schema_version"] == 1 and value["artifact_kind"] == kind
                and payload_with_sha256_v1(value)["sha256"] == value["sha256"],
                "original container fact schema or self seal mismatch")
            return value

        if expected_descriptor is None:
            expected_descriptor, _ = io.read_descriptor(receipt_path, label="original container receipt",
                maximum=MAX_FACT_BYTES, capture=False)
            expected_descriptor["path"] = str(receipt_path)
        _require(str(receipt_path) == expected_descriptor["path"], "original container receipt path mismatch")
        receipt = fact(expected_descriptor, RECEIPT_FIELDS, "vast_original_container_custody_v1")
        _require(receipt["operation_id"] == operation_id
            and receipt["original_operation"] == original_operation_descriptor
            and receipt["native_context"] == native_context_descriptor
            and receipt["container_image"] == expected_container_image
            and receipt["status"] == "complete_original_container_custody" and receipt["failure"] is None
            and type(receipt["measurement_returncode"]) is int and receipt["measurement_returncode"] == terminal["returncode"] == 0
            and receipt["accepted"] is False and receipt["publication_ready"] is False,
            "original container capture is failed or foreign")
        root = Path(receipt_path).parent
        _require(root.name == "container-custody"
            and receipt["reservation"]["path"] == str(root / "reservation.v1.json"),
            "original container evidence namespace mismatch")
        reservation = fact(receipt["reservation"], RESERVATION_FIELDS, "vast_original_container_reservation_v1")
        _require(reservation["operation_id"] == operation_id
            and reservation["original_operation"] == original_operation_descriptor
            and reservation["native_context"] == native_context_descriptor
            and reservation["container_image"] == expected_container_image
            and reservation["controller"] == launch["controller"]
            and reservation["engine"] == launch["engine"]
            and reservation["engine_socket"] == launch["engine_socket"]
            and type(reservation["name"]) is str and re.fullmatch(r"vast-op-[0-9a-f]{32}", reservation["name"])
            and reservation["cidfile"] == str(root / "measurement.cid"),
            "original reservation differs from original process launch")
        label = hashlib.sha256(canonical_json_v1({"operation_id": operation_id,
            "original_operation": original_operation_descriptor, "native_context": native_context_descriptor,
            "name": reservation["name"], "controller": launch["controller"]})).hexdigest()
        _require(reservation["label"] == label and receipt["started_at_ns"] == reservation["reserved_at_ns"]
            and type(receipt["started_at_ns"]) is int and type(receipt["finished_at_ns"]) is int
            and receipt["started_at_ns"] <= launch["started_at_ns"] <= terminal["terminal_at_ns"] <= receipt["finished_at_ns"],
            "original container reservation label or time mismatch")
        argv = launch["argv"]
        for key, value in (("--cidfile", reservation["cidfile"]), ("--name", reservation["name"]),
                ("--label", LABEL + "=" + label)):
            _require(argv.count(key) == 1 and argv.index(key) + 1 < len(argv)
                and argv[argv.index(key) + 1] == value, "original CLI did not launch its reserved container")
        _require(argv[1] == "run" and expected_container_image["image_id"] in argv,
            "original measurement image or engine command mismatch")
        _require(receipt["cid_source"] == "original_cidfile" and receipt["cidfile"] is not None
            and receipt["cidfile"]["path"] == reservation["cidfile"], "original CID file was not retained")
        raw = read(receipt["cidfile"], 65)
        _require(re.fullmatch(b"[0-9a-f]{64}\n?", raw) is not None
            and receipt["container_id"] == raw[:64].decode("ascii"), "original CID bytes mismatch")
        cid = receipt["container_id"]
        commands = receipt["commands"]
        # Any survivor requiring stop is a failed measurement, retained for diagnosis.
        _require(type(commands) is list and len(commands) == 4 and receipt["terminal_command_seq"] == 3,
            "original successful container command coverage is incomplete")
        roles = ("daemon_before", "reservation_absence", "original_terminal", "daemon_after")
        first_daemon, last_daemon, state = None, None, None
        last = receipt["started_at_ns"]
        for seq, (descriptor, role) in enumerate(zip(commands, roles), 1):
            _require(descriptor["path"] == str(root / f"command_{seq:02d}.v1.json"),
                "original command fact path mismatch")
            row = fact(descriptor, COMMAND_FIELDS, "vast_original_container_engine_observation_v1")
            _require(row["operation_id"] == operation_id and type(row["seq"]) is int and row["seq"] == seq
                and row["role"] == role and row["engine"] == launch["engine"]
                and row["engine_socket"] == launch["engine_socket"]
                and row["executable_observation"] in {"observed_held_executable", "unavailable_original_child_zombie"}
                and all(row[key] is False for key in ("timed_out", "capture_exceeded", "capture_drain_failed"))
                and type(row["returncode"]) is int, "original command binding or terminal mismatch")
            owner = row["child"]
            _require(type(owner) is dict and set(owner) == set(launch["child"])
                and all(owner[key] == launch["controller"][key] for key in ("uid", "gid", "boot_id"))
                and owner["ppid"] == launch["controller"]["pid"]
                and type(owner["pid"]) is int and owner["pid"] > 0
                and type(owner["proc_stat_starttime_ticks"]) is int
                and owner["proc_stat_starttime_ticks"] >= launch["controller"]["proc_stat_starttime_ticks"],
                "original observation child ownership mismatch")
            _require(type(row["started_at_ns"]) is int and type(row["terminal_at_ns"]) is int
                and last <= row["started_at_ns"] <= row["terminal_at_ns"] <= receipt["finished_at_ns"],
                "original command time order mismatch")
            if seq == 3:
                _require(terminal["terminal_at_ns"] <= row["started_at_ns"],
                    "container terminal observation predates original CLI terminal")
            last = row["terminal_at_ns"]
            result = {key: row[key] for key in ("returncode", "timed_out", "capture_exceeded", "capture_drain_failed", "terminal_at_ns")}
            for stream in ("stdout", "stderr"):
                _require(row[stream]["path"] == str(root / f"command_{seq:02d}.{stream}"),
                    "original command output path mismatch")
                output = fact(row[stream], {"schema_version", "artifact_kind", "content", "size_bytes",
                    "content_sha256", "sha256"}, "vast_original_container_command_output_v1", MAX_OUTPUT_FACT_BYTES)
                _require(type(output["content"]) is str and len(output["content"]) <= MAX_OUTPUT_BYTES,
                    "original container command output text exceeds bound")
                raw_output = output["content"].encode("utf-8")
                _require(len(raw_output) <= MAX_OUTPUT_BYTES and type(output["size_bytes"]) is int
                    and output["size_bytes"] == len(raw_output)
                    and output["content_sha256"] == hashlib.sha256(raw_output).hexdigest(),
                    "original container command bytes or digest mismatch")
                result[stream] = raw_output
            expected = ("info", "--format", "{{json .ID}}") if seq in (1, 4) else _ContainerCustody._inspect_argv(
                reservation["name"] if seq == 2 else cid)
            _require(row["argv"] == [launch["engine"]["proc_path"], *expected],
                "original observer used foreign engine command")
            if seq == 1:
                first_daemon = _ContainerCustody._daemon(result)
            elif seq == 2:
                _require(_ContainerCustody._absent(result, reservation["name"]),
                    "original name collision or unavailable prelaunch state")
            elif seq == 3:
                if not _ContainerCustody._absent(result, cid):
                    _require(result["returncode"] == 0 and result["stderr"] == b"",
                        "original exact container terminal unavailable")
                    state = _state(result["stdout"], reservation, cid, result["terminal_at_ns"])
                    _successful_terminal(state, result["terminal_at_ns"])
            else:
                last_daemon = _ContainerCustody._daemon(result)
            del result
        _require(first_daemon == reservation["daemon_id"] == last_daemon,
            "original name collision or daemon identity mismatch")
        expected_names = {"reservation.v1.json", "measurement.cid", "original_container_custody.v1.json"}
        expected_names.update(f"command_{seq:02d}.{suffix}" for seq in range(1, 5)
            for suffix in ("stdout", "stderr", "v1.json"))
        _require(set(io.list_directory_names(root, label="original container namespace")) == expected_names,
            "original container namespace has missing or uncounted facts")
        for descriptor, maximum, epoch in retained:
            actual, _ = io.read_descriptor(descriptor["path"], label="final original container rehash",
                maximum=maximum, capture=False)
            actual["path"] = descriptor["path"]
            _require(actual == descriptor and epoch == _epoch(Path(descriptor["path"]).lstat()),
                "original container bytes changed during cold validation")
        witnesses = {}
        _require(type(process["validated_inputs"]) is list and bool(process["validated_inputs"]),
            "original process physical input witnesses are missing")
        for item in [*process["validated_inputs"], *({"descriptor": descriptor, "epoch": list(epoch)}
                for descriptor, _, epoch in retained)]:
            _require(type(item) is dict and set(item) == {"descriptor", "epoch"}
                and type(item["epoch"]) is list and len(item["epoch"]) == 7,
                "original physical input witness shape invalid")
            name = item["descriptor"]["path"]
            _require(name not in witnesses or witnesses[name] == item,
                "original physical input witness conflicts across validators")
            witnesses[name] = copy.deepcopy(item)
        io.verify()
        return {"descriptor": copy.deepcopy(expected_descriptor), "process_descriptor": process["descriptor"],
            "operation_id": operation_id, "container_id": cid, "daemon_id": reservation["daemon_id"],
            "container_quiescence_verified": True, "container_state": state,
            "oom_killed": None if state is None else state["OOMKilled"],
            "validated_inputs": list(witnesses.values())}
