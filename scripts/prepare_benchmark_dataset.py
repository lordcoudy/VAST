#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

import yaml
from benchmark_contract import ContractError, load_dataset, sha256_file
from kpp_legacy_iss_v2_manifest import (
    KppLegacyIssV2ManifestError,
    validate_kpp_legacy_iss_v2_manifest_entry,
)
from kpp_iss_publication_v3_dataset import (
    KppIssPublicationV3DatasetError,
    validate_kpp_iss_publication_v3_manifest_entry,
)


class DatasetPrepError(RuntimeError):
    pass


@dataclass(frozen=True)
class SourceSpec:
    source_rel: Path
    pattern: str
    fps: int = 30


@dataclass(frozen=True)
class ClipPlan:
    project_root: Path
    rel_path: Path
    target: Path
    source_dir: Path
    pattern: str
    expected_sha256: str
    fps: int = 30

    @property
    def input_pattern(self) -> Path:
        return self.source_dir / self.pattern


@dataclass(frozen=True)
class VideoTranscodePlan:
    project_root: Path
    rel_path: Path
    target: Path
    source_file: Path
    expected_sha256: str
    source_expected_sha256: str
    ffmpeg_filter: str
    encoder: str
    preset: str
    crf: int
    pix_fmt: str


PreparationPlan = ClipPlan | VideoTranscodePlan


PUBLIC_CLIP_SOURCES: dict[str, SourceSpec] = {
    "mot17_02.mp4": SourceSpec(Path("MOT17/train/MOT17-02-FRCNN/img1"), "%06d.jpg"),
    "mot17_04.mp4": SourceSpec(Path("MOT17/train/MOT17-04-FRCNN/img1"), "%06d.jpg"),
    "mot17_09.mp4": SourceSpec(Path("MOT17/train/MOT17-09-FRCNN/img1"), "%06d.jpg"),
    "uadetrac_mvi_20011.mp4": SourceSpec(Path("DETRAC-Images/MVI_20011"), "img%05d.jpg"),
    "uadetrac_mvi_40152.mp4": SourceSpec(Path("DETRAC-Images/MVI_40152"), "img%05d.jpg"),
    "uadetrac_mvi_40714.mp4": SourceSpec(Path("DETRAC-Images/MVI_40714"), "img%05d.jpg"),
}

Runner = Callable[[Sequence[str]], subprocess.CompletedProcess]


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PUBLIC_OUTPUT_REL = Path("data/benchmark")
VIDEO_SOURCE_REL = Path("data/videos")
KPP_SOURCE_REL = Path("data/videos/kpp")
CONFIG_REL = Path("configs")
KPP_CODECS = frozenset({"h264", "h265"})
_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


def _lexical_absolute(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _same_location(left: Path, right: Path) -> bool:
    return os.path.normcase(os.fspath(_lexical_absolute(left))) == os.path.normcase(
        os.fspath(_lexical_absolute(right))
    )


def _is_link_or_reparse(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(os.path, "isjunction", lambda _path: False)
    if bool(is_junction(path)):
        return True
    try:
        attributes = int(getattr(path.lstat(), "st_file_attributes", 0))
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise DatasetPrepError(f"cannot inspect path safety for {path}: {exc}") from exc
    return bool(attributes & _REPARSE_POINT)


def _has_parent_reference(path: Path) -> bool:
    return ".." in path.parts


def _require_plain_path_chain(path: Path, *, stop: Path, label: str) -> None:
    lexical = _lexical_absolute(path)
    boundary = _lexical_absolute(stop)
    try:
        relative = lexical.relative_to(boundary)
    except ValueError as exc:
        raise DatasetPrepError(f"{label} escapes the project root") from exc

    current = boundary
    paths = [current]
    for part in relative.parts:
        current = current / part
        paths.append(current)
    for index, current in enumerate(paths):
        if _is_link_or_reparse(current):
            raise DatasetPrepError(
                f"{label} contains a symlink, junction, or reparse point: {current}"
            )
        if not os.path.lexists(current):
            continue
        try:
            observed = current.lstat()
        except OSError as exc:
            raise DatasetPrepError(f"cannot inspect {label}: {current}: {exc}") from exc
        if index < len(paths) - 1 and not stat.S_ISDIR(observed.st_mode):
            raise DatasetPrepError(f"{label} has a non-directory parent: {current}")

    resolved = lexical.resolve(strict=False)
    if not _same_location(resolved, lexical):
        raise DatasetPrepError(f"{label} contains a filesystem alias: {lexical}")


def _validated_project_root(project_root: Path) -> Path:
    raw = Path(project_root)
    if not raw.is_absolute() or _has_parent_reference(raw):
        raise DatasetPrepError("project root must be an absolute canonical path")
    root = _lexical_absolute(raw)
    if _is_link_or_reparse(root) or not root.is_dir():
        raise DatasetPrepError("project root is missing or is a symlink, junction, or reparse point")
    if not _same_location(root.resolve(strict=True), root):
        raise DatasetPrepError("project root must not be a filesystem alias")
    return root


def _project_candidate(project_root: Path, value: Path, *, label: str) -> Path:
    raw = Path(value)
    if _has_parent_reference(raw):
        raise DatasetPrepError(f"{label} contains parent traversal")
    if raw.drive and not raw.is_absolute():
        raise DatasetPrepError(f"{label} is a drive-relative path")
    candidate = raw if raw.is_absolute() else project_root / raw
    return _lexical_absolute(candidate)


def _guard_exact_project_location(
    project_root: Path,
    value: Path,
    *,
    expected_rel: Path,
    label: str,
) -> Path:
    candidate = _project_candidate(project_root, value, label=label)
    expected = _lexical_absolute(project_root / expected_rel)
    if not _same_location(candidate, expected):
        raise DatasetPrepError(
            f"{label} must be exactly project_root/{expected_rel.as_posix()}"
        )
    _require_plain_path_chain(candidate, stop=project_root, label=label)
    return candidate


def _guard_manifest(project_root: Path, manifest: Path) -> Path:
    candidate = _project_candidate(project_root, manifest, label="dataset manifest")
    config_root = _lexical_absolute(project_root / CONFIG_REL)
    try:
        relative = candidate.relative_to(config_root)
    except ValueError as exc:
        raise DatasetPrepError("dataset manifest must be inside project_root/configs") from exc
    if not relative.parts:
        raise DatasetPrepError("dataset manifest must name a file below project_root/configs")
    _require_plain_path_chain(candidate, stop=project_root, label="dataset manifest")
    if _is_link_or_reparse(candidate):
        raise DatasetPrepError("dataset manifest must not be a symlink, junction, or reparse point")
    try:
        observed = candidate.lstat()
    except FileNotFoundError as exc:
        raise DatasetPrepError(f"dataset manifest is missing: {candidate}") from exc
    except OSError as exc:
        raise DatasetPrepError(f"cannot inspect dataset manifest: {candidate}: {exc}") from exc
    if not stat.S_ISREG(observed.st_mode):
        raise DatasetPrepError(f"dataset manifest is not a regular file: {candidate}")
    return candidate


def _relative_contract_path(value: object, *, label: str) -> Path:
    raw = str(value).strip()
    if not raw or "\\" in raw:
        raise DatasetPrepError(f"{label} is not a valid relative POSIX path")
    relative = Path(raw)
    if relative.is_absolute() or relative.drive:
        raise DatasetPrepError(f"{label} must be relative to project root")
    if _has_parent_reference(relative):
        raise DatasetPrepError(f"{label} contains parent traversal")
    if any(":" in part for part in relative.parts):
        raise DatasetPrepError(f"{label} is not a portable project-relative path")
    return relative


def _guard_contract_location(
    project_root: Path,
    relative: Path,
    *,
    namespace_rel: Path,
    label: str,
) -> Path:
    candidate = _lexical_absolute(project_root / relative)
    namespace = _lexical_absolute(project_root / namespace_rel)
    try:
        candidate.relative_to(namespace)
    except ValueError as exc:
        raise DatasetPrepError(
            f"{label} must stay below project_root/{namespace_rel.as_posix()}"
        ) from exc
    _require_plain_path_chain(candidate, stop=project_root, label=label)
    return candidate


def _public_target_rel(relative: Path, *, target_name: str) -> Path:
    expected = PUBLIC_OUTPUT_REL / target_name
    if relative != expected:
        raise DatasetPrepError(
            f"public target must be exactly {expected.as_posix()}, got {relative.as_posix()}"
        )
    return relative


def _kpp_source_rel(relative: Path, *, label: str) -> Path:
    parts = relative.parts
    if (
        len(parts) != 4
        or parts[:3] != KPP_SOURCE_REL.parts
        or relative.suffix.lower() != ".avi"
    ):
        raise DatasetPrepError(
            f"{label} must be a direct AVI child of {KPP_SOURCE_REL.as_posix()}"
        )
    return relative


def _kpp_target_rel(relative: Path) -> Path:
    parts = relative.parts
    if (
        len(parts) != 5
        or parts[:3] != KPP_SOURCE_REL.parts
        or parts[3] not in KPP_CODECS
        or relative.suffix.lower() != ".mp4"
    ):
        raise DatasetPrepError(
            "transcode target must be a direct MP4 child of data/videos/kpp/h264 "
            "or data/videos/kpp/h265"
        )
    return relative


def _read_manifest_dataset(manifest: Path, dataset_name: str) -> dict:
    with manifest.open("r", encoding="utf-8") as src:
        config = yaml.safe_load(src) or {}
    datasets = config.get("datasets", {})
    if dataset_name not in datasets:
        raise DatasetPrepError(f"unknown dataset '{dataset_name}' in {manifest}")
    dataset = datasets[dataset_name] or {}
    streams = list(dataset.get("streams") or [])
    if not streams:
        raise DatasetPrepError(f"dataset '{dataset_name}' has no streams")
    return dataset


def _is_check_only_materialized_v2(
    dataset_name: str,
    dataset: dict,
    *,
    project_root: Path,
) -> bool:
    try:
        if validate_kpp_legacy_iss_v2_manifest_entry(
            dataset_name,
            dataset,
            project_root=project_root,
            require_files=False,
        ):
            return True
        return validate_kpp_iss_publication_v3_manifest_entry(
            dataset_name,
            dataset,
            project_root=project_root,
            require_files=False,
        )
    except (KppLegacyIssV2ManifestError, KppIssPublicationV3DatasetError) as exc:
        raise DatasetPrepError(str(exc)) from exc


def _build_video_transcode_plans(
    *,
    manifest: Path,
    dataset_name: str,
    dataset: dict,
    project_root: Path,
) -> list[VideoTranscodePlan]:
    source_dataset_name = str(dataset.get("source_dataset", "")).strip()
    if not source_dataset_name:
        raise DatasetPrepError(
            f"real codec dataset '{dataset_name}' does not declare source_dataset"
        )
    source_dataset = _read_manifest_dataset(manifest, source_dataset_name)
    source_by_path: dict[str, str] = {}
    for raw_source in list(source_dataset.get("streams") or []):
        source_path = _kpp_source_rel(
            _relative_contract_path(
                (raw_source or {}).get("path", ""),
                label=f"source dataset '{source_dataset_name}' stream",
            ),
            label=f"source dataset '{source_dataset_name}' stream",
        )
        _guard_contract_location(
            project_root,
            source_path,
            namespace_rel=KPP_SOURCE_REL,
            label=f"source dataset '{source_dataset_name}' stream",
        )
        source_sha256 = str((raw_source or {}).get("sha256", "")).strip()
        if not source_sha256 or source_sha256.startswith("SET_"):
            raise DatasetPrepError(
                f"source dataset '{source_dataset_name}' has an incomplete stream contract"
            )
        key = source_path.as_posix()
        previous = source_by_path.setdefault(key, source_sha256)
        if previous != source_sha256:
            raise DatasetPrepError(
                f"source dataset '{source_dataset_name}' has checksum drift for {source_path}"
            )

    transcode = dict(dataset.get("transcode") or {})
    source_paths: set[str] = set()
    for value in list(transcode.get("source_paths") or []):
        source_rel = _kpp_source_rel(
            _relative_contract_path(
                value,
                label=f"dataset '{dataset_name}' transcode source",
            ),
            label=f"dataset '{dataset_name}' transcode source",
        )
        _guard_contract_location(
            project_root,
            source_rel,
            namespace_rel=KPP_SOURCE_REL,
            label=f"dataset '{dataset_name}' transcode source",
        )
        source_paths.add(source_rel.as_posix())
    ffmpeg_filter = str(transcode.get("ffmpeg_filter", "")).strip()
    encoder = str(transcode.get("encoder", "")).strip()
    preset = str(transcode.get("preset", "")).strip()
    pix_fmt = str(transcode.get("pix_fmt", "")).strip()
    if not source_paths or not ffmpeg_filter or not encoder or not preset or not pix_fmt:
        raise DatasetPrepError(
            f"real codec dataset '{dataset_name}' has an incomplete transcode contract"
        )
    try:
        crf = int(transcode["crf"])
    except (KeyError, TypeError, ValueError) as exc:
        raise DatasetPrepError(
            f"real codec dataset '{dataset_name}' has an invalid transcode crf"
        ) from exc
    if crf < 0:
        raise DatasetPrepError(
            f"real codec dataset '{dataset_name}' has a negative transcode crf"
        )

    plans_by_target: dict[str, VideoTranscodePlan] = {}
    used_source_paths: set[str] = set()
    for raw_stream in list(dataset.get("streams") or []):
        stream = dict(raw_stream or {})
        rel_path_value = str(stream.get("path", "")).strip()
        source_path_value = str(stream.get("source_path", "")).strip()
        if not rel_path_value or not source_path_value:
            raise DatasetPrepError(
                f"real codec dataset '{dataset_name}' has a stream without path/source_path"
            )
        rel_path = _kpp_target_rel(
            _relative_contract_path(rel_path_value, label="transcode target")
        )
        source_rel = _kpp_source_rel(
            _relative_contract_path(source_path_value, label="transcode source"),
            label="transcode source",
        )
        target = _guard_contract_location(
            project_root,
            rel_path,
            namespace_rel=KPP_SOURCE_REL,
            label="transcode target",
        )
        source_file = _guard_contract_location(
            project_root,
            source_rel,
            namespace_rel=KPP_SOURCE_REL,
            label="transcode source",
        )
        expected_sha256 = str(stream.get("sha256", "")).strip()
        if not expected_sha256 or expected_sha256.startswith("SET_"):
            raise DatasetPrepError(
                f"dataset stream {rel_path} does not have a real sha256 in {manifest}"
            )
        source_key = source_rel.as_posix()
        if source_key not in source_paths:
            raise DatasetPrepError(
                f"stream {rel_path} uses source outside transcode.source_paths: {source_rel}"
            )
        source_expected_sha256 = source_by_path.get(source_key)
        if source_expected_sha256 is None:
            raise DatasetPrepError(
                f"stream {rel_path} source is absent from {source_dataset_name}: {source_rel}"
            )
        used_source_paths.add(source_key)
        plan = VideoTranscodePlan(
            project_root=project_root,
            rel_path=rel_path,
            target=target,
            source_file=source_file,
            expected_sha256=expected_sha256,
            source_expected_sha256=source_expected_sha256,
            ffmpeg_filter=ffmpeg_filter,
            encoder=encoder,
            preset=preset,
            crf=crf,
            pix_fmt=pix_fmt,
        )
        target_key = rel_path.as_posix()
        previous = plans_by_target.setdefault(target_key, plan)
        if previous != plan:
            raise DatasetPrepError(
                f"logical replicas disagree on transcode contract for {rel_path}"
            )

    if used_source_paths != source_paths:
        raise DatasetPrepError(
            f"dataset '{dataset_name}' transcode.source_paths differs from resolved stream sources"
        )

    expected_unique_sources = int(dataset.get("unique_recorded_sources", 0) or 0)
    if expected_unique_sources and len(plans_by_target) != expected_unique_sources:
        raise DatasetPrepError(
            f"dataset '{dataset_name}' declares {expected_unique_sources} unique sources "
            f"but resolves {len(plans_by_target)} physical transcodes"
        )
    return list(plans_by_target.values())


def build_clip_plans(
    *,
    manifest: Path,
    dataset_name: str,
    project_root: Path,
    source_root: Path,
    output_dir: Path,
) -> list[PreparationPlan]:
    project_root = _validated_project_root(project_root)
    manifest = _guard_manifest(project_root, manifest)
    source_root = _guard_exact_project_location(
        project_root,
        source_root,
        expected_rel=VIDEO_SOURCE_REL,
        label="raw video source directory",
    )
    output_dir = _guard_exact_project_location(
        project_root,
        output_dir,
        expected_rel=PUBLIC_OUTPUT_REL,
        label="public output directory",
    )
    dataset = _read_manifest_dataset(manifest, dataset_name)
    if _is_check_only_materialized_v2(
        dataset_name,
        dataset,
        project_root=project_root,
    ):
        return []
    dataset_kind = str(dataset.get("kind", ""))
    if dataset_kind == "real_avi":
        return []
    if dataset_kind == "real_codec_transcode":
        return _build_video_transcode_plans(
            manifest=manifest,
            dataset_name=dataset_name,
            dataset=dataset,
            project_root=project_root,
        )

    plans: list[ClipPlan] = []
    for raw_stream in list(dataset.get("streams") or []):
        rel_path = _relative_contract_path(
            (raw_stream or {}).get("path", ""),
            label=f"dataset '{dataset_name}' public target",
        )
        target_name = rel_path.name
        spec = PUBLIC_CLIP_SOURCES.get(target_name)
        if spec is None:
            expected = ", ".join(sorted(PUBLIC_CLIP_SOURCES))
            raise DatasetPrepError(f"no preparation source mapping for {target_name}; expected one of: {expected}")
        expected_sha256 = str((raw_stream or {}).get("sha256", "")).strip()
        if not expected_sha256 or expected_sha256.startswith("SET_"):
            raise DatasetPrepError(f"dataset stream {rel_path} does not have a real sha256 in {manifest}")
        rel_path = _public_target_rel(rel_path, target_name=target_name)
        target = _guard_contract_location(
            project_root,
            rel_path,
            namespace_rel=PUBLIC_OUTPUT_REL,
            label="public target",
        )
        source_dir = _guard_contract_location(
            project_root,
            VIDEO_SOURCE_REL / spec.source_rel,
            namespace_rel=VIDEO_SOURCE_REL,
            label="raw frame source directory",
        )
        plans.append(
            ClipPlan(
                project_root=project_root,
                rel_path=rel_path,
                target=target,
                source_dir=source_dir,
                pattern=spec.pattern,
                expected_sha256=expected_sha256,
                fps=spec.fps,
            )
        )
    return plans


def first_frame_path(plan: ClipPlan) -> Path:
    try:
        return plan.source_dir / (plan.pattern % 1)
    except TypeError as exc:
        raise DatasetPrepError(f"invalid ffmpeg image pattern for {plan.target.name}: {plan.pattern}") from exc


FileSnapshot = tuple[int, int, int, int, int, int]
DirectorySnapshot = tuple[int, int, int]


def _file_snapshot_from_stat(observed: os.stat_result) -> FileSnapshot:
    return (
        int(observed.st_dev),
        int(observed.st_ino),
        int(observed.st_mode),
        int(observed.st_size),
        int(observed.st_mtime_ns),
        int(observed.st_ctime_ns),
    )


def _file_object_identity(snapshot: FileSnapshot) -> tuple[int, int, int]:
    return snapshot[:3]


def _regular_file_snapshot(
    path: Path,
    *,
    label: str,
    missing_ok: bool = False,
) -> FileSnapshot | None:
    if _is_link_or_reparse(path):
        raise DatasetPrepError(f"{label} is a symlink, junction, or reparse point: {path}")
    try:
        observed = path.lstat()
    except FileNotFoundError:
        if missing_ok:
            return None
        raise DatasetPrepError(f"{label} is missing: {path}") from None
    except OSError as exc:
        raise DatasetPrepError(f"cannot inspect {label}: {path}: {exc}") from exc
    if not stat.S_ISREG(observed.st_mode):
        raise DatasetPrepError(f"{label} is not a regular file: {path}")
    return _file_snapshot_from_stat(observed)


def _directory_snapshot(path: Path, *, label: str) -> DirectorySnapshot:
    if _is_link_or_reparse(path):
        raise DatasetPrepError(f"{label} is a symlink, junction, or reparse point: {path}")
    try:
        observed = path.lstat()
    except FileNotFoundError:
        raise DatasetPrepError(f"{label} is missing: {path}") from None
    except OSError as exc:
        raise DatasetPrepError(f"cannot inspect {label}: {path}: {exc}") from exc
    if not stat.S_ISDIR(observed.st_mode):
        raise DatasetPrepError(f"{label} is not a directory: {path}")
    return (int(observed.st_dev), int(observed.st_ino), int(observed.st_mode))


def _stable_file_sha256(path: Path, *, label: str) -> tuple[str, FileSnapshot]:
    before = _regular_file_snapshot(path, label=label)
    assert before is not None
    try:
        digest = sha256_file(path)
    except OSError as exc:
        raise DatasetPrepError(f"cannot hash {label}: {path}: {exc}") from exc
    after = _regular_file_snapshot(path, label=label)
    assert after is not None
    if after != before:
        raise DatasetPrepError(f"{label} changed while it was hashed: {path}")
    return digest, after


def _guard_plan_paths(plan: PreparationPlan) -> None:
    project_root = _validated_project_root(plan.project_root)
    relative = _relative_contract_path(plan.rel_path.as_posix(), label="dataset target")
    if isinstance(plan, VideoTranscodePlan):
        relative = _kpp_target_rel(relative)
        expected_target = _guard_contract_location(
            project_root,
            relative,
            namespace_rel=KPP_SOURCE_REL,
            label="transcode target",
        )
        try:
            raw_source_relative = plan.source_file.relative_to(project_root)
        except ValueError as exc:
            raise DatasetPrepError("transcode source path escaped project root") from exc
        source_relative = _kpp_source_rel(raw_source_relative, label="transcode source")
        expected_source = _guard_contract_location(
            project_root,
            source_relative,
            namespace_rel=KPP_SOURCE_REL,
            label="transcode source",
        )
        if not _same_location(plan.source_file, expected_source):
            raise DatasetPrepError("transcode source path drifted after planning")
    else:
        relative = _public_target_rel(relative, target_name=plan.target.name)
        expected_target = _guard_contract_location(
            project_root,
            relative,
            namespace_rel=PUBLIC_OUTPUT_REL,
            label="public target",
        )
        try:
            source_relative = plan.source_dir.relative_to(project_root)
        except ValueError as exc:
            raise DatasetPrepError("raw frame source path escaped project root") from exc
        expected_source = _guard_contract_location(
            project_root,
            source_relative,
            namespace_rel=VIDEO_SOURCE_REL,
            label="raw frame source directory",
        )
        if not _same_location(plan.source_dir, expected_source):
            raise DatasetPrepError("raw frame source path drifted after planning")
    if not _same_location(plan.target, expected_target):
        raise DatasetPrepError("dataset target path drifted after planning")


def ensure_source_frames(plan: ClipPlan) -> None:
    _guard_plan_paths(plan)
    try:
        _directory_snapshot(plan.source_dir, label="raw source directory")
    except DatasetPrepError as exc:
        if "is missing" in str(exc):
            raise DatasetPrepError(
                f"missing raw source directory for {plan.target.name}: {plan.source_dir}"
            ) from exc
        raise
    first_frame = first_frame_path(plan)
    try:
        _regular_file_snapshot(first_frame, label="first raw frame")
    except DatasetPrepError as exc:
        if "is missing" in str(exc):
            raise DatasetPrepError(
                f"missing first raw frame for {plan.target.name}: {first_frame}"
            ) from exc
        raise


def ensure_source_video(plan: VideoTranscodePlan) -> None:
    _guard_plan_paths(plan)
    try:
        actual_sha256, _ = _stable_file_sha256(
            plan.source_file,
            label="raw source video",
        )
    except DatasetPrepError as exc:
        if "is missing" in str(exc):
            raise DatasetPrepError(
                f"missing raw source video for {plan.target.name}: {plan.source_file}"
            ) from exc
        raise
    if actual_sha256 != plan.source_expected_sha256:
        raise DatasetPrepError(
            f"source checksum mismatch for {plan.source_file}: "
            f"expected {plan.source_expected_sha256}, got {actual_sha256}"
        )


def ffmpeg_command(
    plan: PreparationPlan,
    output: Path,
    *,
    ffmpeg: str = "ffmpeg",
) -> list[str]:
    if isinstance(plan, VideoTranscodePlan):
        return [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(plan.source_file),
            "-vf",
            plan.ffmpeg_filter,
            "-an",
            "-c:v",
            plan.encoder,
            "-preset",
            plan.preset,
            "-crf",
            str(plan.crf),
            "-pix_fmt",
            plan.pix_fmt,
            str(output),
        ]
    return [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-start_number",
        "1",
        "-framerate",
        str(plan.fps),
        "-i",
        str(plan.input_pattern),
        "-vf",
        "scale=1920:1080,fps=30",
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "slow",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(output),
    ]


def run_subprocess(command: Sequence[str]) -> subprocess.CompletedProcess:
    return subprocess.run(list(command), check=False)


def _target_state(plan: PreparationPlan) -> tuple[str | None, FileSnapshot | None]:
    _guard_plan_paths(plan)
    snapshot = _regular_file_snapshot(
        plan.target,
        label="dataset target",
        missing_ok=True,
    )
    if snapshot is None:
        return None, None
    digest, stable = _stable_file_sha256(plan.target, label="dataset target")
    return digest, stable


def _ensure_target_parent(plan: PreparationPlan) -> DirectorySnapshot:
    _guard_plan_paths(plan)
    try:
        plan.target.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise DatasetPrepError(
            f"cannot create dataset target directory {plan.target.parent}: {exc}"
        ) from exc
    _guard_plan_paths(plan)
    return _directory_snapshot(plan.target.parent, label="dataset target directory")


def _snapshot_at(
    directory_fd: int,
    name: str,
    *,
    label: str,
    missing_ok: bool = False,
) -> FileSnapshot | None:
    try:
        observed = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        if missing_ok:
            return None
        raise DatasetPrepError(f"{label} is missing") from None
    except OSError as exc:
        raise DatasetPrepError(f"cannot inspect {label}: {exc}") from exc
    if not stat.S_ISREG(observed.st_mode):
        raise DatasetPrepError(f"{label} is not a regular file")
    return _file_snapshot_from_stat(observed)


def _open_verified_directory(
    path: Path,
    *,
    expected: DirectorySnapshot,
    label: str,
) -> int:
    flags = os.O_RDONLY
    flags |= int(getattr(os, "O_DIRECTORY", 0))
    flags |= int(getattr(os, "O_CLOEXEC", 0))
    flags |= int(getattr(os, "O_NOFOLLOW", 0))
    try:
        directory_fd = os.open(path, flags)
    except OSError as exc:
        raise DatasetPrepError(f"{label} changed or became unsafe: {path}: {exc}") from exc
    observed = os.fstat(directory_fd)
    actual = (int(observed.st_dev), int(observed.st_ino), int(observed.st_mode))
    if actual != expected or not stat.S_ISDIR(observed.st_mode):
        os.close(directory_fd)
        raise DatasetPrepError(f"{label} changed during dataset preparation")
    return directory_fd


def _target_changed(
    current: FileSnapshot | None,
    expected: FileSnapshot | None,
) -> bool:
    return current != expected


def _install_candidate(
    plan: PreparationPlan,
    candidate: Path,
    *,
    parent_snapshot: DirectorySnapshot,
    candidate_snapshot: FileSnapshot,
    expected_target_snapshot: FileSnapshot | None,
) -> None:
    parent = plan.target.parent
    if os.name == "posix":
        directory_fd = _open_verified_directory(
            parent,
            expected=parent_snapshot,
            label="dataset target directory",
        )
        try:
            current_candidate = _snapshot_at(
                directory_fd,
                candidate.name,
                label="dataset preparation candidate",
            )
            if current_candidate != candidate_snapshot:
                raise DatasetPrepError("dataset preparation candidate changed before installation")
            current_target = _snapshot_at(
                directory_fd,
                plan.target.name,
                label="dataset target",
                missing_ok=True,
            )
            if _target_changed(current_target, expected_target_snapshot):
                raise DatasetPrepError("dataset target changed while encoder ran")
            try:
                os.replace(
                    candidate.name,
                    plan.target.name,
                    src_dir_fd=directory_fd,
                    dst_dir_fd=directory_fd,
                )
            except OSError as exc:
                raise DatasetPrepError(f"cannot install prepared dataset target: {exc}") from exc
            installed = _snapshot_at(
                directory_fd,
                plan.target.name,
                label="installed dataset target",
            )
            assert installed is not None
            if _file_object_identity(installed) != _file_object_identity(candidate_snapshot):
                raise DatasetPrepError("installed dataset target identity mismatch")
        finally:
            os.close(directory_fd)
    else:
        _guard_plan_paths(plan)
        if _directory_snapshot(parent, label="dataset target directory") != parent_snapshot:
            raise DatasetPrepError("dataset target directory changed during preparation")
        current_candidate = _regular_file_snapshot(
            candidate,
            label="dataset preparation candidate",
        )
        if current_candidate != candidate_snapshot:
            raise DatasetPrepError("dataset preparation candidate changed before installation")
        current_target = _regular_file_snapshot(
            plan.target,
            label="dataset target",
            missing_ok=True,
        )
        if _target_changed(current_target, expected_target_snapshot):
            raise DatasetPrepError("dataset target changed while encoder ran")
        try:
            os.replace(candidate, plan.target)
        except OSError as exc:
            raise DatasetPrepError(f"cannot install prepared dataset target: {exc}") from exc

    _guard_plan_paths(plan)
    installed_sha256, _ = _stable_file_sha256(
        plan.target,
        label="installed dataset target",
    )
    if installed_sha256 != plan.expected_sha256:
        raise DatasetPrepError("installed dataset target checksum changed after installation")


def _remove_verified_candidate(
    candidate: Path,
    *,
    parent_snapshot: DirectorySnapshot,
    candidate_identity: tuple[int, int, int],
) -> None:
    parent = candidate.parent
    if os.name == "posix":
        try:
            directory_fd = _open_verified_directory(
                parent,
                expected=parent_snapshot,
                label="dataset target directory",
            )
        except DatasetPrepError:
            return
        try:
            try:
                current = _snapshot_at(
                    directory_fd,
                    candidate.name,
                    label="dataset preparation candidate",
                    missing_ok=True,
                )
            except DatasetPrepError:
                return
            if current is None or _file_object_identity(current) != candidate_identity:
                return
            try:
                os.unlink(candidate.name, dir_fd=directory_fd)
            except OSError:
                return
        finally:
            os.close(directory_fd)
        return

    try:
        if _directory_snapshot(parent, label="dataset target directory") != parent_snapshot:
            return
        current = _regular_file_snapshot(
            candidate,
            label="dataset preparation candidate",
            missing_ok=True,
        )
        if current is None or _file_object_identity(current) != candidate_identity:
            return
        candidate.unlink()
    except (DatasetPrepError, OSError):
        return


def prepare_clip(
    plan: PreparationPlan,
    *,
    force: bool = False,
    dry_run: bool = False,
    ffmpeg: str = "ffmpeg",
    runner: Runner = run_subprocess,
) -> str:
    target_sha256, target_snapshot = _target_state(plan)
    if target_sha256 == plan.expected_sha256 and not force:
        return "skipped"
    if target_snapshot is not None and not force:
        raise DatasetPrepError(
            f"refusing to overwrite mismatched target without --force: {plan.target}"
        )
    reason = "forced" if force and target_snapshot is not None else "missing"

    if isinstance(plan, VideoTranscodePlan):
        ensure_source_video(plan)
        source_description = plan.source_file
    else:
        ensure_source_frames(plan)
        source_description = plan.source_dir
    if dry_run:
        print(f"[dataset] would encode {plan.target} from {source_description} ({reason})")
        return f"dry_run_{reason}"

    if runner is run_subprocess and shutil.which(ffmpeg) is None:
        raise DatasetPrepError(f"ffmpeg not found: {ffmpeg}")

    parent_snapshot = _ensure_target_parent(plan)
    target_after_parent_create = _regular_file_snapshot(
        plan.target,
        label="dataset target",
        missing_ok=True,
    )
    if _target_changed(target_after_parent_create, target_snapshot):
        raise DatasetPrepError("dataset target changed before encoder start")

    tmp_path: Path | None = None
    candidate_identity: tuple[int, int, int] | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{plan.target.stem}.",
            suffix=plan.target.suffix,
            dir=plan.target.parent,
            delete=False,
        ) as tmp:
            tmp_path = Path(tmp.name)
        candidate_initial = _regular_file_snapshot(
            tmp_path,
            label="dataset preparation candidate",
        )
        assert candidate_initial is not None
        candidate_identity = _file_object_identity(candidate_initial)
        if (
            _directory_snapshot(plan.target.parent, label="dataset target directory")
            != parent_snapshot
        ):
            raise DatasetPrepError("dataset target directory changed before encoder start")

        command = ffmpeg_command(plan, tmp_path, ffmpeg=ffmpeg)
        completed = runner(command)
        if int(completed.returncode) != 0:
            raise DatasetPrepError(f"ffmpeg failed for {plan.target.name} with exit code {completed.returncode}")
        actual_sha256, candidate_snapshot = _stable_file_sha256(
            tmp_path,
            label="dataset preparation candidate",
        )
        if _file_object_identity(candidate_snapshot) != candidate_identity:
            raise DatasetPrepError("dataset preparation candidate was replaced by encoder")
        if actual_sha256 != plan.expected_sha256:
            raise DatasetPrepError(
                f"prepared checksum mismatch for {plan.target.name}: "
                f"expected {plan.expected_sha256}, got {actual_sha256}"
            )
        try:
            with tmp_path.open("rb+") as candidate_file:
                os.fsync(candidate_file.fileno())
        except OSError as exc:
            raise DatasetPrepError(
                f"cannot flush prepared dataset candidate {tmp_path}: {exc}"
            ) from exc
        _install_candidate(
            plan,
            tmp_path,
            parent_snapshot=parent_snapshot,
            candidate_snapshot=candidate_snapshot,
            expected_target_snapshot=target_snapshot,
        )
    finally:
        if tmp_path is not None and candidate_identity is not None:
            _remove_verified_candidate(
                tmp_path,
                parent_snapshot=parent_snapshot,
                candidate_identity=candidate_identity,
            )
    return reason


def prepare_dataset(
    *,
    manifest: Path,
    dataset_name: str,
    project_root: Path,
    source_root: Path,
    output_dir: Path,
    force: bool = False,
    dry_run: bool = False,
    ffmpeg: str = "ffmpeg",
    runner: Runner = run_subprocess,
) -> list[tuple[PreparationPlan, str]]:
    project_root = _validated_project_root(project_root)
    manifest = _guard_manifest(project_root, manifest)
    dataset = _read_manifest_dataset(manifest, dataset_name)
    if _is_check_only_materialized_v2(
        dataset_name,
        dataset,
        project_root=project_root,
    ):
        if force:
            raise DatasetPrepError(
                "--force is not supported for check-only materialized datasets"
            )
        validate_manifest_dataset(
            manifest,
            dataset_name,
            project_root=project_root,
            dry_run=dry_run,
        )
        return []
    plans = build_clip_plans(
        manifest=manifest,
        dataset_name=dataset_name,
        project_root=project_root,
        source_root=source_root,
        output_dir=output_dir,
    )
    results: list[tuple[PreparationPlan, str]] = []
    for plan in plans:
        status = prepare_clip(plan, force=force, dry_run=dry_run, ffmpeg=ffmpeg, runner=runner)
        results.append((plan, status))
        print(f"[dataset] {plan.target.name}: {status}")
    return results


def validate_manifest_dataset(manifest: Path, dataset_name: str, *, project_root: Path, dry_run: bool) -> None:
    dataset = _read_manifest_dataset(manifest, dataset_name)
    check_only = _is_check_only_materialized_v2(
        dataset_name,
        dataset,
        project_root=project_root,
    )
    if dry_run and not check_only:
        return
    try:
        load_dataset(
            manifest,
            dataset_name,
            mode="smoke" if check_only else "benchmark",
            project_root=project_root,
            require_files=True,
        )
    except ContractError as exc:
        raise DatasetPrepError(str(exc)) from exc


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare VAST public clips or manifest-defined KPP codec transcodes "
            "from checksum-verified local sources"
        )
    )
    parser.add_argument("--manifest", type=Path, default=Path("configs/datasets.yaml"))
    parser.add_argument("--dataset", default="kpp_real_h264")
    parser.add_argument(
        "--source-root",
        type=Path,
        default=Path("data/videos"),
        help="Raw image root for MOT17/UA-DETRAC preparation",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/benchmark"),
        help="Fixed public clip output (must resolve to project_root/data/benchmark)",
    )
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace a stable mismatched manifest target after rechecking its identity",
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    project_root = _validated_project_root(args.project_root)
    if not _same_location(project_root, PROJECT_ROOT):
        raise DatasetPrepError(
            f"project root must match the repository containing this script: {PROJECT_ROOT}"
        )
    manifest = _guard_manifest(project_root, args.manifest)
    prepare_dataset(
        manifest=manifest,
        dataset_name=args.dataset,
        project_root=project_root,
        source_root=args.source_root,
        output_dir=args.output_dir,
        force=bool(args.force),
        dry_run=bool(args.dry_run),
        ffmpeg=str(args.ffmpeg),
    )
    dataset = _read_manifest_dataset(manifest, args.dataset)
    check_only = _is_check_only_materialized_v2(
        args.dataset,
        dataset,
        project_root=project_root,
    )
    if not check_only:
        validate_manifest_dataset(
            manifest,
            args.dataset,
            project_root=project_root,
            dry_run=bool(args.dry_run),
        )
    print(f"[dataset] {args.dataset} ready")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except DatasetPrepError as exc:
        print(f"[dataset][error] {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
