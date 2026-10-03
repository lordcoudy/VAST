#!/usr/bin/env python3
"""Hand refrozen native-probe identities to the four runtime builders."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import stat
import subprocess
from pathlib import Path
from typing import Any, Mapping, Sequence


ARTIFACT_KIND = "vast_publication_runtime_image_refreeze_handoff_plan_v1"
BUILD_REGISTRY = "configs/publication_image_build_v1.json"
REFREEZE_REGISTRY = "configs/publication_qualification_image_refreeze_v1.json"
SYSTEMS = ("deepstream", "savant", "openvino_gva", "gstreamer_custom")
_IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
_SHA = re.compile(r"^[0-9a-f]{64}$")


class RuntimeImageRefreezeHandoffV1Error(ValueError):
    """A native receipt or runtime builder handoff failed closed."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeImageRefreezeHandoffV1Error(message)


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")


def _module(filename: str, name: str):
    path = Path(__file__).resolve().with_name(filename)
    spec = importlib.util.spec_from_file_location(name, path)
    _require(spec is not None and spec.loader is not None, f"required module is unavailable: {filename}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _root(project_root: Path) -> Path:
    value = Path(project_root)
    _require(value.is_dir() and not value.is_symlink(), "project_root is unsafe")
    return value.resolve(strict=True)


def _physical_project_file(root: Path, path: Path) -> Path:
    value = Path(path)
    if not value.is_absolute():
        value = root / value
    try:
        before = value.lstat()
        resolved = value.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, RuntimeError, ValueError) as error:
        raise RuntimeImageRefreezeHandoffV1Error("handoff input is absent or escapes project_root") from error
    _require(
        stat.S_ISREG(before.st_mode)
        and not value.is_symlink()
        and int(before.st_nlink) == 1
        and resolved == value.absolute(),
        "handoff input must be one unaliased physical file",
    )
    return resolved


def _physical_artifact_directory(root: Path, path: Path) -> Path:
    value = Path(path)
    if not value.is_absolute():
        value = root / value
    try:
        before = value.lstat()
        resolved = value.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, RuntimeError, ValueError) as error:
        raise RuntimeImageRefreezeHandoffV1Error(
            "artifact_dir is absent or escapes project_root"
        ) from error
    _require(
        stat.S_ISDIR(before.st_mode)
        and not value.is_symlink()
        and resolved == value.absolute(),
        "artifact_dir must be one physical project directory",
    )
    return resolved


def _receipt_rows(
    *, root: Path, receipt: Path,
    build_registry_sha256: str,
) -> tuple[dict[str, dict[str, Any]], str]:
    physical = _physical_project_file(root, receipt)
    build = _module("publication_image_build_v1.py", "runtime_handoff_publication_image_build_v1")
    try:
        value = build.load_publication_image_freeze_receipt(physical)
    except (OSError, ValueError) as error:
        raise RuntimeImageRefreezeHandoffV1Error("native-probe freeze receipt is invalid") from error
    _require(
        value.get("group") == "native_probe"
        and value.get("registry_path") == BUILD_REGISTRY
        and value.get("registry_sha256") == build_registry_sha256,
        "native-probe freeze receipt registry/group drifted",
    )
    rows: dict[str, dict[str, Any]] = {}
    for row in value.get("images", []):
        _require(type(row) is dict and type(row.get("name")) is str, "native-probe receipt row is invalid")
        rows[row["name"]] = row
    _require(
        set(rows) == {
            "native_probe_deepstream", "native_probe_openvino",
            "native_probe_savant",
        },
        "native-probe freeze receipt coverage drifted",
    )
    return rows, value["receipt_sha256"]


def _override_rows(value: Mapping[str, Mapping[str, str]]) -> dict[str, dict[str, Any]]:
    _require(
        set(value) == {
            "native_probe_deepstream", "native_probe_openvino",
            "native_probe_savant",
        },
        "test producer override coverage drifted",
    )
    result: dict[str, dict[str, Any]] = {}
    for name, binding in value.items():
        _require(
            type(binding) is dict
            and set(binding) == {
                "image_id", "source_set_sha256", "base_image_id",
                "base_reference", "target_reference",
            }
            and _IMAGE_ID.fullmatch(str(binding["image_id"])) is not None
            and _IMAGE_ID.fullmatch(str(binding["base_image_id"])) is not None
            and _SHA.fullmatch(str(binding["source_set_sha256"])) is not None,
            f"test producer override is invalid: {name}",
        )
        result[name] = {"name": name, **binding}
    return result


def runtime_image_handoff_plan(
    *, project_root: Path, native_receipt: Path | None,
    artifact_dir: Path | None = None,
    producer_image_overrides: Mapping[str, Mapping[str, str]] | None = None,
) -> dict[str, Any]:
    root = _root(project_root)
    build = _module("publication_image_build_v1.py", "runtime_handoff_build_registry_v1")
    registry = build.load_publication_image_registry(
        project_root=root,
        registry_path=root / BUILD_REGISTRY,
    )
    refreeze = _module(
        "publication_qualification_image_refreeze_v1.py",
        "runtime_handoff_qualification_refreeze_v1",
    ).load_refreeze_registry(
        project_root=root,
        registry_path=root / REFREEZE_REGISTRY,
    )
    _require(
        registry["registry_sha256"] == refreeze["build_registry_sha256"],
        "build/refreeze registry identity drifted",
    )
    if native_receipt is not None:
        _require(producer_image_overrides is None, "physical receipt and producer overrides are mutually exclusive")
        _require(
            artifact_dir is not None,
            "explicit artifact_dir is required with a physical native receipt",
        )
        output_artifact_dir = _physical_artifact_directory(root, artifact_dir)
        rows, receipt_sha256 = _receipt_rows(
            root=root, receipt=native_receipt,
            build_registry_sha256=registry["registry_sha256"],
        )
    else:
        _require(producer_image_overrides is not None, "native-probe freeze receipt is required")
        rows = _override_rows(producer_image_overrides)
        receipt_sha256 = None
        output_artifact_dir = (
            _physical_artifact_directory(root, artifact_dir)
            if artifact_dir is not None
            else root / "artifacts" / "publication_image_build_v1"
        )

    system_rows = {row["system"]: row for row in refreeze["systems"]}
    deepstream = rows["native_probe_deepstream"]
    openvino = rows["native_probe_openvino"]
    savant = rows["native_probe_savant"]
    _require(
        _IMAGE_ID.fullmatch(str(deepstream.get("base_image_id", ""))) is not None
        and _IMAGE_ID.fullmatch(str(openvino.get("image_id", ""))) is not None
        and _IMAGE_ID.fullmatch(str(savant.get("image_id", ""))) is not None
        and _IMAGE_ID.fullmatch(str(savant.get("base_image_id", ""))) is not None
        and _SHA.fullmatch(str(savant.get("source_set_sha256", ""))) is not None,
        "refrozen native-probe identity is incomplete",
    )
    _require(
        deepstream.get("base_reference")
        == system_rows["deepstream"]["base"]["reference"]
        and savant.get("base_reference")
        == system_rows["savant"]["base"]["reference"]
        and openvino.get("target_reference", system_rows["openvino_gva"]["base"]["reference"])
        == system_rows["openvino_gva"]["base"]["reference"]
        and savant.get("target_reference", system_rows["savant"]["native_builder"]["reference"])
        == system_rows["savant"]["native_builder"]["reference"],
        "refrozen native-probe target reference drifted",
    )
    common_openvino_environment = {
        "VAST_OPENVINO_NATIVE_PROBE_IMAGE": system_rows["openvino_gva"]["base"]["reference"],
        "VAST_OPENVINO_NATIVE_PROBE_IMAGE_ID": openvino["image_id"],
    }
    rows_out = [
        {
            "system": "deepstream",
            "command": ["/usr/bin/bash", str(root / "scripts/build_deepstream_publication_runtime_v3.sh")],
            "environment": {
                "VAST_DEEPSTREAM_BASE_IMAGE_ID": deepstream["base_image_id"],
            },
        },
        {
            "system": "savant",
            "command": ["/usr/bin/bash", str(root / "scripts/build_savant_publication_runtime_v3.sh")],
            "environment": {
                "VAST_SAVANT_NATIVE_PROBE_IMAGE": system_rows["savant"]["native_builder"]["reference"],
                "VAST_SAVANT_NATIVE_PROBE_IMAGE_ID": savant["image_id"],
                "VAST_SAVANT_NATIVE_PROBE_SOURCE_SHA256": savant["source_set_sha256"],
                "VAST_SAVANT_BASE_IMAGE_ID": savant["base_image_id"],
                "VAST_SAVANT_RUNTIME_IMAGE_MANIFEST": str(
                    output_artifact_dir
                    / "savant.runtime_image.materialized.v3.json"
                ),
            },
        },
        {
            "system": "openvino_gva",
            "command": ["/usr/bin/bash", str(root / "scripts/build_openvino_gva_publication_runtime_v3.sh")],
            "environment": dict(common_openvino_environment),
        },
        {
            "system": "gstreamer_custom",
            "command": ["/usr/bin/bash", str(root / "scripts/build_gstreamer_custom_publication_runtime_v3.sh")],
            "environment": dict(common_openvino_environment),
        },
    ]
    return {
        "schema_version": 1,
        "artifact_kind": ARTIFACT_KIND,
        "build_registry_sha256": registry["registry_sha256"],
        "refreeze_registry_sha256": refreeze["registry_sha256"],
        "native_probe_receipt_sha256": receipt_sha256,
        "artifact_dir": output_artifact_dir.relative_to(root).as_posix(),
        "runtime_builds": rows_out,
    }


def build_runtime_images_after_refreeze(
    *, project_root: Path, native_receipt: Path, artifact_dir: Path,
) -> dict[str, Any]:
    root = _root(project_root)
    plan = runtime_image_handoff_plan(
        project_root=root,
        native_receipt=native_receipt,
        artifact_dir=artifact_dir,
    )
    environment = dict(os.environ)
    for row in plan["runtime_builds"]:
        command = row["command"]
        _require(
            command[0] == "/usr/bin/bash"
            and _physical_project_file(root, Path(command[1])).is_file(),
            f"runtime builder is unsafe: {row['system']}",
        )
        invocation_environment = dict(environment)
        invocation_environment.update(row["environment"])
        try:
            completed = subprocess.run(
                command,
                cwd=root,
                env=invocation_environment,
                stdin=subprocess.DEVNULL,
                check=False,
            )
        except OSError as error:
            raise RuntimeImageRefreezeHandoffV1Error(
                f"runtime builder is unavailable: {row['system']}",
            ) from error
        _require(completed.returncode == 0, f"runtime builder failed: {row['system']}")
    return plan


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build four runtimes from a physical native-probe freeze receipt")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("plan", "build"):
        child = commands.add_parser(name)
        child.add_argument("--project-root", type=Path, required=True)
        child.add_argument("--native-receipt", type=Path, required=True)
        child.add_argument("--artifact-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "plan":
            result = runtime_image_handoff_plan(
                project_root=args.project_root,
                native_receipt=args.native_receipt,
                artifact_dir=args.artifact_dir,
            )
        else:
            result = build_runtime_images_after_refreeze(
                project_root=args.project_root,
                native_receipt=args.native_receipt,
                artifact_dir=args.artifact_dir,
            )
    except (OSError, ValueError) as error:
        print(str(error), file=os.sys.stderr)
        return 2
    print(_canonical(result).decode("ascii"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "RuntimeImageRefreezeHandoffV1Error",
    "build_runtime_images_after_refreeze",
    "runtime_image_handoff_plan",
]
