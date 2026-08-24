#!/usr/bin/env python3
"""Physical OpenVINO GVA topology launcher (engineering-only).

Starts either 24 independent branch processes or six shared decode/tee graphs,
passes sealed post-preprocess Gst tensors into an injected execution bridge,
and proves common admission, reset, and terminal closure.  It never creates
accepted/publication evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import socket
import struct
import subprocess
import sys
import threading
import time
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from analytics_execution_protocol import (
    BRANCHES,
    ProtocolError,
    close_fds,
    receive_packet,
    send_packet,
    verify_sealed_memfd,
)


INDEPENDENT_PROCESSES = "independent_processes"
SHARED_VIDEO_DAG = "shared_video_dag"


GVA_SDK_BINDING = "intel_dl_streamer_gva_verified_preprocess_gst_buffer_v1"
GVA_TENSOR_ORIGIN = "verified_preprocess_src_pad"
GVA_PTS_ORIGIN = "GST_BUFFER_PTS"
ENGINEERING_CLAIM_STATUS = "engineering_openvino_gva_runtime_nonpublication"
ENGINEERING_BLOCKERS = (
    "openvino_gva_topology_engineering_runtime_not_accepted",
    "openvino_gva_native_policy_decision_evidence_not_bound",
    "openvino_gva_resource_v2_not_accepted",
    "openvino_gva_kpp_pilots_not_accepted",
    "openvino_gva_accepted_sidecars_not_written",
)
MESSAGE_READY = "openvino_gva_worker_ready"
MESSAGE_START = "openvino_gva_worker_start"
MESSAGE_TENSOR = "openvino_gva_verified_tensor"
MESSAGE_TERMINAL = "openvino_gva_bridge_terminal"
MESSAGE_DRAINED = "openvino_gva_worker_drained"
MESSAGE_CLOSE = "openvino_gva_worker_close"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_STABLE_RE = re.compile(r"^[A-Za-z0-9._-]{1,160}$")
_TENSOR_MESSAGE_FIELDS = {
    "schema_version", "message_type", "worker_id", "topology_kind",
    "stream_id", "branch", "context", "tensor_descriptor", "tensor",
    "gst_evidence",
}


class ExecutionBridgeLike(Protocol):
    def handshake_all(self) -> Mapping[str, Any]: ...

    def execute(self, *, context: Mapping[str, Any], tensor: bytes,
                tensor_descriptor: Mapping[str, Any]) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class GVAWorkerSpec:
    worker_id: str
    topology_kind: str
    stream_id: int
    branches: tuple[str, ...]


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ProtocolError(message)


def _sha(value: Any, label: str) -> str:
    result = str(value or "")
    _require(_SHA256_RE.fullmatch(result) is not None, f"{label} must be a lowercase SHA-256")
    return result


def _stable(value: Any, label: str) -> str:
    result = str(value or "")
    _require(_STABLE_RE.fullmatch(result) is not None, f"{label} is invalid")
    return result


def _exact(value: Any, fields: set[str], label: str) -> Mapping[str, Any]:
    _require(isinstance(value, Mapping), f"{label} must be a mapping")
    _require(set(value) == fields, f"{label} fields have drifted")
    return value


def _validate_spec(spec: GVAWorkerSpec) -> GVAWorkerSpec:
    _require(isinstance(spec, GVAWorkerSpec), "GVA worker spec is invalid")
    _stable(spec.worker_id, "GVA worker_id")
    _require(type(spec.stream_id) is int and 0 <= spec.stream_id < 6,
             "GVA worker stream_id is invalid")
    _require(bool(spec.branches) and len(spec.branches) == len(set(spec.branches))
             and all(branch in BRANCHES for branch in spec.branches),
             "GVA worker branches are invalid")
    if spec.topology_kind == INDEPENDENT_PROCESSES:
        _require(len(spec.branches) == 1, "independent GVA worker must own one branch")
    elif spec.topology_kind == SHARED_VIDEO_DAG:
        _require(spec.branches == tuple(BRANCHES),
                 "shared GVA graph must own exact four branches")
    else:
        raise ProtocolError("GVA worker topology kind is invalid")
    return spec


def build_openvino_gva_worker_specs(
    topology_kind: str, *, stream_count: int = 6,
) -> tuple[GVAWorkerSpec, ...]:
    """Return the exact physical process inventory for one topology arm."""

    _require(type(stream_count) is int and 1 <= stream_count <= 6,
             "GVA stream_count must be in 1..6")
    specs: list[GVAWorkerSpec] = []
    if topology_kind == INDEPENDENT_PROCESSES:
        for stream_id in range(stream_count):
            for branch in BRANCHES:
                specs.append(GVAWorkerSpec(
                    f"gva-stream-{stream_id}-branch-{branch}", topology_kind,
                    stream_id, (branch,),
                ))
    elif topology_kind == SHARED_VIDEO_DAG:
        for stream_id in range(stream_count):
            specs.append(GVAWorkerSpec(
                f"gva-stream-{stream_id}-shared-graph", topology_kind,
                stream_id, tuple(BRANCHES),
            ))
    else:
        raise ProtocolError("GVA topology kind is invalid")
    result = tuple(_validate_spec(spec) for spec in specs)
    _require(len({spec.worker_id for spec in result}) == len(result),
             "GVA worker IDs are not unique")
    return result


def build_dispatch_contexts(
    *,
    specs: Sequence[GVAWorkerSpec],
    run_id: str,
    arm_id: str,
    codec: str,
    payload_sha256: str,
    preprocessing_contract_sha256: str,
    transport_pts_ns: int,
    resource_by_branch: Mapping[str, str] | None = None,
    deadline_monotonic_ns: int | None = None,
) -> dict[tuple[str, str], dict[str, Any]]:
    """Bind every branch tensor to one per-stream direct admission identity."""

    values = tuple(_validate_spec(spec) for spec in specs)
    _require(bool(values), "GVA dispatch contexts require worker specs")
    normalized_codec = str(codec).strip().lower().replace("hevc", "h265")
    _require(normalized_codec in {"h264", "h265"}, "GVA dispatch codec is invalid")
    payload_sha = _sha(payload_sha256, "GVA admitted payload sha256")
    preprocess_sha = _sha(preprocessing_contract_sha256, "GVA preprocessing sha256")
    normalized_run_id = _stable(run_id, "GVA run_id")
    normalized_arm_id = _stable(arm_id, "GVA arm_id")
    _require(type(transport_pts_ns) is int and transport_pts_ns >= 0,
             "GVA transport PTS is invalid")
    resources = dict(resource_by_branch or {
        "plate_number": "cpu", "vehicle_type": "cpu",
        "damage": "gpu", "foreign_object": "gpu",
    })
    _require(set(resources) == set(BRANCHES),
             "GVA resource map must cover exact branches")
    _require(set(resources.values()) <= {"cpu", "gpu"},
             "GVA resource map is invalid")
    deadline = deadline_monotonic_ns or (time.monotonic_ns() + 300_000_000_000)
    _require(type(deadline) is int and deadline > time.monotonic_ns(),
             "GVA deadline is not in the future")

    result: dict[tuple[str, str], dict[str, Any]] = {}
    for spec in values:
        admission_id = (
            f"admission-{normalized_codec}-stream-{spec.stream_id}-"
            f"{payload_sha[:16]}"
        )
        input_frame_key = (
            f"engineering-{normalized_codec}-stream-{spec.stream_id}-frame-0"
        )
        trace_id = f"{normalized_run_id}:{spec.stream_id}:0:{spec.worker_id}"
        for sequence, branch in enumerate(spec.branches, start=1):
            resource = resources[branch]
            decision_payload = {
                "claim_status": "engineering_synthetic_resource_selection_nonpublication",
                "worker_id": spec.worker_id,
                "branch": branch,
                "resource": resource,
                "preprocessing_contract_sha256": preprocess_sha,
            }
            decision_sha = hashlib.sha256(json.dumps(
                decision_payload, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")).hexdigest()
            result[(spec.worker_id, branch)] = {
                "sdk_binding": GVA_SDK_BINDING,
                "tensor_origin": GVA_TENSOR_ORIGIN,
                "pts_origin": GVA_PTS_ORIGIN,
                "run_id": normalized_run_id,
                "arm_id": normalized_arm_id,
                "request_id": f"request-{spec.worker_id}-{branch}-0",
                "topology_kind": spec.topology_kind,
                "topology_worker_id": spec.worker_id,
                "topology_worker_trace_id": trace_id,
                "event_sequence": sequence,
                "stream_id": spec.stream_id,
                "frame_id": 0,
                "input_frame_key": input_frame_key,
                "transport_pts_ns": transport_pts_ns,
                "branch": branch,
                "selected_resource": resource,
                "parent_execution_id": (
                    f"{trace_id}:{branch}:fanout"
                    if spec.topology_kind == SHARED_VIDEO_DAG
                    else f"{trace_id}:{branch}:preprocess"
                ),
                "terminal_execution_id": f"{trace_id}:{branch}:terminal",
                "admission_id": admission_id,
                "payload_sha256": payload_sha,
                "policy_decision_id": (
                    f"engineering-{spec.worker_id}-{branch}-{resource}"
                ),
                "policy_decision_sha256": decision_sha,
                "deadline_monotonic_ns": deadline,
            }
    return result


def dispatch_verified_tensor(
    *,
    bridge: ExecutionBridgeLike,
    spec: GVAWorkerSpec,
    message: Mapping[str, Any],
    fds: Sequence[int],
    expected_context: Mapping[str, Any],
) -> dict[str, Any]:
    """Verify Gst provenance + sealed ownership, then call the ready bridge."""

    checked_spec = _validate_spec(spec)
    descriptors = list(fds)
    try:
        _require(len(descriptors) == 1,
                 "GVA verified tensor requires exactly one sealed memfd")
        raw = _exact(message, _TENSOR_MESSAGE_FIELDS,
                     "GVA verified tensor message")
        _require(raw["schema_version"] == 1
                 and raw["message_type"] == MESSAGE_TENSOR,
                 "GVA tensor header is invalid")
        _require(raw["worker_id"] == checked_spec.worker_id,
                 "GVA tensor worker_id mismatch")
        _require(raw["topology_kind"] == checked_spec.topology_kind,
                 "GVA tensor topology mismatch")
        _require(raw["stream_id"] == checked_spec.stream_id,
                 "GVA tensor stream mismatch")
        branch = str(raw["branch"])
        _require(branch in checked_spec.branches,
                 "GVA tensor branch is a relabel")
        context = raw["context"]
        _require(isinstance(context, Mapping), "GVA tensor context is invalid")
        _require(
            dict(context) == dict(expected_context),
            "GVA tensor does not match the launcher-owned dispatch context",
        )
        _require(
            context.get("topology_worker_id") == checked_spec.worker_id
            and context.get("topology_kind") == checked_spec.topology_kind
            and context.get("stream_id") == checked_spec.stream_id
            and context.get("branch") == branch,
            "GVA tensor context coordinate mismatch",
        )
        tensor = _exact(raw["tensor"], {"byte_length", "sha256"},
                        "GVA tensor payload")
        byte_length = tensor["byte_length"]
        _require(type(byte_length) is int and byte_length > 0,
                 "GVA tensor byte length is invalid")
        tensor_sha = _sha(tensor["sha256"], "GVA tensor sha256")
        gst = _exact(
            raw["gst_evidence"],
            {"caps", "buffer_pts_ns", "buffer_size", "map_mode",
             "origin_element"},
            "GVA Gst evidence",
        )
        _require(str(gst["caps"]).startswith("other/tensors"),
                 "GVA Gst caps are not tensors")
        _require(gst["buffer_pts_ns"] == context.get("transport_pts_ns"),
                 "GVA GST_BUFFER_PTS mismatch")
        _require(gst["buffer_size"] == byte_length,
                 "GVA GstBuffer size mismatch")
        _require(gst["map_mode"] == "GST_MAP_READ_copied_before_unmap",
                 "GVA GstBuffer ownership is not detached")
        _require(gst["origin_element"] == f"gva_tensor_convert_{branch}",
                 "GVA tensor origin element mismatch")
        payload = verify_sealed_memfd(
            descriptors[0], expected_bytes=byte_length,
            expected_sha256=tensor_sha,
        )
        result = bridge.execute(
            context=context, tensor=payload,
            tensor_descriptor=raw["tensor_descriptor"],
        )
        _require(isinstance(result, Mapping), "GVA bridge result is invalid")
        value = dict(result)
        _require(value.get("publication_ready") is False,
                 "GVA engineering bridge claimed publication readiness")
        _require(value.get("accepted_evidence_written") is False,
                 "GVA engineering bridge wrote accepted evidence")
        terminal = value.get("terminal_event")
        _require(
            isinstance(terminal, Mapping)
            and terminal.get("protocol_version") == 3
            and terminal.get("event_kind") in {"branch_complete", "branch_drop"}
            and terminal.get("worker_id") == checked_spec.worker_id
            and terminal.get("branch_id") == branch,
            "GVA bridge terminal is invalid",
        )
        return value
    finally:
        close_fds(descriptors)


def _record_by_worker(
    records: Sequence[Mapping[str, Any]], *, expected_workers: set[str],
    label: str,
) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for record in records:
        worker_id = str(record.get("worker_id") or "")
        _require(worker_id in expected_workers and worker_id not in result,
                 f"GVA {label} worker coverage is invalid")
        result[worker_id] = record
    _require(set(result) == expected_workers,
             f"GVA {label} worker coverage is incomplete")
    return result


def audit_openvino_gva_run(
    *,
    specs: Sequence[GVAWorkerSpec],
    ready_records: Sequence[Mapping[str, Any]],
    drained_records: Sequence[Mapping[str, Any]],
    terminal_results: Mapping[tuple[str, str], Mapping[str, Any]],
    peer_pids: Mapping[str, int],
    dispatch_contexts: Mapping[tuple[str, str], Mapping[str, Any]] | None = None,
    require_full_publication_topology: bool = True,
) -> dict[str, Any]:
    """Fail closed on physical topology, common admission, reset and terminals."""

    values = tuple(_validate_spec(spec) for spec in specs)
    _require(bool(values), "GVA run audit requires worker specs")
    workers = {spec.worker_id for spec in values}
    _require(len(workers) == len(values),
             "GVA run audit worker IDs are duplicated")
    topologies = {spec.topology_kind for spec in values}
    _require(len(topologies) == 1, "GVA run audit mixes topologies")
    topology_kind = next(iter(topologies))
    if require_full_publication_topology:
        _require(
            {spec.stream_id for spec in values} == set(range(6)),
            "GVA publication topology requires exactly six streams",
        )
    expected_count = len({spec.stream_id for spec in values}) * (
        len(BRANCHES) if topology_kind == INDEPENDENT_PROCESSES else 1
    )
    _require(len(values) == expected_count,
             "GVA physical process topology is incomplete")
    _require(set(peer_pids) == workers,
             "GVA SO_PEERCRED coverage is incomplete")
    _require(all(type(pid) is int and pid > 0 for pid in peer_pids.values())
             and len(set(peer_pids.values())) == len(values),
             "GVA physical processes do not have distinct positive peer PIDs")
    ready = _record_by_worker(
        ready_records, expected_workers=workers, label="READY"
    )
    drained = _record_by_worker(
        drained_records, expected_workers=workers, label="DRAINED"
    )
    for spec in values:
        pid = peer_pids[spec.worker_id]
        row = ready[spec.worker_id]
        _require(
            row.get("schema_version") == 1
            and row.get("message_type") == MESSAGE_READY
            and row.get("pid") == pid
            and row.get("topology_kind") == spec.topology_kind
            and row.get("stream_id") == spec.stream_id
            and row.get("branches") == list(spec.branches),
            f"GVA READY binding drifted for {spec.worker_id}",
        )
        pipeline = row.get("pipeline")
        _require(isinstance(pipeline, Mapping),
                 "GVA READY pipeline evidence is invalid")
        shared = spec.topology_kind == SHARED_VIDEO_DAG
        _require(
            pipeline.get("fresh_pipeline_count") == 1
            and pipeline.get("decoder_count") == 1
            and pipeline.get("tee_count") == (1 if shared else 0)
            and pipeline.get("tensor_convert_count") == len(spec.branches)
            and pipeline.get("appsink_count") == len(spec.branches)
            and pipeline.get("post_preprocess_binding")
            == "dlstreamer_tensor_convert_src_to_appsink_v1",
            f"GVA pipeline topology evidence drifted for {spec.worker_id}",
        )
        end = drained[spec.worker_id]
        reset = end.get("reset")
        _require(
            end.get("schema_version") == 1
            and end.get("message_type") == MESSAGE_DRAINED
            and end.get("pid") == pid
            and end.get("terminal_branches") == list(spec.branches)
            and isinstance(reset, Mapping),
            f"GVA DRAINED binding drifted for {spec.worker_id}",
        )
        _require(
            reset.get("fresh_pipeline_count") == 1
            and reset.get("start_state") == "NULL"
            and reset.get("pre_start_queue_depths")
            == {branch: 0 for branch in spec.branches}
            and reset.get("admission_stopped_before_drain") is True
            and reset.get("terminal_state") == "DRAINED"
            and reset.get("post_stop_state") == "NULL"
            and reset.get("post_stop_queue_depths")
            == {branch: 0 for branch in spec.branches},
            f"GVA reset closure drifted for {spec.worker_id}",
        )

    expected_terminals = {
        (spec.worker_id, branch) for spec in values for branch in spec.branches
    }
    _require(set(terminal_results) == expected_terminals,
             "GVA terminal coverage is incomplete")
    for (worker_id, branch), result in terminal_results.items():
        terminal = result.get("terminal_event")
        _require(
            result.get("publication_ready") is False
            and result.get("accepted_evidence_written") is False
            and isinstance(terminal, Mapping)
            and terminal.get("protocol_version") == 3
            and terminal.get("worker_id") == worker_id
            and terminal.get("branch_id") == branch
            and terminal.get("event_kind") in {"branch_complete", "branch_drop"},
            f"GVA terminal closure drifted for {worker_id}/{branch}",
        )

    _require(
        dispatch_contexts is not None,
        "GVA dispatch contexts are required for a completed topology audit",
    )
    _require(set(dispatch_contexts) == expected_terminals,
             "GVA common admission context coverage is incomplete")
    by_stream: dict[int, list[Mapping[str, Any]]] = {}
    spec_by_worker = {spec.worker_id: spec for spec in values}
    for (worker_id, branch), context in dispatch_contexts.items():
        spec = spec_by_worker[worker_id]
        _require(
            context.get("stream_id") == spec.stream_id
            and context.get("branch") == branch
            and context.get("topology_worker_id") == worker_id,
            "GVA common admission context coordinate drifted",
        )
        terminal = terminal_results[(worker_id, branch)]["terminal_event"]
        _require(
            terminal.get("sequence") == context.get("event_sequence")
            and terminal.get("run_id") == context.get("run_id")
            and terminal.get("trace_id") == context.get("topology_worker_trace_id")
            and terminal.get("stream_id") == context.get("stream_id")
            and terminal.get("frame_id") == context.get("frame_id")
            and terminal.get("input_frame_key") == context.get("input_frame_key")
            and terminal.get("topology_kind") == context.get("topology_kind")
            and terminal.get("execution_id") == context.get("terminal_execution_id")
            and terminal.get("parent_execution_ids")
            == [context.get("parent_execution_id")]
            and terminal.get("admission_id") == context.get("admission_id")
            and terminal.get("payload_sha256") == context.get("payload_sha256"),
            f"GVA terminal is not bound to dispatch context for {worker_id}/{branch}",
        )
        by_stream.setdefault(spec.stream_id, []).append(context)
    for contexts in by_stream.values():
        _require(
            len({str(value.get("admission_id")) for value in contexts}) == 1
            and len({str(value.get("payload_sha256")) for value in contexts}) == 1
            and len({int(value.get("transport_pts_ns")) for value in contexts}) == 1,
            "GVA workers did not consume one common admission per stream",
        )
    common_admission_verified = True

    return {
        "schema_version": 1,
        "artifact_kind": "vast_openvino_gva_topology_runtime_audit",
        "claim_status": ENGINEERING_CLAIM_STATUS,
        "topology_kind": topology_kind,
        "physical_process_count": len(values),
        "distinct_peer_pid_count": len(set(peer_pids.values())),
        "stream_count": len({spec.stream_id for spec in values}),
        "terminal_count": len(terminal_results),
        "common_admission_required": True,
        "common_admission_verified": common_admission_verified,
        "reset_and_terminal_closure_verified": True,
        "engineering_runtime_complete": common_admission_verified,
        "publication_ready": False,
        "accepted_evidence_written": False,
        "publication_blockers": list(ENGINEERING_BLOCKERS),
    }


def _peer_pid(connection: socket.socket) -> int:
    _require(hasattr(socket, "SO_PEERCRED"),
             "GVA launcher requires Linux SO_PEERCRED")
    size = struct.calcsize("3i")
    credentials = connection.getsockopt(
        socket.SOL_SOCKET, socket.SO_PEERCRED, size
    )
    pid, _uid, _gid = struct.unpack("3i", credentials)
    _require(pid > 0, "GVA launcher peer PID is invalid")
    return int(pid)


def _adapter_config(
    *,
    spec: GVAWorkerSpec,
    codec: str,
    source_path: Path,
    source_sha256: str,
    socket_path: Path,
    width: int,
    height: int,
    preprocessing_contract_sha256: str,
    contexts: Mapping[tuple[str, str], Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "artifact_kind": "vast_openvino_gva_adapter_config",
        "worker": {
            "worker_id": spec.worker_id,
            "topology_kind": spec.topology_kind,
            "stream_id": spec.stream_id,
            "branches": list(spec.branches),
        },
        "codec": codec,
        "source_path": str(source_path),
        "source_sha256": source_sha256,
        "socket_path": str(socket_path),
        "width": width,
        "height": height,
        "preprocessing_contract_sha256": preprocessing_contract_sha256,
        "contexts": {
            branch: dict(contexts[(spec.worker_id, branch)])
            for branch in spec.branches
        },
    }


def run_openvino_gva_topology(
    *,
    bridge: ExecutionBridgeLike,
    topology_kind: str,
    codec: str,
    source_path: Path,
    preprocessing_contract_sha256: str,
    work_root: Path,
    adapter_path: Path,
    python_executable: str = sys.executable,
    stream_count: int = 6,
    require_full_publication_topology: bool = True,
    width: int = 224,
    height: int = 224,
    timeout_s: float = 90.0,
) -> dict[str, Any]:
    """Launch physical processes, bridge every tensor, and prove closure."""

    _require(os.name == "posix", "GVA topology launcher requires Linux")
    work = work_root.resolve()
    _require(work == Path("/tmp") or Path("/tmp") in work.parents,
             "GVA launcher output must stay under /tmp")
    work.mkdir(parents=True, exist_ok=True)
    source = source_path.resolve()
    _require(source.is_file(), "GVA launcher source fixture is missing")
    source_payload = source.read_bytes()
    _require(bool(source_payload), "GVA launcher source fixture is empty")
    source_sha256 = hashlib.sha256(source_payload).hexdigest()
    preprocess_sha = _sha(preprocessing_contract_sha256,
                          "GVA preprocessing sha256")
    normalized_codec = str(codec).strip().lower().replace("hevc", "h265")
    _require(normalized_codec in {"h264", "h265"},
             "GVA launcher codec is invalid")
    specs = build_openvino_gva_worker_specs(
        topology_kind, stream_count=stream_count
    )
    if require_full_publication_topology:
        _require(
            stream_count == 6,
            "GVA full engineering topology requires exactly six streams",
        )
    run_id = (
        f"run-gva-{normalized_codec}-"
        f"{topology_kind.replace('_', '-')}-{os.getpid()}"
    )
    arm_id = f"arm-gva-{normalized_codec}-{topology_kind.replace('_', '-')}"
    contexts = build_dispatch_contexts(
        specs=specs,
        run_id=run_id,
        arm_id=arm_id,
        codec=normalized_codec,
        payload_sha256=source_sha256,
        preprocessing_contract_sha256=preprocess_sha,
        transport_pts_ns=333_333_333,
    )
    handshake = dict(bridge.handshake_all())
    _require(handshake.get("publication_ready") is False
             and handshake.get("accepted_evidence_written") is False,
             "GVA bridge handshake escaped engineering-only scope")
    socket_path = work / "launcher.sock"
    if socket_path.exists():
        socket_path.unlink()
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    listener.bind(str(socket_path))
    listener.listen(len(specs))
    listener.settimeout(timeout_s)

    processes: dict[str, subprocess.Popen[str]] = {}
    connections: dict[str, socket.socket] = {}
    ready_records: list[dict[str, Any]] = []
    peer_pids: dict[str, int] = {}
    drained_records: list[dict[str, Any]] = []
    terminal_results: dict[tuple[str, str], dict[str, Any]] = {}
    result_lock = threading.Lock()
    bridge_lock = threading.Lock()
    deadline = time.monotonic() + timeout_s
    try:
        for spec in specs:
            config_path = work / f"{spec.worker_id}.json"
            config_path.write_text(
                json.dumps(_adapter_config(
                    spec=spec,
                    codec=normalized_codec,
                    source_path=source,
                    source_sha256=source_sha256,
                    socket_path=socket_path,
                    width=width,
                    height=height,
                    preprocessing_contract_sha256=preprocess_sha,
                    contexts=contexts,
                ), sort_keys=True, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )
            environment = dict(os.environ)
            environment["PYTHONDONTWRITEBYTECODE"] = "1"
            environment["TMPDIR"] = str(work)
            registry_template = Path(
                environment.get(
                    "VAST_GST_REGISTRY_TEMPLATE",
                    "/opt/vast/share/gstreamer-registry.bin",
                )
            )
            if registry_template.is_file():
                environment["GST_REGISTRY"] = str(registry_template)
                environment["GST_REGISTRY_UPDATE"] = "no"
            processes[spec.worker_id] = subprocess.Popen(
                (python_executable, str(adapter_path),
                 "--config", str(config_path)),
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                close_fds=True,
            )

        expected_by_id = {spec.worker_id: spec for spec in specs}
        while len(connections) < len(specs):
            _require(time.monotonic() < deadline,
                     "GVA READY barrier timed out")
            try:
                connection, _ = listener.accept()
            except TimeoutError as error:
                process_errors: list[str] = []
                for worker_id, process in processes.items():
                    state = process.poll()
                    if state is None:
                        continue
                    stdout, stderr = process.communicate()
                    process_errors.append(
                        f"{worker_id}:rc={state}:stdout={stdout.strip()}:"
                        f"stderr={stderr.strip()}"
                    )
                detail = " | ".join(process_errors) or "no adapter exited"
                raise ProtocolError(
                    f"GVA READY barrier timed out; {detail}"
                ) from error
            connection.settimeout(max(1.0, deadline - time.monotonic()))
            message, fds = receive_packet(connection, expected_fds=0)
            close_fds(fds)
            worker_id = str(message.get("worker_id") or "")
            _require(worker_id in expected_by_id
                     and worker_id not in connections,
                     "GVA READY worker is unknown or duplicated")
            pid = _peer_pid(connection)
            _require(message.get("pid") == pid == processes[worker_id].pid,
                     f"GVA READY SO_PEERCRED/Popen PID mismatch for {worker_id}")
            connections[worker_id] = connection
            peer_pids[worker_id] = pid
            ready_records.append(dict(message))

        for connection in connections.values():
            send_packet(connection, {
                "schema_version": 1, "message_type": MESSAGE_START,
            })

        def serve_worker(spec: GVAWorkerSpec) -> None:
            connection = connections[spec.worker_id]
            while True:
                message, fds = receive_packet(connection)
                kind = str(message.get("message_type") or "")
                if kind == MESSAGE_TENSOR:
                    with bridge_lock:
                        terminal = dispatch_verified_tensor(
                            bridge=bridge, spec=spec,
                            message=message, fds=fds,
                            expected_context=contexts[
                                (spec.worker_id, str(message.get("branch") or ""))
                            ],
                        )
                    key = (spec.worker_id, str(message["branch"]))
                    with result_lock:
                        _require(key not in terminal_results,
                                 "GVA launcher received duplicate terminal")
                        terminal_results[key] = terminal
                    send_packet(connection, {
                        "schema_version": 1,
                        "message_type": MESSAGE_TERMINAL,
                        "worker_id": spec.worker_id,
                        "branch": key[1],
                        "result": terminal,
                    })
                    continue
                close_fds(fds)
                _require(kind == MESSAGE_DRAINED,
                         f"GVA worker {spec.worker_id} sent an unexpected message")
                with result_lock:
                    drained_records.append(dict(message))
                send_packet(connection, {
                    "schema_version": 1, "message_type": MESSAGE_CLOSE,
                })
                return

        with ThreadPoolExecutor(max_workers=len(specs)) as executor:
            futures = [executor.submit(serve_worker, spec) for spec in specs]
            for future in futures:
                future.result(timeout=max(1.0, deadline - time.monotonic()))

        process_errors: list[str] = []
        for spec in specs:
            process = processes[spec.worker_id]
            stdout, stderr = process.communicate(
                timeout=max(1.0, deadline - time.monotonic())
            )
            if process.returncode != 0 or stdout.strip():
                process_errors.append(
                    f"{spec.worker_id}:rc={process.returncode}:"
                    f"stdout={stdout.strip()}:stderr={stderr.strip()}"
                )
        _require(not process_errors,
                 "GVA adapter process failure: " + " | ".join(process_errors))
        audit = audit_openvino_gva_run(
            specs=specs,
            ready_records=ready_records,
            drained_records=drained_records,
            terminal_results=terminal_results,
            peer_pids=peer_pids,
            dispatch_contexts=contexts,
            require_full_publication_topology=require_full_publication_topology,
        )
        return {
            "schema_version": 1,
            "artifact_kind": "vast_openvino_gva_topology_runtime_result",
            "claim_status": ENGINEERING_CLAIM_STATUS,
            "codec": normalized_codec,
            "source_sha256": source_sha256,
            "bridge_handshake": handshake,
            "audit": audit,
            "worker_pids": dict(sorted(peer_pids.items())),
            "publication_ready": False,
            "accepted_evidence_written": False,
            "publication_blockers": list(ENGINEERING_BLOCKERS),
        }
    finally:
        for connection in connections.values():
            try:
                connection.close()
            except OSError:
                pass
        listener.close()
        if socket_path.exists():
            socket_path.unlink()
        for process in processes.values():
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)


class EngineeringSyntheticBridge:
    """Deterministic canary bridge; never native-model inference evidence."""

    def handshake_all(self) -> dict[str, Any]:
        return {
            "claim_status": "engineering_synthetic_bridge_handshake_nonpublication",
            "publication_ready": False,
            "accepted_evidence_written": False,
        }

    def execute(self, *, context: Mapping[str, Any], tensor: bytes,
                tensor_descriptor: Mapping[str, Any]) -> dict[str, Any]:
        payload = bytes(tensor)
        _require(bool(payload), "synthetic bridge tensor is empty")
        _require(tensor_descriptor.get("contiguous") is True,
                 "synthetic bridge tensor is not contiguous")
        return {
            "schema_version": 1,
            "artifact_kind": "vast_openvino_gva_execution_bridge_result",
            "claim_status": "engineering_synthetic_terminal_nonpublication",
            "branch": context["branch"],
            "selected_resource": context["selected_resource"],
            "input_sha256": hashlib.sha256(payload).hexdigest(),
            "publication_ready": False,
            "accepted_evidence_written": False,
            "terminal_event": {
                "protocol_version": 3,
                "worker_id": context["topology_worker_id"],
                "sequence": context["event_sequence"],
                "run_id": context["run_id"],
                "trace_id": context["topology_worker_trace_id"],
                "stream_id": context["stream_id"],
                "frame_id": context["frame_id"],
                "input_frame_key": context["input_frame_key"],
                "topology_kind": context["topology_kind"],
                "event_kind": "branch_complete",
                "stage": context["branch"],
                "branch_id": context["branch"],
                "execution_id": context["terminal_execution_id"],
                "parent_execution_ids": [context["parent_execution_id"]],
                "timestamp_ms": int(time.monotonic_ns() // 1_000_000),
                "admission_id": context["admission_id"],
                "payload_sha256": context["payload_sha256"],
                "terminal_reason": "engineering_synthetic_bridge_completed",
                "objects": 0,
                "detector": "engineering-synthetic-bridge",
                "backend": "engineering-synthetic-bridge",
            },
        }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engineering-self-smoke", action="store_true")
    parser.add_argument(
        "--topology", choices=(INDEPENDENT_PROCESSES, SHARED_VIDEO_DAG)
    )
    parser.add_argument("--codec", choices=("h264", "h265"))
    parser.add_argument("--source", type=Path)
    parser.add_argument("--work-root", type=Path)
    parser.add_argument("--adapter", type=Path)
    parser.add_argument("--width", type=int, default=32)
    parser.add_argument("--height", type=int, default=32)
    args = parser.parse_args(argv)
    _require(args.engineering_self_smoke,
             "launcher CLI is restricted to explicit engineering self-smoke")
    _require(args.topology and args.codec and args.source
             and args.work_root and args.adapter,
             "self-smoke arguments are incomplete")
    preprocessing_sha = hashlib.sha256(
        f"engineering-dlstreamer-bgr-uint8-"
        f"{args.width}x{args.height}-nhwc-v1".encode("ascii")
    ).hexdigest()
    result = run_openvino_gva_topology(
        bridge=EngineeringSyntheticBridge(),
        topology_kind=args.topology,
        codec=args.codec,
        source_path=args.source,
        preprocessing_contract_sha256=preprocessing_sha,
        work_root=args.work_root,
        adapter_path=args.adapter,
        width=args.width,
        height=args.height,
    )
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ENGINEERING_BLOCKERS",
    "ENGINEERING_CLAIM_STATUS",
    "EngineeringSyntheticBridge",
    "GVAWorkerSpec",
    "INDEPENDENT_PROCESSES",
    "SHARED_VIDEO_DAG",
    "audit_openvino_gva_run",
    "build_dispatch_contexts",
    "build_openvino_gva_worker_specs",
    "dispatch_verified_tensor",
    "run_openvino_gva_topology",
]
