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


def build_clip_plans(
    *,
    manifest: Path,
    dataset_name: str,
    project_root: Path,
    source_root: Path,
    output_dir: Path,
) -> list[ClipPlan]:
    project_root = project_root.resolve()
    manifest = _resolve_under_project(project_root, manifest).resolve()
    source_root = _resolve_under_project(project_root, source_root).resolve()
    output_dir = _resolve_under_project(project_root, output_dir).resolve()
    dataset = _read_manifest_dataset(manifest, dataset_name)
    if str(dataset.get("kind", "")) in {"real_avi", "real_codec_transcode"}:
        return []

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


def ffmpeg_command(plan: ClipPlan, output: Path, *, ffmpeg: str = "ffmpeg") -> list[str]:
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


def _target_matches(plan: ClipPlan) -> bool:
    return plan.target.exists() and sha256_file(plan.target) == plan.expected_sha256


def prepare_clip(
    plan: ClipPlan,
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

    ensure_source_frames(plan)
    if dry_run:
        print(f"[dataset] would encode {plan.target} from {plan.source_dir} ({reason})")
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
) -> list[tuple[ClipPlan, str]]:
    plans = build_clip_plans(
        manifest=manifest,
        dataset_name=dataset_name,
        project_root=project_root,
        source_root=source_root,
        output_dir=output_dir,
    )
    results: list[tuple[ClipPlan, str]] = []
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
    parser = argparse.ArgumentParser(description="Prepare VAST public benchmark clips from local raw MOT17/UA-DETRAC sources")
    parser.add_argument("--manifest", type=Path, default=Path("configs/datasets.yaml"))
    parser.add_argument("--dataset", default="kpp_real_h264")
    parser.add_argument("--source-root", type=Path, default=Path("data/videos"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/benchmark"))
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
