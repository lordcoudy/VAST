#!/usr/bin/env python3
"""Fail-closed Savant publication entrypoint for dispatch ABI v2."""
from __future__ import annotations

from typing import Sequence

from checkpoint_publication_launcher_guard import (
    run_fail_closed_publication_launcher,
)


PUBLICATION_READY = False
_BLOCKER = (
    "checkpoint_savant_launcher.py is engineering-only and its generated "
    "module configuration/native runtime are missing"
)


def main(argv: Sequence[str] | None = None) -> int:
    return run_fail_closed_publication_launcher(
        argv,
        expected_system="savant",
        blocker=_BLOCKER,
    )


if __name__ == "__main__":
    raise SystemExit(main())
