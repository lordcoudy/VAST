#!/usr/bin/env python3
from __future__ import annotations

import struct
from dataclasses import dataclass


TRACE_EXTENSION_ID = 1
TRACE_MAGIC = 0x5641  # "VA"
TRACE_VERSION = 1
TRACE_STRUCT = struct.Struct("!HBBIQ")


@dataclass(frozen=True)
class RtpTrace:
    stream_id: int
    frame_id: int
    ingress_timestamp_ms: int

    @property
    def trace_id_suffix(self) -> str:
        return f"{self.stream_id}:{self.frame_id}"


def pack_trace(trace: RtpTrace) -> bytes:
    if trace.stream_id < 0 or trace.stream_id > 255:
        raise ValueError("stream_id must fit in one byte")
    if trace.frame_id < 0 or trace.frame_id > 0xFFFFFFFF:
        raise ValueError("frame_id must fit in uint32")
    if trace.ingress_timestamp_ms < 0:
        raise ValueError("ingress_timestamp_ms must be non-negative")
    return TRACE_STRUCT.pack(
        TRACE_MAGIC,
        TRACE_VERSION,
        int(trace.stream_id),
        int(trace.frame_id),
        int(trace.ingress_timestamp_ms),
    )


def unpack_trace(payload: bytes) -> RtpTrace:
    if len(payload) != TRACE_STRUCT.size:
        raise ValueError(f"trace payload must be {TRACE_STRUCT.size} bytes")
    magic, version, stream_id, frame_id, ingress_ms = TRACE_STRUCT.unpack(payload)
    if magic != TRACE_MAGIC:
        raise ValueError("invalid trace magic")
    if version != TRACE_VERSION:
        raise ValueError("unsupported trace version")
    return RtpTrace(stream_id=stream_id, frame_id=frame_id, ingress_timestamp_ms=ingress_ms)
