"""Bounded cold join of original native requests and observed guardian work.

This comparison supplies no launch/publication authority. Callers first validate
original process custody, operation contexts and stock measured ingress/policy
evidence. Digests index held physical records; matched full identities are read
again and compared, so a digest alone never authorizes a request.
"""
from __future__ import annotations

import hashlib
import heapq
import json
import os
import shutil
import stat
import struct
import tempfile
from collections.abc import Mapping
from pathlib import Path

from publication_operational_request_domain_v1 import (
    expand_guardian_identity_v1,
    strict_json_object_v1,
    validate_guardian_event_v1,
    validate_native_occurrence_v1,
)
from publication_policy_projection_v1 import reconstruct_original_decision_v1
from non_decreasing_wall_clock_v1 import MAXIMUM_BACKWARD_STEP_NS

GROUP_LIMIT = 256 * 1024 * 1024
FILE_LIMIT = 64 * 1024 * 1024
KEY = struct.Struct(">32sHQI")
CHUNK_KEYS = 16_384
MAX_SCRATCH_FILES = 128
MAX_EVENTS = 1_000_000
ROUTES = tuple(f"{branch}:{resource}" for branch in
               ("plate_number", "vehicle_type", "damage", "foreign_object")
               for resource in ("cpu", "gpu"))
MODES = {"complete_qualification_operational_identity_v1",
         "bounded_native_diagnostic_operational_v1"}


def _require(ok, message):
    if not ok:
        raise ValueError(message)


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("ascii")


def _sealed(value):
    _require(type(value) is dict and type(value.get("sha256")) is str,
             "operational object has no semantic seal")
    unsigned = {key: item for key, item in value.items() if key != "sha256"}
    _require(hashlib.sha256(_canonical(unsigned)).hexdigest() == value["sha256"],
             "operational object semantic seal mismatch")


def _snapshot(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


class _PinnedFile:
    def __init__(self, path, descriptor, *, limit=FILE_LIMIT, allow_empty=False):
        self.path = Path(path).absolute()
        _require(type(descriptor) is dict and set(descriptor) ==
                 {"path", "size_bytes", "sha256"}, "operational descriptor fields drifted")
        _require(str(self.path) == str(Path(descriptor["path"]).absolute()),
                 "operational descriptor path mismatch")
        _require(type(allow_empty) is bool and type(descriptor["size_bytes"]) is int and
                 (0 if allow_empty else 1) <= descriptor["size_bytes"] <= limit,
                 "operational file exceeds its byte budget")
        for parent in (self.path, *self.path.parents):
            _require(not parent.is_symlink(), "operational path traverses a symlink")
        self.parents = []
        for parent in self.path.parents:
            info = parent.lstat()
            _require(stat.S_ISDIR(info.st_mode), "operational ancestor is not a directory")
            self.parents.append((parent, (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid)))
        self.fd = -1
        try:
            named = self.path.lstat()
            self.fd = os.open(self.path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                              | getattr(os, "O_CLOEXEC", 0))
            opened = os.fstat(self.fd)
            _require(stat.S_ISREG(opened.st_mode) and opened.st_nlink == 1 and
                     _snapshot(named) == _snapshot(opened), "unsafe operational file")
            self.before = _snapshot(opened)
            _require(opened.st_size == descriptor["size_bytes"], "operational size drift")
            digest = hashlib.sha256()
            while block := os.read(self.fd, 1024 * 1024):
                digest.update(block)
            _require(digest.hexdigest() == descriptor["sha256"], "operational physical hash drift")
            self.check()
        except BaseException:
            self.close()
            raise

    def check(self):
        for parent, identity in self.parents:
            info = parent.lstat()
            _require(stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode) and
                (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid) == identity,
                "operational ancestor changed during cold validation")
        _require(self.before == _snapshot(os.fstat(self.fd)) ==
                 _snapshot(self.path.lstat()), "operational file changed during cold validation")

    def lines(self, *, first_cap=65_536, record_cap=9_216):
        os.lseek(self.fd, 0, os.SEEK_SET)
        # dup shares the held open-file description; no caller reads concurrently.
        with os.fdopen(os.dup(self.fd), "rb") as stream:
            offset = 0
            index = 0
            while True:
                cap = first_cap if index == 0 else record_cap
                line = stream.readline(cap + 1)
                if not line:
                    break
                _require(1 < len(line) <= cap and line.endswith(b"\n"),
                         "operational JSONL framing or line bound drifted")
                value = strict_json_object_v1(line, max_bytes=cap)
                _require(_canonical(value) + b"\n" == line, "operational JSONL is not canonical")
                yield offset, len(line), value
                offset += len(line)
                index += 1
        self.check()

    def record(self, offset, length):
        _require(type(length) is int and 1 < length <= 65_536,
                 "indexed operational record length is invalid")
        self.check()
        os.lseek(self.fd, offset, os.SEEK_SET)
        chunks = []
        remaining = length
        while remaining:
            chunk = os.read(self.fd, remaining)
            _require(bool(chunk), "indexed operational record is truncated")
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        value = strict_json_object_v1(raw, max_bytes=length)
        _require(_canonical(value) + b"\n" == raw, "indexed operational record drifted")
        return value

    def object(self, cap):
        _require(self.before[4] <= cap, "operational object exceeds its bound")
        os.lseek(self.fd, 0, os.SEEK_SET)
        with os.fdopen(os.dup(self.fd), "rb") as stream:
            raw = stream.read(cap + 1)
        _require(len(raw) == self.before[4] and raw.endswith(b"\n"),
                 "operational object framing drifted")
        value = strict_json_object_v1(raw, max_bytes=cap)
        _require(_canonical(value) + b"\n" == raw, "operational object is not canonical")
        self.check()
        return value

    def close(self):
        if self.fd >= 0:
            os.close(self.fd)
            self.fd = -1


class _Scratch:
    def __init__(self, root):
        root = Path(root).absolute()
        root.mkdir(parents=True, exist_ok=True)
        _require(not root.is_symlink() and root.is_dir(), "cold scratch root is unsafe")
        self.root = root
        self.path = Path(tempfile.mkdtemp(prefix=".operational-cold-", dir=root))
        self.files = []
        self.bytes = 0

    def write(self, rows):
        rows.sort()
        payload = b"".join(rows)
        _require(len(payload) <= 4 * 1024 * 1024 and
                 len(self.files) < MAX_SCRATCH_FILES and
                 self.bytes + len(payload) <= GROUP_LIMIT, "cold scratch budget exhausted")
        path = self.path / f"keys-{len(self.files):03d}.bin"
        with path.open("xb") as stream:
            stream.write(payload)
        self.files.append(path)
        self.bytes += len(payload)
        return path

    def close(self):
        # Delete only the private directory created by this instance.
        _require(self.path.parent == self.root and
                 self.path.name.startswith(".operational-cold-") and
                 not self.path.is_symlink(), "cold scratch cleanup target drifted")
        shutil.rmtree(self.path)


class _Index:
    def __init__(self, scratch):
        self.scratch = scratch
        self.rows = []
        self.paths = []
        self.count = 0

    def add(self, digest, source, offset, length):
        _require(self.count < MAX_EVENTS, "cold identity index count exhausted")
        self.rows.append(KEY.pack(digest, source, offset, length))
        self.count += 1
        if len(self.rows) == CHUNK_KEYS:
            self.flush()

    def flush(self):
        if self.rows:
            self.paths.append(self.scratch.write(self.rows))
            self.rows = []

    def sorted(self):
        self.flush()
        # The complete bounded index needs <=62 chunks. Merge one fixed-size
        # key per file; no Python collection grows with lifetime occurrences.
        _require(len(self.paths) <= 64, "cold merge fan-in exceeds its bound")
        streams = [path.open("rb") for path in self.paths]
        try:
            def records(stream):
                while raw := stream.read(KEY.size):
                    _require(len(raw) == KEY.size, "cold scratch key is truncated")
                    yield raw
            for raw in heapq.merge(*(records(stream) for stream in streams)):
                yield KEY.unpack(raw)
        finally:
            for stream in streams:
                stream.close()


def _identity(record, header, route_headers):
    raw = record["decision_request"]
    accepted = record["accepted_record"]
    branch, resource = accepted["branch"], accepted["selected_resource"]
    # The native header protocol describes the policy RPC, not the inference
    # front. These exact runtime implementations use their pinned front source.
    _require(header["system"] in {"gstreamer_custom", "openvino_gva", "deepstream", "savant"},
             "unsupported original operational runtime")
    protocol = ("analytics_execute" if header["system"] in
                {"gstreamer_custom", "openvino_gva"} else "infer_request")
    decision_id = record["decision_id"]
    worker = raw["worker_id"]
    if protocol == "analytics_execute":
        request_id = hashlib.sha256("\n".join(("analytics_execution_request_v1",
            raw["run_id"], raw["input_frame_key"], branch, decision_id)).encode("utf-8")).hexdigest()
        arm_id = hashlib.sha256(("analytics_execution_arm_v1\n" + raw["run_id"] +
            "\n" + accepted["policy"] + "\n" + f"{float(header['deadline_ms']):.6f}").encode("utf-8")).hexdigest()
    elif protocol == "infer_request":
        worker = route_headers[f"{branch}:{resource}"]["worker_capability"]["worker_id"]
        material = f"{decision_id}\0{raw['input_frame_key']}\0{branch}\0{worker}"
        request_id = "deepstream-" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:48]
        arm_id = header["context_arm_id"]
        decision_id = None  # This field is genuinely absent from the proxy wire.
    else:
        raise ValueError("unsupported original front protocol")
    return {"protocol": protocol, "run_id": raw["run_id"], "arm_id": arm_id,
            "system": accepted["system"], "policy": accepted["policy"],
            "worker_id": worker, "stream_id": raw["stream_id"],
            "request_id": request_id, "input_frame_key": raw["input_frame_key"],
            "frame_id": raw["frame_id"], "transport_pts_ns": raw["transport_pts_ns"],
            "decision_id": decision_id, "branch": branch, "resource": resource}


def load_operational_jsonl_header_v1(entry):
    """Read one bounded header under the same original physical file custody."""
    source = _PinnedFile(entry["path"], entry["descriptor"])
    lines = source.lines()
    try:
        _, _, header = next(lines)
        source.check()
        return header
    finally:
        lines.close()
        source.close()


def reconcile_operational_request_domain_v1(*, producer_domains, guardian_companion,
        measurement_descriptors, expected_context, authority_validator, scratch_root):
    """Validate full multiplicity and the independently held measured subset."""
    _require(type(expected_context) is dict and set(expected_context) ==
             {"mode", "operation_count", "guardian_headers"} and
             expected_context["mode"] in MODES, "unsupported operational cold context")
    count = expected_context["operation_count"]
    _require(type(count) is int and 0 < count <= 37 and
             len(producer_domains) == len(measurement_descriptors) == count,
             "original operational domain cardinality drifted")
    route_headers = expected_context["guardian_headers"]
    _require(type(route_headers) is dict and set(route_headers) == set(ROUTES),
             "cold context lacks the exact eight original route headers")
    for header in route_headers.values():
        _sealed(header)
    operation_counts = []
    scratch = _Scratch(scratch_root)
    sources = []
    expected = _Index(scratch)
    observed = _Index(scratch)
    measured_native = _Index(scratch)
    measured_projection = _Index(scratch)
    event_ordinals = _Index(scratch)
    request_ordinals = _Index(scratch)
    connection_ordinals = _Index(scratch)
    expected_counts = {key: 0 for key in ROUTES}
    observed_counts = {key: 0 for key in ROUTES}
    headers = {}
    kinds = {}
    try:
        def pin(entry, *, limit=FILE_LIMIT):
            _require(len(sources) < 128, "cold source handle bound exhausted")
            source = _PinnedFile(entry["path"], entry["descriptor"], limit=limit)
            sources.append(source)
            return len(sources) - 1, source

        for operation, (domain, measurement) in enumerate(zip(producer_domains,
                                                            measurement_descriptors, strict=True)):
            source_id, source = pin(domain)
            kinds[source_id] = ("native", operation)
            lines = source.lines()
            _, _, header = next(lines)
            _sealed(header)
            _require(header == domain["expected_header"], "original native context/header drifted")
            headers[source_id] = header
            canonical_frames = measurement["canonical_frames"]
            if callable(canonical_frames):
                # A qualification caller supplies a held ingress loader per
                # original operation, so it never retains 37 frame maps.
                canonical_frames = canonical_frames()
            _require(type(canonical_frames) is dict and 0 < len(canonical_frames) <= 1686,
                     "measured ingress subset exceeds supported source bound")
            native_measured = 0
            native_count = 0
            previous_decision_time_ms = 0.0
            seen_decisions = set()
            for offset, length, record in lines:
                _require(native_count < 6744, "native complete request count exhausted")
                validate_native_occurrence_v1(record, expected_header=header,
                    original_authority_validator=authority_validator)
                native_count += 1
                _require(record["runtime_decision_seq"] == native_count and
                         record["decision_id"] not in seen_decisions,
                         "native operational issuance is duplicated or incomplete")
                seen_decisions.add(record["decision_id"])
                raw = record["decision_request"]
                serialized_time = max(previous_decision_time_ms, float(raw["decision_time_ms"]))
                _require(record["accepted_record"]["request"]["decision_time_ms"] == serialized_time,
                         "original dense policy decision clock serialization drifted")
                previous_decision_time_ms = serialized_time
                frame = canonical_frames.get(raw["input_frame_key"])
                _require(record["measurement"] is (frame is not None),
                         "operational measurement membership differs from original ingress")
                identity = _identity(record, header, route_headers)
                expected.add(hashlib.sha256(_canonical(identity)).digest(), source_id, offset, length)
                expected_counts[f"{identity['branch']}:{identity['resource']}"] += 1
                if frame is not None:
                    _require(raw["stream_id"] == frame["stream_id"],
                             "measured original stream differs from ingress")
                    native_measured += 1
                    subset = {"operation": operation,
                              "accepted_record_sha256": record["accepted_record_sha256"],
                              "issued_record_sha256": record["issued_record_sha256"]}
                    measured_native.add(hashlib.sha256(_canonical(subset)).digest(), source_id, offset, length)
            _require(native_count == header["counts"]["complete_decision_count"] and
                     native_measured == header["counts"]["measurement_decision_count"] and
                     native_count - native_measured == header["counts"]["excluded_decision_count"],
                     "native operational header counts differ from original records")
            projection_id, projection = pin(measurement)
            kinds[projection_id] = ("measurement", operation)
            projection_count = 0
            for offset, length, record in projection.lines(first_cap=9_216):
                _require(projection_count < 6744, "measured decision count exhausted")
                original, issued = reconstruct_original_decision_v1(record)
                projection_count += 1
                key = original["native_decision_evidence"]["input_frame_key"]
                frame = canonical_frames.get(key)
                _require(frame is not None and record["trace_id"] == frame["trace_id"] and
                         record["decision_seq"] == projection_count,
                         "projected decision differs from validated measured ingress")
                subset = {"operation": operation, "accepted_record_sha256": original["sha256"],
                          "issued_record_sha256": issued["sha256"]}
                measured_projection.add(hashlib.sha256(_canonical(subset)).digest(), projection_id, offset, length)
            _require(projection_count == native_measured,
                     "measured projection and complete native subset counts differ")
            operation_counts.append({"ordinal": operation, "request_count": native_count,
                "measurement_request_count": native_measured,
                "excluded_request_count": native_count - native_measured})

        _, companion_source = pin(guardian_companion, limit=1024 * 1024)
        companion = companion_source.object(1024 * 1024)
        _sealed(companion)
        # Historical v1 groups predate max_clamp_ns; a present value is bounded.
        clamp = companion.get("max_clamp_ns", 0)
        _require(set(companion) - {"max_clamp_ns"} == {"schema_version", "artifact_kind", "lifecycle_id",
                 "accounting_input", "journals", "counts", "sha256"} and
                 companion["schema_version"] == 1 and
                 companion["artifact_kind"] == "vast_guardian_operational_group_v1" and
                 type(companion["journals"]) is list and len(companion["journals"]) == 8 and
                 type(clamp) is int and 0 <= clamp <= MAXIMUM_BACKWARD_STEP_NS + 1,
                 "guardian operational companion schema drifted")
        seen_routes = set()
        totals = {key: 0 for key in ("requests_started", "requests_completed", "requests_failed",
                                    "unfinished_requests", "event_count")}
        journal_bytes = 0
        for journal in companion["journals"]:
            _require(set(journal) == {"route", "path", "size_bytes", "sha256", "event_count",
                     "requests_started", "requests_completed", "requests_failed", "unfinished_requests",
                     "final_event_sha256"}, "guardian journal descriptor fields drifted")
            route = journal["route"]
            _require(route in ROUTES and route not in seen_routes, "guardian route is foreign or duplicated")
            seen_routes.add(route)
            _require(all(type(journal[key]) is int and 0 <= journal[key] <= MAX_EVENTS
                         for key in ("event_count", "requests_started", "requests_completed",
                                     "requests_failed", "unfinished_requests")),
                     "guardian journal counters are not bounded original integers")
            entry = {"path": journal["path"], "descriptor":
                     {key: journal[key] for key in ("path", "size_bytes", "sha256")}}
            journal_bytes += journal["size_bytes"]
            _require(journal_bytes + companion_source.before[4] <= GROUP_LIMIT,
                     "guardian retained group byte budget exhausted")
            source_id, source = pin(entry)
            kinds[source_id] = ("guardian", route)
            lines = source.lines(record_cap=768)
            _, _, header = next(lines)
            _require(header == route_headers[route] and
                     header["lifecycle_id"] == companion["lifecycle_id"] and
                     header["descriptors"]["accounting_input"] == companion["accounting_input"],
                     "guardian observed context differs from original authority")
            headers[source_id] = header
            previous_sha = header["sha256"]
            previous_seq = 0
            pending = {}
            begins = terminals = events = 0
            for offset, length, event in lines:
                validate_guardian_event_v1(event, previous_sha256=previous_sha)
                _require(event["seq"] > previous_seq, "guardian route event order drifted")
                previous_seq, previous_sha = event["seq"], event["sha256"]
                events += 1
                event_ordinals.add(event["seq"].to_bytes(32, "big"), source_id, offset, length)
                if event.get("type") == "begin":
                    _require(len(pending) < 128 and event["seq"] not in pending,
                             "guardian pending occurrence bound exhausted")
                    identity = expand_guardian_identity_v1(header, event)
                    request_ordinals.add(event["request_seq"].to_bytes(32, "big"),
                                         source_id, offset, length)
                    connection_key = (event["connection"].to_bytes(8, "big") +
                                      event["local_seq"].to_bytes(8, "big") + bytes(16))
                    connection_ordinals.add(connection_key, source_id, offset, length)
                    pending[event["seq"]] = event["at_ns"]
                    observed.add(hashlib.sha256(_canonical(identity)).digest(), source_id, offset, length)
                    observed_counts[route] += 1
                    begins += 1
                else:
                    began = pending.pop(event["begin_seq"], None)
                    _require(began is not None and event["at_ns"] >= began and
                             event["outcome"] == "completed" and event["send"] == "sent" and
                             type(event["response"]) is str,
                             "guardian operational request lacks exactly one successful full terminal")
                    terminals += 1
            _require(not pending and begins == terminals == journal["requests_started"] ==
                     journal["requests_completed"] and journal["requests_failed"] ==
                     journal["unfinished_requests"] == 0 and events == journal["event_count"] and
                     previous_sha == journal["final_event_sha256"], "guardian journal terminal/count drift")
            for key in totals:
                totals[key] += journal[key]
        _require(set(companion["counts"]) == set(totals) | {"connections_accepted"} and
                 all(type(value) is int and 0 <= value <= MAX_EVENTS
                     for value in companion["counts"].values()) and
                 all(companion["counts"][key] == value for key, value in totals.items()),
                 "guardian complete operational totals drifted")
        for ordinal, (digest, _, _, _) in enumerate(event_ordinals.sorted(), 1):
            _require(int.from_bytes(digest, "big") == ordinal,
                     "guardian global event union is duplicated or incomplete")
        for ordinal, (digest, _, _, _) in enumerate(request_ordinals.sorted(), 1):
            _require(int.from_bytes(digest, "big") == ordinal,
                     "guardian request ordinal union is duplicated or incomplete")
        previous_connection = previous_local = participating_connections = 0
        for digest, _, _, _ in connection_ordinals.sorted():
            connection = int.from_bytes(digest[:8], "big")
            local = int.from_bytes(digest[8:16], "big")
            _require(0 < connection <= companion["counts"]["connections_accepted"],
                     "guardian request references a foreign original connection")
            if connection != previous_connection:
                previous_local = 0
                participating_connections += 1
            _require(local == previous_local + 1,
                     "guardian per-connection request sequence is duplicated or incomplete")
            previous_connection, previous_local = connection, local
        _require(event_ordinals.count == totals["event_count"] and
                 expected.count == observed.count == totals["requests_completed"] and
                 expected_counts == observed_counts, "guardian and native complete domains differ")

        def reread(index_row, *, subset=False):
            _, source_id, offset, length = index_row
            record = sources[source_id].record(offset, length)
            kind, operation = kinds[source_id]
            if kind == "native":
                if subset:
                    return {"operation": operation, "accepted": record["accepted_record"],
                            "issued_record_sha256": record["issued_record_sha256"]}
                return _identity(record, headers[source_id], route_headers)
            if kind == "guardian":
                return expand_guardian_identity_v1(headers[source_id], record)
            accepted, issued = reconstruct_original_decision_v1(record)
            return {"operation": operation, "accepted": accepted, "issued_record_sha256": issued["sha256"]}

        comparison = hashlib.sha256(b"VAST:complete-operational-request-domain:v1\0")
        for left, right in zip(expected.sorted(), observed.sorted(), strict=True):
            expected_identity, observed_identity = reread(left), reread(right)
            _require(left[0] == right[0] and expected_identity == observed_identity,
                     "same-count substituted or foreign guardian request identity")
            encoded = _canonical(expected_identity)
            comparison.update(len(encoded).to_bytes(8, "big") + encoded)
        _require(measured_native.count == measured_projection.count,
                 "measured operational subset is incomplete")
        for left, right in zip(measured_native.sorted(), measured_projection.sorted(), strict=True):
            _require(left[0] == right[0] and reread(left, subset=True) == reread(right, subset=True),
                     "measured original policy evidence is substituted or duplicated")
        for source in sources:
            source.check()
        return {"schema_version": 1, "artifact_kind": "vast_complete_operational_reconciliation_v1",
                "mode": expected_context["mode"], "original_operation_count": count,
                "operations": operation_counts,
                "request_count": expected.count, "measurement_request_count": measured_native.count,
                "excluded_request_count": expected.count - measured_native.count,
                "connections_accepted": companion["counts"]["connections_accepted"],
                "requests_by_worker": expected_counts, "comparison_sha256": comparison.hexdigest(),
                "publication_authority": False}
    finally:
        for source in sources:
            source.close()
        scratch.close()
