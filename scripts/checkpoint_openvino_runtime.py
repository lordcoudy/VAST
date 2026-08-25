#!/usr/bin/env python3
"""OpenVINO-specific checkpoint topology plans and read-only capability preflight.

This module deliberately exposes no measurement command.  It proves what is
present in the candidate image, freezes the intended 24-process baseline and
6-process shared topology, and reports the remaining publication blockers.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from benchmark_contract import ContractError


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SYSTEM = "openvino_gstreamer"
LOGICAL_STREAMS = 6
BRANCHES = (
    "plate_number",
    "vehicle_type",
    "damage",
    "foreign_object",
)
SCENARIOS = {
    "checkpoint_independent_processes_baseline": "independent_processes",
    "checkpoint_video_dag_shared": "shared_video_dag",
}
CODEC_CONTRACTS = {
    "h264": {
        "dataset": "kpp_iss_publication_v3_h264",
        "compressed_caps": "video/x-h264",
        "parser_factory": "h264parse",
    },
    "h265": {
        "dataset": "kpp_iss_publication_v3_h265",
        "compressed_caps": "video/x-h265",
        "parser_factory": "h265parse",
    },
}
ANALYTICS_QUEUE_CONTRACT = {
    "contract_version": 1,
    "factory": "vastanalyticsqueue",
    "scope": "per_branch_waiting_queue_before_verified_detector",
    "max_buffers": 1,
    "overflow_policy": "drop_newest",
    "inflight_detector_buffer_excluded": True,
}
REQUIRED_GSTREAMER_ELEMENTS = (
    "appsrc",
    "h264parse",
    "h265parse",
    "decodebin",
    "videoconvert",
    "tee",
    "vastanalyticsqueue",
    "gvadetect",
    "vastanalyticsterminal",
)
BASE_PUBLICATION_BLOCKERS = (
    "cuda_tensorrt_parity_not_established",
    "checkpoint_protocol_v3_native_routing_not_implemented",
    "checkpoint_resource_v2_not_implemented",
    "checkpoint_policy_calibration_not_accepted",
)
DEPLOYMENT_CONTRACT = {
    "schema_version": 1,
    "artifact_kind": "vast_openvino_checkpoint_deployment_contract",
    "system": SYSTEM,
    "status": "capability_preflight_and_plan_only",
    "topology_runtime_implemented": False,
    "measurement_execution_allowed": False,
    "generic_probe_relabelled": False,
    "scenarios": list(SCENARIOS),
    "codecs": list(CODEC_CONTRACTS),
    "logical_streams": LOGICAL_STREAMS,
    "branches": list(BRANCHES),
    "baseline_worker_processes": LOGICAL_STREAMS * len(BRANCHES),
    "shared_graph_processes": LOGICAL_STREAMS,
    "queued_branches_per_stream": len(BRANCHES),
}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


CommandRunner = Callable[[list[str]], str]


def _canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ContractError(f"OpenVINO checkpoint value is not canonical JSON: {error}") from error


def _json_copy(value: Any) -> Any:
    return json.loads(_canonical_json(value).decode("utf-8"))


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def _with_identity(value: Mapping[str, Any]) -> dict[str, Any]:
    payload = _json_copy(value)
    payload["identity"] = {
        "schema_version": 1,
        "sha256": _sha256_bytes(_canonical_json(payload)),
    }
    return payload


def load_deployment_contract(project_root: Path | str = PROJECT_ROOT) -> dict[str, Any]:
    root = Path(project_root).resolve()
    path = root / "deploy" / "openvino" / "checkpoint" / "contract.json"
    if path.is_symlink() or not path.is_file():
        raise ContractError("OpenVINO checkpoint deployment contract is missing")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ContractError(f"invalid OpenVINO checkpoint deployment contract: {error}") from error
    if type(value) is not dict or _canonical_json(value) != _canonical_json(DEPLOYMENT_CONTRACT):
        raise ContractError("OpenVINO checkpoint deployment contract drifted")
    return _json_copy(value)


def _source_coordinators(codec: str) -> list[dict[str, Any]]:
    return [
        {
            "process_id": f"stream-{stream_id}-source-coordinator",
            "process_kind": "protocol_v3_common_source_coordinator",
            "stream_id": stream_id,
            "codec": codec,
            "delivery": "framed_compressed_access_unit_broadcast",
            "measurement_execution_status": "not_implemented",
        }
        for stream_id in range(LOGICAL_STREAMS)
    ]


def _baseline_workers(codec: str) -> list[dict[str, Any]]:
    workers = []
    for stream_id in range(LOGICAL_STREAMS):
        for branch in BRANCHES:
            workers.append(
                {
                    "process_id": f"stream-{stream_id}-branch-{branch}",
                    "process_kind": "independent_branch_worker",
                    "stream_id": stream_id,
                    "branch_id": branch,
                    "codec": codec,
                    "pipeline_stages": [
                        f"decode_{branch}",
                        f"preprocess_{branch}",
                        branch,
                    ],
                    "analytics_queue": copy.deepcopy(ANALYTICS_QUEUE_CONTRACT),
                    "analytics_factory": "gvadetect",
                    "terminal_factory": "vastanalyticsterminal",
                    "protocol_v3_binding_status": "not_implemented",
                }
            )
    return workers


def _shared_workers(codec: str) -> list[dict[str, Any]]:
    return [
        {
            "process_id": f"stream-{stream_id}-shared-video-dag",
            "process_kind": "shared_video_dag_worker",
            "stream_id": stream_id,
            "codec": codec,
            "shared_prefix": ["decode", "preprocess"],
            "fanout_factory": "tee",
            "branches": [
                {
                    "branch_id": branch,
                    "queue_required": True,
                    "analytics_queue": copy.deepcopy(ANALYTICS_QUEUE_CONTRACT),
                    "analytics_factory": "gvadetect",
                    "terminal_factory": "vastanalyticsterminal",
                }
                for branch in BRANCHES
            ],
            "protocol_v3_binding_status": "not_implemented",
        }
        for stream_id in range(LOGICAL_STREAMS)
    ]


def build_openvino_topology_plan(
    *,
    scenario: str,
    codec: str,
    runtime_image: Mapping[str, Any] | None = None,
    device_inventory_sha256: str = "unbound_capability_plan",
    deployment_contract: Mapping[str, Any] = DEPLOYMENT_CONTRACT,
) -> dict[str, Any]:
    normalized_codec = str(codec).lower().replace("hevc", "h265")
    if normalized_codec not in CODEC_CONTRACTS:
        raise ContractError(f"unsupported OpenVINO checkpoint codec: {codec}")
    if scenario not in SCENARIOS:
        raise ContractError(f"unsupported OpenVINO checkpoint scenario: {scenario}")
    if _canonical_json(deployment_contract) != _canonical_json(DEPLOYMENT_CONTRACT):
        raise ContractError("OpenVINO checkpoint deployment contract drifted")
    topology_kind = SCENARIOS[scenario]
    workers = (
        _baseline_workers(normalized_codec)
        if topology_kind == "independent_processes"
        else _shared_workers(normalized_codec)
    )
    codec_contract = CODEC_CONTRACTS[normalized_codec]
    plan = {
        "schema_version": 1,
        "artifact_kind": "vast_openvino_checkpoint_topology_plan",
        "claim_status": "immutable_capability_plan_not_measurement",
        "system": SYSTEM,
        "scenario": scenario,
        "topology_kind": topology_kind,
        "codec": normalized_codec,
        "dataset": codec_contract["dataset"],
        "logical_streams": LOGICAL_STREAMS,
        "required_branches": list(BRANCHES),
        "queued_branches_per_stream": len(BRANCHES),
        "analytics_queue": copy.deepcopy(ANALYTICS_QUEUE_CONTRACT),
        "decoder": {
            "compressed_caps": codec_contract["compressed_caps"],
            "parser_factory": codec_contract["parser_factory"],
            "decoder_factory": "decodebin",
            "decoder_hardware_binding": "unverified_capability_only",
        },
        "openvino_analytics": {
            "factory": "gvadetect",
            "device_selection": "actual_Core_available_devices_preflight_required",
            "nvidia_gpu_is_openvino_gpu": False,
        },
        "source_coordinators": _source_coordinators(normalized_codec),
        "workers": workers,
        "process_counts": {
            "source_coordinators": LOGICAL_STREAMS,
            "topology_workers": len(workers),
            "analytics_branch_instances": LOGICAL_STREAMS * len(BRANCHES),
            "decoder_instances": (
                LOGICAL_STREAMS * len(BRANCHES)
                if topology_kind == "independent_processes"
                else LOGICAL_STREAMS
            ),
        },
        "publication_dependencies": {
            "cuda_tensorrt_parity": "not_established",
            "protocol_v3_native_routing": "not_implemented",
            "resource_v2": "not_implemented",
            "policy_calibration": "not_accepted",
        },
        "runtime_image": _json_copy(runtime_image or {"status": "unbound"}),
        "device_inventory_sha256": str(device_inventory_sha256),
        "deployment_contract_sha256": _sha256_bytes(
            _canonical_json(DEPLOYMENT_CONTRACT)
        ),
        "topology_runtime_implemented": False,
        "measurement_execution_allowed": False,
        "generic_probe_relabelled": False,
    }
    result = _with_identity(plan)
    validate_openvino_topology_plan(result)
    return result


def validate_openvino_topology_plan(plan: Mapping[str, Any]) -> None:
    _require(type(plan) is dict, "OpenVINO topology plan must be an object")
    identity = plan.get("identity")
    _require(type(identity) is dict, "OpenVINO topology plan identity is missing")
    expected_identity = _sha256_bytes(
        _canonical_json({key: value for key, value in plan.items() if key != "identity"})
    )
    _require(
        identity.get("schema_version") == 1
        and identity.get("sha256") == expected_identity,
        "OpenVINO topology plan identity drifted",
    )
    _require(plan.get("artifact_kind") == "vast_openvino_checkpoint_topology_plan", "invalid plan kind")
    _require(plan.get("system") == SYSTEM, "OpenVINO topology plan system drifted")
    scenario = str(plan.get("scenario", ""))
    codec = str(plan.get("codec", ""))
    _require(scenario in SCENARIOS, "OpenVINO topology plan scenario drifted")
    _require(codec in CODEC_CONTRACTS, "OpenVINO topology plan codec drifted")
    _require(plan.get("topology_kind") == SCENARIOS[scenario], "OpenVINO topology kind drifted")
    _require(plan.get("dataset") == CODEC_CONTRACTS[codec]["dataset"], "OpenVINO dataset drifted")
    _require(plan.get("logical_streams") == LOGICAL_STREAMS, "OpenVINO stream count drifted")
    _require(plan.get("required_branches") == list(BRANCHES), "OpenVINO branches drifted")
    _require(plan.get("queued_branches_per_stream") == len(BRANCHES), "OpenVINO queued branch count drifted")
    _require(plan.get("analytics_queue") == ANALYTICS_QUEUE_CONTRACT, "OpenVINO analytics queue drifted")
    _require(plan.get("measurement_execution_allowed") is False, "measurement execution must remain disabled")
    _require(plan.get("topology_runtime_implemented") is False, "topology runtime must remain unimplemented")
    _require(plan.get("generic_probe_relabelled") is False, "generic probe relabeling is prohibited")
    decoder = plan.get("decoder") or {}
    _require(decoder.get("parser_factory") == CODEC_CONTRACTS[codec]["parser_factory"], "decoder parser drifted")
    _require(decoder.get("compressed_caps") == CODEC_CONTRACTS[codec]["compressed_caps"], "decoder caps drifted")
    coordinators = plan.get("source_coordinators")
    workers = plan.get("workers")
    _require(type(coordinators) is list and len(coordinators) == LOGICAL_STREAMS, "source coordinator count drifted")
    _require(type(workers) is list, "OpenVINO topology workers are invalid")
    counts = plan.get("process_counts") or {}
    expected_workers = LOGICAL_STREAMS * len(BRANCHES) if SCENARIOS[scenario] == "independent_processes" else LOGICAL_STREAMS
    _require(len(workers) == expected_workers, "OpenVINO topology worker count drifted")
    _require(counts.get("topology_workers") == expected_workers, "OpenVINO worker metadata drifted")
    process_ids = [str(worker.get("process_id", "")) for worker in workers]
    _require(all(process_ids) and len(process_ids) == len(set(process_ids)), "OpenVINO worker IDs drifted")
    if SCENARIOS[scenario] == "independent_processes":
        _require(all(worker.get("process_kind") == "independent_branch_worker" for worker in workers), "baseline worker kind drifted")
        _require({worker.get("branch_id") for worker in workers} == set(BRANCHES), "baseline branches drifted")
        _require(all(worker.get("analytics_queue") == ANALYTICS_QUEUE_CONTRACT for worker in workers), "baseline queue drifted")
    else:
        for graph in workers:
            _require(graph.get("process_kind") == "shared_video_dag_worker", "shared worker kind drifted")
            _require(graph.get("shared_prefix") == ["decode", "preprocess"], "shared prefix drifted")
            _require(graph.get("fanout_factory") == "tee", "shared fanout drifted")
            branches = graph.get("branches")
            _require(type(branches) is list and len(branches) == len(BRANCHES), "shared branch count drifted")
            _require({branch.get("branch_id") for branch in branches} == set(BRANCHES), "shared branches drifted")
            _require(all(branch.get("queue_required") is True for branch in branches), "shared branch queue missing")
            _require(all(branch.get("analytics_queue") == ANALYTICS_QUEUE_CONTRACT for branch in branches), "shared queue drifted")


def classify_openvino_devices(devices: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    cpu_devices: list[str] = []
    intel_gpu_devices: list[str] = []
    rejected_gpu_devices: list[str] = []
    normalized: list[dict[str, str]] = []
    for raw in devices:
        if type(raw) is not dict:
            raise ContractError("OpenVINO device inventory entry is invalid")
        device_id = str(raw.get("device_id", "")).strip()
        full_name = str(raw.get("full_device_name", "")).strip()
        vendor = str(raw.get("vendor", "")).strip()
        device_type = str(raw.get("device_type", "")).strip()
        if not device_id:
            raise ContractError("OpenVINO device inventory entry lacks device_id")
        base = device_id.split(".", 1)[0].upper()
        vendor_identity = f"{vendor} {full_name}".lower()
        if base == "CPU":
            cpu_devices.append(device_id)
        elif base == "GPU":
            if "intel" in vendor_identity and "nvidia" not in vendor_identity:
                intel_gpu_devices.append(device_id)
            else:
                rejected_gpu_devices.append(device_id)
        normalized.append(
            {
                "device_id": device_id,
                "full_device_name": full_name,
                "vendor": vendor,
                "device_type": device_type,
            }
        )
    return {
        "reported": normalized,
        "cpu_devices": sorted(cpu_devices),
        "intel_openvino_gpu_devices": sorted(intel_gpu_devices),
        "rejected_gpu_devices": sorted(rejected_gpu_devices),
        "nvidia_devices_counted_as_openvino_gpu": False,
        "availability_mode": (
            "cpu_and_intel_gpu"
            if cpu_devices and intel_gpu_devices
            else "cpu_only"
            if cpu_devices
            else "no_cpu_device"
        ),
    }


def build_device_probe_command(
    *, image: str, project_root: Path | str
) -> list[str]:
    root = Path(project_root).resolve()
    probe = root / "deploy" / "openvino" / "checkpoint" / "probe_openvino_devices.py"
    if probe.is_symlink() or not probe.is_file():
        raise ContractError("OpenVINO device probe script is missing")
    return [
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--gpus",
        "all",
        "-v",
        f"{root}:/workspace/project:ro",
        "--entrypoint",
        "python3",
        image,
        "/workspace/project/deploy/openvino/checkpoint/probe_openvino_devices.py",
    ]


def _default_command_runner(command: list[str]) -> str:
    try:
        return subprocess.check_output(
            command,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError) as error:
        raise ContractError("OpenVINO capability command failed") from error


def _inspect_image(image: str, *, command_runner: CommandRunner) -> dict[str, Any]:
    try:
        value = json.loads(
            command_runner(
                ["docker", "image", "inspect", "--format", "{{json .}}", image]
            )
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError, ContractError):
        raise ContractError("OpenVINO checkpoint image inspect failed") from None
    if type(value) is not dict:
        raise ContractError("OpenVINO checkpoint image inspect returned invalid data")
    image_id = str(value.get("Id", ""))
    if not image_id.startswith("sha256:") or _SHA256_RE.fullmatch(image_id[7:]) is None:
        raise ContractError("OpenVINO checkpoint image ID is invalid")
    repo_digests = value.get("RepoDigests") or []
    if type(repo_digests) is not list or any(type(item) is not str for item in repo_digests):
        raise ContractError("OpenVINO checkpoint image RepoDigests are invalid")
    return {
        "reference": image,
        "image_id": image_id,
        "repo_digests": sorted(set(repo_digests)),
        "architecture": str(value.get("Architecture", "")),
        "os": str(value.get("Os", "")),
    }


def _host_nvidia_gpus(*, command_runner: CommandRunner) -> list[dict[str, str]]:
    try:
        output = command_runner(
            [
                "nvidia-smi",
                "--query-gpu=name,uuid,driver_version",
                "--format=csv,noheader,nounits",
            ]
        )
    except (OSError, ContractError):
        return []
    result = []
    for line in output.splitlines():
        if not line.strip():
            continue
        values = [value.strip() for value in line.split(",")]
        if len(values) != 3 or any(not value for value in values):
            raise ContractError("NVIDIA host inventory is invalid")
        result.append(
            {"name": values[0], "uuid": values[1], "driver_version": values[2]}
        )
    return result


def _runtime_artifacts(project_root: Path) -> list[dict[str, Any]]:
    paths = (
        project_root / "scripts" / "checkpoint_openvino_runtime.py",
        project_root / "deploy" / "openvino" / "checkpoint" / "contract.json",
        project_root
        / "deploy"
        / "openvino"
        / "checkpoint"
        / "probe_openvino_devices.py",
    )
    records = []
    for path in paths:
        if path.is_symlink() or not path.is_file():
            raise ContractError(f"OpenVINO checkpoint runtime artifact is missing: {path.name}")
        records.append(
            {
                "path": path.relative_to(project_root).as_posix(),
                "size_bytes": int(path.stat().st_size),
                "sha256": _sha256_file(path),
            }
        )
    return records


def preflight_openvino_checkpoint(
    *,
    image: str,
    project_root: Path | str = PROJECT_ROOT,
    command_runner: CommandRunner = _default_command_runner,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    contract = load_deployment_contract(root)
    runtime_image = _inspect_image(image, command_runner=command_runner)
    nvidia_gpus = _host_nvidia_gpus(command_runner=command_runner)
    try:
        probe = json.loads(
            command_runner(
                build_device_probe_command(image=image, project_root=root)
            )
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError, ContractError):
        raise ContractError("OpenVINO in-image device probe failed") from None
    if (
        type(probe) is not dict
        or probe.get("schema_version") != 1
        or probe.get("artifact_kind") != "vast_openvino_checkpoint_device_probe"
    ):
        raise ContractError("OpenVINO in-image device probe schema drifted")
    available_devices = probe.get("available_devices")
    elements = probe.get("gstreamer_elements")
    if type(available_devices) is not list or type(elements) is not dict:
        raise ContractError("OpenVINO in-image capability inventory is invalid")
    classified = classify_openvino_devices(available_devices)
    blockers = list(BASE_PUBLICATION_BLOCKERS)
    operational_blockers: list[str] = []
    if not classified["cpu_devices"]:
        operational_blockers.append("openvino_cpu_device_missing")
    for element in REQUIRED_GSTREAMER_ELEMENTS:
        item = elements.get(element)
        if type(item) is not dict or item.get("available") is not True:
            operational_blockers.append(f"required_gstreamer_element_missing:{element}")
    for device_id in classified["rejected_gpu_devices"]:
        operational_blockers.append(
            f"openvino_gpu_vendor_not_verified:{device_id}"
        )
    blockers.extend(operational_blockers)
    blockers = list(dict.fromkeys(blockers))
    inventory_material = {
        "openvino_version": str(probe.get("openvino_version", "")),
        "devices": classified,
        "gstreamer_elements": elements,
    }
    inventory_sha = _sha256_bytes(_canonical_json(inventory_material))
    plan_identities = []
    for scenario in SCENARIOS:
        for codec in CODEC_CONTRACTS:
            plan = build_openvino_topology_plan(
                scenario=scenario,
                codec=codec,
                runtime_image=runtime_image,
                device_inventory_sha256=inventory_sha,
                deployment_contract=contract,
            )
            plan_identities.append(
                {
                    "scenario": scenario,
                    "codec": codec,
                    "sha256": plan["identity"]["sha256"],
                }
            )
    artifacts = _runtime_artifacts(root)
    capability_passed = not operational_blockers
    return {
        "schema_version": 1,
        "artifact_kind": "vast_openvino_checkpoint_capability_preflight",
        "status": (
            "capability_verified_publication_blocked"
            if capability_passed
            else "capability_blocked"
        ),
        "system": SYSTEM,
        "capability_preflight_passed": capability_passed,
        "topology_plan_implemented": True,
        "topology_runtime_implemented": False,
        "publication_ready": False,
        "measurement_execution_allowed": False,
        "generic_probe_relabelled": False,
        "supported_plan_scenarios": list(SCENARIOS),
        "supported_plan_codecs": list(CODEC_CONTRACTS),
        "runtime_image": runtime_image,
        "openvino_version": str(probe.get("openvino_version", "")),
        "openvino_devices": classified,
        "nvidia_host_gpus": nvidia_gpus,
        "nvidia_gpu_counted_as_openvino_gpu": False,
        "gstreamer_elements": _json_copy(elements),
        "device_inventory_sha256": inventory_sha,
        "deployment_contract_sha256": _sha256_bytes(_canonical_json(contract)),
        "runtime_artifacts": artifacts,
        "runtime_artifacts_sha256": _sha256_bytes(_canonical_json(artifacts)),
        "topology_plan_identities": plan_identities,
        "blockers": blockers,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build OpenVINO checkpoint topology plans or inspect image capability; no measurement command exists."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan = subparsers.add_parser("plan")
    plan.add_argument("--codec", choices=tuple(CODEC_CONTRACTS), required=True)
    plan.add_argument("--scenario", choices=tuple(SCENARIOS), required=True)
    preflight = subparsers.add_parser("preflight")
    preflight.add_argument("--image", required=True)
    preflight.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "plan":
            result = build_openvino_topology_plan(
                scenario=args.scenario,
                codec=args.codec,
            )
            exit_code = 0
        else:
            result = preflight_openvino_checkpoint(
                image=args.image,
                project_root=args.project_root,
            )
            exit_code = 0 if result["publication_ready"] else 78
    except ContractError as error:
        result = {
            "schema_version": 1,
            "artifact_kind": "vast_openvino_checkpoint_command_error",
            "status": "permanent_error",
            "message": str(error),
        }
        exit_code = 78
    print(json.dumps(result, indent=2, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "BASE_PUBLICATION_BLOCKERS",
    "BRANCHES",
    "REQUIRED_GSTREAMER_ELEMENTS",
    "build_device_probe_command",
    "build_openvino_topology_plan",
    "build_parser",
    "classify_openvino_devices",
    "load_deployment_contract",
    "main",
    "preflight_openvino_checkpoint",
    "validate_openvino_topology_plan",
]
