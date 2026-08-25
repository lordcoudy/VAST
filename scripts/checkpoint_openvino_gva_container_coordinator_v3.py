#!/usr/bin/env python3
"""Code-authorized OpenVINO facade for the shared checkpoint coordinator."""

from __future__ import annotations

import sys
from collections.abc import Sequence

sys.dont_write_bytecode = True

from checkpoint_gstreamer_runtime import main as run_checkpoint_runtime


def main(argv: Sequence[str] | None = None) -> int:
    return run_checkpoint_runtime(
        None if argv is None else tuple(argv),
        publication_system_authority="openvino_gva",
    )


if __name__ == "__main__":
    raise SystemExit(main())
