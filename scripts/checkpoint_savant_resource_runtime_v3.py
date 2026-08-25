#!/usr/bin/env python3
"""Savant-owned physical NVDEC/fanout resource fragment emitter v3."""
from __future__ import annotations

from checkpoint_deepstream_resource_runtime_v3 import (
    DeepStreamNativeResourceRecorderV3,
)


EMITTER_ID = "vast-savant-native-resource-recorder-v3"
IMPLEMENTATION_ID = (
    "savant-0.5.17-deepstream-7.0-native-nvdec-fanout-intervals-v3"
)


class SavantNativeResourceRecorderV3(DeepStreamNativeResourceRecorderV3):
    """Use the shared schema with Savant-local identity and canonical traces."""

    emitter_id = EMITTER_ID
    implementation_id = IMPLEMENTATION_ID

    def _trace_id(self, frame_id: int) -> str:
        # DirectRuntimeJoinCoordinator assigns the same gap-free frame ID from
        # the six common admission streams; worker suffixes are prohibited.
        return f"{self.run_id}:{self.stream_id}:{frame_id}"


__all__ = [
    "EMITTER_ID",
    "IMPLEMENTATION_ID",
    "SavantNativeResourceRecorderV3",
]
