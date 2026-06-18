from __future__ import annotations

import csv
import os
import struct
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


def now_ms() -> int:
    return int(time.time() * 1000)


def unpack_trace(payload: bytes) -> tuple[int, int, int]:
    magic, version, stream_id, frame_id, ingress_ms = TRACE_STRUCT.unpack(payload)
    if magic != TRACE_MAGIC or version != TRACE_VERSION:
        raise ValueError("invalid VAST RTP trace payload")
    return stream_id, frame_id, ingress_ms


class NativeEventWriter:
    def __init__(self, output_dir: str, run_id: str, stage: str, role: str) -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id
        self.stage = stage
        self.role = role
        self.path = self.output_dir / "frame_events.csv"
        self.file = self.path.open("w", newline="", encoding="utf-8")
        self.writer = csv.DictWriter(self.file, fieldnames=FRAME_EVENT_COLUMNS)
        self.writer.writeheader()

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
                "resource": "gpu",
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
