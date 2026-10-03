#!/usr/bin/env python3
"""Durable no-replace publication/adoption for immutable project directories."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from publication_physical_io_v1 import (
    PhysicalRootCustodyV1,
    PublicationPhysicalIoV1Error,
)


JOURNAL_ROOT = ".publication-directory-journal-v1"
JOURNAL_KIND = "vast_publication_immutable_directory_intent_v1"


class PublicationImmutableDirectoryV1Error(RuntimeError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise PublicationImmutableDirectoryV1Error(message)


def _canonical(value: Any) -> bytes:
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


def _is_link(info: os.stat_result) -> bool:
    reparse = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    return stat.S_ISLNK(info.st_mode) or bool(
        int(getattr(info, "st_file_attributes", 0)) & reparse
    )


def _tree(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    _require(path.is_dir() and not path.is_symlink(), "immutable directory is unsafe")
    logical: list[dict[str, Any]] = []
    physical: list[dict[str, Any]] = []
    entries = [path, *sorted(path.rglob("*"), key=lambda item: item.relative_to(path).as_posix())]
    for entry in entries:
        info = entry.lstat()
        _require(not _is_link(info), "immutable directory contains a link/reparse point")
        relative = "." if entry == path else entry.relative_to(path).as_posix()
        if stat.S_ISDIR(info.st_mode):
            kind = "directory"
            item: dict[str, Any] = {
                "path": relative,
                "kind": kind,
                "mode": stat.S_IMODE(info.st_mode),
            }
        else:
            _require(
                stat.S_ISREG(info.st_mode) and int(info.st_nlink) == 1,
                "immutable directory contains a non-regular or aliased file",
            )
            payload = entry.read_bytes()
            after = entry.lstat()
            _require(_snapshot(after) == _snapshot(info), "immutable directory file changed while hashing")
            item = {
                "path": relative,
                "kind": "file",
                "mode": stat.S_IMODE(info.st_mode),
                "size_bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        logical.append(item)
        physical.append({**item, "snapshot": _snapshot(info)})
    return logical, physical


def _fsync_tree(path: Path) -> None:
    files = sorted(item for item in path.rglob("*") if item.is_file())
    directories = sorted(
        (item for item in path.rglob("*") if item.is_dir()),
        key=lambda item: len(item.parts),
        reverse=True,
    )
    for item in files:
        descriptor = os.open(item, os.O_RDONLY | int(getattr(os, "O_CLOEXEC", 0)))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    for item in [*directories, path]:
        descriptor = os.open(
            item,
            os.O_RDONLY
            | int(getattr(os, "O_DIRECTORY", 0))
            | int(getattr(os, "O_CLOEXEC", 0)),
        )
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _physical_matches_anchor(
    observed: list[dict[str, Any]], anchored: list[dict[str, Any]], *, published: bool
) -> bool:
    if len(observed) != len(anchored):
        return False
    for current, expected in zip(observed, anchored, strict=True):
        if {key: value for key, value in current.items() if key != "snapshot"} != {
            key: value for key, value in expected.items() if key != "snapshot"
        }:
            return False
        current_snapshot = current["snapshot"]
        expected_snapshot = expected["snapshot"]
        if published and current["path"] == ".":
            stable = ("st_dev", "st_ino", "st_mode", "st_nlink", "st_file_attributes")
            if any(current_snapshot[key] != expected_snapshot[key] for key in stable):
                return False
        elif current_snapshot != expected_snapshot:
            return False
    return True


def _strict_descendant(root: Path, value: Path, *, label: str) -> tuple[Path, str]:
    lexical = Path(os.path.abspath(os.fspath(value)))
    try:
        relative = lexical.relative_to(root).as_posix()
    except ValueError as error:
        raise PublicationImmutableDirectoryV1Error(f"{label} escaped project root") from error
    _require(relative and relative != "." and ".." not in PurePosixPath(relative).parts, f"{label} is invalid")
    return lexical, relative


def commit_or_adopt_immutable_directory_v1(
    *,
    project_root: Path | str,
    staging: Path | str,
    target: Path | str,
    after_publish_step: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Publish one durable tree, or adopt only its exact anchored physical tree."""

    root = Path(os.path.abspath(os.fspath(project_root))).resolve(strict=True)
    stage, stage_relative = _strict_descendant(root, Path(staging), label="staging directory")
    final, final_relative = _strict_descendant(root, Path(target), label="target directory")
    _require(stage.parent == final.parent and stage != final, "directory publish paths are not siblings")
    supplied_logical, supplied_physical = _tree(stage)
    if after_publish_step is not None:
        after_publish_step("mid_write")
    _fsync_tree(stage)
    key = hashlib.sha256(final_relative.encode("utf-8")).hexdigest()
    intent_relative = f"{JOURNAL_ROOT}/{key}.json"
    custody: PhysicalRootCustodyV1 | None = None
    try:
        custody = PhysicalRootCustodyV1.open(root, label="immutable directory project root")
        intent_path = root.joinpath(*PurePosixPath(intent_relative).parts)
        if os.path.lexists(intent_path):
            _descriptor, payload = custody.read_descriptor(
                intent_relative,
                label="immutable directory intent",
                maximum=64 * 1024 * 1024,
                capture=True,
            )
            assert payload is not None
            try:
                intent = json.loads(payload.decode("ascii"))
            except (UnicodeError, json.JSONDecodeError) as error:
                raise PublicationImmutableDirectoryV1Error("immutable directory intent is invalid") from error
            _require(payload == _canonical(intent), "immutable directory intent is noncanonical")
            intent_core = {
                key: value for key, value in intent.items() if key != "intent_sha256"
            }
            _require(
                type(intent) is dict
                and intent.get("schema_version") == 1
                and intent.get("artifact_kind") == JOURNAL_KIND
                and intent.get("target") == final_relative
                and intent.get("logical_tree") == supplied_logical,
                "immutable directory intent is foreign or drifted",
            )
            _require(
                intent.get("intent_sha256")
                == hashlib.sha256(_canonical(intent_core)).hexdigest(),
                "immutable directory intent self-hash drifted",
            )
            anchored_stage = root.joinpath(*PurePosixPath(str(intent.get("staging"))).parts)
            anchored_physical = intent.get("physical_tree")
            _require(type(anchored_physical) is list, "immutable directory physical intent drifted")
            if os.path.lexists(final):
                observed_logical, observed_physical = _tree(final)
                _require(
                    observed_logical == supplied_logical
                    and _physical_matches_anchor(observed_physical, anchored_physical, published=True),
                    "published immutable directory is foreign, tampered, rebound, or ABA-restored",
                )
                _fsync_tree(final)
                parent_fd = os.open(final.parent, os.O_RDONLY | int(getattr(os, "O_DIRECTORY", 0)))
                try:
                    os.fsync(parent_fd)
                finally:
                    os.close(parent_fd)
                return {"disposition": "adopted", "target": final_relative, "staging": stage_relative}
            _require(os.path.lexists(anchored_stage), "immutable directory writer is orphaned")
            anchored_logical, observed_physical = _tree(anchored_stage)
            _require(
                anchored_logical == supplied_logical
                and _physical_matches_anchor(observed_physical, anchored_physical, published=False),
                "anchored immutable directory staging changed",
            )
            publish_source = anchored_stage
        else:
            _require(not os.path.lexists(final), "foreign immutable directory target exists without intent")
            intent_core = {
                "schema_version": 1,
                "artifact_kind": JOURNAL_KIND,
                "target": final_relative,
                "staging": stage_relative,
                "logical_tree": supplied_logical,
                "physical_tree": supplied_physical,
            }
            intent = {
                **intent_core,
                "intent_sha256": hashlib.sha256(_canonical(intent_core)).hexdigest(),
            }
            custody.commit_or_adopt_exact_identity(
                intent_relative,
                _canonical(intent),
                label="immutable directory intent",
                mode=0o444,
                create_parents=True,
            )
            publish_source = stage
        if after_publish_step is not None:
            after_publish_step("post_fsync_pre_publish")
        from publication_policy_qualification_pilot_executor_v2 import (
            _rename_directory_noreplace,
        )

        _rename_directory_noreplace(publish_source, final)
        if after_publish_step is not None:
            after_publish_step("post_publish_pre_parent_fsync")
        _fsync_tree(final)
        parent_fd = os.open(final.parent, os.O_RDONLY | int(getattr(os, "O_DIRECTORY", 0)))
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
        observed_logical, observed_physical = _tree(final)
        _require(
            observed_logical == supplied_logical
            and _physical_matches_anchor(observed_physical, intent["physical_tree"], published=True),
            "published immutable directory identity drifted",
        )
        return {"disposition": "published", "target": final_relative, "staging": stage_relative}
    except PublicationPhysicalIoV1Error as error:
        raise PublicationImmutableDirectoryV1Error(
            "immutable directory physical custody failed"
        ) from error
    finally:
        if custody is not None:
            custody.close()


__all__ = [
    "PublicationImmutableDirectoryV1Error",
    "commit_or_adopt_immutable_directory_v1",
]
