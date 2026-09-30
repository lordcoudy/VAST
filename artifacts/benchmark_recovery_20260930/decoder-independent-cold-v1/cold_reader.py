"""Read-only failed-setup audit of the first original research attempt.

No producer/GI import, subprocess, Docker query, source launch or pixel decode.
Review before execution. This fixed failed-setup audit exits nonzero after sealing
its forensic report; it cannot approve a successful or partial source-run cohort.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import struct
import time

HEADER = struct.Struct(">8sHHQQQQQQIIIQ")
MISSING = (1 << 64) - 1
RAW_MAX = 128 * 1024 * 1024
PAYLOAD_MAX = 64 * 1024 * 1024
DOC_MAX = 1024 * 1024
LINE_MAX = 16384
CHANNEL_MAX = 1024 * 1024
ORDER = (("front_gate", "default"), ("front_gate", "zero"),
         ("underbody", "zero"), ("underbody", "default"))
PLANNING = "b1ad01c09b4e21f542f971b9dc794548245719b0"
SOURCE_COMMIT = "a045b8874ad15b2fa05f1a5d7fc9f331e8b04a47"
IMAGE = "sha256:70696f057232acd382f60beaaf12cd9279b317b0ba9a7ade29f0b955ce90481a"
DAEMON = "aa8f3d33-e1dc-4ed2-ad06-488b46b332d0"
ENGINE_SHA = "a429e235ef670ea83357a5c8c7451f0a69d485a6fee49f9032fd938a0ab4969d"
CODE_PINS = {
    "controller.py": "2a40c3bc584dae92aa8be2295707dd02553242b64f4eec4fa4b8e33d7b3c0124",
    "guest_consumer.py": "d826898fe9c03d6111c6c2725dee35a1061ee572fb7992f5b749f7fe97848a30",
    "research_protocol.py": "fcb8a16bbb100fa13c3ff5584913d318f25f95a8205751107790be5086b02c63",
}
EVENT_FIELDS = frozenset(("protocol_version", "source_process_id", "sequence", "run_id",
    "dataset_id", "stream_id", "admission_id", "input_frame_key", "source_sha256",
    "source_cycle", "access_unit_pts_ns", "payload_sha256", "payload_size_bytes",
    "schedule_offset_ns", "admission_timestamp_ms", "event_provenance"))


class Refusal(ValueError):
    pass


def require(ok, message):
    if not ok:
        raise Refusal(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("ascii")


def strict_json(raw, maximum=DOC_MAX, sealed=False):
    require(0 < len(raw) <= maximum, "JSON byte limit")
    def pairs(items):
        out = {}
        for key, value in items:
            require(key not in out, "duplicate JSON key")
            out[key] = value
        return out
    def bad_constant(value):
        raise Refusal("nonfinite JSON number")
    try:
        value = json.loads(raw, object_pairs_hook=pairs, parse_constant=bad_constant)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise Refusal("invalid bounded JSON") from error
    require(type(value) is dict, "JSON object required")
    if sealed:
        body = dict(value)
        digest = body.pop("sha256", None)
        require(digest == hashlib.sha256(canonical(body)).hexdigest(), "original self seal differs")
    return value


def epoch(info):
    return [info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns]


class Held:
    """Stream-hash fixed files; retain actual FD epochs and directory identities."""
    def __init__(self, root, deadline):
        self.root = Path(root)
        require(self.root.is_absolute() and self.root.resolve(strict=True) == self.root,
                "cold root has a path alias")
        self.deadline = deadline
        self.files = {}
        self.directories = {}
        self.pin_directory(self.root)

    def pin_directory(self, path):
        path = Path(path)
        require(path.resolve(strict=True) == path, "directory ancestor alias")
        for parent in (path, *path.parents):
            if str(parent) not in self.directories:
                require(len(self.directories) < 128, "cold directory FD limit")
                fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                info = os.fstat(fd)
                self.directories[str(parent)] = (fd, [info.st_dev, info.st_ino,
                    info.st_mode, info.st_uid, info.st_gid])

    def digest(self, fd, size):
        digest = hashlib.sha256()
        offset = 0
        while offset < size:
            require(time.monotonic() < self.deadline, "cold120s elapsed limit")
            raw = os.pread(fd, min(65536, size-offset), offset)
            require(bool(raw), "held physical file truncated")
            digest.update(raw)
            offset += len(raw)
        return digest.hexdigest()

    def pin(self, path, descriptor=None, maximum=RAW_MAX, under_root=True):
        path = Path(path)
        require(path.is_absolute() and path.resolve(strict=True) == path,
                "physical file path/ancestor alias")
        require(not under_root or path.is_relative_to(self.root), "foreign output leaf")
        key = str(path)
        if key not in self.files:
            require(len(self.files) < 256, "cold file FD limit")
            self.pin_directory(path.parent)
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            info = os.fstat(fd)
            try:
                require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1
                        and info.st_size <= maximum, "physical single-link/file cap")
                before = epoch(info)
                sha = self.digest(fd, info.st_size)
                require(before == epoch(os.fstat(fd)) == epoch(path.lstat()),
                        "physical leaf changed during hash")
                self.files[key] = (fd, before, {"path": key,
                    "size_bytes": info.st_size, "sha256": sha})
            except BaseException:
                os.close(fd)
                raise
        fd, before, actual = self.files[key]
        require(before[4] <= maximum, "reused leaf cap")
        if descriptor is not None:
            require(type(descriptor) is dict and set(descriptor) == {"path", "size_bytes", "sha256"},
                    "physical descriptor fields")
            require(descriptor == actual, "physical descriptor/path/hash differs")
        self.check(rehash=False)
        return dict(actual)

    def read(self, path, maximum=DOC_MAX, under_root=True):
        path = Path(path)
        self.pin(path, maximum=maximum, under_root=under_root)
        fd, before, _ = self.files[str(path)]
        raw = os.pread(fd, before[4]+1, 0)
        require(len(raw) == before[4], "held JSON read changed")
        self.check(rehash=False)
        return raw

    def document(self, path, kind=None, under_root=True):
        value = strict_json(self.read(path, under_root=under_root), sealed=True)
        if kind is not None:
            require(value.get("artifact_kind") == kind, "original document kind differs")
        return value

    def check(self, rehash):
        for path, (fd, before, descriptor) in self.files.items():
            require(before == epoch(os.fstat(fd)) == epoch(Path(path).lstat()),
                    "held leaf mutation/ABA")
            if rehash:
                require(self.digest(fd, before[4]) == descriptor["sha256"], "held bytes changed")
                require(before == epoch(os.fstat(fd)), "held hash epoch changed")
        for path, (fd, expected) in self.directories.items():
            for info in (os.fstat(fd), Path(path).lstat()):
                require([info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid] == expected,
                        "held namespace/ancestor changed")

    def observations(self):
        return [{"descriptor": descriptor, "actual_cold_epoch7": before}
                for _, before, descriptor in self.files.values()]

    def close(self):
        for fd, _, _ in self.files.values():
            os.close(fd)
        for fd, _ in self.directories.values():
            os.close(fd)




def bounded_lines(held, path, maximum_bytes=CHANNEL_MAX, maximum_lines=512):
    held.pin(path, maximum=maximum_bytes)
    fd, before, _ = held.files[str(path)]
    offset = 0
    pending = bytearray()
    number = 0
    while offset < before[4]:
        require(time.monotonic() < held.deadline, "cold line read deadline")
        raw = os.pread(fd, min(4096, before[4]-offset), offset)
        require(bool(raw), "original line read truncated")
        offset += len(raw)
        pending.extend(raw)
        while b"\n" in pending:
            end = pending.index(b"\n")+1
            require(end <= LINE_MAX and number < maximum_lines, "original line/count cap")
            number += 1
            yield bytes(pending[:end])
            del pending[:end]
        require(len(pending) <= LINE_MAX, "original incomplete line cap")
    require(not pending, "original truncated line prefix")




def nonpromoting(value):
    require(value.get("accepted") is False and value.get("publication_ready", False) is False,
            "research artifact improperly promotes acceptance")
    for field in ("benchmark_arm_count", "native_pair_count", "qualification_count"):
        require(value.get(field, 0) == 0, "research artifact has benchmark counts")


def validate_owner(value):
    require(type(value) is dict and type(value.get("pid")) is int and value["pid"] > 0
            and type(value.get("ppid")) is int and value["ppid"] >= 0
            and type(value.get("starttime_ticks")) is int and value["starttime_ticks"] > 0
            and value.get("uid") == value.get("gid") == 1000
            and re.fullmatch(r"[0-9a-f-]{36}", value.get("boot_id", "")), "original process owner facts")










def namespace(held, attempt):
    require({row.name for row in attempt.iterdir()} == {"controller","guest"}, "original attempt root namespace")
    inventory = []
    for group in (attempt/"controller",attempt/"guest"):
        held.pin_directory(group)
    controller = list((attempt/"controller").iterdir())
    require(len(controller) <= 128, "controller leaf limit")
    group_total = 0
    for leaf in controller:
        descriptor = held.pin(leaf,maximum=16*1024*1024)
        group_total += descriptor["size_bytes"]
        inventory.append(descriptor)
    require(group_total <= 16*1024*1024, "controller metadata limit")
    directories = list((attempt/"guest").iterdir())
    require(len(directories) <= 5, "guest namespace count")
    allowed = {"metadata",*[f"run-{i:02d}-{role}-{setting}" for i,(role,setting) in enumerate(ORDER,1)]}
    for directory in directories:
        require(directory.name in allowed and directory.is_dir() and not directory.is_symlink(), "foreign guest namespace")
        held.pin_directory(directory)
        leaves = list(directory.iterdir())
        require(len(leaves) <= 32, "guest leaf limit")
        size = 0
        for leaf in leaves:
            descriptor = held.pin(leaf,maximum=RAW_MAX)
            size += descriptor["size_bytes"]
            inventory.append(descriptor)
        require(size <= (16*1024*1024 if directory.name == "metadata" else 256*1024*1024),
                "guest namespace byte limit")
    require(sum(row["size_bytes"] for row in inventory) <= 4*256*1024*1024+32*1024*1024,
            "original total namespace limit")
    return inventory


def closed_command_group(held, path, expected_sha, kind):
    held.pin(path, maximum=LINE_MAX, under_root=False)
    require(held.files[str(path)][2]["sha256"] == expected_sha, "original closed observation physical hash")
    value = held.document(path, kind, under_root=False)
    nonpromoting(value)
    for row in value["commands"]:
        require(row["argv"][0] == "/usr/bin/docker" and type(row["returncode"]) is int
                and row["started_at_ns"] <= row["terminal_at_ns"], "actual observer command identity/time")
        validate_owner(row["child"])
        for role in ("stdout", "stderr"):
            descriptor = row[role]
            require(Path(descriptor["path"]).parent == path.parent, "foreign closed observer raw leaf")
            held.pin(Path(descriptor["path"]), descriptor, maximum=65536, under_root=False)
    return value


def command_bytes(held, row, role):
    descriptor = row[role]
    return held.read(Path(descriptor["path"]), maximum=65536, under_root=False)


def exact_absence(row, stdout, stderr, identifier):
    return row["returncode"] == 1 and stdout in (b"", b"\n") and stderr in [
        (prefix+identifier+"\n").encode("ascii") for prefix in (
            "Error response from daemon: No such container: ",
            "Error: No such object: ", "Error: No such container: ")]


def timestamp_ns(value):
    found = re.fullmatch(r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.(\d{1,9}))?Z", value)
    require(found is not None, "original daemon UTC timestamp")
    seconds = int(datetime.fromisoformat(found[1]+"+00:00").timestamp())
    return seconds*1000000000+int((found[2] or "").ljust(9,"0"))


def cleanup_facts(held, attempt, controller, late_path, cleanup_path):
    late = closed_command_group(held,late_path,
        "10a2ee8c76c856db3c9fe775145114aab549e16968b4ec2e0930bc4311332629",
        "vast_decoder_research_post_terminal_original_observation_v1")
    cleanup = closed_command_group(held,cleanup_path,
        "9af05fba0e32cdad28580f28c5bbbb02135b9b73a4666099c15062e429f4b9bf",
        "vast_decoder_research_original_owned_cleanup_v1")
    reservation_path = attempt/"controller/reservation.v1.json"
    held.pin(reservation_path,cleanup["reservation"])
    reservation = held.document(reservation_path,"vast_decoder_research_reservation_v1")
    require(reservation["name"] == controller["name"] and reservation["label"] == controller["label"]
            and reservation["image_id"] == IMAGE and reservation["daemon_id"] == DAEMON,
            "original reservation join")
    held.pin(Path(cleanup["engine"]["path"]),cleanup["engine"],maximum=64*1024*1024,under_root=False)
    require(cleanup["engine"]["sha256"] == ENGINE_SHA and cleanup["engine"] == late["engine"]
            and cleanup["engine_socket"] == late["engine_socket"] == reservation["engine_socket"],
            "original held engine/socket observation join")
    held.pin(late_path,cleanup["late_observation"],maximum=LINE_MAX,under_root=False)
    held.pin(attempt/"controller/terminal.v1.json",late["original_controller_terminal"])
    held.pin(attempt/"guest/metadata/research-terminal.v1.json",late["guest_terminal"])
    cid_path = attempt/"controller/original.cid"
    held.pin(cid_path,late["original_cidfile"])
    raw_cid = held.read(cid_path,65)
    require(re.fullmatch(b"[0-9a-f]{64}\n?",raw_cid) is not None, "completed original CID bytes")
    cid = raw_cid[:64].decode("ascii")
    require(cid == late["original_cid"] == cleanup["original_cid"], "original late CID equality")
    states = []
    for value in (late,cleanup):
        commands = value["commands"]
        require(commands[0]["argv"] == ["/usr/bin/docker","info","--format","{{json .ID}}"]
                and commands[0]["returncode"] == 0
                and command_bytes(held,commands[0],"stdout") == canonical(DAEMON)+b"\n"
                and command_bytes(held,commands[0],"stderr") == b"", "same original daemon")
        for row in commands:
            if row["argv"][1:3] == ["container","inspect"] and row["returncode"] == 0:
                require(row["argv"][-1] in (cid,controller["name"])
                        and command_bytes(held,row,"stderr") == b"", "original exact inspect identifier")
                observed = strict_json(command_bytes(held,row,"stdout"),16384)
                require(observed["Id"] == cid and observed["Name"] == "/"+controller["name"]
                        and observed["Image"] == IMAGE and observed["Operation"] == controller["label"]
                        and observed["Running"] is False and observed["Pid"] == 0
                        and observed["ExitCode"] == 1 and observed["OOMKilled"] is False,
                        "original late nonrunning failed container identity")
                states.append(observed)
    require(len(states) == 4 and all(row == states[0] for row in states)
            and cleanup["original_nonrunning_state_before_remove"] == states[0],
            "late observed state/full before-remove equality")
    initial = held.document(attempt/"controller/engine-05.v1.json",
        "vast_decoder_research_engine_observation_v1")
    require(initial["argv"][1:3] == ["container","inspect"]
            and initial["argv"][-1] == controller["name"] and initial["timed_out"] is False
            and initial["errors"] == [] and exact_absence(initial,
                command_bytes(held,initial,"stdout"),command_bytes(held,initial,"stderr"),controller["name"]),
            "original premature exact-name absence observation")
    timeline = {"original_name_absence_observed_realtime_ns":initial["observed_realtime_ns"],
        **{key+"_ns":timestamp_ns(states[0][key]) for key in ("Created","StartedAt","FinishedAt")}}
    require(timeline["Created_ns"] <= timeline["StartedAt_ns"] <= timeline["FinishedAt_ns"],
            "original late daemon timestamp ordering")
    commands = cleanup["commands"]
    require(len(commands) == 7 and commands[4]["argv"] == ["/usr/bin/docker","container","rm",cid]
            and commands[4]["returncode"] == 0 and command_bytes(held,commands[4],"stdout") == (cid+"\n").encode()
            and command_bytes(held,commands[4],"stderr") == b"", "original exact nonforce removal")
    for row,identifier in zip(commands[5:],(cid,controller["name"])):
        require(row["argv"][1:3] == ["container","inspect"] and row["argv"][-1] == identifier
                and exact_absence(row,command_bytes(held,row,"stdout"),command_bytes(held,row,"stderr"),identifier),
                "original post-remove exact CID/name absence")
    require(cleanup["confirmed_absent_identifiers"] == [cid,controller["name"]]
            and all(row["proc_exists"] is False for row in cleanup["original_pid_absence"])
            and all(row["group_exists"] is False for row in cleanup["original_group_absence"]),
            "original closed process/group/identifier absence observations")
    return {"late_observation":held.files[str(late_path)][2],"owned_cleanup":held.files[str(cleanup_path)][2],
        "late_positive_original_state":states[0],"exact_nonforce_remove_returncode":0,
        "post_remove_CID_and_name_absence_verified":True,
        "absence_limit":"These are original retained command/process observations after cleanup, not a new live engine query by this reader.",
        "original_controller_oom_remains_unknown":controller["oom_killed"] is None,
        "late_container_OOMKilled":states[0]["OOMKilled"],
        "original_realtime_observations":timeline,
        "timeline_limit":"Daemon UTC fields and controller realtime observation are retained setup facts; no sub-millisecond scientific latency or exclusive publication cause is inferred."}


def audit(project_root, attempt, external_terminal, late_path, cleanup_path):
    begun = time.monotonic()
    project_root, attempt = Path(project_root), Path(attempt)
    held = Held(attempt,begun+120)
    try:
        inventory = namespace(held,attempt)
        external_terminal = Path(external_terminal)
        held.pin(external_terminal,maximum=LINE_MAX,under_root=False)
        require(held.files[str(external_terminal)][2]["sha256"] ==
                "3e49f768a1c4c3718c66cfaa3e747166aedf0224eaeadb31f2364d4942868317",
                "original external terminal physical pin")
        # External observer artifacts are fixed outside the attempt. Pin without
        # admitting their paths as ordinary producer output leaves.
        external = strict_json(os.pread(held.files[str(external_terminal)][0],LINE_MAX,0),sealed=True)
        require(external["artifact_kind"] == "vast_decoder_research_original_controller_terminal_v1",
                "original external controller terminal kind")
        nonpromoting(external)
        require(type(external["returncode"]) is int and external["elapsed_s"] >= 0,
                "original external controller outcome")
        for key in ("stdout","stderr"):
            held.pin(Path(external[key]["path"]),external[key],maximum=CHANNEL_MAX,under_root=False)
        held.pin(Path(external["launch"]["path"]),external["launch"],maximum=LINE_MAX,under_root=False)
        external_launch = held.document(Path(external["launch"]["path"]),
            "vast_decoder_research_original_controller_launch_v1",under_root=False)
        require(external_launch["source_commit"] == SOURCE_COMMIT and external_launch["authorization_comment"] == 5902659269,
                "original exact authorized source/PR checkpoint")
        require(external_launch["argv"] == [
            "/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python",
            "-I","-B",str(project_root/"artifacts/benchmark_recovery_20260930/decoder-research-implementation-v1/controller.py"),
            "--project-root",str(project_root),"--output-dir",str(attempt)], "original external exact controller argv")
        controller = held.document(attempt/"controller/terminal.v1.json",
                                   "vast_decoder_research_controller_terminal_v1")
        nonpromoting(controller)
        require(external["child"] == external_launch["child"] == controller["controller"],
                "original external/internal controller process identity")
        original_stdout = held.read(Path(external["stdout"]["path"]),maximum=LINE_MAX,under_root=False)
        stdout_result = strict_json(original_stdout,LINE_MAX)
        held.pin(attempt/"controller/terminal.v1.json",stdout_result["receipt"])
        require(stdout_result["original_execution_completed"] is False and external["returncode"] == 1,
                "v1 cold reader scoped to original failed setup, not a complete cohort")
        require(controller["planning_commit"] == PLANNING and controller["image_id"] == IMAGE,
                "original reviewed planning/image")
        require(len(controller["held_inputs"]) <= 128, "original held input count")
        for descriptor in controller["held_inputs"]:
            source = Path(descriptor["path"])
            require(source.is_relative_to(project_root) or source == Path("/usr/bin/docker"),
                    "foreign original held source")
            held.pin(source,descriptor,maximum=2*1024*1024*1024,under_root=False)
        plan = held.document(attempt/"controller/execution-plan.v1.json","vast_decoder_research_plan_v1")
        require(plan["planning_commit"] == PLANNING and plan["image_id"] == IMAGE
                and plan["fixed_order"] == [list(row) for row in ORDER], "original fixed plan")
        held.pin(attempt/"controller/closed-controller-leaves.v1.json",controller["closed_controller_leaves"])
        manifest = held.document(attempt/"controller/closed-controller-leaves.v1.json",
                                 "vast_decoder_research_closed_controller_leaves_v1")
        require(len(manifest["leaves"]) <= 128, "controller manifest count")
        names = set()
        for descriptor in manifest["leaves"]:
            leaf = Path(descriptor["path"])
            require(leaf.parent == attempt/"controller" and leaf.name not in names, "controller manifest path/duplicate")
            names.add(leaf.name)
            held.pin(leaf,descriptor,maximum=16*1024*1024)
        require(names == {leaf.name for leaf in (attempt/"controller").iterdir()} -
                {"terminal.v1.json","closed-controller-leaves.v1.json","receipt-time-limit-failure.v1.json"},
                "controller original closed membership")
        # Do not claim inaccessible guest image files have been rehashed after
        # disposal. Actual host-mounted source/media/code observations are held.
        for descriptor in plan["code"]+plan["source_files"]+plan["planning_files"]+[plan["historical_prerequisite"]]:
            leaf = Path(descriptor["path"])
            require(leaf.is_relative_to(project_root), "foreign original project input")
            held.pin(leaf,descriptor,maximum=16*1024*1024,under_root=False)
        for row in plan["code"]:
            require(Path(row["path"]).name in CODE_PINS and row["sha256"] == CODE_PINS[Path(row["path"]).name],
                    "original exact reviewed code")
        for source in plan["sources"]:
            descriptor = source["media"]
            require(Path(descriptor["path"]).is_relative_to(project_root), "foreign source media")
            held.pin(Path(descriptor["path"]),descriptor,maximum=2*1024*1024*1024,under_root=False)
        guest_path = attempt/"guest/metadata/research-terminal.v1.json"
        guest = held.document(guest_path,"vast_decoder_research_guest_terminal_v1") if guest_path.exists() else None
        if guest is not None:
            nonpromoting(guest)
            require(guest["plan"]["sha256"] == held.files[str(attempt/"controller/execution-plan.v1.json")][2]["sha256"],
                    "original guest plan byte equality")
        runs_present = [path.name for path in (attempt/"guest").iterdir() if path.name.startswith("run-")]
        base = {"schema_version":1,"artifact_kind":"vast_independent_decoder_cold_replay_v1",
            "reviewed_planning_commit":PLANNING,"original_source_commit":SOURCE_COMMIT,
            "original_external_returncode":external["returncode"],"original_external_elapsed_s":external["elapsed_s"],
            "original_controller_failure":controller["failure"],"original_controller_errors":controller["errors"],
            "original_cli_returncode":controller["original_cli_returncode"],
            "original_cleanup_state":controller["final_observed_state"],
            "original_absence_claim":controller["container_not_found_after_owned_remove"],
            "original_guest_failure":None if guest is None else guest["failure"],
            "observed_run_namespaces":runs_present,"physical_namespace":inventory,
            "accepted":False,"publication_ready":False,"native_pair_count":0,"benchmark_arm_count":0,
            "qualification_count":0,"model_or_parity_evidence":False,
            "pixel_limit":"Observed active-row RGB hashes can be compared; this reader never independently recreates pixels.",
            "guest_package_limit":"Original source/plugin/library observations are image-bound records; disposed guest paths are not claimed as currently rehashed host files."}
        base["closed_late_original_cleanup"] = cleanup_facts(held,attempt,controller,Path(late_path),Path(cleanup_path))
        base["external_dispatch_source_limit"] = "The original observer was an inline WSL CPython tool script, not a saved prelaunch physical wrapper. Its retained launch/terminal/log/process joins are checked; no dispatch source descriptor is invented."
        base["original_CID_final_bytes"] = held.files[str(attempt/"controller/original.cid")][2]
        base["held_original_b1_planning_files"] = [
            dict(descriptor, actual_cold_epoch7=held.files[descriptor["path"]][1])
            for descriptor in plan["planning_files"]]
        complete = external["returncode"] == 0 and controller["original_execution_completed"] is True
        complete = complete and controller["failure"] is None and not controller["errors"]
        complete = complete and controller["original_cli_returncode"] == 0 and controller["elapsed_s"] <= 600
        complete = complete and guest is not None and guest["failure"] is None and guest["result"] is not None
        complete = complete and guest["runs_completed"] == 4 and guest["elapsed_s"] <= 600
        late = any(Path(row["path"]).name == "receipt-time-limit-failure.v1.json" for row in inventory)
        complete = complete and not late
        if not complete:
            require(not runs_present and guest is not None and guest["runs_completed"] == 0
                    and guest["result"] is None, "failed-setup scope differs; full/partial source-run audit needs further review")
            guest_events = [strict_json(line,LINE_MAX) for line in
                bounded_lines(held,attempt/"guest/metadata/events.jsonl")]
            require([row["event_seq"] for row in guest_events] == [1,2]
                    and [row["kind"] for row in guest_events] == ["registry_process_started","registry_process_terminal"]
                    and guest_events[1]["returncode"] == 0 and guest_events[1]["failures"] == [],
                    "original retained registry prelaunch stages")
            base.update(research_complete=False,disposition="retained_failed_prefix_only",
                decoder_timing_conclusion=None,full32_output_correctness=None,
                failure_scope="Original setup/run failed or was late/incomplete. No complete cohort or causal decoder conclusion is promoted.",
                CID_failure_observation_limit="Failure-time CID stat was not retained by this controller; the final CID bytes cannot prove its earlier size/mode or an exclusive cause.")
            base["original_guest_setup_stages"] = guest_events
            base["GI_failure_call_limit"] = "Gst.init(None) is an explicit None-bearing preflight candidate after successful registry refresh, not a proven failing frame; the original exception has no retained traceback. The earlier metadata probe exposed GI APIs without executing Gst.init."
            base["reviewer_self_critique"] = "The earlier source review correctly kept metadata separate from decoder success but still recommended Gst.init(None) without an actual initialization call or verified nullable signature in the packaged route. The first genuine setup exposed that untested boundary. Treat init(None) only as a candidate until an actual failing frame is captured. The controller's initial CID/NotFound logic also gave too much meaning to one transient publication observation; the repaired path must distinguish pending identity from malformed identity and settle after the original CLI terminal. No research findings exist from this zero-run attempt."
        held.check(rehash=True)
        base["actual_cold_file_epochs"] = held.observations()
        base["cold_elapsed_s"] = time.monotonic()-begun
        base["recorded_at"] = datetime.now(timezone.utc).isoformat()
        return base
    finally:
        held.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root",required=True)
    parser.add_argument("--attempt-dir",required=True)
    parser.add_argument("--external-terminal",required=True)
    parser.add_argument("--late-observation",required=True)
    parser.add_argument("--cleanup-terminal",required=True)
    parser.add_argument("--report",required=True)
    args = parser.parse_args()
    report = Path(args.report)
    require(report.is_absolute() and not report.exists(), "new exclusive cold report required")
    value = audit(args.project_root,args.attempt_dir,args.external_terminal,args.late_observation,args.cleanup_terminal)
    value["sha256"] = hashlib.sha256(canonical(value)).hexdigest()
    raw = json.dumps(value,indent=2,sort_keys=True,ensure_ascii=True,allow_nan=False).encode("ascii")+b"\n"
    require(len(raw) <= 2*1024*1024, "cold report2MiB cap")
    with report.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    print(json.dumps({"report":str(report),"size_bytes":len(raw),"sha256":hashlib.sha256(raw).hexdigest(),
                      "research_complete":value["research_complete"]},sort_keys=True))
    return 0 if value["research_complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
