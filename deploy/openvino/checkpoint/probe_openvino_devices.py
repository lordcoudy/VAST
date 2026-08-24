#!/usr/bin/env python3
"""Read-only OpenVINO/GStreamer inventory executed inside the candidate image."""

from __future__ import annotations

import json
import subprocess
import sys
from typing import Any


REQUIRED_GSTREAMER_ELEMENTS = (
    "appsrc",
    "h264parse",
    "h265parse",
    "decodebin",
    "videoconvert",
    "tee",
    "vastanalyticsqueue",
    "gvadetect",
    "vastanalyticsterminal",
)


def _property(core: Any, device_id: str, *names: str) -> str:
    for name in names:
        try:
            value = core.get_property(device_id, name)
        except Exception:
            continue
        if value not in (None, ""):
            return str(value)
    return ""


def _load_openvino() -> tuple[Any, str]:
    try:
        import openvino as ov

        core_type = ov.Core
        version = str(getattr(ov, "__version__", ""))
    except (ImportError, AttributeError):
        from openvino.runtime import Core as core_type

        try:
            from openvino import __version__ as version
        except ImportError:
            version = ""
    return core_type(), str(version)


def _gst_element(element: str) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            ["gst-inspect-1.0", element],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=15,
        )
        available = completed.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        available = False
    return {"available": available, "factory": element}


def probe() -> dict[str, Any]:
    core, version = _load_openvino()
    devices = []
    for device_id in sorted(str(value) for value in core.available_devices):
        devices.append(
            {
                "device_id": device_id,
                "full_device_name": _property(
                    core,
                    device_id,
                    "FULL_DEVICE_NAME",
                    "DEVICE_FULL_NAME",
                ),
                "device_type": _property(core, device_id, "DEVICE_TYPE"),
                "vendor": _property(
                    core,
                    device_id,
                    "DEVICE_VENDOR",
                    "VENDOR_NAME",
                ),
            }
        )
    return {
        "schema_version": 1,
        "artifact_kind": "vast_openvino_checkpoint_device_probe",
        "openvino_version": version,
        "available_devices": devices,
        "gstreamer_elements": {
            element: _gst_element(element)
            for element in REQUIRED_GSTREAMER_ELEMENTS
        },
    }


def main() -> int:
    try:
        payload = probe()
    except Exception as error:
        payload = {
            "schema_version": 1,
            "artifact_kind": "vast_openvino_checkpoint_device_probe_error",
            "error_type": type(error).__name__,
            "message": str(error),
        }
        print(json.dumps(payload, sort_keys=True))
        return 2
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
