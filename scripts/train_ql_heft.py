#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import random
from pathlib import Path


def train(seed: int, episodes: int) -> dict[str, float | int | str]:
    rng = random.Random(seed)
    cpu_weight = 1.0
    gpu_weight = 0.85
    heavy_bonus = 1.75
    threshold = 32
    for _ in range(max(1, episodes)):
        objects = rng.randint(0, 90)
        cpu_backlog = rng.randint(0, 24)
        gpu_backlog = rng.randint(0, 24)
        target_gpu = objects >= threshold or gpu_backlog * gpu_weight <= cpu_backlog * cpu_weight
        reward = (objects / 90.0) if target_gpu else ((90 - objects) / 90.0)
        gpu_weight = max(0.5, min(1.5, gpu_weight - (reward - 0.5) * 0.0005))
        cpu_weight = max(0.5, min(1.5, cpu_weight + (reward - 0.5) * 0.0002))
        heavy_bonus = max(0.5, min(3.0, heavy_bonus + (reward - 0.5) * 0.0003))
    return {
        "schema_version": 1,
        "policy": "ql_heft_frozen",
        "seed": seed,
        "cpu_queue_weight": cpu_weight,
        "gpu_queue_weight": gpu_weight,
        "heavy_object_threshold": threshold,
        "heavy_gpu_bonus": heavy_bonus,
    }


def render(policy: dict[str, float | int | str]) -> str:
    lines: list[str] = []
    for key, value in policy.items():
        if isinstance(value, float):
            lines.append(f"{key}={value:.6f}")
        else:
            lines.append(f"{key}={value}")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Train and freeze the reproducible QL-HEFT policy artifact")
    parser.add_argument("--seed", type=int, default=14700)
    parser.add_argument("--episodes", type=int, default=10000)
    parser.add_argument("--output", type=Path, default=Path("policies/ql_heft_frozen.policy"))
    args = parser.parse_args()

    payload = render(train(args.seed, args.episodes))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(payload, encoding="utf-8")
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    args.output.with_suffix(args.output.suffix + ".sha256").write_text(f"{digest}  {args.output.name}\n", encoding="utf-8")
    print(f"wrote {args.output} sha256={digest}")


if __name__ == "__main__":
    main()
