#!/usr/bin/env python3
"""Child-only DeepStream publication launcher adapter for ABI v3."""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True

from collections.abc import Sequence

from checkpoint_deepstream_publication_runtime_v3 import (
    run_checkpoint_deepstream_publication_runtime_v3,
)
from checkpoint_publication_launcher_adapter_v3 import (
    run_native_publication_launcher_adapter_v3,
)


PUBLICATION_READY = False
NATIVE_RUNTIME_ENTRYPOINT = (
    "checkpoint_deepstream_publication_runtime_v3."
    "run_checkpoint_deepstream_publication_runtime_v3"
)
MISSING_RUNTIME_PINS = (
    "deepstream_publication_runtime_v3_image_grant_not_materialized",
    "deepstream_publication_runtime_v3_endpoint_bound_24_6_full_kpp_arm_pilot_not_complete",
)
BLOCKER = MISSING_RUNTIME_PINS[0]


NATIVE_TOPOLOGY_RUNNERS = {
    "independent_processes": run_checkpoint_deepstream_publication_runtime_v3,
    "shared_video_dag": run_checkpoint_deepstream_publication_runtime_v3,
}


def main(argv: Sequence[str] | None = None) -> int:
    return run_native_publication_launcher_adapter_v3(
        argv,
        expected_system="deepstream",
        native_topology_runners=NATIVE_TOPOLOGY_RUNNERS,
        readiness_blockers=MISSING_RUNTIME_PINS,
    )


if __name__ == "__main__":
    raise SystemExit(main())
