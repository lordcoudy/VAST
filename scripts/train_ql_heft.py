#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import random
from pathlib import Path


def project_pair_mean_one(
    cpu_weight: float,
    gpu_weight: float,
    lower_bound: float = 0.5,
    upper_bound: float = 1.5,
) -> tuple[float, float]:
    if lower_bound <= 0 or upper_bound < lower_bound or 2 * lower_bound > 2 or 2 * upper_bound < 2:
        raise ValueError("weight bounds do not intersect the mean-one plane")
    lo = min(cpu_weight - upper_bound, gpu_weight - upper_bound)
    hi = max(cpu_weight - lower_bound, gpu_weight - lower_bound)
    for _ in range(200):
        shift = (lo + hi) / 2
        total = max(lower_bound, min(upper_bound, cpu_weight - shift)) + max(
            lower_bound, min(upper_bound, gpu_weight - shift)
        )
        if total > 2:
            lo = shift
        else:
            hi = shift
    shift = (lo + hi) / 2
    return (
        max(lower_bound, min(upper_bound, cpu_weight - shift)),
        max(lower_bound, min(upper_bound, gpu_weight - shift)),
    )


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
    cpu_weight, gpu_weight = project_pair_mean_one(cpu_weight, gpu_weight)
    return {
        "schema_version": 2,
        "policy": "ql_heft_frozen",
        "seed": seed,
        "cpu_queue_weight": cpu_weight,
        "gpu_queue_weight": gpu_weight,
        "heavy_object_threshold": threshold,
        "heavy_gpu_bonus": heavy_bonus,
        "weight_lower_bound": 0.5,
        "weight_upper_bound": 1.5,
        "projection_rule": "euclidean_box_mean_one_v1",
        "feedback_lag_limit": 8,
        "feedback_cooldown_events": 2,
        "variation_budget": 0.25,
        "feedback_update_rule": "simplified_gpu_queue_terminal_signal_v1",
        "feedback_penalty_step": 0.002,
        "feedback_reward_step": 0.0002,
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
    parser = argparse.ArgumentParser(
        description="Generate and freeze the reproducible adaptive-weight policy artifact"
    )
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
