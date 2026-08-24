#!/usr/bin/env python3
"""Real GStreamer/DL Streamer adapter for the OpenVINO GVA execution bridge.

One process owns one decoder graph.  An independent-process worker owns one
branch, while a shared-video-DAG worker owns one decoder/preprocess prefix and
one tee feeding the four analytics branches.  The mapped ``other/tensors``
buffer is copied before unmap, sealed in a memfd, and sent to the launcher.

This is engineering runtime plumbing only.  It does not create accepted
benchmark evidence or assert publication readiness.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import socket
import sys
import threading
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from analytics_execution_protocol import (
    BRANCHES,
    ProtocolError,
    close_fds,
    create_sealed_memfd,
    receive_packet,
    send_packet,
)


INDEPENDENT_PROCESSES = "independent_processes"
SHARED_VIDEO_DAG = "shared_video_dag"


ADAPTER_BINDING = "dlstreamer_tensor_convert_src_to_appsink_v1"
ADAPTER_MESSAGE_READY = "openvino_gva_worker_ready"
ADAPTER_MESSAGE_START = "openvino_gva_worker_start"
ADAPTER_MESSAGE_TENSOR = "openvino_gva_verified_tensor"
ADAPTER_MESSAGE_TERMINAL = "openvino_gva_bridge_terminal"
ADAPTER_MESSAGE_DRAINED = "openvino_gva_worker_drained"
ADAPTER_MESSAGE_CLOSE = "openvino_gva_worker_close"
ADAPTER_MESSAGE_ERROR = "openvino_gva_worker_error"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_STABLE_RE = re.compile(r"^[A-Za-z0-9._-]{1,160}$")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ProtocolError(message)


def _stable(value: Any, label: str) -> str:
    result = str(value or "")
    _require(_STABLE_RE.fullmatch(result) is not None, f"{label} is invalid")
    return result


def _sha(value: Any, label: str) -> str:
    result = str(value or "")
    _require(_SHA256_RE.fullmatch(result) is not None, f"{label} must be a lowercase SHA-256")
    return result


def _branches(values: Sequence[Any]) -> tuple[str, ...]:
    result = tuple(str(value) for value in values)
    _require(bool(result) and len(result) == len(set(result)), "GVA adapter branches must be unique")
    _require(all(value in BRANCHES for value in result), "GVA adapter branch is invalid")
    return result


def _branch_chain(branch: str) -> str:
    return (
        f"queue name=gva_branch_queue_{branch} max-size-buffers=1 "
        "max-size-bytes=0 max-size-time=0 leaky=no "
        f"! tensor_convert name=gva_tensor_convert_{branch} "
        f"! appsink name=gva_tensor_sink_{branch} emit-signals=true "
        "max-buffers=1 leaky-type=none sync=false async=false wait-on-eos=true"
    )


def build_gst_pipeline(
    *,
    topology_kind: str,
    codec: str,
    branches: Sequence[str],
    width: int = 224,
    height: int = 224,
) -> str:
    """Build one genuine decode/preprocess/tensor graph with exact topology."""

    branch_values = _branches(branches)
    normalized_codec = str(codec).strip().lower().replace("hevc", "h265")
    _require(normalized_codec in {"h264", "h265"}, "GVA adapter codec must be h264 or h265")
    _require(type(width) is int and width > 0, "GVA adapter width must be positive")
    _require(type(height) is int and height > 0, "GVA adapter height must be positive")
    if topology_kind == INDEPENDENT_PROCESSES:
        _require(len(branch_values) == 1, "independent GVA adapter must own exactly one branch")
    elif topology_kind == SHARED_VIDEO_DAG:
        _require(branch_values == tuple(BRANCHES), "shared GVA adapter must own the exact four branches")
    else:
        raise ProtocolError("GVA adapter topology kind is invalid")

    media_type = "video/x-h264" if normalized_codec == "h264" else "video/x-h265"
    parser = "h264parse" if normalized_codec == "h264" else "h265parse"
    decoder = "avdec_h264" if normalized_codec == "h264" else "avdec_h265"
    prefix = (
        "appsrc name=gva_source is-live=false format=time do-timestamp=false block=true "
        "max-buffers=1 max-bytes=0 max-time=0 "
        f'caps="{media_type},stream-format=(string)byte-stream,alignment=(string)au" '
        f"! {parser} name=gva_parser "
        f"! {decoder} name=gva_decoder "
        "! queue name=gva_postdecode_queue max-size-buffers=1 max-size-bytes=0 max-size-time=0 leaky=no "
        "! videoconvert ! videoscale "
        f"! video/x-raw,format=BGR,width={width},height={height},pixel-aspect-ratio=1/1 "
        "! identity name=gva_verified_preprocess silent=true"
    )
    if topology_kind == INDEPENDENT_PROCESSES:
        return prefix + " ! " + _branch_chain(branch_values[0])
    branches_text = "".join(
        f" gva_shared_tee. ! {_branch_chain(branch)}" for branch in branch_values
    )
    return prefix + " ! tee name=gva_shared_tee" + branches_text


def _load_config(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    expected = {
        "schema_version",
        "artifact_kind",
        "worker",
        "codec",
        "source_path",
        "source_sha256",
        "socket_path",
        "width",
        "height",
        "preprocessing_contract_sha256",
        "contexts",
    }
    _require(isinstance(value, Mapping) and set(value) == expected, "GVA adapter config fields drifted")
    _require(value["schema_version"] == 1, "GVA adapter config schema_version is invalid")
    _require(value["artifact_kind"] == "vast_openvino_gva_adapter_config", "GVA adapter config kind is invalid")
    return dict(value)


def _connect(path: str) -> socket.socket:
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    deadline = time.monotonic() + 30.0
    while True:
        try:
            sock.connect(path)
            return sock
        except (FileNotFoundError, ConnectionRefusedError):
            if time.monotonic() >= deadline:
                sock.close()
                raise ProtocolError("GVA adapter launcher socket did not become ready")
            time.sleep(0.01)


def _pipeline_evidence(pipeline: Any, *, topology_kind: str, branches: tuple[str, ...]) -> dict[str, Any]:
    shared = topology_kind == SHARED_VIDEO_DAG
    _require(pipeline.get_by_name("gva_source") is not None, "GVA pipeline appsrc is missing")
    _require(pipeline.get_by_name("gva_decoder") is not None, "GVA pipeline decoder is missing")
    _require(
        (pipeline.get_by_name("gva_shared_tee") is not None) is shared,
        "GVA pipeline tee topology is invalid",
    )
    for branch in branches:
        _require(
            pipeline.get_by_name(f"gva_tensor_convert_{branch}") is not None
            and pipeline.get_by_name(f"gva_tensor_sink_{branch}") is not None,
            f"GVA pipeline tensor path is missing for {branch}",
        )
    return {
        "fresh_pipeline_count": 1,
        "decoder_count": 1,
        "tee_count": 1 if shared else 0,
        "tensor_convert_count": len(branches),
        "appsink_count": len(branches),
        "post_preprocess_binding": ADAPTER_BINDING,
    }


def _state_name(element: Any) -> str:
    return str(element.current_state.value_nick).upper()


def run_adapter(config_path: Path) -> dict[str, Any]:
    """Run one physical GStreamer worker and close it in a verified NULL state."""

    config = _load_config(config_path)
    worker = config["worker"]
    _require(isinstance(worker, Mapping), "GVA adapter worker must be a mapping")
    worker_id = _stable(worker.get("worker_id"), "GVA adapter worker_id")
    topology_kind = str(worker.get("topology_kind"))
    stream_id = worker.get("stream_id")
    _require(type(stream_id) is int and 0 <= stream_id < 6, "GVA adapter stream_id is invalid")
    branches = _branches(worker.get("branches") or ())
    source_path = Path(str(config["source_path"]))
    _require(source_path.is_file(), "GVA adapter source does not exist")
    source = source_path.read_bytes()
    source_sha256 = hashlib.sha256(source).hexdigest()
    _require(source and source_sha256 == _sha(config["source_sha256"], "GVA adapter source SHA-256"), "GVA adapter source SHA-256 mismatch")
    contexts = config["contexts"]
    _require(isinstance(contexts, Mapping) and set(contexts) == set(branches), "GVA adapter contexts differ from branches")

    try:
        import gi

        gi.require_version("Gst", "1.0")
        from gi.repository import Gst
    except (ImportError, ValueError) as error:
        raise ProtocolError("GVA adapter requires PyGObject GStreamer 1.0") from error

    Gst.init([])
    text = build_gst_pipeline(
        topology_kind=topology_kind,
        codec=str(config["codec"]),
        branches=branches,
        width=int(config["width"]),
        height=int(config["height"]),
    )
    pipeline = Gst.parse_launch(text)
    _require(pipeline is not None, "GVA adapter failed to construct a pipeline")
    start_state = _state_name(pipeline)
    _require(start_state == "NULL", "fresh GVA pipeline is not NULL")
    evidence = _pipeline_evidence(pipeline, topology_kind=topology_kind, branches=branches)
    pre_depths = {
        branch: int(pipeline.get_by_name(f"gva_tensor_sink_{branch}").get_property("current-level-buffers"))
        for branch in branches
    }
    _require(set(pre_depths.values()) == {0}, "fresh GVA appsink queue is not empty")

    sock = _connect(str(config["socket_path"]))
    terminals: dict[str, dict[str, Any]] = {}
    exchange_lock = threading.Lock()
    callback_errors: list[BaseException] = []

    def on_sample(sink: Any, branch: str) -> Any:
        try:
            _require(branch not in terminals, f"GVA adapter emitted duplicate tensor for {branch}")
            sample = sink.emit("pull-sample")
            _require(sample is not None, f"GVA adapter appsink sample is missing for {branch}")
            buffer = sample.get_buffer()
            caps = sample.get_caps()
            _require(buffer is not None and caps is not None, "GVA adapter sample lacks buffer/caps")
            context = dict(contexts[branch])
            pts = int(buffer.pts)
            _require(pts == int(context["transport_pts_ns"]), "GVA adapter GST_BUFFER_PTS drifted")
            caps_text = caps.to_string()
            _require(caps_text.startswith("other/tensors"), "GVA adapter output is not a DL Streamer tensor")
            ok, mapped = buffer.map(Gst.MapFlags.READ)
            _require(ok, "GVA adapter failed to map tensor buffer read-only")
            try:
                payload = bytes(mapped.data)
            finally:
                buffer.unmap(mapped)
            expected_bytes = int(config["width"]) * int(config["height"]) * 3
            _require(len(payload) == expected_bytes, "GVA adapter tensor byte length is invalid")
            payload_sha256 = hashlib.sha256(payload).hexdigest()
            message = {
                "schema_version": 1,
                "message_type": ADAPTER_MESSAGE_TENSOR,
                "worker_id": worker_id,
                "topology_kind": topology_kind,
                "stream_id": stream_id,
                "branch": branch,
                "context": context,
                "tensor_descriptor": {
                    "name": "input",
                    "dtype": "uint8",
                    "layout": "NHWC",
                    "shape": [1, int(config["height"]), int(config["width"]), 3],
                    "preprocessing_contract_sha256": config[
                        "preprocessing_contract_sha256"
                    ],
                    "contiguous": True,
                    "read_only": True,
                },
                "tensor": {"byte_length": len(payload), "sha256": payload_sha256},
                "gst_evidence": {
                    "caps": caps_text,
                    "buffer_pts_ns": pts,
                    "buffer_size": len(payload),
                    "map_mode": "GST_MAP_READ_copied_before_unmap",
                    "origin_element": f"gva_tensor_convert_{branch}",
                },
            }
            descriptor = create_sealed_memfd(f"gva-{worker_id}-{branch}", payload)
            try:
                with exchange_lock:
                    send_packet(sock, message, fds=(descriptor,))
                    response, fds = receive_packet(sock, expected_fds=0)
                close_fds(fds)
            finally:
                os.close(descriptor)
            _require(
                response.get("message_type") == ADAPTER_MESSAGE_TERMINAL
                and response.get("worker_id") == worker_id
                and response.get("branch") == branch,
                "GVA adapter received an invalid bridge terminal",
            )
            result = response.get("result")
            _require(isinstance(result, Mapping), "GVA adapter bridge result is invalid")
            terminals[branch] = dict(result)
            return Gst.FlowReturn.OK
        except BaseException as error:
            callback_errors.append(error)
            return Gst.FlowReturn.ERROR

    try:
        for branch in branches:
            sink = pipeline.get_by_name(f"gva_tensor_sink_{branch}")
            sink.connect("new-sample", on_sample, branch)
        send_packet(
            sock,
            {
                "schema_version": 1,
                "message_type": ADAPTER_MESSAGE_READY,
                "worker_id": worker_id,
                "topology_kind": topology_kind,
                "stream_id": stream_id,
                "branches": list(branches),
                "pid": os.getpid(),
                "pipeline": evidence,
            },
        )
        start, fds = receive_packet(sock, expected_fds=0)
        close_fds(fds)
        _require(start == {"schema_version": 1, "message_type": ADAPTER_MESSAGE_START}, "GVA adapter start barrier drifted")

        change = pipeline.set_state(Gst.State.PLAYING)
        _require(change != Gst.StateChangeReturn.FAILURE, "GVA adapter pipeline failed to enter PLAYING")
        source_element = pipeline.get_by_name("gva_source")
        source_buffer = Gst.Buffer.new_allocate(None, len(source), None)
        source_buffer.fill(0, source)
        transport_pts = {int(context["transport_pts_ns"]) for context in contexts.values()}
        _require(len(transport_pts) == 1, "GVA adapter branches do not share one transport PTS")
        source_buffer.pts = next(iter(transport_pts))
        source_buffer.dts = source_buffer.pts
        source_buffer.duration = 1_000_000_000
        _require(source_element.emit("push-buffer", source_buffer) == Gst.FlowReturn.OK, "GVA adapter appsrc push failed")
        _require(source_element.emit("end-of-stream") == Gst.FlowReturn.OK, "GVA adapter appsrc EOS failed")
        bus = pipeline.get_bus()
        message = bus.timed_pop_filtered(30 * Gst.SECOND, Gst.MessageType.ERROR | Gst.MessageType.EOS)
        _require(message is not None, "GVA adapter pipeline timed out before EOS")
        if message.type == Gst.MessageType.ERROR:
            error, debug = message.parse_error()
            raise ProtocolError(f"GVA adapter pipeline error: {error}; {debug}")
        _require(
            not callback_errors,
            f"GVA adapter tensor callback failed: "
            f"{callback_errors[0] if callback_errors else ''}",
        )
        _require(set(terminals) == set(branches), "GVA adapter terminal coverage is incomplete")
    finally:
        pipeline.set_state(Gst.State.NULL)
        pipeline.get_state(5 * Gst.SECOND)

    post_state = _state_name(pipeline)
    post_depths = {
        branch: int(pipeline.get_by_name(f"gva_tensor_sink_{branch}").get_property("current-level-buffers"))
        for branch in branches
    }
    drained = {
        "schema_version": 1,
        "message_type": ADAPTER_MESSAGE_DRAINED,
        "worker_id": worker_id,
        "pid": os.getpid(),
        "terminal_branches": list(branches),
        "reset": {
            "fresh_pipeline_count": 1,
            "start_state": start_state,
            "pre_start_queue_depths": pre_depths,
            "admission_stopped_before_drain": True,
            "terminal_state": "DRAINED",
            "post_stop_state": post_state,
            "post_stop_queue_depths": post_depths,
        },
    }
    send_packet(sock, drained)
    close_message, fds = receive_packet(sock, expected_fds=0)
    close_fds(fds)
    _require(close_message == {"schema_version": 1, "message_type": ADAPTER_MESSAGE_CLOSE}, "GVA adapter close acknowledgement drifted")
    sock.close()
    return drained


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        run_adapter(args.config)
    except BaseException as error:
        import traceback

        print(f"openvino_gva_gst_adapter: {error}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ADAPTER_BINDING",
    "ADAPTER_MESSAGE_CLOSE",
    "ADAPTER_MESSAGE_DRAINED",
    "ADAPTER_MESSAGE_ERROR",
    "ADAPTER_MESSAGE_READY",
    "ADAPTER_MESSAGE_START",
    "ADAPTER_MESSAGE_TENSOR",
    "ADAPTER_MESSAGE_TERMINAL",
    "build_gst_pipeline",
    "run_adapter",
]
