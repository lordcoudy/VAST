#!/usr/bin/env python3
"""Validate the exact source closure copied into the GStreamer ABI-v3 image."""

from __future__ import annotations

import argparse
import ast
import re
from pathlib import Path, PurePosixPath
from typing import Iterable, Sequence


ENTRY_MODULE = "checkpoint_gstreamer_custom_container_coordinator_v3"
MANIFEST_RELATIVE_PATH = (
    "deploy/gstreamer_custom/publication/runtime-source-allowlist.txt"
)
FIXED_BUILD_SOURCES = {
    "deploy/gstreamer_custom/publication/Dockerfile",
    MANIFEST_RELATIVE_PATH,
    "deploy/gstreamer_custom/publication/vast_gstreamer_custom_publication_runtime_v3",
}
_PYTHON_PATH = re.compile(r"scripts/[a-z][a-z0-9_]*\.py")
_NATIVE_PATH = re.compile(
    r"deploy/native_gst_probe/[a-z][a-z0-9_]*\.(?:cpp|hpp)"
)
_LOCAL_INCLUDE = re.compile(r'^\s*#include\s+"([^"]+)"', re.MULTILINE)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _canonical_relative_path(value: str) -> str:
    _require(bool(value) and value == value.strip(), "source path is empty or padded")
    path = PurePosixPath(value)
    _require(
        not path.is_absolute()
        and str(path) == value
        and all(part not in {"", ".", ".."} for part in path.parts),
        f"source path is not canonical and relative: {value}",
    )
    return value


def _require_regular_source(project_root: Path, relative_path: str) -> Path:
    source = project_root / relative_path
    _require(
        source.is_file() and not source.is_symlink(),
        f"runtime source must be a physical regular file: {relative_path}",
    )
    try:
        source.resolve(strict=True).relative_to(project_root.resolve(strict=True))
    except ValueError as exc:
        raise ValueError(
            f"runtime source escapes project root: {relative_path}"
        ) from exc
    return source


def _local_python_modules(project_root: Path) -> dict[str, Path]:
    scripts = project_root / "scripts"
    _require(scripts.is_dir() and not scripts.is_symlink(), "scripts directory is invalid")
    modules: dict[str, Path] = {}
    for source in scripts.glob("*.py"):
        if source.is_symlink() or not source.is_file():
            continue
        _require(source.stem not in modules, f"duplicate local Python module: {source.stem}")
        modules[source.stem] = source
    return modules


def _python_imports(source: Path) -> set[str]:
    try:
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    except (OSError, UnicodeError, SyntaxError) as exc:
        raise ValueError(f"cannot parse runtime Python source: {source}") from exc
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            _require(node.level == 0, f"relative import is forbidden in runtime source: {source}")
            if node.module:
                imports.add(node.module.split(".", 1)[0])
    return imports


def validate_python_source_closure(
    *,
    project_root: Path,
    declared_paths: Iterable[str],
    entry_module: str,
) -> tuple[str, ...]:
    root = project_root.resolve(strict=True)
    declared = tuple(_canonical_relative_path(value) for value in declared_paths)
    _require(len(declared) == len(set(declared)), "duplicate Python source declaration")
    _require(
        all(_PYTHON_PATH.fullmatch(value) for value in declared),
        "Python source declaration is outside scripts/*.py",
    )
    for value in declared:
        _require_regular_source(root, value)

    modules = _local_python_modules(root)
    _require(entry_module in modules, f"runtime entry module is absent: {entry_module}")
    reachable: set[str] = set()
    pending = [entry_module]
    while pending:
        module = pending.pop()
        if module in reachable:
            continue
        source = modules[module]
        _require(
            source.is_file() and not source.is_symlink(),
            f"reachable Python source is not physical: {module}",
        )
        reachable.add(module)
        pending.extend(
            sorted(
                dependency
                for dependency in _python_imports(source)
                if dependency in modules and dependency not in reachable
            )
        )

    expected = {f"scripts/{module}.py" for module in reachable}
    observed = set(declared)
    missing = sorted(expected - observed)
    extra = sorted(observed - expected)
    _require(
        not missing,
        "missing reachable Python source: " + ", ".join(missing),
    )
    _require(
        not extra,
        "extraneous Python source: " + ", ".join(extra),
    )
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
    _require(
        all(_NATIVE_PATH.fullmatch(value) for value in declared),
        "native source declaration is outside deploy/native_gst_probe",
    )
    for value in declared:
        _require_regular_source(root, value)

    native_root = root / "deploy" / "native_gst_probe"
    available = {
        source.name: source
        for pattern in ("*.cpp", "*.hpp")
        for source in native_root.glob(pattern)
        if source.is_file() and not source.is_symlink()
    }
    entry_name = PurePosixPath(entry_source).name
    _require(entry_name in available, f"native entry source is absent: {entry_source}")
    reachable: set[str] = set()
    pending = [entry_name]
    while pending:
        name = pending.pop()
        if name in reachable:
            continue
        reachable.add(name)
        try:
            text = available[name].read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise ValueError(f"cannot read native runtime source: {name}") from exc
        for include in _LOCAL_INCLUDE.findall(text):
            _require(
                "/" not in include and "\\" not in include,
                f"native local include is not flat/canonical: {include}",
            )
            if include in available and include not in reachable:
                pending.append(include)

    expected = {f"deploy/native_gst_probe/{name}" for name in reachable}
    observed = set(declared)
    missing = sorted(expected - observed)
    extra = sorted(observed - expected)
    _require(not missing, "missing reachable native source: " + ", ".join(missing))
    _require(not extra, "extraneous native source: " + ", ".join(extra))
    return tuple(sorted(expected))


def validate_runtime_source_closure(
    *,
    project_root: Path,
    manifest_path: Path,
) -> dict[str, object]:
    root = project_root.resolve(strict=True)
    manifest = manifest_path.resolve(strict=True)
    try:
        manifest_relative = manifest.relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError("runtime source allowlist escapes project root") from exc
    _require(
        manifest_relative == MANIFEST_RELATIVE_PATH
        and manifest.is_file()
        and not manifest.is_symlink(),
        "runtime source allowlist path/type drifted",
    )
    try:
        raw = manifest.read_bytes()
        text = raw.decode("utf-8")
    except (OSError, UnicodeError) as exc:
        raise ValueError("runtime source allowlist is not canonical UTF-8") from exc
    _require(raw and raw.endswith(b"\n") and b"\r" not in raw, "allowlist must be LF-terminated")
    declared = tuple(text.splitlines())
    _require(
        all(declared)
        and tuple(sorted(set(declared))) == declared,
        "runtime source allowlist must be non-empty, unique, and sorted",
    )
    for value in declared:
        _canonical_relative_path(value)
        _require_regular_source(root, value)

    python_declared = tuple(value for value in declared if _PYTHON_PATH.fullmatch(value))
    native_declared = tuple(value for value in declared if _NATIVE_PATH.fullmatch(value))
    fixed_declared = set(declared) - set(python_declared) - set(native_declared)
    _require(
        fixed_declared == FIXED_BUILD_SOURCES,
        "runtime source allowlist has missing/extraneous fixed build sources",
    )
    python_sources = validate_python_source_closure(
        project_root=root,
        declared_paths=python_declared,
        entry_module=ENTRY_MODULE,
    )
    native_sources = validate_native_source_closure(
        project_root=root,
        declared_paths=native_declared,
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
        project_root=args.project_root,
        manifest_path=args.manifest,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
