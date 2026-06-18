from __future__ import annotations

import argparse
import csv
import os
import struct
import sys
import time
from pathlib import Path
from typing import Any


TRACE_EXTENSION_URI = "urn:vast:rtp-trace:v1"
TRACE_EXTENSION_ID = 1
TRACE_STRUCT = struct.Struct("!HBBIQ")
TRACE_MAGIC = 0x5641
TRACE_VERSION = 1
FRAME_EVENT_COLUMNS = [
    "schema_version",
    "run_id",
    "trace_id",
    "stream_id",
    "frame_id",
    "stage",
    "role",
    "host",
    "resource",
    "queue_enter_timestamp_ms",
    "stage_start_timestamp_ms",
    "stage_end_timestamp_ms",
    "queue_depth",
    "estimated_cost_ms",
    "policy_action",
]
FRAME_COLUMNS = [
    "schema_version",
    "run_id",
    "trace_id",
    "stream_id",
    "frame_id",
    "ingress_timestamp_ms",
    "egress_timestamp_ms",
    "e2e_latency_ms",
    "objects",
    "detector",
    "backend",
    "telemetry_source",
]

_LOCAL_INGRESS_MS: dict[tuple[int, int], int] = {}
_INITIALIZED_EVENT_FILES: set[Path] = set()


def now_ms() -> int:
    return int(time.time() * 1000)


def unpack_trace(payload: bytes) -> tuple[int, int, int]:
    magic, version, stream_id, frame_id, ingress_ms = TRACE_STRUCT.unpack(payload)
    if magic != TRACE_MAGIC or version != TRACE_VERSION:
        raise ValueError("invalid VAST RTP trace payload")
    return stream_id, frame_id, ingress_ms


class NativeEventWriter:
    def __init__(
        self,
        output_dir: str,
        run_id: str,
        stage: str,
        role: str,
        resource: str = "gpu",
        shared: bool = False,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id
        self.stage = stage
        self.role = role
        self.resource = resource
        self.path = self.output_dir / "frame_events.csv"
        write_header = not shared or self.path not in _INITIALIZED_EVENT_FILES
        self.file = self.path.open("w" if write_header else "a", newline="", encoding="utf-8")
        self.writer = csv.DictWriter(self.file, fieldnames=FRAME_EVENT_COLUMNS)
        if write_header:
            self.writer.writeheader()
            self.file.flush()
            if shared:
                _INITIALIZED_EVENT_FILES.add(self.path)

    def write(self, stream_id: int, frame_id: int, start_ms: int, end_ms: int) -> None:
        trace_id = f"{self.run_id}:{stream_id}:{frame_id}"
        self.writer.writerow(
            {
                "schema_version": 2,
                "run_id": self.run_id,
                "trace_id": trace_id,
                "stream_id": stream_id,
                "frame_id": frame_id,
                "stage": self.stage,
                "role": self.role,
                "host": os.uname().nodename,
                "resource": self.resource,
                "queue_enter_timestamp_ms": start_ms,
                "stage_start_timestamp_ms": start_ms,
                "stage_end_timestamp_ms": end_ms,
                "queue_depth": 0,
                "estimated_cost_ms": max(1, end_ms - start_ms),
                "policy_action": "native:savant",
            }
        )
        self.file.flush()

    def close(self) -> None:
        self.file.close()


class NativeFrameWriter:
    def __init__(self, output_dir: str, run_id: str, detector: str, backend: str, min_objects: int, max_objects: int) -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id
        self.detector = detector
        self.backend = backend
        self.min_objects = min_objects
        self.max_objects = max_objects
        self.path = self.output_dir / "frames.csv"
        self.file = self.path.open("w", newline="", encoding="utf-8")
        self.writer = csv.DictWriter(self.file, fieldnames=FRAME_COLUMNS)
        self.writer.writeheader()

    def write(self, stream_id: int, frame_id: int, ingress_ms: int, egress_ms: int) -> None:
        self.writer.writerow(
            {
                "schema_version": 2,
                "run_id": self.run_id,
                "trace_id": f"{self.run_id}:{stream_id}:{frame_id}",
                "stream_id": stream_id,
                "frame_id": frame_id,
                "ingress_timestamp_ms": ingress_ms,
                "egress_timestamp_ms": egress_ms,
                "e2e_latency_ms": max(0, egress_ms - ingress_ms),
                "objects": object_count(self.min_objects, self.max_objects),
                "detector": self.detector,
                "backend": self.backend,
                "telemetry_source": "native",
            }
        )
        self.file.flush()

    def close(self) -> None:
        self.file.close()


def object_count(min_objects: int, max_objects: int) -> int:
    return max(min_objects, min(max_objects, (min_objects + max_objects) // 2))


def frame_identity(frame: Any) -> tuple[int, int]:
    stream_id = int(os.environ.get("VAST_STREAM_ID", getattr(frame, "source_id", 0) or 0))
    frame_id = int(getattr(frame, "pts", 0) or getattr(frame, "idx", 0) or 0)
    return stream_id, frame_id


class SavantNativeDetectProbe:
    """Savant pyfunc hook that writes strict native detect events.

    The hook is intentionally small: Savant owns decode/detect execution, while this
    module records the native stage event when frame metadata carries the VAST RTP
    trace fields propagated by the canonical transport.
    """

    def __init__(self, stage: str, role: str, output_dir: str, run_id: str, **_: Any) -> None:
        self.writer = NativeEventWriter(output_dir, run_id, stage, role)

    def __call__(self, frame: Any, *args: Any, **kwargs: Any) -> Any:
        start_ms = now_ms()
        stream_id = int(os.environ.get("VAST_STREAM_ID", getattr(frame, "source_id", 0) or 0))
        frame_id = int(getattr(frame, "pts", 0) or 0)
        trace_payload = getattr(frame, "vast_rtp_trace", None)
        if isinstance(trace_payload, (bytes, bytearray)) and len(trace_payload) == TRACE_STRUCT.size:
            try:
                stream_id, frame_id, _ = unpack_trace(bytes(trace_payload))
            except ValueError:
                pass
        self.writer.write(stream_id, frame_id, start_ms, now_ms())
        return frame

    def on_stop(self) -> None:
        self.writer.close()


class SavantLocalTelemetryProbe:
    """Savant pyfunc hook that writes strict local benchmark telemetry."""

    def __init__(
        self,
        stage: str,
        output_dir: str,
        run_id: str,
        detector: str,
        backend: str,
        min_objects: int = 0,
        max_objects: int = 20,
        role: str = "local",
        **_: Any,
    ) -> None:
        resource = "gpu" if stage == "detect" else "cpu"
        self.stage = stage
        self.events = NativeEventWriter(output_dir, run_id, stage, role, resource=resource, shared=True)
        self.frames = (
            NativeFrameWriter(output_dir, run_id, detector, backend, int(min_objects), int(max_objects))
            if stage == "aggregate"
            else None
        )

    def __call__(self, frame: Any, *args: Any, **kwargs: Any) -> Any:
        start_ms = now_ms()
        stream_id, frame_id = frame_identity(frame)
        key = (stream_id, frame_id)
        if self.stage == "decode":
            _LOCAL_INGRESS_MS[key] = start_ms
        end_ms = now_ms()
        self.events.write(stream_id, frame_id, start_ms, end_ms)
        if self.stage == "aggregate" and self.frames is not None:
            ingress_ms = _LOCAL_INGRESS_MS.pop(key, start_ms)
            self.frames.write(stream_id, frame_id, ingress_ms, end_ms)
        return frame

    def on_stop(self) -> None:
        self.events.close()
        if self.frames is not None:
            self.frames.close()


def merge_csvs(paths: list[Path], output: Path, fieldnames: list[str]) -> int:
    rows = 0
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as out:
        writer = csv.DictWriter(out, fieldnames=fieldnames)
        writer.writeheader()
        for path in paths:
            with path.open("r", newline="", encoding="utf-8") as src:
                reader = csv.DictReader(src)
                for row in reader:
                    writer.writerow({field: row.get(field, "") for field in fieldnames})
                    rows += 1
    return rows


def merge_local_outputs(output_dir: str | Path, streams: int) -> None:
    root = Path(output_dir)
    stream_dirs = [root / "streams" / f"stream_{stream_id}" for stream_id in range(max(1, int(streams)))]
    frame_paths = [path / "frames.csv" for path in stream_dirs]
    event_paths = [path / "frame_events.csv" for path in stream_dirs]
    missing = [str(path) for path in frame_paths + event_paths if not path.exists()]
    if missing:
        raise RuntimeError("missing Savant local telemetry files: " + ", ".join(missing))

    frame_rows = merge_csvs(frame_paths, root / "frames.csv", FRAME_COLUMNS)
    event_rows = merge_csvs(event_paths, root / "frame_events.csv", FRAME_EVENT_COLUMNS)
    if frame_rows == 0:
        raise RuntimeError(f"Savant local telemetry merge produced no frame rows in {root / 'frames.csv'}")
    if event_rows == 0:
        raise RuntimeError(f"Savant local telemetry merge produced no event rows in {root / 'frame_events.csv'}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Savant native telemetry helpers")
    parser.add_argument("--merge-local", action="store_true", help="Merge per-stream local telemetry CSV files")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--streams", type=int, required=True)
    args = parser.parse_args(argv)
    if not args.merge_local:
        parser.error("expected --merge-local")
    merge_local_outputs(args.output_dir, args.streams)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[savant-native-probe][error] {exc}", file=sys.stderr)
        raise SystemExit(1)
