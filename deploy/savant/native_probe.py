from __future__ import annotations

import argparse
import csv
import math
import os
import struct
import sys
import threading
import time
from pathlib import Path
from typing import Any, Iterator

try:
    from savant.base.pyfunc import BasePyFuncPlugin
except Exception:
    class BasePyFuncPlugin:  # type: ignore[no-redef]
        def __init__(self, **_: Any) -> None:
            self.gst_element = None

        def on_start(self) -> bool:
            return True

        def on_stop(self) -> bool:
            return True

        def process_buffer(self, buffer: Any) -> Any:
            return buffer


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
_LOCAL_INGRESS_LOCK = threading.Lock()
_SHARED_EVENT_WRITERS: dict[Path, "_SharedCsvWriter"] = {}
_SHARED_EVENT_WRITERS_LOCK = threading.Lock()
_NULL_STRINGS = {"", "none", "nan", "null"}
_FRAME_NUMERIC_COLUMNS = {
    "schema_version",
    "stream_id",
    "frame_id",
    "ingress_timestamp_ms",
    "egress_timestamp_ms",
    "e2e_latency_ms",
    "objects",
}
_FRAME_EVENT_NUMERIC_COLUMNS = {
    "schema_version",
    "stream_id",
    "frame_id",
    "queue_enter_timestamp_ms",
    "stage_start_timestamp_ms",
    "stage_end_timestamp_ms",
    "queue_depth",
    "estimated_cost_ms",
}


def now_ms() -> int:
    return int(time.time() * 1000)


def unpack_trace(payload: bytes) -> tuple[int, int, int]:
    magic, version, stream_id, frame_id, ingress_ms = TRACE_STRUCT.unpack(payload)
    if magic != TRACE_MAGIC or version != TRACE_VERSION:
        raise ValueError("invalid VAST RTP trace payload")
    return stream_id, frame_id, ingress_ms


def missing_value(value: Any) -> bool:
    if value is None:
        return True
    return str(value).strip().lower() in _NULL_STRINGS


def validate_csv_row(
    row: dict[str, Any],
    fieldnames: list[str],
    numeric_columns: set[str],
    *,
    source: str,
) -> dict[str, Any]:
    if None in row:
        raise RuntimeError(f"{source}: unexpected extra CSV fields: {row[None]!r}")
    normalized: dict[str, Any] = {}
    for field in fieldnames:
        value = row.get(field)
        if missing_value(value):
            raise RuntimeError(f"{source}: missing or empty value for {field}")
        normalized[field] = value

    if not str(normalized.get("trace_id", "")).strip():
        raise RuntimeError(f"{source}: missing or empty trace_id")

    for field in numeric_columns:
        try:
            number = float(normalized[field])
        except (TypeError, ValueError) as exc:
            raise RuntimeError(f"{source}: invalid numeric value for {field}: {normalized[field]!r}") from exc
        if not math.isfinite(number):
            raise RuntimeError(f"{source}: invalid numeric value for {field}: {normalized[field]!r}")

    return normalized


class _SharedCsvWriter:
    def __init__(self, path: Path, fieldnames: list[str]) -> None:
        self.path = path
        self.fieldnames = fieldnames
        self.lock = threading.Lock()
        self.refcount = 0
        self.file = self.path.open("w", newline="", encoding="utf-8")
        self.writer = csv.DictWriter(self.file, fieldnames=self.fieldnames)
        self.writer.writeheader()
        self.file.flush()

    def write(self, row: dict[str, Any]) -> None:
        with self.lock:
            self.writer.writerow(row)
            self.file.flush()

    def close(self) -> None:
        with self.lock:
            if not self.file.closed:
                self.file.close()


def acquire_shared_writer(path: Path, fieldnames: list[str]) -> _SharedCsvWriter:
    path.parent.mkdir(parents=True, exist_ok=True)
    path = path.resolve()
    with _SHARED_EVENT_WRITERS_LOCK:
        writer = _SHARED_EVENT_WRITERS.get(path)
        if writer is None:
            writer = _SharedCsvWriter(path, fieldnames)
            _SHARED_EVENT_WRITERS[path] = writer
        writer.refcount += 1
        return writer


def release_shared_writer(path: Path, writer: _SharedCsvWriter) -> None:
    path = path.resolve()
    close_writer: _SharedCsvWriter | None = None
    with _SHARED_EVENT_WRITERS_LOCK:
        current = _SHARED_EVENT_WRITERS.get(path)
        if current is not writer:
            return
        current.refcount -= 1
        if current.refcount <= 0:
            close_writer = current
            del _SHARED_EVENT_WRITERS[path]
    if close_writer is not None:
        close_writer.close()


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
        self.shared = shared
        self.closed = False
        self.lock = threading.Lock()
        self.shared_writer: _SharedCsvWriter | None = None
        if shared:
            self.shared_writer = acquire_shared_writer(self.path, FRAME_EVENT_COLUMNS)
        else:
            self.file = self.path.open("w", newline="", encoding="utf-8")
            self.writer = csv.DictWriter(self.file, fieldnames=FRAME_EVENT_COLUMNS)
            self.writer.writeheader()
            self.file.flush()

    def write(self, stream_id: int, frame_id: int, start_ms: int, end_ms: int) -> None:
        trace_id = f"{self.run_id}:{stream_id}:{frame_id}"
        row = validate_csv_row(
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
            },
            FRAME_EVENT_COLUMNS,
            _FRAME_EVENT_NUMERIC_COLUMNS,
            source=f"{self.path}:emitted",
        )
        if self.shared_writer is not None:
            self.shared_writer.write(row)
        else:
            with self.lock:
                self.writer.writerow(row)
                self.file.flush()

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        if self.shared_writer is not None:
            release_shared_writer(self.path, self.shared_writer)
        else:
            with self.lock:
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
        self.lock = threading.Lock()
        self.closed = False
        self.file = self.path.open("w", newline="", encoding="utf-8")
        self.writer = csv.DictWriter(self.file, fieldnames=FRAME_COLUMNS)
        self.writer.writeheader()

    def write(self, stream_id: int, frame_id: int, ingress_ms: int, egress_ms: int) -> None:
        row = validate_csv_row(
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
            },
            FRAME_COLUMNS,
            _FRAME_NUMERIC_COLUMNS,
            source=f"{self.path}:emitted",
        )
        with self.lock:
            self.writer.writerow(row)
            self.file.flush()

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        with self.lock:
            self.file.close()


def object_count(min_objects: int, max_objects: int) -> int:
    return max(min_objects, min(max_objects, (min_objects + max_objects) // 2))


def frame_identity(frame_or_buffer: Any) -> tuple[int, int]:
    stream_id = int(os.environ.get("VAST_STREAM_ID", getattr(frame_or_buffer, "source_id", 0) or 0))
    frame_id = int(
        getattr(frame_or_buffer, "pts", None)
        or getattr(frame_or_buffer, "offset", None)
        or getattr(frame_or_buffer, "idx", None)
        or 0
    )
    return stream_id, frame_id


class SavantNativeDetectProbe(BasePyFuncPlugin):
    """Savant pyfunc hook that writes strict native detect events.

    The hook is intentionally small: Savant owns decode/detect execution, while this
    module records the native stage event when frame metadata carries the VAST RTP
    trace fields propagated by the canonical transport.
    """

    def __init__(self, stage: str, role: str, output_dir: str, run_id: str, **_: Any) -> None:
        super().__init__()
        self.writer = NativeEventWriter(output_dir, run_id, stage, role)

    def process_buffer(self, buffer: Any) -> Any:
        start_ms = now_ms()
        stream_id, frame_id = frame_identity(buffer)
        trace_payload = getattr(buffer, "vast_rtp_trace", None)
        if isinstance(trace_payload, (bytes, bytearray)) and len(trace_payload) == TRACE_STRUCT.size:
            try:
                stream_id, frame_id, _ = unpack_trace(bytes(trace_payload))
            except ValueError:
                pass
        self.writer.write(stream_id, frame_id, start_ms, now_ms())
        return buffer

    def __call__(self, frame: Any, *args: Any, **kwargs: Any) -> Any:
        return self.process_buffer(frame)

    def on_stop(self) -> bool:
        self.writer.close()
        return True


class SavantLocalTelemetryProbe(BasePyFuncPlugin):
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
        super().__init__()
        resource = "gpu" if stage == "detect" else "cpu"
        self.stage = stage
        self.events = NativeEventWriter(output_dir, run_id, stage, role, resource=resource, shared=True)
        self.frames = (
            NativeFrameWriter(output_dir, run_id, detector, backend, int(min_objects), int(max_objects))
            if stage == "aggregate"
            else None
        )

    def process_buffer(self, buffer: Any) -> Any:
        start_ms = now_ms()
        stream_id, frame_id = frame_identity(buffer)
        key = (stream_id, frame_id)
        if self.stage == "decode":
            with _LOCAL_INGRESS_LOCK:
                _LOCAL_INGRESS_MS[key] = start_ms
        end_ms = now_ms()
        self.events.write(stream_id, frame_id, start_ms, end_ms)
        if self.stage == "aggregate" and self.frames is not None:
            with _LOCAL_INGRESS_LOCK:
                ingress_ms = _LOCAL_INGRESS_MS.pop(key, start_ms)
            self.frames.write(stream_id, frame_id, ingress_ms, end_ms)
        return buffer

    def __call__(self, frame: Any, *args: Any, **kwargs: Any) -> Any:
        return self.process_buffer(frame)

    def on_stop(self) -> bool:
        self.events.close()
        if self.frames is not None:
            self.frames.close()
        return True


def read_timestamp_marker(root: Path, name: str) -> int | None:
    path = root / name
    if not path.exists():
        return None
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError as exc:
        raise RuntimeError(f"invalid Savant measurement marker {path}: {raw!r}") from exc


def row_timestamp(row: dict[str, Any], column: str, *, path: Path, row_number: int) -> int:
    raw_value = row.get(column)
    if missing_value(raw_value):
        raise RuntimeError(f"{path}:{row_number}: missing or empty timestamp column {column}")
    raw = str(raw_value).strip()
    try:
        return int(float(raw))
    except ValueError as exc:
        raise RuntimeError(f"{path}:{row_number}: invalid Savant timestamp value for {column}: {raw!r}") from exc


def row_in_window(
    row: dict[str, Any],
    *,
    start_column: str,
    end_column: str,
    min_timestamp_ms: int | None,
    max_timestamp_ms: int | None,
    path: Path,
    row_number: int,
) -> bool:
    if min_timestamp_ms is not None and row_timestamp(row, start_column, path=path, row_number=row_number) < min_timestamp_ms:
        return False
    if max_timestamp_ms is not None and row_timestamp(row, end_column, path=path, row_number=row_number) > max_timestamp_ms:
        return False
    return True


def iter_csv_rows(paths: list[Path]) -> Iterator[tuple[Path, int, dict[str, Any]]]:
    for path in paths:
        with path.open("r", newline="", encoding="utf-8") as src:
            reader = csv.DictReader(src)
            for row_number, row in enumerate(reader, start=2):
                yield path, row_number, row


def row_trace_id(row: dict[str, Any]) -> str:
    value = row.get("trace_id")
    if missing_value(value):
        return ""
    return str(value).strip()


def merge_frame_csvs(
    paths: list[Path],
    output: Path,
    *,
    min_timestamp_ms: int | None = None,
    max_timestamp_ms: int | None = None,
) -> tuple[int, set[str]]:
    rows = 0
    trace_ids: set[str] = set()
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as out:
        writer = csv.DictWriter(out, fieldnames=FRAME_COLUMNS)
        writer.writeheader()
        for path, row_number, row in iter_csv_rows(paths):
            normalized = validate_csv_row(
                row,
                FRAME_COLUMNS,
                _FRAME_NUMERIC_COLUMNS,
                source=f"{path}:{row_number}",
            )
            if not row_in_window(
                normalized,
                start_column="ingress_timestamp_ms",
                end_column="egress_timestamp_ms",
                min_timestamp_ms=min_timestamp_ms,
                max_timestamp_ms=max_timestamp_ms,
                path=path,
                row_number=row_number,
            ):
                continue
            writer.writerow(normalized)
            trace_ids.add(str(normalized["trace_id"]).strip())
            rows += 1
    return rows, trace_ids


def merge_event_csvs(
    paths: list[Path],
    output: Path,
    measured_trace_ids: set[str],
) -> tuple[int, dict[str, set[str]]]:
    rows = 0
    stage_traces: dict[str, set[str]] = {}
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as out:
        writer = csv.DictWriter(out, fieldnames=FRAME_EVENT_COLUMNS)
        writer.writeheader()
        for path, row_number, row in iter_csv_rows(paths):
            trace_id = row_trace_id(row)
            if trace_id not in measured_trace_ids:
                continue
            normalized = validate_csv_row(
                row,
                FRAME_EVENT_COLUMNS,
                _FRAME_EVENT_NUMERIC_COLUMNS,
                source=f"{path}:{row_number}",
            )
            writer.writerow(normalized)
            stage = str(normalized["stage"]).strip()
            stage_traces.setdefault(stage, set()).add(trace_id)
            rows += 1
    return rows, stage_traces


def validate_required_stage_events(measured_trace_ids: set[str], stage_traces: dict[str, set[str]]) -> None:
    for stage in ("decode", "detect", "aggregate"):
        missing = measured_trace_ids - stage_traces.get(stage, set())
        if missing:
            sample = ", ".join(sorted(missing)[:5])
            raise RuntimeError(
                f"Savant local telemetry is missing '{stage}' frame_events for "
                f"{len(missing)} measured frames; sample trace_id values: {sample}"
            )


def merge_local_outputs(output_dir: str | Path, streams: int) -> None:
    root = Path(output_dir)
    stream_dirs = [root / "streams" / f"stream_{stream_id}" for stream_id in range(max(1, int(streams)))]
    frame_paths = [path / "frames.csv" for path in stream_dirs]
    event_paths = [path / "frame_events.csv" for path in stream_dirs]
    missing = [str(path) for path in frame_paths + event_paths if not path.exists()]
    if missing:
        raise RuntimeError("missing Savant local telemetry files: " + ", ".join(missing))

    measurement_start_ms = read_timestamp_marker(root, "measurement_start_ms")
    measurement_end_ms = read_timestamp_marker(root, "measurement_end_ms")

    frame_rows, measured_trace_ids = merge_frame_csvs(
        frame_paths,
        root / "frames.csv",
        min_timestamp_ms=measurement_start_ms,
        max_timestamp_ms=measurement_end_ms,
    )
    event_rows, stage_traces = merge_event_csvs(
        event_paths,
        root / "frame_events.csv",
        measured_trace_ids,
    )
    if frame_rows == 0:
        raise RuntimeError(f"Savant local telemetry merge produced no frame rows in {root / 'frames.csv'}")
    if event_rows == 0:
        raise RuntimeError(f"Savant local telemetry merge produced no event rows in {root / 'frame_events.csv'}")
    validate_required_stage_events(measured_trace_ids, stage_traces)


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
