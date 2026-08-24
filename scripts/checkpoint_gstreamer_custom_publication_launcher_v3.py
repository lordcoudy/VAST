#!/usr/bin/env python3
"""Fail-closed custom GStreamer publication entrypoint scaffold for ABI v3."""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True

from collections.abc import Sequence

from checkpoint_publication_launcher_guard_v3 import (
    run_fail_closed_publication_launcher_v3,
)


PUBLICATION_READY = False
BLOCKER = "gstreamer_custom_native_publication_adapter_not_implemented"


def main(argv: Sequence[str] | None = None) -> int:
    return run_fail_closed_publication_launcher_v3(
        argv,
        expected_system="gstreamer_custom",
        implementation_blocker=BLOCKER,
    )


if __name__ == "__main__":
    raise SystemExit(main())
