#!/usr/bin/env python3
"""Pinned Savant 0.5.17 / DeepStream 7.0 publication container runtime.

The module has deliberately dependency-free contract and finalization paths so
they can be checked on the host.  Native Savant imports are confined to the
worker/pilot execution path and therefore fail closed when the exact SDK image
is not in use.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import stat
import sys
import tempfile
import time
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = 3
SAVANT_VERSION = "0.5.17"
DEEPSTREAM_VERSION = "7.0"
RUNTIME_ABI = "3"
BASE_IMAGE_ID = (
    "sha256:3c0ef6f4bb57e385644da526789626f0c943dcb90ff32b72a7883e05798ce9e6"
)
DATASET_BY_CODEC = {
    "h264": "kpp_iss_publication_v3_h264",
    "h265": "kpp_iss_publication_v3_h265",
}
BRANCHES = ("plate_number", "vehicle_type", "damage", "foreign_object")
TOPOLOGY_SCENARIO = {
    "independent_processes": "checkpoint_independent_processes_baseline",
    "shared_video_dag": "checkpoint_video_dag_shared",
}
WORKER_RECEIPT_KIND = "vast_savant_publication_worker_receipt_v3"
PILOT_RECEIPT_KIND = "vast_savant_publication_native_pilot_v3"
TERMINAL_KIND = "vast_savant_publication_runtime_terminal_v3"
EVIDENCE_KIND = "vast_savant_publication_runtime_evidence_v3"
_SHA = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_MODULE = re.compile(
    r"^savant-stream-(?P<stream>[0-5])-(?:branch-(?P<branch>plate_number|"
    r"vehicle_type|damage|foreign_object)|(?P<shared>shared-video-dag))$"
)
# PyFunc loader imports by canonical module name while the entrypoint executes
# this file as __main__; both must share the same observer registry.
if __name__ == "__main__":
    _importlib_util = __import__("importlib.util", fromlist=["spec_from_file_location"])
    __spec__ = _importlib_util.spec_from_file_location(
        "savant_publication_runtime_v3", __file__
    )
    sys.modules.setdefault("savant_publication_runtime_v3", sys.modules[__name__])



class SavantPublicationImageRuntimeError(RuntimeError):
    """The image-local runtime contract failed closed."""


def _require(condition: bool, blocker: str) -> None:
    if not condition:
        raise SavantPublicationImageRuntimeError(blocker)


def _canonical(value: Any) -> bytes:
    try:
        return (
            json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            ).encode("ascii")
            + b"\n"
        )
    except (TypeError, ValueError) as exc:
        raise SavantPublicationImageRuntimeError(
            "savant_image_noncanonical_json"
        ) from exc


def _payload_sha256(value: Mapping[str, Any], field: str) -> str:
    body = dict(value)
    body.pop(field, None)
    return hashlib.sha256(_canonical(body)).hexdigest()


def receipt_payload_sha256(value: Mapping[str, Any]) -> str:
    return _payload_sha256(value, "receipt_payload_sha256")


def evidence_payload_sha256(value: Mapping[str, Any]) -> str:
    return _payload_sha256(value, "evidence_payload_sha256")


def _regular_file(path: Path, blocker: str, *, maximum: int | None = None) -> os.stat_result:
    try:
        before = path.lstat()
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise SavantPublicationImageRuntimeError(blocker) from exc
    _require(resolved == path and stat.S_ISREG(before.st_mode), blocker)
    _require(not path.is_symlink() and int(before.st_nlink) == 1, blocker)
    _require(int(before.st_size) > 0, blocker)
    if maximum is not None:
        _require(int(before.st_size) <= maximum, blocker)
    return before


def _read_exact_json(path: Path, blocker: str, *, maximum: int = 16 * 1024 * 1024) -> dict[str, Any]:
    before = _regular_file(path, blocker, maximum=maximum)
    try:
        payload = path.read_bytes()
        after = path.lstat()
        value = json.loads(payload)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SavantPublicationImageRuntimeError(blocker) from exc
    _require(
        (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns),
        blocker,
    )
    _require(type(value) is dict, blocker)
    return value


def _atomic_write(path: Path, payload: bytes) -> None:
    _require(path.is_absolute(), "savant_image_output_path_not_absolute")
    _require(not path.exists(), "savant_image_output_already_exists")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = -1
    temporary: Path | None = None
    try:
        descriptor, raw = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        temporary = Path(raw)
        os.fchmod(descriptor, 0o600)
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            _require(written > 0, "savant_image_output_write_failed")
            view = view[written:]
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        os.link(temporary, path)
        temporary.unlink()
        temporary = None
        directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except (OSError, SavantPublicationImageRuntimeError) as exc:
        raise SavantPublicationImageRuntimeError(
            "savant_image_output_commit_failed"
        ) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _checked_text(value: Any, blocker: str) -> str:
    _require(type(value) is str and _IDENTIFIER.fullmatch(value) is not None, blocker)
    return value


def _checked_sha(value: Any, blocker: str) -> str:
    _require(type(value) is str and _SHA.fullmatch(value) is not None, blocker)
    return value


def _checked_codec_dataset(codec: Any, dataset_id: Any) -> tuple[str, str]:
    _require(type(codec) is str and codec in DATASET_BY_CODEC, "savant_codec_invalid")
    _require(dataset_id == DATASET_BY_CODEC[codec], "savant_dataset_codec_binding_invalid")
    return codec, str(dataset_id)


def _checked_topology(value: Any) -> str:
    _require(type(value) is str and value in TOPOLOGY_SCENARIO, "savant_topology_invalid")
    return value


def materialize_topology_descriptors(
    *, topology_kind: str, dataset_id: str, codec: str, policy: str,
    deadline_ms: float,
) -> tuple[dict[str, Any], ...]:
    """Return the exact 24-process baseline or six-process shared layout."""

    topology = _checked_topology(topology_kind)
    checked_codec, checked_dataset = _checked_codec_dataset(codec, dataset_id)
    checked_policy = _checked_text(policy, "savant_policy_invalid")
    _require(
        isinstance(deadline_ms, (int, float))
        and not isinstance(deadline_ms, bool)
        and math.isfinite(float(deadline_ms))
        and float(deadline_ms) > 0,
        "savant_deadline_invalid",
    )
    rows: list[dict[str, Any]] = []
    for stream_id in range(6):
        route_sets = (BRANCHES,) if topology == "shared_video_dag" else tuple(
            (branch,) for branch in BRANCHES
        )
        for branches in route_sets:
            suffix = "shared-video-dag" if topology == "shared_video_dag" else f"branch-{branches[0]}"
            rows.append({
                "schema_version": SCHEMA_VERSION,
                "artifact_kind": "vast_savant_topology_descriptor_v3",
                "module_id": f"savant-stream-{stream_id}-{suffix}",
                "topology_kind": topology,
                "stream_id": stream_id,
                "branches": list(branches),
                "dataset_id": checked_dataset,
                "codec": checked_codec,
                "policy": checked_policy,
                "deadline_ms": float(deadline_ms),
                "physical_decoder_count": 1,
                "decoder_factory": "nvv4l2decoder",
                "decoder_gpu_id": 0,
                "route_queue_max_buffers": 1,
                "route_drop_policy": "drop_newest",
            })
    expected = 6 if topology == "shared_video_dag" else 24
    _require(len(rows) == expected, "savant_topology_cardinality_invalid")
    return tuple(rows)


_WORKER_FIELDS = {
    "schema_version", "artifact_kind", "status", "run_id", "arm_id",
    "module_id", "topology_kind", "stream_id", "branches", "dataset_id",
    "codec", "source_sha256", "module_config_sha256", "savant_version",
    "deepstream_version", "decoder_factory", "decoder_gpu_id",
    "admitted_frames", "decoded_frames", "branch_terminals", "branch_drops",
    "runtime_event_count", "worker_started_monotonic_ns",
    "worker_completed_monotonic_ns", "receipt_payload_sha256",
}


def validate_worker_receipt(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate observations emitted by native Savant callbacks."""
    _require(type(value) is dict, "savant_worker_receipt_not_object")
    receipt = dict(value)
    _require(set(receipt) == _WORKER_FIELDS, "savant_worker_receipt_fields_drifted")
    _require(
        receipt["schema_version"] == SCHEMA_VERSION
        and receipt["artifact_kind"] == WORKER_RECEIPT_KIND
        and receipt["status"] == "completed_native_savant_worker",
        "savant_worker_receipt_identity_invalid",
    )
    _checked_text(receipt["run_id"], "savant_worker_run_id_invalid")
    _checked_text(receipt["arm_id"], "savant_worker_arm_id_invalid")
    module_id = _checked_text(receipt["module_id"], "savant_worker_module_id_invalid")
    match = _MODULE.fullmatch(module_id)
    _require(match is not None, "savant_worker_module_id_invalid")
    topology = _checked_topology(receipt["topology_kind"])
    stream_id = receipt["stream_id"]
    _require(
        type(stream_id) is int and 0 <= stream_id < 6
        and int(match.group("stream")) == stream_id,
        "savant_worker_stream_binding_invalid",
    )
    branches = receipt["branches"]
    _require(type(branches) is list and all(type(x) is str for x in branches),
             "savant_worker_branches_invalid")
    if topology == "shared_video_dag":
        _require(match.group("shared") is not None and tuple(branches) == BRANCHES,
                 "savant_worker_shared_routes_invalid")
    else:
        branch = match.group("branch")
        _require(branch is not None and branches == [branch],
                 "savant_worker_baseline_route_invalid")
    _checked_codec_dataset(receipt["codec"], receipt["dataset_id"])
    _checked_sha(receipt["source_sha256"], "savant_worker_source_pin_invalid")
    _checked_sha(receipt["module_config_sha256"], "savant_worker_config_pin_invalid")
    _require(
        receipt["savant_version"] == SAVANT_VERSION
        and receipt["deepstream_version"] == DEEPSTREAM_VERSION,
        "savant_worker_sdk_version_drifted",
    )
    _require(
        receipt["decoder_factory"] == "nvv4l2decoder"
        and receipt["decoder_gpu_id"] == 0,
        "savant_worker_native_decoder_not_observed",
    )
    integer_fields = (
        "admitted_frames", "decoded_frames", "branch_terminals",
        "branch_drops", "runtime_event_count", "worker_started_monotonic_ns",
        "worker_completed_monotonic_ns",
    )
    _require(
        all(type(receipt[field]) is int and receipt[field] >= 0 for field in integer_fields),
        "savant_worker_counter_invalid",
    )
    admitted = int(receipt["admitted_frames"])
    decoded = int(receipt["decoded_frames"])
    terminals = int(receipt["branch_terminals"])
    drops = int(receipt["branch_drops"])
    _require(admitted > 0 and decoded > 0 and admitted == decoded,
             "savant_worker_decode_incomplete")
    _require(terminals == decoded * len(branches),
             "savant_worker_route_terminal_incomplete")
    _require(0 <= drops <= terminals, "savant_worker_drop_count_invalid")
    _require(receipt["runtime_event_count"] >= admitted + decoded + terminals,
             "savant_worker_runtime_event_set_incomplete")
    _require(
        0 < receipt["worker_started_monotonic_ns"]
        < receipt["worker_completed_monotonic_ns"],
        "savant_worker_timeline_invalid",
    )
    supplied = _checked_sha(
        receipt["receipt_payload_sha256"], "savant_worker_receipt_hash_invalid"
    )
    _require(supplied == receipt_payload_sha256(receipt),
             "savant_worker_receipt_hash_drifted")
    return receipt


def _checked_evidence_mapping(value: Mapping[str, str]) -> dict[str, str]:
    _require(type(value) is dict and value, "savant_evidence_mapping_invalid")
    result: dict[str, str] = {}
    for name, raw in value.items():
        _require(type(name) is str and Path(name).name == name,
                 "savant_evidence_mapping_invalid")
        _require(type(raw) is str and "\\" not in raw and "\x00" not in raw,
                 "savant_evidence_mapping_invalid")
        pure = PurePosixPath(raw)
        _require(
            not pure.is_absolute() and pure.parts and pure.parts[0] == "evidence"
            and pure.as_posix() == raw
            and all(part not in {"", ".", ".."} for part in pure.parts),
            "savant_evidence_mapping_invalid",
        )
        result[name] = raw
    _require(len(set(result.values())) == len(result), "savant_evidence_mapping_invalid")
    return result


def _receipt_paths(runtime_output: Path) -> tuple[Path, ...]:
    modules = runtime_output / "modules"
    _require(modules.is_dir() and not modules.is_symlink(),
             "savant_worker_receipt_namespace_missing")
    paths: list[Path] = []
    for child in modules.iterdir():
        _require(child.is_dir() and not child.is_symlink(),
                 "savant_worker_receipt_namespace_invalid")
        _require(_MODULE.fullmatch(child.name) is not None,
                 "savant_worker_receipt_namespace_invalid")
        entries = list(child.iterdir())
        _require(
            len(entries) == 1 and entries[0].name == "worker-receipt.json"
            and not entries[0].is_symlink(),
            "savant_worker_receipt_namespace_invalid",
        )
        paths.append(child / "worker-receipt.json")
    return tuple(sorted(paths, key=lambda item: item.parent.name))


def finalize_runtime_output(
    *, runtime_output: Path, run_id: str, arm_id: str, scenario: str,
    topology_kind: str, dataset_id: str, codec: str, policy: str,
    deadline_ms: float, module_count: int, evidence_mapping: Mapping[str, str],
) -> dict[str, Any]:
    """Commit evidence derived solely from complete native worker receipts."""
    root = runtime_output.resolve(strict=True)
    _require(root == runtime_output and root.is_dir(), "savant_runtime_output_invalid")
    topology = _checked_topology(topology_kind)
    checked_codec, checked_dataset = _checked_codec_dataset(codec, dataset_id)
    _require(scenario == TOPOLOGY_SCENARIO[topology], "savant_scenario_topology_invalid")
    _checked_text(run_id, "savant_finalize_run_id_invalid")
    _checked_text(arm_id, "savant_finalize_arm_id_invalid")
    _checked_text(policy, "savant_finalize_policy_invalid")
    _require(
        type(module_count) is int
        and module_count == (6 if topology == "shared_video_dag" else 24),
        "savant_finalize_module_count_invalid",
    )
    _require(
        isinstance(deadline_ms, (int, float)) and not isinstance(deadline_ms, bool)
        and math.isfinite(float(deadline_ms)) and float(deadline_ms) > 0,
        "savant_finalize_deadline_invalid",
    )
    mapping = _checked_evidence_mapping(evidence_mapping)
    paths = _receipt_paths(root)
    _require(len(paths) == module_count, "savant_worker_receipt_count_incomplete")
    receipts = tuple(validate_worker_receipt(_read_exact_json(
        path, "savant_worker_receipt_read_failed"
    )) for path in paths)
    descriptors = materialize_topology_descriptors(
        topology_kind=topology, dataset_id=checked_dataset, codec=checked_codec,
        policy=policy, deadline_ms=float(deadline_ms),
    )
    expected_modules = {row["module_id"] for row in descriptors}
    _require({row["module_id"] for row in receipts} == expected_modules,
             "savant_worker_receipt_topology_incomplete")
    for row in receipts:
        _require(
            row["run_id"] == run_id and row["arm_id"] == arm_id
            and row["topology_kind"] == topology
            and row["dataset_id"] == checked_dataset
            and row["codec"] == checked_codec,
            "savant_worker_receipt_arm_binding_invalid",
        )
    document: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": EVIDENCE_KIND,
        "status": "accepted_native_savant_runtime_evidence",
        "run_id": run_id,
        "arm_id": arm_id,
        "system": "savant",
        "scenario": scenario,
        "topology_kind": topology,
        "dataset_id": checked_dataset,
        "codec": checked_codec,
        "policy": policy,
        "deadline_ms": float(deadline_ms),
        "worker_receipt_count": len(receipts),
        "decoded_frame_count": sum(int(row["decoded_frames"]) for row in receipts),
        "branch_terminal_count": sum(int(row["branch_terminals"]) for row in receipts),
        "branch_drop_count": sum(int(row["branch_drops"]) for row in receipts),
        "worker_receipt_sha256": {
            row["module_id"]: row["receipt_payload_sha256"] for row in receipts
        },
        "evidence_payload_sha256": "",
    }
    document["evidence_payload_sha256"] = evidence_payload_sha256(document)
    payload = _canonical(document)
    for source in mapping.values():
        target = root.joinpath(*PurePosixPath(source).parts)
        try:
            target.resolve(strict=False).relative_to(root)
        except (OSError, ValueError) as exc:
            raise SavantPublicationImageRuntimeError(
                "savant_evidence_target_escape"
            ) from exc
        _atomic_write(target, payload)
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": TERMINAL_KIND,
        "status": "accepted_native_checkpoint_arm",
        "run_id": run_id,
        "arm_id": arm_id,
        "system": "savant",
        "scenario": scenario,
        "topology_kind": topology,
        "dataset_id": checked_dataset,
        "codec": checked_codec,
        "policy": policy,
        "deadline_ms": float(deadline_ms),
        "module_count": module_count,
        "evidence_files": list(mapping),
    }


class _PilotObserver:
    def __init__(self, *, pilot_id: str, topology_kind: str, branches: Sequence[str], frame_limit: int) -> None:
        self.pilot_id = pilot_id
        self.topology_kind = topology_kind
        self.branches = tuple(branches)
        self.frame_limit = frame_limit
        self.started_ns = time.monotonic_ns()
        self.decoder: tuple[str, int] | None = None
        self.decoded: set[tuple[int, int, int]] = set()
        self.terminals: set[tuple[tuple[int, int, int], str]] = set()
        self.drain_decoded: set[tuple[int, int, int]] = set()
        self.drain_terminals: set[tuple[tuple[int, int, int], str]] = set()
        self.keys_by_pts: dict[int, tuple[int, int, int]] = {}
        self.lock = __import__("threading").Lock()

    @staticmethod
    def frame_key(frame_meta: Any) -> tuple[int, int, int]:
        native = getattr(frame_meta, "frame_meta", None)
        _require(native is not None, "savant_pilot_nvds_frame_meta_missing")
        key = (
            int(getattr(native, "source_id", -1)),
            int(getattr(native, "frame_num", -1)),
            int(getattr(native, "buf_pts", -1)),
        )
        _require(all(value >= 0 for value in key), "savant_pilot_nvds_identity_invalid")
        return key

    def bind_decoder(self, factory: str, gpu_id: int) -> None:
        with self.lock:
            _require(self.decoder in {None, (factory, gpu_id)},
                     "savant_pilot_decoder_observation_drifted")
            _require(factory == "nvv4l2decoder" and gpu_id == 0,
                     "savant_pilot_native_decoder_not_observed")
            self.decoder = (factory, gpu_id)

    def observe_prefix(self, frame_meta: Any) -> int:
        key = self.frame_key(frame_meta)
        with self.lock:
            _require(self.decoder == ("nvv4l2decoder", 0),
                     "savant_pilot_decoder_observation_missing")
            _require(key not in self.decoded and key not in self.drain_decoded,
                     "savant_pilot_decode_duplicated")
            pts = key[2]
            _require(pts not in self.keys_by_pts,
                     "savant_pilot_pts_duplicated")
            self.keys_by_pts[pts] = key
            if len(self.decoded) < self.frame_limit:
                self.decoded.add(key)
                return len(self.decoded)
            self.drain_decoded.add(key)
            _require(len(self.drain_decoded) <= 16,
                     "savant_pilot_drain_bound_exceeded")
            return self.frame_limit
    def observe_terminal(self, frame_meta: Any, branch: str) -> None:
        key = self.frame_key(frame_meta)
        with self.lock:
            _require(branch in self.branches
                     and key in self.decoded | self.drain_decoded,
                     "savant_pilot_route_without_decode")
            terminal = (key, branch)
            _require(terminal not in self.terminals
                     and terminal not in self.drain_terminals,
                     "savant_pilot_route_duplicated")
            if key in self.decoded:
                self.terminals.add(terminal)
            else:
                self.drain_terminals.add(terminal)


    def observe_terminal_pts(self, pts: int, branch: str) -> None:
        with self.lock:
            key = self.keys_by_pts.get(pts)
            _require(key is not None, "savant_pilot_route_without_decode")
            _require(branch in self.branches,
                     "savant_pilot_route_branch_invalid")
            terminal = (key, branch)
            _require(terminal not in self.terminals
                     and terminal not in self.drain_terminals,
                     "savant_pilot_route_duplicated")
            if key in self.decoded:
                self.terminals.add(terminal)
            else:
                _require(key in self.drain_decoded,
                         "savant_pilot_route_without_decode")
                self.drain_terminals.add(terminal)
    def result(self, *, frame_limit: int) -> dict[str, Any]:
        with self.lock:
            decoded = len(self.decoded)
            terminals = len(self.terminals)
            drain_decoded = len(self.drain_decoded)
            drain_terminals = len(self.drain_terminals)
            _require(self.decoder == ("nvv4l2decoder", 0),
                     "savant_pilot_decoder_observation_missing")
            _require(decoded == frame_limit, "savant_pilot_frame_limit_not_exact")
            _require(terminals == decoded * len(self.branches),
                     "savant_pilot_route_matrix_incomplete")
            return {
                "decoder_factory": self.decoder[0],
                "decoder_gpu_id": self.decoder[1],
                "measured_decoded_frames": decoded,
                "measured_branch_terminals": terminals,
                "drain_decoded_frames": drain_decoded,
                "drain_branch_terminals": drain_terminals,
                "decoded_frames": decoded + drain_decoded,
                "branch_terminals": terminals + drain_terminals,
                "worker_started_monotonic_ns": self.started_ns,
                "worker_completed_monotonic_ns": time.monotonic_ns(),
            }


_PILOT_BUILTINS = __import__("builtins")
if not hasattr(_PILOT_BUILTINS, "_vast_savant_pilot_observers_v3"):
    setattr(_PILOT_BUILTINS, "_vast_savant_pilot_observers_v3", {})
_PILOT_OBSERVERS: dict[str, _PilotObserver] = getattr(
    _PILOT_BUILTINS, "_vast_savant_pilot_observers_v3")


try:
    from savant.base.pyfunc import BasePyFuncPlugin as _BasePyFuncPlugin
    from savant.config.schema import PipelineElement as _PipelineElement
    from savant.config.schema import PyFuncElement as _PyFuncElement
    from savant.deepstream.pipeline import NvDsPipeline as _NvDsPipeline
    from savant.deepstream.pyfunc import NvDsPyFuncPlugin as _NvDsPyFuncPlugin
    from savant.gstreamer import Gst as _Gst
except (ImportError, OSError):
    _PipelineElement = _PyFuncElement = _Gst = None

    class _BasePyFuncPlugin:  # type: ignore[no-redef]
        def __init__(self, **_: Any) -> None:
            self.gst_element = None

        def on_start(self) -> bool:
            return True


    class _NvDsPyFuncPlugin:  # type: ignore[no-redef]
        def __init__(self, **_: Any) -> None:
            self.gst_element = None

        def on_start(self) -> bool:
            return True

    class _NvDsPipeline:  # type: ignore[no-redef]
        def __init__(self, *_: Any, **__: Any) -> None:
            raise SavantPublicationImageRuntimeError("savant_sdk_not_available")


def _pilot_observer(pilot_id: str) -> _PilotObserver:
    observer = _PILOT_OBSERVERS.get(pilot_id)
    _require(observer is not None, "savant_pilot_observer_missing")
    return observer


class SavantPilotPrefixPlugin(_NvDsPyFuncPlugin):
    def __init__(self, *, pilot_id: str, frame_limit: int, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.pilot_id = pilot_id
        _require(type(frame_limit) is int and frame_limit > 0, "savant_pilot_frame_limit_invalid")
        self.frame_limit = frame_limit
        self._decoder_observed = False
        self._eos_sent = False

    def _observe_decoder(self) -> None:
        if self._decoder_observed:
            return
        _require(_Gst is not None and self.gst_element is not None,
                 "savant_pilot_gstreamer_unavailable")
        root = self.gst_element.get_parent()
        while root.get_parent() is not None:
            root = root.get_parent()
        iterator = root.iterate_recurse()
        decoders: list[Any] = []
        while True:
            result, element = iterator.next()
            if result == _Gst.IteratorResult.OK:
                factory = element.get_factory()
                if factory is not None and factory.get_name() == "nvv4l2decoder":
                    decoders.append(element)
            elif result == _Gst.IteratorResult.DONE:
                break
            elif result == _Gst.IteratorResult.RESYNC:
                iterator.resync()
            else:
                raise SavantPublicationImageRuntimeError(
                    "savant_pilot_decoder_graph_iteration_failed"
                )
        _require(len(decoders) == 1, "savant_pilot_decoder_cardinality_invalid")
        decoder = decoders[0]
        gpu_id = int(decoder.get_property("gpu-id")) if decoder.find_property("gpu-id") else 0
        _pilot_observer(self.pilot_id).bind_decoder("nvv4l2decoder", gpu_id)
        self._decoder_observed = True

    def process_frame(self, _buffer: Any, frame_meta: Any) -> None:
        self._observe_decoder()
        count = _pilot_observer(self.pilot_id).observe_prefix(frame_meta)
        # nvstreammux has one already-admitted buffer in flight at this callback.
        if count == self.frame_limit and not self._eos_sent:
            self._eos_sent = True
            _require(_Gst is not None and self.gst_element is not None,
                     "savant_pilot_gstreamer_unavailable")
            root = self.gst_element.get_parent()
            while root.get_parent() is not None:
                root = root.get_parent()
            _require(root.send_event(_Gst.Event.new_eos()),
                     "savant_pilot_bound_eos_rejected")


class SavantPilotRoutePlugin(_NvDsPyFuncPlugin):
    def __init__(self, *, pilot_id: str, branch: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.pilot_id = pilot_id
        self.branch = branch

    def process_frame(self, _buffer: Any, frame_meta: Any) -> None:
        _pilot_observer(self.pilot_id).observe_terminal(frame_meta, self.branch)


class SavantPilotRouteBufferPlugin(_BasePyFuncPlugin):
    """Observe a real post-demux buffer without requiring removed batch meta."""
    def __init__(self, *, pilot_id: str, branch: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.pilot_id = pilot_id
        self.branch = branch

    def process_buffer(self, buffer: Any) -> None:
        pts = int(getattr(buffer, "pts", -1))
        _require(pts >= 0, "savant_pilot_route_pts_invalid")
        _pilot_observer(self.pilot_id).observe_terminal_pts(pts, self.branch)

class SavantPilotNvDsPipeline(_NvDsPipeline):
    """Official NvDsPipeline with a physical four-route post-demux tee."""
    def __init__(self, name: str, pipeline_cfg: Any, **kwargs: Any) -> None:
        self.pilot_id = str(kwargs.get("pilot_id", ""))
        self.pilot_topology = _checked_topology(kwargs.get("pilot_topology"))
        branches = kwargs.get("pilot_branches")
        _require(isinstance(branches, list) and all(x in BRANCHES for x in branches),
                 "savant_pilot_pipeline_branches_invalid")
        self.pilot_branches = tuple(branches)
        if self.pilot_topology == "shared_video_dag":
            _require(self.pilot_branches == BRANCHES,
                     "savant_pilot_shared_pipeline_branches_invalid")
        else:
            _require(len(self.pilot_branches) == 1,
                     "savant_pilot_baseline_pipeline_branches_invalid")
        super().__init__(name, pipeline_cfg, **kwargs)

    def _add_source_output(self, source_info: Any, *args: Any, **kwargs: Any) -> Any:
        if self.pilot_topology != "shared_video_dag":
            return super()._add_source_output(source_info, *args, **kwargs)
        _require(_PipelineElement is not None and _PyFuncElement is not None and _Gst is not None,
                 "savant_pilot_sdk_graph_api_unavailable")
        self._check_pipeline_is_running()
        output_sink = super()._add_source_output(
            source_info, link_to_demuxer=False,
            source_output=kwargs.get("source_output"),
            buffer_processor=kwargs.get("buffer_processor"),
        )
        tee = self.add_element(_PipelineElement(
            "tee", name=f"vast_savant_pilot_shared_tee_{source_info.pad_idx}"
        ), link=False)
        tee.sync_state_with_parent()
        source_info.after_demuxer.append(tee)
        self._link_demuxer_src_pad(tee.get_static_pad("sink"), source_info)
        for index, branch in enumerate(self.pilot_branches):
            queue = self.add_element(_PipelineElement(
                "queue", name=f"vast_savant_pilot_queue_{branch}", properties={
                    "max-size-buffers": 1, "max-size-bytes": 0,
                    "max-size-time": 0, "leaky": "upstream",
                }
            ), link=False)
            plugin = self.add_element(_PyFuncElement(
                module="savant_publication_runtime_v3",
                class_name="SavantPilotRouteBufferPlugin",
                kwargs={"pilot_id": self.pilot_id, "branch": branch},
                name=f"vast_savant_pilot_terminal_{branch}",
            ), link=False)
            plugin.set_property("pipeline", self._video_pipeline)
            plugin.set_property("gst-pipeline", self)
            plugin.set_property("stream-pool-size", self._batch_size)
            _require(queue.link(plugin), "savant_pilot_route_link_failed")
            tee_pad = tee.request_pad_simple("src_%u")
            _require(
                tee_pad is not None
                and tee_pad.link(queue.get_static_pad("sink")) == _Gst.PadLinkReturn.OK,
                "savant_pilot_tee_link_failed",
            )
            queue.sync_state_with_parent()
            plugin.sync_state_with_parent()
            source_info.after_demuxer.extend([queue, plugin])
            if index == len(self.pilot_branches) - 1:
                _require(
                    plugin.get_static_pad("src").link(output_sink)
                    == _Gst.PadLinkReturn.OK,
                    "savant_pilot_owner_route_link_failed",
                )
            else:
                sink = self.add_element(_PipelineElement(
                    "fakesink", name=f"vast_savant_pilot_sink_{branch}",
                    properties={"sync": 0, "qos": 0, "enable-last-sample": 0},
                ), link=False)
                _require(plugin.link(sink), "savant_pilot_route_sink_link_failed")
                sink.sync_state_with_parent()
                source_info.after_demuxer.append(sink)
        return output_sink


def build_pilot_module_config(
    *, source_file: Path, pilot_id: str, topology_kind: str,
    branches: Sequence[str], frame_limit: int,
) -> dict[str, Any]:
    topology = _checked_topology(topology_kind)
    _checked_text(pilot_id, "savant_pilot_id_invalid")
    branch_tuple = tuple(branches)
    _require(
        branch_tuple == BRANCHES if topology == "shared_video_dag"
        else len(branch_tuple) == 1 and branch_tuple[0] in BRANCHES,
        "savant_pilot_branches_invalid",
    )
    _require(type(frame_limit) is int and 1 <= frame_limit <= 3600,
             "savant_pilot_frame_limit_invalid")
    source = source_file.resolve(strict=True)
    _regular_file(source, "savant_pilot_source_invalid")
    elements: list[dict[str, Any]] = [
        {"element": "pyfunc", "name": "vast_savant_pilot_prefix",
         "module": "savant_publication_runtime_v3",
         "class_name": "SavantPilotPrefixPlugin",
         "kwargs": {"pilot_id": pilot_id, "frame_limit": frame_limit}},
    ]
    if topology == "independent_processes":
        elements.append({
            "element": "pyfunc", "name": "vast_savant_pilot_terminal",
            "module": "savant_publication_runtime_v3",
            "class_name": "SavantPilotRoutePlugin",
            "kwargs": {"pilot_id": pilot_id, "branch": branch_tuple[0]},
        })
    return {
        "name": f"vast-savant-pilot-{pilot_id}",
        "parameters": {
            "log_level": "INFO", "batch_size": 1, "max_parallel_streams": 1,
            "min_fps": "600/1", "max_fps": "600/1", "max_fps_control": False,
            "queue_maxsize": 1, "egress_queue_length": 1,
            "egress_queue_byte_size": 0, "output_frame": None,
            "pilot_id": pilot_id, "pilot_topology": topology,
            "pilot_branches": list(branch_tuple),
        },
        "pipeline": {
            "pipeline_class": "savant_publication_runtime_v3.SavantPilotNvDsPipeline",
            "source": {"element": "uridecodebin", "properties": {"uri": source.as_uri()}},
            "elements": elements,
            "sink": [{"element": "devnull_sink"}],
        },
    }


def _hash_file(path: Path, blocker: str) -> tuple[int, str]:
    before = _regular_file(path, blocker)
    digest = hashlib.sha256()
    size = 0
    try:
        with path.open("rb", buffering=0) as handle:
            while True:
                chunk = handle.read(4 * 1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                digest.update(chunk)
        after = path.lstat()
    except OSError as exc:
        raise SavantPublicationImageRuntimeError(blocker) from exc
    _require(
        (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        and size == before.st_size,
        blocker,
    )
    return size, digest.hexdigest()


def execute_native_pilot(args: argparse.Namespace) -> dict[str, Any]:
    source = Path(args.source_file).resolve(strict=True)
    _, source_sha = _hash_file(source, "savant_pilot_source_pin_failed")
    _require(source_sha == args.source_sha256, "savant_pilot_source_digest_drifted")
    codec, dataset = _checked_codec_dataset(args.codec, args.dataset_id)
    topology = _checked_topology(args.topology_kind)
    branches = tuple(value for value in args.branches.split(",") if value)
    pilot_id = _checked_text(args.pilot_id, "savant_pilot_id_invalid")
    output = Path(args.output_dir).resolve(strict=True)
    _require(output.is_dir() and not output.is_symlink(), "savant_pilot_output_invalid")
    _require(not any(output.iterdir()), "savant_pilot_output_not_empty")
    config = build_pilot_module_config(
        source_file=source, pilot_id=pilot_id, topology_kind=topology,
        branches=branches, frame_limit=args.frame_limit,
    )
    config_payload = _canonical(config)
    config_sha = hashlib.sha256(config_payload).hexdigest()
    config_path = output / "pilot-module.json"
    _atomic_write(config_path, config_payload)
    observer = _PilotObserver(
        pilot_id=pilot_id, topology_kind=topology, branches=branches, frame_limit=args.frame_limit
    )
    _require(pilot_id not in _PILOT_OBSERVERS, "savant_pilot_id_duplicated")
    _PILOT_OBSERVERS[pilot_id] = observer
    try:
        try:
            from savant.entrypoint.main import main as savant_main
        except (ImportError, OSError) as exc:
            raise SavantPublicationImageRuntimeError("savant_sdk_not_available") from exc
        savant_main(config_path)
        observations = observer.result(frame_limit=args.frame_limit)
    finally:
        _PILOT_OBSERVERS.pop(pilot_id, None)
    receipt: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": PILOT_RECEIPT_KIND,
        "status": "completed_native_savant_pilot_nonpublication",
        "pilot_id": pilot_id,
        "topology_kind": topology,
        "branches": list(branches),
        "dataset_id": dataset,
        "codec": codec,
        "source_sha256": source_sha,
        "module_config_sha256": config_sha,
        "savant_version": SAVANT_VERSION,
        "deepstream_version": DEEPSTREAM_VERSION,
        "base_image_id": BASE_IMAGE_ID,
        "pipeline_class": "savant_publication_runtime_v3.SavantPilotNvDsPipeline",
        "callback_class": "savant_publication_runtime_v3.SavantPilotPrefixPlugin",
        "bounded_frame_limit": args.frame_limit,
        **observations,
        "accepted_measurement_evidence_emitted": False,
        "publication_ready": False,
        "receipt_payload_sha256": "",
    }
    receipt["receipt_payload_sha256"] = receipt_payload_sha256(receipt)
    _atomic_write(output / "pilot-receipt.json", _canonical(receipt))
    return receipt


def _add_runtime_file_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--python-module-root", required=True)
    parser.add_argument("--plugin-root", required=True)
    parser.add_argument("--model-binding-manifest", required=True)
    parser.add_argument("--runtime-binding", required=True)
    parser.add_argument("--analytics-execution-manifest", required=True)
    parser.add_argument("--analytics-model-manifest", required=True)
    parser.add_argument("--evidence-schema", required=True)
    parser.add_argument("--policy-calibration", required=True)
    parser.add_argument("--policy-capability-manifest", required=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vast_savant_checkpoint_runtime",
        description="Pinned Savant publication image runtime v3",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("capability")

    pilot = subparsers.add_parser("pilot")
    pilot.add_argument("--pilot-id", required=True)
    pilot.add_argument("--source-file", required=True)
    pilot.add_argument("--source-sha256", required=True)
    pilot.add_argument("--dataset-id", required=True)
    pilot.add_argument("--codec", choices=tuple(DATASET_BY_CODEC), required=True)
    pilot.add_argument("--topology-kind", choices=tuple(TOPOLOGY_SCENARIO), required=True)
    pilot.add_argument("--branches", required=True)
    pilot.add_argument("--frame-limit", type=int, required=True)
    pilot.add_argument("--output-dir", required=True)

    worker = subparsers.add_parser("worker")
    worker.add_argument("--module-id", required=True)
    worker.add_argument("--module-config", required=True)
    worker.add_argument("--module-config-sha256", required=True)
    worker.add_argument("--source-file", required=True)
    worker.add_argument("--source-sha256", required=True)
    worker.add_argument("--source-id", required=True)
    worker.add_argument("--stream-id", type=int, required=True)
    worker.add_argument("--dataset-id", required=True)
    worker.add_argument("--codec", choices=tuple(DATASET_BY_CODEC), required=True)
    worker.add_argument("--scenario", required=True)
    worker.add_argument("--topology-kind", choices=tuple(TOPOLOGY_SCENARIO), required=True)
    worker.add_argument("--branches", required=True)
    worker.add_argument("--policy", required=True)
    worker.add_argument("--deadline-ms", type=float, required=True)
    worker.add_argument("--duration-s", type=int, required=True)
    worker.add_argument("--run-id", required=True)
    worker.add_argument("--arm-id", required=True)
    worker.add_argument("--output-dir", required=True)
    worker.add_argument("--policy-socket", required=True)
    worker.add_argument("--analytics-execution-socket", required=True)
    worker.add_argument("--ready-timeout-s", type=float, required=True)
    worker.add_argument("--drain-timeout-s", type=float, required=True)
    _add_runtime_file_arguments(worker)

    finalizer = subparsers.add_parser("finalize")
    finalizer.add_argument("--runtime-output", required=True)
    finalizer.add_argument("--run-id", required=True)
    finalizer.add_argument("--arm-id", required=True)
    finalizer.add_argument("--scenario", required=True)
    finalizer.add_argument("--topology-kind", choices=tuple(TOPOLOGY_SCENARIO), required=True)
    finalizer.add_argument("--dataset-id", required=True)
    finalizer.add_argument("--codec", choices=tuple(DATASET_BY_CODEC), required=True)
    finalizer.add_argument("--policy", required=True)
    finalizer.add_argument("--deadline-ms", type=float, required=True)
    finalizer.add_argument("--module-count", type=int, required=True)
    finalizer.add_argument("--evidence-mapping-json", required=True)
    _add_runtime_file_arguments(finalizer)
    return parser


def _capability() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": "vast_savant_publication_image_capability_v3",
        "status": "materialized_pinned_savant_image_runtime",
        "runtime_abi": RUNTIME_ABI,
        "savant_version": SAVANT_VERSION,
        "deepstream_version": DEEPSTREAM_VERSION,
        "base_image_id": BASE_IMAGE_ID,
        "datasets": dict(DATASET_BY_CODEC),
        "topologies": {"independent_processes": 24, "shared_video_dag": 6},
        "worker_receipt_kind": WORKER_RECEIPT_KIND,
        "pilot_receipt_kind": PILOT_RECEIPT_KIND,
        "terminal_kind": TERMINAL_KIND,
    }


def execute_worker(_args: argparse.Namespace) -> dict[str, Any]:
    raise SavantPublicationImageRuntimeError(
        "savant_production_worker_external_execution_not_implemented"
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "capability":
            result = _capability()
        elif args.command == "pilot":
            result = execute_native_pilot(args)
        elif args.command == "worker":
            result = execute_worker(args)
        elif args.command == "finalize":
            try:
                mapping = json.loads(args.evidence_mapping_json)
            except json.JSONDecodeError as exc:
                raise SavantPublicationImageRuntimeError(
                    "savant_evidence_mapping_json_invalid"
                ) from exc
            result = finalize_runtime_output(
                runtime_output=Path(args.runtime_output).resolve(strict=True),
                run_id=args.run_id, arm_id=args.arm_id, scenario=args.scenario,
                topology_kind=args.topology_kind, dataset_id=args.dataset_id,
                codec=args.codec, policy=args.policy, deadline_ms=args.deadline_ms,
                module_count=args.module_count, evidence_mapping=mapping,
            )
        else:
            raise SavantPublicationImageRuntimeError("savant_image_command_invalid")
        sys.stdout.buffer.write(_canonical(result))
        sys.stdout.buffer.flush()
        return 0
    except (OSError, SavantPublicationImageRuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
