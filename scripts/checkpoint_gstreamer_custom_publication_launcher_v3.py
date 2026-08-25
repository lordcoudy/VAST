#!/usr/bin/env python3
"""Child-only custom GStreamer publication launcher adapter for ABI v3."""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True

from collections.abc import Sequence

from checkpoint_gstreamer_publication_runtime_v3 import (
    run_checkpoint_gstreamer_publication_runtime_v3,
)
from checkpoint_publication_launcher_adapter_v3 import (
    run_native_publication_launcher_adapter_v3,
)


PUBLICATION_READY = False
NATIVE_RUNTIME_ENTRYPOINT = (
    "checkpoint_gstreamer_publication_runtime_v3."
    "run_checkpoint_gstreamer_publication_runtime_v3"
)
MISSING_RUNTIME_PINS = (
    "gstreamer_custom_publication_v3_accepted_model_policy_sidecars_not_materialized",
    "gstreamer_custom_publication_v3_endpoint_bound_h264_h265_24_6_gpu_pilots_not_complete",
)
BLOCKER = MISSING_RUNTIME_PINS[0]


NATIVE_TOPOLOGY_RUNNERS = {
    "independent_processes": run_checkpoint_gstreamer_publication_runtime_v3,
    "shared_video_dag": run_checkpoint_gstreamer_publication_runtime_v3,
}


def main(argv: Sequence[str] | None = None) -> int:
    return run_native_publication_launcher_adapter_v3(
        argv,
        expected_system="gstreamer_custom",
        native_topology_runners=NATIVE_TOPOLOGY_RUNNERS,
        readiness_blockers=MISSING_RUNTIME_PINS,
    )


if __name__ == "__main__":
    raise SystemExit(main())
