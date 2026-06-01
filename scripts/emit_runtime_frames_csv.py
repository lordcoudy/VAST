#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import subprocess
import time
import uuid
from pathlib import Path


def probe_video_fps(video_path: Path) -> float:
    if not video_path.exists():
        return 30.0

    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=avg_frame_rate",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(video_path),
    ]
    try:
        raw = subprocess.check_output(cmd, text=True).strip()
        if "/" in raw:
            num, den = raw.split("/", 1)
            den_f = float(den)
            if den_f == 0:
                return 30.0
            fps = float(num) / den_f
            return fps if fps > 0 else 30.0
        fps = float(raw)
        return fps if fps > 0 else 30.0
    except Exception:
        return 30.0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Emit synthetic smoke-only per-frame metrics to frames.csv"
    )
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--duration-s", required=True, type=int)
    parser.add_argument("--streams", required=True, type=int)
    parser.add_argument("--elapsed-ms", required=True, type=float)
    parser.add_argument("--source-video", required=True, type=Path)
    parser.add_argument("--min-objects", type=int, default=0)
    parser.add_argument("--max-objects", type=int, default=20)
    parser.add_argument("--deadline-ms", type=float, default=3000.0)
    parser.add_argument("--run-id", default="")
    parser.add_argument("--detector", default="synthetic")
    parser.add_argument("--backend", default="synthetic")
    args = parser.parse_args()

    output = args.output
    output.parent.mkdir(parents=True, exist_ok=True)

    streams = max(1, int(args.streams))
    duration_s = max(1, int(args.duration_s))
    elapsed_ms = max(float(args.elapsed_ms), 1.0)
    source_fps = probe_video_fps(args.source_video)
    run_id = args.run_id or f"smoke-{uuid.uuid4()}"

    target_frames = int(round(source_fps * duration_s * streams))
    total_frames = max(1, target_frames)

    latency_ms = elapsed_ms / total_frames
    if latency_ms <= 0:
        latency_ms = 0.001
    fps_instant = 1000.0 / latency_ms
    objects = max(args.min_objects, min(args.max_objects, (args.min_objects + args.max_objects) // 2))
    start_ts = int(time.time() * 1000) - int(elapsed_ms)
    frame_dt_ms = max(1.0, 1000.0 / max(fps_instant, 0.001))

    with output.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "schema_version",
                "run_id",
                "trace_id",
                "stream_id",
                "frame_id",
                "ingress_timestamp_ms",
                "egress_timestamp_ms",
                "e2e_latency_ms",
                "objects",
                "detector",
                "backend",
                "telemetry_source",
            ]
        )
        for frame_id in range(total_frames):
            stream_id = frame_id % streams
            ingress_ts = start_ts + int(frame_id * frame_dt_ms)
            egress_ts = ingress_ts + latency_ms
            writer.writerow(
                [
                    2,
                    run_id,
                    f"{run_id}:{stream_id}:{frame_id}",
                    stream_id,
                    frame_id,
                    round(ingress_ts, 6),
                    round(egress_ts, 6),
                    round(latency_ms, 6),
                    objects,
                    args.detector,
                    args.backend,
                    "synthetic",
                ]
            )


if __name__ == "__main__":
    main()
