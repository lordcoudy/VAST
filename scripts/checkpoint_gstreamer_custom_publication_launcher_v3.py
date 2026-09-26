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


PUBLICATION_READY = True
NATIVE_RUNTIME_ENTRYPOINT = (
    "checkpoint_gstreamer_publication_runtime_v3."
    "run_checkpoint_gstreamer_publication_runtime_v3"
)
NATIVE_TOPOLOGY_RUNNERS = {
    "independent_processes": run_checkpoint_gstreamer_publication_runtime_v3,
    "shared_video_dag": run_checkpoint_gstreamer_publication_runtime_v3,
}


def main(argv: Sequence[str] | None = None) -> int:
    return run_native_publication_launcher_adapter_v3(
        argv,
        expected_system="gstreamer_custom",
        native_topology_runners=NATIVE_TOPOLOGY_RUNNERS,
    )


if __name__ == "__main__":
    raise SystemExit(main())
