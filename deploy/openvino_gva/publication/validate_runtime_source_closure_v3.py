#!/usr/bin/env python3
"""Validate the exact transitive source closure of the OpenVINO ABI-v3 image."""

from __future__ import annotations

import argparse
import ast
import re
from pathlib import Path, PurePosixPath
from typing import Iterable, Sequence


ENTRY_MODULE = "checkpoint_openvino_gva_container_coordinator_v3"
MANIFEST_RELATIVE_PATH = "deploy/openvino_gva/publication/runtime-source-allowlist.txt"
FIXED_BUILD_SOURCES = {
    "deploy/openvino_gva/publication/Dockerfile",
    "deploy/openvino_gva/publication/vast_openvino_gva_publication_runtime_v3",
}
_PYTHON_PATH = re.compile(r"scripts/[a-z][a-z0-9_]*\.py")
_NATIVE_PATH = re.compile(r"deploy/native_gst_probe/[a-z][a-z0-9_]*\.(?:cpp|hpp)")
_LOCAL_INCLUDE = re.compile(r'^\s*#include\s+"([^"]+)"', re.MULTILINE)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _canonical_relative_path(value: str) -> str:
    _require(bool(value) and value == value.strip(), "source path is empty or padded")
    path = PurePosixPath(value)
    _require(
        not path.is_absolute()
        and path.as_posix() == value
        and all(part not in {"", ".", ".."} for part in path.parts),
        f"source path is not canonical and relative: {value}",
    )
    return value


def _physical_file(root: Path, relative: str) -> Path:
    path = root.joinpath(*PurePosixPath(relative).parts)
    _require(path.is_file() and not path.is_symlink(), f"runtime source is unsafe: {relative}")
    try:
        path.resolve(strict=True).relative_to(root.resolve(strict=True))
    except ValueError as error:
        raise ValueError(f"runtime source escapes project root: {relative}") from error
    return path


def _python_modules(root: Path) -> dict[str, Path]:
    scripts = root / "scripts"
    _require(scripts.is_dir() and not scripts.is_symlink(), "scripts directory is unsafe")
    modules: dict[str, Path] = {}
    for path in scripts.glob("*.py"):
        if path.is_file() and not path.is_symlink():
            _require(path.stem not in modules, f"duplicate local module: {path.stem}")
            modules[path.stem] = path
    return modules


def _imports(path: Path) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, UnicodeError, SyntaxError) as error:
        raise ValueError(f"cannot parse runtime Python source: {path}") from error
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            _require(node.level == 0, f"relative runtime import is forbidden: {path}")
            if node.module:
                imports.add(node.module.split(".", 1)[0])
    return imports


def validate_python_source_closure(
    *, project_root: Path, declared_paths: Iterable[str], entry_module: str,
) -> tuple[str, ...]:
    root = project_root.resolve(strict=True)
    declared = tuple(_canonical_relative_path(value) for value in declared_paths)
    _require(len(declared) == len(set(declared)), "duplicate Python source declaration")
    _require(all(_PYTHON_PATH.fullmatch(value) for value in declared), "Python source path drifted")
    for value in declared:
        _physical_file(root, value)
    modules = _python_modules(root)
    _require(entry_module in modules, f"runtime entry module is absent: {entry_module}")
    reachable: set[str] = set()
    pending = [entry_module]
    while pending:
        module = pending.pop()
        if module in reachable:
            continue
        reachable.add(module)
        pending.extend(
            dependency
            for dependency in sorted(_imports(modules[module]))
            if dependency in modules and dependency not in reachable
        )
    expected = {f"scripts/{module}.py" for module in reachable}
    missing = sorted(expected - set(declared))
    extra = sorted(set(declared) - expected)
    _require(not missing, "missing reachable Python source: " + ", ".join(missing))
    _require(not extra, "extraneous Python source: " + ", ".join(extra))
    return tuple(sorted(expected))


def validate_native_source_closure(
    *,
    project_root: Path,
    declared_paths: Iterable[str],
    entry_source: str = "deploy/native_gst_probe/vast_native_gst_probe.cpp",
) -> tuple[str, ...]:
    root = project_root.resolve(strict=True)
    declared = tuple(_canonical_relative_path(value) for value in declared_paths)
    _require(len(declared) == len(set(declared)), "duplicate native source declaration")
    _require(all(_NATIVE_PATH.fullmatch(value) for value in declared), "native source path drifted")
    for value in declared:
        _physical_file(root, value)
    native_root = root / "deploy" / "native_gst_probe"
    available = {
        path.name: path
        for pattern in ("*.cpp", "*.hpp")
        for path in native_root.glob(pattern)
        if path.is_file() and not path.is_symlink()
    }
    entry = PurePosixPath(entry_source).name
    _require(entry in available, f"native entry source is absent: {entry_source}")
    reachable: set[str] = set()
    pending = [entry]
    while pending:
        name = pending.pop()
        if name in reachable:
            continue
        reachable.add(name)
        text = available[name].read_text(encoding="utf-8")
        for include in _LOCAL_INCLUDE.findall(text):
            _require("/" not in include and "\\" not in include, "native include path drifted")
            if include in available and include not in reachable:
                pending.append(include)
    expected = {f"deploy/native_gst_probe/{name}" for name in reachable}
    missing = sorted(expected - set(declared))
    extra = sorted(set(declared) - expected)
    _require(not missing, "missing reachable native source: " + ", ".join(missing))
    _require(not extra, "extraneous native source: " + ", ".join(extra))
    return tuple(sorted(expected))


def validate_runtime_source_closure(
    *, project_root: Path, manifest_path: Path,
) -> dict[str, object]:
    root = project_root.resolve(strict=True)
    manifest = manifest_path.resolve(strict=True)
    try:
        relative = manifest.relative_to(root).as_posix()
    except ValueError as error:
        raise ValueError("runtime source allowlist escapes project root") from error
    _require(
        relative == MANIFEST_RELATIVE_PATH
        and manifest.is_file()
        and not manifest.is_symlink(),
        "runtime source allowlist path/type drifted",
    )
    raw = manifest.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeError as error:
        raise ValueError("runtime source allowlist is not UTF-8") from error
    _require(raw and raw.endswith(b"\n") and b"\r" not in raw, "allowlist must be LF-terminated")
    declared = tuple(text.splitlines())
    _require(declared == tuple(sorted(set(declared))), "allowlist must be unique and sorted")
    _require(MANIFEST_RELATIVE_PATH not in declared, "allowlist must not reference itself")
    for value in declared:
        _canonical_relative_path(value)
        _physical_file(root, value)
    python = tuple(value for value in declared if _PYTHON_PATH.fullmatch(value))
    native = tuple(value for value in declared if _NATIVE_PATH.fullmatch(value))
    fixed = set(declared) - set(python) - set(native)
    _require(fixed == FIXED_BUILD_SOURCES, "fixed build source set drifted")
    python_sources = validate_python_source_closure(
        project_root=root, declared_paths=python, entry_module=ENTRY_MODULE,
    )
    native_sources = validate_native_source_closure(
        project_root=root, declared_paths=native,
    )
    return {
        "entry_module": ENTRY_MODULE,
        "python_sources": python_sources,
        "native_sources": native_sources,
        "all_sources": declared,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args(argv)
    validate_runtime_source_closure(
        project_root=args.project_root, manifest_path=args.manifest,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
