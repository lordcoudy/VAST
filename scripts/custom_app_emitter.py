#!/usr/bin/env python3
import argparse
import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    p = argparse.ArgumentParser(description="Wrapper that produces realistic frames.csv for custom app runs")
    p.add_argument("--scenario", required=False)
    p.add_argument("--streams", type=int, default=6)
    p.add_argument("--duration", type=int, default=30)
    p.add_argument("--output", required=True, help="Output directory (frames.csv will be created inside)")
    p.add_argument("--run-id", default=os.environ.get("EXPERIMENT_RUN_ID", "smoke-custom"))
    p.add_argument("--detector", default=os.environ.get("ADAPTER_DETECTOR", "synthetic"))
    p.add_argument("--backend", default=os.environ.get("ADAPTER_BACKEND", "synthetic"))
    args = p.parse_args()

    project_root = Path(__file__).resolve().parent
    # Ensure output dir exists and target frames file path
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)
    frames_csv = out_dir / "frames.csv"

    # Locate the emitter script bundled in this project
    emitter = project_root / "emit_runtime_frames_csv.py"
    if not emitter.exists():
        emitter = project_root / "emit_runtime_frames_csv.py"

    # Pick a source video from VIDEO_LAYOUT_DIR or fallback to project data/videos
    video_layout = os.environ.get("VIDEO_LAYOUT_DIR", str(project_root.parent / "data" / "videos"))
    source_video = str(Path(video_layout) / "stream01.mp4")

    duration_s = int(args.duration)
    streams = int(args.streams)
    elapsed_ms = duration_s * 1000

    cmd = [
        sys.executable,
        str(emitter),
        "--output",
        str(frames_csv),
        "--duration-s",
        str(duration_s),
        "--streams",
        str(streams),
        "--elapsed-ms",
        str(elapsed_ms),
        "--source-video",
        source_video,
        "--min-objects",
        os.environ.get("MIN_OBJECTS", "0"),
        "--max-objects",
        os.environ.get("MAX_OBJECTS", "20"),
        "--deadline-ms",
        os.environ.get("DEADLINE_MS", "3000"),
        "--run-id",
        args.run_id,
        "--detector",
        args.detector,
        "--backend",
        args.backend,
    ]

    try:
        subprocess.run(cmd, check=True)
        return 0
    except subprocess.CalledProcessError as exc:
        print(f"Emitter failed: {exc}", file=sys.stderr)
        return exc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
