"""Fixed Windows P0 capture for gate 2.

Three literal wsl.exe invocations prove an agent-observed root snapshot.
The ordinary C/D runner stays UID/GID 1000. Injected effects are controlled
seams and never launch a process or grant physical acceptance. The native
entry records an agent-observed classification and also does not grant
physical acceptance. Terminating the owned wsl.exe handle does not prove
that the Linux child closed.
"""
from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import math
import os
from pathlib import Path
import stat
import time


KNOWN_ENGINE_ID = "1e493309-3767-45fb-9078-05b838bdfd80"
CHAIN_ID = "sha256:583abc9004877e79fd0f5d47e4c7cff085b8538fdcbff0c070e044bdb0b43c1a"
WSL_EXE = "C:/Windows/System32/wsl.exe"
COMMAND_ORDER = ("id", "snapshot_info", "snapshot_ls")
ABSOLUTE_DEADLINE_S = 30.0
PER_COMMAND_DEADLINE_S = 10.0
PERSISTENCE_RESERVE_S = 1.0
OWNED_PARENT_TERMINATION_RESERVE_S = 1.0
CLOSURE_OBSERVATION_RESERVE_S = 0.5
STDOUT_CAPS = {"id": 16, "snapshot_info": 64 * 1024, "snapshot_ls": 256 * 1024}
STDERR_COMBINED_CAP = 16 * 1024
CONTROL_RECORD_CAP = 8 * 1024
COMPLETION_RECORD_CAP = 4 * 1024
METADATA_COMBINED_CAP = 12 * 1024
METADATA_COPY_CAP = 12 * 1024
BINDING_PREENCODING_CAP = 4096
P0_FORMS_CEILING = 384 * 1024
CODE_P0_ALLOCATION = 1024 * 1024
ALLOCATION_QUANTUM = 4096
DIRECTORY_RESERVE = 4096
INODE_BYTES = 256
READ_CHUNK = 4096
ORDINARY_CD_UID_GID = (1000, 1000)
STREAM_FILES = {
    "id": ("p0-id.stdout.original", "p0-id.stderr.original"),
    "snapshot_info": ("p0-snapshot-info.stdout.original", "p0-snapshot-info.stderr.original"),
    "snapshot_ls": ("p0-snapshot-ls.stdout.original", "p0-snapshot-ls.stderr.original"),
}
CONTROL_NAME = "p0-control.v1.json"
COMPLETION_NAME = "p0-completion.v1.json"


class P0SeamError(RuntimeError):
    """Raised when an effects object is not a controlled non-accepting seam."""


class P0OriginalsRefusal(ValueError):
    """A fixed P0 original or its bound observation failed validation."""

    def __init__(self, cause):
        super().__init__(cause)
        self.cause = cause


def fixed_environment():
    return {
        "SystemRoot": "C:/Windows",
        "WINDIR": "C:/Windows",
        "PATH": "C:/Windows/System32;C:/Windows",
    }


def fixed_argv(name):
    prefix = [WSL_EXE, "-d", "Ubuntu", "-u", "root", "--cd", "/", "--exec"]
    tails = {
        "id": ["/usr/bin/id", "-u"],
        "snapshot_info": [
            "/usr/bin/ctr", "-n", "moby", "snapshots", "--snapshotter", "overlayfs",
            "info", CHAIN_ID,
        ],
        "snapshot_ls": [
            "/usr/bin/ctr", "-n", "moby", "snapshots", "--snapshotter", "overlayfs", "ls",
        ],
    }
    if name not in tails:
        raise KeyError(name)
    return prefix + list(tails[name])


def command_phase_deadlines(cmd_start, global_deadline):
    cmd_deadline = min(cmd_start + PER_COMMAND_DEADLINE_S, global_deadline)
    termination_deadline = cmd_deadline - PERSISTENCE_RESERVE_S
    capture_deadline = (
        termination_deadline
        - OWNED_PARENT_TERMINATION_RESERVE_S
        - CLOSURE_OBSERVATION_RESERVE_S
    )
    return {
        "cmd_start": cmd_start,
        "cmd_deadline": cmd_deadline,
        "termination_deadline": termination_deadline,
        "capture_deadline": capture_deadline,
        "global_deadline": global_deadline,
        "persistence_deadline": cmd_deadline,
    }


def round_up_allocation(logical_bytes):
    if logical_bytes < 0:
        raise ValueError("negative allocation")
    if logical_bytes == 0:
        return ALLOCATION_QUANTUM
    quantum = ALLOCATION_QUANTUM
    return ((logical_bytes + quantum - 1) // quantum) * quantum


def _worst_rounded_files(total_bytes, file_count):
    quantum = ALLOCATION_QUANTUM
    max_blocks = total_bytes // quantum + 1

    def minimum_bytes(blocks):
        if blocks <= 1:
            return 0
        return (blocks - 1) * quantum + 1

    counts = [1] * file_count
    best = 0
    while True:
        if sum(minimum_bytes(blocks) for blocks in counts) <= total_bytes:
            best = max(best, sum(counts) * quantum)
        index = 0
        while index < file_count:
            counts[index] += 1
            if counts[index] <= max_blocks:
                break
            counts[index] = 1
            index += 1
        else:
            break
    return best


def maximum_inclusive_charge():
    stdout = sum(round_up_allocation(STDOUT_CAPS[name]) for name in COMMAND_ORDER)
    stderr = _worst_rounded_files(STDERR_COMBINED_CAP, len(COMMAND_ORDER))
    metadata = round_up_allocation(CONTROL_RECORD_CAP) + round_up_allocation(COMPLETION_RECORD_CAP)
    copy = round_up_allocation(METADATA_COPY_CAP)
    inodes = 9 * INODE_BYTES
    return DIRECTORY_RESERVE + stdout + stderr + metadata + copy + inodes


def canonical_json(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False,
    ).encode("utf-8")


def _strict_json_decoder():
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    def refuse_constant(value):
        raise ValueError("nonfinite JSON")

    def finite_float(value):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("nonfinite JSON")
        return number

    return json.JSONDecoder(object_pairs_hook=unique, parse_constant=refuse_constant, parse_float=finite_float)


def preencoding_exceeds(record):
    return len(canonical_json(record)) > CONTROL_RECORD_CAP


def _add(causes, item):
    if item not in causes:
        causes.append(item)


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def _binding_estimate(value, limit, depth=0):
    if depth > 8:
        return limit + 1
    if value is None or isinstance(value, bool):
        return 4
    if isinstance(value, int):
        return len(str(value))
    if isinstance(value, str):
        return len(value) * 6 + 2
    if isinstance(value, dict):
        total = 2
        for key, item in value.items():
            if not isinstance(key, str):
                return limit + 1
            total += _binding_estimate(key, limit, depth + 1)
            total += _binding_estimate(item, limit, depth + 1) + 1
            if total > limit:
                return total
        return total
    if isinstance(value, (list, tuple)):
        total = 2
        for item in value:
            total += _binding_estimate(item, limit, depth + 1) + 1
            if total > limit:
                return total
        return total
    return limit + 1


def _valid_commit(value):
    if not isinstance(value, str) or len(value) != 40:
        return False
    return all(char in "0123456789abcdef" for char in value)


def is_windows_absolute(path):
    if not isinstance(path, str) or len(path) < 3:
        return False
    if path[0].isalpha() and path[1] == ":" and path[2] in "/\\":
        return True
    if path.startswith("\\\\"):
        rest = path[2:]
        return "\\" in rest and not rest.startswith("\\")
    if path.startswith("//"):
        rest = path[2:]
        return "/" in rest and not rest.startswith("/")
    return False


def join_output(directory, name):
    if "/" in name or "\\" in name or name in ("", ".", ".."):
        raise ValueError(name)
    if directory.endswith(("/", "\\")):
        return directory + name
    if directory.startswith("\\\\") and "/" not in directory:
        return directory + "\\" + name
    return directory + "/" + name


def validate_sealed_binding(binding):
    causes = []
    bound_engine_id = None
    boot_id = None
    observer = None
    if not isinstance(binding, dict):
        return {
            "ok": False,
            "causes": ["binding_not_mapping"],
            "bound_engine_id": None,
            "boot_id": None,
            "provenance_observer": None,
            "engine_observed_by_collector": False,
        }
    if _binding_estimate(binding, BINDING_PREENCODING_CAP) > BINDING_PREENCODING_CAP:
        _add(causes, "binding_preencoding_exceeds_control_budget")
    known = binding.get("known_engine_id", None)
    if known != KNOWN_ENGINE_ID:
        _add(causes, "known_engine_mismatch")
    boot = binding.get("boot")
    if isinstance(boot, dict):
        boot_id = boot.get("boot_id")
    if not isinstance(boot_id, str) or boot_id == "" or len(boot_id) > 128:
        _add(causes, "boot_descriptor_missing")
        boot_id = None
    provenance = binding.get("provenance")
    if not isinstance(provenance, dict):
        _add(causes, "engine_not_externally_bound")
    else:
        if provenance.get("source") != "external":
            _add(causes, "engine_not_externally_bound")
        observer = provenance.get("observer")
        if observer not in ("ordinary_api", "c_guard"):
            _add(causes, "engine_not_externally_bound")
        if "engine_id" not in provenance:
            _add(causes, "engine_provenance_missing")
            bound_engine_id = None
        else:
            bound_engine_id = provenance.get("engine_id")
            if bound_engine_id != KNOWN_ENGINE_ID or bound_engine_id != known:
                _add(causes, "engine_provenance_mismatch")
        if boot_id is not None and provenance.get("boot_id") != boot_id:
            _add(causes, "boot_provenance_mismatch")
    return {
        "ok": not causes,
        "causes": causes,
        "bound_engine_id": bound_engine_id,
        "boot_id": boot_id,
        "provenance_observer": observer if isinstance(observer, str) else None,
        "engine_observed_by_collector": False,
    }


def validate_id_stdout(data):
    causes = []
    if data != b"0\n":
        _add(causes, "id_stdout_not_exact_zero_newline")
        token = data.split(b"\n", 1)[0].strip()
        if token != b"0":
            _add(causes, "id_uid_not_zero")
    return {"ok": not causes, "causes": causes, "uid": 0 if not causes else None}


def validate_snapshot_info(data):
    causes = []
    name = None
    kind = None
    try:
        text = data.decode("utf-8")
        value, end = _strict_json_decoder().raw_decode(text)
        if text[end:].strip():
            _add(causes, "snapshot_info_json_trailing")
    except (UnicodeError, ValueError, RecursionError):
        return {
            "ok": False,
            "causes": ["snapshot_info_json_invalid"],
            "name": None,
            "kind": None,
        }
    if not isinstance(value, dict):
        return {
            "ok": False,
            "causes": ["snapshot_info_json_invalid"],
            "name": None,
            "kind": None,
        }
    if isinstance(value.get("Name"), str):
        name = value["Name"]
    if isinstance(value.get("Kind"), str):
        kind = value["Kind"]
    if name != CHAIN_ID:
        _add(causes, "snapshot_info_name_mismatch")
    if kind != "Committed":
        _add(causes, "snapshot_info_kind_not_committed")
    return {"ok": not causes, "causes": causes, "name": name, "kind": kind}


def _listing_rows(data):
    try:
        text = data.decode("utf-8")
    except UnicodeError:
        return None
    rows = []
    for index, line in enumerate(text.splitlines()):
        if line == "":
            continue
        if index == 0 and line.startswith("KEY") and "KIND" in line:
            continue
        parts = line.split()
        if len(parts) == 2:
            rows.append({"key": parts[0], "parent": "", "kind": parts[1], "malformed": False})
        elif len(parts) == 3:
            rows.append({
                "key": parts[0], "parent": parts[1], "kind": parts[2], "malformed": False,
            })
        else:
            rows.append({"key": None, "parent": "", "kind": None, "malformed": True})
    return rows


def validate_snapshot_ls(data):
    causes = []
    rows = _listing_rows(data)
    if rows is None:
        return {"ok": False, "causes": ["snapshot_ls_malformed_row"], "matches": 0}
    if any(row["malformed"] for row in rows):
        _add(causes, "snapshot_ls_malformed_row")
    matches = [row for row in rows if row["key"] == CHAIN_ID]
    if len(matches) != 1:
        _add(causes, "snapshot_ls_chain_row_not_exactly_one")
    elif matches[0]["kind"] != "Committed":
        _add(causes, "snapshot_ls_kind_not_committed")
    return {"ok": not causes, "causes": causes, "matches": len(matches)}


def _originals_require(condition, cause):
    if not condition:
        raise P0OriginalsRefusal(cause)


def _originals_shape(value, fields, cause):
    _originals_require(type(value) is dict and len(value) == len(fields) and set(value) == set(fields), cause)


def _originals_number(value):
    try:
        return type(value) in (int, float) and math.isfinite(value) and value >= 0
    except OverflowError:
        return False


def _originals_signature(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns, getattr(info, "st_blocks", None))


def _originals_allocation(info, minimum):
    blocks = getattr(info, "st_blocks", None)
    _originals_require(type(blocks) is int and blocks >= 0, "p0_original_blocks_unknown")
    return max(minimum, blocks * 512)


def _originals_inventory(directory, root):
    _originals_require(directory.is_absolute() and directory.is_relative_to(root)
                       and directory.resolve(strict=True) == directory, "p0_original_directory")
    info = directory.lstat()
    _originals_require(stat.S_ISDIR(info.st_mode), "p0_original_directory")
    allocation = _originals_allocation(info, DIRECTORY_RESERVE)
    expected = {name for pair in STREAM_FILES.values() for name in pair} | {CONTROL_NAME, COMPLETION_NAME}
    found = set()
    # A ninth entry already refutes the fixed eight-file inventory. Never
    # enumerate an arbitrary directory to construct an unbounded list.
    with os.scandir(directory) as rows:
        for _ in range(9):
            entry = next(rows, None)
            if entry is None:
                break
            _originals_require(len(found) < 8 and entry.name in expected and entry.name not in found,
                               "p0_original_inventory")
            entry_info = entry.stat(follow_symlinks=False)
            _originals_require(stat.S_ISREG(entry_info.st_mode) and entry_info.st_nlink == 1,
                               "p0_original_inventory")
            found.add(entry.name)
    _originals_require(found == expected and _originals_signature(directory.lstat()) == _originals_signature(info),
                       "p0_original_inventory")
    return _originals_signature(info), allocation


def _read_original(path, cap, root, observed):
    _originals_require(path.is_absolute() and path.is_relative_to(root)
                       and path.resolve(strict=True) == path, "p0_original_path")
    before = path.lstat()
    _originals_require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
                       and 0 <= before.st_size <= cap, "p0_original_bound")
    identity = (before.st_dev, before.st_ino)
    _originals_require(identity not in observed, "p0_original_alias")
    signature = _originals_signature(before)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0)
    with os.fdopen(os.open(path, flags), "rb") as file:
        _originals_require(_originals_signature(os.fstat(file.fileno())) == signature, "p0_original_drift")
        raw = file.read(cap + 1)
        _originals_require(len(raw) == before.st_size
                           and _originals_signature(os.fstat(file.fileno())) == signature, "p0_original_drift")
    _originals_require(path.resolve(strict=True) == path and _originals_signature(path.lstat()) == signature,
                       "p0_original_drift")
    observed[identity] = (path, signature,
                          _originals_allocation(before, round_up_allocation(len(raw))) + INODE_BYTES)
    return raw


def _originals_json(raw, cap):
    _originals_require(type(raw) is bytes and 0 < len(raw) <= cap, "p0_json_bound")
    try:
        value, end = _strict_json_decoder().raw_decode(raw.decode("ascii"))
        _originals_require(end == len(raw) and canonical_json(value) == raw, "p0_json_canonical")
        return value
    except (UnicodeError, ValueError, RecursionError, TypeError) as error:
        raise P0OriginalsRefusal("p0_json_invalid") from error


def _originals_proof(value, raw):
    expected = {"open_completed": True, "written_bytes": len(raw), "fsync_completed": True,
                "close_completed": True, "late": False, "extent_unknown": False,
                "completed": True, "prefix_sha256": _sha256(raw)}
    _originals_shape(value, expected, "p0_write_proof")
    _originals_require(all(type(value[key]) is type(item) and value[key] == item
                           for key, item in expected.items()), "p0_write_proof")


def _originals_classification(value, commit, engine, boot):
    expected = {"controlled": False, "physical_acceptance": False, "human_review": False,
                "engine_observed_by_collector": False, "reviewed_code_commit": commit,
                "bound_engine_id": engine, "boot_id": boot, "predicates_satisfied": True, "causes": []}
    _originals_require(all(key in value and type(value[key]) is type(item) and value[key] == item
                           for key, item in expected.items()), "p0_original_classification")


def _originals_command(value, name, directory, root, observed, stderr_remaining, global_deadline, previous_finish):
    _originals_shape(value, (
        "name", "argv", "env", "pid", "returncode", "normal_exit", "forced_parent_termination",
        "parent_termination_proves_linux_child_closure", "linux_child_closure", "eof_stdout", "eof_stderr",
        "late", "timed_out", "causes", "stdout", "stderr", "deadline", "timestamps",
    ), "p0_command_shape")
    expected = {"name": name, "argv": fixed_argv(name), "env": fixed_environment(), "returncode": 0,
                "normal_exit": True, "forced_parent_termination": False,
                "parent_termination_proves_linux_child_closure": False,
                "linux_child_closure": "normal_wsl_exit_and_eof", "eof_stdout": True, "eof_stderr": True,
                "late": False, "timed_out": False, "causes": []}
    _originals_require(all(type(value[key]) is type(item) and value[key] == item
                           for key, item in expected.items()), "p0_command_predicate")
    _originals_require(type(value["pid"]) is int and 0 < value["pid"] < 2 ** 32, "p0_command_pid")
    phases = value["deadline"]
    _originals_shape(phases, command_phase_deadlines(0, 0), "p0_command_deadline")
    _originals_require(all(_originals_number(item) for item in phases.values()), "p0_command_deadline")
    started = phases["cmd_start"]
    _originals_require(previous_finish <= started < global_deadline
                       and phases == command_phase_deadlines(started, global_deadline), "p0_command_deadline")
    timestamps = value["timestamps"]
    _originals_shape(timestamps, ("spawn_returned", "drain_finished", "persist_finished"), "p0_command_timing")
    _originals_require(all(_originals_number(item) for item in timestamps.values()), "p0_command_timing")
    _originals_require(started <= timestamps["spawn_returned"] <= timestamps["drain_finished"]
                       <= timestamps["persist_finished"] <= phases["cmd_deadline"], "p0_command_timing")
    bodies, charged = {}, 0
    for index, key in enumerate(("stdout", "stderr")):
        stream = value[key]
        _originals_shape(stream, ("cap_bytes", "retained_bytes", "observed_bytes", "eof", "overflow",
            "remainder_unknown", "prefix_sha256", "relative_path", "persistence"), "p0_stream_shape")
        cap = STDOUT_CAPS[name] if key == "stdout" else stderr_remaining
        filename = STREAM_FILES[name][index]
        _originals_require(type(stream["cap_bytes"]) is int and stream["cap_bytes"] == cap
                           and stream["relative_path"] == filename, "p0_stream_contract")
        raw = _read_original(directory / filename, cap, root, observed)
        for field in ("retained_bytes", "observed_bytes"):
            _originals_require(type(stream[field]) is int and stream[field] == len(raw), "p0_stream_extent")
        _originals_require(stream["eof"] is True and stream["overflow"] is False
                           and stream["remainder_unknown"] is False and stream["prefix_sha256"] == _sha256(raw),
                           "p0_stream_capture")
        _originals_proof(stream["persistence"], raw)
        bodies[key] = raw
        charged += round_up_allocation(len(raw)) + INODE_BYTES
    checker = {"id": validate_id_stdout, "snapshot_info": validate_snapshot_info, "snapshot_ls": validate_snapshot_ls}[name]
    _originals_require(checker(bodies["stdout"])["ok"] is True, "p0_stdout_semantics")
    return stderr_remaining - len(bodies["stderr"]), timestamps["persist_finished"], charged


def validate_p0_originals_v1(descriptor, *, project_root, expected_code_commit, expected_engine_id, expected_boot_id):
    """Reread a fixed completion, control and six original streams; never launch.

    The externally reviewed packet binds the completion descriptor and the
    actual native invocation's returned status and completion write proof.
    This file validator verifies the control's already completed write proof;
    it cannot infer the completion's historical fsync/close from file existence,
    authenticate a producer by its own strings, or grant physical acceptance.
    No self-persistence claim or extra full-result original is introduced.
    """
    try:
        return _validate_p0_originals(descriptor, project_root, expected_code_commit,
                                      expected_engine_id, expected_boot_id)
    except P0OriginalsRefusal:
        raise
    except (OSError, ValueError, TypeError, RecursionError) as error:
        raise P0OriginalsRefusal("p0_original_io_or_shape") from error


def _validate_p0_originals(descriptor, project_root, commit, engine, boot):
    _originals_require(_valid_commit(commit) and engine == KNOWN_ENGINE_ID
                       and type(boot) is str and 0 < len(boot) <= 128, "p0_expected_identity")
    root = Path(project_root)
    _originals_require(root.is_absolute() and root.resolve(strict=True) == root and root.is_dir(), "p0_project_root")
    _originals_shape(descriptor, ("path", "size_bytes", "sha256"), "p0_descriptor")
    _originals_require(type(descriptor["path"]) is str and 0 < len(descriptor["path"]) <= 4096
                       and type(descriptor["size_bytes"]) is int and 0 < descriptor["size_bytes"] <= COMPLETION_RECORD_CAP
                       and type(descriptor["sha256"]) is str and len(descriptor["sha256"]) == 64
                       and all(char in "0123456789abcdef" for char in descriptor["sha256"]), "p0_descriptor")
    path = Path(descriptor["path"])
    _originals_require(path.name == COMPLETION_NAME, "p0_completion_name")
    directory_signature, directory_allocation = _originals_inventory(path.parent, root)
    observed = {}
    raw = _read_original(path, COMPLETION_RECORD_CAP, root, observed)
    _originals_require(descriptor["size_bytes"] == len(raw) and descriptor["sha256"] == _sha256(raw), "p0_descriptor_drift")
    completion = _originals_json(raw, COMPLETION_RECORD_CAP)
    _originals_shape(completion, ("schema", "reviewed_code_commit", "controlled", "physical_acceptance", "actor",
        "human_review", "engine_observed_by_collector", "bound_engine_id", "boot_id", "control",
        "control_write_proof", "predicates_satisfied", "causes", "timing", "allocation"), "p0_completion_shape")
    _originals_classification(completion, commit, engine, boot)
    _originals_require(completion["schema"] == "gate2-p0-originals.v1"
                       and completion["actor"] == "agent_observed_root_proof", "p0_completion_classification")
    control_descriptor = completion["control"]
    _originals_shape(control_descriptor, ("relative_path", "size_bytes", "sha256"), "p0_control_descriptor")
    _originals_require(control_descriptor["relative_path"] == CONTROL_NAME
                       and type(control_descriptor["size_bytes"]) is int
                       and 0 < control_descriptor["size_bytes"] <= CONTROL_RECORD_CAP, "p0_control_descriptor")
    control_raw = _read_original(path.parent / CONTROL_NAME, CONTROL_RECORD_CAP, root, observed)
    _originals_require(len(control_raw) == control_descriptor["size_bytes"]
                       and _sha256(control_raw) == control_descriptor["sha256"]
                       and len(raw) + len(control_raw) <= METADATA_COMBINED_CAP, "p0_control_binding")
    _originals_proof(completion["control_write_proof"], control_raw)
    control = _originals_json(control_raw, CONTROL_RECORD_CAP)
    _originals_shape(control, ("schema", "physical_acceptance", "controlled", "reviewed_code_commit", "human_review",
        "engine_observed_by_collector", "comparison_engine_constant", "bound_engine_id", "boot_id", "provenance_observer",
        "changes_distro_default_uid", "ordinary_cd_uid_gid", "predicates_satisfied", "causes", "commands_attempted",
        "commands", "allocation"), "p0_control_shape")
    _originals_classification(control, commit, engine, boot)
    _originals_require(control["schema"] == "gate2-p0-control.v1" and control["comparison_engine_constant"] == engine
                       and control["provenance_observer"] in ("ordinary_api", "c_guard")
                       and control["changes_distro_default_uid"] is False
                       and type(control["ordinary_cd_uid_gid"]) is list
                       and all(type(uid) is int for uid in control["ordinary_cd_uid_gid"])
                       and control["ordinary_cd_uid_gid"] == [1000, 1000]
                       and type(control["commands_attempted"]) is int and control["commands_attempted"] == 3
                       and type(control["commands"]) is list and len(control["commands"]) == 3, "p0_control_predicate")
    expected_allocation = {"ceiling_bytes": P0_FORMS_CEILING, "quantum_bytes": ALLOCATION_QUANTUM,
                           "directory_reserve_bytes": DIRECTORY_RESERVE, "includes_control_persistence_claim": False}
    _originals_shape(control["allocation"], expected_allocation, "p0_control_allocation")
    _originals_require(all(type(control["allocation"][key]) is type(item) and control["allocation"][key] == item
                           for key, item in expected_allocation.items()), "p0_control_allocation")
    timing = completion["timing"]
    _originals_shape(timing, ("start", "deadline", "finish"), "p0_completion_timing")
    _originals_require(all(_originals_number(item) for item in timing.values()), "p0_completion_timing")
    _originals_require(timing["start"] < timing["deadline"] == timing["start"] + ABSOLUTE_DEADLINE_S
                       and timing["start"] <= timing["finish"] <= timing["deadline"], "p0_completion_timing")
    stderr_remaining, previous_finish, charge = STDERR_COMBINED_CAP, timing["start"], _fresh_reservation()["bytes"]
    for name, command in zip(COMMAND_ORDER, control["commands"]):
        stderr_remaining, previous_finish, command_charge = _originals_command(command, name, path.parent,
            root, observed, stderr_remaining, timing["deadline"], previous_finish)
        charge += command_charge
    _originals_require(previous_finish <= timing["finish"], "p0_completion_timing")
    charge += round_up_allocation(len(control_raw)) + INODE_BYTES
    allocation = completion["allocation"]
    expected_allocation = {"ceiling_bytes": P0_FORMS_CEILING, "charged_bytes": charge,
                           "within_ceiling": True, "metadata_copy_bytes": METADATA_COPY_CAP}
    _originals_shape(allocation, expected_allocation, "p0_completion_allocation")
    _originals_require(all(type(allocation[key]) is type(item) and allocation[key] == item
                           for key, item in expected_allocation.items()), "p0_completion_allocation")
    final_charge = charge + round_up_allocation(len(raw)) + INODE_BYTES
    _originals_require(final_charge <= P0_FORMS_CEILING and maximum_inclusive_charge() <= P0_FORMS_CEILING,
                       "p0_allocation_ceiling")
    physical_allocation = (directory_allocation + round_up_allocation(METADATA_COPY_CAP) + INODE_BYTES
                           + sum(allocation for _, _, allocation in observed.values()))
    _originals_require(physical_allocation <= P0_FORMS_CEILING, "p0_physical_allocation_ceiling")
    for original, signature, _ in observed.values():
        _originals_require(original.resolve(strict=True) == original
                           and _originals_signature(original.lstat()) == signature, "p0_original_drift")
    _originals_require(_originals_signature(path.parent.lstat()) == directory_signature, "p0_original_directory_drift")
    return {"schema": "gate2-p0-validation.v1", "originals_validated": True, "physical_acceptance": False,
            "completion_persistence_verified": False, "external_native_completion_proof_required": True,
            "reviewed_code_commit": commit, "bound_engine_id": engine, "boot_id": boot,
            "charged_bytes": final_charge, "physical_allocation_bytes": physical_allocation}


def _require_controlled(effects):
    if getattr(effects, "controlled", None) is not True:
        raise P0SeamError("controlled_seam_required")
    if getattr(effects, "physical_acceptance", False):
        raise P0SeamError("physical_acceptance_forbidden")
    if getattr(effects, "label", None) != "controlled":
        raise P0SeamError("controlled_label_required")
    if getattr(effects, "claims_native", False) or getattr(effects, "native", False):
        raise P0SeamError("native_spoof_forbidden")


async def _maybe(value):
    if inspect.isawaitable(value):
        return await value
    return value


def _stream_fact(cap, retained, observed, eof, overflow, remainder_unknown, relative_path, persistence):
    return {
        "cap_bytes": cap,
        "retained_bytes": len(retained),
        "observed_bytes": observed,
        "eof": eof,
        "overflow": overflow,
        "remainder_unknown": remainder_unknown,
        "prefix_sha256": _sha256(retained),
        "relative_path": relative_path,
        "persistence": persistence,
    }


def _empty_persistence():
    return {
        "open_completed": False,
        "written_bytes": 0,
        "fsync_completed": False,
        "close_completed": False,
        "late": False,
        "extent_unknown": False,
        "completed": False,
        "prefix_sha256": None,
    }


def _blank_command(name, phases):
    stdout_name, stderr_name = STREAM_FILES[name]
    return {
        "name": name,
        "argv": fixed_argv(name),
        "env": fixed_environment(),
        "pid": None,
        "returncode": None,
        "normal_exit": False,
        "forced_parent_termination": False,
        "parent_termination_proves_linux_child_closure": False,
        "linux_child_closure": "unknown",
        "eof_stdout": False,
        "eof_stderr": False,
        "late": False,
        "timed_out": False,
        "causes": [],
        "stdout": _stream_fact(
            STDOUT_CAPS[name], b"", 0, False, False, False, stdout_name, _empty_persistence(),
        ),
        "stderr": _stream_fact(
            0, b"", 0, False, False, False, stderr_name, _empty_persistence(),
        ),
        "deadline": dict(phases),
        "timestamps": {
            "spawn_returned": None,
            "drain_finished": None,
            "persist_finished": None,
        },
    }


class _Clock:
    def __init__(self, effects, started):
        self.effects = effects
        self.last = started
        self.regressed = False

    async def read(self):
        now = await _maybe(self.effects.monotonic())
        if now < self.last:
            self.regressed = True
            return now
        self.last = now
        return now


def _note_reserve(effects, rounded):
    callback = getattr(effects, "reserve_before_write", None)
    if callable(callback):
        callback(rounded)


def _fresh_reservation():
    return {
        "bytes": DIRECTORY_RESERVE + round_up_allocation(METADATA_COPY_CAP) + INODE_BYTES,
    }


class _Pull:
    def __init__(self):
        self.buf = bytearray()
        self.eof = False
        self.overflow = False
        self.remainder_unknown = False
        self.read_failed = False
        self.observed = 0


async def _pull_stream(effects, method_name, handle, state, cap, chunk_limit):
    if state.eof or state.overflow or state.read_failed:
        return False
    remaining = cap - len(state.buf)
    to_read = min(chunk_limit, remaining + 1 if remaining >= 0 else 1)
    if to_read < 1:
        to_read = 1
    try:
        chunk = await _maybe(getattr(effects, method_name)(handle, to_read))
    except Exception:
        state.remainder_unknown = True
        state.read_failed = True
        return False
    if chunk is None:
        return False
    if chunk == b"":
        state.eof = True
        return True
    if not isinstance(chunk, (bytes, bytearray)):
        state.remainder_unknown = True
        return False
    state.observed += len(chunk)
    if len(state.buf) >= cap or len(state.buf) + len(chunk) > cap:
        take = cap - len(state.buf)
        if take > 0:
            state.buf += chunk[:take]
        state.overflow = True
        state.remainder_unknown = True
        return True
    state.buf += chunk
    return True


def _signature(stdout, stderr, status):
    return (len(stdout.buf), stdout.eof, stdout.overflow, len(stderr.buf), stderr.eof, stderr.overflow, status)


async def _persist(effects, path, payload, deadline, clock, reservation):
    fact = _empty_persistence()
    causes = []
    if not isinstance(payload, (bytes, bytearray)):
        fact["extent_unknown"] = True
        _add(causes, "persisted_prefix_extent_unknown")
        _add(causes, "persistence_incomplete")
        return fact, causes
    data = bytes(payload)
    now = await clock.read()
    if clock.regressed or now > deadline:
        fact["late"] = now > deadline
        fact["extent_unknown"] = True
        if now > deadline:
            _add(causes, "deadline_late")
        if clock.regressed:
            _add(causes, "clock_regression")
        _add(causes, "persistence_incomplete")
        _add(causes, "persisted_prefix_extent_unknown")
        return fact, causes
    rounded = round_up_allocation(len(data)) + INODE_BYTES
    if reservation["bytes"] + rounded > P0_FORMS_CEILING:
        fact["extent_unknown"] = True
        _add(causes, "allocation_ceiling_exceeded")
        _add(causes, "persisted_prefix_extent_unknown")
        _add(causes, "persistence_incomplete")
        return fact, causes
    reservation["bytes"] += rounded
    _note_reserve(effects, rounded)
    now = await clock.read()
    if clock.regressed or now > deadline:
        fact["late"] = True
        fact["extent_unknown"] = True
        _add(causes, "deadline_late")
        _add(causes, "persistence_incomplete")
        _add(causes, "persisted_prefix_extent_unknown")
        return fact, causes
    try:
        handle = await _maybe(effects.open_exclusive(path))
        fact["open_completed"] = True
    except Exception:
        fact["extent_unknown"] = True
        _add(causes, "stream_write_failed")
        _add(causes, "persisted_prefix_extent_unknown")
        _add(causes, "persistence_incomplete")
        return fact, causes
    try:
        view = memoryview(data)
        offset = 0
        while offset < len(view):
            now = await clock.read()
            if clock.regressed or now > deadline:
                fact["late"] = True
                fact["extent_unknown"] = True
                _add(causes, "deadline_late")
                break
            try:
                written = await _maybe(effects.write(handle, bytes(view[offset:offset + READ_CHUNK])))
            except Exception:
                fact["extent_unknown"] = True
                _add(causes, "stream_write_failed")
                break
            if not isinstance(written, int) or written < 0 or (written == 0 and offset < len(view)):
                fact["extent_unknown"] = True
                _add(causes, "stream_write_failed")
                break
            offset += written
            fact["written_bytes"] = offset
        if fact["written_bytes"] != len(data):
            fact["extent_unknown"] = True
            _add(causes, "persistence_incomplete")
        if not fact["extent_unknown"] and not fact["late"] and not clock.regressed:
            now = await clock.read()
            if clock.regressed or now > deadline:
                fact["late"] = now > deadline
                fact["extent_unknown"] = True
                if now > deadline:
                    _add(causes, "deadline_late")
                if clock.regressed:
                    _add(causes, "clock_regression")
            else:
                try:
                    await _maybe(effects.fsync(handle))
                    fact["fsync_completed"] = True
                except Exception:
                    fact["extent_unknown"] = True
                    _add(causes, "stream_fsync_failed")
                now = await clock.read()
                if clock.regressed or now > deadline:
                    fact["late"] = now > deadline
                    fact["extent_unknown"] = True
                    if now > deadline:
                        _add(causes, "deadline_late")
                    if clock.regressed:
                        _add(causes, "clock_regression")
    finally:
        try:
            await _maybe(effects.close(handle))
            fact["close_completed"] = True
        except Exception:
            fact["close_completed"] = False
            fact["extent_unknown"] = True
            _add(causes, "stream_close_failed")
    if fact["extent_unknown"]:
        _add(causes, "persisted_prefix_extent_unknown")
    now = await clock.read()
    if clock.regressed or now > deadline:
        fact["late"] = True if now > deadline else fact["late"]
        fact["extent_unknown"] = True
        fact["completed"] = False
        fact["prefix_sha256"] = None
        if now > deadline:
            _add(causes, "deadline_late")
        if clock.regressed:
            _add(causes, "clock_regression")
        _add(causes, "persisted_prefix_extent_unknown")
        _add(causes, "persistence_incomplete")
        return fact, causes
    fact["completed"] = (
        fact["open_completed"]
        and fact["fsync_completed"]
        and fact["close_completed"]
        and fact["written_bytes"] == len(data)
        and not fact["extent_unknown"]
        and not fact["late"]
    )
    if fact["completed"]:
        fact["prefix_sha256"] = _sha256(data)
    else:
        fact["prefix_sha256"] = None
        _add(causes, "persistence_incomplete")
    return fact, causes


def _apply_stream(command, key, state, cap, persistence):
    retained = bytes(state.buf)
    command[key] = _stream_fact(
        cap,
        retained,
        state.observed,
        state.eof,
        state.overflow,
        state.remainder_unknown,
        command[key]["relative_path"],
        persistence,
    )
    if key == "stdout":
        command["eof_stdout"] = state.eof
    else:
        command["eof_stderr"] = state.eof


def _mark_remainder(stdout, stderr):
    if not stdout.eof and not stdout.overflow:
        stdout.remainder_unknown = True
    if not stderr.eof and not stderr.overflow:
        stderr.remainder_unknown = True


async def _run_command(effects, name, phases, stderr_budget, output_dir, clock, reservation):
    command = _blank_command(name, phases)
    command["__stdout_path"] = join_output(output_dir, STREAM_FILES[name][0])
    command["__stderr_path"] = join_output(output_dir, STREAM_FILES[name][1])
    causes = command["causes"]
    stdout = _Pull()
    stderr = _Pull()
    stdout_cap = STDOUT_CAPS[name]
    stderr_cap = stderr_budget
    command["stderr"]["cap_bytes"] = stderr_cap
    handle = None
    status = None
    spawned = False
    spawn_late = False

    async def observe():
        now = await clock.read()
        if clock.regressed:
            _add(causes, "clock_regression")
        return now

    try:
        handle = await _maybe(effects.spawn(list(command["argv"]), dict(command["env"])))
        spawned = True
        command["pid"] = getattr(handle, "pid", None)
    except Exception:
        _add(causes, "spawn_failed")
        command["timestamps"]["spawn_returned"] = await observe()
        command["linux_child_closure"] = "unknown"
        return command, stderr_budget
    command["timestamps"]["spawn_returned"] = await observe()
    if clock.regressed or command["timestamps"]["spawn_returned"] > phases["cmd_deadline"]:
        spawn_late = True
        command["linux_child_closure"] = "unknown"
        if command["timestamps"]["spawn_returned"] > phases["cmd_deadline"]:
            command["late"] = True
            command["timed_out"] = True
            _add(causes, "deadline_late")
        command["timestamps"]["drain_finished"] = command["timestamps"]["spawn_returned"]
        return command, stderr_budget
    idle = getattr(effects, "idle", None)
    try:
        while True:
            now = await observe()
            if clock.regressed:
                _mark_remainder(stdout, stderr)
                break
            if now > phases["cmd_deadline"]:
                command["late"] = True
                command["timed_out"] = True
                _add(causes, "deadline_late")
                break
            if now >= phases["capture_deadline"] and not (
                (stdout.eof or stdout.overflow) and (stderr.eof or stderr.overflow) and status is not None
            ):
                command["timed_out"] = True
                _mark_remainder(stdout, stderr)
                break
            before = _signature(stdout, stderr, status)
            before_t = now
            if not stdout.eof and not stdout.overflow:
                await _pull_stream(effects, "read_stdout", handle, stdout, stdout_cap, READ_CHUNK)
                if stdout.read_failed:
                    _add(causes, "stream_read_failed")
                    _mark_remainder(stdout, stderr)
                    break
            now = await observe()
            if clock.regressed or now > phases["cmd_deadline"]:
                if now > phases["cmd_deadline"]:
                    command["late"] = True
                    command["timed_out"] = True
                    _add(causes, "deadline_late")
                _mark_remainder(stdout, stderr)
                break
            if not stderr.eof and not stderr.overflow:
                await _pull_stream(effects, "read_stderr", handle, stderr, stderr_cap, READ_CHUNK)
                if stderr.read_failed:
                    _add(causes, "stream_read_failed")
                    _mark_remainder(stdout, stderr)
                    break
            try:
                status = await _maybe(effects.poll_exit(handle))
            except Exception:
                status = None
                _add(causes, "stream_read_failed")
                _mark_remainder(stdout, stderr)
                break
            now = await observe()
            if clock.regressed or now > phases["cmd_deadline"]:
                if now > phases["cmd_deadline"]:
                    command["late"] = True
                    command["timed_out"] = True
                    _add(causes, "deadline_late")
                _mark_remainder(stdout, stderr)
                break
            if (stdout.eof or stdout.overflow) and (stderr.eof or stderr.overflow) and status is not None:
                break
            after = _signature(stdout, stderr, status)
            # Async process-exit callbacks can remain queued after both pipe
            # EOFs. An advancing clock is not progress and must not starve them.
            if after == before:
                if idle is not None:
                    await _maybe(idle())
                    now = await observe()
                if clock.regressed:
                    _mark_remainder(stdout, stderr)
                    break
                if now <= before_t:
                    _add(causes, "clock_stalled")
                    break
        command["timestamps"]["drain_finished"] = await observe()
        now = command["timestamps"]["drain_finished"]
        if clock.regressed:
            _mark_remainder(stdout, stderr)
    except Exception:
        _mark_remainder(stdout, stderr)
        _add(causes, "stream_read_failed")
        now = await observe()
        command["timestamps"]["drain_finished"] = now
    if (
        spawned
        and not spawn_late
        and status is None
        and not command["late"]
        and not clock.regressed
        and now <= phases["cmd_deadline"]
        and now >= phases["capture_deadline"]
    ):
        try:
            await _maybe(effects.terminate_owned_parent(handle))
            command["forced_parent_termination"] = True
        except Exception:
            _add(causes, "owned_parent_termination_failed")
            command["forced_parent_termination"] = False
        try:
            if not stdout.eof and not stdout.overflow:
                await _pull_stream(effects, "read_stdout", handle, stdout, stdout_cap, READ_CHUNK)
            if not stderr.eof and not stderr.overflow:
                await _pull_stream(effects, "read_stderr", handle, stderr, stderr_cap, READ_CHUNK)
            if stdout.read_failed or stderr.read_failed:
                _add(causes, "stream_read_failed")
                _mark_remainder(stdout, stderr)
            status = await _maybe(effects.poll_exit(handle))
        except Exception:
            status = None
            _add(causes, "stream_read_failed")
            _mark_remainder(stdout, stderr)
        now = await observe()
        if now > phases["cmd_deadline"]:
            command["late"] = True
            command["timed_out"] = True
            _add(causes, "deadline_late")
    command["returncode"] = status
    if stdout.overflow:
        _add(causes, "stdout_overflow")
    if stderr.overflow:
        _add(causes, "stderr_combined_overflow")
    if command["forced_parent_termination"]:
        _add(causes, "owned_parent_forced_termination")
        _add(causes, "linux_child_closure_unknown")
    if not spawn_late and not command["late"]:
        if not stdout.eof or not stderr.eof:
            _add(causes, "stream_eof_missing")
        if status is None:
            _add(causes, "wsl_status_unknown")
            _add(causes, "linux_child_closure_unknown")
        elif status != 0 and not command["forced_parent_termination"]:
            _add(causes, "wsl_status_nonzero")
    complete_bytes = (
        stdout.eof
        and stderr.eof
        and not stdout.overflow
        and not stderr.overflow
        and not stdout.remainder_unknown
        and not stderr.remainder_unknown
    )
    if complete_bytes and not command["late"] and not command["forced_parent_termination"]:
        if name == "id":
            for item in validate_id_stdout(bytes(stdout.buf))["causes"]:
                _add(causes, item)
        elif name == "snapshot_info":
            for item in validate_snapshot_info(bytes(stdout.buf))["causes"]:
                _add(causes, item)
        elif name == "snapshot_ls":
            for item in validate_snapshot_ls(bytes(stdout.buf))["causes"]:
                _add(causes, item)
    closure_known = (
        complete_bytes
        and status is not None
        and not command["forced_parent_termination"]
        and not command["late"]
    )
    command["linux_child_closure"] = "normal_wsl_exit_and_eof" if closure_known else "unknown"
    command["normal_exit"] = bool(
        closure_known and status == 0 and "stream_eof_missing" not in causes
    )
    if command["linux_child_closure"] != "normal_wsl_exit_and_eof":
        _add(causes, "linux_child_closure_unknown")
    now = await observe()
    if clock.regressed or now > phases["cmd_deadline"]:
        if now > phases["cmd_deadline"]:
            command["late"] = True
            _add(causes, "deadline_late")
        stdout_persistence = _empty_persistence()
        stderr_persistence = _empty_persistence()
        stdout_persistence["late"] = now > phases["cmd_deadline"]
        stderr_persistence["late"] = now > phases["cmd_deadline"]
        stdout_persistence["extent_unknown"] = True
        stderr_persistence["extent_unknown"] = True
        _add(causes, "persistence_incomplete")
        _add(causes, "persisted_prefix_extent_unknown")
    else:
        try:
            stdout_persistence, stdout_causes = await _persist(
                effects, command["__stdout_path"], bytes(stdout.buf), phases["cmd_deadline"],
                clock, reservation,
            )
            stderr_persistence, stderr_causes = await _persist(
                effects, command["__stderr_path"], bytes(stderr.buf), phases["cmd_deadline"],
                clock, reservation,
            )
        except Exception:
            stdout_persistence = _empty_persistence()
            stderr_persistence = _empty_persistence()
            stdout_persistence["extent_unknown"] = True
            stderr_persistence["extent_unknown"] = True
            stdout_causes = ["stream_write_failed", "persisted_prefix_extent_unknown"]
            stderr_causes = []
            _mark_remainder(stdout, stderr)
        for item in stdout_causes + stderr_causes:
            _add(causes, item)
        if stdout_persistence["late"] or stderr_persistence["late"]:
            command["late"] = True
            _add(causes, "deadline_late")
    _apply_stream(command, "stdout", stdout, stdout_cap, stdout_persistence)
    _apply_stream(command, "stderr", stderr, stderr_cap, stderr_persistence)
    command["timestamps"]["persist_finished"] = await observe()
    if clock.regressed or command["timestamps"]["persist_finished"] > phases["cmd_deadline"]:
        if command["timestamps"]["persist_finished"] > phases["cmd_deadline"]:
            command["late"] = True
            _add(causes, "deadline_late")
    if command["late"] or clock.regressed:
        command["linux_child_closure"] = "unknown"
        command["normal_exit"] = False
        _add(causes, "linux_child_closure_unknown")
        for key in ("stdout", "stderr"):
            command[key]["persistence"]["completed"] = False
            command[key]["persistence"]["late"] = command["late"]
            command[key]["persistence"]["prefix_sha256"] = None
            if clock.regressed or command["late"]:
                command[key]["persistence"]["extent_unknown"] = True
    retained_stderr = len(stderr.buf)
    return command, max(0, stderr_budget - retained_stderr)


def _public_command(command):
    hidden = {"__stdout_path", "__stderr_path", "_output_dir"}
    return {key: value for key, value in command.items() if key not in hidden}


def _result_shell(sealed, causes, *, controlled, reviewed_code_commit):
    return {
        "schema": "gate2-p0-capture.v1",
        "physical_acceptance": False,
        "controlled": controlled is True,
        "reviewed_code_commit": reviewed_code_commit,
        "kernel_preemption_claimed": False,
        "human_review": False,
        "actor": "agent_observed_root_proof",
        "engine_observed_by_collector": False,
        "comparison_engine_constant": KNOWN_ENGINE_ID,
        "bound_engine_id": sealed.get("bound_engine_id"),
        "boot_id": sealed.get("boot_id"),
        "provenance_observer": sealed.get("provenance_observer"),
        "changes_distro_default_uid": False,
        "ordinary_cd_uid_gid": [ORDINARY_CD_UID_GID[0], ORDINARY_CD_UID_GID[1]],
        "accepted": False,
        "predicates_satisfied": False,
        "causes": list(causes),
        "commands_attempted": 0,
        "spawn_count": 0,
        "commands": [],
        "allocation": {
            "ceiling_bytes": P0_FORMS_CEILING,
            "code_p0_allocation_bytes": CODE_P0_ALLOCATION,
            "quantum_bytes": ALLOCATION_QUANTUM,
            "directory_reserve_bytes": DIRECTORY_RESERVE,
            "preencoding_reserve_bytes": METADATA_COMBINED_CAP,
            "preencoding_control_bytes": 0,
            "metadata_copy_bytes": METADATA_COPY_CAP,
            "inode_bytes": INODE_BYTES,
            "charged_bytes": 0,
            "maximum_inclusive_bytes": maximum_inclusive_charge(),
            "within_ceiling": True,
            "p0_only": True,
        },
        "control_record": {
            "relative_path": CONTROL_NAME,
            "encoded_bytes": 0,
            "claims_self_persistence": False,
            "write_proof": _empty_persistence(),
        },
        "completion_record": None,
        "deadlines": {
            "absolute_s": ABSOLUTE_DEADLINE_S,
            "per_command_s": PER_COMMAND_DEADLINE_S,
            "persistence_reserve_s": PERSISTENCE_RESERVE_S,
            "owned_parent_termination_reserve_s": OWNED_PARENT_TERMINATION_RESERVE_S,
            "closure_observation_reserve_s": CLOSURE_OBSERVATION_RESERVE_S,
        },
    }


def _merge_control_causes(result, control_causes):
    for item in control_causes:
        if item == "stream_write_failed":
            _add(result["causes"], "control_record_write_failed")
        elif item == "stream_fsync_failed":
            _add(result["causes"], "control_record_fsync_failed")
        elif item == "stream_close_failed":
            _add(result["causes"], "control_record_close_failed")
        else:
            _add(result["causes"], item)


def _minimal_control(result):
    return {
        "schema": "gate2-p0-control.v1",
        "physical_acceptance": False,
        "controlled": result["controlled"] is True,
        "reviewed_code_commit": result["reviewed_code_commit"],
        "engine_observed_by_collector": False,
        "predicates_satisfied": False,
        "causes": ["control_record_preencoding_exceeded"],
        "commands_attempted": result["commands_attempted"],
    }


def _completion_document(result, control_bytes, control_proof, started, deadline, finish, charged):
    return {
        "schema": "gate2-p0-originals.v1",
        "reviewed_code_commit": result["reviewed_code_commit"],
        "controlled": False,
        "physical_acceptance": False,
        "actor": "agent_observed_root_proof",
        "human_review": False,
        "engine_observed_by_collector": False,
        "bound_engine_id": result["bound_engine_id"],
        "boot_id": result["boot_id"],
        "control": {
            "relative_path": CONTROL_NAME,
            "size_bytes": len(control_bytes),
            "sha256": _sha256(control_bytes),
        },
        "control_write_proof": {
            "open_completed": control_proof["open_completed"],
            "written_bytes": control_proof["written_bytes"],
            "fsync_completed": control_proof["fsync_completed"],
            "close_completed": control_proof["close_completed"],
            "late": control_proof["late"],
            "extent_unknown": control_proof["extent_unknown"],
            "completed": control_proof["completed"],
            "prefix_sha256": control_proof["prefix_sha256"],
        },
        "predicates_satisfied": result["predicates_satisfied"] is True and not result["causes"],
        "causes": list(result["causes"]),
        "timing": {
            "start": started,
            "deadline": deadline,
            "finish": finish,
        },
        "allocation": {
            "ceiling_bytes": P0_FORMS_CEILING,
            "charged_bytes": charged,
            "within_ceiling": charged <= P0_FORMS_CEILING,
            "metadata_copy_bytes": METADATA_COPY_CAP,
        },
    }


async def _collect(output_dir, sealed_binding, effects, *, controlled, reviewed_code_commit, native_completion,
                   original_start=None):
    started = await _maybe(effects.monotonic()) if original_start is None else original_start
    clock = _Clock(effects, started)
    global_deadline = started + ABSOLUTE_DEADLINE_S
    sealed = validate_sealed_binding(sealed_binding)
    result = _result_shell(
        sealed, sealed["causes"], controlled=controlled, reviewed_code_commit=reviewed_code_commit,
    )
    if clock.regressed:
        _add(result["causes"], "clock_regression")
        return result
    if not sealed["ok"]:
        return result
    if not is_windows_absolute(output_dir):
        _add(result["causes"], "output_dir_not_absolute")
        return result
    if maximum_inclusive_charge() > P0_FORMS_CEILING:
        _add(result["causes"], "allocation_ceiling_exceeded")
        return result
    before_mkdir = await clock.read()
    if clock.regressed:
        _add(result["causes"], "clock_regression")
        return result
    if before_mkdir >= global_deadline:
        _add(result["causes"], "absolute_deadline")
        _add(result["causes"], "deadline_late")
        return result
    try:
        await _maybe(effects.mkdir_fresh(output_dir))
    except FileExistsError:
        _add(result["causes"], "output_dir_not_fresh")
        return result
    except Exception:
        _add(result["causes"], "output_dir_not_fresh")
        return result
    reservation = _fresh_reservation()
    stderr_budget = STDERR_COMBINED_CAP
    for name in COMMAND_ORDER:
        now = await clock.read()
        if clock.regressed:
            _add(result["causes"], "clock_regression")
            break
        if now >= global_deadline:
            _add(result["causes"], "absolute_deadline")
            _add(result["causes"], "deadline_late")
            break
        phases = command_phase_deadlines(now, global_deadline)
        command, stderr_budget = await _run_command(
            effects, name, phases, stderr_budget, output_dir, clock, reservation,
        )
        result["commands"].append(_public_command(command))
        if command["causes"]:
            for item in command["causes"]:
                _add(result["causes"], item)
            break
    result["commands_attempted"] = len(result["commands"])
    result["spawn_count"] = sum(
        1 for command in result["commands"]
        if command["timestamps"]["spawn_returned"] is not None
    )
    predicates = _predicates_satisfied(result)
    result["predicates_satisfied"] = predicates
    document = _control_document(result)
    encoded = canonical_json(document)
    if len(encoded) > CONTROL_RECORD_CAP:
        _add(result["causes"], "control_record_preencoding_exceeded")
        result["predicates_satisfied"] = False
        predicates = False
        encoded = canonical_json(_minimal_control(result))
    proof, control_causes = await _persist(
        effects, join_output(output_dir, CONTROL_NAME), encoded, global_deadline, clock, reservation,
    )
    _merge_control_causes(result, control_causes)
    result["allocation"]["preencoding_control_bytes"] = len(encoded)
    result["control_record"] = {
        "relative_path": CONTROL_NAME,
        "encoded_bytes": len(encoded),
        "claims_self_persistence": False,
        "write_proof": proof,
    }
    completion_ok = not native_completion
    if native_completion:
        finish = await clock.read()
        if clock.regressed:
            _add(result["causes"], "clock_regression")
        completion = _completion_document(
            result, encoded, proof, started, global_deadline, finish, reservation["bytes"],
        )
        completion_encoded = canonical_json(completion)
        if (
            len(completion_encoded) > COMPLETION_RECORD_CAP
            or len(encoded) + len(completion_encoded) > METADATA_COMBINED_CAP
        ):
            _add(result["causes"], "control_record_preencoding_exceeded")
            predicates = False
        else:
            completion_proof, completion_causes = await _persist(
                effects, join_output(output_dir, COMPLETION_NAME), completion_encoded,
                global_deadline, clock, reservation,
            )
            for item in completion_causes:
                if item == "stream_write_failed":
                    _add(result["causes"], "completion_record_write_failed")
                elif item == "stream_fsync_failed":
                    _add(result["causes"], "completion_record_fsync_failed")
                elif item == "stream_close_failed":
                    _add(result["causes"], "completion_record_close_failed")
                else:
                    _add(result["causes"], item)
            result["completion_record"] = {
                "relative_path": COMPLETION_NAME,
                "encoded_bytes": len(completion_encoded),
                "sha256": _sha256(completion_encoded),
                "claims_self_persistence": False,
                "write_proof": completion_proof,
            }
            completion_ok = completion_proof["completed"]
    final_now = await clock.read()
    if clock.regressed:
        _add(result["causes"], "clock_regression")
    if final_now > global_deadline:
        _add(result["causes"], "deadline_late")
    within = (
        reservation["bytes"] <= P0_FORMS_CEILING
        and len(encoded) <= CONTROL_RECORD_CAP
    )
    if not within:
        _add(result["causes"], "allocation_ceiling_exceeded")
    result["allocation"]["charged_bytes"] = reservation["bytes"]
    result["allocation"]["within_ceiling"] = within and "allocation_ceiling_exceeded" not in result["causes"]
    result["accepted"] = bool(
        predicates and proof["completed"] and completion_ok and within and not result["causes"]
    )
    return result


async def collect_p0_v1_async(output_dir, sealed_binding, *, effects):
    _require_controlled(effects)
    return await _collect(
        output_dir, sealed_binding, effects,
        controlled=True, reviewed_code_commit=None, native_completion=False,
    )


def _predicates_satisfied(result):
    if result["causes"] or result["commands_attempted"] != len(COMMAND_ORDER):
        return False
    for command in result["commands"]:
        if command["causes"]:
            return False
        if command["linux_child_closure"] != "normal_wsl_exit_and_eof":
            return False
        if command["returncode"] != 0 or command["late"] or command["forced_parent_termination"]:
            return False
        if not command["stdout"]["persistence"]["completed"]:
            return False
        if not command["stderr"]["persistence"]["completed"]:
            return False
    return True


def _control_document(result):
    commands = [dict(command) for command in result["commands"]]
    return {
        "schema": "gate2-p0-control.v1",
        "physical_acceptance": False,
        "controlled": result["controlled"] is True,
        "reviewed_code_commit": result["reviewed_code_commit"],
        "human_review": False,
        "engine_observed_by_collector": False,
        "comparison_engine_constant": KNOWN_ENGINE_ID,
        "bound_engine_id": result["bound_engine_id"],
        "boot_id": result["boot_id"],
        "provenance_observer": result["provenance_observer"],
        "changes_distro_default_uid": False,
        "ordinary_cd_uid_gid": [1000, 1000],
        "predicates_satisfied": result["predicates_satisfied"],
        "causes": list(result["causes"]),
        "commands_attempted": len(result["commands"]),
        "commands": commands,
        "allocation": {
            "ceiling_bytes": P0_FORMS_CEILING,
            "quantum_bytes": ALLOCATION_QUANTUM,
            "directory_reserve_bytes": DIRECTORY_RESERVE,
            "includes_control_persistence_claim": False,
        },
    }


def collect_p0_v1(output_dir, sealed_binding, *, effects):
    return asyncio.run(
        collect_p0_v1_async(output_dir, sealed_binding, effects=effects)
    )


def _invocation_allowed(argv, env):
    if os.name != "nt":
        return False
    if not isinstance(argv, list):
        return False
    if not any(argv == fixed_argv(name) for name in COMMAND_ORDER):
        return False
    if not isinstance(env, dict) or env != fixed_environment():
        return False
    return True


async def _collect_native_p0_v1_async(output_dir, sealed_binding, *, reviewed_code_commit, original_start):
    if os.name != "nt":
        sealed = validate_sealed_binding(sealed_binding)
        result = _result_shell(
            sealed, sealed["causes"], controlled=False, reviewed_code_commit=None,
        )
        _add(result["causes"], "windows_native_requires_nt")
        return result
    if not _valid_commit(reviewed_code_commit):
        sealed = validate_sealed_binding(sealed_binding)
        result = _result_shell(
            sealed, sealed["causes"], controlled=False, reviewed_code_commit=None,
        )
        _add(result["causes"], "reviewed_code_commit_invalid")
        return result
    effects = windows_native_p0_effects()
    return await _collect(
        output_dir, sealed_binding, effects,
        controlled=False, reviewed_code_commit=reviewed_code_commit, native_completion=True,
        original_start=original_start,
    )


async def collect_native_p0_v1_async(output_dir, sealed_binding, *, reviewed_code_commit):
    original_start = time.monotonic()
    return await _collect_native_p0_v1_async(
        output_dir, sealed_binding, reviewed_code_commit=reviewed_code_commit, original_start=original_start,
    )


def collect_native_p0_v1(output_dir, sealed_binding, *, reviewed_code_commit):
    # Include validation, native factory construction and event-loop startup in
    # the same clock interval. These trusted calls are not kernel-preemptible.
    original_start = time.monotonic()
    return asyncio.run(_collect_native_p0_v1_async(
        output_dir, sealed_binding, reviewed_code_commit=reviewed_code_commit, original_start=original_start,
    ))


class _WindowsP0Io:
    """Shared bounded process IO. Construction does not launch."""

    def monotonic(self):
        return time.monotonic()

    async def _read(self, stream, max_bytes):
        if stream is None:
            return b""
        try:
            return await asyncio.wait_for(stream.read(max_bytes), timeout=0.05)
        except asyncio.TimeoutError:
            return None

    async def read_stdout(self, handle, max_bytes):
        return await self._read(handle.proc.stdout, max_bytes)

    async def read_stderr(self, handle, max_bytes):
        return await self._read(handle.proc.stderr, max_bytes)

    def poll_exit(self, handle):
        return handle.proc.returncode

    async def idle(self):
        await asyncio.sleep(0.05)

    def terminate_owned_parent(self, handle):
        handle.proc.terminate()

    def mkdir_fresh(self, path):
        if os.path.exists(path):
            raise FileExistsError(path)
        os.mkdir(path)

    def open_exclusive(self, path):
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        if hasattr(os, "O_BINARY"):
            flags |= os.O_BINARY
        return os.open(path, flags, 0o600)

    def write(self, handle, data):
        return os.write(handle, data)

    def fsync(self, handle):
        os.fsync(handle)

    def close(self, handle):
        os.close(handle)


class WindowsControlledEffects(_WindowsP0Io):
    """Controlled seam. Construction and spawn never launch a process."""

    controlled = True
    physical_acceptance = False
    label = "controlled"

    def __init__(self):
        self.spawn_calls = 0

    async def spawn(self, argv, env):
        raise P0SeamError("controlled_effects_cannot_launch")


class WindowsNativeP0Effects(_WindowsP0Io):
    """Fixed Windows launcher. Spawn accepts only the exact argv and env."""

    controlled = False
    physical_acceptance = False
    label = "native"

    def __init__(self):
        self.spawn_calls = 0

    async def spawn(self, argv, env):
        if not _invocation_allowed(argv, env):
            raise P0SeamError("fixed_wsl_argv_required")
        self.spawn_calls += 1
        process = await asyncio.create_subprocess_exec(
            argv[0],
            *argv[1:],
            env=fixed_environment(),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        handle = type("WindowsHandle", (), {})()
        handle.proc = process
        handle.pid = process.pid
        handle.identity = ("owned-parent", process.pid)
        return handle


def windows_controlled_effects():
    return WindowsControlledEffects()


def windows_native_p0_effects():
    if os.name != "nt":
        raise P0SeamError("windows_native_requires_nt")
    return WindowsNativeP0Effects()
