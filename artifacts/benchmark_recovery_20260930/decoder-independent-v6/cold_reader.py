"""Independent, nonpromoting cold replay of closed V6 decoder evidence.

Only stdlib is imported. Git reads establish reviewed source identity; no
producer, GI, image query, source process, pixel decoder or model is executed.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import selectors
import signal
import stat
import struct
import subprocess
import time

PLANNING = '3aa35c3b2eedc05d22cf16ba37d470143d080f6b'
OBSERVER_PLANNING = '684ea836a27fa002bc231117fbe445d0ec5579ab'
OWNER_CORE = frozenset(('pid','ppid','starttime_ticks','uid','gid','boot_id'))
HOST_INTERPRETER = '/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python'
IMAGE = 'sha256:70696f057232acd382f60beaaf12cd9279b317b0ba9a7ade29f0b955ce90481a'
DAEMON = 'aa8f3d33-e1dc-4ed2-ad06-488b46b332d0'
ENGINE_SHA = 'a429e235ef670ea83357a5c8c7451f0a69d485a6fee49f9032fd938a0ab4969d'
LEDGER_SHA = '8e99036f2d9e2e21ccf27b9d7f92989b22b7d9d9e7f7b7923e99b9b390fe2654'
MEDIA_OBSERVATION = {'size_bytes':3430,'sha256':'1c0be813ac9c62e34a8a633cc566603e8af203ddfcffd4f76cb0d4f4eef843cf'}
CUSTODY = {'size_bytes':38235,'sha256':'036805ad328ddc6c63377c942f86bf3e26a0bf6de2a83847c4bc9801d5d8d334'}
PROJECTION = ('{"Id":{{json .Id}},"Name":{{json .Name}},"Image":{{json .Image}},'
    '"Created":{{json .Created}},"Running":{{json .State.Running}},'
    '"OOMKilled":{{json .State.OOMKilled}},"ExitCode":{{json .State.ExitCode}},'
    '"Pid":{{json .State.Pid}},"StartedAt":{{json .State.StartedAt}},'
    '"FinishedAt":{{json .State.FinishedAt}},'
    '"Operation":{{json (index .Config.Labels "vast.operational-custody")}}}')
ORDER = (('front_gate', 'default'), ('front_gate', 'zero'),
         ('underbody', 'zero'), ('underbody', 'default'))
HEADER = struct.Struct('>8sHHQQQQQQIIIQ')
MISSING = (1 << 64) - 1
RAW_MAX, PAYLOAD_MAX = 128 * 1048576, 64 * 1048576
DOC_MAX, LINE_MAX, CHANNEL_MAX = 1048576, 16384, 1048576
TOTAL_MAX, REPORT_MAX = 4 * 256 * 1048576 + 32 * 1048576, 2 * 1048576
RUNTIME = 'artifacts/benchmark_recovery_20260930/decoder-research-implementation-v6'
OBSERVER = 'artifacts/benchmark_recovery_20260930/decoder-independent-v6/cold_reader.py'
PLANNING_PATHS = {
    'reviewed-proposal.md': 'proposal.md', 'reviewed-design.md': 'design.md',
    'reviewed-tasks.md': 'tasks.md',
    'reviewed-delta-spec.md': 'specs/benchmark-launch-preparation/spec.md'}
RUN_LEAVES = {'events.jsonl', 'run-started.v1.json', 'startup-completed.v1.json',
    'source-admission.raw', 'source-status.raw', 'source-ack.raw', 'source-control.raw',
    'source-transport.raw', 'source.stdout', 'source.stderr', 'source-transport-eof.v1.json',
    'decoder-drain-completed.v1.json', 'observations.v1.json', 'terminal.v1.json'}
PIPELINE = ('appsrc name=source is-live=true format=time do-timestamp=false block=true '
    'max-buffers=1 max-bytes=0 max-time=0 leaky-type=none '
    'caps="video/x-h264,stream-format=byte-stream,alignment=au" ! '
    'h264parse ! video/x-h264,stream-format=byte-stream,alignment=au ! '
    'identity name=ingress ! nvh264dec name=decoder ! videoconvert ! '
    'video/x-raw,format=RGB ! appsink name=output sync=false async=false drop=false '
    'max-buffers=1 emit-signals=false')
EVENT_FIELDS = frozenset(('protocol_version', 'source_process_id', 'sequence', 'run_id',
    'dataset_id', 'stream_id', 'admission_id', 'input_frame_key', 'source_sha256',
    'source_cycle', 'access_unit_pts_ns', 'payload_sha256', 'payload_size_bytes',
    'schedule_offset_ns', 'admission_timestamp_ms', 'event_provenance'))


class Refusal(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise Refusal(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=True, allow_nan=False).encode('ascii')


def strict_json(raw, maximum=DOC_MAX, sealed=False):
    require(0 < len(raw) <= maximum, 'JSON byte limit')
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'duplicate JSON key')
            result[key] = value
        return result
    def nonfinite(value):
        raise Refusal('nonfinite JSON number')
    try:
        result = json.loads(raw, object_pairs_hook=pairs, parse_constant=nonfinite)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise Refusal('invalid bounded JSON') from error
    require(type(result) is dict, 'JSON object required')
    if sealed:
        body = dict(result)
        digest = body.pop('sha256', None)
        require(digest == hashlib.sha256(canonical(body)).hexdigest(), 'document self seal')
    return result


def epoch(info):
    return [info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns]


def nonpromoting(value):
    require(value.get('accepted') is False and value.get('publication_ready', False) is False,
            'artifact promotes acceptance')
    for key in ('native_pair_count', 'benchmark_arm_count', 'qualification_count'):
        require(type(value.get(key, 0)) is int and value.get(key, 0) == 0,
                'nonzero or invalid research authority count')
    require(value.get('model_or_parity_evidence', False) is False, 'model/parity authority')


def validate_owner(value):
    require(type(value) is dict and type(value.get('pid')) is int and value['pid'] > 0
        and type(value.get('ppid')) is int and value['ppid'] >= 0
        and type(value.get('starttime_ticks')) is int and value['starttime_ticks'] > 0
        and value.get('uid') == value.get('gid') == 1000
        and re.fullmatch(r'[0-9a-f-]{36}', value.get('boot_id', '')), 'original owner facts')


def validate_external_owner(value, child=False):
    validate_owner(value)
    require(set(value) == OWNER_CORE | {'process_group_id','session_id'}
        and all(type(value[key]) is int and value[key] > 0 for key in ('process_group_id','session_id'))
        and type(value['uid']) is type(value['gid']) is int, 'external eight-field owner facts')
    require(not child or value['pid'] == value['process_group_id'] == value['session_id'],
        'external original child session containment')


def timestamp_ns(value):
    match = re.fullmatch(r'(.*)\.(\d{1,9})Z', value)
    require(match is not None, 'daemon timestamp')
    return int(datetime.fromisoformat(match[1]).replace(tzinfo=timezone.utc).timestamp()) * 10**9 + int(match[2].ljust(9, '0'))


def exact_absence(row, stdout, stderr, identifier):
    return (type(row['returncode']) is int and row['returncode'] == 1
        and stdout in (b'', b'\n') and stderr in (
            f'Error: No such container: {identifier}\n'.encode(),
            f'Error response from daemon: No such container: {identifier}\n'.encode()))


class Held:
    """One finite owner for real leaf/ancestor FDs and namespace observations."""
    def __init__(self, root, deadline):
        self.root, self.deadline = Path(root), deadline
        self.files, self.directories, self.names = {}, {}, {}
        self.close_errors = []
        require(self.root.is_absolute() and self.root.resolve(strict=True) == self.root, 'attempt alias')
        try:
            self.pin_directory(self.root)
        except BaseException:
            self.close()
            raise

    def clock(self):
        require(time.monotonic() < self.deadline, 'cold120s limit')

    def pin_directory(self, path):
        for parent in (Path(path), *Path(path).parents):
            key = str(parent)
            if key in self.directories:
                continue
            self.clock()
            require(parent.resolve(strict=True) == parent, 'ancestor alias')
            require(len(self.directories) < 128, 'directory FD128 limit')
            fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            self.directories[key] = (fd, None)
            info = os.fstat(fd)
            expected = [info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid]
            self.directories[key] = (fd, expected)
            require(stat.S_ISDIR(info.st_mode), 'ancestor type')

    def digest(self, fd, size):
        h, offset = hashlib.sha256(), 0
        while offset < size:
            self.clock()
            block = os.pread(fd, min(65536, size-offset), offset)
            require(bool(block), 'short held file')
            h.update(block); offset += len(block)
        require(not os.pread(fd, 1, size), 'held file grew')
        return h.hexdigest()

    def pin(self, path, descriptor=None, maximum=RAW_MAX, under_root=True):
        path = Path(path); key = str(path)
        self.clock()
        require(path.is_absolute() and path.resolve(strict=True) == path, 'leaf/ancestor alias')
        require(not under_root or path.is_relative_to(self.root), 'foreign output')
        if key not in self.files:
            require(len(self.files) < 256, 'file FD256 limit')
            self.pin_directory(path.parent)
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            self.files[key] = (fd, None, None)
            info = os.fstat(fd)
            require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and 0 <= info.st_size <= maximum,
                    'single-link regular file/cap')
            before = epoch(info)
            actual = {'path': key, 'size_bytes': info.st_size, 'sha256': self.digest(fd, info.st_size)}
            require(before == epoch(os.fstat(fd)) == epoch(path.lstat()), 'leaf changed during hash')
            self.files[key] = (fd, before, actual)
        fd, before, actual = self.files[key]
        require(before is not None and before[4] <= maximum, 'cached physical cap')
        if descriptor is not None:
            require(type(descriptor) is dict and set(descriptor) == {'path', 'size_bytes', 'sha256'}
                    and descriptor == actual, 'physical descriptor/path/bytes mismatch')
        self.check(False)
        return dict(actual)

    def read(self, path, maximum=DOC_MAX, under_root=True):
        path = Path(path); self.pin(path, maximum=maximum, under_root=under_root)
        fd, before, _ = self.files[str(path)]
        chunks=[];offset=0
        while offset<before[4]:
            self.clock();block=os.pread(fd,min(65536,before[4]-offset),offset)
            require(bool(block),'short held read');chunks.append(block);offset+=len(block)
        raw=b''.join(chunks)
        require(len(raw) == before[4], 'short held read')
        self.check(False)
        return raw

    def document(self, path, kind=None, under_root=True):
        value = strict_json(self.read(path, under_root=under_root), sealed=True)
        require(kind is None or value.get('artifact_kind') == kind, 'document kind')
        return value

    def members(self, path):
        path = Path(path); self.pin_directory(path)
        result = frozenset(p.name for p in path.iterdir())
        require(len(result) <= 128, 'namespace leaf count')
        require(str(path) not in self.names or self.names[str(path)] == result, 'namespace drift')
        self.names[str(path)] = result
        return result

    def check(self, rehash):
        self.clock()
        for path, (fd, before, descriptor) in self.files.items():
            require(before is not None and before == epoch(os.fstat(fd)) == epoch(Path(path).lstat()), 'held leaf/epoch drift')
            if rehash:
                require(self.digest(fd, before[4]) == descriptor['sha256']
                        and before == epoch(os.fstat(fd)), 'held bytes drift')
        for path, (fd, expected) in self.directories.items():
            require(expected is not None, 'incomplete ancestor acquisition')
            for info in (os.fstat(fd), Path(path).lstat()):
                require([info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid] == expected, 'ancestor replaced')
        for path, expected in self.names.items():
            require(frozenset(p.name for p in Path(path).iterdir()) == expected, 'closed namespace changed')

    def observations(self):
        return [{'descriptor': row[2], 'actual_cold_epoch7': row[1]} for row in self.files.values() if row[1] is not None]

    def close(self):
        for collection in (self.files, self.directories):
            for key, row in list(collection.items()):
                try:
                    os.close(row[0])
                except OSError as error:
                    self.close_errors.append({'path': key, 'type': type(error).__name__, 'errno': error.errno})
                finally:
                    del collection[key]
        return list(self.close_errors)


def bounded_lines(held, path, maximum_bytes=CHANNEL_MAX, maximum_lines=512):
    raw = held.read(path, maximum_bytes)
    rows = raw.splitlines(keepends=True)
    require(len(rows) <= maximum_lines and all(r.endswith(b'\n') and len(r) <= LINE_MAX for r in rows), 'line/count/trailing prefix limit')
    return rows


class Replay:
    def __init__(self, project, repository, attempt, mode, source_commit, planning_commit=PLANNING,
                 *, observer_repository=None, observer_commit=None):
        require(mode in ('metadata-only', 'research'), 'explicit mode')
        require(re.fullmatch(r'[0-9a-f]{40}', source_commit) is not None, 'source commit')
        require((observer_repository is None) == (observer_commit is None), 'paired observer repository/commit')
        self.project, self.repository, self.attempt = map(Path, (project, repository, attempt))
        self.mode, self.source_commit, self.planning_commit = mode, source_commit, planning_commit
        self.observer_repository = self.repository if observer_repository is None else Path(observer_repository)
        self.observer_commit = source_commit if observer_commit is None else observer_commit
        self.observer_binding = {'planning_commit':OBSERVER_PLANNING,'source_commit':self.observer_commit,
            'review_repository_root':str(self.observer_repository)}
        self.guest_terminal_join = None
        self.require = require
        self.h = Held(self.attempt, time.monotonic()+120)
        self.git_commands = []

    def doc(self, path, kind):
        value = self.h.document(path, kind, under_root=Path(path).is_relative_to(self.attempt))
        nonpromoting(value)
        return value

    def output(self, descriptor):
        original = Path(descriptor['path'])
        require(original.is_relative_to('/opt/vast/output'), 'foreign guest path')
        path = self.attempt/'guest'/original.relative_to('/opt/vast/output')
        self.h.pin(path, dict(descriptor, path=str(path)))
        return path

    def journal(self, path):
        rows = [strict_json(r, LINE_MAX) for r in bounded_lines(self.h, path, 512*LINE_MAX)]
        require([r['event_seq'] for r in rows] == list(range(1, len(rows)+1)), 'journal sequence')
        require(all(type(r['observed_monotonic_ns']) is int and r['observed_monotonic_ns'] > 0 for r in rows), 'journal clock')
        return rows

    def one(self, rows, kind):
        selected = [r for r in rows if r['kind'] == kind]
        require(len(selected) == 1, 'one journal event: '+kind)
        return selected[0]

    def match_descriptor(self, descriptor, expected=None, maximum=RAW_MAX):
        self.h.pin(Path(descriptor['path']), descriptor, maximum=maximum, under_root=False)
        require(expected is None or descriptor['sha256'] == expected, 'independent source hash')


    def caps(self, row):
        self.require(type(row["caps"]) is str and len(row["caps"].encode())<=4096
            and type(row["caps_features"]) is list and len(row["caps_features"])<=8
            and all(type(x) is str for x in row["caps_features"])
            and sum(len(x.encode()) for x in row["caps_features"])<=4096, "actual bounded caps/features")
        if "memory" in row:
            self.require(type(row["memory"]) is list and len(row["memory"])<=32
                and all(set(x)=={"system_memory","cuda_memory"} and all(type(v) is bool for v in x.values())
                        for x in row["memory"]), "actual bounded memory observations")


    def packets(self, directory, admissions, source, run):
        path = directory / "source-transport.raw"
        self.h.pin(path, maximum=RAW_MAX)
        fd, epoch, _ = self.h.files[str(path)]
        offset, records = 0, []
        def read(size):
            nonlocal offset
            self.require(offset + size <= epoch[4], "truncated original transport")
            raw = os.pread(fd, size, offset)
            self.require(len(raw) == size, "short original transport")
            offset += size
            return raw
        for sequence, declaration in enumerate(admissions, 1):
            self.require(type(declaration) is dict and set(declaration) == EVENT_FIELDS
                and type(declaration['protocol_version']) is int
                and all(type(declaration[field]) is int and 0 <= declaration[field] <= MISSING
                    for field in ('sequence','stream_id','source_cycle','access_unit_pts_ns',
                                  'payload_size_bytes','schedule_offset_ns','admission_timestamp_ms'))
                and all(type(declaration[field]) is str for field in EVENT_FIELDS-
                    {'protocol_version','sequence','stream_id','source_cycle','access_unit_pts_ns',
                     'payload_size_bytes','schedule_offset_ns','admission_timestamp_ms'}),
                'original admission types/u64')
            magic, version, flags, seq, cycle, aupts, pts, dts, duration, a, k, n, size = HEADER.unpack(read(80))
            self.require(magic == b"VASTAU01" and version == 1 and flags & ~1 == 0
                and seq == sequence and cycle == 0 and 0 < a <= 8192 and 0 < k <= 8192
                and n == 64 and 0 < size <= PAYLOAD_MAX, "original80B header limits/identity")
            admission, input_key, payload_sha = (read(x).decode("utf8") for x in (a, k, n))
            self.require(set(declaration) == EVENT_FIELDS and declaration["protocol_version"] == 1
                and declaration["event_provenance"] == "native_common_source_coordinator", "original admission fields")
            self.require(declaration["sequence"] == seq and declaration["source_cycle"] == cycle
                and declaration["access_unit_pts_ns"] == aupts and declaration["payload_size_bytes"] == size
                and declaration["payload_sha256"] == payload_sha and declaration["admission_id"] == admission
                and declaration["input_frame_key"] == input_key, "raw packet/admission join")
            self.require(declaration["run_id"] == run and declaration["dataset_id"] == source["dataset_id"]
                and declaration["stream_id"] == source["stream_id"]
                and declaration["source_sha256"] == source["media"]["sha256"], "original source identity")
            self.require(admission == f'{run}:{source["stream_id"]}:admission:{seq}'
                and input_key == f'{source["dataset_id"]}:{source["stream_id"]}:{source["media"]["sha256"]}:0:{aupts}'
                and pts == aupts * 600 and 999999600 <= duration < MISSING, "original text/PTS/cadence")
            digest = hashlib.sha256()
            remaining = size
            while remaining:
                self.require(time.monotonic() < self.h.deadline, "cold raw120s limit")
                chunk = read(min(65536, remaining))
                digest.update(chunk)
                remaining -= len(chunk)
            self.require(re.fullmatch(r"[0-9a-f]{64}", payload_sha) is not None
                and digest.hexdigest() == payload_sha, "full original AU payload hash")
            records.append(dict(sequence=seq, source_cycle=cycle, access_unit_pts_ns=aupts,
                transport_pts_ns=pts, access_unit_dts_ns=dts, duration_ns=duration,
                keyframe=bool(flags & 1), payload_size_bytes=size, payload_sha256=payload_sha))
        self.require(len(records) == 32 and offset == epoch[4] and offset <= RAW_MAX-80,
                     "exact32 transport/no trailing bytes/reserved raw cap")
        self.require(len({r["transport_pts_ns"] for r in records}) == 32, "unique original PTS")
        expected = 0
        for declaration, packet in zip(admissions, records):
            self.require(declaration["schedule_offset_ns"] == expected, "duration-driven schedule")
            expected += packet["duration_ns"]
        return records, offset


    def run(self, index, role, setting, source, guest_owner):
        d = self.attempt / "guest" / f"run-{index:02d}-{role}-{setting}"
        self.require({p.name for p in d.iterdir()} == RUN_LEAVES, "complete fixed run namespace")
        terminal = self.doc(d/"terminal.v1.json", "vast_decoder_research_run_terminal_v1")
        self.require(terminal["run"] == index and terminal["clip"] == role and terminal["setting"] == setting
            and terminal["controller"] == guest_owner and terminal["run_successful"] is True
            and terminal["source_returncode"] == 0 and terminal["errors"] == terminal["cleanup_errors"] == []
            and 0 <= terminal["elapsed_s"] <= 120, "original complete bounded run")
        original_leaves = [self.output(row) for row in terminal["closed_original_leaves"]]
        self.require(all(p.parent==d for p in original_leaves),"operation-scoped original run leaf")
        leaves = {p.name for p in original_leaves}
        self.require(leaves == RUN_LEAVES-{"terminal.v1.json"}
            and len(leaves) == len(terminal["closed_original_leaves"]), "run closed original leaves")
        observations_path = self.output(terminal["observations"])
        self.require(observations_path==d/"observations.v1.json","original run observations path")
        observations = self.doc(observations_path, "vast_decoder_research_observations_v1")
        events = self.journal(d/"events.jsonl")
        launched = self.one(events, "source_process_started")
        validate_owner(launched["child"])
        self.require(launched["controller"] == guest_owner and launched["child"]["ppid"] == guest_owner["pid"],
                     "actual source PID parent")
        self.require(launched["source_binary"] == self.plan["source_binary"]
            and launched["media"]["sha256"] == source["media"]["sha256"]
            and launched["media"]["size_bytes"] == source["media"]["size_bytes"], "actual source ELF/media")
        params = source["stock_source_parameters"]
        argv = launched["argv"]
        self.require(argv[:2] == [self.plan["source_binary"]["path"], "--source-path"]
            and re.fullmatch(r"/proc/self/fd/[0-9]+", argv[2]) is not None
            and argv[3:] == ["--dataset-id",source["dataset_id"],"--source-sha256",source["media"]["sha256"],
                "--checkpoint-container",params["source_container"],"--checkpoint-codec",params["source_codec"],
                "--source-duration-ns",str(params["source_duration_ns"]),"--playback-timestamp-scale","600",
                "--source-replay","continuous","--logical-stream-id",str(source["stream_id"])], "exact original source command")
        worker, run = f"research-source-{role}-{index:02d}", f"research-decoder-{index:02d}"
        env = launched["environment"]
        expected_env = {"VAST_CHECKPOINT_WORKER_ID":worker,"VAST_CHECKPOINT_RUN_ID":run,
            "VAST_CHECKPOINT_DATASET_ID":source["dataset_id"],"VAST_CHECKPOINT_SOURCE_SHA256":source["media"]["sha256"],
            "VAST_CHECKPOINT_STREAM_ID":str(source["stream_id"]),"VAST_CHECKPOINT_SOURCE_CONTAINER":params["source_container"],
            "VAST_CHECKPOINT_SOURCE_CODEC":params["source_codec"],"VAST_CHECKPOINT_SOURCE_DURATION_NS":str(params["source_duration_ns"]),
            "VAST_CHECKPOINT_PLAYBACK_TIMESTAMP_SCALE":"600","VAST_CHECKPOINT_SOURCE_REPLAY":"continuous",
            "VAST_CHECKPOINT_ADMISSION_MODE":"native_common_source_coordinator",
            "GST_REGISTRY":f"/tmp/decoder-research-source-{index}.registry.bin","GST_REGISTRY_UPDATE":"no"}
        self.require(all(env.get(k) == v for k,v in expected_env.items()), "original source environment")
        for key in ("ADMISSION_EVENT_FD","ADMISSION_ACK_FD","CONTROL_FD","STATUS_FD"):
            self.require(re.fullmatch(r"[0-9]+",env.get("VAST_CHECKPOINT_"+key,"")) is not None, "actual source pipe FD")
        consumers = strict_json(env["VAST_CHECKPOINT_ADMISSION_CONSUMER_FDS_JSON"].encode())
        self.require(set(consumers) == {"research-decoder"} and type(consumers["research-decoder"]) is int, "one actual AU pipe")
        control = list(bounded_lines(self.h,d/"source-control.raw"))
        self.require(len(control) == 2, "one START/STOP")
        match = re.fullmatch(rb"1 START (\d+) (\d+) (\d+) (\d+)\n",control[0])
        self.require(match is not None, "original START shape")
        future, start, end, drain = map(int,match.groups())
        self.require(end-start == 31500 and drain-end == 10000 and control[1] == f"1 STOP {end}\n".encode(), "frozen original windows")
        clock = self.one(events,"clock_domains")
        self.require(future == clock["guest_monotonic_ns"]+2000000000
            and start == (clock["guest_realtime_ns"]+2000000000)//1000000
            and clock["secondary_admission_to_output_omitted"] is True, "original guest clock domains")
        statuses = list(bounded_lines(self.h,d/"source-status.raw"))
        status_events = [r for r in events if r["kind"] == "source_status"]
        expected_status = ["READY","STARTED","ADMISSION_STOPPED","DRAINED"]
        self.require([r["status"] for r in status_events] == expected_status
            and statuses == [f'1 {r["status"]} {worker} {r["original_timestamp"]}\n'.encode()
                             for r in status_events], "actual source lifecycle")
        admissions = [strict_json(x) for x in bounded_lines(self.h,d/"source-admission.raw",maximum_lines=32)]
        self.require(len(admissions) == 32 and all(r["source_process_id"] == worker
            and start <= r["admission_timestamp_ms"] < end for r in admissions), "actual admitted window32")
        acks = list(bounded_lines(self.h,d/"source-ack.raw",maximum_lines=32))
        self.require(acks == [f"1 ACK {n}\n".encode() for n in range(1,33)], "exact original ACK1..32")
        records, raw_bytes = self.packets(d,admissions,source,run)
        declarations = [r for r in events if r["kind"] == "admission_declaration"]
        start_intent = self.one(events,'start_intent')
        loaded = self.one(events,'actual_source_loaded_libraries')
        self.require(status_events[0]['event_seq'] < loaded['event_seq'] < start_intent['event_seq']
            < status_events[1]['event_seq'] and declarations
            and start_intent['event_seq'] < declarations[0]['event_seq'],
            'source START enabling causality')
        intents = [r for r in events if r["kind"] == "ack_intent"]
        sent = [r for r in events if r["kind"] == "ack_sent"]
        valid = [r for r in events if r["kind"] == "transport_validated"]
        self.require(len(declarations) == len(intents) == len(sent) == len(valid) == 32, "complete original causal journal")
        for n,(declaration,intent,completed,packet) in enumerate(zip(declarations,intents,sent,valid)):
            self.require(declaration["original"] == admissions[n] and intent["raw_ascii"].encode() == acks[n]
                and completed["raw_ascii"].encode() == acks[n]
                and declaration["event_seq"] < intent["event_seq"] < completed["event_seq"]
                and intent["event_seq"] < packet["event_seq"]
                and (n == 0 or valid[n-1]["event_seq"] < declaration["event_seq"]), "event/ACK enabling causality")
            self.require({k:packet[k] for k in records[n]} == records[n], "raw transport/journal equality")
        # ACK_sent is logged after write; transport_validated may appear first.
        for kind,raw in (("start",control[0]),("stop",control[1])):
            intent,completed = self.one(events,kind+"_intent"),self.one(events,kind+"_sent")
            self.require(intent["raw_ascii"].encode() == completed["raw_ascii"].encode() == raw
                and intent["event_seq"] < completed["event_seq"], "original control journal")
        created = self.one(events,"pipeline_created")
        self.require(created["text"] == PIPELINE and created["setting"] == setting
            and created["property_default_readback"] == -1 and created["property_readback"] == (0 if setting=="zero" else -1)
            and created["default_was_unset"] == (setting=="default"), "only reviewed decoder property differs")
        expected_pts = [r["transport_pts_ns"] for r in records]
        sinks, sources, rgb = [[r for r in events if r["kind"] == kind]
                             for kind in ("decoder_sink","decoder_src","rgb_output")]
        for rows in (sinks,sources,rgb):
            self.require(len(rows) == 32 and Counter(r["pts"] for r in rows) == Counter(expected_pts), "complete decoder/RGB PTS multiset")
            for row in rows:
                self.caps(row)
        sink_eos = self.one(events,"decoder_sink_eos_observed")["observed_monotonic_ns"]
        self.one(events,"decoder_src_eos_observed")
        self.one(events,"pipeline_bus_eos")
        self.one(events,"appsrc_eos_requested")
        inputs = {r["pts"]:r for r in sinks}; outputs = {r["pts"]:r for r in sources}
        timings=[]
        for n,pts in enumerate(expected_pts,1):
            enter,exit = inputs[pts]["observed_monotonic_ns"],outputs[pts]["observed_monotonic_ns"]
            self.require(exit >= enter, "decoder same-clock residence ordering")
            timings.append(dict(original_sequence=n,pts=pts,decoder_sink_ns=enter,decoder_src_ns=exit,
                residence_ns=exit-enter,cohort="startup" if n<=8 else "central" if n<=24 else "tail",
                after_actual_decoder_sink_eos=exit>=sink_eos))
        rgb_rows = [{k:v for k,v in row.items() if k not in {"kind","event_seq","observed_monotonic_ns"}} for row in rgb]
        geometry=source["encoded_geometry"]
        for n,row in enumerate(rgb_rows,1):
            self.require(row["output_ordinal"] == n and row["format"] == "RGB"
                and row["width"] == geometry["width"] and row["height"] == geometry["height"]
                and row["stride"] >= row["width"]*3 and row["offset"] >= 0
                and row["offset"]+(row["height"]-1)*row["stride"]+row["width"]*3 <= PAYLOAD_MAX
                and re.fullmatch(r"[0-9a-f]{64}",row["pixel_sha256"]) is not None
                and row["hold_hash_ns"] == row["sample_hold_end_ns"]-row["sample_hold_start_ns"] >= 0,
                "actual observed RGB geometry/hash/hold")
        submissions = [r for r in events if r["kind"] == "appsrc_submission"]
        self.require(len(submissions)==32 and [r["sequence"] for r in submissions]==list(range(1,33)), "original FIFO appsrc32")
        for packet,row in zip(records,submissions):
            self.require(row["pts"] == packet["transport_pts_ns"] and 0 <= row["fifo_depth"] <= 32
                and row["blocking_ns"] == row["push_return_monotonic_ns"]-row["observed_monotonic_ns"] >= 0, "original appsrc timing")
        started=self.doc(d/"run-started.v1.json","vast_decoder_research_run_started_v1")
        startup=self.doc(d/"startup-completed.v1.json","vast_decoder_research_startup_v1")
        eof=self.doc(d/"source-transport-eof.v1.json","vast_decoder_research_source_transport_eof_v1")
        drained=self.doc(d/"decoder-drain-completed.v1.json","vast_decoder_research_decoder_drain_v1")
        self.require(started["run"]==startup["run"]==eof["run"]==drained["run"]==index
            and started["controller"]==guest_owner and 0<=startup["elapsed_s"]<=45
            and 0<=drained["elapsed_from_source_eof_s"]<=10
            and drained["actual_decoder_sink_eos_ns"]==sink_eos
            and abs(drained["source_eof_monotonic_ns"]-eof["observed_monotonic_ns"])<=2
            and 0<=drained["completed_monotonic_ns"]-eof["observed_monotonic_ns"]<=10000000000,
            "original startup/actualEOF/drain bounds")
        self.require(self.one(events,"source_transport_eof")["observed_monotonic_ns"]==eof["observed_monotonic_ns"], "actual EOF journal")
        sufficient=all(not r["after_actual_decoder_sink_eos"] for r in timings if r["cohort"]=="central")
        actual=dict(clip=role,setting=setting,outputs=rgb_rows,timings=timings,packets=records,
            input_pts_decode_order=expected_pts,actual_decoder_sink_eos_ns=sink_eos,
            central_steady_state_sufficient=sufficient,actual_admissions=32,actual_packets=32,
            raw_bytes=raw_bytes,maximum_actual_au_payload_bytes=max(r["payload_size_bytes"] for r in records),
            pipeline=PIPELINE,property_default_readback=-1,property_readback=0 if setting=="zero" else -1)
        self.require(all(observations.get(k)==v for k,v in actual.items()), "independent run recomputation differs from guest report")
        return actual,started

    def namespace(self):
        require(self.h.members(self.attempt) == {'controller', 'guest'}, 'attempt namespace')
        require(self.h.members(self.attempt/'guest') <= {'metadata', *[
            f'run-{i:02d}-{role}-{setting}' for i, (role, setting) in enumerate(ORDER, 1)]}, 'guest namespace')
        inventory = []
        for directory in (self.attempt/'controller', *sorted((self.attempt/'guest').iterdir())):
            names = self.h.members(directory)
            cap = 16*1048576 if directory.name in ('controller', 'metadata') else 256*1048576
            require(len(names) <= (128 if directory.name == 'controller' else 32), 'namespace count')
            rows = [self.h.pin(directory/name, maximum=RAW_MAX) for name in sorted(names)]
            require(sum(row['size_bytes'] for row in rows) <= cap, 'namespace byte cap')
            inventory.extend(rows)
        require(sum(row['size_bytes'] for row in inventory) <= TOTAL_MAX, 'total namespace cap')
        return inventory

    def git(self, *arguments, cap=DOC_MAX, allow_one=False, repository=None):
        """Bound one read-only original Git child, including both pipe EOFs."""
        self.h.clock()
        executable = Path('/usr/bin/git')
        self.h.pin(executable, maximum=64*1048576, under_root=False)
        fd = self.h.files[str(executable)][0]
        argv = [str(executable), '--no-replace-objects', '-c', 'core.longpaths=true',
                '-C', str(self.repository if repository is None else repository), *arguments]
        deadline = min(self.h.deadline, time.monotonic()+5)
        process = selector = None
        chunks = [bytearray(), bytearray()]
        eof = [False, False]; close_errors = []; primary = None
        observation = {'argv': argv, 'started_monotonic_ns': time.monotonic_ns(),
                       'pid': None, 'owner': None, 'owner_unavailable': None}
        try:
            process = subprocess.Popen(argv, executable=f'/proc/self/fd/{fd}', pass_fds=(fd,),
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                start_new_session=True, env=dict(os.environ, GIT_NO_LAZY_FETCH='1', GIT_OPTIONAL_LOCKS='0'))
            observation['pid'] = process.pid
            try:
                raw = Path(f'/proc/{process.pid}/stat').read_bytes()
                require(len(raw) <= LINE_MAX, 'Git owner stat cap')
                suffix = raw.rsplit(b')', 1)[1].split()
                observation['owner'] = {'pid': process.pid, 'ppid': int(suffix[1]),
                    'process_group_id': int(suffix[2]), 'starttime_ticks': int(suffix[19])}
            except (OSError, ValueError, IndexError) as error:
                observation['owner_unavailable'] = type(error).__name__
            selector = selectors.DefaultSelector()
            for index, pipe in enumerate((process.stdout, process.stderr)):
                os.set_blocking(pipe.fileno(), False); selector.register(pipe, selectors.EVENT_READ, index)
            while selector.get_map():
                require(time.monotonic() < deadline, 'owned Git5s limit')
                for key, _ in selector.select(min(.05, deadline-time.monotonic())):
                    block = os.read(key.fd, 65536); index = key.data
                    if not block:
                        eof[index] = True; selector.unregister(key.fileobj)
                    else:
                        require(len(chunks[index])+len(block) <= (cap if index == 0 else 65536), 'Git stream cap')
                        chunks[index].extend(block)
            process.wait(timeout=max(.001, deadline-time.monotonic()))
            require(process.returncode == 0 or (allow_one and process.returncode == 1), 'Git command failed')
            require(not chunks[1], 'Git stderr not empty')
        except BaseException as error:
            primary = error
        finally:
            if process is not None and process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=max(.001, deadline-time.monotonic()))
                except (OSError, subprocess.TimeoutExpired) as error:
                    close_errors.append(type(error).__name__)
            for item in (selector, None if process is None else process.stdout,
                         None if process is None else process.stderr):
                if item is not None:
                    try: item.close()
                    except BaseException as error: close_errors.append(type(error).__name__)
            observation.update(returncode=None if process is None else process.returncode,
                eof=eof, close_errors=close_errors, finished_monotonic_ns=time.monotonic_ns(),
                stdout_size=len(chunks[0]), stdout_sha256=hashlib.sha256(chunks[0]).hexdigest(),
                stderr_size=len(chunks[1]), stderr_sha256=hashlib.sha256(chunks[1]).hexdigest(),
                first_failure=None if primary is None else type(primary).__name__+': '+str(primary))
            self.git_commands.append(observation)
        if primary is not None: raise primary
        require(not close_errors and all(eof) and time.monotonic() < deadline, 'Git final close/deadline')
        self.h.check(False)
        return bytes(chunks[0])

    def source_bindings(self, plan):
        """Producer declarations are checked against raw P/S objects and held bytes."""
        require(self.repository.is_absolute() and self.repository.resolve(strict=True) == self.repository,
                'review repository alias')
        require(self.git('rev-parse', '--show-toplevel').decode().strip() == str(self.repository), 'Git repository root')
        for commit in (self.planning_commit, self.source_commit):
            require(re.fullmatch(r'[0-9a-f]{40}', commit) is not None, 'exact commit shape')
            require(self.git('rev-parse', '--verify', commit+'^{commit}').decode().strip() == commit, 'Git commit identity')
        head = self.git('rev-parse', 'HEAD').decode().strip()
        head_path=Path(self.git('rev-parse','--git-path','HEAD').decode().strip())
        if not head_path.is_absolute():head_path=self.repository/head_path
        self.h.pin(head_path,maximum=4096,under_root=False)
        self.git('merge-base', '--is-ancestor', self.planning_commit, self.source_commit)
        self.git('merge-base', '--is-ancestor', self.source_commit, head)
        expected = {'planning_commit': self.planning_commit, 'source_commit': self.source_commit,
            'current_checkout_commit': head, 'review_repository_root': str(self.repository),
            'project_root': str(self.project), 'mode': self.mode}
        require(all(plan.get(key) == value for key, value in expected.items()), 'independent P/S/H/root/mode join')
        require(plan['image_id'] == IMAGE and plan['fixed_order'] == [list(x) for x in ORDER], 'image/fixed order')
        require(type(plan['guest_prelaunch_budget_s']) in (int, float)
            and math.isfinite(plan['guest_prelaunch_budget_s']) and 0 < plan['guest_prelaunch_budget_s'] <= 120,
            'remaining shared prelaunch time')
        require(len(plan['code']) == 3 and {Path(r['path']).name for r in plan['code']} ==
                {'controller.py', 'guest_consumer.py', 'research_protocol.py'}, 'three runtime descriptors')
        for row in plan['code']:
            path = self.repository/RUNTIME/Path(row['path']).name
            require(Path(row['path']) == path, 'runtime Git path')
            data = self.git('cat-file', 'blob', self.source_commit+':'+path.relative_to(self.repository).as_posix())
            require(row == {'path':str(path), 'size_bytes':len(data), 'sha256':hashlib.sha256(data).hexdigest()}, 'S runtime blob')
            self.match_descriptor(row)
        observer_raw = self.git('cat-file', 'blob', self.source_commit+':'+OBSERVER)
        self.h.pin(self.repository/OBSERVER,{'path':str(self.repository/OBSERVER),'size_bytes':len(observer_raw),
            'sha256':hashlib.sha256(observer_raw).hexdigest()},under_root=False)
        require(len(plan['planning_files']) == 4, 'four P copies')
        names = set()
        for row in plan['planning_files']:
            name = Path(row['path']).name; require(name in PLANNING_PATHS and name not in names, 'P flat path/duplicate')
            names.add(name)
            git_path = 'openspec/changes/fix-decoder-preflight/'+PLANNING_PATHS[name]
            require(row['git_path'] == git_path and row['planning_commit'] == self.planning_commit
                and Path(row['path']) == self.attempt/'controller'/name, 'P copy source binding')
            raw = self.git('cat-file', 'blob', self.planning_commit+':'+git_path)
            require(row['git_blob_sha1'] == hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest(), 'P raw blob OID')
            descriptor = {k:row[k] for k in ('path', 'size_bytes', 'sha256')}
            self.match_descriptor(descriptor)
            require(self.h.read(Path(row['path'])) == raw, 'P raw copy mismatch')
        self.observer_source_bindings(self.h.files[str(self.repository/OBSERVER)][2])
        require(self.git('rev-parse', 'HEAD').decode().strip() == head, 'repository changed during cold Git reads')
        return expected

    def observer_source_bindings(self, original_observer):
        """C/P2 authority is independent of the original producer binding."""
        root = self.observer_repository
        require(root.is_absolute() and root.resolve(strict=True) == root, 'observer repository alias')
        require(self.git('rev-parse','--show-toplevel',repository=root).decode().strip() == str(root),
            'observer Git repository root')
        for commit in (OBSERVER_PLANNING,self.observer_commit):
            require(type(commit) is str and re.fullmatch('[0-9a-f]{40}',commit), 'observer exact commit shape')
            require(self.git('rev-parse','--verify',commit+'^{commit}',repository=root).decode().strip() == commit,
                'observer Git commit identity')
        head = self.git('rev-parse','HEAD',repository=root).decode().strip()
        head_path = Path(self.git('rev-parse','--git-path','HEAD',repository=root).decode().strip())
        if not head_path.is_absolute():head_path=root/head_path
        self.h.pin(head_path,maximum=4096,under_root=False)
        for before,after in ((self.planning_commit,OBSERVER_PLANNING),
                (OBSERVER_PLANNING,self.observer_commit),(self.source_commit,self.observer_commit),
                (self.observer_commit,head)):
            self.git('merge-base','--is-ancestor',before,after,repository=root)
        self.observer_binding.update(current_checkout_commit=head,original_observer=dict(original_observer))
        raw = self.git('cat-file','blob',self.observer_commit+':'+OBSERVER,repository=root)
        source = {'path':str(root/OBSERVER),'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
        self.match_descriptor(source,maximum=DOC_MAX)
        executed = Path(__file__).absolute()
        require(executed.resolve(strict=True) == executed, 'executed observer alias')
        actual = self.h.read(executed,DOC_MAX,under_root=False)
        require(raw == actual, 'executed observer bytes do not equal C')
        self.observer_binding.update(reviewed_observer=source,executed_observer=dict(self.h.files[str(executed)][2]))
        planning = []
        for relative in PLANNING_PATHS.values():
            path = 'openspec/changes/fix-decoder-preflight/'+relative
            data = self.git('cat-file','blob',OBSERVER_PLANNING+':'+path,repository=root)
            planning.append({'planning_commit':OBSERVER_PLANNING,'git_path':path,'size_bytes':len(data),
                'sha256':hashlib.sha256(data).hexdigest(),
                'git_blob_sha1':hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()})
        require(sum(row['size_bytes'] for row in planning) <= 4*DOC_MAX, 'four P2 raw blob cap')
        self.observer_binding['planning_files'] = planning
        require(self.git('rev-parse','HEAD',repository=root).decode().strip() == head,
            'observer repository changed during cold Git reads')

    def external(self, terminal_path, capture_sha, tool_record):
        directory = terminal_path.parent
        require(self.h.members(directory) == {'launch.v1.json', 'process-start.v1.json',
            'original.stdout', 'original.stderr', 'terminal.v1.json'}, 'closed external namespace')
        terminal = self.doc(terminal_path, 'vast_decoder_research_external_original_controller_terminal_v1')
        require(all(terminal.get(k) == v for k, v in self.binding.items()), 'external P/S/H/root/mode')
        require(terminal['external_capture_completed'] is True and terminal['original_controller_returncode'] == 0
            and terminal['timed_out'] is False and terminal['capture_exceeded'] == terminal['failures'] == []
            and terminal['containment'] is None and terminal['all_source_epochs_rechecked'] is True
            and 0 <= terminal['elapsed_s'] <= 600 and terminal['started_at_ns'] <= terminal['finished_at_ns'],
            'external original completion')
        require(terminal['log_eof'] == {'stdout': True, 'stderr': True}
            and terminal['close_errors'] == [] and terminal['all_streams_closed'] is True,
            'external final stream closure')
        require(terminal['signals'] == [] and terminal['container_cleanup_verified'] is None
            and terminal['container_oom_observed'] is None, 'external direct-child-only scope')
        require(terminal['provisional_until_owner_final_close'] is True, 'external terminal body scope')
        record = strict_json(self.h.read(tool_record,CHANNEL_MAX,under_root=False))
        calls = record['tool_calls']; require(type(calls) is list and 1 <= len(calls) <= 128, 'original capture tool call count')
        session = None; output=[]
        for index,call in enumerate(calls):
            result = call['result']; require(type(result) is dict and type(result['output']) is str, 'original tool result')
            token_count=result.get('original_token_count')
            require((token_count is None or type(token_count) is int and 0<=token_count<=call['arguments'].get('max_output_tokens',10000))
                and 'warning: truncated output' not in result['output'].lower()
                and 'tokens truncated' not in result['output'].lower(), 'tool output truncation')
            if index == 0:
                require(call['tool_name'] == 'exec_command', 'initial original exec tool')
            else:
                require(call['tool_name'] == 'write_stdin' and call['arguments']['session_id'] == session
                    and call['arguments'].get('chars','') == '', 'original capture session join/no input')
            require(index == len(calls)-1 or result.get('exit_code') is None, 'tool terminal before last chunk')
            if result.get('session_id') is not None:
                require(session is None or result['session_id'] == session, 'tool session changed')
                session = result['session_id']
            output.append(result['output'])
        require(calls[-1]['result']['exit_code'] == 0, 'original external final tool rc')
        joined = ''.join(output).encode('utf8'); require(len(joined) <= CHANNEL_MAX, 'original external console cap')
        # WSL's UTF16 warning may leave a NUL before the following UTF8 console.
        lines = [line.lstrip(b'\0').strip() for line in joined.splitlines() if line.lstrip(b'\0').strip().startswith(b'{')]
        require(len(lines) == 1, 'one original external post-close console')
        complete = strict_json(lines[0],LINE_MAX)
        require(complete['external_capture_completed'] is True and complete['late_terminal'] is None
            and complete['close_errors'] == [] and complete['receipt'] == self.h.files[str(terminal_path)][2], 'external post-close tool/receipt join')
        self.match_descriptor(terminal['launch'])
        launch = self.doc(Path(terminal['launch']['path']), 'vast_decoder_research_external_original_controller_launch_v1')
        started = self.doc(directory/'process-start.v1.json', 'vast_decoder_research_external_original_controller_started_v1')
        require(launch['argv'] == started['argv'] == terminal['argv']
            and launch['controller'] == started['controller'] == terminal['controller']
            and started['child'] == terminal['original_child'], 'external launch/owner join')
        validate_external_owner(terminal['controller'])
        validate_external_owner(terminal['original_child'],child=True)
        require(terminal['original_child']['ppid'] == terminal['controller']['pid'], 'external child parent')
        code = self.repository/RUNTIME/'controller.py'
        require(launch['argv'] == [HOST_INTERPRETER,
            '-I', '-B', str(code), '--project-root', str(self.project), '--review-repository-root', str(self.repository),
            '--source-commit', self.source_commit, '--mode', self.mode, '--output-dir', str(self.attempt)], 'external exact mode/roots argv')
        require(launch['sources'] == terminal['sources_before'] == terminal['sources_after'], 'external source epochs')
        require([r['descriptor'] for r in launch['sources']] == [*self.plan['code'],self.h.files[str(self.repository/OBSERVER)][2]], 'external exact runtime/observer source set')
        require(launch['interpreter']['descriptor']['path'] == launch['argv'][0]
            and terminal['dispatch_source'] == terminal['dispatch_source_after'] == launch['dispatch_source']
            and terminal['interpreter_after'] == launch['interpreter'], 'external helper/interpreter final custody')
        for row in terminal['sources_before']+[launch['dispatch_source'], launch['interpreter']]:
            self.match_descriptor(row['descriptor'])
            require(self.h.files[row['descriptor']['path']][1] == row['epoch'], 'external physical source epoch')
        require(launch['dispatch_source']['descriptor']['sha256'] == capture_sha, 'independently reviewed capture source')
        for role in ('stdout', 'stderr'):
            require(Path(terminal[role]['path']) == directory/('original.'+role), 'external log path')
            self.match_descriptor(terminal[role], maximum=CHANNEL_MAX)
        raw = self.h.read(Path(terminal['stdout']['path']), CHANNEL_MAX, under_root=False)
        console = strict_json(raw.strip(), LINE_MAX)
        require(console['successful'] is True and console['original_execution_completed'] is True
            and console['streams_closed'] is True and console['pins_closed'] is True and console['socket_closed'] is True
            and console['controller_close_errors'] == [] and console['failure'] is None
            and console['close_failure'] is None and console['close_failure_capture_error'] is None
            and console['receipt_time_limit_failure'] is None and console['mode']==self.mode
            and console['planning_commit']==self.planning_commit and console['source_commit']==self.source_commit,
            'post-close controller stdout is failed')
        self.h.pin(self.attempt/'controller/terminal.v1.json', console['receipt'])
        return terminal

    def controller(self, external):
        directory = self.attempt/'controller'
        require(not ({'controller-close-failure.v1.json','receipt-time-limit-failure.v1.json'} & self.h.members(directory)),
                'controller final close/late companion')
        value = self.doc(directory/'terminal.v1.json', 'vast_decoder_research_controller_terminal_v1')
        require(all(value.get(k) == v for k, v in self.binding.items()), 'controller P/S/H/root/mode')
        require(value['provisional_until_owner_final_close'] is True and value['operation_completed'] is True
            and value['original_execution_completed'] is True and value['failure'] is None
            and value['errors'] == [] and value['original_cli_returncode'] == 0 and value['oom_killed'] is False
            and value['container_not_found_after_owned_remove'] is True and 0 <= value['elapsed_s'] <= 600
            and 0 <= value['cleanup_elapsed_after_close_s'] <= 15
            and value['independent_cold_recomputed'] is False and value['research_conclusion_authorized'] is False,
            'controller body/clock/nonpromoting completion')
        require(value['research_complete'] is (self.mode == 'research'), 'mode-specific controller completion')
        require(value['metadata_preflight_completed'] is (self.mode == 'metadata-only') and
            value['runs_completed'] == (0 if self.mode == 'metadata-only' else 4)
            and (self.mode != 'metadata-only' or value['result'] is None), 'mode-specific controller result/count')
        validate_owner(value['controller'])
        require(set(value['controller']) == OWNER_CORE
            and type(value['controller']['uid']) is type(value['controller']['gid']) is int,
            'controller six-field owner facts')
        require(value['controller'] == {key:external['original_child'][key] for key in OWNER_CORE},
            'external/controller original identity')
        manifest_path = Path(value['closed_controller_leaves']['path'])
        self.h.pin(manifest_path, value['closed_controller_leaves'])
        manifest = self.doc(manifest_path, 'vast_decoder_research_closed_controller_leaves_v1')
        expected = self.h.members(directory)-{'terminal.v1.json', 'closed-controller-leaves.v1.json'}
        require(len(manifest['leaves']) == len(expected)
            and {Path(r['path']).name for r in manifest['leaves']} == expected, 'complete closed controller leaves')
        for row in manifest['leaves']:
            require(Path(row['path']).parent == directory, 'foreign controller manifest leaf')
            self.h.pin(Path(row['path']), row)
        reservation = self.doc(directory/'reservation.v1.json', 'vast_decoder_research_reservation_v1')
        require(reservation['controller'] == value['controller'] and reservation['name'] == value['name']
            and reservation['label'] == value['label'] and reservation['daemon_id'] == DAEMON
            and reservation['image_id'] == IMAGE and reservation['once_only'] is True, 'original reservation')
        require(value['label'] == hashlib.sha256((self.planning_commit+self.source_commit+self.mode+IMAGE+value['name']).encode()).hexdigest(),
                'P/S/mode reservation label')
        self.h.pin(directory/'execution-plan.v1.json', reservation['plan'])
        require(reservation['engine']['path'] == '/usr/bin/docker','canonical engine path')
        self.match_descriptor(reservation['engine'], ENGINE_SHA, 64*1048576)
        cid = self.h.read(directory/'original.cid', 65)
        require(re.fullmatch(rb'[0-9a-f]{64}\n?', cid) is not None and cid[:64].decode() == value['container_id'], 'original CID')
        launch = self.doc(directory/'launch-intent.v1.json', 'vast_decoder_research_launch_intent_v1')
        started = self.doc(directory/'process-start.v1.json', 'vast_decoder_research_process_start_v1')
        require(launch['argv'] == started['argv'] and started['child'] == value['child']
            and started['controller'] == value['controller'], 'original inner child/argv')
        validate_owner(value['child'])
        require(value['child']['ppid'] == value['controller']['pid'], 'inner original child parent')
        argv = ['/usr/bin/docker', 'run', '--name', value['name'], '--cidfile', str(directory/'original.cid'),
            '--label', 'vast.operational-custody='+value['label'], '--gpus', 'all', '--network', 'none', '--read-only',
            '--tmpfs', '/tmp:rw,nosuid,nodev,size=134217728,mode=1777', '--env', 'HOME=/tmp', '--env', 'XDG_CACHE_HOME=/tmp',
            '--env', 'NVIDIA_DRIVER_CAPABILITIES=compute,utility,video', '--mount',
            'type=bind,src='+str(self.repository/RUNTIME)+',dst=/opt/vast/code,readonly', '--mount',
            'type=bind,src='+str(directory/'execution-plan.v1.json')+',dst=/opt/vast/input/plan.json,readonly', '--mount',
            'type=bind,src='+str(self.attempt/'guest')+',dst=/opt/vast/output']
        for role in ('front_gate', 'underbody'):
            row = next(r for r in self.plan['sources'] if r['role'] == role)
            argv += ['--mount', 'type=bind,src='+row['media']['path']+',dst=/opt/vast/media/'+role+'.mp4,readonly']
        argv += ['--entrypoint', '/usr/bin/python3', IMAGE, '-I', '-B', '/opt/vast/code/guest_consumer.py',
            '--plan', '/opt/vast/input/plan.json', '--output-dir', '/opt/vast/output', '--mode', self.mode]
        require(launch['argv'] == argv, 'exact original Docker/guest command')
        commands = []
        for n, path in enumerate(sorted(directory.glob('engine-*.v1.json')), 1):
            require(path.name == f'engine-{n:02d}.v1.json', 'engine sequence')
            row = self.doc(path, 'vast_decoder_research_engine_observation_v1')
            require(row['argv'][0] == '/usr/bin/docker' and row['timed_out'] is False
                and row['errors'] == [] and row['controller'] == value['controller'] and 0 <= row['elapsed_s'] <= 10
                and type(row['returncode']) is int, 'original engine observation')
            validate_owner(row['child']);require(row['child']['ppid']==value['controller']['pid'],'engine original child parent')
            for role in ('stdout', 'stderr'):
                require(Path(row[role]['path']).parent == directory, 'engine output scope')
                self.h.pin(Path(row[role]['path']), row[role], 65536)
            commands.append((row, self.h.read(Path(row['stdout']['path']), 65536),
                             self.h.read(Path(row['stderr']['path']), 65536)))
        require(9 <= len(commands) <= 32, 'engine command count')
        def exact(index, arguments, output):
            row, out, err = commands[index]
            require(row['argv'] == ['/usr/bin/docker', *arguments] and row['returncode'] == 0
                and out == output and err == b'', 'original daemon/image command')
        exact(0, ['info', '--format', '{{json .ID}}'], canonical(DAEMON)+b'\n')
        exact(1, ['ps', '--all', '--no-trunc', '--format', '{{.ID}}'], b'')
        exact(2, ['image', 'inspect', '--format', '{{.Id}}', IMAGE], (IMAGE+'\n').encode())
        exact(-1, ['info', '--format', '{{json .ID}}'], canonical(DAEMON)+b'\n')
        remove = [i for i, (r, _, _) in enumerate(commands) if r['argv'] ==
                  ['/usr/bin/docker', 'container', 'rm', value['container_id']]]
        require(len(remove) == 1, 'one owned nonforce remove')
        index = remove[0]; row, out, err = commands[index]
        require(row['returncode'] == 0 and out == (value['container_id']+'\n').encode()
            and not err and index+4 == len(commands), 'owned remove/absence/daemon order')
        states = []
        for i, (row, out, err) in enumerate(commands[3:-1], 3):
            if i == index: continue
            require(row['argv'][:4] == ['/usr/bin/docker', 'container', 'inspect', '--format']
                and len(row['argv']) == 6 and row['argv'][4] == PROJECTION
                and row['argv'][-1] in (value['container_id'], value['name']), 'owned inspect scope')
            if i > index:
                identity = value['container_id'] if i == index+1 else value['name']
                require(row['argv'][-1] == identity and exact_absence(row, out, err, identity), 'CID/name absence')
            elif row['returncode'] == 0:
                state = strict_json(out, 65536)
                require(set(state) == {'Id','Name','Image','Created','Running','OOMKilled','ExitCode','Pid','StartedAt','FinishedAt','Operation'}
                    and type(state['Running']) is bool and type(state['OOMKilled']) is bool
                    and type(state['Pid']) is int and type(state['ExitCode']) is int
                    and not err and state['Id'] == value['container_id'] and state['Name'] == '/'+value['name']
                    and state['Image'] == IMAGE and state['Operation'] == value['label'], 'positive inner ownership')
                states.append((state, row['observed_realtime_ns']))
            else:
                require(i == 3 and exact_absence(row, out, err, value['name']), 'reserved name absence')
        require(states and states[-1][0] == value['final_observed_state'], 'final owned state')
        state, observed = states[-1]
        require(state['Running'] is False and state['Pid'] == state['ExitCode'] == 0 and state['OOMKilled'] is False
            and reservation['reserved_at_ns'] <= timestamp_ns(state['Created']) <= timestamp_ns(state['StartedAt'])
            <= timestamp_ns(state['FinishedAt']) <= observed, 'actual inner terminal')
        events = self.journal(directory/'events.jsonl')
        require(self.one(events, 'original_container_terminal_before_remove')['state'] == state
            and self.one(events, 'original_launcher_terminal')['forced_group_stop'] is False
            and self.one(events, 'original_launcher_terminal')['returncode'] == 0
            and self.one(events, 'original_cleanup_terminal')['exact_remove_then_absence'] is True
            and self.one(events, 'original_cleanup_terminal')['errors'] == [], 'inner causal cleanup facts')
        return value

    def historical_inputs(self):
        """Frozen ledger grants exact input bytes, independently of producer seals."""
        base = self.project/'artifacts/benchmark_recovery_20260930/decoder-experiment-prerequisites'
        ledger_path = base/'prerequisite-recipe-ledger.v1.json'
        self.match_descriptor(self.plan['historical_prerequisite'],LEDGER_SHA)
        require(Path(self.plan['historical_prerequisite']['path']) == ledger_path, 'original ledger root')
        ledger = self.h.document(ledger_path, under_root=False)
        observed_path = base/'original-media-physical-observation.v1.json'
        self.h.pin(observed_path,dict(MEDIA_OBSERVATION,path=str(observed_path)),under_root=False)
        observed = strict_json(self.h.read(observed_path, under_root=False))
        expected_files = [r['descriptor'] for r in ledger['source_citations']]
        require(self.plan['source_files'] == expected_files and ledger['image_id'] == IMAGE, 'historical citation/image join')
        for row in expected_files:
            require(Path(row['path']).is_relative_to(self.project), 'historical citation root')
            self.match_descriptor(row)
        media = {r['role']:r['descriptor'] for r in observed['media']}
        expected = []
        require(set(media) == {'front_gate','underbody'}, 'original media roles')
        for source in ledger['stock_sources']:
            row = dict(source); role = source['role']
            row['media'] = media[role]; row['actual_first_32_au_max_bytes'] = None
            require(Path(media[role]['path']) == self.project/source['stock_source_parameters']['input_path']
                and media[role]['sha256'] == source['stock_source_parameters']['source_sha256'], 'original full media identity')
            self.match_descriptor(media[role], maximum=2*1024*1048576)
            expected.append(row)
        require(self.plan['sources'] == expected and len(expected) == 2, 'exact frozen source parameters')
        for name in ('source_binary','nvcodec_plugin'):
            require(self.plan[name] == ledger['actual_package_files'][name], 'image-bound original package identity')
        custody = self.plan['custody_helper']
        require(custody == dict(CUSTODY,path=str(self.project/'scripts/publication_operational_container_custody_v1.py')), 'original custody source')
        self.match_descriptor(custody)
        require(self.plan['review_git'] == self.h.files['/usr/bin/git'][2], 'actual independent Git executable')

    @staticmethod
    def buffer_abi(value):
        require(value['implementation']=='cpython' and type(value['version']) is list and len(value['version'])==3
            and all(type(v) is int and v>=0 for v in value['version']) and value['version'][:2]>=[3,11]
            and value['pointer_bytes']==8 and value['py_buffer_bytes']==80 and value['format_offset']==40
            and value['request']=='PyBUF_SIMPLE' and value['field_offsets']=={'buf':0,'obj':8,'len':16,'itemsize':24,
                'readonly':32,'ndim':36,'format':40,'shape':48,'strides':56,'suboffsets':64,'internal':72}, 'original full buffer ABI')

    @staticmethod
    def mapped_row(row, resolved=True):
        raw = row['original_row']; require(type(raw) is str and len(raw.encode()) <= LINE_MAX, 'selected map row cap')
        fields = raw.split(None, 5)
        require(len(fields) == 6 and re.fullmatch(r'[0-9a-fA-F]+-[0-9a-fA-F]+',fields[0])
            and re.fullmatch(r'[r-][w-][x-][ps]',fields[1]) and re.fullmatch(r'[0-9a-fA-F]+',fields[2])
            and re.fullmatch(r'[0-9a-fA-F]+:[0-9a-fA-F]+',fields[3]) and re.fullmatch(r'[0-9]+',fields[4]), 'selected original map syntax')
        start,end = (int(x,16) for x in fields[0].split('-'))
        major,minor = (int(x,16) for x in fields[3].split(':'))
        parsed = {'original_row':raw,'address_start':start,'address_end':end,'permissions':fields[1],
            'offset':int(fields[2],16),'mapped_identity':[os.makedev(major,minor),int(fields[4])],'path':fields[5]}
        require(0 < start < end and parsed['mapped_identity'][1] > 0 and fields[5].startswith('/')
            and '\\' not in fields[5] and not fields[5].endswith(' (deleted)'), 'selected map range/path')
        if resolved:
            require(type(row['resolved_path']) is str and Path(row['resolved_path']).is_absolute(), 'original resolved map path')
            parsed['resolved_path'] = row['resolved_path']
        require(row == parsed, 'selected original map fields differ from raw row')
        return parsed

    def mappings(self, final, prelaunch, packages, guest_owner, source_owners):
        directory = self.attempt/'guest/metadata'
        collections = final['mapped_library_collections']
        require(type(collections) is list and 1 <= len(collections) <= 16
            and collections[:len(prelaunch['mapped_library_collections'])] == prelaunch['mapped_library_collections'], 'original mapping collections')
        require({Path(r['path']).name for r in collections} == {p.name for p in directory.glob('mapped-inputs-*-closed.v1.json')}
            and len({r['path'] for r in collections}) == len(collections), 'all closed mapping collections')
        owners = [guest_owner,*source_owners]
        for index, descriptor in enumerate(collections,1):
            path = self.output(descriptor)
            require(path == directory/f'mapped-inputs-{index:02d}-closed.v1.json', 'mapping collection sequence')
            value = self.doc(path,'vast_decoder_research_original_mapped_inputs_v1')
            require(value['observation_complete'] is True and value['owner_before'] == value['owner_after'] == value['process']
                and value['process'] in owners and value['proc_path'] == f"/proc/{value['process']['pid']}/maps", 'original mapping owner lifetime')
            validate_owner(value['process'])
            rows = value['selected_original_rows']
            require(rows == value['selected_rows_before'] == value['selected_rows_after'] and 1 <= len(rows) <= 512,
                    'selected mapping before/after equality')
            parsed = [self.mapped_row(row) for row in rows]
            ranges = sorted((r['address_start'],r['address_end']) for r in parsed)
            require(all(a[1] <= b[0] for a,b in zip(ranges,ranges[1:])), 'selected map overlap')
            require(type(value['selectors']) is list and value['selectors'] and all(type(s) is str and s for s in value['selectors']), 'map selectors')
            require(value['selectors'] == (['libgst','libglib','libgobject','libgirepository','_gi.','libcuda','libnvcuvid','libnvidia']
                if value['process']==guest_owner else ['libgst','libglib','libgobject']), 'original guest/source selector domain')
            require(all(any(s in row['path'] for s in value['selectors']) for row in rows), 'selected row selector')
            for prefix in ('snapshot','snapshot_after'):
                require(type(value[prefix+'_size_bytes']) is int and 0 < value[prefix+'_size_bytes'] <= CHANNEL_MAX
                    and re.fullmatch('[0-9a-f]{64}',value[prefix+'_sha256']), 'original full map observation bounds')
            before_path = self.output(value['before_snapshot'])
            require(before_path == directory/f'mapped-inputs-{index:02d}.v1.json', 'mapping before leaf')
            before = self.doc(before_path,'vast_decoder_research_original_mapped_inputs_v1')
            require(before['observation_complete'] is False and all(before[k] == value[k] for k in
                ('process','proc_path','selectors','snapshot_size_bytes','snapshot_sha256','selected_original_rows')), 'original mapping before/final join')
            identity_by_path = {}
            for row in rows:
                require(row['resolved_path'] not in identity_by_path or identity_by_path[row['resolved_path']] == row['mapped_identity'], 'conflicting mapped identity')
                identity_by_path[row['resolved_path']] = row['mapped_identity']
            observations = value['pin_observations']
            require(len(observations) == len(identity_by_path) and {r['descriptor']['path'] for r in observations} == set(identity_by_path), 'mapped descriptor coverage')
            for item in observations:
                descriptor, observation = item['descriptor'], item['mapping_observation']
                require(packages.get(descriptor['path']) == descriptor and observation['selected_identity'] == identity_by_path[descriptor['path']], 'mapped package/backing join')
                visible = observation['visible_identity']; selected = observation['selected_identity']
                require(all(type(v) is int and v >= 0 for v in visible) and len(visible) == 2 and visible[1] > 0, 'visible backing identity')
                probe = observation['probe']
                if observation['view'] == 'direct':
                    require(visible == selected and probe is None, 'direct mapped equality')
                else:
                    require(observation['view'] == 'readonly_backing_bridge' and visible != selected and type(probe) is dict, 'bridge view')
                    abi = probe['abi']
                    self.buffer_abi(abi)
                    validate_owner(probe['owner']); require(probe['owner'] == guest_owner, 'bridge observer owner')
                    vma = self.mapped_row(probe['vma'],False)
                    address,length = probe['buffer_address'],probe['buffer_length']
                    require(type(address) is int and type(length) is int and 0 < length <= min(65536,descriptor['size_bytes'])
                        and vma['address_start'] <= address < address+length <= vma['address_end']
                        and vma['permissions'] == 'r--p' and vma['offset']+address-vma['address_start'] == 0
                        and vma['mapped_identity'] == selected and probe['export_released'] is True
                        and probe['mapping_closed'] is True and 0 < probe['maps_size_bytes'] <= CHANNEL_MAX
                        and re.fullmatch('[0-9a-f]{64}',probe['maps_sha256']), 'readonly bridge range/retirement')
                    if value['process'] == guest_owner:
                        require(probe['selected_rows_during_without_probe'] == rows, 'self bridge original selected mappings unchanged')

    def guest(self, controller):
        directory = self.attempt/'guest/metadata'
        leaf = 'metadata-preflight-terminal.v1.json' if self.mode == 'metadata-only' else 'research-terminal.v1.json'
        names = {'events.jsonl','registry.stdout','registry.stderr','prelaunch.v1.json',
            'initialization-metadata.v1.json','final-package-pins.v1.json',leaf}
        if self.mode == 'research': names.add('paired-timing.v1.json')
        actual_names = self.h.members(directory)
        require(names <= actual_names and all(name in names or re.fullmatch(r'mapped-inputs-[0-9]{2}(-closed)?\.v1\.json',name)
            for name in actual_names), 'closed guest metadata/no failure companions')
        require(controller['guest_terminal']['path'] == str(directory/leaf), 'physical mode terminal path')
        self.match_descriptor(controller['guest_terminal'])
        terminal = self.doc(directory/leaf,'vast_decoder_research_metadata_preflight_terminal_v1' if self.mode == 'metadata-only' else 'vast_decoder_research_guest_terminal_v1')
        require(all(terminal.get(k) == v for k,v in self.binding.items()) and terminal['provisional_until_owner_final_close'] is True
            and terminal['operation_completed'] is True and terminal['metadata_preflight_completed'] is (self.mode == 'metadata-only')
            and terminal['research_complete'] is (self.mode == 'research') and terminal['runs_completed'] == (0 if self.mode == 'metadata-only' else 4), 'guest mode/body completion')
        require(all(terminal[k] is None for k in ('failure','failure_stage','failure_type','failure_traceback','failure_traceback_error',
            'original_primary_failure','primary_failure_capture_error')) and 0 <= terminal['elapsed_s'] <= (120 if self.mode == 'metadata-only' else 600), 'guest body failure/time')
        require(terminal['plan'] == dict(self.h.files[str(self.attempt/'controller/execution-plan.v1.json')][2],path='/opt/vast/input/plan.json'), 'guest original plan')
        stdout = strict_json(self.h.read(self.attempt/'controller/original.stdout',CHANNEL_MAX).strip(),LINE_MAX)
        require(stdout['successful'] is True and all(stdout[k] is None for k in ('receipt_time_limit_failure','close_failure',
            'metadata_close_error','pin_close_error','close_failure_capture_error')), 'actual post-close guest stdout')
        require(stdout['receipt']['path'] == '/opt/vast/output/metadata/'+leaf, 'mode guest terminal alias')
        require(self.output(stdout['receipt']) == directory/leaf
            and all(stdout['receipt'][key] == controller['guest_terminal'][key] for key in ('size_bytes','sha256')),
            'guest/controller physical terminal join')
        self.guest_terminal_join = {'controller_physical':dict(controller['guest_terminal']),
            'guest_stdout_alias':dict(stdout['receipt']),
            'held_physical':dict(self.h.files[str(directory/leaf)][2])}
        prelaunch = self.doc(directory/'prelaunch.v1.json','vast_decoder_research_guest_prelaunch_v1')
        require(prelaunch['plan'] == terminal['plan'] and prelaunch['gi_version'] == '3.50.0'
            and prelaunch['gst_version'] == [1,28,2,0] and prelaunch['plugin_path'] == self.plan['nvcodec_plugin']['path']
            and 0 <= prelaunch['elapsed_s'] <= self.plan['guest_prelaunch_budget_s'], 'packaged preflight version/clock')
        guest_owner = prelaunch['controller']; validate_owner(guest_owner)
        self.buffer_abi(prelaunch['buffer_abi'])
        init = self.doc(directory/'initialization-metadata.v1.json','vast_decoder_research_initialization_metadata_v1')
        require(init['intended_arguments'] == [] and (init['callable_doc'] is None or
            (type(init['callable_doc']) is str and len(init['callable_doc'].encode()) <= 4096)), 'original initializer arguments')
        events = self.journal(directory/'events.jsonl')
        require(self.one(events,'gst_initialization_before')['intended_arguments'] == []
            and self.one(events,'gst_initialization_after')['actual_initialized'] is True
            and self.one(events,'registry_process_terminal')['returncode'] == 0
            and self.one(events,'registry_process_terminal')['failures'] == [], 'actual initialization/registry')
        started = self.one(events,'registry_process_started'); validate_owner(started['child'])
        require(started['controller'] == guest_owner and started['child']['ppid'] == guest_owner['pid'], 'registry original owner')
        final = self.doc(directory/'final-package-pins.v1.json','vast_decoder_research_final_package_pins_v1')
        require(final['all_before_after_verified'] is True and 1 <= len(final['pins']) <= 128, 'original package closure')
        packages = {row['path']:row for row in final['pins']}
        require(len(packages) == len(final['pins']), 'duplicate package')
        for row in final['pins']:
            require(set(row) == {'path','size_bytes','sha256'} and Path(row['path']).is_absolute()
                and type(row['size_bytes']) is int and 0 < row['size_bytes'] <= 2*1024*1048576
                and re.fullmatch('[0-9a-f]{64}',row['sha256']), 'bounded original package descriptor')
        for row in [self.plan['source_binary'],self.plan['nvcodec_plugin'],terminal['plan'],
            *prelaunch['packages'],*init['actual_loaded_override_sources'],init['gi_package'],init['gi_extension'],init['gst_typelib']]:
            require(packages.get(row['path']) == row, 'original prelaunch/init/final package join')
        for row in self.plan['code']:
            require(packages.get('/opt/vast/code/'+Path(row['path']).name) == dict(row,path='/opt/vast/code/'+Path(row['path']).name), 'guest runtime S mount')
        by_role = {row['role']:row for row in self.plan['sources']}
        for role,source in by_role.items():
            require(prelaunch['media'][role] == dict(source['media'],path='/opt/vast/media/'+role+'.mp4')
                and packages.get(prelaunch['media'][role]['path']) == prelaunch['media'][role], 'original guest/full media join')
        completed,pairs,owners = [],[],[]
        if self.mode == 'metadata-only':
            require(terminal['result'] is None and self.h.members(self.attempt/'guest') == {'metadata'}, 'metadata-only zero runs/result')
        else:
            result = terminal['result']; require(result['research_correctness_preserved'] is True and len(result['runs']) == 4, 'complete research result')
            self.output(result['final_package_pins']); starts=[]
            for index,(role,setting) in enumerate(ORDER,1):
                run_dir = self.attempt/'guest'/f'run-{index:02d}-{role}-{setting}'
                require(self.output(result['runs'][index-1]['terminal']) == run_dir/'terminal.v1.json'
                    and self.output(result['runs'][index-1]['observations']) == run_dir/'observations.v1.json', 'four original run descriptors')
                actual,begin = self.run(index,role,setting,by_role[role],guest_owner)
                completed.append(actual); starts.append(begin)
                journal=self.journal(run_dir/'events.jsonl');source_owner=self.one(journal,'source_process_started')['child'];owners.append(source_owner)
                loaded=self.one(journal,'actual_source_loaded_libraries')
                loaded_path=self.output(loaded['mapped_inputs'])
                mapped=self.doc(loaded_path,'vast_decoder_research_original_mapped_inputs_v1')
                require(loaded['mapped_inputs'] in final['mapped_library_collections'] and mapped['process']==source_owner
                    and loaded['libraries']==[r['descriptor'] for r in mapped['pin_observations']], 'source READY original loaded-library join')
            require(all(starts[n]['guest_elapsed_at_start_s'] < starts[n+1]['guest_elapsed_at_start_s'] for n in range(3)), 'fixed serial order')
            for a,b in ((0,1),(3,2)):
                left,right = completed[a],completed[b]
                require(left['packets'] == right['packets'] and left['input_pts_decode_order'] == right['input_pts_decode_order'], 'paired identical AU prefix')
                require([r['pts'] for r in left['outputs']] == [r['pts'] for r in right['outputs']], 'paired presentation order')
                for first,second in zip(left['outputs'],right['outputs']):
                    require(all(first[k] == second[k] for k in ('pts','width','height','format','caps','caps_features','pixel_sha256')), 'paired RGB correctness')
                for n,(first,second) in enumerate(zip(left['timings'],right['timings']),1):
                    pairs.append(dict(clip=left['clip'],sequence=n,default_residence_ns=first['residence_ns'],zero_residence_ns=second['residence_ns'],
                        zero_minus_default_ns=second['residence_ns']-first['residence_ns'],cohort=first['cohort'],
                        steady_state_pair=not(first['after_actual_decoder_sink_eos'] or second['after_actual_decoder_sink_eos'])))
            paired = self.doc(self.output(result['paired_timings']),'vast_decoder_research_paired_timing_v1')
            require(paired['observations'] == pairs and len(pairs) == 64 and result['central_steady_state_sufficient_by_run'] ==
                [r['central_steady_state_sufficient'] for r in completed], 'independent64/cohort summary')
        self.mappings(final,prelaunch,packages,guest_owner,owners)
        require({r['path'] for r in final['mapped_library_collections']} == {str(Path('/opt/vast/output/metadata')/p.name)
            for p in directory.glob('mapped-inputs-*-closed.v1.json')}, 'mapping namespace complete')
        return completed,pairs

    def execute(self, external_path, capture_sha, tool_record):
        self.namespace()
        self.plan = self.doc(self.attempt/'controller/execution-plan.v1.json','vast_decoder_research_plan_v1')
        self.binding = self.source_bindings(self.plan)
        self.historical_inputs()
        external = self.external(external_path,capture_sha,tool_record)
        controller = self.controller(external)
        completed,pairs = self.guest(controller)
        self.h.check(True)
        return {'schema_version':1,'artifact_kind':'vast_decoder_research_independent_cold_replay_v6',**self.binding,
            'operation_completed':True,'metadata_preflight_completed':self.mode == 'metadata-only','research_complete':self.mode == 'research',
            'raw_join_complete':True,'actual_original_au_count':sum(r['actual_packets'] for r in completed),
            'paired_timing_count':len(pairs),'central_steady_state_sufficient_by_run':[r['central_steady_state_sufficient'] for r in completed],
            'paired_timings':pairs,'observer_binding':self.observer_binding,
            'guest_terminal_join':self.guest_terminal_join,
            'git_observations':self.git_commands,'held_inputs':self.h.observations(),
            'limitations':['Selected original VMA rows and backing probes are replayed; full unselected maps and mapped memory bytes are unavailable.',
                'Disposed image package/library descriptors are original observations, not current host rehashes.',
                'Pixel hashes are original observed RGB active-row hashes, compared but not independently decoded.',
                'Same-guest sink/src wall residence includes queueing/backpressure; it is not decoder utilization.',
                'ACK_sent is observed after its write and can follow transport validation; enabling ACK intent must precede it.',
                'Central outputs at/after actual sink EOS are flush-only and insufficient for central steady-state conclusions.',
                'No global host/process quiescence, six-stream100ms, model, parity, qualification or benchmark acceptance is inferred.'],
            'accepted':False,'publication_ready':False,'native_pair_count':0,'benchmark_arm_count':0,'qualification_count':0,'model_or_parity_evidence':False}

    def failed_prefixes(self):
        """Only independently hash-valid raw prefixes; never a successful cohort."""
        findings=[]
        for index,(role,setting) in enumerate(ORDER,1):
            path=self.attempt/'guest'/f'run-{index:02d}-{role}-{setting}'/'source-transport.raw'
            if not path.exists(): continue
            count=offset=0; failure=None
            try:
                self.h.pin(path,maximum=RAW_MAX)
                fd,before,_=self.h.files[str(path)]
                while offset < before[4] and count < 32:
                    raw=os.pread(fd,80,offset); require(len(raw)==80,'partial raw header')
                    magic,version,flags,seq,cycle,aupts,pts,dts,duration,a,k,n,size=HEADER.unpack(raw)
                    require(magic==b'VASTAU01' and version==1 and flags in (0,1) and seq==count+1 and cycle==0
                        and pts==aupts*600 and 999999600<=duration<MISSING and 0<a<=8192 and 0<k<=8192 and n==64
                        and 0<size<=PAYLOAD_MAX,'invalid raw prefix header')
                    text=os.pread(fd,a+k+n,offset+80); require(len(text)==a+k+n,'partial raw text')
                    digest=text[-64:].decode('ascii'); require(re.fullmatch('[0-9a-f]{64}',digest),'prefix payload digest')
                    begin=offset+80+a+k+n; require(begin+size<=before[4],'partial raw payload')
                    h=hashlib.sha256(); position=0
                    while position<size:
                        self.h.clock(); block=os.pread(fd,min(65536,size-position),begin+position)
                        require(bool(block),'short raw prefix'); h.update(block);position+=len(block)
                    require(h.hexdigest()==digest,'prefix payload mismatch')
                    offset=begin+size;count+=1
                require(offset==before[4],'trailing raw prefix bytes')
            except (ValueError,OSError,UnicodeError) as error:
                failure=type(error).__name__+': '+str(error)
            findings.append({'run':index,'clip':role,'setting':setting,'hash_valid_packet_prefix':count,
                'hash_valid_prefix_bytes':offset,'first_prefix_refusal':failure,'causal_join_complete':False,'promoted_cohort':False})
        return findings


def save_exclusive(path,value):
    value=dict(value); value['sha256']=hashlib.sha256(canonical(value)).hexdigest()
    raw=canonical(value)+b'\n'; require(len(raw)<=REPORT_MAX,'report2MiB cap')
    fd=None
    try:
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        view=memoryview(raw)
        while view:
            written=os.write(fd,view); require(written>0,'short report write');view=view[written:]
        os.fsync(fd)
    finally:
        if fd is not None:os.close(fd)
    return {'path':str(path),'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}


def reader_owner():
    raw=Path(f'/proc/{os.getpid()}/stat').read_bytes();require(len(raw)<=LINE_MAX,'reader proc stat cap')
    fields=raw.rsplit(b')',1)[1].split()
    return {'pid':os.getpid(),'ppid':int(fields[1]),'process_group_id':int(fields[2]),'starttime_ticks':int(fields[19]),
        'uid':os.getuid(),'gid':os.getgid(),'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip()}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('project-root','review-repository-root','planning-commit','source-commit','mode','attempt',
                 'external-terminal','capture-source-sha256','capture-tool-record','report'):
        parser.add_argument('--'+name,required=True,choices=('metadata-only','research') if name=='mode' else None)
    parser.add_argument('--observer-repository-root')
    parser.add_argument('--observer-commit')
    args=parser.parse_args()
    require((args.observer_repository_root is None) == (args.observer_commit is None),
        'paired observer repository/commit')
    require(args.planning_commit==PLANNING,'exact reviewed planning P required')
    require(re.fullmatch('[0-9a-f]{64}',args.capture_source_sha256),'reviewed capture SHA256 required')
    paths=[Path(getattr(args,name.replace('-','_'))) for name in ('project-root','review-repository-root','attempt','external-terminal','capture-tool-record','report')]
    project,repository,attempt,external,tool,report=paths
    require(all(path.is_absolute() for path in paths),'absolute original paths required')
    require(not report.exists() and report.parent.resolve(strict=True)==report.parent
        and not report.is_relative_to(attempt) and not report.is_relative_to(external.parent),'exclusive report outside closed originals')
    begun=time.monotonic(); original_reader=reader_owner();fd_before=len(list(Path('/proc/self/fd').iterdir()))
    replay=None;result=None;code=1;first=None;prefix=[];held=[];close=[]
    try:
        replay=Replay(project,repository,attempt,args.mode,args.source_commit,planning_commit=args.planning_commit,
            observer_repository=args.observer_repository_root,observer_commit=args.observer_commit)
        replay.h.deadline=begun+120
        result=replay.execute(external,args.capture_source_sha256,tool)
        code=0
    except (ValueError,OSError,KeyError,TypeError,IndexError,OverflowError) as error:
        first={'type':type(error).__name__,'message':str(error)[:4096]}
        if replay is not None:
            try:
                prefix=replay.failed_prefixes()
                replay.h.check(True)
            except (ValueError,OSError,KeyError,TypeError) as prefix_error:
                prefix=[{'prefix_review_unavailable':type(prefix_error).__name__,
                         'message':str(prefix_error)[:4096],'promoted_cohort':False}]
    finally:
        if replay is not None:
            held=replay.h.observations();replay.h.close();close=list(replay.h.close_errors)
    if close:
        code=1
        if first is None:first={'type':'CloseFailure','message':'independent held input retirement failed'}
    if time.monotonic()-begun>=120:
        code=1
        if first is None:first={'type':'TimeLimit','message':'cold120s exhausted before report'}
    if code:
        result={'schema_version':1,'artifact_kind':'vast_decoder_research_independent_cold_refusal_v6',
            'planning_commit':PLANNING,'source_commit':args.source_commit,'mode':args.mode,'first_failure':first,
            'operation_completed':False,'metadata_preflight_completed':False,'research_complete':False,'raw_join_complete':False,
            'valid_prefix_findings':prefix,'held_inputs':held,'accepted':False,'publication_ready':False,
            'native_pair_count':0,'benchmark_arm_count':0,'qualification_count':0,'model_or_parity_evidence':False,
            'observer_binding':None if replay is None else replay.observer_binding,
            'guest_terminal_join':None if replay is None else replay.guest_terminal_join}
    fd_after=len(list(Path('/proc/self/fd').iterdir()))
    if fd_after!=fd_before:
        code=1
        if first is None:first={'type':'FdClosure','message':'reader original FD count changed'}
        result.update(first_failure=first,operation_completed=False,metadata_preflight_completed=False,research_complete=False,raw_join_complete=False)
    result.update(reader_original=original_reader,reader_after=reader_owner(),fd_before=fd_before,fd_after=fd_after,
                  provisional_until_owner_final_close=True,close_errors=close,all_held_fds_released=not close and fd_before==fd_after and (replay is None or not replay.h.files and not replay.h.directories),
                  elapsed_s=time.monotonic()-begun)
    descriptor=save_exclusive(report,result)
    late=None
    if time.monotonic()-begun>=120:
        code=1
        late=save_exclusive(report.with_name(report.name+'.late-failure.v1.json'),{
            'artifact_kind':'vast_decoder_research_independent_cold_late_failure_v6','provisional_report':descriptor,
            'first_failure':first,'elapsed_s':time.monotonic()-begun,'accepted':False,'publication_ready':False})
    print(canonical({'report':descriptor,'successful':code==0,'late_failure':late,'close_errors':close}).decode(),flush=True)
    return code if time.monotonic()-begun<120 else 1


if __name__=='__main__':
    raise SystemExit(main())
