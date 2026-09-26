#!/usr/bin/env python3
"""Build and cold-validate the qualification executor's exact Python closure."""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import os
import stat
import sys
from pathlib import Path
from typing import Any, Mapping
from typing import Sequence

from publication_physical_io_v1 import (
    PhysicalRootCustodyV1,
    PublicationPhysicalIoV1Error,
)


SCHEMA_VERSION = 1
KIND = "vast_publication_policy_qualification_execution_code_closure_v1"
SEED_MODULES = (
    "publication_policy_qualification_pilot_executor_v2",
    "checkpoint_model_parity_acceptance_v4",
    "checkpoint_gstreamer_analytics_sidecar",
    "publication_guardian_preprocessing_contract_v1",
    "publication_guardian_runtime_expectations_v1",
    "checkpoint_qualification_pilot_acceptance_v1",
)
_MAX_SOURCE_BYTES = 16 * 1024 * 1024
_MAX_INTERPRETER_BYTES = 1024 * 1024 * 1024


class ExecutionCodeClosureV1Error(RuntimeError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ExecutionCodeClosureV1Error(message)


def _canonical_bytes(value: object) -> bytes:
    try:
        return (
            json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            )
            + "\n"
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeError) as error:
        raise ExecutionCodeClosureV1Error("execution code closure is not canonical JSON") from error


def semantic_sha256_v1(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value).rstrip(b"\n")).hexdigest()


def _snapshot(info: os.stat_result) -> dict[str, int]:
    return {
        "st_dev": int(info.st_dev),
        "st_ino": int(info.st_ino),
        "st_mode": int(info.st_mode),
        "st_nlink": int(info.st_nlink),
        "st_size": int(info.st_size),
        "st_mtime_ns": int(info.st_mtime_ns),
        "st_ctime_ns": int(info.st_ctime_ns),
        "st_file_attributes": int(getattr(info, "st_file_attributes", 0)),
    }


def _stable_leaf_identity(info: os.stat_result) -> tuple[int, ...]:
    """Identity fields stable across Windows' first-open ctime normalization."""

    return (
        int(info.st_dev),
        int(info.st_ino),
        int(info.st_nlink),
        int(info.st_size),
        int(info.st_mtime_ns),
        int(getattr(info, "st_file_attributes", 0)),
    )


def _is_link_or_reparse(info: os.stat_result) -> bool:
    reparse = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    return stat.S_ISLNK(info.st_mode) or bool(
        int(getattr(info, "st_file_attributes", 0)) & reparse
    )


def _canonical_root(project_root: Path | str) -> Path:
    lexical = Path(os.path.abspath(os.fspath(project_root)))
    try:
        info = lexical.lstat()
        resolved = lexical.resolve(strict=True)
    except OSError as error:
        raise ExecutionCodeClosureV1Error("project_root is unavailable") from error
    _require(
        lexical == resolved and stat.S_ISDIR(info.st_mode) and not _is_link_or_reparse(info),
        "project_root is not one canonical physical directory",
    )
    return lexical


def _relative(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError as error:
        raise ExecutionCodeClosureV1Error("execution source escaped project_root") from error


def _module_path(scripts_root: Path, module: str) -> Path | None:
    _require(
        bool(module) and all(part.isidentifier() for part in module.split(".")),
        f"invalid Python module name in execution closure: {module!r}",
    )
    leaf = scripts_root.joinpath(*module.split("."))
    source = leaf.with_suffix(".py")
    package = leaf / "__init__.py"
    if source.is_file():
        return source
    if package.is_file():
        return package
    return None


def _literal_dynamic_imports(tree: ast.AST) -> set[str]:
    result: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        first = node.args[0]
        if not isinstance(first, ast.Constant) or not isinstance(first.value, str):
            continue
        function = node.func
        if isinstance(function, ast.Name) and function.id == "__import__":
            result.add(first.value)
        elif (
            isinstance(function, ast.Attribute)
            and function.attr == "import_module"
            and isinstance(function.value, ast.Name)
            and function.value.id == "importlib"
        ):
            result.add(first.value)
    return result


def _imports(path: Path, module: str) -> set[str]:
    try:
        payload = path.read_bytes()
        tree = ast.parse(payload, filename=str(path))
    except (OSError, SyntaxError, ValueError) as error:
        raise ExecutionCodeClosureV1Error(f"cannot parse execution source {path}") from error
    found = _literal_dynamic_imports(tree)
    package = module.split(".")[:-1]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                keep = max(0, len(package) - node.level + 1)
                prefix = package[:keep]
            else:
                prefix = []
            if node.module:
                base = ".".join((*prefix, node.module))
                found.add(base)
                found.update(
                    f"{base}.{alias.name}"
                    for alias in node.names
                    if alias.name != "*"
                )
            elif prefix:
                found.update(".".join((*prefix, alias.name)) for alias in node.names)
    return found


def _discover_sources(root: Path) -> tuple[tuple[str, Path], ...]:
    scripts_root = root / "scripts"
    _require(scripts_root.is_dir(), "project scripts directory is unavailable")
    pending = list(SEED_MODULES)
    seen: set[str] = set()
    sources: dict[str, Path] = {}
    while pending:
        module = min(pending)
        pending.remove(module)
        if module in seen:
            continue
        seen.add(module)
        path = _module_path(scripts_root, module)
        _require(path is not None, f"execution closure seed is missing: {module}")
        sources[module] = path
        for imported in sorted(_imports(path, module)):
            parts = imported.split(".")
            for width in range(1, len(parts) + 1):
                candidate = ".".join(parts[:width])
                if (
                    candidate not in seen
                    and _module_path(scripts_root, candidate) is not None
                ):
                    pending.append(candidate)
    return tuple(sorted(sources.items(), key=lambda item: _relative(root, item[1])))


def _hash_external_regular(path: Path, *, maximum: int, label: str) -> dict[str, Any]:
    try:
        before = path.lstat()
        resolved = path.resolve(strict=True)
        _require(
            resolved == path
            and stat.S_ISREG(before.st_mode)
            and not _is_link_or_reparse(before)
            and int(before.st_nlink) == 1,
            f"{label} is not one canonical physical file",
        )
        _require(0 < int(before.st_size) <= maximum, f"{label} size is invalid")
        digest = hashlib.sha256()
        count = 0
        with path.open("rb", buffering=0) as stream:
            opened = os.fstat(stream.fileno())
            _require(
                _stable_leaf_identity(opened) == _stable_leaf_identity(before),
                f"{label} identity drifted",
            )
            while chunk := stream.read(1024 * 1024):
                count += len(chunk)
                _require(count <= maximum, f"{label} exceeded its size bound")
                digest.update(chunk)
            after = os.fstat(stream.fileno())
            named_after = path.lstat()
        _require(
            _stable_leaf_identity(after) == _stable_leaf_identity(opened)
            and _stable_leaf_identity(after) == _stable_leaf_identity(named_after),
            f"{label} physical snapshot drifted",
        )
    except ExecutionCodeClosureV1Error:
        raise
    except OSError as error:
        raise ExecutionCodeClosureV1Error(f"{label} cannot be read") from error
    return {
        "path": str(path),
        "size_bytes": count,
        "sha256": digest.hexdigest(),
        "snapshot": _snapshot(named_after),
    }


def _source_record(
    root: Path, custody: PhysicalRootCustodyV1, path: Path
) -> dict[str, Any]:
    relative = _relative(root, path)
    del custody  # The source leaf itself is held by the descriptor opened below.
    record = _hash_external_regular(
        path,
        maximum=_MAX_SOURCE_BYTES,
        label=f"execution source {relative}",
    )
    record["path"] = relative
    return record


def _receipt_body(root: Path, custody: PhysicalRootCustodyV1) -> dict[str, Any]:
    discovered = _discover_sources(root)
    sources = [_source_record(root, custody, path) for _module, path in discovered]
    rediscovered = _discover_sources(root)
    _require(
        tuple((module, _relative(root, path)) for module, path in rediscovered)
        == tuple((module, _relative(root, path)) for module, path in discovered),
        "execution code import closure changed while being discovered",
    )
    _require(
        [_source_record(root, custody, path) for _module, path in rediscovered]
        == sources,
        "execution code sources changed while being frozen",
    )
    interpreter = Path(os.path.abspath(sys.executable))
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": KIND,
        "status": "frozen",
        "seeds": list(SEED_MODULES),
        "project_sources": sources,
        "interpreter": _hash_external_regular(
            interpreter,
            maximum=_MAX_INTERPRETER_BYTES,
            label="Python interpreter",
        ),
        "scope": "qualification execution Python code only",
        "nonauthority": "This receipt does not authorize publication or acceptance.",
    }


def _windows_commit_or_adopt_exact(
    path: Path, payload: bytes
) -> tuple[dict[str, Any], tuple[int, int], str]:
    """Native-Windows fallback for the known lstat/fstat ctime normalization gap."""

    _require(os.name == "nt", "Windows publication fallback used off Windows")
    path.parent.mkdir(parents=True, exist_ok=True)
    disposition = "published"
    try:
        with path.open("xb", buffering=0) as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        path.chmod(stat.S_IREAD)
    except FileExistsError:
        disposition = "adopted"
    try:
        observed = path.read_bytes()
        info = path.lstat()
    except OSError as error:
        raise ExecutionCodeClosureV1Error("execution code closure receipt adoption failed") from error
    _require(observed == payload, "existing execution code closure receipt differs")
    descriptor = {
        "path": path.as_posix(),
        "size_bytes": len(observed),
        "sha256": hashlib.sha256(observed).hexdigest(),
    }
    return descriptor, (int(info.st_dev), int(info.st_ino)), disposition


def materialize_execution_code_closure_v1(
    *, project_root: Path | str, receipt_path: Path | str
) -> dict[str, Any]:
    root = _canonical_root(project_root)
    receipt = Path(receipt_path)
    if not receipt.is_absolute():
        receipt = root / receipt
    relative = _relative(root, Path(os.path.abspath(receipt)))
    custody = PhysicalRootCustodyV1.open(root, label="execution code closure build root")
    try:
        body = _receipt_body(root, custody)
        document = {**body, "receipt_sha256": semantic_sha256_v1(body)}
        payload = _canonical_bytes(document)
        try:
            descriptor, identity, disposition = custody.commit_or_adopt_exact_identity(
                relative,
                payload,
                label="execution code closure receipt",
                mode=0o444,
            )
        except (PublicationPhysicalIoV1Error, AttributeError):
            if os.name != "nt":
                raise
            descriptor, identity, disposition = _windows_commit_or_adopt_exact(
                receipt, payload
            )
    except PublicationPhysicalIoV1Error as error:
        raise ExecutionCodeClosureV1Error("execution code closure publication failed") from error
    finally:
        custody.close()
    return {
        "receipt": document,
        "receipt_descriptor": descriptor,
        "receipt_identity": list(identity),
        "disposition": disposition,
    }


def _validate_shape(receipt: Any) -> Mapping[str, Any]:
    _require(type(receipt) is dict, "execution code closure receipt is not an object")
    expected = {
        "schema_version",
        "kind",
        "status",
        "seeds",
        "project_sources",
        "interpreter",
        "scope",
        "nonauthority",
        "receipt_sha256",
    }
    _require(set(receipt) == expected, "execution code closure receipt fields are invalid")
    _require(receipt["schema_version"] == SCHEMA_VERSION and receipt["kind"] == KIND, "execution code closure schema is invalid")
    _require(receipt["status"] == "frozen", "execution code closure is not frozen")
    _require(receipt["seeds"] == list(SEED_MODULES), "execution code closure seeds drifted")
    supplied = receipt["receipt_sha256"]
    body = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    _require(type(supplied) is str and supplied == semantic_sha256_v1(body), "execution code closure self-hash is invalid")
    _require(type(receipt["project_sources"]) is list and bool(receipt["project_sources"]), "execution code closure has no sources")
    return receipt


def load_execution_code_closure_v1(
    *, project_root: Path | str, receipt_path: Path | str
) -> dict[str, Any]:
    root = _canonical_root(project_root)
    receipt = Path(receipt_path)
    if not receipt.is_absolute():
        receipt = root / receipt
    relative = _relative(root, Path(os.path.abspath(receipt)))
    custody = PhysicalRootCustodyV1.open(root, label="execution code closure validation root")
    try:
        try:
            descriptor, payload = custody.read_descriptor(
                relative,
                label="execution code closure receipt",
                maximum=16 * 1024 * 1024,
                capture=True,
            )
        except (PublicationPhysicalIoV1Error, AttributeError):
            if os.name != "nt":
                raise
            payload = receipt.read_bytes()
            descriptor = {
                "path": relative,
                "size_bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        _require(payload is not None, "execution code closure receipt is unreadable")
        try:
            receipt_value = json.loads(payload.decode("ascii"))
        except (UnicodeError, json.JSONDecodeError) as error:
            raise ExecutionCodeClosureV1Error("execution code closure receipt is invalid JSON") from error
        receipt_value = _validate_shape(receipt_value)
        _require(payload == _canonical_bytes(receipt_value), "execution code closure receipt is not canonical")
        observed = _receipt_body(root, custody)
        expected_body = {key: value for key, value in receipt_value.items() if key != "receipt_sha256"}
        _require(observed == expected_body, "execution code closure physical snapshot drifted")
    except PublicationPhysicalIoV1Error as error:
        raise ExecutionCodeClosureV1Error("execution code closure validation failed") from error
    finally:
        custody.close()
    return {"receipt": dict(receipt_value), "receipt_descriptor": descriptor}


def assert_loaded_project_modules_covered_v1(
    *, project_root: Path | str, receipt: Mapping[str, Any]
) -> None:
    root = _canonical_root(project_root)
    scripts_root = root / "scripts"
    covered = {str(item["path"]) for item in receipt["project_sources"]}
    escaped: list[str] = []
    for name, module in tuple(sys.modules.items()):
        raw = getattr(module, "__file__", None)
        if not raw:
            continue
        path = Path(os.path.abspath(os.fspath(raw)))
        if path.suffix in {".pyc", ".pyo"}:
            try:
                path = Path(importlib.util.source_from_cache(str(path)))
            except (ValueError, NotImplementedError):
                continue
        try:
            path.relative_to(scripts_root)
        except ValueError:
            continue
        relative = _relative(root, path)
        if relative not in covered:
            escaped.append(f"{name}={relative}")
    _require(
        not escaped,
        "loaded project module escaped execution code closure: " + ", ".join(sorted(escaped)),
    )


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--validate-only", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        result = (
            load_execution_code_closure_v1(
                project_root=args.project_root, receipt_path=args.receipt
            )
            if args.validate_only
            else materialize_execution_code_closure_v1(
                project_root=args.project_root, receipt_path=args.receipt
            )
        )
    except (OSError, ExecutionCodeClosureV1Error) as error:
        print(f"qualification execution code closure blocked: {error}", file=sys.stderr)
        return 78
    receipt = result["receipt"]
    print(
        json.dumps(
            {
                "status": "validated" if args.validate_only else result["disposition"],
                "receipt_path": str(Path(args.receipt)),
                "receipt_sha256": receipt["receipt_sha256"],
                "project_source_count": len(receipt["project_sources"]),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


__all__ = [
    "ExecutionCodeClosureV1Error",
    "KIND",
    "SCHEMA_VERSION",
    "SEED_MODULES",
    "assert_loaded_project_modules_covered_v1",
    "load_execution_code_closure_v1",
    "materialize_execution_code_closure_v1",
    "semantic_sha256_v1",
]


if __name__ == "__main__":
    raise SystemExit(main())
