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
DEFAULT_SCENARIO = "all"
DEFAULT_DATASET = "kpp_real_h264"
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



def requested_scenarios(config: dict, scenario: str) -> list[str]:
    scenarios = config.get("scenarios") or {}
    if not scenarios:
        return [scenario]
    if scenario == "all":
        return [str(name) for name in scenarios]
    if scenario not in scenarios:
        raise StrictValidationError(f"unknown scenario '{scenario}'")
    return [scenario]


def scenario_variant_paths(config: dict, scenario: str) -> list[tuple[str, ...]]:
    raw = (config.get("scenarios") or {}).get(scenario) or {}
    workload = raw.get("workload") or {}
    variants = workload.get("variants") or [None]
    if "stream_range" in workload:
        start, end = workload["stream_range"]
        streams = range(int(start), int(end) + 1)
    else:
        streams = [int(workload.get("streams", 6))]

    paths: list[tuple[str, ...]] = []
    for variant in variants:
        variant_name = str(variant.get("name", "variant")) if isinstance(variant, dict) else ""
        for stream_count in streams:
            parts = [scenario]
            if variant_name:
                parts.append(f"variant_{variant_name}")
            parts.append(f"streams_{stream_count}")
            paths.append(tuple(parts))
    return paths


def _metadata_matches_suffix(policy_root: Path, suffix: tuple[str, ...], repeat: int) -> bool:
    expected = (*suffix, f"rep_{repeat:02d}")
    for metadata in policy_root.rglob("run_metadata.json"):
        parts = metadata.parent.parts
        if len(parts) >= len(expected) and tuple(parts[-len(expected) :]) == expected:
            return True
    return False


def scenario_completed(
    output_root: Path,
    policy: str,
    config: dict,
    scenario: str,
    system: str,
    repeats: int,
) -> bool:
    policy_root = output_root / policy
    for prefix in scenario_variant_paths(config, scenario):
        suffix = (*prefix, system)
        if not all(_metadata_matches_suffix(policy_root, suffix, rep) for rep in range(1, repeats + 1)):
            return False
    return True


def scenario_groups(config: dict, scenario: str, run_kind: str) -> list[tuple[str, list[str]]]:
    names = requested_scenarios(config, scenario)
    raw_scenarios = config.get("scenarios") or {}
    local = [name for name in names if not bool((raw_scenarios.get(name, {}).get("distributed") or {}).get("enabled"))]
    distributed = [name for name in names if name not in local]
    if run_kind in {"local", "heterogeneous"}:
        return [("heterogeneous", local)] if local else []
    if run_kind == "single-server-distributed":
        return [("single-server-distributed", distributed)] if distributed else []
    if run_kind == "distributed":
        return [("distributed", distributed)] if distributed else []
    if run_kind == "auto":
        groups: list[tuple[str, list[str]]] = []
        if local:
            groups.append(("heterogeneous", local))
        if distributed:
            groups.append(("single-server-distributed", distributed))
        return groups
    raise StrictValidationError(f"unsupported run kind '{run_kind}'")


def run_experiments_command(
    args: argparse.Namespace,
    policy: str,
    systems: Sequence[str] | None = None,
    *,
    scenarios: Sequence[str] | None = None,
    run_kind: str | None = None,
    resume_run_root: Path | None = None,
) -> list[str]:
    selected_systems = [str(system) for system in (systems or args.systems)]
    selected_scenarios = [str(name) for name in (scenarios or [args.scenario])]
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
        str(run_kind or args.run_kind),
        "--systems",
        *selected_systems,
        "--scenarios",
        *selected_scenarios,
        "--policy",
        policy,
        "--output-root",
        str(args.output_root / policy),
    ]
    if resume_run_root is not None:
        command.extend(["--resume-run-root", str(resume_run_root)])
    if args.repeats is not None:
        command.extend(["--repeats", str(args.repeats)])
    if args.warmup is not None:
        command.extend(["--warmup", str(args.warmup)])
    if args.measurement is not None:
        command.extend(["--measurement", str(args.measurement)])
    if args.dry_run_plan:
        command.append("--dry-run-plan")
    if getattr(args, "continue_on_error", False):
        command.append("--continue-on-error")
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
        for selected_run_kind, scenarios in scenario_groups(config, args.scenario, args.run_kind):
            for system in [str(system) for system in args.systems]:
                pending = list(scenarios)
                if args.resume:
                    pending = [
                        scenario
                        for scenario in scenarios
                        if not scenario_completed(output_root, policy, config, scenario, system, requested_repeats)
                    ]
                    completed = sorted(set(scenarios) - set(pending))
                    if completed:
                        print(
                            f"[strict-validation] policy={policy} system={system} "
                            f"completed scenarios: {', '.join(completed)}"
                        )
                if not pending:
                    print(
                        f"[strict-validation] policy={policy} system={system} "
                        f"run_kind={selected_run_kind} already complete"
                    )
                    continue
                resume_root = output_root / policy / "one_server_all" / selected_run_kind / system
                if not args.dry_run_plan:
                    resume_root.mkdir(parents=True, exist_ok=True)
                run_command(
                    run_experiments_command(
                        args,
                        policy,
                        [system],
                        scenarios=pending,
                        run_kind=selected_run_kind,
                        resume_run_root=resume_root,
                    ),
                    cwd=project_root,
                    env=env,
                    dry_run=args.dry_run_plan,
                )

def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare assets and run resumable strict VAST validation")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--config", type=Path, default=Path("configs/experiments.yaml"))
    parser.add_argument("--manifest", type=Path, default=Path("configs/datasets.yaml"))
    parser.add_argument("--dataset", default=DEFAULT_DATASET)
    parser.add_argument("--source-root", type=Path, default=Path("data/videos"))
    parser.add_argument("--dataset-output-dir", type=Path, default=Path("data/benchmark"))
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--scenario", default=DEFAULT_SCENARIO)
    parser.add_argument(
        "--run-kind",
        choices=["heterogeneous", "local", "auto", "single-server-distributed", "distributed"],
        default="auto",
    )
    parser.add_argument("--systems", nargs="+", default=DEFAULT_SYSTEMS)
    parser.add_argument("--policies", nargs="+", default=["all"])
    parser.add_argument("--repeats", type=int, default=None)
    parser.add_argument("--warmup", type=int, default=None)
    parser.add_argument("--measurement", type=int, default=None)
    parser.add_argument("--clear-runtime-artifacts", action="store_true")
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--dry-run-plan", action="store_true")
    parser.add_argument("--continue-on-error", action="store_true", help="Record failed repetitions in summary.csv and continue the matrix")
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
