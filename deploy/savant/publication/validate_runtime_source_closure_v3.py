#!/usr/bin/env python3
"""Validate the exact source closure copied into the Savant ABI-v3 image."""

from __future__ import annotations

import argparse
import ast
import re
from pathlib import Path, PurePosixPath
from typing import Iterable, Sequence


ENTRY_MODULES = (
    "checkpoint_savant_container_runtime_v3",
    "checkpoint_savant_sdk_runtime_v3",
)
MANIFEST_RELATIVE_PATH = (
    "deploy/savant/publication/runtime-source-allowlist.txt"
)
DEPENDENCY_MANIFEST_RELATIVE_PATH = (
    "deploy/deepstream/checkpoint/runtime-dependency-allowlist.txt"
)
BUILD_ONLY_SOURCES = {
    "deploy/savant/publication/Dockerfile",
    "deploy/savant/publication/validate_runtime_source_closure_v3.py",
    "scripts/build_savant_publication_runtime_v3.sh",
    "scripts/materialize_runtime_build_context_v3.py",
}
RUNTIME_FIXED_COPY_SOURCES = {
    DEPENDENCY_MANIFEST_RELATIVE_PATH,
    MANIFEST_RELATIVE_PATH,
    "deploy/savant/publication/vast_savant_checkpoint_runtime",
}
NATIVE_ENTRY_SOURCE = (
    "deploy/native_gst_probe/checkpoint_source_coordinator.cpp"
)
_PYTHON_PATH = re.compile(r"scripts/[a-z][a-z0-9_]*\.py")
_NATIVE_PATH = re.compile(
    r"deploy/native_gst_probe/[a-z][a-z0-9_]*\.(?:cpp|hpp)"
)
_LOCAL_INCLUDE = re.compile(r'^\s*#include\s+"([^"]+)"', re.MULTILINE)
_MODULE_REFERENCE = re.compile(
    r"^([a-z][a-z0-9_]*):[A-Za-z_][A-Za-z0-9_]*$"
)


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
    except ValueError as error:
        raise ValueError(
            f"runtime source escapes project root: {relative_path}"
        ) from error
    return source


def _local_python_modules(project_root: Path) -> dict[str, Path]:
    scripts = project_root / "scripts"
    _require(
        scripts.is_dir() and not scripts.is_symlink(),
        "scripts directory is invalid",
    )
    modules: dict[str, Path] = {}
    for source in scripts.glob("*.py"):
        if source.is_symlink() or not source.is_file():
            continue
        _require(
            source.stem not in modules,
            f"duplicate local Python module: {source.stem}",
        )
        modules[source.stem] = source
    return modules


def _dynamic_import_name(node: ast.Call) -> str | None:
    is_import = isinstance(node.func, ast.Name) and node.func.id == "__import__"
    is_import_module = (
        isinstance(node.func, ast.Attribute)
        and node.func.attr == "import_module"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "importlib"
    )
    if not (is_import or is_import_module) or not node.args:
        return None
    first = node.args[0]
    if not isinstance(first, ast.Constant) or not isinstance(first.value, str):
        return None
    return first.value.split(".", 1)[0]


def _python_imports(source: Path) -> set[str]:
    try:
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    except (OSError, UnicodeError, SyntaxError) as error:
        raise ValueError(f"cannot parse runtime Python source: {source}") from error
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            _require(
                node.level == 0,
                f"relative import is forbidden in runtime source: {source}",
            )
            if node.module:
                imports.add(node.module.split(".", 1)[0])
        elif isinstance(node, ast.Call):
            dynamic = _dynamic_import_name(node)
            if dynamic is not None:
                imports.add(dynamic)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            reference = _MODULE_REFERENCE.fullmatch(node.value)
            if reference is not None:
                imports.add(reference.group(1))
    return imports


def validate_python_source_closure(
    *,
    project_root: Path,
    declared_paths: Iterable[str],
    entry_modules: Iterable[str],
) -> tuple[str, ...]:
    root = project_root.resolve(strict=True)
    declared = tuple(_canonical_relative_path(value) for value in declared_paths)
    entries = tuple(str(value) for value in entry_modules)
    _require(len(declared) == len(set(declared)), "duplicate Python source declaration")
    _require(
        bool(entries)
        and len(entries) == len(set(entries))
        and all(re.fullmatch(r"[a-z][a-z0-9_]*", value) for value in entries),
        "runtime Python entry-module declaration is invalid",
    )
    _require(
        all(_PYTHON_PATH.fullmatch(value) for value in declared),
        "Python source declaration is outside scripts/*.py",
    )
    for value in declared:
        _require_regular_source(root, value)

    modules = _local_python_modules(root)
    for entry_module in entries:
        _require(
            entry_module in modules,
            f"runtime entry module is absent: {entry_module}",
        )
    reachable: set[str] = set()
    pending = list(entries)
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
    entry_source: str = NATIVE_ENTRY_SOURCE,
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
        except (OSError, UnicodeError) as error:
            raise ValueError(f"cannot read native runtime source: {name}") from error
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


def validate_dependency_source_closure(
    *, project_root: Path, manifest_path: Path,
) -> tuple[str, ...]:
    root = project_root.resolve(strict=True)
    manifest = manifest_path.resolve(strict=True)
    try:
        relative = manifest.relative_to(root).as_posix()
    except ValueError as error:
        raise ValueError("runtime dependency allowlist escapes project root") from error
    _require(
        relative == DEPENDENCY_MANIFEST_RELATIVE_PATH
        and manifest.is_file()
        and not manifest.is_symlink(),
        "runtime dependency allowlist path/type drifted",
    )
    raw = manifest.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeError as error:
        raise ValueError("runtime dependency allowlist is not UTF-8") from error
    _require(
        raw and raw.endswith(b"\n") and b"\r" not in raw,
        "dependency allowlist must be LF-terminated",
    )
    declared = tuple(text.splitlines())
    _require(
        declared == tuple(sorted(set(declared))) and bool(declared),
        "dependency allowlist must be non-empty, unique, and sorted",
    )
    for value in declared:
        _canonical_relative_path(value)
        _require_regular_source(root, value)
    requirements = "deploy/deepstream/checkpoint/requirements.lock"
    wheel_prefix = "deploy/deepstream/checkpoint/wheels/"
    _require(
        declared.count(requirements) == 1
        and all(
            value == requirements
            or (
                value.startswith(wheel_prefix)
                and PurePosixPath(value).name == value.removeprefix(wheel_prefix)
                and value.endswith(".whl")
            )
            for value in declared
        ),
        "runtime dependency declaration is outside the frozen bundle",
    )
    wheels = root / "deploy/deepstream/checkpoint/wheels"
    _require(wheels.is_dir() and not wheels.is_symlink(), "wheel directory is invalid")
    children = tuple(wheels.iterdir())
    observed = {
        path.relative_to(root).as_posix()
        for path in children if path.is_file() and not path.is_symlink()
    }
    declared_wheels = {value for value in declared if value.startswith(wheel_prefix)}
    _require(
        observed == declared_wheels
        and all(
            path.is_file() and not path.is_symlink() and path.suffix == ".whl"
            for path in children
        ),
        "runtime wheel dependency set drifted",
    )
    return declared


def validate_runtime_source_closure(
    *,
    project_root: Path,
    manifest_path: Path,
) -> dict[str, object]:
    root = project_root.resolve(strict=True)
    manifest = manifest_path.resolve(strict=True)
    try:
        manifest_relative = manifest.relative_to(root).as_posix()
    except ValueError as error:
        raise ValueError("runtime source allowlist escapes project root") from error
    _require(
        manifest_relative == MANIFEST_RELATIVE_PATH
        and manifest.is_file()
        and not manifest.is_symlink(),
        "runtime source allowlist path/type drifted",
    )
    try:
        raw = manifest.read_bytes()
        text = raw.decode("utf-8")
    except (OSError, UnicodeError) as error:
        raise ValueError("runtime source allowlist is not canonical UTF-8") from error
    _require(
        bool(raw) and raw.endswith(b"\n") and b"\r" not in raw,
        "allowlist must be LF-terminated",
    )
    declared = tuple(text.splitlines())
    _require(
        all(declared) and tuple(sorted(set(declared))) == declared,
        "runtime source allowlist must be non-empty, unique, and sorted",
    )
    for value in declared:
        _canonical_relative_path(value)
        _require_regular_source(root, value)

    build_only = set(declared).intersection(BUILD_ONLY_SOURCES)
    runtime_fixed = set(declared).intersection(RUNTIME_FIXED_COPY_SOURCES)
    classified_fixed = build_only | runtime_fixed
    python_declared = tuple(
        value for value in declared
        if value not in classified_fixed and _PYTHON_PATH.fullmatch(value)
    )
    native_declared = tuple(
        value for value in declared if _NATIVE_PATH.fullmatch(value)
    )
    classified = classified_fixed | set(python_declared) | set(native_declared)
    _require(
        build_only == BUILD_ONLY_SOURCES
        and runtime_fixed == RUNTIME_FIXED_COPY_SOURCES
        and classified == set(declared),
        "runtime source allowlist has missing/extraneous fixed build sources",
    )
    python_sources = validate_python_source_closure(
        project_root=root,
        declared_paths=python_declared,
        entry_modules=ENTRY_MODULES,
    )
    native_sources = validate_native_source_closure(
        project_root=root,
        declared_paths=native_declared,
    )
    dependency_sources = validate_dependency_source_closure(
        project_root=root,
        manifest_path=root / DEPENDENCY_MANIFEST_RELATIVE_PATH,
    )
    docker_copy_sources = tuple(sorted(
        set(python_sources) | set(native_sources) | RUNTIME_FIXED_COPY_SOURCES
    ))
    return {
        "entry_modules": ENTRY_MODULES,
        "python_sources": python_sources,
        "native_sources": native_sources,
        "build_only_sources": tuple(sorted(BUILD_ONLY_SOURCES)),
        "docker_copy_sources": docker_copy_sources,
        "dependency_sources": dependency_sources,
        "all_sources": declared,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    arguments = parser.parse_args(argv)
    validate_runtime_source_closure(
        project_root=arguments.project_root,
        manifest_path=arguments.manifest,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
