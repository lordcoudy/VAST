#!/usr/bin/env python3
"""Read-only Savant/DeepStream/NVDEC engineering capability probe.

The probe decodes exactly one buffer for each frozen codec.  It never launches
a benchmark arm and never writes or claims accepted benchmark sidecars.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


IMAGE = "ghcr.io/insight-platform/savant-deepstream:0.5.17-7.0"
IMAGE_ID = (
    "sha256:3c0ef6f4bb57e385644da526789626f0c943dcb90ff32b72a7883e05798ce9e6"
)
IMAGE_REPO_DIGEST = (
    "ghcr.io/insight-platform/savant-deepstream@"
    "sha256:3c0ef6f4bb57e385644da526789626f0c943dcb90ff32b72a7883e05798ce9e6"
)
SAVANT_VERSION = "0.5.17"
SAVANT_ENTRYPOINT = ["python", "-m", "savant.entrypoint"]
CLAIM_STATUS = "engineering_capability_probe_not_measurement"
REQUIRED_ELEMENTS = (
    "appsrc", "h264parse", "h265parse", "nvv4l2decoder", "nvstreammux",
    "nvvideoconvert", "nvinfer", "tee", "queue", "appsink",
    "fakesink",
)
SOURCE_BY_CODEC = {
    "h264": Path("/opt/vast/kpp/h264/1.mp4"),
    "h265": Path("/opt/vast/kpp/h265/1.mp4"),
}
PARSER_BY_CODEC = {"h264": "h264parse", "h265": "h265parse"}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ProbeInvariantError(RuntimeError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ProbeInvariantError(message)


def _run(
    command: list[str], *, timeout_s: float = 30.0,
) -> subprocess.CompletedProcess[str]:
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
    filename, version = "", ""
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


def _deepstream_version() -> str:
    completed = _run(["deepstream-app", "--version-all"])
    if completed.returncode != 0:
        return ""
    match = re.search(r"DeepStreamSDK\s+([0-9]+(?:\.[0-9]+){2})", completed.stdout)
    return match.group(1) if match else ""


def _gpu() -> dict[str, Any]:
    completed = _run([
        "nvidia-smi",
        "--query-gpu=name,uuid,driver_version",
        "--format=csv,noheader",
    ])
    if completed.returncode != 0 or not completed.stdout.strip():
        return {
            "name": "", "uuid": "", "driver_version": "", "visible": False,
        }
    values = [
        value.strip()
        for value in completed.stdout.splitlines()[0].split(",", maxsplit=2)
    ]
    return {
        "name": values[0],
        "uuid": values[1] if len(values) > 1 else "",
        "driver_version": values[2] if len(values) > 2 else "",
        "visible": True,
    }


def _savant_identity() -> tuple[str, str]:
    entrypoint_spec = importlib.util.find_spec("savant.entrypoint")
    _require(entrypoint_spec is not None, "savant.entrypoint is not importable")
    import savant  # imported only after the explicit capability check

    version = importlib.metadata.version("savant")
    path = str(Path(savant.__file__ or "").resolve())
    _require(version == SAVANT_VERSION, "Savant Python package version drifted")
    _require(path.endswith("/savant/__init__.py"), "Savant import path drifted")
    return version, path


def _decoder_probe(codec: str, source_sha256: str) -> dict[str, Any]:
    import gi

    gi.require_version("Gst", "1.0")
    from gi.repository import GLib, Gst

    Gst.init(None)
    parser = PARSER_BY_CODEC[codec]
    pipeline = None
    decoded_buffers = 0
    output_caps = ""
    pipeline_status = "error"
    buffer_evidence = "no_decoded_sample"
    try:
        pipeline = Gst.parse_launch(
            f"filesrc location={SOURCE_BY_CODEC[codec]} ! qtdemux ! "
            f"{parser} ! nvv4l2decoder gpu-id=0 ! "
            "appsink name=vast_buffer_probe sync=false max-buffers=1 drop=true"
        )
        sink = pipeline.get_by_name("vast_buffer_probe")
        _require(sink is not None, f"{codec} appsink was not constructed")
        state_change = pipeline.set_state(Gst.State.PLAYING)
        if state_change == Gst.StateChangeReturn.FAILURE:
            pipeline_status = "error"
        else:
            sample = sink.emit("try-pull-sample", 30 * Gst.SECOND)
            if sample is not None and sample.get_buffer() is not None:
                decoded_buffers = 1
                caps = sample.get_caps()
                output_caps = caps.to_string() if caps is not None else ""
                buffer_evidence = "appsink_sample"
                if (
                    "video/x-raw(memory:NVMM)" in output_caps
                    and "gpu-id=(int)0" in output_caps
                ):
                    pipeline_status = "sample_observed"
                else:
                    pipeline_status = "sample_wrong_caps"
            else:
                bus = pipeline.get_bus()
                message = bus.timed_pop_filtered(
                    0, Gst.MessageType.ERROR | Gst.MessageType.EOS
                )
                if message is not None and message.type == Gst.MessageType.ERROR:
                    pipeline_status = "error"
                elif message is not None and message.type == Gst.MessageType.EOS:
                    pipeline_status = "eos_without_buffer"
                else:
                    pipeline_status = "timeout_without_buffer"
    except (ProbeInvariantError, GLib.Error, RuntimeError, ValueError, TypeError):
        pipeline_status = "error"
    finally:
        if pipeline is not None:
            pipeline.set_state(Gst.State.NULL)
    passed = decoded_buffers == 1 and pipeline_status == "sample_observed"
    return {
        "passed": passed,
        "decoder_factory": "nvv4l2decoder",
        "parser_factory": parser,
        "gpu_id": 0,
        "decoded_buffers": decoded_buffers,
        "source_sha256": source_sha256,
        "pipeline_status": pipeline_status,
        "output_caps": output_caps,
        "buffer_evidence": buffer_evidence,
    }


def build_payload() -> dict[str, Any]:
    _require(os.environ.get("VAST_SAVANT_IMAGE") == IMAGE, "image tag drifted")
    _require(os.environ.get("VAST_SAVANT_IMAGE_ID") == IMAGE_ID, "image ID drifted")
    _require(
        os.environ.get("VAST_SAVANT_IMAGE_REPO_DIGEST") == IMAGE_REPO_DIGEST,
        "image repo digest drifted",
    )
    source_hashes = {}
    for codec, path in SOURCE_BY_CODEC.items():
        _require(path.is_file(), f"{codec} source missing")
        actual = _sha256_file(path)
        expected = os.environ.get(
            f"VAST_{codec.upper()}_SOURCE_SHA256", ""
        ).lower()
        _require(bool(_SHA256_RE.fullmatch(expected)), f"{codec} hash invalid")
        _require(actual == expected, f"{codec} source hash mismatch")
        source_hashes[codec] = actual
    savant_version, savant_path = _savant_identity()
    return {
        "schema_version": 1,
        "artifact_kind": "savant_checkpoint_capability_probe",
        "claim_status": CLAIM_STATUS,
        "system": "savant",
        "image": IMAGE,
        "image_id": IMAGE_ID,
        "image_repo_digest": IMAGE_REPO_DIGEST,
        "savant_version": savant_version,
        "savant_import_path": savant_path,
        "savant_entrypoint": SAVANT_ENTRYPOINT,
        "deepstream_sdk_version": _deepstream_version(),
        "gpu": _gpu(),
        "required_elements": {
            name: _inspect_element(name) for name in REQUIRED_ELEMENTS
        },
        "decoder_probes": {
            codec: _decoder_probe(codec, source_hashes[codec])
            for codec in ("h264", "h265")
        },
        "dedicated_checkpoint_runtime_present": Path(
            "/usr/local/bin/vast_savant_checkpoint_runtime"
        ).is_file(),
        "protocol_v3_policy_adapter_present": Path(
            "/usr/local/lib/vast/savant/libvastsavantpolicyadapter.so"
        ).is_file(),
        "resource_v2_emitter_present": Path(
            "/usr/local/bin/vast_savant_resource_v2_emitter"
        ).is_file(),
        "generic_probe_executed": False,
        "accepted_measurement_evidence_emitted": False,
        "publication_ready": False,
    }


def main() -> int:
    try:
        payload = build_payload()
    except (ProbeInvariantError, importlib.metadata.PackageNotFoundError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
