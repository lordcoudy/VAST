#!/usr/bin/env python3
"""Image-local, code-authorized facade for GStreamer Custom ABI-v3."""

from __future__ import annotations

import sys
from collections.abc import Sequence

sys.dont_write_bytecode = True

from checkpoint_gstreamer_runtime import main as run_checkpoint_runtime


def main(argv: Sequence[str] | None = None) -> int:
    values = tuple(sys.argv[1:] if argv is None else argv)
    if any(
        type(value) is not str
        or value == "--system"
        or value.startswith("--system=")
        for value in values
    ):
        raise ValueError("GStreamer Custom image rejects a system override")
    return run_checkpoint_runtime(("--system", "gstreamer_custom", *values))


if __name__ == "__main__":
    raise SystemExit(main())
