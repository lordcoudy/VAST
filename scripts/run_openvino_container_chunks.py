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
        "/workspace/project/build/bin/vast_native_gst_probe",
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
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    frames_out = output_dir / "frames.csv"
    events_out = output_dir / "frame_events.csv"
    for path in (frames_out, events_out):
        if path.exists():
            path.unlink()

    stream_sources = parse_stream_sources(args)
    parallel_streams = resolve_parallel_streams(args)
    remaining = int(args.duration)
    chunk_index = 1
    while remaining > 0:
        chunk_duration = min(int(args.chunk_s), remaining)
        chunk_dir = output_dir / "chunks" / f"chunk_{chunk_index:02d}"
        if chunk_dir.exists():
            shutil.rmtree(chunk_dir)
        chunk_dir.mkdir(parents=True, exist_ok=True)
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
