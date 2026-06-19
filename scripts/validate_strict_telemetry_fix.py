#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Sequence

import yaml


class StrictValidationError(RuntimeError):
    pass


DEFAULT_SYSTEMS = [
    "deepstream",
    "savant",
    "openvino_gva",
    "gstreamer_custom",
    "custom_cpp_cuda_qt",
]
DEFAULT_SCENARIO = "canonical_heterogeneous"
DEFAULT_DATASET = "mot17_uadetrac_public"
DEFAULT_OUTPUT_ROOT = Path("runs/strict_validation")


def load_config(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as src:
        return yaml.safe_load(src) or {}


def is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def resolve_project_path(project_root: Path, path: Path) -> Path:
    return (path if path.is_absolute() else project_root / path).resolve()


def guard_repo_child(path: Path, project_root: Path) -> Path:
    resolved = path.resolve()
    root = project_root.resolve()
    if resolved == root or not is_relative_to(resolved, root):
        raise StrictValidationError(f"refusing to operate outside repository: {resolved}")
    return resolved


def runtime_artifact_paths(project_root: Path, output_root: Path) -> list[Path]:
    project_root = project_root.resolve()
    return [
        project_root / ".cache" / "savant",
        resolve_project_path(project_root, output_root),
    ]


def docker_clear_directory(path: Path, *, image: str | None = None) -> bool:
    if shutil.which("docker") is None:
        return False
    cleanup_image = image or os.environ.get(
        "STRICT_VALIDATION_CLEANUP_IMAGE",
        os.environ.get("SAVANT_IMAGE", "ghcr.io/insight-platform/savant-deepstream:0.5.17-7.0"),
    )
    command = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{path}:/target",
        "--entrypoint",
        "bash",
        cleanup_image,
        "-lc",
        "shopt -s dotglob nullglob; rm -rf /target/*",
    ]
    print(f"[strict-validation] root cleanup fallback: {shlex.join(command)}")
    completed = subprocess.run(command, check=False)
    return int(completed.returncode) == 0


def remove_tree(path: Path) -> None:
    try:
        shutil.rmtree(path)
        return
    except PermissionError:
        if not docker_clear_directory(path):
            raise
    if path.exists():
        shutil.rmtree(path)


def clear_runtime_artifacts(project_root: Path, output_root: Path, *, dry_run: bool = False) -> None:
    for path in runtime_artifact_paths(project_root, output_root):
        guarded = guard_repo_child(path, project_root)
        if dry_run:
            print(f"[strict-validation] would remove {guarded}")
            continue
        if guarded.exists():
            remove_tree(guarded)
            print(f"[strict-validation] removed {guarded}")
        else:
            print(f"[strict-validation] already absent {guarded}")


def expand_policies(config: dict, requested: Sequence[str]) -> list[str]:
    configured = [str(policy) for policy in config.get("benchmark", {}).get("scheduler_policies", [])]
    if not configured:
        raise StrictValidationError("configs/experiments.yaml has no benchmark.scheduler_policies")
    if not requested or "all" in requested:
        return configured
    unknown = [policy for policy in requested if policy not in configured]
    if unknown:
        raise StrictValidationError(f"unknown scheduler policies: {', '.join(unknown)}; expected: {', '.join(configured)}")
    return list(requested)


def validation_environment(project_root: Path, base: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ if base is None else base)
    env.setdefault("SAVANT_LOCAL_PREWARM", "1")
    env.setdefault("SAVANT_LOCAL_STARTUP_WAIT_S", "300")
    env.setdefault("SAVANT_LOCAL_SHUTDOWN_GRACE_S", "30")
    return env


def python_executable() -> str:
    return sys.executable or "python3"


def prepare_dataset_command(args: argparse.Namespace) -> list[str]:
    return [
        python_executable(),
        "scripts/prepare_benchmark_dataset.py",
        "--manifest",
        str(args.manifest),
        "--dataset",
        str(args.dataset),
        "--source-root",
        str(args.source_root),
        "--output-dir",
        str(args.dataset_output_dir),
    ]


def check_dataset_command(args: argparse.Namespace) -> list[str]:
    return [
        python_executable(),
        "scripts/check_dataset.py",
        "--manifest",
        str(args.manifest),
        "--dataset",
        str(args.dataset),
        "--mode",
        "benchmark",
    ]


def build_prerequisite_commands() -> list[list[str]]:
    return [
        ["bash", "scripts/prepare_assets.sh"],
        ["cmake", "-S", ".", "-B", "build/cmake"],
        ["cmake", "--build", "build/cmake", "--target", "vast_native_gst_probe"],
        ["cmake", "--build", "build/cmake", "--target", "gstadaptivescheduler"],
        ["cmake", "--build", "build/cmake", "--target", "adaptive_scheduler_app"],
        ["bash", "scripts/build_native_probe_images.sh"],
    ]


def completed_systems(output_root: Path, policy: str, scenario: str, systems: Sequence[str], repeats: int) -> set[str]:
    policy_root = output_root / policy
    completed: set[str] = set()
    for system in systems:
        for timestamp_dir in sorted(policy_root.glob("*")):
            streams_dir = timestamp_dir / scenario / "streams_6" / str(system)
            if not streams_dir.is_dir():
                continue
            if all((streams_dir / f"rep_{rep:02d}" / "run_metadata.json").exists() for rep in range(1, repeats + 1)):
                completed.add(str(system))
                break
    return completed


def run_experiments_command(args: argparse.Namespace, policy: str, systems: Sequence[str] | None = None) -> list[str]:
    selected_systems = [str(system) for system in (systems or args.systems)]
    command = [
        python_executable(),
        "scripts/run_experiments.py",
        "--config",
        str(args.config),
        "--mode",
        "benchmark",
        "--dataset",
        str(args.dataset),
        "--run-kind",
        str(args.run_kind),
        "--systems",
        *selected_systems,
        "--scenarios",
        str(args.scenario),
        "--policy",
        policy,
        "--output-root",
        str(args.output_root / policy),
    ]
    if args.repeats is not None:
        command.extend(["--repeats", str(args.repeats)])
    if args.warmup is not None:
        command.extend(["--warmup", str(args.warmup)])
    if args.measurement is not None:
        command.extend(["--measurement", str(args.measurement)])
    if args.dry_run_plan:
        command.append("--dry-run-plan")
    return command


def run_command(command: Sequence[str], *, cwd: Path, env: dict[str, str], dry_run: bool = False) -> None:
    printable = shlex.join([str(part) for part in command])
    print(f"[strict-validation] command: {printable}")
    if dry_run:
        return
    completed = subprocess.run(list(command), cwd=cwd, env=env, check=False)
    if int(completed.returncode) != 0:
        raise StrictValidationError(f"command failed with exit code {completed.returncode}: {printable}")


def run_validation(args: argparse.Namespace) -> None:
    project_root = args.project_root.resolve()
    config_path = resolve_project_path(project_root, args.config)
    output_root = resolve_project_path(project_root, args.output_root)
    config = load_config(config_path)
    policies = expand_policies(config, args.policies)
    env = validation_environment(project_root)

    if args.clear_runtime_artifacts:
        clear_runtime_artifacts(project_root, output_root, dry_run=args.dry_run_plan)

    run_command(prepare_dataset_command(args), cwd=project_root, env=env, dry_run=args.dry_run_plan)
    run_command(check_dataset_command(args), cwd=project_root, env=env, dry_run=args.dry_run_plan)

    if not args.skip_build:
        for command in build_prerequisite_commands():
            run_command(command, cwd=project_root, env=env, dry_run=args.dry_run_plan)

    requested_repeats = int(args.repeats if args.repeats is not None else config.get("protocol", {}).get("repeats", 1))
    for policy in policies:
        systems = [str(system) for system in args.systems]
        if args.resume:
            done = completed_systems(output_root, policy, args.scenario, systems, requested_repeats)
            if done:
                print(f"[strict-validation] policy={policy} completed systems: {', '.join(sorted(done))}")
            systems = [system for system in systems if system not in done]
        if not systems:
            print(f"[strict-validation] policy={policy} already complete")
            continue
        run_command(run_experiments_command(args, policy, systems), cwd=project_root, env=env, dry_run=args.dry_run_plan)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare assets, clear runtime artifacts, and run strict local VAST validation")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--config", type=Path, default=Path("configs/experiments.yaml"))
    parser.add_argument("--manifest", type=Path, default=Path("configs/datasets.yaml"))
    parser.add_argument("--dataset", default=DEFAULT_DATASET)
    parser.add_argument("--source-root", type=Path, default=Path("data/videos"))
    parser.add_argument("--dataset-output-dir", type=Path, default=Path("data/benchmark"))
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--scenario", default=DEFAULT_SCENARIO)
    parser.add_argument("--run-kind", choices=["heterogeneous", "local", "auto"], default="heterogeneous")
    parser.add_argument("--systems", nargs="+", default=DEFAULT_SYSTEMS)
    parser.add_argument("--policies", nargs="+", default=["all"])
    parser.add_argument("--repeats", type=int, default=None)
    parser.add_argument("--warmup", type=int, default=None)
    parser.add_argument("--measurement", type=int, default=None)
    parser.add_argument("--clear-runtime-artifacts", action="store_true")
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--dry-run-plan", action="store_true")
    parser.add_argument("--resume", action="store_true", help="Skip systems with all requested repeats already completed under the policy output root")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    run_validation(args)
    print("[strict-validation] complete")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except StrictValidationError as exc:
        print(f"[strict-validation][error] {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
