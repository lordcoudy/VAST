#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

import yaml
from benchmark_contract import ContractError, load_dataset, sha256_file


class DatasetPrepError(RuntimeError):
    pass


@dataclass(frozen=True)
class SourceSpec:
    source_rel: Path
    pattern: str
    fps: int = 30


@dataclass(frozen=True)
class ClipPlan:
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


def _resolve_under_project(project_root: Path, path: Path) -> Path:
    return path if path.is_absolute() else project_root / path


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
        source_path = Path(str((raw_source or {}).get("path", "")))
        source_sha256 = str((raw_source or {}).get("sha256", "")).strip()
        if not str(source_path) or not source_sha256 or source_sha256.startswith("SET_"):
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
    source_paths = {
        Path(str(value)).as_posix()
        for value in list(transcode.get("source_paths") or [])
        if str(value).strip()
    }
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
        rel_path = Path(rel_path_value)
        source_rel = Path(source_path_value)
        expected_sha256 = str(stream.get("sha256", "")).strip()
        if not rel_path_value or not source_path_value:
            raise DatasetPrepError(
                f"real codec dataset '{dataset_name}' has a stream without path/source_path"
            )
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
            rel_path=rel_path,
            target=_resolve_under_project(project_root, rel_path).resolve(),
            source_file=_resolve_under_project(project_root, source_rel).resolve(),
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
    project_root = project_root.resolve()
    manifest = _resolve_under_project(project_root, manifest).resolve()
    source_root = _resolve_under_project(project_root, source_root).resolve()
    output_dir = _resolve_under_project(project_root, output_dir).resolve()
    dataset = _read_manifest_dataset(manifest, dataset_name)
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
        rel_path = Path(str((raw_stream or {}).get("path", "")))
        if not str(rel_path):
            raise DatasetPrepError(f"dataset '{dataset_name}' contains a stream without path")
        target_name = rel_path.name
        spec = PUBLIC_CLIP_SOURCES.get(target_name)
        if spec is None:
            expected = ", ".join(sorted(PUBLIC_CLIP_SOURCES))
            raise DatasetPrepError(f"no preparation source mapping for {target_name}; expected one of: {expected}")
        expected_sha256 = str((raw_stream or {}).get("sha256", "")).strip()
        if not expected_sha256 or expected_sha256.startswith("SET_"):
            raise DatasetPrepError(f"dataset stream {rel_path} does not have a real sha256 in {manifest}")
        plans.append(
            ClipPlan(
                rel_path=rel_path,
                target=output_dir / target_name,
                source_dir=source_root / spec.source_rel,
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


def ensure_source_frames(plan: ClipPlan) -> None:
    if not plan.source_dir.is_dir():
        raise DatasetPrepError(f"missing raw source directory for {plan.target.name}: {plan.source_dir}")
    first_frame = first_frame_path(plan)
    if not first_frame.exists():
        raise DatasetPrepError(f"missing first raw frame for {plan.target.name}: {first_frame}")


def ensure_source_video(plan: VideoTranscodePlan) -> None:
    if not plan.source_file.is_file():
        raise DatasetPrepError(
            f"missing raw source video for {plan.target.name}: {plan.source_file}"
        )
    actual_sha256 = sha256_file(plan.source_file)
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


def _target_matches(plan: PreparationPlan) -> bool:
    return plan.target.exists() and sha256_file(plan.target) == plan.expected_sha256


def prepare_clip(
    plan: PreparationPlan,
    *,
    force: bool = False,
    dry_run: bool = False,
    ffmpeg: str = "ffmpeg",
    runner: Runner = run_subprocess,
) -> str:
    if _target_matches(plan) and not force:
        return "skipped"

    reason = "forced" if force and plan.target.exists() else "missing"
    if plan.target.exists() and not force:
        reason = "checksum_mismatch"

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

    plan.target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        prefix=f".{plan.target.stem}.",
        suffix=plan.target.suffix,
        dir=plan.target.parent,
        delete=False,
    ) as tmp:
        tmp_path = Path(tmp.name)

    try:
        command = ffmpeg_command(plan, tmp_path, ffmpeg=ffmpeg)
        completed = runner(command)
        if int(completed.returncode) != 0:
            raise DatasetPrepError(f"ffmpeg failed for {plan.target.name} with exit code {completed.returncode}")
        if not tmp_path.exists():
            raise DatasetPrepError(f"ffmpeg did not produce expected output: {tmp_path}")
        actual_sha256 = sha256_file(tmp_path)
        if actual_sha256 != plan.expected_sha256:
            raise DatasetPrepError(
                f"prepared checksum mismatch for {plan.target.name}: "
                f"expected {plan.expected_sha256}, got {actual_sha256}"
            )
        tmp_path.replace(plan.target)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
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
    if dry_run:
        return
    try:
        load_dataset(manifest, dataset_name, mode="benchmark", project_root=project_root, require_files=True)
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
        help="Public clip output; KPP targets use their exact manifest paths",
    )
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    project_root = args.project_root.resolve()
    manifest = _resolve_under_project(project_root, args.manifest).resolve()
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
    validate_manifest_dataset(manifest, args.dataset, project_root=project_root, dry_run=bool(args.dry_run))
    print(f"[dataset] {args.dataset} ready")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except DatasetPrepError as exc:
        print(f"[dataset][error] {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
