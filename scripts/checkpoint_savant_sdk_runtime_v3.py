#!/usr/bin/env python3
"""Genuine Savant 0.5.17 worker for one process in a publication arm."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import selectors
import socket
import stat
import threading
import time
import warnings
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


_GOOGLE_API_CORE_PYTHON_310_EOL_WARNING = (
    "You are using a Python version (3.10.12) which Google will stop "
    "supporting in new releases of google.api_core once it reaches its "
    "end of life (2026-10-04). Please upgrade to the latest Python "
    "version, or at least Python 3.11, to continue receiving updates "
    "for google.api_core past that date."
)


def _install_google_api_core_python_eol_filter() -> None:
    """Suppress only the pinned google.api_core Python 3.10 EOL warning."""
    warnings.filterwarnings(
        "ignore",
        message=re.escape(_GOOGLE_API_CORE_PYTHON_310_EOL_WARNING) + r"\Z",
        category=FutureWarning,
        module=r"^google\.api_core\._python_version_support$",
    )


_install_google_api_core_python_eol_filter()

from checkpoint_deepstream_sdk_runtime import (
    ADMISSION_DATA_FD_ENV, CONTROL_FD_ENV, EVENT_FD_ENV, POLICY_FD_ENV,
    RUN_ID_ENV, STATUS_FD_ENV, STREAM_ID_ENV, TOPOLOGY_KIND_ENV, WORKER_ID_ENV,
    CanonicalEventFdSink, LifecycleChannel, SeqpacketPolicyExchange,
    build_deepstream_stage_contract_rows, read_admission_transport_frame,
    write_deepstream_stage_contracts,
)
from checkpoint_savant_ingress import (
    SavantNativeIngress, SavantSourceBinding, _native_dependencies,
)
from checkpoint_savant_native_module import (
    SavantNativeModuleBinding, build_native_frame_identity,
    build_native_module_artifact, register_native_runtime,
    unregister_native_runtime,
)
from checkpoint_savant_protocol_adapter_v3 import create_savant_callbacks
from checkpoint_savant_resource_runtime_v3 import (
    SavantNativeResourceRecorderV3,
)
from checkpoint_savant_publication_specs_v3 import (
    DESCRIPTOR_ENV, SOURCE_BINDING_ENV,
)


BRANCHES = ("plate_number", "vehicle_type", "damage", "foreign_object")
SAVANT_VERSION = "0.5.17"
DROP_REASON = "native_pre_detector_queue_full_drop_newest"
MAX_CONFIG_BYTES = 8 * 1024 * 1024


class SavantSdkRuntimeV3Error(RuntimeError):
    """The official Savant module or inherited protocol failed closed."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SavantSdkRuntimeV3Error(message)


def _now_ms() -> int:
    return time.time_ns() // 1_000_000


def _text_environment(name: str) -> str:
    value = os.environ.get(name, "").strip()
    _require(bool(value), f"required Savant environment is missing: {name}")
    return value


def _integer_environment(name: str) -> int:
    try:
        result = int(_text_environment(name))
    except ValueError as exc:
        raise SavantSdkRuntimeV3Error(
            f"Savant environment is not an integer: {name}"
        ) from exc
    _require(result >= 0, f"Savant environment is negative: {name}")
    return result


def _canonical(value: Mapping[str, Any]) -> bytes:
    try:
        return json.dumps(
            dict(value), sort_keys=True, separators=(",", ":"),
            ensure_ascii=True, allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError) as exc:
        raise SavantSdkRuntimeV3Error(
            "Savant module config is not canonical JSON"
        ) from exc


def _write_exclusive(path: Path, payload: bytes) -> None:
    _require(path.is_absolute(), "Savant output path must be absolute")
    _require(bool(payload) and len(payload) <= MAX_CONFIG_BYTES,
             "Savant output payload is empty or unbounded")
    try:
        with path.open("xb") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
    except FileExistsError as exc:
        raise SavantSdkRuntimeV3Error(
            f"Savant runtime artifact already exists: {path.name}"
        ) from exc


def materialize_worker_module_config(
    *, output_dir: Path, descriptor_json: str, source_json: str,
) -> dict[str, Any]:
    """Write exactly one hash-bound official Savant module config."""
    directory = Path(output_dir)
    _require(directory.is_absolute() and directory.is_dir()
             and not directory.is_symlink(),
             "Savant worker output directory is invalid")
    try:
        descriptor = json.loads(descriptor_json)
        source = json.loads(source_json)
    except json.JSONDecodeError as exc:
        raise SavantSdkRuntimeV3Error(
            "Savant descriptor/source JSON is invalid"
        ) from exc
    _require(isinstance(descriptor, Mapping) and isinstance(source, Mapping),
             "Savant descriptor/source JSON is not an object")
    artifact = build_native_module_artifact(descriptor, source)
    payload = str(artifact["module_config_json"]).encode("utf-8")
    _require(hashlib.sha256(payload).hexdigest()
             == str(artifact["module_config_sha256"]),
             "Savant generated module config SHA-256 drifted")
    path = directory / "module.json"
    _write_exclusive(path, payload)
    return {
        "path": path,
        "sha256": str(artifact["module_config_sha256"]),
        "binding": SavantNativeModuleBinding.from_json(
            str(artifact["binding_json"])
        ),
        "artifact": artifact,
    }


def _sha256_regular_file(path: Path, label: str) -> tuple[Path, str]:
    try:
        before = path.lstat()
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise SavantSdkRuntimeV3Error(f"{label} cannot be resolved") from exc
    _require(stat.S_ISREG(before.st_mode) and not path.is_symlink(),
             f"{label} is not a regular file")
    digest = hashlib.sha256()
    with resolved.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    after = path.lstat()
    _require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
             == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns),
             f"{label} changed while being hashed")
    return resolved, digest.hexdigest()


def _caps_output(caps: Any, label: str) -> tuple[dict[str, Any], str]:
    _require(caps is not None and not caps.is_empty() and caps.get_size() == 1,
             f"Savant {label} negotiated caps are missing or ambiguous")
    structure = caps.get_structure(0)
    _require(structure is not None, f"Savant {label} caps lack a structure")
    media_type = str(structure.get_name() or "").strip()
    pixel_format = str(structure.get_string("format") or "").strip()
    try:
        width = int(structure.get_value("width"))
        height = int(structure.get_value("height"))
    except (TypeError, ValueError) as exc:
        raise SavantSdkRuntimeV3Error(
            f"Savant {label} caps dimensions are invalid"
        ) from exc
    _require(media_type == "video/x-raw" and pixel_format
             and width > 0 and height > 0,
             f"Savant {label} caps identity drifted")
    text = str(caps.to_string()).strip()
    _require(bool(text), f"Savant {label} caps serialization is empty")
    if "memory:NVMM" in text:
        media_type += "(memory:NVMM)"
    channels = 4 if pixel_format in {"RGBA", "BGRA"} else 3
    return {
        "media_type": media_type,
        "format": "rgb24" if pixel_format == "RGB" else pixel_format.lower(),
        "shape": [height, width, channels],
    }, text


class SavantSdkCallbackRuntime:
    """Bridge official Savant callbacks to exact CPU/TensorRT endpoints."""
    publication_ready = False
    accepted_measurement_evidence_emitted = False

    def __init__(self, *, binding: SavantNativeModuleBinding,
                 callbacks: Any, resource_recorder: Any) -> None:
        self.binding = binding.validate()
        self.callbacks = callbacks
        self.resource_recorder = resource_recorder
        self.decoder_observed = threading.Event()
        self._lock = threading.RLock()
        self._decoder: tuple[str, int] | None = None
        self._identity_by_pts: dict[int, dict[str, Any]] = {}
        self._admission_by_pts: dict[int, dict[str, Any]] = {}
        self._pending_by_branch = {
            branch: [] for branch in self.binding.branches
        }
        self._terminal_by_pts: dict[int, set[str]] = {}
        self._preprocessed: set[int] = set()
        self._fanout: set[tuple[int, str]] = set()
        self._loaded_factories: dict[str, list[dict[str, str]]] = {}
        self._decode_output: dict[str, Any] | None = None
        self._decode_caps = ""
        self._preprocess_output: dict[str, Any] | None = None
        self._preprocess_caps = ""

    def bind_decoder(self, factory: str, gpu_id: int) -> None:
        with self._lock:
            _require(self._decoder is None,
                     "Savant native decoder was bound twice")
            _require(factory == "nvv4l2decoder" and gpu_id == 0,
                     "Savant native decoder placement drifted")
            self._decoder = (factory, gpu_id)
            self.decoder_observed.set()


    def bind_loaded_graph(self, *, root: Any, decoder: Any,
                          prefix_element: Any) -> None:
        """Capture actual loaded factory/plugin paths from this process."""
        del decoder
        try:
            from savant.gstreamer import Gst
        except (ImportError, OSError) as exc:
            raise SavantSdkRuntimeV3Error(
                "Savant GStreamer API is unavailable"
            ) from exc
        factories: dict[str, list[dict[str, str]]] = {}
        iterator = root.iterate_recurse()
        while True:
            result, element = iterator.next()
            if result == Gst.IteratorResult.OK:
                factory = element.get_factory()
                if factory is None:
                    continue
                name = str(factory.get_name() or "").strip()
                plugin = factory.get_plugin()
                filename = str(plugin.get_filename() or "").strip() \
                    if plugin is not None else ""
                version = str(plugin.get_version() or "").strip() \
                    if plugin is not None else ""
                if name and filename and version:
                    row = {
                        "element_name": str(element.get_name()),
                        "filename": filename,
                        "version": version,
                    }
                    if row not in factories.setdefault(name, []):
                        factories[name].append(row)
            elif result == Gst.IteratorResult.DONE:
                break
            elif result == Gst.IteratorResult.RESYNC:
                iterator.resync()
            else:
                raise SavantSdkRuntimeV3Error(
                    "Savant loaded graph iteration failed"
                )
        parser = "h264parse" if self.binding.codec == "h264" else "h265parse"
        required = {
            parser, "nvv4l2decoder", "nvstreammux",
            "nvvideoconvert", "capsfilter",
        }
        _require(required <= set(factories),
                 "Savant loaded graph lacks required native factories")
        _require(len(factories["nvv4l2decoder"]) == 1,
                 "Savant loaded graph has more than one NVDEC decoder")
        if self.binding.topology_kind == "shared_video_dag":
            _require("tee" in factories,
                     "Savant shared graph lacks a physical tee")
        with self._lock:
            _require(not self._loaded_factories,
                     "Savant loaded graph was captured twice")
            self._loaded_factories = factories
        pad = prefix_element.get_static_pad("sink")
        _require(pad is not None, "Savant prefix sink pad is missing")
        self.capture_decode_caps(pad.get_current_caps())

    def capture_decode_caps(self, caps: Any) -> None:
        output, text = _caps_output(caps, "decode output")
        with self._lock:
            if self._decode_output is None:
                self._decode_output, self._decode_caps = output, text
            else:
                _require(self._decode_output == output
                         and self._decode_caps == text,
                         "Savant decode caps drifted within one worker")

    def capture_preprocess_caps(self, caps: Any) -> None:
        output, text = _caps_output(caps, "preprocess output")
        _require(output["media_type"] == "video/x-raw"
                 and output["format"] == "rgb24",
                 "Savant post-demux terminal is not system-memory RGB")
        with self._lock:
            if self._preprocess_output is None:
                self._preprocess_output, self._preprocess_caps = output, text
            else:
                _require(self._preprocess_output == output
                         and self._preprocess_caps == text,
                         "Savant route RGB caps drifted")

    def admit_video_frame(self, _frame: Any,
                          binding: SavantNativeModuleBinding) -> None:
        _require(binding == self.binding,
                 "Savant ingress binding changed within one worker")

    def admit_transport_frame(self, frame: Any) -> None:
        """Bind one coordinator admission to the native decoder submit edge."""
        try:
            pts = int(frame.transport_pts_ns)
            frame_id = int(frame.frame_id)
            input_frame_key = str(frame.input_frame_key)
            payload_bytes = len(frame.payload)
        except (AttributeError, TypeError, ValueError) as exc:
            raise SavantSdkRuntimeV3Error(
                "Savant admission transport identity is invalid"
            ) from exc
        _require(pts >= 0 and frame_id >= 0 and bool(input_frame_key)
                 and payload_bytes > 0,
                 "Savant admission transport identity is incomplete")
        self.callbacks.admit_transport_frame(
            frame, observed_timestamp_ms=_now_ms()
        )
        decode_submit_start_ns = time.time_ns()
        with self._lock:
            _require(pts not in self._admission_by_pts,
                     "Savant transport PTS was admitted twice")
            self._admission_by_pts[pts] = {
                "frame_id": frame_id,
                "input_frame_key": input_frame_key,
                "payload_bytes": payload_bytes,
                "decode_submit_start_ns": decode_submit_start_ns,
            }

    def observe_prefix(self, _buffer: Any, frame_meta: Any,
                       binding: SavantNativeModuleBinding) -> None:
        _require(binding == self.binding, "Savant prefix binding drifted")
        _require(self._decoder == ("nvv4l2decoder", 0),
                 "Savant decode callback precedes decoder placement")
        identity = build_native_frame_identity(
            binding=binding, frame_meta=frame_meta,
            decoder_factory="nvv4l2decoder", decoder_gpu_id=0,
        )
        pts = int(identity["transport_pts_ns"])
        completed_ns = time.time_ns()
        with self._lock:
            _require(pts not in self._identity_by_pts,
                     "Savant decoded PTS was duplicated")
            admission = self._admission_by_pts.pop(pts, None)
            _require(admission is not None,
                     "Savant decoded PTS has no native admission")
            _require(int(identity["frame_id"]) == admission["frame_id"]
                     and str(identity["input_frame_key"])
                     == admission["input_frame_key"],
                     "Savant decoded identity differs from admission")
            self._identity_by_pts[pts] = identity
            for branch in binding.branches:
                self._pending_by_branch[branch].append(pts)
        completed_ns = max(
            completed_ns,
            int(admission["decode_submit_start_ns"]) + 1,
        )
        self.callbacks.observe_decoded_frame(
            identity, observed_timestamp_ms=completed_ns / 1_000_000.0
        )
        self.resource_recorder.record_nvdec(
            frame_id=admission["frame_id"],
            input_frame_key=admission["input_frame_key"],
            payload_bytes=admission["payload_bytes"],
            start_timestamp_ns=admission["decode_submit_start_ns"],
            end_timestamp_ns=completed_ns,
        )

    def _preprocess_and_fanout(
        self, *, pts: int, branch: str, identity: Mapping[str, Any],
    ) -> None:
        with self._lock:
            if pts not in self._preprocessed:
                self.callbacks.observe_preprocessed_frame(
                    identity, observed_timestamp_ms=_now_ms()
                )
                self._preprocessed.add(pts)
            if self.binding.topology_kind == "shared_video_dag":
                marker = (pts, branch)
                _require(marker not in self._fanout,
                         "Savant physical fanout was duplicated")
                self.callbacks.observe_fanout(
                    identity, branch=branch, observed_timestamp_ms=_now_ms()
                )
                self._fanout.add(marker)

    def _mark_terminal(self, pts: int, branch: str) -> None:
        with self._lock:
            terminals = self._terminal_by_pts.setdefault(pts, set())
            _require(branch not in terminals,
                     "Savant branch terminal was duplicated")
            terminals.add(branch)
            if terminals == set(self.binding.branches):
                del self._terminal_by_pts[pts]
                self._identity_by_pts.pop(pts)
                self._preprocessed.discard(pts)
                self._fanout = {
                    marker for marker in self._fanout if marker[0] != pts
                }

    def observe_route_buffer(
        self, buffer: Any, binding: SavantNativeModuleBinding, branch: str,
        *, sample: Any, caps: Any,
    ) -> None:
        _require(binding == self.binding and branch in binding.branches,
                 "Savant route binding drifted")
        self.capture_preprocess_caps(caps)
        pts = int(getattr(buffer, "pts", -1))
        with self._lock:
            identity = self._identity_by_pts.get(pts)
            pending = self._pending_by_branch[branch]
            _require(identity is not None and bool(pending)
                     and pending.pop(0) == pts,
                     "Savant route PTS/order has no decoded admission")
        fanout_started_ns = time.time_ns()
        fanout_started_thread_ns = time.thread_time_ns()
        self._preprocess_and_fanout(
            pts=pts, branch=branch, identity=identity
        )
        fanout_completed_ns = time.time_ns()
        fanout_completed_thread_ns = time.thread_time_ns()
        if self.binding.topology_kind == "shared_video_dag":
            try:
                payload_bytes = int(buffer.get_size())
            except (AttributeError, TypeError, ValueError) as exc:
                raise SavantSdkRuntimeV3Error(
                    "Savant routed buffer size is unavailable"
                ) from exc
            self.resource_recorder.record_fanout(
                frame_id=int(identity["frame_id"]),
                input_frame_key=str(identity["input_frame_key"]),
                branch=branch,
                payload_bytes=payload_bytes,
                start_timestamp_ns=fanout_started_ns,
                end_timestamp_ns=max(fanout_completed_ns,
                                     fanout_started_ns + 1),
                thread_cpu_time_ns=max(
                    1, fanout_completed_thread_ns - fanout_started_thread_ns,
                ),
            )
        self.callbacks.execute_branch_sample(
            identity, branch=branch, sample=sample
        )
        self._mark_terminal(pts, branch)

    def queue_overrun(
        self, *, branch: str, queue_name: str,
        current_level_buffers: int, binding: SavantNativeModuleBinding,
    ) -> None:
        _require(binding == self.binding and branch in binding.branches
                 and queue_name.endswith(branch)
                 and current_level_buffers >= 1,
                 "Savant queue overrun observation drifted")
        with self._lock:
            pending = self._pending_by_branch[branch]
            _require(bool(pending),
                     "Savant queue overrun has no incoming admission")
            pts = pending.pop()
            identity = self._identity_by_pts.get(pts)
            _require(identity is not None,
                     "Savant dropped PTS has no decoded identity")
        self._preprocess_and_fanout(
            pts=pts, branch=branch, identity=identity
        )
        self.callbacks.drop_branch(
            str(identity["input_frame_key"]), branch, reason=DROP_REASON,
            observed_timestamp_ms=_now_ms(),
        )
        self._mark_terminal(pts, branch)

    def assert_drained(self) -> None:
        with self._lock:
            _require(not self._identity_by_pts
                     and not self._admission_by_pts
                     and not self._terminal_by_pts
                     and all(not values for values
                             in self._pending_by_branch.values()),
                     "Savant module drained with unresolved identities")

    def _plugin_artifact(
        self, factory: str, role: str,
    ) -> tuple[dict[str, str], str]:
        values = self._loaded_factories.get(factory) or []
        _require(bool(values), f"Savant loaded plugin is missing: {factory}")
        value = values[0]
        _path, sha256 = _sha256_regular_file(
            Path(value["filename"]), f"Savant {factory} plugin"
        )
        return {
            "role": role, "kind": "plugin",
            "logical_name": factory, "sha256": sha256,
        }, f"{factory}-{value['version']}"

    def stage_contract_rows(
        self, *, run_id: str, worker_id: str,
    ) -> list[dict[str, Any]]:
        with self._lock:
            _require(self._decoder == ("nvv4l2decoder", 0)
                     and self._loaded_factories
                     and self._decode_output is not None
                     and self._preprocess_output is not None,
                     "Savant runtime stage observations are incomplete")
            decode_output = dict(self._decode_output)
            preprocess_output = dict(self._preprocess_output)
            decode_caps = self._decode_caps
            preprocess_caps = self._preprocess_caps
        parser = "h264parse" if self.binding.codec == "h264" else "h265parse"
        decode_artifacts: list[dict[str, str]] = []
        preprocess_artifacts: list[dict[str, str]] = []
        versions: list[str] = []
        for factory, role in (
            (parser, "codec_parser"), ("nvv4l2decoder", "decoder"),
            ("nvstreammux", "stream_mux"),
        ):
            artifact, version = self._plugin_artifact(factory, role)
            decode_artifacts.append(artifact)
            versions.append(version)
        for factory, role in (
            ("nvvideoconvert", "format_converter"),
            ("capsfilter", "caps_filter"),
        ):
            artifact, version = self._plugin_artifact(factory, role)
            preprocess_artifacts.append(artifact)
            versions.append(version)


        worker_path, worker_sha = _sha256_regular_file(
            Path(__file__), "Savant SDK worker"
        )
        module_path, module_sha = _sha256_regular_file(
            Path(__file__).with_name("checkpoint_savant_native_module.py"),
            "Savant native module",
        )
        common = [
            {
                "role": "stage_host", "kind": "executable",
                "logical_name": worker_path.name, "sha256": worker_sha,
            },
            {
                "role": "savant_module", "kind": "executable",
                "logical_name": module_path.name, "sha256": module_sha,
            },
        ]
        hostname = socket.gethostname().strip()
        _require(bool(hostname), "Savant runtime hostname is empty")
        rows = build_deepstream_stage_contract_rows(
            run_id=run_id, worker_id=worker_id,
            topology_kind=self.binding.topology_kind,
            branches=self.binding.branches,
            execution_domain=(
                f"{hostname}:pid-{os.getpid()}:worker-{worker_id}"
            ),
            implementation_version=(
                f"Savant-{SAVANT_VERSION}/"
                + "/".join(sorted(set(versions)))
            ),
            decode_config={
                "backend": "savant_deepstream",
                "codec": self.binding.codec,
                "decoder_factory": "nvv4l2decoder",
                "decoder_gpu_id": 0,
                "output_caps": decode_caps,
                "pipeline_role": "checkpoint",
                "savant_version": SAVANT_VERSION,
                "software_fallback": "prohibited",
                "stream_mux_batch_size": 1,
            },
            preprocess_config={
                "backend": "savant_deepstream",
                "converter_factory": "nvvideoconvert",
                "output_caps": preprocess_caps,
                "pipeline_role": "checkpoint",
                "savant_version": SAVANT_VERSION,
            },
            artifacts_by_stage={
                "decode": [*common, *decode_artifacts],
                "preprocess": [*common, *preprocess_artifacts],
            },
            decode_output=decode_output,
            preprocess_output=preprocess_output,
        )
        for row in rows:
            row["implementation_name"] = (
                f"vast-savant-checkpoint-{row['base_stage']}"
            )
        return rows


def _wait_module_running(
    status_path: Path, *, timeout_s: float, errors: list[BaseException],
) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if errors:
            raise SavantSdkRuntimeV3Error(
                f"Savant module failed during initialization: {errors[0]}"
            )
        try:
            value = status_path.read_text(encoding="ascii").strip().lower()
            if value == "running":
                return
        except FileNotFoundError:
            pass
        time.sleep(0.02)
    raise SavantSdkRuntimeV3Error(
        "Savant module did not reach RUNNING before timeout"
    )


def run_fd_worker(args: argparse.Namespace) -> dict[str, Any]:
    worker_id = _text_environment(WORKER_ID_ENV)
    run_id = _text_environment(RUN_ID_ENV)
    topology = _text_environment(TOPOLOGY_KIND_ENV)
    stream_id = _integer_environment(STREAM_ID_ENV)
    _require(args.topology_kind == topology,
             "Savant topology differs between argv and coordinator")
    _require(args.stream_id == stream_id,
             "Savant stream differs between argv and coordinator")
    branches = tuple(value for value in args.branches.split(",") if value)
    _require(
        (topology == "independent_processes"
         and len(branches) == 1 and branches[0] in BRANCHES)
        or (topology == "shared_video_dag" and branches == BRANCHES),
        "Savant worker branch matrix drifted",
    )
    output_dir = Path(args.output_dir)
    _require(output_dir.is_absolute() and output_dir.is_dir()
             and not output_dir.is_symlink()
             and not any(output_dir.iterdir()),
             "Savant worker output directory is invalid or nonempty")
    materialized = materialize_worker_module_config(
        output_dir=output_dir,
        descriptor_json=_text_environment(DESCRIPTOR_ENV),
        source_json=_text_environment(SOURCE_BINDING_ENV),
    )
    binding: SavantNativeModuleBinding = materialized["binding"]
    _require(binding.module_id == worker_id
             and binding.topology_kind == topology
             and binding.stream_id == stream_id
             and binding.branches == branches
             and binding.codec == args.codec,
             "Savant generated module binding differs from coordinator")
    admission_fd = _integer_environment(ADMISSION_DATA_FD_ENV)
    event_sink = CanonicalEventFdSink(_integer_environment(EVENT_FD_ENV))
    lifecycle = LifecycleChannel(
        worker_id=worker_id,
        control_fd=_integer_environment(CONTROL_FD_ENV),
        status_fd=_integer_environment(STATUS_FD_ENV),
    )
    policy = SeqpacketPolicyExchange(_integer_environment(POLICY_FD_ENV))
    resource_recorder = SavantNativeResourceRecorderV3(
        output_dir=output_dir,
        run_id=run_id,
        worker_id=worker_id,
        stream_id=stream_id,
        topology_kind=topology,
        branches=branches,
    )
    try:
        callbacks = create_savant_callbacks(
            context={
                "run_id": run_id, "arm_id": args.arm_id,
                "worker_id": worker_id, "topology_kind": topology,
                "stream_id": stream_id, "branches": list(branches),
                "codec": args.codec,
                "claim_status":
                    "native_sdk_runtime_requires_external_acceptance",
            },
            event_sink=event_sink, policy_exchange=policy,
            resource_recorder=resource_recorder,
        )
    except BaseException:
        resource_recorder.close()
        policy.close()
        raise
    runtime = SavantSdkCallbackRuntime(
        binding=binding,
        callbacks=callbacks,
        resource_recorder=resource_recorder,
    )
    status_path = Path(_text_environment("SAVANT_STATUS_FILEPATH"))
    _require(status_path.is_absolute()
             and status_path.parent == Path("/tmp")
             and not status_path.exists(),
             "Savant module status path is invalid or preexisting")
    errors: list[BaseException] = []
    errors_lock = threading.Lock()
    stop_event = threading.Event()
    stop_timestamp: list[int] = []
    decoder_status_sent = threading.Event()
    ingress_finished = threading.Event()
    window = None
    stop_thread: threading.Thread | None = None
    resource_paths: dict[str, Path] = {}

    def record_error(exc: BaseException) -> None:
        with errors_lock:
            if not errors:
                errors.append(exc)
        stop_event.set()

    def receive_stop() -> None:
        try:
            stop_timestamp.append(lifecycle.await_stop())
        except BaseException as exc:
            record_error(exc)
        finally:
            stop_event.set()

    def run_ingress() -> None:
        ingress: SavantNativeIngress | None = None
        selector = selectors.DefaultSelector()
        try:
            _wait_module_running(
                status_path, timeout_s=args.module_ready_timeout_s,
                errors=errors,
            )
            frame_builder, source_factory = _native_dependencies()
            source_binding = SavantSourceBinding(
                stream_id=binding.stream_id, source_id=binding.source_id,
                codec=binding.codec, width=binding.width,
                height=binding.height, framerate=binding.framerate,
                dataset_id=binding.dataset_id,
                source_sha256=binding.source_sha256,
                socket=binding.source_socket,
            )
            ingress = SavantNativeIngress(
                binding=source_binding,
                runner=source_factory(binding.source_socket),
                frame_builder=frame_builder,
            )
            lifecycle.started()
            selector.register(admission_fd, selectors.EVENT_READ)
            while not stop_event.is_set():
                if runtime.decoder_observed.is_set() \
                        and not decoder_status_sent.is_set():
                    lifecycle.decoder_placement_verified()
                    decoder_status_sent.set()
                ready = selector.select(timeout=0.05)
                if not ready:
                    continue
                frame = read_admission_transport_frame(admission_fd)
                _require(frame is not None,
                         "Savant admission FD closed before STOP")
                runtime.admit_transport_frame(frame)
                ingress.send_frame(frame)
            _require(bool(stop_timestamp),
                     "Savant STOP timestamp was not received")
            lifecycle.admission_stopped(stop_timestamp[0])
            ingress.finish()
            deadline = time.monotonic() + args.drain_timeout_s
            while not decoder_status_sent.is_set() \
                    and time.monotonic() < deadline:
                if runtime.decoder_observed.wait(0.02):
                    lifecycle.decoder_placement_verified()
                    decoder_status_sent.set()
            _require(decoder_status_sent.is_set(),
                     "Savant NVDEC placement was never observed")
        except BaseException as exc:
            if ingress is not None:
                try:
                    ingress.finish()
                except BaseException:
                    pass
            record_error(exc)
        finally:
            selector.close()
            ingress_finished.set()


    register_native_runtime(binding.descriptor_sha256, runtime)
    try:
        lifecycle.ready()
        window = lifecycle.await_start()
        while time.monotonic_ns() < window.common_start_monotonic_ns:
            time.sleep(min(
                0.001,
                (window.common_start_monotonic_ns - time.monotonic_ns()) / 1e9,
            ))
        stop_thread = threading.Thread(
            target=receive_stop, name=f"savant-stop-{worker_id}", daemon=True,
        )
        ingress_thread = threading.Thread(
            target=run_ingress,
            name=f"savant-ingress-{worker_id}", daemon=True,
        )
        stop_thread.start()
        ingress_thread.start()
        try:
            from savant.entrypoint.main import main as savant_main
        except (ImportError, OSError) as exc:
            raise SavantSdkRuntimeV3Error(
                "Savant 0.5.17 entrypoint is unavailable"
            ) from exc
        # Savant installs signal handlers, so its official main must own this
        # OS process' main thread. Admissions and STOP are handled above.
        savant_main(materialized["path"])
        ingress_thread.join(timeout=args.drain_timeout_s + 2.0)
        _require(ingress_finished.is_set(),
                 "Savant ingress thread did not drain")
        with errors_lock:
            _require(
                not errors,
                "Savant worker callback failed: "
                + (str(errors[0]) if errors else ""),
            )
        runtime.assert_drained()
        stage_path = write_deepstream_stage_contracts(
            output_dir,
            runtime.stage_contract_rows(run_id=run_id, worker_id=worker_id),
        )
        resource_paths = resource_recorder.close()
        lifecycle.drained(_now_ms())
        receipt = {
            "schema_version": 3,
            "artifact_kind": "vast_savant_sdk_worker_exit_v3",
            "claim_status":
                "native_runtime_exit_requires_external_acceptance",
            "run_id": run_id,
            "arm_id": args.arm_id,
            "worker_id": worker_id,
            "topology_kind": topology,
            "stream_id": stream_id,
            "branches": list(branches),
            "codec": args.codec,
            "module_config_sha256": materialized["sha256"],
            "stage_contract_runtime_path": str(stage_path),
            "resource_interval_runtime_path": str(
                resource_paths["resource_intervals"]
            ),
            "fanout_work_runtime_path": (
                str(resource_paths["fanout_work_counters"])
                if "fanout_work_counters" in resource_paths else None
            ),
            "decoder_factory": "nvv4l2decoder",
            "decoder_gpu_id": 0,
            "publication_ready": False,
        }
        _write_exclusive(
            output_dir / "worker.runtime.json", _canonical(receipt) + b"\n"
        )
        return receipt
    except BaseException:
        if window is not None:
            try:
                lifecycle.censored(
                    min(_now_ms(), window.drain_end_timestamp_ms)
                )
            except BaseException:
                pass
        raise
    finally:
        unregister_native_runtime(binding.descriptor_sha256, runtime)
        resource_paths = resource_recorder.close()
        callbacks.close()
        policy.close()
        if stop_thread is not None:
            stop_thread.join(timeout=2.0)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Genuine Savant checkpoint SDK worker v3"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run")
    run.add_argument("--codec", choices=("h264", "h265"), required=True)
    run.add_argument(
        "--topology-kind",
        choices=("independent_processes", "shared_video_dag"),
        required=True,
    )
    run.add_argument("--stream-id", type=int, required=True)
    run.add_argument("--branches", required=True)
    run.add_argument("--arm-id", required=True)
    run.add_argument("--output-dir", type=Path, required=True)
    run.add_argument("--module-ready-timeout-s", type=float, default=300.0)
    run.add_argument("--drain-timeout-s", type=float, default=60.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        _require(args.module_ready_timeout_s > 0
                 and args.drain_timeout_s > 0,
                 "Savant worker timeout is invalid")
        result = run_fd_worker(args)
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0
    except (
        KeyError,
        OSError,
        SavantSdkRuntimeV3Error,
        TypeError,
        ValueError,
    ) as exc:
        print(str(exc), file=os.sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
