#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Sequence


class ChunkRunError(RuntimeError):
    pass


CHUNK_OWNER_MARKER = ".vast_openvino_chunk_owner"


def _is_link_or_junction(path: Path) -> bool:
    is_junction = getattr(os.path, "isjunction", lambda _path: False)
    return path.is_symlink() or bool(is_junction(path))


def _lexical_absolute(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _require_plain_path_chain(path: Path, *, stop: Path, label: str) -> None:
    lexical = _lexical_absolute(path)
    boundary = _lexical_absolute(stop)
    try:
        relative = lexical.relative_to(boundary)
    except ValueError as exc:
        raise ChunkRunError(f"{label} escapes its expected root") from exc
    current = boundary
    for part in relative.parts:
        current = current / part
        if _is_link_or_junction(current):
            raise ChunkRunError(f"{label} contains a symlink or junction: {current}")


def guard_chunk_output_dir(project_dir: Path | str, output_dir: Path | str) -> Path:
    """Bind chunk output to a real directory below the project runs namespace."""

    project_raw = Path(project_dir)
    output_raw = Path(output_dir)
    if not project_raw.is_absolute() or not output_raw.is_absolute():
        raise ChunkRunError("project and OpenVINO chunk output paths must be absolute")
    project = _lexical_absolute(project_raw)
    output = _lexical_absolute(output_raw)
    if (
        not project.is_dir()
        or _is_link_or_junction(project)
        or project.resolve() != project
    ):
        raise ChunkRunError("OpenVINO chunk project directory is unsafe")
    runs_root = project / "runs"
    resolved_output = output.resolve()
    resolved_runs = runs_root.resolve()
    try:
        relative = resolved_output.relative_to(resolved_runs)
    except ValueError as exc:
        raise ChunkRunError("OpenVINO chunk output must be below project/runs") from exc
    if not relative.parts or output != resolved_output:
        raise ChunkRunError("OpenVINO chunk output must be a dedicated plain child below project/runs")
    _require_plain_path_chain(output, stop=project, label="OpenVINO chunk output")
    if output.exists() and not output.is_dir():
        raise ChunkRunError("OpenVINO chunk output exists but is not a directory")
    if output in {project, runs_root, Path.cwd().resolve()}:
        raise ChunkRunError("OpenVINO chunk output is not a dedicated run directory")
    return output


def _expected_chunk_directory(
    output_dir: Path | str,
    chunk_dir: Path | str,
    *,
    chunk_index: int,
) -> tuple[Path, Path]:
    if type(chunk_index) is not int or chunk_index <= 0:
        raise ChunkRunError("OpenVINO chunk index must be a positive integer")
    output = _lexical_absolute(Path(output_dir))
    chunk = _lexical_absolute(Path(chunk_dir))
    expected = output / "chunks" / f"chunk_{chunk_index:02d}"
    if chunk != expected:
        raise ChunkRunError("OpenVINO chunk cleanup target is not the exact expected directory")
    if output.resolve() != output or _is_link_or_junction(output):
        raise ChunkRunError("OpenVINO chunk output became a symlink, junction, or alias")
    _require_plain_path_chain(chunk, stop=output, label="OpenVINO chunk cleanup target")
    if chunk in {output, Path.cwd().resolve()}:
        raise ChunkRunError("refusing to remove a broad OpenVINO chunk path")
    return output, chunk


def _owner_payload(*, run_id: str, chunk_index: int) -> str:
    if (
        type(run_id) is not str
        or not run_id
        or len(run_id) > 512
        or "\n" in run_id
        or "\r" in run_id
    ):
        raise ChunkRunError("OpenVINO chunk run_id is invalid")
    return f"{run_id}\n{chunk_index}\n"


def remove_owned_chunk_directory(
    output_dir: Path | str,
    chunk_dir: Path | str,
    *,
    run_id: str,
    chunk_index: int,
) -> None:
    """Remove only a previously marked directory for this exact run/chunk."""

    output, chunk = _expected_chunk_directory(
        output_dir,
        chunk_dir,
        chunk_index=chunk_index,
    )
    if not chunk.exists() and not _is_link_or_junction(chunk):
        return
    if _is_link_or_junction(chunk) or not chunk.is_dir() or chunk.resolve() != chunk:
        raise ChunkRunError("OpenVINO chunk cleanup target is not a plain directory")
    before = chunk.lstat()
    before_identity = (before.st_dev, before.st_ino, before.st_mode)
    marker = chunk / CHUNK_OWNER_MARKER
    if (
        _is_link_or_junction(marker)
        or not marker.is_file()
        or marker.resolve() != marker
        or marker.stat().st_size > 1024
    ):
        raise ChunkRunError("OpenVINO chunk ownership marker is missing or unsafe")
    try:
        observed_owner = marker.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ChunkRunError("OpenVINO chunk ownership marker cannot be read") from exc
    if observed_owner != _owner_payload(run_id=run_id, chunk_index=chunk_index):
        raise ChunkRunError("OpenVINO chunk ownership marker does not match this run")
    _require_plain_path_chain(chunk, stop=output, label="OpenVINO chunk cleanup target")
    if _is_link_or_junction(chunk) or chunk.resolve() != chunk:
        raise ChunkRunError("OpenVINO chunk cleanup target changed during verification")
    after = chunk.lstat()
    if (after.st_dev, after.st_ino, after.st_mode) != before_identity:
        raise ChunkRunError("OpenVINO chunk cleanup target changed during verification")
    shutil.rmtree(chunk)


def _initialize_owned_chunk_directory(
    output_dir: Path,
    chunk_dir: Path,
    *,
    run_id: str,
    chunk_index: int,
) -> None:
    output, chunk = _expected_chunk_directory(
        output_dir,
        chunk_dir,
        chunk_index=chunk_index,
    )
    chunk.mkdir(parents=True, exist_ok=False)
    _require_plain_path_chain(chunk, stop=output, label="OpenVINO chunk directory")
    if _is_link_or_junction(chunk) or chunk.resolve() != chunk:
        raise ChunkRunError("OpenVINO chunk directory became unsafe during creation")
    marker = chunk / CHUNK_OWNER_MARKER
    with marker.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(_owner_payload(run_id=run_id, chunk_index=chunk_index))
        handle.flush()
        os.fsync(handle.fileno())


def append_csv(src: Path, dst: Path, *, run_id: str, stream_index: int) -> None:
    if not src.exists() or src.stat().st_size == 0:
        raise ChunkRunError(f"chunk CSV was not produced: {src}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    with src.open("r", encoding="utf-8", newline="") as in_file:
        reader = csv.DictReader(in_file)
        if not reader.fieldnames:
            raise ChunkRunError(f"chunk CSV is empty: {src}")
        required = {"run_id", "trace_id", "stream_id", "frame_id"}
        missing = required.difference(reader.fieldnames)
        if missing:
            raise ChunkRunError(f"chunk CSV {src} is missing columns: {sorted(missing)}")
        write_header = not dst.exists() or dst.stat().st_size == 0
        with dst.open("a", encoding="utf-8", newline="") as out_file:
            writer = csv.DictWriter(out_file, fieldnames=reader.fieldnames)
            if write_header:
                writer.writeheader()
            for line_number, row in enumerate(reader, start=2):
                if None in row or any(value is None for key, value in row.items() if key is not None):
                    raise ChunkRunError(
                        f"malformed raw CSV row in {src} at line {line_number}: "
                        f"expected {len(reader.fieldnames)} fields"
                    )
                frame_id = row.get("frame_id", "")
                row["run_id"] = run_id
                row["stream_id"] = str(stream_index)
                row["trace_id"] = f"{run_id}:{stream_index}:{frame_id}"
                writer.writerow(row)


def parse_stream_sources(args: argparse.Namespace) -> list[str]:
    if not args.dataset_streams_json:
        return [""] * int(args.streams)
    try:
        raw = json.loads(args.dataset_streams_json)
    except json.JSONDecodeError as exc:
        raise ChunkRunError(f"--dataset-streams-json is not valid JSON: {exc}") from exc
    if not isinstance(raw, list):
        raise ChunkRunError("--dataset-streams-json must be a JSON list")
    if not raw:
        raise ChunkRunError("--dataset-streams-json must contain at least one stream when provided")
    if any(not isinstance(value, str) for value in raw):
        raise ChunkRunError("--dataset-streams-json entries must be strings")
    # Benchmarks may request more streams than the public clip set; match the native
    # probe's deterministic round-robin assignment instead of rejecting the profile.
    return [str(raw[index % len(raw)]) for index in range(int(args.streams))]


def build_stream_command(
    args: argparse.Namespace,
    *,
    chunk_index: int,
    chunk_duration: int,
    stream_index: int,
    stream_source: str,
) -> tuple[str, list[str]]:
    stream_run_id = f"{args.run_id}-chunk{chunk_index:02d}-stream{stream_index:02d}"
    container_stream_dir = (
        f"{args.container_output_dir.rstrip('/')}/chunks/chunk_{chunk_index:02d}/stream_{stream_index:02d}"
    )
    dataset_json = json.dumps([stream_source]) if stream_source else ""
    command = [
        "docker",
        "run",
        "--rm",
        "--network",
        "host",
        "--gpus",
        "all",
        "-e",
        "NVIDIA_DRIVER_CAPABILITIES=compute,utility,video",
        "-e",
        f"EXPERIMENT_RTP_INPUT_PORT={args.input_port}",
        "-e",
        f"EXPERIMENT_RTP_OUTPUT_HOST={args.output_host}",
        "-e",
        f"EXPERIMENT_RTP_OUTPUT_PORT={args.output_port}",
        "-e",
        f"EXPERIMENT_RTP_PORT_STRIDE={args.port_stride}",
        "-e",
        f"EXPERIMENT_RUN_ID={stream_run_id}",
        "-e",
        f"EXPERIMENT_HOST_ROLE={args.role}",
        "-e",
        f"EXPERIMENT_PIPELINE_STAGES={args.stages}",
        "-e",
        f"ADAPTER_DETECTOR={args.detector}",
        "-e",
        f"ADAPTER_BACKEND={args.backend}",
        "-e",
        f"DATASET_STREAMS_JSON={dataset_json}",
        "-v",
        f"{args.project_dir}:/workspace/project",
        "-w",
        "/workspace/project",
        "--entrypoint",
        "/usr/local/bin/vast_native_gst_probe",
        args.image,
        "--system",
        "openvino_gva",
        "--role",
        args.role,
        "--stages",
        args.stages,
        "--run-id",
        stream_run_id,
        "--detector",
        args.detector,
        "--backend",
        args.backend,
        "--output-dir",
        container_stream_dir,
        "--duration",
        str(chunk_duration),
        "--streams",
        "1",
        "--video-layout-dir",
        args.video_layout_dir,
        "--detect-bin",
        args.detect_bin,
        "--min-objects",
        str(args.min_objects),
        "--max-objects",
        str(args.max_objects),
        "--deadline-ms",
        str(args.deadline_ms),
        "--policy",
        args.policy,
        "--port-stride",
        str(args.port_stride),
    ]
    if args.input_port:
        command.extend(["--input-port-base", args.input_port])
    if args.output_host:
        command.extend(["--output-host", args.output_host])
    if args.output_port:
        command.extend(["--output-port-base", args.output_port])
    return stream_run_id, command


def resolve_parallel_streams(args: argparse.Namespace) -> int:
    if args.parallel_streams and int(args.parallel_streams) > 0:
        requested = int(args.parallel_streams)
    else:
        requested = int(os.environ.get("OPENVINO_GVA_PARALLEL_STREAMS", "0") or "0")
    if requested <= 0:
        requested = int(args.streams)
    return max(1, min(int(args.streams), requested))


def run_stream(command: list[str], *, chunk_index: int, stream_index: int, chunk_duration: int) -> int:
    print(
        f"[openvino-chunks] chunk={chunk_index:02d} stream={stream_index:02d} "
        f"duration_s={chunk_duration}"
    )
    return int(subprocess.run(command, check=False).returncode)


def run_chunks(args: argparse.Namespace) -> None:
    output_dir = guard_chunk_output_dir(args.project_dir, args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_dir = guard_chunk_output_dir(args.project_dir, output_dir)
    frames_out = output_dir / "frames.csv"
    events_out = output_dir / "frame_events.csv"
    for path in (frames_out, events_out):
        if path.exists():
            if path.is_symlink() or not path.is_file() or path.resolve() != path:
                raise ChunkRunError(f"refusing to replace unsafe chunk aggregate: {path}")
            path.unlink()

    stream_sources = parse_stream_sources(args)
    parallel_streams = resolve_parallel_streams(args)
    remaining = int(args.duration)
    chunk_index = 1
    while remaining > 0:
        chunk_duration = min(int(args.chunk_s), remaining)
        chunk_dir = output_dir / "chunks" / f"chunk_{chunk_index:02d}"
        remove_owned_chunk_directory(
            output_dir,
            chunk_dir,
            run_id=str(args.run_id),
            chunk_index=chunk_index,
        )
        _initialize_owned_chunk_directory(
            output_dir,
            chunk_dir,
            run_id=str(args.run_id),
            chunk_index=chunk_index,
        )
        jobs: list[tuple[int, str, Path, list[str]]] = []
        for stream_index, stream_source in enumerate(stream_sources):
            stream_run_id, command = build_stream_command(
                args,
                chunk_index=chunk_index,
                chunk_duration=chunk_duration,
                stream_index=stream_index,
                stream_source=stream_source,
            )
            jobs.append((stream_index, stream_run_id, chunk_dir / f"stream_{stream_index:02d}", command))
        with ThreadPoolExecutor(max_workers=parallel_streams) as executor:
            futures = {
                executor.submit(
                    run_stream,
                    command,
                    chunk_index=chunk_index,
                    stream_index=stream_index,
                    chunk_duration=chunk_duration,
                ): (stream_index, stream_run_id, stream_dir)
                for stream_index, stream_run_id, stream_dir, command in jobs
            }
            failures: list[str] = []
            for future in as_completed(futures):
                stream_index, _stream_run_id, _stream_dir = futures[future]
                rc = future.result()
                if rc != 0:
                    failures.append(f"stream {stream_index:02d} rc={rc}")
            if failures:
                raise ChunkRunError(f"OpenVINO chunk {chunk_index:02d} failed: {', '.join(failures)}")
        for stream_index, stream_run_id, stream_dir, _command in jobs:
            append_csv(stream_dir / "frames.csv", frames_out, run_id=stream_run_id, stream_index=stream_index)
            append_csv(
                stream_dir / "frame_events.csv",
                events_out,
                run_id=stream_run_id,
                stream_index=stream_index,
            )
        remaining -= chunk_duration
        chunk_index += 1


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run OpenVINO native probe in isolated stream container chunks and merge native CSV telemetry")
    parser.add_argument("--image", required=True)
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--container-output-dir", required=True)
    parser.add_argument("--duration", type=int, required=True)
    parser.add_argument("--chunk-s", type=int, required=True)
    parser.add_argument("--streams", type=int, required=True)
    parser.add_argument("--video-layout-dir", required=True)
    parser.add_argument("--detect-bin", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--role", required=True)
    parser.add_argument("--stages", required=True)
    parser.add_argument("--detector", required=True)
    parser.add_argument("--backend", required=True)
    parser.add_argument("--dataset-streams-json", default="")
    parser.add_argument("--input-port", default="")
    parser.add_argument("--output-host", default="")
    parser.add_argument("--output-port", default="")
    parser.add_argument("--port-stride", type=int, default=1)
    parser.add_argument("--min-objects", type=int, required=True)
    parser.add_argument("--max-objects", type=int, required=True)
    parser.add_argument("--deadline-ms", type=float, required=True)
    parser.add_argument("--policy", required=True)
    parser.add_argument("--parallel-streams", type=int, default=0)
    args = parser.parse_args(argv)
    if args.chunk_s <= 0:
        raise ChunkRunError("--chunk-s must be positive")
    if args.duration <= 0:
        raise ChunkRunError("--duration must be positive")
    if args.streams <= 0:
        raise ChunkRunError("--streams must be positive")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    run_chunks(parse_args(argv))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ChunkRunError as exc:
        print(f"[openvino-chunks][error] {exc}")
        raise SystemExit(2) from exc
