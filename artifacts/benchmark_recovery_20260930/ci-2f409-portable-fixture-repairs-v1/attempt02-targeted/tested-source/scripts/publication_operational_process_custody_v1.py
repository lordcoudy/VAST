"""Optional capture of original engine CLI calls, never container quiescence.

The existing wrapper owns Popen, capture, timeout and cleanup. These hooks only
observe genuine original children at explicit phases and persist bounded facts.
"""
from __future__ import annotations

import copy
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import threading
import time

from publication_operational_request_domain_v1 import (
    canonical_json_v1, payload_with_sha256_v1, strict_json_object_v1, validate_descriptor_v1,
)
from publication_physical_io_v1 import PhysicalRootCustodyV1, PublicationPhysicalIoV1Error

PHASES = {"image_inspect", "embedded_artifact_probe", "openvino_device_probe", "nvidia_device_probe", "measurement"}
MAX_CALLS = 32
MAX_LAUNCH_BYTES = 65536
MAX_TERMINAL_BYTES = 4096
MAX_RECEIPT_BYTES = 65536
MAX_CAPTURE_BYTES = 8 * 1024 * 1024
MAX_ENGINE_BYTES = 256 * 1024 * 1024
MAX_INPUT_BYTES = 1024 * 1024
MAX_TRANSFER_METADATA_BYTES = 8192
IMAGE_FIELDS = {"image_id", "repository_digest", "inspect_projection_sha256", "base_image_id"}
GVA_IMAGE_FIELDS = {"image_id", "repository_digest", "inspect_projection_sha256"}
SDK_IMAGE_FIELDS = {"image_id", "repository_digest", "inspect_sha256", "coordinator_path", "required_labels"}
SOCKET_FIELDS = {"path", "device", "inode", "owner_uid", "owner_gid"}
OWNER_FIELDS = {"pid", "proc_stat_starttime_ticks", "uid", "gid", "boot_id", "ppid"}
ENGINE_FIELDS = {"path", "size_bytes", "sha256", "device", "inode", "mode", "owner_uid", "owner_gid", "fd", "proc_path"}
LAUNCH_FIELDS = {"schema_version", "artifact_kind", "operation_id", "phase", "call_seq", "controller", "child",
                 "engine", "engine_socket", "container_image", "argv", "argv_sha256", "started_at_ns", "executable_observation", "measurement_binding", "sha256"}
TERMINAL_FIELDS = {"schema_version", "artifact_kind", "operation_id", "call_seq", "launch_descriptor", "returncode",
                  "stdout", "stderr", "timed_out", "capture_exceeded", "capture_drain_failed", "terminal_at_ns", "sha256"}
RECEIPT_FIELDS = {"schema_version", "artifact_kind", "operation_id", "original_operation", "native_context", "container_image",
    "controller", "started_at_ns", "finished_at_ns", "status", "failure", "body_error", "call_count", "measurement_count",
    "calls", "native_transfer", "container_quiescence_verified", "accepted", "publication_ready", "sha256"}
_capture = ContextVar("vast_original_engine_capture_v1", default=None)
_phase = ContextVar("vast_original_engine_phase_v1", default=None)


def _require(ok, message):
    if not ok:
        raise ValueError(message)


def _epoch(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _path(value):
    path = Path(value)
    _require(path.is_absolute() and str(path) == os.path.normpath(str(path)) and path.resolve(strict=True) == path,
             "original process path is not physically canonical")
    return path


def _hash_fd(fd, maximum):
    digest, size, offset = hashlib.sha256(), 0, 0
    while True:
        chunk = os.pread(fd, min(1024 * 1024, maximum + 1 - size), offset)
        if not chunk:
            break
        digest.update(chunk)
        size += len(chunk)
        offset += len(chunk)
        _require(size <= maximum, "original process file exceeds byte bound")
    return size, digest.hexdigest()


def _owner_with_state(pid):
    _require(sys.platform.startswith("linux") and type(pid) is int and 0 < pid < 2**31,
             "actual original Linux process identity is required")
    def read(name, maximum):
        fd = os.open(f"/proc/{pid}/{name}", os.O_RDONLY | os.O_NOFOLLOW)
        try:
            before = os.fstat(fd)
            raw = os.read(fd, maximum + 1)
            after = os.fstat(fd)
            _require((before.st_dev, before.st_ino) == (after.st_dev, after.st_ino) and 0 < len(raw) <= maximum,
                     "original /proc process custody drifted")
            return raw
        finally:
            os.close(fd)
    def parse(raw):
        end = raw.rfind(b")")
        fields = raw[end + 2:].split()
        _require(raw.startswith(f"{pid} (".encode()) and end > 0 and len(fields) >= 20,
                 "original /proc process stat framing drifted")
        return int(fields[19]), int(fields[1]), fields[0].decode("ascii")
    ticks, ppid, _ = parse(read("stat", 4096))
    status = {}
    for line in read("status", 16384).splitlines():
        key, sep, value = line.partition(b":")
        if key in {b"Pid", b"PPid", b"Uid", b"Gid"}:
            _require(sep and key not in status, "original process credential rows ambiguous")
            status[key] = value.split()
    _require(set(status) == {b"Pid", b"PPid", b"Uid", b"Gid"} and status[b"Pid"] == [str(pid).encode()]
        and status[b"PPid"] == [str(ppid).encode()] and len(status[b"Uid"]) == len(status[b"Gid"]) == 4
        and all(value.isdigit() for name in (b"Uid", b"Gid") for value in status[name]), "original process credential identity drifted")
    reread_ticks, reread_ppid, state = parse(read("stat", 4096))
    _require((ticks, ppid) == (reread_ticks, reread_ppid), "original process identity changed across credential observation")
    boot = Path("/proc/sys/kernel/random/boot_id").read_text("ascii").strip()
    _require(ticks > 0 and re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", boot), "original process boot/start identity unavailable")
    # /proc stat inode ownership may reset to root for a zombie. Status real
    # credentials are actual observed process UID/GID, never inferred owners.
    return ({"pid": pid, "proc_stat_starttime_ticks": ticks, "uid": int(status[b"Uid"][0]), "gid": int(status[b"Gid"][0]),
             "boot_id": boot, "ppid": ppid}, state)


def _owner(pid):
    return _owner_with_state(pid)[0]


def _validate_owner(value):
    _require(type(value) is dict and set(value) == OWNER_FIELDS, "original process owner fields invalid")
    for name in ("pid", "ppid", "uid", "gid", "proc_stat_starttime_ticks"):
        maximum = (1 << 64) - 1 if name == "proc_stat_starttime_ticks" else (1 << 32) - 1
        minimum = 1 if name in {"pid", "proc_stat_starttime_ticks"} else 0
        _require(type(value[name]) is int and minimum <= value[name] <= maximum, "original process owner integer invalid")
    _require(type(value["boot_id"]) is str and re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", value["boot_id"]),
             "original process boot identity invalid")


def _image(value):
    _require(type(value) is dict and set(value) in (IMAGE_FIELDS, GVA_IMAGE_FIELDS, SDK_IMAGE_FIELDS), "original container image fields drifted")
    for key in ("image_id", "base_image_id") if set(value) == IMAGE_FIELDS else ("image_id",):
        _require(type(value[key]) is str and re.fullmatch(r"sha256:[0-9a-f]{64}", value[key]), "original container image ID invalid")
    _require(type(value["repository_digest"]) is str and len(value["repository_digest"]) <= 512
             and re.fullmatch(r"[A-Za-z0-9./:_-]+@sha256:[0-9a-f]{64}", value["repository_digest"]), "original repository digest invalid")
    inspect_key = "inspect_sha256" if set(value) == SDK_IMAGE_FIELDS else "inspect_projection_sha256"
    _require(type(value[inspect_key]) is str and re.fullmatch(r"[0-9a-f]{64}", value[inspect_key]),
             "original image projection digest invalid")
    if set(value) == SDK_IMAGE_FIELDS:
        _require(type(value["coordinator_path"]) is str and value["coordinator_path"].startswith("/")
            and len(value["coordinator_path"]) <= 512 and type(value["required_labels"]) is dict
            and len(canonical_json_v1(value["required_labels"])) <= 8192
            and all(type(k) is str and type(v) is str for k, v in value["required_labels"].items()), "original SDK image contract invalid")
    return copy.deepcopy(value)


def _original_input(raw):
    value = strict_json_object_v1(raw, max_bytes=MAX_INPUT_BYTES)
    _require(set(value) == {"schema_version", "artifact_kind", "operation", "container_image", "outputs", "sha256"}
        and value["schema_version"] == 1 and type(value["schema_version"]) is int
        and value["artifact_kind"] == "vast_original_native_operation_input_v1"
        and payload_with_sha256_v1(value)["sha256"] == value["sha256"] and canonical_json_v1(value) + b"\n" == raw,
        "original native operation input schema or seal drifted")
    _require(type(value["operation"]) is dict and type(value["outputs"]) is dict
        and set(value["outputs"]) == {"measurement_dir", "native_domain", "process_receipt", "container_receipt"}, "original output reservations drifted")
    for name in value["outputs"].values():
        path = Path(name)
        _require(type(name) is str and path.is_absolute() and os.path.normpath(name) == name, "original output reservation not canonical absolute")
    _require(Path(value["outputs"]["native_domain"]).name == "native_operational_requests.v1.jsonl", "original native domain filename drifted")
    _image(value["container_image"])
    return value


def _argv_mounts(argv):
    mounts = []
    for index, token in enumerate(argv):
        if token == "--mount":
            _require(index + 1 < len(argv), "original mount argument missing")
            fields = argv[index + 1].split(",")
            mount = {}
            for field in fields:
                key, sep, value = field.partition("=")
                _require(key not in mount and (sep or key == "readonly"), "original mount fields ambiguous")
                mount[key] = value if sep else True
            _require(set(mount) in ({"type", "src", "dst"}, {"type", "src", "dst", "readonly"}) and mount["type"] == "bind"
                and mount.get("readonly", True) is True and all(PurePosixPath(mount[key]).is_absolute() for key in ("src", "dst")), "original bind mount invalid")
            mounts.append({"source": mount["src"], "destination": mount["dst"], "readonly": "readonly" in mount})
    _require(len({row["destination"] for row in mounts}) == len(mounts), "original mount destinations duplicate")
    return mounts


def _argument(argv, flag):
    positions = [i for i, token in enumerate(argv) if token == flag]
    _require(len(positions) == 1 and positions[0] + 1 < len(argv), "original operational argument missing or repeated")
    return argv[positions[0] + 1]


def validate_original_measurement_argv_v1(*, argv, original_input, native_context_descriptor, observed_binding=None):
    """Resolve actual mount/argument facts; retired scratch is not a durable path."""
    context = _argument(argv, "--operational-request-context")
    output = _argument(argv, "--operational-output-dir")
    mounts = _argv_mounts(argv)
    _require(output == "/opt/vast/operational", "original operational output argument drifted")
    outputs = [row for row in mounts if row["destination"] == output and not row["readonly"]]
    inputs = [row for row in mounts if row["readonly"] and
              (context == row["destination"] or PurePosixPath(context).is_relative_to(PurePosixPath(row["destination"])))]
    _require(len(outputs) == len(inputs) == 1, "original operational mounts ambiguous or detached")
    input_mount, output_mount = inputs[0], outputs[0]
    relative = PurePosixPath(context).relative_to(PurePosixPath(input_mount["destination"]))
    _require(".." not in relative.parts, "original context mount escapes its input tree")
    source = Path(input_mount["source"]).joinpath(*relative.parts)
    expected = {"context_argument": context, "context_mount": input_mount, "context_source": {"path": str(source),
        "size_bytes": native_context_descriptor["size_bytes"], "sha256": native_context_descriptor["sha256"]},
        "operational_argument": output, "operational_mount": output_mount,
        "expected_native_domain": original_input["outputs"]["native_domain"],
        "expected_measurement_dir": original_input["outputs"]["measurement_dir"]}
    if observed_binding is None:
        path = _path(source)
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            info = os.fstat(fd)
            _require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and _hash_fd(fd, MAX_INPUT_BYTES) ==
                (native_context_descriptor["size_bytes"], native_context_descriptor["sha256"]) and _epoch(info) == _epoch(path.lstat()),
                "actual original context mount bytes differ from declared native context")
        finally:
            os.close(fd)
        directory = _path(output_mount["source"])
        info = directory.lstat()
        _require(stat.S_ISDIR(info.st_mode), "actual original operational output is not a directory")
        expected["operational_source_directory"] = {"path": str(directory), "device": info.st_dev, "inode": info.st_ino,
            "mode": info.st_mode, "owner_uid": info.st_uid, "owner_gid": info.st_gid}
    else:
        _require(type(observed_binding) is dict and set(observed_binding) == set(expected) | {"operational_source_directory"}
            and all(observed_binding[key] == value for key, value in expected.items()), "cold original operational argv binding drifted")
        directory = observed_binding["operational_source_directory"]
        _require(type(directory) is dict and set(directory) == {"path", "device", "inode", "mode", "owner_uid", "owner_gid"} and directory["path"] == output_mount["source"]
            and all(type(directory[key]) is int and directory[key] >= 0 for key in ("device", "inode", "mode", "owner_uid", "owner_gid"))
            and stat.S_ISDIR(directory["mode"]), "original operational directory identity invalid")
        expected["operational_source_directory"] = directory
    return expected


def _transfer_metadata(custody, inputs, target_dir):
    """Read the exact stock one-file transfer, without reopening retired scratch."""
    target_dir = Path(target_dir)
    relative = target_dir.relative_to(custody.root).as_posix()
    name = "group-" + hashlib.sha256(relative.encode("ascii")).hexdigest() + ".json"
    receipt_path = custody.root / ".publication-child-evidence-receipts-v1" / name
    intent_path = custody.root / ".publication-child-evidence-intents-v1" / name
    values, refs = {}, {}
    for label, path, kind, seal in (("receipt", receipt_path, "vast_publication_child_evidence_group_receipt_v1", "receipt_sha256"),
                                  ("intent", intent_path, "vast_publication_child_evidence_group_intent_v1", "intent_sha256")):
        descriptor, _ = custody.read_descriptor(path, label="original native transfer " + label, maximum=MAX_TRANSFER_METADATA_BYTES)
        descriptor["path"] = str(path)
        raw = inputs.read(descriptor, MAX_TRANSFER_METADATA_BYTES)
        value = strict_json_object_v1(raw, max_bytes=MAX_TRANSFER_METADATA_BYTES)
        unsigned = {key: item for key, item in value.items() if key != seal}
        _require(value.get("schema_version") == 1 and type(value["schema_version"]) is int and value.get("artifact_kind") == kind
            and value.get(seal) == hashlib.sha256(canonical_json_v1(unsigned)).hexdigest() and canonical_json_v1(value) + b"\n" == raw,
            "original stock native transfer schema or seal drifted")
        values[label], refs[label] = value, descriptor
    receipt, intent = values["receipt"], values["intent"]
    _require(set(receipt) == {"schema_version", "artifact_kind", "status", "output_directory", "output_directory_identity", "intent", "intent_sha256", "leaves", "receipt_sha256"}
        and set(intent) == {"schema_version", "artifact_kind", "status", "source_directory", "source_directory_identity", "output_directory", "output_directory_identity", "baseline", "leaves", "intent_sha256"}
        and receipt["status"] == "committed_child_evidence_group" and intent["status"] == "prepared_child_evidence_group"
        and intent["baseline"] == [] and receipt["output_directory"] == intent["output_directory"] == relative
        and receipt["output_directory_identity"] == intent["output_directory_identity"] and receipt["intent_sha256"] == intent["intent_sha256"],
        "original native transfer custody metadata drifted")
    expected_intent = {**refs["intent"], "path": intent_path.relative_to(custody.root).as_posix()}
    _require(receipt["intent"] == expected_intent and type(receipt["leaves"]) is list and len(receipt["leaves"]) == 1
        and type(intent["leaves"]) is list and len(intent["leaves"]) == 1, "original native transfer is not exact one-file stock custody")
    leaf, planned = receipt["leaves"][0], intent["leaves"][0]
    _require(set(leaf) == {"target_name", "source_name", "source", "output", "output_identity"}
        and set(planned) == {"target_name", "source_name", "source", "output"}
        and all(leaf[key] == planned[key] for key in planned)
        and leaf["source_name"] == leaf["target_name"] == "native_operational_requests.v1.jsonl", "original native transfer leaf differs")
    for descriptor in (leaf["source"], leaf["output"]):
        validate_descriptor_v1(descriptor)
    _require(leaf["source"]["path"] == intent["source_directory"] + "/native_operational_requests.v1.jsonl"
        and leaf["output"]["path"] == relative + "/native_operational_requests.v1.jsonl"
        and all(leaf["source"][key] == leaf["output"][key] for key in ("size_bytes", "sha256")), "original native transfer bytes or source path differ")
    for identity, length in ((leaf["output_identity"], 2), (receipt["output_directory_identity"], 5), (intent["source_directory_identity"], 5)):
        _require(type(identity) is list and len(identity) == length and all(type(value) is int and value >= 0 for value in identity),
                 "original native transfer physical identity invalid")
    return {"receipt": receipt, "intent": intent, "descriptors": refs}


def record_original_native_transfer_v1(source_dir, target_dir, result):
    """Record only the first actual stock scratch-to-original output transfer."""
    capture = _capture.get()
    if capture is None:
        return
    try:
        _require(capture.native_transfer is None and type(result) is tuple and len(result) == 1, "original native transfer repeated or missing stock result")
        measured = [row for row in capture.calls if row["phase"] == "measurement"]
        _require(len(measured) == 1, "original transfer has no unique measurement")
        launch = _read_record(capture.inputs, measured[0]["launch"], LAUNCH_FIELDS, "vast_original_engine_process_launch_v1", MAX_LAUNCH_BYTES)
        binding = launch["measurement_binding"]
        source_dir = _path(source_dir)
        info = source_dir.lstat()
        expected = binding["operational_source_directory"]
        _require(str(source_dir) == expected["path"] and [info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid] ==
            [expected[key] for key in ("device", "inode", "mode", "owner_uid", "owner_gid")], "original native transfer source differs from actual measurement mount")
        transfer = _transfer_metadata(capture.custody, capture.inputs, target_dir)
        _require(transfer["intent"]["source_directory"] == source_dir.name and transfer["intent"]["source_directory_identity"] ==
            [info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid] and result[0] == transfer["receipt"]["leaves"][0]["output"],
            "actual original stock native transfer result differs")
        capture.native_transfer = {"source_directory": str(source_dir), "target_directory": str(Path(target_dir)),
                                   **transfer["descriptors"]}
    except BaseException:
        capture.fail("original_native_transfer_observation_failed")
        raise


def validate_original_native_transfer_chain_v1(*, custody, inputs, first_transfer, measurement_binding, final_domain):
    _require(type(first_transfer) is dict and set(first_transfer) == {"source_directory", "target_directory", "receipt", "intent"},
             "original first native transfer missing")
    first = _transfer_metadata(custody, inputs, first_transfer["target_directory"])
    _require(first["descriptors"] == {key: first_transfer[key] for key in ("receipt", "intent")}, "original first native transfer pins differ")
    source = measurement_binding["operational_source_directory"]
    _require(first_transfer["source_directory"] == source["path"] and first["intent"]["source_directory"] == Path(source["path"]).name
        and first["intent"]["source_directory_identity"] == [source[key] for key in ("device", "inode", "mode", "owner_uid", "owner_gid")],
        "original first transfer does not bind measurement scratch")
    final_dir = Path(final_domain).parent
    transfers = [first]
    if str(final_dir) != first_transfer["target_directory"]:
        second = _transfer_metadata(custody, inputs, final_dir)
        _require(second["intent"]["source_directory"] == Path(first_transfer["target_directory"]).name
            and second["intent"]["source_directory_identity"] == first["receipt"]["output_directory_identity"]
            and all(second["receipt"]["leaves"][0]["source"][key] == first["receipt"]["leaves"][0]["output"][key] for key in ("size_bytes", "sha256")),
            "second native transfer is not the original first output")
        transfers.append(second)
    final = transfers[-1]["receipt"]
    observed, _ = custody.read_descriptor(final_domain, label="final original native transfer output", maximum=64 * 1024 * 1024, capture=False)
    inputs.read({**observed, "path": str(final_domain)}, 64 * 1024 * 1024, capture=False)
    mode, identity = custody.stat_regular_identity(final_domain, label="final original native transfer file")
    _require(observed == final["leaves"][0]["output"] and list(identity) == final["leaves"][0]["output_identity"]
        and list(custody.stat_directory_identity(final_dir, label="final original native transfer directory")[1]) == final["output_directory_identity"],
        "final original native transfer output bytes or identity changed")
    return transfers


def _socket(value):
    _require(type(value) is dict and set(value) == SOCKET_FIELDS, "original engine socket fields drifted")
    path = _path(value["path"])
    info = path.lstat()
    _require(stat.S_ISSOCK(info.st_mode) and all(type(value[key]) is int and value[key] >= 0 for key in SOCKET_FIELDS - {"path"})
        and (info.st_dev, info.st_ino, info.st_uid, info.st_gid) ==
        (value["device"], value["inode"], value["owner_uid"], value["owner_gid"]), "original engine socket identity drifted")
    return copy.deepcopy(value)


class _Inputs:
    def __init__(self, custody):
        self.custody, self.rows = custody, {}

    def read(self, descriptor, maximum=MAX_INPUT_BYTES, *, capture=True):
        validate_descriptor_v1(descriptor)
        _require(descriptor["size_bytes"] <= maximum, "original process descriptor exceeds bound")
        name = str(_path(descriptor["path"]))
        if name in self.rows:
            _require(self.rows[name][0] == descriptor, "original process conflicting physical descriptor")
            raw = self.rows[name][1]
            _require(not capture or raw is not None, "stream-only original input cannot become a cached payload")
            return raw
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            epoch = _epoch(os.fstat(fd))
            observed, raw = self.custody.read_descriptor(name, label="original process input", maximum=maximum, capture=capture)
            observed["path"] = name
            _require(observed == descriptor and epoch == _epoch(Path(name).lstat()) and epoch[3] == 1,
                     "original process input custody drifted")
            self.rows[name] = (copy.deepcopy(descriptor), raw, fd, epoch)
            return raw
        except BaseException:
            os.close(fd)
            raise

    def verify(self):
        self.custody.verify()
        for name, (descriptor, raw, fd, epoch) in self.rows.items():
            _require(_epoch(os.fstat(fd)) == epoch == _epoch(_path(name).lstat()), "held original process input changed")
            observed, current = self.custody.read_descriptor(name, label="held original process input",
                maximum=max(MAX_INPUT_BYTES, descriptor["size_bytes"]), capture=raw is not None)
            observed["path"] = name
            _require(observed == descriptor and current == raw, "held original process input bytes changed")

    def close(self):
        for row in self.rows.values():
            os.close(row[2])


@contextmanager
def _held(project_root):
    try:
        custody = PhysicalRootCustodyV1.open(project_root, label="original engine process root")
    except (OSError, PublicationPhysicalIoV1Error) as error:
        raise ValueError("original engine process custody failed: " + str(error)) from error
    # Exceptions raised by the original wrapper body retain their type and
    # traceback. Only the custody opening above belongs to this adapter.
    with custody:
        inputs = _Inputs(custody)
        try:
            yield custody, inputs
        finally:
            inputs.close()


def _write(custody, path, value, maximum):
    value = payload_with_sha256_v1(value)
    raw = canonical_json_v1(value) + b"\n"
    _require(len(raw) <= maximum, "original engine process record capacity exhausted")
    descriptor = custody.write_exclusive(path, raw, label="immutable original engine process fact", mode=0o444)
    descriptor["path"] = str(path)
    validate_descriptor_v1(descriptor)
    return descriptor


class _Capture:
    def __init__(self, custody, inputs, output_dir, operation_id, original, context, image):
        _require(type(operation_id) is str and 0 < len(operation_id) <= 128 and operation_id.isascii(), "original operation ID invalid")
        self.output_dir = Path(output_dir)
        _require(self.output_dir.is_absolute() and not os.path.lexists(self.output_dir), "original process output must be new and separate")
        self.operation_id, self.image = operation_id, _image(image)
        self.custody, self.inputs = custody, inputs
        self.original, self.context = copy.deepcopy(original), copy.deepcopy(context)
        self.original_operation_descriptor = self.original
        self.native_context_descriptor = self.context
        self.container_image = self.image
        self.container_receipt_descriptor = None
        self.original_input = _original_input(inputs.read(original))
        _require(self.original_input["container_image"] == self.image, "original image differs from physical operation input")
        _require(self.original_input["outputs"]["process_receipt"] == str(self.output_dir / "original_engine_process_capture.v1.json"),
                 "original process receipt does not match reserved immutable output")
        inputs.read(context)
        custody.ensure_directory(self.output_dir, label="separate original engine process evidence")
        self.controller, self.started = _owner(os.getpid()), time.time_ns()
        self.calls, self.engines, self.failure = [], [], None
        self.receipt_descriptor = None
        self.native_transfer = None
        self.lock = threading.RLock()

    def fail(self, reason):
        if self.failure is None:
            self.failure = reason

    def verify(self):
        self.inputs.verify()
        _require(_owner(os.getpid()) == self.controller, "original engine controller identity changed")
        for fd, path, epoch, descriptor, socket in self.engines:
            _require(_epoch(os.fstat(fd)) == epoch == _epoch(_path(path).lstat()), "original held engine identity changed")
            _require(_hash_fd(fd, MAX_ENGINE_BYTES) == (descriptor["size_bytes"], descriptor["sha256"]), "original held engine bytes changed")
            _socket(socket)

    def finish(self, body_error):
        self.verify()
        measured = [row for row in self.calls if row["phase"] == "measurement"]
        if body_error is not None:
            self.fail("original_wrapper_failed")
        if len(measured) != 1:
            self.fail("exactly_one_measurement_call_required")
        if any(row["terminal"] is None for row in self.calls):
            self.fail("original_engine_terminal_missing")
        if self.native_transfer is None:
            self.fail("original_native_transfer_missing")
        value = {"schema_version": 1, "artifact_kind": "vast_original_engine_process_capture_v1",
            "operation_id": self.operation_id, "original_operation": self.original, "native_context": self.context,
            "container_image": self.image, "controller": self.controller, "started_at_ns": self.started,
            "finished_at_ns": time.time_ns(), "status": "complete_original_cli_capture" if self.failure is None else "failed_original_cli_capture",
            "failure": self.failure, "body_error": None if body_error is None else {
                "type": type(body_error).__name__, "message_sha256": hashlib.sha256(str(body_error).encode()).hexdigest()},
            "call_count": len(self.calls), "measurement_count": len(measured), "calls": self.calls,
            "native_transfer": self.native_transfer, "container_quiescence_verified": False, "accepted": False, "publication_ready": False}
        self.receipt_descriptor = _write(self.custody, self.output_dir / "original_engine_process_capture.v1.json", value, MAX_RECEIPT_BYTES)
        self.inputs.read(self.receipt_descriptor, MAX_RECEIPT_BYTES)
        self.verify()
        _require(self.failure is None, "original engine capture failed: " + str(self.failure))

    def close(self):
        for row in self.engines:
            os.close(row[0])


def current_original_engine_capture_v1():
    """Return the actual active capture, or None; daemon custody is separate."""
    return _capture.get()


@contextmanager
def capture_original_engine_processes_v1(*, project_root, output_dir, operation_id,
        original_operation_descriptor, native_context_descriptor, container_image):
    if _capture.get() is not None:
        _capture.get().fail("original_engine_context_overlap")
        raise ValueError("original engine captures cannot overlap in one context")
    with _held(project_root) as (custody, inputs):
        capture = _Capture(custody, inputs, output_dir, operation_id, original_operation_descriptor, native_context_descriptor, container_image)
        token, error = _capture.set(capture), None
        try:
            try:
                yield capture
            except BaseException as original:
                error = original
                raise
            finally:
                try:
                    capture.finish(error)
                except BaseException as finish_error:
                    if error is None:
                        raise
                    error.add_note("Original process capture finalization failed: " + str(finish_error))
        finally:
            _capture.reset(token)
            capture.close()


@contextmanager
def original_engine_phase_v1(phase):
    if _capture.get() is not None:
        if type(phase) is not str or phase not in PHASES:
            _capture.get().fail("original_engine_phase_invalid")
            raise ValueError("original engine phase must be explicit")
    token = _phase.set(phase)
    try:
        yield
    finally:
        _phase.reset(token)


def engine_process_started_v1(process, engine_pin, engine_socket_pin, argv):
    capture = _capture.get()
    if capture is None:
        return None
    with capture.lock:
        fd = -1
        try:
            _require(capture.failure is None, "original engine capture already failed")
            capture.verify()
            phase = _phase.get()
            _require(phase in PHASES and len(capture.calls) < MAX_CALLS, "original engine phase missing or call capacity exhausted")
            _require(type(process) is subprocess.Popen, "only a genuine original Popen child can be observed")
            path = _path(engine_pin.path)
            fd = os.dup(engine_pin.fd)
            info = os.fstat(fd)
            _require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and _epoch(info) == _epoch(path.lstat()), "held original engine is not exact regular bytes")
            size, digest = _hash_fd(fd, MAX_ENGINE_BYTES)
            _require(size == engine_pin.size and digest == engine_pin.sha256, "original engine source pin drifted")
            socket = _socket(engine_socket_pin)
            _require(type(argv) in {list, tuple} and bool(argv) and all(type(arg) is str and "\x00" not in arg for arg in argv), "original engine argv invalid")
            arguments = [engine_pin.proc_path, *argv]
            _require(list(process.args) == arguments and engine_pin.proc_path == f"/proc/self/fd/{engine_pin.fd}", "original child argv/held executable drifted")
            child = _owner(process.pid)
            _require(child["ppid"] == capture.controller["pid"] and child["boot_id"] == capture.controller["boot_id"]
                and child["uid"] == capture.controller["uid"] and child["gid"] == capture.controller["gid"], "original child ownership differs from controller")
            try:
                executable = os.stat(f"/proc/{process.pid}/exe")
            except FileNotFoundError:
                reread, state = _owner_with_state(process.pid)
                _require(reread == child and state == "Z", "missing original child executable is not an observed zombie")
                executable_observation = "exited_before_executable_observation"
            else:
                _require((executable.st_dev, executable.st_ino) == (info.st_dev, info.st_ino), "observed original child is not held engine executable")
                executable_observation = "matched_original_engine"
            engine = {"path": str(path), "size_bytes": size, "sha256": digest, "device": info.st_dev, "inode": info.st_ino,
                "mode": info.st_mode, "owner_uid": info.st_uid, "owner_gid": info.st_gid, "fd": engine_pin.fd, "proc_path": engine_pin.proc_path}
            seq = len(capture.calls) + 1
            launch = {"schema_version": 1, "artifact_kind": "vast_original_engine_process_launch_v1", "operation_id": capture.operation_id,
                "phase": phase, "call_seq": seq, "controller": capture.controller, "child": child, "engine": engine,
                "engine_socket": socket, "container_image": capture.image, "argv": arguments,
                "argv_sha256": hashlib.sha256(canonical_json_v1(arguments)).hexdigest(), "started_at_ns": time.time_ns(),
                "executable_observation": executable_observation, "measurement_binding": validate_original_measurement_argv_v1(
                    argv=arguments, original_input=capture.original_input, native_context_descriptor=capture.context) if phase == "measurement" else None}
            descriptor = _write(capture.custody, capture.output_dir / f"engine_{seq:02d}.launch.v1.json", launch, MAX_LAUNCH_BYTES)
            capture.inputs.read(descriptor, MAX_LAUNCH_BYTES)
            row = {"call_seq": seq, "phase": phase, "launch": descriptor, "terminal": None}
            capture.calls.append(row)
            capture.engines.append((fd, path, _epoch(info), engine, socket))
            fd = -1
            return (capture, row, process)
        except BaseException:
            capture.fail("original_engine_start_observation_failed")
            raise
        finally:
            if fd >= 0:
                os.close(fd)


def engine_process_terminal_v1(token, process, stdout, stderr, timed_out, capture_exceeded, capture_drain_failed):
    if token is None:
        return
    capture, row, original_process = token
    with capture.lock:
        try:
            _require(_capture.get() is capture and process is original_process and row["terminal"] is None,
                     "original engine terminal context/child/multiplicity drifted")
            capture.verify()
            _require(type(process.returncode) is int and process.poll() is not None, "original child has no actual terminal returncode")
            _require(type(stdout) is bytes and type(stderr) is bytes and len(stdout) <= MAX_CAPTURE_BYTES and len(stderr) <= MAX_CAPTURE_BYTES,
                     "original child captures exceed source bounds")
            _require(all(type(flag) is bool for flag in (timed_out, capture_exceeded, capture_drain_failed)), "original terminal flags invalid")
            terminal = {"schema_version": 1, "artifact_kind": "vast_original_engine_process_terminal_v1", "operation_id": capture.operation_id,
                "call_seq": row["call_seq"], "launch_descriptor": row["launch"], "returncode": process.returncode,
                "stdout": {"size_bytes": len(stdout), "sha256": hashlib.sha256(stdout).hexdigest()},
                "stderr": {"size_bytes": len(stderr), "sha256": hashlib.sha256(stderr).hexdigest()},
                "timed_out": timed_out, "capture_exceeded": capture_exceeded, "capture_drain_failed": capture_drain_failed,
                "terminal_at_ns": time.time_ns()}
            descriptor = _write(capture.custody, capture.output_dir / f"engine_{row['call_seq']:02d}.terminal.v1.json", terminal, MAX_TERMINAL_BYTES)
            capture.inputs.read(descriptor, MAX_TERMINAL_BYTES)
            row["terminal"] = descriptor
            if process.returncode != 0 or timed_out or capture_exceeded or capture_drain_failed:
                capture.fail("original_engine_terminal_failed")
        except BaseException:
            capture.fail("original_engine_terminal_observation_failed")
            raise


def _read_record(inputs, descriptor, fields, kind, maximum):
    raw = inputs.read(descriptor, maximum)
    value = strict_json_object_v1(raw, max_bytes=maximum)
    _require(set(value) == fields and canonical_json_v1(value) + b"\n" == raw and type(value["schema_version"]) is int
        and value["schema_version"] == 1 and value["artifact_kind"] == kind
        and payload_with_sha256_v1(value)["sha256"] == value["sha256"], "original process record schema/semantic seal drifted")
    return value


def original_process_validator_v1(*, project_root, receipt_path, expected_descriptor=None, operation_id,
        original_operation_descriptor, native_context_descriptor, expected_container_image):
    """Cold original CLI evidence only; daemon quiescence must be checked separately."""
    with _held(project_root) as (custody, inputs):
        receipt_path = _path(receipt_path)
        if expected_descriptor is None:
            expected_descriptor, _ = custody.read_descriptor(receipt_path, label="original process receipt", maximum=MAX_RECEIPT_BYTES)
            expected_descriptor["path"] = str(receipt_path)
        _require(expected_descriptor["path"] == str(receipt_path), "original process receipt descriptor path differs")
        receipt = _read_record(inputs, expected_descriptor, RECEIPT_FIELDS, "vast_original_engine_process_capture_v1", MAX_RECEIPT_BYTES)
        _require(receipt["operation_id"] == operation_id and receipt["original_operation"] == original_operation_descriptor
            and receipt["native_context"] == native_context_descriptor and receipt["container_image"] == _image(expected_container_image),
            "original process receipt differs from expected original authority")
        original = _original_input(inputs.read(original_operation_descriptor))
        _require(original["container_image"] == expected_container_image, "physical original operation image differs from expected image")
        _require(original["outputs"]["process_receipt"] == str(receipt_path), "original process receipt differs from reserved output")
        inputs.read(native_context_descriptor)
        _require(receipt["status"] == "complete_original_cli_capture" and receipt["failure"] is None and receipt["body_error"] is None
            and receipt["container_quiescence_verified"] is False and receipt["accepted"] is False and receipt["publication_ready"] is False,
            "original process receipt is failed or claims unobserved authority")
        calls = receipt["calls"]
        _require(type(calls) is list and 1 <= len(calls) <= MAX_CALLS and type(receipt["call_count"]) is int
            and receipt["call_count"] == len(calls), "original process receipt call count invalid")
        _validate_owner(receipt["controller"])
        _require(type(receipt["started_at_ns"]) is int and type(receipt["finished_at_ns"]) is int
            and 0 < receipt["started_at_ns"] <= receipt["finished_at_ns"] <= (1 << 64) - 1, "original capture clock invalid")
        results, measured, identities, engine_inputs = [], [], set(), {}
        for seq, row in enumerate(calls, 1):
            _require(type(row) is dict and set(row) == {"call_seq", "phase", "launch", "terminal"} and row["call_seq"] == seq
                and type(row["call_seq"]) is int and type(row["phase"]) is str and row["phase"] in PHASES
                and row["terminal"] is not None, "original process call sequence/phase/terminal invalid")
            launch = _read_record(inputs, row["launch"], LAUNCH_FIELDS, "vast_original_engine_process_launch_v1", MAX_LAUNCH_BYTES)
            terminal = _read_record(inputs, row["terminal"], TERMINAL_FIELDS, "vast_original_engine_process_terminal_v1", MAX_TERMINAL_BYTES)
            _require(launch["operation_id"] == terminal["operation_id"] == operation_id and launch["call_seq"] == terminal["call_seq"] == seq
                and type(launch["call_seq"]) is type(terminal["call_seq"]) is int
                and launch["phase"] == row["phase"] and launch["controller"] == receipt["controller"]
                and launch["container_image"] == expected_container_image and terminal["launch_descriptor"] == row["launch"],
                "original launch/terminal authority join drifted")
            _require(type(launch["executable_observation"]) is str and launch["executable_observation"] in {"matched_original_engine", "exited_before_executable_observation"},
                     "original executable observation must preserve its actual limitation")
            child = launch["child"]
            _validate_owner(child)
            _require(child["ppid"] == receipt["controller"]["pid"]
                and all(child[key] == receipt["controller"][key] for key in ("uid", "gid", "boot_id")), "original child owner join drifted")
            identity = (child["boot_id"], child["pid"], child["proc_stat_starttime_ticks"])
            _require(identity not in identities, "original child process identity repeated")
            identities.add(identity)
            engine = launch["engine"]
            _require(type(engine) is dict and set(engine) == ENGINE_FIELDS and engine["proc_path"] == f"/proc/self/fd/{engine['fd']}",
                     "original engine descriptor invalid")
            _require(type(engine["fd"]) is int and 0 <= engine["fd"] < 2**31
                and type(engine["size_bytes"]) is int and 0 < engine["size_bytes"] <= MAX_ENGINE_BYTES
                and all(type(engine[key]) is int and engine[key] >= 0 for key in ("device", "inode", "mode", "owner_uid", "owner_gid"))
                and type(engine["sha256"]) is str and re.fullmatch(r"[0-9a-f]{64}", engine["sha256"]), "original engine bounds invalid")
            path = _path(engine["path"])
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            try:
                info = os.fstat(fd)
                _require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid) ==
                    (engine["device"], engine["inode"], engine["mode"], engine["owner_uid"], engine["owner_gid"])
                    and _hash_fd(fd, MAX_ENGINE_BYTES) == (engine["size_bytes"], engine["sha256"]), "original engine source custody drifted")
                engine_inputs[str(path)] = {"descriptor": {"path": str(path), "size_bytes": engine["size_bytes"], "sha256": engine["sha256"]},
                                           "epoch": list(_epoch(info))}
            finally:
                os.close(fd)
            _socket(launch["engine_socket"])
            argv = launch["argv"]
            _require(type(argv) is list and len(argv) >= 2 and argv[0] == engine["proc_path"] and all(type(arg) is str and "\x00" not in arg for arg in argv)
                and hashlib.sha256(canonical_json_v1(argv)).hexdigest() == launch["argv_sha256"], "original argv seal drifted")
            _require(type(terminal["returncode"]) is int and terminal["returncode"] == 0 and all(terminal[key] is False for key in
                ("timed_out", "capture_exceeded", "capture_drain_failed")), "original CLI failed or capture was incomplete")
            for name in ("stdout", "stderr"):
                capture = terminal[name]
                _require(type(capture) is dict and set(capture) == {"size_bytes", "sha256"} and type(capture["size_bytes"]) is int
                    and 0 <= capture["size_bytes"] <= MAX_CAPTURE_BYTES and type(capture["sha256"]) is str
                    and re.fullmatch(r"[0-9a-f]{64}", capture["sha256"]), "original CLI output digest invalid")
            _require(type(launch["started_at_ns"]) is int and type(terminal["terminal_at_ns"]) is int
                and receipt["started_at_ns"] <= launch["started_at_ns"] <= terminal["terminal_at_ns"] <= receipt["finished_at_ns"],
                "original CLI time ordering drifted")
            result = {"launch": launch, "terminal": terminal}
            results.append(result)
            if row["phase"] == "measurement":
                _require(type(launch["measurement_binding"]) is dict, "original measurement binding missing")
                validate_original_measurement_argv_v1(argv=launch["argv"], original_input=original,
                    native_context_descriptor=native_context_descriptor, observed_binding=launch["measurement_binding"])
                measured.append(result)
            else:
                _require(launch["measurement_binding"] is None, "probe cannot carry measurement binding")
        _require(type(receipt["measurement_count"]) is int and receipt["measurement_count"] == len(measured) == 1,
                 "original CLI capture must contain exactly one successful measurement")
        inputs.verify()
        transfers = validate_original_native_transfer_chain_v1(custody=custody, inputs=inputs, first_transfer=receipt["native_transfer"],
            measurement_binding=measured[0]["launch"]["measurement_binding"], final_domain=original["outputs"]["native_domain"])
        inputs.verify()
        validated_inputs = [{"descriptor": copy.deepcopy(row[0]), "epoch": list(row[3])} for row in inputs.rows.values()]
        validated_inputs.extend(engine_inputs.values())
        return {"receipt": receipt, "calls": results, "measurement": measured[0], "native_transfers": transfers,
                "validated_inputs": validated_inputs, "descriptor": copy.deepcopy(expected_descriptor)}
