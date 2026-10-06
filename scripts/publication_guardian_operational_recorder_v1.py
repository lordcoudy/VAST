"""Bounded, nonauthorizing capture of actual guardian front requests.

Headers hold validated wire constants. Events keep every dynamic identity field;
references never identify a physical original invocation. All limits are checked
before new pending state or writes, with terminal capacity reserved at begin.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import threading
import time
from publication_operational_request_domain_v1 import canonical_json_v1, payload_with_sha256_v1, seal_guardian_event_v1, validate_study_scope_v1, STUDY_GUARDIAN_KIND_V1
from non_decreasing_wall_clock_v1 import process_wall_clock, wall_time_ns
from typing import Any, Callable, Mapping

BRANCHES = ("plate_number", "vehicle_type", "damage", "foreign_object")
ROUTES = {(branch, resource) for branch in BRANCHES for resource in ("cpu", "gpu")}
HEADER_KIND = "vast_guardian_operational_request_journal_v1"
GROUP_KIND = "vast_guardian_operational_group_v1"
DEFAULT_BUDGETS = {
    "max_group_bytes": 268435456, "max_route_bytes": 67108864,
    "max_header_bytes": 65536, "max_begin_bytes": 768,
    "max_terminal_bytes": 256, "max_events": 1000000,
    "max_requests": 500000, "max_pending": 128,
    "max_append_bytes": 65536, "terminal_reservation_bytes": 4096,
}
STUDY_BUDGET_OVERRIDES = {"max_terminal_bytes": 2048, "max_group_bytes": 768 * 1024 * 1024}  # Amendment7 pool lifetime.
COUNTS = ("requests_started", "requests_completed", "requests_failed",
          "unfinished_requests", "connections_accepted", "event_count")
HEADER_FIELDS = {"schema_version", "artifact_kind", "record_kind",
    "digest_algorithm", "descriptors", "lifecycle_id", "owner", "route",
    "protocols", "contexts", "front_workers", "bindings", "worker_capability",
    "initial_counters", "budgets", "sha256"}
DESCRIPTORS = {"accounting_input", "service_authority", "capability_manifest",
    "execution_config", "execution_code_closure", "model_authority",
    "source_plan", "native_protocol_source", "proxy_protocol_source"}
SHA = re.compile(r"[0-9a-f]{64}\Z")


class GuardianOperationalError(ValueError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise GuardianOperationalError(message)


def _canonical(value: Any) -> bytes:
    try:
        return canonical_json_v1(value)
    except (TypeError, ValueError, OverflowError) as error:
        raise GuardianOperationalError("operational JSON is invalid") from error


def _sealed(value: Mapping[str, Any]) -> dict[str, Any]:
    return payload_with_sha256_v1({key: item for key, item in value.items() if key != "sha256"})


def _integer(value: Any, maximum: int, label: str, minimum: int = 0) -> int:
    _require(type(value) is int and minimum <= value <= maximum,
             "operational " + label + " is outside supported source bounds")
    return value


def _text(value: Any, maximum: int, label: str) -> str:
    _require(type(value) is str and 0 < len(value) <= maximum
             and value.isascii() and all(0x21 <= ord(c) < 0x7f for c in value),
             "operational " + label + " is outside supported source bounds")
    return value


def _descriptor(value: Any) -> None:
    _require(type(value) is dict and set(value) == {"path", "size_bytes", "sha256"},
             "operational descriptor fields drifted")
    path = value["path"]
    _require(type(path) is str and 0 < len(path) <= 512 and path.isascii()
             and not any(ord(c) < 0x20 for c in path), "operational descriptor path invalid")
    _integer(value["size_bytes"], (1 << 64) - 1, "descriptor size")
    _require(type(value["sha256"]) is str and SHA.fullmatch(value["sha256"]),
             "operational descriptor SHA invalid")


def _table(header: Mapping[str, Any], name: str, fields: set[str], maximum: int) -> dict[int, dict[str, Any]]:
    rows = header[name]
    _require(type(rows) is list and 0 < len(rows) <= maximum,
             "operational " + name + " table is outside supported bounds")
    result = {}
    for row in rows:
        _require(type(row) is dict and set(row) == fields,
                 "operational " + name + " row fields drifted")
        identity = _integer(row["id"], 221, name + " id")
        _require(identity not in result, "duplicate operational " + name + " reference")
        result[identity] = row
    return result


def _header(value: Mapping[str, Any], route: tuple[str, str], budgets: Mapping[str, int]) -> tuple[dict[str, Any], dict[tuple[Any, ...], int]]:
    study_scope = value.get("study_scope")
    if study_scope is not None:
        validate_study_scope_v1(study_scope)
    _require(type(value) is dict and set(value) == (HEADER_FIELDS if study_scope is None else HEADER_FIELDS | {"study_scope"}),
             "operational header fields drifted")
    _require(type(value["schema_version"]) is int and value["schema_version"] == 1 and value["artifact_kind"] == (HEADER_KIND if study_scope is None else STUDY_GUARDIAN_KIND_V1)
             and value["record_kind"] == "header" and value["digest_algorithm"] == "sha256",
             "operational header version drifted")
    _require(value["route"] == {"branch": route[0], "resource": route[1]},
             "operational header route drifted")
    _require(type(value["descriptors"]) is dict and set(value["descriptors"]) == DESCRIPTORS,
             "operational header descriptor roles drifted")
    for descriptor in value["descriptors"].values():
        _descriptor(descriptor)
    _text(value["lifecycle_id"], 32, "lifecycle")
    _require(type(value["owner"]) is dict and set(value["owner"]) == {"uid", "gid", "pid", "proc_stat_starttime_ticks"},
             "operational owner fields drifted")
    for key, number in value["owner"].items():
        _integer(number, (1 << 64) - 1 if key == "proc_stat_starttime_ticks" else 9999999999, "owner " + key)
    _require(type(value["initial_counters"]) is dict and set(value["initial_counters"]) == set(COUNTS)
             and all(type(number) is int for number in value["initial_counters"].values())
             and value["initial_counters"] == dict.fromkeys(COUNTS, 0),
             "operational header initial counters must be zero")
    _require(type(value["budgets"]) is dict and all(type(number) is int for number in value["budgets"].values())
             and value["budgets"] == budgets, "operational header budgets drifted")
    protocols = _table(value, "protocols", {"id", "schema_version", "message_type", "transport", "source_descriptor"}, 2)
    contexts = _table(value, "contexts", {"id", "protocol", "run_id", "arm_id", "system", "policy"}, 37 if study_scope is None else 32)
    workers = _table(value, "front_workers", {"id", "worker_id", "stream_id"}, 24)
    bindings = _table(value, "bindings", {"id", "context", "front_worker"}, 222)
    lookup = {}
    for protocol in protocols.values():
        _require(protocol["schema_version"] == 1 and protocol["message_type"] in {"analytics_execute", "infer_request"}
                 and protocol["transport"] == "unix_seqpacket_scm_rights_sealed_memfd"
                 and protocol["source_descriptor"] == ("native_protocol_source" if protocol["message_type"] == "analytics_execute" else "proxy_protocol_source"),
                 "operational protocol constants drifted")
    for context in contexts.values():
        _text(context["run_id"], 64, "context run")
        _text(context["arm_id"], 68, "wire arm")
        _text(context["system"], 16, "system")
        _text(context["policy"], 19, "policy")
        _require(context["protocol"] in protocols, "unresolved operational protocol reference")
    for worker in workers.values():
        _text(worker["worker_id"], 160, "front worker")
        _integer(worker["stream_id"], 5, "front stream")
    for binding in bindings.values():
        _require(binding["context"] in contexts and binding["front_worker"] in workers,
                 "unresolved operational binding reference")
        context, worker = contexts[binding["context"]], workers[binding["front_worker"]]
        protocol = protocols[context["protocol"]]
        key = (protocol["message_type"], context["run_id"], context["arm_id"], worker["worker_id"], worker["stream_id"])
        _require(key not in lookup, "ambiguous operational wire binding")
        lookup[key] = binding["id"]
    _require(type(value["worker_capability"]) is dict
             and len(_canonical(value["worker_capability"])) <= 6136,
             "operational worker capability exceeds source bound")
    header = _sealed(value)
    _require(len(_canonical(header)) + 1 <= budgets["max_header_bytes"], "operational header byte capacity exhausted")
    return json.loads(_canonical(header)), lookup


class GuardianOperationalRecorder:
    """One bounded lifetime group. ``budgets`` may only reduce reviewed limits."""

    def __init__(self, outdir: Path | str, headers_by_route: Mapping[tuple[str, str], Mapping[str, Any]],
                 *, budgets: Mapping[str, int] | None = None,
                 clock_ns: Callable[[], int] = wall_time_ns) -> None:
        self._budgets = dict(DEFAULT_BUDGETS)
        study_scopes = [header.get("study_scope") for header in headers_by_route.values()]
        if any(scope is not None for scope in study_scopes):
            _require(all(scope is not None and scope == study_scopes[0] for scope in study_scopes),
                     "study scope differs across held routes")
            self._budgets.update(STUDY_BUDGET_OVERRIDES)
        for key, number in (budgets or {}).items():
            _require(key in DEFAULT_BUDGETS, "unknown operational budget")
            _integer(number, self._budgets[key], key, 1)
            self._budgets[key] = number
        _require(set(headers_by_route) == ROUTES, "operational headers must cover exact eight routes")
        checked = {route: _header(dict(header), route, self._budgets) for route, header in headers_by_route.items()}
        lifecycle = {header[0]["lifecycle_id"] for header in checked.values()}
        accounting = {_canonical(header[0]["descriptors"]["accounting_input"]) for header in checked.values()}
        _require(len(lifecycle) == len(accounting) == 1, "operational header lifetime/input differs across routes")
        self._outdir = Path(outdir).absolute()
        _require(self._outdir.parent.resolve(strict=True) == self._outdir.parent,
                 "operational output parent path has aliases")
        self._outdir.mkdir(mode=0o700)
        _require(not self._outdir.is_symlink(), "operational output directory is a symlink")
        self._directory_identity = (self._outdir.stat().st_dev, self._outdir.stat().st_ino)
        self._directory_fd = os.open(self._outdir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW) if os.name == "posix" else None
        self._closed = False
        self._lock = threading.RLock()
        self._clock_ns = clock_ns
        self._failure: str | None = None
        self._finished = False
        self._seq = 0
        self._pending: dict[int, tuple[tuple[str, str], int]] = {}
        self._counts = dict.fromkeys(COUNTS, 0)
        self._routes: dict[tuple[str, str], dict[str, Any]] = {}
        self.group_descriptor: dict[str, Any] | None = None
        self._headers = {route: pair[0] for route, pair in checked.items()}
        try:
            for route, (header, lookup) in sorted(checked.items()):
                path = self._outdir / (route[0] + "-" + route[1] + ".jsonl")
                raw = _canonical(header) + b"\n"
                stream = self._open_exclusive(path.name)
                row = {"study_scope": header.get("study_scope"), "path": path, "stream": stream, "lookup": lookup, "sha": header["sha256"],
                       "digest": hashlib.sha256(), "bytes": 0, "pending": 0,
                       "file_identity": (os.fstat(stream.fileno()).st_dev, os.fstat(stream.fileno()).st_ino),
                       "event_count": 0, "requests_started": 0, "requests_completed": 0, "requests_failed": 0}
                self._routes[route] = row
                self._write(row, raw)
        except BaseException:
            self.close()
            raise

    def _assert_custody(self, row: dict[str, Any] | None = None) -> None:
        _require(not self._outdir.is_symlink() and self._outdir.is_dir(),
                 "operational output directory custody changed")
        observed = self._outdir.stat()
        _require((observed.st_dev, observed.st_ino) == self._directory_identity,
                 "operational output directory custody changed")
        if self._directory_fd is not None:
            pinned = os.fstat(self._directory_fd)
            _require((pinned.st_dev, pinned.st_ino) == self._directory_identity,
                     "operational output dirfd custody changed")
        if row is not None:
            path = row["path"]
            _require(not path.is_symlink(), "operational journal is a symlink")
            current = os.stat(path.name, dir_fd=self._directory_fd, follow_symlinks=False) if self._directory_fd is not None else path.stat()
            _require((current.st_dev, current.st_ino) == row["file_identity"] and current.st_nlink == 1,
                     "operational journal custody changed")

    def _open_exclusive(self, name: str):
        self._assert_custody()
        if self._directory_fd is None:
            return (self._outdir / name).open("xb", buffering=0)
        descriptor = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o600, dir_fd=self._directory_fd)
        return os.fdopen(descriptor, "wb", buffering=0)

    def _write(self, row: dict[str, Any], raw: bytes) -> None:
        _require(len(raw) <= self._budgets["max_append_bytes"], "operational append capacity exhausted")
        try:
            self._assert_custody(row)
            written = row["stream"].write(raw)
            _require(written == len(raw), "operational append was short")
            self._assert_custody(row)
        except BaseException as error:
            self._failure = "operational persistence failure: " + type(error).__name__
            raise GuardianOperationalError(self._failure) from error
        row["digest"].update(raw)
        row["bytes"] += len(raw)

    def fail(self, reason: str) -> None:
        with self._lock:
            if self._failure is None:
                self._failure = str(reason)[:2048]

    def _event(self, row: dict[str, Any], core: dict[str, Any], cap: int) -> bytes:
        raw = _canonical(seal_guardian_event_v1(core, previous_sha256=row["sha"], study_scope=row.get("study_scope"))) + b"\n"
        _require(len(raw) <= cap, "operational event byte capacity exhausted")
        return raw

    def begin(self, message: Mapping[str, Any], route: tuple[str, str], protocol_mode: str,
              connection_seq: int, local_seq: int) -> int:
        with self._lock:
            try:
                _require(not self._closed and not self._finished and self._failure is None, self._failure or "operational recorder already finished")
                _require(route in self._routes, "operational request route invalid")
                _require(protocol_mode in {"gstreamer", "worker"}, "operational front protocol mode invalid")
                _integer(connection_seq, 1000000, "connection", 1)
                scope = self._headers[route].get("study_scope")
                _integer(local_seq, 6744 if scope is None else scope["max_requests_per_arm"], "local sequence", 1)
                _require(len(self._pending) < self._budgets["max_pending"], "operational pending capacity exhausted")
                _require(self._counts["requests_started"] < self._budgets["max_requests"], "operational request capacity exhausted")
                _require(self._seq + len(self._pending) + 2 <= self._budgets["max_events"], "operational event terminal reservation exhausted")
                frame = message["frame"]
                expected_type = "infer_request" if protocol_mode == "worker" else "analytics_execute"
                _require(message["message_type"] == expected_type and message["schema_version"] == 1
                         and frame["branch"] == route[0], "operational observed protocol/route drifted")
                worker_key = "worker_id" if protocol_mode == "worker" else "gstreamer_worker_id"
                stream = _integer(frame["stream_id"], 5, "observed stream")
                key = (expected_type, message["run_id"], message["arm_id"], message[worker_key], stream)
                row = self._routes[route]
                _require(key in row["lookup"], "operational observed worker/stream/context has no exact binding")
                if protocol_mode == "gstreamer":
                    _require(message["decision"]["selected_resource"] == route[1], "operational observed selected resource drifted")
                    decision = _text(message["decision"]["decision_id"], 157, "decision id")
                else:
                    _require(message["engine"] == ("openvino_cpu" if route[1] == "cpu" else "tensorrt_cuda"), "operational proxy engine drifted")
                    decision = None
                token = self._seq + 1
                core = {"type": "begin", "seq": token, "request_seq": self._counts["requests_started"] + 1,
                        "connection": connection_seq, "local_seq": local_seq, "binding": row["lookup"][key],
                        "request_id": _text(message["request_id"], 64, "request id"),
                        "input_key": _text(frame["input_frame_key"], 136, "input frame key"),
                        "frame_id": _integer(frame["frame_id"], 280 if scope is None else scope["max_frame_id"], "frame id"),
                        "pts_ns": _integer(frame["transport_pts_ns"], (1 << 64) - 1, "transport PTS"),
                        "decision_id": decision, "control_sha256": hashlib.sha256(_canonical(message)).hexdigest(),
                        "at_ns": _integer(self._clock_ns(), (1 << 64) - 1, "observed clock")}
                raw = self._event(row, core, self._budgets["max_begin_bytes"])
                reserve = self._budgets["terminal_reservation_bytes"]
                _require(row["bytes"] + row["pending"] * reserve + len(raw) + reserve <= self._budgets["max_route_bytes"], "operational route capacity exhausted")
                group_bytes = sum(item["bytes"] for item in self._routes.values())
                _require(group_bytes + len(self._pending) * reserve + len(raw) + reserve + 1048576 <= self._budgets["max_group_bytes"], "operational group capacity exhausted")
                self._write(row, raw)
                row["sha"] = json.loads(raw)["sha256"]
                row["pending"] += 1
                row["event_count"] += 1
                row["requests_started"] += 1
                self._pending[token] = (route, connection_seq)
                self._seq = token
                self._counts["event_count"] += 1
                self._counts["requests_started"] += 1
                return token
            except BaseException as error:
                self.fail(str(error))
                if isinstance(error, GuardianOperationalError):
                    raise
                raise GuardianOperationalError("operational begin validation failed") from error

    def terminal(self, token: int, response: Mapping[str, Any] | None, *, outcome: str, send: str, timings=None) -> None:
        with self._lock:
            try:
                _require(not self._finished and token in self._pending, "operational terminal has no unique pending begin")
                _require(outcome in {"completed", "failed"} and send in {"sent", "failed", "closed"}, "operational terminal outcome invalid")
                _require(outcome != "completed" or send == "sent", "operational completed terminal was not sent")
                route, _connection = self._pending[token]
                row = self._routes[route]
                core = {"seq": self._seq + 1, "begin_seq": token,
                        "at_ns": _integer(self._clock_ns(), (1 << 64) - 1, "observed clock"),
                        "response": None if response is None else hashlib.sha256(_canonical(response)).hexdigest(),
                        "outcome": outcome, "send": send}
                if row["study_scope"] is not None:
                    core["timings"] = timings
                else:
                    _require(timings is None, "legacy terminal cannot adopt study timing fields")
                raw = self._event(row, core, self._budgets["max_terminal_bytes"])
                _require(len(raw) <= self._budgets["terminal_reservation_bytes"], "operational terminal reservation exhausted")
                self._write(row, raw)
                row["sha"] = json.loads(raw)["sha256"]
                row["pending"] -= 1
                row["event_count"] += 1
                row["requests_" + outcome] += 1
                del self._pending[token]
                self._seq += 1
                self._counts["event_count"] += 1
                self._counts["requests_" + outcome] += 1
            except BaseException as error:
                self.fail(str(error))
                if isinstance(error, GuardianOperationalError):
                    raise
                raise GuardianOperationalError("operational terminal persistence failed") from error

    @property
    def headers(self) -> dict[tuple[str, str], dict[str, Any]]:
        return {route: json.loads(_canonical(header)) for route, header in self._headers.items()}

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return {**self._counts, "unfinished_requests": len(self._pending)}

    def capture_study_arm_v1(self, run_id, outdir, *, deadline):
        """Copy actual closed arm ranges from the idle held journals, without closing the pool."""
        from publication_operational_request_domain_v1 import expand_guardian_identity_v1, validate_guardian_event_v1
        with self._lock:
            _require(not self._closed and not self._finished and self._failure is None and not self._pending,
                "study journal snapshot requires a live idle original recorder")
            _require(all(h.get("study_scope") is not None for h in self._headers.values()),"journal snapshot requires separately typed study")
            out=Path(outdir);_require(out.is_dir() and not any(out.iterdir()),"journal snapshot output is not exclusive")
            decoded=[];ranges=[]
            for route,row in sorted(self._routes.items()):
                _require(time.monotonic()<deadline,"original campaign snapshot deadline")
                self._assert_custody(row);row["stream"].flush();os.fsync(row["stream"].fileno())
                before=os.stat(row["path"],follow_symlinks=False)
                with row["path"].open("rb") as source:
                    raw=source.read(self._budgets["max_route_bytes"]+1)
                    _require(len(raw)==row["bytes"] and hashlib.sha256(raw).hexdigest()==row["digest"].hexdigest(),"held journal snapshot digest/size")
                    after=os.fstat(source.fileno())
                fields=lambda value:(value.st_dev,value.st_ino,value.st_mode,value.st_nlink,value.st_size,value.st_mtime_ns,value.st_ctime_ns)
                _require(fields(before)==fields(after)==fields(os.stat(row["path"],follow_symlinks=False)),"idle original journal drifted")
                lines=raw.splitlines(keepends=True);header=json.loads(lines[0]);previous=header["sha256"];begins={};tokens=set();selected=[];offset=len(lines[0])
                for line in lines[1:]:
                    _require(time.monotonic()<deadline,"original journal snapshot deadline")
                    event=json.loads(line);validate_guardian_event_v1(event,previous_sha256=previous,study_scope=header["study_scope"])
                    previous=event["sha256"]
                    if "begin_seq" not in event:
                        identity=expand_guardian_identity_v1(header,event)
                        if identity["run_id"]==run_id:
                            begins[event["seq"]]=(identity,event);tokens.add(event["seq"])
                    elif event.get("begin_seq") in begins:
                        identity,begin=begins.pop(event["begin_seq"])
                        decoded.append({"identity":identity,"begin":begin,"terminal":event,"original_header":header,
                            "original_journal_path":str(row["path"]),"original_terminal_offset":offset})
                    if ("begin_seq" not in event and event["seq"] in tokens) or event.get("begin_seq") in tokens:
                        selected.append(line)
                    offset+=len(line)
                _require(not begins,"idle snapshot has unfinished original arm begins")
                path=out/(route[0]+"-"+route[1]+".original-range.jsonl")
                payload=lines[0]+b"".join(selected)
                with path.open("xb") as output:
                    _require(output.write(payload)==len(payload),"short original journal range copy");output.flush();os.fsync(output.fileno())
                ranges.append({"route":list(route),"path":str(path),"size_bytes":len(payload),"sha256":hashlib.sha256(payload).hexdigest(),
                    "original_journal_path":str(row["path"]),"original_prefix_size_bytes":len(raw),"original_prefix_sha256":hashlib.sha256(raw).hexdigest(),
                    "original_prefix_epochs":list(fields(before)),"range_is_complete_journal":False})
            _require(time.monotonic()<deadline,"original idle snapshot closed late")
            return {"decoded":decoded,"ranges":ranges}

    def finish(self, counters: Mapping[str, Any]) -> dict[str, Any]:
        with self._lock:
            _require(not self._finished, "operational recorder already finished")
            try:
                self._counts["connections_accepted"] = _integer(counters["connections_accepted"], 1000000, "accepted connections")
                for key in ("requests_started", "requests_completed", "requests_failed"):
                    _require(counters[key] == self._counts[key], "operational lifetime counter mismatch: " + key)
                if "requests_by_worker" in counters:
                    _require(counters["requests_by_worker"] == {route[0] + ":" + route[1]: row["requests_started"] for route, row in self._routes.items()}, "operational per-worker counter mismatch")
                if self._pending:
                    self.fail("operational unfinished requests remain")
                journals = []
                for route, row in sorted(self._routes.items()):
                    self._assert_custody(row)
                    row["stream"].flush()
                    os.fsync(row["stream"].fileno())
                    journals.append({"route": route[0] + ":" + route[1],
                        "path": str(row["path"]), "size_bytes": row["bytes"], "sha256": row["digest"].hexdigest(),
                        "event_count": row["event_count"], "requests_started": row["requests_started"],
                        "requests_completed": row["requests_completed"], "requests_failed": row["requests_failed"],
                        "unfinished_requests": row["pending"], "final_event_sha256": row["sha"]})
                first = next(iter(self._headers.values()))
                group = _sealed({"schema_version": 1, "artifact_kind": GROUP_KIND,
                    "lifecycle_id": first["lifecycle_id"], "accounting_input": first["descriptors"]["accounting_input"],
                    "journals": journals, "counts": self.snapshot(),
                    "max_clamp_ns": process_wall_clock().max_clamp_ns()})
                raw = _canonical(group) + b"\n"
                _require(len(raw) <= 1048576 and sum(row["bytes"] for row in self._routes.values()) + len(raw) <= self._budgets["max_group_bytes"], "operational companion/group capacity exhausted")
                path = self._outdir / "operational_group.v1.json"
                with self._open_exclusive(path.name) as output:
                    _require(output.write(raw) == len(raw), "operational companion write was short")
                    output.flush()
                    os.fsync(output.fileno())
                self._assert_custody()
                if self._directory_fd is not None:
                    os.fsync(self._directory_fd)
                self.group_descriptor = {"path": str(path), "size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
                self._finished = True
                self.close()
                _require(self._failure is None, self._failure or "operational recorder failed")
                return dict(self.group_descriptor)
            except BaseException as error:
                self.fail(str(error))
                self._finished = True
                self.close()
                if isinstance(error, GuardianOperationalError):
                    raise
                raise GuardianOperationalError("operational finish failed") from error

    def close(self) -> None:
        self._closed = True
        for row in getattr(self, "_routes", {}).values():
            if not row["stream"].closed:
                row["stream"].close()
        descriptor = getattr(self, "_directory_fd", None)
        if descriptor is not None:
            self._directory_fd = None
            os.close(descriptor)

    def __del__(self) -> None:
        self.close()

