#!/usr/bin/env python3
"""Native DeepStream resource-v2 fragments for one physical SDK worker.

The recorder is deliberately standard-library-only because it is imported by
every 24/6 worker process.  It records only callback-observed wall intervals
and ``time.thread_time_ns`` work.  It does not infer CUDA transfer timing;
that remains owned by the separately attested TensorRT endpoint.
"""
from __future__ import annotations

import csv
import hashlib
import os
import re
import threading
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


TELEMETRY_SCHEMA_VERSION = 2
RESOURCE_INTERVAL_CONTRACT_VERSION = 2
FULL_RESOURCE_CONTRACT_VERSION = 2
RESOURCE_INTERVAL_COLUMNS = (
    "schema_version",
    "interval_contract_version",
    "run_id",
    "trace_id",
    "stream_id",
    "frame_id",
    "input_frame_key",
    "component",
    "direction",
    "stage",
    "branch_id",
    "execution_id",
    "host_start_timestamp_ns",
    "host_end_timestamp_ns",
    "duration_ns",
    "bytes",
    "device_id",
    "counter_scope",
    "native_event_id",
    "duration_provenance",
    "telemetry_source",
)
FANOUT_WORK_COUNTER_COLUMNS = (
    "schema_version",
    "resource_contract_version",
    "run_id",
    "trace_id",
    "stream_id",
    "frame_id",
    "input_frame_key",
    "branch_id",
    "execution_id",
    "thread_cpu_time_ns",
    "work_units",
    "device_id",
    "counter_scope",
    "counter_provenance",
    "telemetry_source",
)
ANALYTICS_BRANCHES = (
    "plate_number",
    "vehicle_type",
    "damage",
    "foreign_object",
)
INDEPENDENT_PROCESSES = "independent_processes"
SHARED_VIDEO_DAG = "shared_video_dag"
_ID_RE = re.compile(r"^[^\x00-\x20\x7f]+$")
_GPU_UUID_RE = re.compile(
    r"^GPU-[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def _text(value: Any, label: str) -> str:
    result = str(value)
    if not result or _ID_RE.fullmatch(result) is None:
        raise ValueError(f"{label} is invalid")
    return result


def _integer(value: Any, label: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError(f"{label} must be an integer >= {minimum}")
    return int(value)


def _native_event_id(values: Sequence[Any]) -> str:
    payload = "\0".join(str(value) for value in values).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class DeepStreamNativeResourceRecorderV3:
    """Write direct NVDEC/fanout fragments for one launched worker PID."""

    def __init__(
        self,
        *,
        output_dir: Path,
        run_id: str,
        worker_id: str,
        stream_id: int,
        topology_kind: str,
        branches: Sequence[str],
        decoder_gpu_index: int,
    ) -> None:
        directory = Path(output_dir)
        if not directory.is_dir() or directory.is_symlink():
            raise ValueError("DeepStream resource output directory is invalid")
        self.run_id = _text(run_id, "run_id")
        self.worker_id = _text(worker_id, "worker_id")
        self.stream_id = _integer(stream_id, "stream_id")
        self.decoder_gpu_index = _integer(
            decoder_gpu_index, "decoder_gpu_index"
        )
        self.topology_kind = str(topology_kind)
        self.branches = tuple(str(branch) for branch in branches)
        if self.topology_kind == INDEPENDENT_PROCESSES:
            if len(self.branches) != 1 or self.branches[0] not in ANALYTICS_BRANCHES:
                raise ValueError("independent DeepStream resource recorder requires one branch")
        elif self.topology_kind == SHARED_VIDEO_DAG:
            if self.branches != ANALYTICS_BRANCHES:
                raise ValueError("shared DeepStream resource recorder requires four frozen branches")
        else:
            raise ValueError("DeepStream resource topology is unsupported")
        self._lock = threading.Lock()
        self._closed = False
        self._identities: set[tuple[str, int, str]] = set()
        self._paths = {
            "resource_intervals": directory / "resource_intervals.runtime.csv",
        }
        try:
            self._interval_handle = self._paths["resource_intervals"].open(
                "x", newline="", encoding="utf-8"
            )
            self._interval_writer = csv.DictWriter(
                self._interval_handle, fieldnames=RESOURCE_INTERVAL_COLUMNS
            )
            self._interval_writer.writeheader()
            self._counter_handle = None
            self._counter_writer = None
            if self.topology_kind == SHARED_VIDEO_DAG:
                counter_path = directory / "fanout_work_counters.runtime.csv"
                self._paths["fanout_work_counters"] = counter_path
                self._counter_handle = counter_path.open(
                    "x", newline="", encoding="utf-8"
                )
                self._counter_writer = csv.DictWriter(
                    self._counter_handle,
                    fieldnames=FANOUT_WORK_COUNTER_COLUMNS,
                )
                self._counter_writer.writeheader()
        except BaseException:
            for handle in (
                getattr(self, "_interval_handle", None),
                getattr(self, "_counter_handle", None),
            ):
                if handle is not None:
                    handle.close()
            raise

    def _trace_id(self, frame_id: int) -> str:
        # DirectRuntimeJoinCoordinator publishes one canonical trace per input
        # frame, while preserving the worker-local execution IDs emitted by
        # DeepStreamProtocolBridge.  Resource rows must bind both identities.
        return f"{self.run_id}:{self.stream_id}:{frame_id}"

    @staticmethod
    def canonical_fanout_interval_end_ns(
        *,
        host_start_timestamp_ns: int,
        physical_end_timestamp_ns: int,
        serialized_topology_timestamp_ms: int,
    ) -> int:
        start = _integer(
            host_start_timestamp_ns, "fanout host start timestamp", minimum=1
        )
        physical_end = _integer(
            physical_end_timestamp_ns, "fanout physical end timestamp", minimum=1
        )
        if physical_end <= start:
            raise ValueError("DeepStream physical fanout interval must have positive width")
        serialized_ms = _integer(
            serialized_topology_timestamp_ms,
            "serialized fanout topology timestamp",
            minimum=1,
        )
        requested_ms = (physical_end + 999_999) // 1_000_000
        if serialized_ms < requested_ms:
            raise ValueError("DeepStream serialized fanout topology timestamp moved backwards")
        if serialized_ms == requested_ms:
            return physical_end
        canonical_end = serialized_ms * 1_000_000
        if canonical_end <= start:
            raise ValueError("DeepStream canonical fanout interval must have positive width")
        return canonical_end

    def _interval(
        self,
        *,
        frame_id: int,
        input_frame_key: str,
        branch: str,
        component: str,
        direction: str = "none",
        stage: str,
        execution_suffix: str,
        payload_bytes: int,
        start_timestamp_ns: int,
        end_timestamp_ns: int,
        device_id: str,
        provenance: str,
        duration_ns: int | None = None,
    ) -> dict[str, Any]:
        frame = _integer(frame_id, "frame_id")
        input_key = _text(input_frame_key, "input_frame_key")
        branch_id = _text(branch, "branch")
        if branch_id not in self.branches and not (
            component == "nvdec_submit_complete"
            and self.topology_kind == SHARED_VIDEO_DAG
            and branch_id == "shared"
        ):
            raise ValueError("DeepStream resource branch is outside this worker")
        size = _integer(payload_bytes, "payload bytes", minimum=1)
        start = _integer(start_timestamp_ns, "start timestamp", minimum=1)
        end = _integer(end_timestamp_ns, "end timestamp", minimum=1)
        if end <= start:
            raise ValueError("DeepStream resource end timestamp must follow start timestamp")
        duration = end - start if duration_ns is None else _integer(
            duration_ns, "resource duration", minimum=1
        )
        if duration > end - start:
            raise ValueError("DeepStream resource duration exceeds its host envelope")
        trace_id = self._trace_id(frame)
        execution_id = f"{trace_id}:{branch_id}:{execution_suffix}"
        identity = (component, frame, execution_id)
        if identity in self._identities:
            raise ValueError("DeepStream native resource execution was recorded twice")
        self._identities.add(identity)
        event_id = _native_event_id(
            (
                self.run_id,
                self.worker_id,
                trace_id,
                component,
                direction,
                execution_id,
                start,
                end,
                duration,
                size,
            )
        )
        return {
            "schema_version": TELEMETRY_SCHEMA_VERSION,
            "interval_contract_version": RESOURCE_INTERVAL_CONTRACT_VERSION,
            "run_id": self.run_id,
            "trace_id": trace_id,
            "stream_id": self.stream_id,
            "frame_id": frame,
            "input_frame_key": input_key,
            "component": component,
            "direction": direction,
            "stage": stage,
            "branch_id": branch_id,
            "execution_id": execution_id,
            "host_start_timestamp_ns": start,
            "host_end_timestamp_ns": end,
            "duration_ns": duration,
            "bytes": size,
            "device_id": device_id,
            "counter_scope": "per_trace_interval",
            "native_event_id": event_id,
            "duration_provenance": provenance,
            "telemetry_source": "native",
        }

    def record_nvdec(
        self,
        *,
        frame_id: int,
        input_frame_key: str,
        payload_bytes: int,
        start_timestamp_ns: int,
        end_timestamp_ns: int,
    ) -> None:
        branch = self.branches[0] if self.topology_kind == INDEPENDENT_PROCESSES else "shared"
        stage = f"decode_{branch}" if self.topology_kind == INDEPENDENT_PROCESSES else "decode"
        with self._lock:
            if self._closed:
                raise ValueError("DeepStream resource recorder is closed")
            row = self._interval(
                frame_id=frame_id,
                input_frame_key=input_frame_key,
                branch=branch,
                component="nvdec_submit_complete",
                stage=stage,
                execution_suffix="decode",
                payload_bytes=payload_bytes,
                start_timestamp_ns=start_timestamp_ns,
                end_timestamp_ns=end_timestamp_ns,
                device_id=f"nvdec:{self.decoder_gpu_index}",
                provenance="native_decoder_submit_complete_interval_v1",
            )
            self._interval_writer.writerow(row)

    def record_analytics_transfers(
        self,
        *,
        frame_id: int,
        input_frame_key: str,
        branch: str,
        selected_resource: str,
        worker_received_monotonic_ns: int,
        path_enter_timestamp_ns: int,
        resource: Mapping[str, Any],
    ) -> None:
        """Bind native CUDA events to the exact topology-v2 CPU/GPU edges."""

        resource_name = str(selected_resource)
        if resource_name not in {"cpu", "gpu"}:
            raise ValueError("DeepStream analytics resource is invalid")
        branch_id = _text(branch, "branch")
        if branch_id not in self.branches:
            raise ValueError("DeepStream analytics branch is outside this worker")
        expected_fields = {
            "process_cpu_time_ns",
            "rss_before_bytes",
            "rss_after_bytes",
            "accelerator_memory_bytes",
            "cuda_h2d_bytes",
            "cuda_d2h_bytes",
            "cuda_transfer_intervals",
        }
        if not isinstance(resource, Mapping) or set(resource) != expected_fields:
            raise ValueError("DeepStream analytics resource receipt fields drifted")
        for field in (
            "process_cpu_time_ns",
            "rss_before_bytes",
            "rss_after_bytes",
            "accelerator_memory_bytes",
            "cuda_h2d_bytes",
            "cuda_d2h_bytes",
        ):
            _integer(resource[field], f"analytics resource {field}")
        worker_received = _integer(
            worker_received_monotonic_ns,
            "worker received monotonic timestamp",
            minimum=1,
        )
        path_enter = _integer(
            path_enter_timestamp_ns,
            "path enter timestamp",
            minimum=1,
        )
        intervals = resource["cuda_transfer_intervals"]
        if not isinstance(intervals, list):
            raise ValueError("DeepStream CUDA transfer intervals must be a list")
        if resource_name == "cpu":
            if (
                resource["accelerator_memory_bytes"] != 0
                or resource["cuda_h2d_bytes"] != 0
                or resource["cuda_d2h_bytes"] != 0
                or intervals
            ):
                raise ValueError("DeepStream CPU analytics path reported CUDA resources")
            return
        if (
            resource["accelerator_memory_bytes"] <= 0
            or resource["cuda_h2d_bytes"] <= 0
            or resource["cuda_d2h_bytes"] <= 0
            or len(intervals) != 2
        ):
            raise ValueError("DeepStream GPU analytics path lacks exact CUDA resources")

        offset = path_enter - worker_received
        expected_directions = ("h2d", "d2h")
        previous_host_end: int | None = None
        with self._lock:
            if self._closed:
                raise ValueError("DeepStream resource recorder is closed")
            for raw, expected_direction in zip(
                intervals, expected_directions, strict=True
            ):
                interval_fields = {
                    "direction",
                    "host_start_monotonic_ns",
                    "host_end_monotonic_ns",
                    "device_elapsed_ns",
                    "bytes",
                    "device_id",
                    "timing_source",
                }
                if not isinstance(raw, Mapping) or set(raw) != interval_fields:
                    raise ValueError("DeepStream CUDA transfer interval fields drifted")
                direction = str(raw["direction"])
                if direction != expected_direction:
                    raise ValueError("DeepStream CUDA transfer direction order drifted")
                start_monotonic = _integer(
                    raw["host_start_monotonic_ns"],
                    f"CUDA {direction} host start",
                    minimum=1,
                )
                end_monotonic = _integer(
                    raw["host_end_monotonic_ns"],
                    f"CUDA {direction} host end",
                    minimum=1,
                )
                if start_monotonic < worker_received or end_monotonic <= start_monotonic:
                    raise ValueError("DeepStream CUDA transfer host envelope is invalid")
                if previous_host_end is not None and start_monotonic < previous_host_end:
                    raise ValueError("DeepStream CUDA transfer pair is out of order")
                previous_host_end = end_monotonic
                elapsed = _integer(
                    raw["device_elapsed_ns"],
                    f"CUDA {direction} device elapsed",
                    minimum=1,
                )
                if elapsed > end_monotonic - start_monotonic:
                    raise ValueError("DeepStream CUDA device duration exceeds its host envelope")
                expected_bytes = int(
                    resource[
                        "cuda_h2d_bytes" if direction == "h2d" else "cuda_d2h_bytes"
                    ]
                )
                payload_bytes = _integer(
                    raw["bytes"], f"CUDA {direction} bytes", minimum=1
                )
                if payload_bytes != expected_bytes:
                    raise ValueError("DeepStream CUDA transfer byte count drifted")
                if raw["timing_source"] != "cudaEventElapsedTime":
                    raise ValueError("DeepStream CUDA transfer timing is not cudaEventElapsedTime")
                gpu_uuid = _text(raw["device_id"], f"CUDA {direction} device_id")
                if _GPU_UUID_RE.fullmatch(gpu_uuid) is None:
                    raise ValueError(f"CUDA {direction} device_id is not an NVIDIA GPU UUID")
                canonical_gpu_uuid = gpu_uuid.lower()
                stage = branch_id if direction == "h2d" else f"postprocess_{branch_id}"
                suffix = "analytics" if direction == "h2d" else "postprocess"
                row = self._interval(
                    frame_id=frame_id,
                    input_frame_key=input_frame_key,
                    branch=branch_id,
                    component="transfer",
                    direction=direction,
                    stage=stage,
                    execution_suffix=suffix,
                    payload_bytes=payload_bytes,
                    start_timestamp_ns=start_monotonic + offset,
                    end_timestamp_ns=end_monotonic + offset,
                    device_id=f"gpu:{canonical_gpu_uuid}",
                    provenance="native_cuda_event_interval_v1",
                    duration_ns=elapsed,
                )
                self._interval_writer.writerow(row)

    def record_fanout(
        self,
        *,
        frame_id: int,
        input_frame_key: str,
        branch: str,
        payload_bytes: int,
        start_timestamp_ns: int,
        end_timestamp_ns: int,
        serialized_topology_timestamp_ms: int,
        thread_cpu_time_ns: int,
    ) -> None:
        if self.topology_kind != SHARED_VIDEO_DAG:
            raise ValueError("DeepStream fanout evidence requires shared topology")
        cpu_time = _integer(thread_cpu_time_ns, "thread CPU time", minimum=1)
        canonical_end_timestamp_ns = self.canonical_fanout_interval_end_ns(
            host_start_timestamp_ns=start_timestamp_ns,
            physical_end_timestamp_ns=end_timestamp_ns,
            serialized_topology_timestamp_ms=serialized_topology_timestamp_ms,
        )
        with self._lock:
            if self._closed:
                raise ValueError("DeepStream resource recorder is closed")
            row = self._interval(
                frame_id=frame_id,
                input_frame_key=input_frame_key,
                branch=branch,
                component="fanout",
                stage="fanout",
                execution_suffix="fanout",
                payload_bytes=payload_bytes,
                start_timestamp_ns=start_timestamp_ns,
                end_timestamp_ns=canonical_end_timestamp_ns,
                # DeepStream SDK routes are physical GStreamer tee/queue elements.
                device_id="gstreamer:tee-queue",
                provenance="native_gstreamer_pad_probe_interval_v1",
            )
            self._interval_writer.writerow(row)
            assert self._counter_writer is not None
            self._counter_writer.writerow(
                {
                    "schema_version": TELEMETRY_SCHEMA_VERSION,
                    "resource_contract_version": FULL_RESOURCE_CONTRACT_VERSION,
                    "run_id": self.run_id,
                    "trace_id": row["trace_id"],
                    "stream_id": self.stream_id,
                    "frame_id": row["frame_id"],
                    "input_frame_key": row["input_frame_key"],
                    "branch_id": branch,
                    "execution_id": row["execution_id"],
                    "thread_cpu_time_ns": cpu_time,
                    "work_units": 1,
                    "device_id": "host:fanout",
                    "counter_scope": "per_trace_resource_work",
                    "counter_provenance": "native_thread_cpu_time_v1",
                    "telemetry_source": "native",
                }
            )

    def close(self) -> dict[str, Path]:
        with self._lock:
            if not self._closed:
                for handle in (self._interval_handle, self._counter_handle):
                    if handle is not None:
                        handle.flush()
                        os.fsync(handle.fileno())
                        handle.close()
                self._closed = True
            return dict(self._paths)


__all__ = ["DeepStreamNativeResourceRecorderV3"]
