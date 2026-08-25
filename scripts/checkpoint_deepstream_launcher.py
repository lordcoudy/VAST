#!/usr/bin/env python3
"""Build and launch topology-exact DeepStream checkpoint worker processes.

The existing checkpoint coordinator remains the sole owner of source/admission,
event, lifecycle, and policy socketpairs.  This adapter contributes one
``WorkerLaunchSpec`` per physical DeepStream process: 24 independent baseline
workers or six shared decode/tee workers.  A manifest command is available in
the runtime image; launch is invoked by the host coordinator API.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable, Mapping, Sequence


INDEPENDENT_PROCESSES = "independent_processes"
SHARED_VIDEO_DAG = "shared_video_dag"
ANALYTICS_BRANCHES = (
    "plate_number",
    "vehicle_type",
    "damage",
    "foreign_object",
)
DEFAULT_RUNTIME_EXECUTABLE = "/usr/local/bin/vast_deepstream_checkpoint_runtime"
DEFAULT_CALLBACK_FACTORY = "checkpoint_deepstream_protocol_adapter:create_callbacks"
ADAPTER_CONFIG_ENV = "VAST_DEEPSTREAM_ADAPTER_CONFIG"


class DeepStreamLauncherError(RuntimeError):
    """A launch plan could not prove the frozen physical process topology."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DeepStreamLauncherError(message)


def _absolute_posix_text(value: Path | str, *, label: str) -> str:
    """Return a canonical container path independent of the planning host OS."""

    text = value.as_posix() if isinstance(value, Path) else str(value)
    parsed = PurePosixPath(text)
    _require(
        parsed.is_absolute()
        and not text.startswith("//")
        and "\\" not in text
        and ".." not in parsed.parts
        and parsed.as_posix() == text
        and all(ord(character) >= 0x20 for character in text)
        and len(text.encode("utf-8")) < 4096,
        f"{label} must be a canonical absolute POSIX path",
    )
    return text


def _gstreamer_registry_path(run_id: str, process_id: str) -> str:
    identity = f"{run_id}\0{process_id}".encode("utf-8")
    digest = hashlib.sha256(identity).hexdigest()
    return f"/tmp/vast-deepstream-gst-registry-{digest}.bin"


@dataclass(frozen=True)
class DeepStreamWorkerLaunchSpec:
    worker_id: str
    stream_id: int
    branch_id: str | None
    command: tuple[str, ...]
    environment: dict[str, str] = field(default_factory=dict)
    native_event_source: bool = True
    inherited_fds: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        _require(
            type(self.inherited_fds) is tuple
            and len(self.inherited_fds) == len(set(self.inherited_fds))
            and all(type(fd) is int and fd > 2 for fd in self.inherited_fds),
            "DeepStream inherited FD set is invalid",
        )


def _source_by_stream(plan: Mapping[str, Any]) -> dict[int, dict[str, str]]:
    result: dict[int, dict[str, str]] = {}
    for source in plan.get("sources") or ():
        _require(isinstance(source, Mapping), "DeepStream plan source is not a mapping")
        stream_id = int(source["stream_id"])
        _require(stream_id not in result, "DeepStream plan has duplicate source streams")
        result[stream_id] = {
            "source_sha256": str(source["source_sha256"]),
            "source_codec": str(source["source_codec"]),
            "source_duration_ns": str(source["source_duration_ns"]),
        }
    return result


def build_deepstream_worker_specs(
    plan: Mapping[str, Any],
    *,
    run_id: str,
    arm_id: str,
    runtime_executable: str = DEFAULT_RUNTIME_EXECUTABLE,
    callback_factory: str = DEFAULT_CALLBACK_FACTORY,
    adapter_config_path: str,
    output_root: Path | None = None,
    inherited_fds: tuple[int, ...] = (),
) -> tuple[DeepStreamWorkerLaunchSpec, ...]:
    """Map a validated DeepStream arm plan to exactly 24 or six OS processes."""

    _require(str(plan.get("system")) == "deepstream", "launcher requires a DeepStream plan")
    topology = str(plan.get("topology_kind"))
    _require(topology in {INDEPENDENT_PROCESSES, SHARED_VIDEO_DAG}, "DeepStream topology is invalid")
    codec = str(plan.get("codec"))
    _require(codec in {"h264", "h265"}, "DeepStream codec is invalid")
    _require(str(run_id).strip() != "" and str(arm_id).strip() != "", "DeepStream run/arm ID is empty")
    _require(runtime_executable == DEFAULT_RUNTIME_EXECUTABLE, "DeepStream runtime executable drifted")
    _require(
        type(inherited_fds) is tuple
        and len(inherited_fds) == len(set(inherited_fds))
        and all(type(fd) is int and fd > 2 for fd in inherited_fds),
        "DeepStream inherited FD set is invalid",
    )
    output_root_posix: str | None = None
    if output_root is not None:
        output_root_posix = _absolute_posix_text(
            output_root,
            label="DeepStream output root",
        )
        _require(not output_root.is_symlink(), "DeepStream output root must not be a symlink")
    _require(":" in callback_factory, "DeepStream callback factory must be module:function")
    _require(
        adapter_config_path.startswith("/")
        and all(ord(character) >= 0x20 for character in adapter_config_path)
        and len(adapter_config_path.encode("utf-8")) < 4096,
        "DeepStream adapter config path must be an absolute POSIX path",
    )
    required_branches = tuple(str(value) for value in plan.get("required_branches") or ())
    _require(required_branches == ANALYTICS_BRANCHES, "DeepStream frozen branch order drifted")
    _require(int(plan.get("stream_count", -1)) == 6, "DeepStream launcher requires six streams")
    source_map = _source_by_stream(plan)
    raw_processes = plan.get("processes")
    _require(isinstance(raw_processes, list), "DeepStream plan process list is missing")
    specs: list[DeepStreamWorkerLaunchSpec] = []
    for raw in raw_processes:
        _require(isinstance(raw, Mapping), "DeepStream process is not a mapping")
        worker_id = str(raw.get("process_id", "")).strip()
        stream_id = int(raw.get("stream_id", -1))
        branches = tuple(str(value) for value in raw.get("branches") or ())
        _require(worker_id != "" and 0 <= stream_id < 6, "DeepStream worker identity is invalid")
        source = source_map.get(stream_id, {})
        source_sha256 = str(raw.get("source_sha256") or source.get("source_sha256") or "")
        source_codec = str(raw.get("source_codec") or source.get("source_codec") or codec)
        source_duration_ns = str(
            raw.get("source_duration_ns") or source.get("source_duration_ns") or ""
        )
        _require(source_codec == codec, f"{worker_id}: source codec differs from arm codec")
        _require(
            source_duration_ns.isdigit() and int(source_duration_ns) > 0,
            f"{worker_id}: scaled source duration is missing",
        )
        branch_id: str | None
        if topology == INDEPENDENT_PROCESSES:
            branch_id = str(raw.get("branch", ""))
            _require(branch_id in ANALYTICS_BRANCHES, f"{worker_id}: baseline branch is invalid")
            _require(branches == (branch_id,), f"{worker_id}: baseline process is not branch-isolated")
        else:
            branch_id = None
            _require(branches == ANALYTICS_BRANCHES, f"{worker_id}: shared graph lacks four routes")
        branch_csv = ",".join(branches)
        command = (
            runtime_executable,
            "run",
            "--codec",
            codec,
            "--topology-kind",
            topology,
            "--stream-id",
            str(stream_id),
            "--branches",
            branch_csv,
            "--arm-id",
            str(arm_id),
            "--callback-factory",
            callback_factory,
        )
        if output_root_posix is not None:
            command += (
                "--output-dir",
                (PurePosixPath(output_root_posix) / "workers" / worker_id).as_posix(),
            )
        specs.append(
            DeepStreamWorkerLaunchSpec(
                worker_id=worker_id,
                stream_id=stream_id,
                branch_id=branch_id,
                command=command,
                environment={
                    "VAST_DEEPSTREAM_BRANCHES": branch_csv,
                    "VAST_DEEPSTREAM_CODEC": codec,
                    "VAST_DEEPSTREAM_DATASET_ID": str(plan.get("dataset", "")),
                    "VAST_DEEPSTREAM_SOURCE_SHA256": source_sha256,
                    "VAST_DEEPSTREAM_SOURCE_DURATION_NS": source_duration_ns,
                    "VAST_DEEPSTREAM_POLICY": str(plan.get("policy", "")),
                    "VAST_DEEPSTREAM_DEADLINE_MS": str(float(plan.get("deadline_ms", 0.0))),
                    "VAST_DEEPSTREAM_CALLBACK_FACTORY": callback_factory,
                    ADAPTER_CONFIG_ENV: adapter_config_path,
                    "VAST_DEEPSTREAM_CLAIM_STATUS": "native_sdk_runtime_requires_external_acceptance",
                    "GST_REGISTRY": _gstreamer_registry_path(run_id, worker_id),
                    "GST_REGISTRY_UPDATE": "no",
                    "GST_REGISTRY_FORK": "no",
                },
                native_event_source=True,
                inherited_fds=inherited_fds,
            )
        )

    expected_count = 24 if topology == INDEPENDENT_PROCESSES else 6
    _require(len(specs) == expected_count, f"DeepStream {topology} requires exactly {expected_count} processes")
    _require(len({spec.worker_id for spec in specs}) == expected_count, "DeepStream worker IDs are not unique")
    _require({spec.stream_id for spec in specs} == set(range(6)), "DeepStream processes do not cover six streams")
    if topology == INDEPENDENT_PROCESSES:
        for stream_id in range(6):
            _require(
                {str(spec.branch_id) for spec in specs if spec.stream_id == stream_id}
                == set(ANALYTICS_BRANCHES),
                f"DeepStream baseline stream {stream_id} lacks four physical branch processes",
            )
    return tuple(specs)


def build_deepstream_source_specs(
    plan: Mapping[str, Any],
    *,
    source_binary: Path,
    project_root: Path,
    run_id: str,
    pinned_source_paths_by_sha256: Mapping[str, str] | None = None,
    inherited_fds: tuple[int, ...] = (),
) -> tuple[Any, ...]:
    """Materialize the six exact common-source coordinator processes."""

    from checkpoint_runtime import SourceLaunchSpec

    _require(str(plan.get("system")) == "deepstream", "launcher requires a DeepStream plan")
    root = project_root.resolve()
    _require(root.is_dir() and not root.is_symlink(), "DeepStream project root is unsafe")
    source_binary_posix = _absolute_posix_text(
        source_binary,
        label="DeepStream source binary",
    )
    _require(
        type(inherited_fds) is tuple
        and len(inherited_fds) == len(set(inherited_fds))
        and all(type(fd) is int and fd > 2 for fd in inherited_fds),
        "DeepStream inherited FD set is invalid",
    )
    raw = plan.get("source_coordinators")
    _require(isinstance(raw, list) and len(raw) == 6, "DeepStream requires six source coordinators")
    specs = []
    for expected_stream_id, value in enumerate(raw):
        _require(isinstance(value, Mapping), "DeepStream source coordinator is invalid")
        stream_id = int(value.get("stream_id", -1))
        _require(stream_id == expected_stream_id, "DeepStream source coordinator order drifted")
        source_sha256 = str(value.get("source_sha256", ""))
        if pinned_source_paths_by_sha256 is None:
            relative = Path(str(value.get("input_path", "")))
            _require(not relative.is_absolute() and ".." not in relative.parts, "DeepStream source path is unsafe")
            lexical = Path(root, relative)
            resolved = lexical.resolve()
            try:
                resolved.relative_to(root)
            except ValueError as exc:
                raise DeepStreamLauncherError("DeepStream source path escapes project root") from exc
            _require(
                lexical == resolved and resolved.is_file() and not resolved.is_symlink(),
                "DeepStream source is missing, a symlink, or an alias",
            )
        else:
            _require(
                source_sha256 in pinned_source_paths_by_sha256,
                "DeepStream source has no SHA-bound publication path",
            )
            resolved = Path(pinned_source_paths_by_sha256[source_sha256])
            _require(
                resolved.is_absolute() and resolved.is_file()
                and not resolved.is_symlink()
                and (os.name == "nt" or resolved.resolve() == resolved),
                "DeepStream SHA-bound publication source is unsafe",
            )
            digest = hashlib.sha256()
            with resolved.open("rb") as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(chunk)
            _require(
                digest.hexdigest() == source_sha256,
                "DeepStream SHA-bound publication source identity drifted",
            )
        process_id = str(value.get("process_id", ""))
        duration = str(value.get("source_duration_ns", ""))
        scale = str(value.get("playback_timestamp_scale", ""))
        _require(duration.isdigit() and int(duration) > 0, "DeepStream source duration is invalid")
        _require(scale == "600", "DeepStream source timestamp scale drifted")
        command = (
            source_binary_posix,
            "--source-path",
            str(resolved),
            "--dataset-id",
            str(plan["dataset"]),
            "--source-sha256",
            source_sha256,
            "--checkpoint-container",
            str(value["source_container"]),
            "--checkpoint-codec",
            str(value["source_codec"]),
            "--source-duration-ns",
            duration,
            "--playback-timestamp-scale",
            scale,
            "--source-replay",
            "continuous",
            "--logical-stream-id",
            str(stream_id),
        )
        specs.append(
            SourceLaunchSpec(
                source_process_id=process_id,
                stream_id=stream_id,
                dataset_id=str(plan["dataset"]),
                source_sha256=source_sha256,
                command=command,
                environment={
                    "GST_REGISTRY": _gstreamer_registry_path(run_id, process_id),
                    "GST_REGISTRY_UPDATE": "no",
                    "GST_REGISTRY_FORK": "no",
                    "VAST_CHECKPOINT_SOURCE_CONTAINER": str(value["source_container"]),
                    "VAST_CHECKPOINT_SOURCE_CODEC": str(value["source_codec"]),
                    "VAST_CHECKPOINT_SOURCE_DURATION_NS": duration,
                    "VAST_CHECKPOINT_PLAYBACK_TIMESTAMP_SCALE": scale,
                    "VAST_CHECKPOINT_SOURCE_REPLAY": "continuous",
                    "VAST_CHECKPOINT_ADMISSION_MODE": "native_common_source_coordinator",
                },
                native_source=True,
                inherited_fds=inherited_fds,
            )
        )
    _require(len({spec.source_process_id for spec in specs}) == 6, "DeepStream source IDs are duplicated")
    return tuple(specs)


def launch_deepstream_worker_processes(
    *,
    plan: Mapping[str, Any],
    run_id: str,
    arm_id: str,
    adapter_config_path: str,
    source_specs: Iterable[Any],
    policy_socket_handler: Callable[[str, Any], None],
    warmup_s: float,
    measurement_s: float,
    timeout_s: float,
    drain_timeout_s: float = 10.0,
    ready_timeout_s: float = 300.0,
    runner: Callable[..., Any] | None = None,
) -> Any:
    """Launch via the established coordinator that owns all inherited FDs."""

    _require(warmup_s >= 0 and measurement_s > 0, "DeepStream lifecycle window is invalid")
    _require(drain_timeout_s > 0 and ready_timeout_s > 0, "DeepStream lifecycle timeout is invalid")
    _require(timeout_s > warmup_s + measurement_s, "DeepStream timeout does not cover the measurement window")
    _require(callable(policy_socket_handler), "DeepStream native policy handler is missing")
    specs = build_deepstream_worker_specs(
        plan,
        run_id=run_id,
        arm_id=arm_id,
        adapter_config_path=adapter_config_path,
    )
    if runner is None:
        from checkpoint_runtime import run_worker_processes as runner
    return runner(
        run_id=run_id,
        topology_kind=str(plan["topology_kind"]),
        branches=ANALYTICS_BRANCHES,
        specs=specs,
        source_specs=tuple(source_specs),
        timeout_s=timeout_s,
        ready_timeout_s=ready_timeout_s,
        synchronized_lifecycle=True,
        warmup_s=warmup_s,
        measurement_s=measurement_s,
        drain_timeout_s=drain_timeout_s,
        require_decoder_placement_verification=True,
        policy_socket_handler=policy_socket_handler,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="DeepStream physical worker launcher")
    parser.add_argument("manifest", nargs="?")
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--arm-id", required=True)
    parser.add_argument("--adapter-config", required=True)
    args = parser.parse_args(argv)
    _require(args.manifest in {None, "manifest"}, "only the non-mutating manifest command is supported")
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    specs = build_deepstream_worker_specs(
        plan,
        run_id=args.run_id,
        arm_id=args.arm_id,
        adapter_config_path=args.adapter_config,
    )
    output = {
        "schema_version": 1,
        "artifact_kind": "deepstream_checkpoint_worker_launch_manifest",
        "claim_status": "launch_manifest_not_measurement",
        "topology_kind": plan["topology_kind"],
        "physical_process_count": len(specs),
        "specs": [asdict(value) for value in specs],
        "accepted_measurement_evidence_emitted": False,
        "publication_ready": False,
    }
    print(json.dumps(output, sort_keys=True, separators=(",", ":"), allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
