#!/usr/bin/env python3
"""Fail-closed DeepStream publication entrypoint for dispatch ABI v2."""
from __future__ import annotations

from typing import Sequence

from checkpoint_publication_launcher_guard import (
    run_fail_closed_publication_launcher,
)


PUBLICATION_READY = False
_BLOCKER = (
    "checkpoint_deepstream_launcher.py only emits a launch manifest with "
    "accepted_measurement_evidence_emitted=false and publication_ready=false"
)


def main(argv: Sequence[str] | None = None) -> int:
    return run_fail_closed_publication_launcher(
        argv,
        expected_system="deepstream",
        blocker=_BLOCKER,
    )


if __name__ == "__main__":
    raise SystemExit(main())
