#!/usr/bin/env python3
"""Fail-closed ABI-v2 publication entrypoint for OpenVINO GVA."""
from __future__ import annotations

from collections.abc import Sequence

from checkpoint_publication_launcher_guard import (
    run_fail_closed_publication_launcher,
)


PUBLICATION_READY = False
BLOCKER = "openvino_gva native full-publication adapter is not implemented"


def main(argv: Sequence[str] | None = None) -> int:
    return run_fail_closed_publication_launcher(
        argv,
        expected_system="openvino_gva",
        blocker=BLOCKER,
    )


if __name__ == "__main__":
    raise SystemExit(main())
