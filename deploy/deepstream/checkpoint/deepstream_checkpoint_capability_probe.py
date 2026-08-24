#!/usr/bin/env python3
"""One-buffer DeepStream SDK/NVDEC engineering probe.

The output is capability metadata only. It never writes benchmark sidecars and
can never claim publication readiness.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any


CLAIM_STATUS = "engineering_capability_probe_not_measurement"
REQUIRED_ELEMENTS = (
    "appsrc",
    "h264parse",
    "h265parse",
    "nvv4l2decoder",
    "nvstreammux",
    "nvvideoconvert",
    "capsfilter",
    "tee",
    "queue",
    "appsink",
)
SOURCE_BY_CODEC = {
    "h264": Path("/opt/vast/kpp/h264/1.mp4"),
    "h265": Path("/opt/vast/kpp/h265/1.mp4"),
}
PARSER_BY_CODEC = {"h264": "h264parse", "h265": "h265parse"}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_IMAGE_ID_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class ProbeInvariantError(RuntimeError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ProbeInvariantError(message)


def _run(command: list[str], *, timeout_s: float = 30.0) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            env={**os.environ, "GST_DEBUG_NO_COLOR": "1"},
        )
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(
            args=command,
            returncode=124,
            stdout=str(exc.stdout or ""),
            stderr=str(exc.stderr or ""),
        )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _inspect_element(name: str) -> dict[str, Any]:
    completed = _run(["gst-inspect-1.0", name])
    filename = ""
    version = ""
    if completed.returncode == 0:
        for line in completed.stdout.splitlines():
            stripped = line.strip()
            if stripped.startswith("Filename"):
                filename = stripped.removeprefix("Filename").strip()
            elif stripped.startswith("Version"):
                version = stripped.removeprefix("Version").strip()
    return {
        "available": completed.returncode == 0,
        "plugin_filename": filename,
        "plugin_version": version,
    }


def _sdk_version() -> str:
    completed = _run(["deepstream-app", "--version-all"])
    if completed.returncode != 0:
        return ""
    match = re.search(r"DeepStreamSDK\s+([0-9]+(?:\.[0-9]+){2})", completed.stdout)
    return match.group(1) if match else ""


def _gpu() -> dict[str, Any]:
    completed = _run([
        "nvidia-smi",
        "--query-gpu=name,driver_version",
        "--format=csv,noheader",
    ])
    if completed.returncode != 0 or not completed.stdout.strip():
        return {"name": "", "driver_version": "", "visible": False}
    first = completed.stdout.splitlines()[0]
    parts = [value.strip() for value in first.split(",", maxsplit=1)]
    return {
        "name": parts[0],
        "driver_version": parts[1] if len(parts) == 2 else "",
        "visible": True,
    }


def _decoder_probe(codec: str, source_sha256: str) -> dict[str, Any]:
    parser = PARSER_BY_CODEC[codec]
    source = SOURCE_BY_CODEC[codec]
    command = [
        "gst-launch-1.0",
        "-q",
        "filesrc",
        f"location={source}",
        "!",
        "qtdemux",
        "!",
        parser,
        "!",
        "nvv4l2decoder",
        "gpu-id=0",
        "!",
        "identity",
        "eos-after=1",
        "!",
        "fakesink",
        "sync=false",
    ]
    completed = _run(command, timeout_s=30.0)
    passed = completed.returncode == 0
    return {
        "passed": passed,
        "decoder_factory": "nvv4l2decoder",
        "parser_factory": parser,
        "gpu_id": 0,
        "decoded_buffers": 1 if passed else 0,
        "source_sha256": source_sha256,
        "command_exit_code": int(completed.returncode),
    }


def build_payload() -> dict[str, Any]:
    image = os.environ.get("VAST_DEEPSTREAM_IMAGE", "")
    image_id = os.environ.get("VAST_DEEPSTREAM_IMAGE_ID", "")
    _require(image == "nvcr.io/nvidia/deepstream:7.0-triton-multiarch", "image identity drifted")
    _require(bool(_IMAGE_ID_RE.fullmatch(image_id)), "image ID is missing or invalid")
    source_hashes: dict[str, str] = {}
    for codec, path in SOURCE_BY_CODEC.items():
        _require(path.is_file(), f"{codec} source is missing")
        actual = _sha256_file(path)
        expected = os.environ.get(f"VAST_{codec.upper()}_SOURCE_SHA256", "").lower()
        _require(bool(_SHA256_RE.fullmatch(expected)), f"{codec} expected SHA-256 is invalid")
        _require(actual == expected, f"{codec} source SHA-256 mismatch")
        source_hashes[codec] = actual
    return {
        "schema_version": 1,
        "artifact_kind": "deepstream_checkpoint_capability_probe",
        "claim_status": CLAIM_STATUS,
        "system": "deepstream",
        "image": image,
        "image_id": image_id,
        "deepstream_sdk_version": _sdk_version(),
        "gpu": _gpu(),
        "sdk_headers_present": Path(
            "/opt/nvidia/deepstream/deepstream/sources/includes/nvdsmeta.h"
        ).is_file(),
        "python_gi_present": importlib.util.find_spec("gi") is not None,
        "pyds_present": importlib.util.find_spec("pyds") is not None,
        "required_elements": {
            name: _inspect_element(name) for name in REQUIRED_ELEMENTS
        },
        "decoder_probes": {
            codec: _decoder_probe(codec, source_hashes[codec])
            for codec in ("h264", "h265")
        },
        "accepted_measurement_evidence_emitted": False,
        "publication_ready": False,
    }


def main() -> int:
    try:
        payload = build_payload()
    except ProbeInvariantError as exc:
        print(str(exc), file=os.sys.stderr)
        return 2
    print(json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
