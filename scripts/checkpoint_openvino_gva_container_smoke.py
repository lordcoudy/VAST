#!/usr/bin/env python3
"""Offline pinned-image engineering smoke for the OpenVINO GVA topology.

The smoke creates one synthetic H.264 access unit and one synthetic H.265
access unit under a fresh ``/tmp`` directory, then runs the exact six-stream
independent-process (24 workers) and shared-video-DAG (six graphs) inventories.
It deliberately uses the synthetic terminal bridge and never writes accepted
benchmark evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from checkpoint_openvino_gva_launcher import (
    ENGINEERING_BLOCKERS,
    ENGINEERING_CLAIM_STATUS,
    EngineeringSyntheticBridge,
    INDEPENDENT_PROCESSES,
    SHARED_VIDEO_DAG,
    run_openvino_gva_topology,
)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _fixture_command(codec: str, output: Path, *, width: int, height: int) -> list[str]:
    common = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        f"testsrc=size={width}x{height}:rate=1",
        "-frames:v",
        "1",
        "-pix_fmt",
        "yuv420p",
        "-preset",
        "ultrafast",
    ]
    if codec == "h264":
        return common + [
            "-c:v",
            "libx264",
            "-tune",
            "zerolatency",
            "-x264-params",
            "keyint=1:min-keyint=1:scenecut=0",
            "-f",
            "h264",
            "-y",
            str(output),
        ]
    _require(codec == "h265", "engineering fixture codec must be h264 or h265")
    return common + [
        "-c:v",
        "libx265",
        "-x265-params",
        "keyint=1:min-keyint=1:scenecut=0:log-level=error",
        "-f",
        "hevc",
        "-y",
        str(output),
    ]


def _generate_fixture(codec: str, root: Path, *, width: int, height: int) -> Path:
    suffix = ".264" if codec == "h264" else ".265"
    output = root / f"synthetic-{codec}{suffix}"
    completed = subprocess.run(
        _fixture_command(codec, output, width=width, height=height),
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=60,
    )
    _require(
        completed.returncode == 0,
        f"ffmpeg {codec} fixture generation failed: {completed.stderr.strip()}",
    )
    _require(output.is_file() and output.stat().st_size > 0,
             f"ffmpeg {codec} fixture is empty")
    return output


def run_smoke(
    *,
    adapter: Path,
    width: int = 32,
    height: int = 32,
    stream_count: int = 6,
    cases: Sequence[tuple[str, str]] | None = None,
) -> dict[str, Any]:
    _require(os.name == "posix", "OpenVINO GVA container smoke requires Linux")
    _require(width > 0 and width % 2 == 0 and height > 0 and height % 2 == 0,
             "engineering smoke dimensions must be positive and even")
    adapter_path = adapter.resolve()
    _require(adapter_path.is_file(), "OpenVINO GVA adapter is missing")
    root = Path(tempfile.mkdtemp(prefix="vast-openvino-gva-smoke-", dir="/tmp"))
    _require(1 <= stream_count <= 6, "engineering smoke stream_count must be in 1..6")
    selected_cases = tuple(cases or (
        ("h264", INDEPENDENT_PROCESSES),
        ("h265", SHARED_VIDEO_DAG),
    ))
    results: list[dict[str, Any]] = []
    for codec, topology in selected_cases:
        source = _generate_fixture(codec, root, width=width, height=height)
        preprocess_sha = hashlib.sha256(
            f"engineering-dlstreamer-bgr-uint8-{width}x{height}-nhwc-v1".encode(
                "ascii"
            )
        ).hexdigest()
        result = run_openvino_gva_topology(
            bridge=EngineeringSyntheticBridge(),
            topology_kind=topology,
            codec=codec,
            source_path=source,
            preprocessing_contract_sha256=preprocess_sha,
            work_root=root / f"{codec}-{topology}",
            adapter_path=adapter_path,
            python_executable=os.environ.get("VAST_PYTHON_EXECUTABLE", "/usr/bin/python3"),
            stream_count=stream_count,
            width=width,
            height=height,
            timeout_s=120.0,
            require_full_publication_topology=(stream_count == 6),
        )
        results.append(result)
    return {
        "schema_version": 1,
        "artifact_kind": "vast_openvino_gva_pinned_image_engineering_smoke",
        "claim_status": ENGINEERING_CLAIM_STATUS,
        "case_count": len(results),
        "cases": results,
        "publication_ready": False,
        "accepted_evidence_written": False,
        "publication_blockers": list(ENGINEERING_BLOCKERS),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adapter", type=Path, required=True)
    parser.add_argument("--width", type=int, default=32)
    parser.add_argument("--height", type=int, default=32)
    args = parser.parse_args(argv)
    result = run_smoke(adapter=args.adapter, width=args.width, height=args.height)
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["run_smoke"]
