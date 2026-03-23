#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import random
import time
from pathlib import Path

SYSTEM_FACTORS = {
    "deepstream": (1.00, 0.95),
    "savant": (0.95, 1.02),
    "openvino_gva": (0.82, 1.12),
    "gstreamer_custom": (0.90, 1.07),
    "custom_cpp_cuda_qt": (1.03, 0.92),
}

SCENARIO_FACTORS = {
    "baseline": (1.00, 1.00),
    "stream_scaling": (0.93, 1.10),
    "complex_pipeline": (0.76, 1.45),
    "dynamic_workload": (0.88, 1.25),
    "heterogeneous_distribution": (0.96, 1.03),
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Synthetic workload generator for experiment pipeline")
    parser.add_argument("--system", required=True)
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--duration", type=int, required=True)
    parser.add_argument("--streams", type=int, required=True)
    parser.add_argument("--min-objects", type=int, default=0)
    parser.add_argument("--max-objects", type=int, default=20)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--deadline-ms", type=float, default=3000.0)
    args = parser.parse_args()

    fps_base = 30.0
    latency_base_ms = 140.0

    sys_fps, sys_lat = SYSTEM_FACTORS.get(args.system, (0.90, 1.10))
    sc_fps, sc_lat = SCENARIO_FACTORS.get(args.scenario, (0.90, 1.10))

    output = args.output
    output.parent.mkdir(parents=True, exist_ok=True)

    total_frames = int(args.duration * fps_base * args.streams)
    rng = random.Random(14700)

    with output.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "timestamp_ms",
            "frame_id",
            "stream_id",
            "objects",
            "latency_ms",
            "fps_instant",
            "slo_violation",
        ])

        start_ms = int(time.time() * 1000)
        for frame_id in range(total_frames):
            stream_id = frame_id % args.streams
            objects = rng.randint(args.min_objects, args.max_objects)

            load_factor = 1.0 + objects / max(1.0, args.max_objects * 1.6)
            jitter = rng.uniform(0.92, 1.08)

            fps = fps_base * sys_fps * sc_fps / load_factor
            fps = max(3.0, min(35.0, fps * jitter))

            latency = latency_base_ms * sys_lat * sc_lat * load_factor * rng.uniform(0.94, 1.11)
            if args.scenario == "dynamic_workload" and rng.random() < 0.03:
                latency *= rng.uniform(2.0, 5.0)

            ts = start_ms + int((frame_id / max(1.0, fps_base * args.streams)) * 1000)
            slo = 1 if latency > args.deadline_ms else 0
            writer.writerow([
                ts,
                frame_id,
                stream_id,
                objects,
                round(latency, 3),
                round(fps, 3),
                slo,
            ])


if __name__ == "__main__":
    main()
