#!/usr/bin/env python3
"""Engineering-only native Savant 0.5.17 checkpoint module slice.

Uses supported ``zeromq_source_bin`` and ``NvDsPipeline`` APIs.  Nothing in
this file is accepted measurement evidence or a readiness promotion.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Mapping, Sequence

from checkpoint_savant_ingress import SAVANT_ADMISSION_TAGS, SavantSourceBinding
if TYPE_CHECKING:
    from checkpoint_savant_protocol_bridge import SavantProtocolBridge

BASELINE_TOPOLOGY = "independent_processes"
SHARED_TOPOLOGY = "shared_video_dag"
BRANCHES = ("plate_number", "vehicle_type", "damage", "foreign_object")
CLAIM_STATUS = "engineering_savant_native_module_nonpublication"
DESCRIPTOR_CLAIM_STATUS = "engineering_savant_module_descriptor_nonpublication"
BRIDGE_CLASS = "checkpoint_savant_protocol_bridge:SavantProtocolBridge"
PIPELINE_CLASS = "checkpoint_savant_native_module.SavantCheckpointNvDsPipeline"
DROP_REASON = "native_pre_detector_queue_full_drop_newest"
SAVANT_EVENT_ORIGIN = "savant_native_frame_callback"
SAVANT_FRAME_IDENTITY_KIND = "savant_native_frame_identity"
SAVANT_VERSION = "0.5.17"
_SHA = re.compile(r"^[0-9a-f]{64}$")
_MODULE = re.compile(
    r"^savant-stream-(?P<stream>[0-5])-(?:(?:branch-(?P<branch>plate_number|"
    r"vehicle_type|damage|foreign_object))|(?P<shared>shared-video-dag))$"
)
_INPUT_KEY = re.compile(
    r"^(?P<dataset>kpp_iss_publication_v3_h26[45]):(?P<stream>[0-5]):"
    r"(?P<sha>[0-9a-f]{64}):"
    r"(?P<cycle>[0-9]+):(?P<pts>[0-9]+)$"
)
_FD_CONTRACT = {
    "admission": "VAST_CHECKPOINT_ADMISSION_DATA_FD",
    "control": "VAST_CHECKPOINT_CONTROL_FD",
    "event": "VAST_CHECKPOINT_EVENT_FD",
    "policy": "VAST_CHECKPOINT_POLICY_FD",
    "status": "VAST_CHECKPOINT_STATUS_FD",
}


class SavantNativeModuleError(RuntimeError):
    """The native module contract failed closed."""


def _require(ok: bool, message: str) -> None:
    if not ok:
        raise SavantNativeModuleError(message)


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _descriptor_digest(value: Mapping[str, Any]) -> str:
    body = dict(value)
    supplied = body.pop("descriptor_sha256", None)
    digest = hashlib.sha256(_canonical(body).encode()).hexdigest()
    _require(supplied == digest, "Savant module descriptor SHA-256 drifted")
    return digest


@dataclass(frozen=True)
class SavantNativeModuleBinding:
    module_id: str
    descriptor_sha256: str
    topology_kind: str
    stream_id: int
    branches: tuple[str, ...]
    source_id: str
    codec: str
    dataset_id: str
    source_sha256: str
    source_duration_ns: int
    width: int
    height: int
    framerate: str
    source_socket: str
    module_socket: str
    policy: str
    deadline_ms: float
    bridge_class: str

    def validate(self) -> "SavantNativeModuleBinding":
        match = _MODULE.fullmatch(self.module_id)
        _require(match is not None, "Savant module_id is outside the frozen topology")
        _require(type(self.stream_id) is int and int(match.group("stream")) == self.stream_id,
                 "Savant module stream identity drifted")
        if self.topology_kind == BASELINE_TOPOLOGY:
            _require(match.group("branch") is not None and
                     self.branches == (match.group("branch"),),
                     "baseline Savant branch identity drifted")
        elif self.topology_kind == SHARED_TOPOLOGY:
            _require(match.group("shared") is not None and self.branches == BRANCHES,
                     "shared Savant route order drifted")
        else:
            raise SavantNativeModuleError("unsupported Savant native topology")
        _require(_SHA.fullmatch(self.descriptor_sha256) is not None,
                 "Savant descriptor SHA-256 is invalid")
        _require(self.bridge_class == BRIDGE_CLASS, "SavantProtocolBridge binding drifted")
        SavantSourceBinding(
            stream_id=self.stream_id, source_id=self.source_id, codec=self.codec,
            width=self.width, height=self.height, framerate=self.framerate,
            dataset_id=self.dataset_id, source_sha256=self.source_sha256,
            source_duration_ns=self.source_duration_ns,
            socket=self.source_socket,
        ).validate()
        _require(self.module_socket == self.source_socket.replace(
            "dealer+connect:", "router+bind:", 1),
            "Savant module/source IPC pairing drifted")
        _require(bool(self.policy) and float(self.deadline_ms) > 0,
                 "Savant policy/deadline binding is invalid")
        return self

    def to_json(self) -> str:
        body = dict(self.__dict__)
        body["branches"] = list(self.branches)
        body["deadline_ms"] = float(self.deadline_ms)
        return _canonical(body)

    @classmethod
    def from_json(cls, value: str) -> "SavantNativeModuleBinding":
        try:
            body = json.loads(value)
            _require(isinstance(body, Mapping), "Savant binding JSON is not an object")
            body = dict(body)
            body["branches"] = tuple(body.get("branches") or ())
            return cls(**body).validate()
        except (TypeError, json.JSONDecodeError) as exc:
            raise SavantNativeModuleError("Savant binding JSON fields drifted") from exc


def _build_binding(descriptor: Mapping[str, Any], source: Mapping[str, Any]) -> SavantNativeModuleBinding:
    digest = _descriptor_digest(descriptor)
    _require(descriptor.get("schema_version") == 1 and
             descriptor.get("artifact_kind") == "savant_checkpoint_module_descriptor" and
             descriptor.get("claim_status") == DESCRIPTOR_CLAIM_STATUS,
             "Savant descriptor header drifted")
    _require(descriptor.get("publication_ready") is False and
             descriptor.get("accepted_measurement_evidence_emitted") is False,
             "promoted Savant descriptor is prohibited")
    _require(descriptor.get("module_config_status") == "missing_not_built",
             "already promoted Savant module config is prohibited")
    _require(dict(descriptor.get("inherited_fd_contract") or {}) == _FD_CONTRACT,
             "Savant inherited-FD contract drifted")
    stream_id = int(descriptor.get("stream_id", -1))
    _require(int(source.get("stream_id", -2)) == stream_id,
             "Savant source stream drifted")
    source_sha = str(source.get("source_sha256", ""))
    _require(source_sha == descriptor.get("source_sha256"),
             "Savant source SHA-256 drifted")
    codec = str(descriptor.get("codec", "")).lower()
    _require(codec in {"h264", "h265"} and
             str(source.get("source_codec", "")).lower() == codec,
             "Savant source codec drifted")
    module_id = str(descriptor.get("module_id", ""))
    source_socket = (
        f"dealer+connect:ipc:///tmp/vast-savant-{digest[:16]}/"
        f"module-{module_id}.ipc"
    )
    return SavantNativeModuleBinding(
        module_id=module_id, descriptor_sha256=digest,
        topology_kind=str(descriptor.get("topology_kind", "")), stream_id=stream_id,
        branches=tuple(str(x) for x in descriptor.get("branches") or ()),
        source_id=str(source.get("source_id", "")), codec=codec,
        dataset_id=str(descriptor.get("dataset", "")), source_sha256=source_sha,
        source_duration_ns=int(source.get("source_duration_ns", 0)),
        width=int(source.get("width", 0)), height=int(source.get("height", 0)),
        framerate="600/1", source_socket=source_socket,
        module_socket=source_socket.replace("dealer+connect:", "router+bind:", 1),
        policy=str(descriptor.get("policy", "")),
        deadline_ms=float(descriptor.get("deadline_ms", 0)),
        bridge_class=str(descriptor.get("bridge_class", "")),
    ).validate()


def _route(branch: str) -> dict[str, Any]:
    return {
        "branch": branch,
        "fanout_name": f"vast_savant_route_fanout_{branch}",
        "queue_name": f"vast_savant_route_queue_{branch}",
        "terminal_name": f"vast_savant_route_terminal_{branch}",
        "max_size_buffers": 1, "leaky": "upstream", "drop_policy": "drop_newest",
    }


def build_native_module_artifact(descriptor: Mapping[str, Any], source: Mapping[str, Any]) -> dict[str, Any]:
    """Generate one exact JSON-as-YAML Savant module configuration."""
    binding = _build_binding(descriptor, source)
    binding_json = binding.to_json()
    routes = [_route(branch) for branch in binding.branches]
    topology = {
        "topology_kind": binding.topology_kind,
        "route_count": len(routes),
        "shared_prefix": [
            "zeromq_source_bin", "savant_rs_video_decode_bin:nvv4l2decoder",
            "nvstreammux", "nvvideoconvert",
            "capsfilter:video/x-raw,format=RGB", "tee",
        ] if binding.topology_kind == SHARED_TOPOLOGY else [
            "zeromq_source_bin", "savant_rs_video_decode_bin:nvv4l2decoder",
            "nvstreammux", "nvvideoconvert",
            "capsfilter:video/x-raw,format=RGB",
        ],
        "routes": routes, "descriptor_sha256": binding.descriptor_sha256,
        "publication_ready": False,
    }
    prefix = {
        "element": "pyfunc", "name": "vast_savant_native_prefix",
        "module": "checkpoint_savant_pyfunc_v3",
        "class_name": "SavantNativePrefixPlugin",
        "kwargs": {"binding_json": binding_json},
    }
    elements = [prefix]
    config = {
        "name": binding.module_id,
        "parameters": {
            # Keep exact KPP geometry; Savant's default alignment is eight.
            "frame": {"width": binding.width, "height": binding.height,
                      "geometry_base": 1},
            "batch_size": 1, "max_parallel_streams": 6,
            # All 24 baseline modules share one container network namespace.
            # Pin distinct ports instead of inheriting Savant's global 8080.
            "webserver_port": 18080 + binding.stream_id * 5 + (
                4 if binding.topology_kind == SHARED_TOPOLOGY
                else BRANCHES.index(binding.branches[0])
            ),
            "min_fps": "600/1", "max_fps": "600/1", "max_fps_control": False,
            "queue_maxsize": 1, "egress_queue_length": 1,
            "egress_queue_byte_size": 0, "output_frame": None,
            "shutdown_auth": f"vast-savant-{binding.descriptor_sha256}",
            "checkpoint_native_topology": topology,
            "checkpoint_binding_json": binding_json,
        },
        "pipeline": {
            "pipeline_class": PIPELINE_CLASS,
            "source": {
                "element": "zeromq_source_bin",
                "properties": {
                    "socket": binding.module_socket, "source-id": binding.source_id,
                    "source-timeout": 60, "ingress-queue-length": 1,
                    "ingress-queue-byte-size": 67_108_864,
                    "decoder-queue-length": 1,
                    "decoder-queue-byte-size": 67_108_864,
                    "low-latency-decoding": False,
                },
                "ingress_frame_filter": {
                    "module": "checkpoint_savant_pyfunc_v3",
                    "class_name": "SavantAdmissionIngressFilter",
                    "kwargs": {"binding_json": binding_json},
                },
            },
            "elements": elements,
            "sink": [{"element": "devnull_sink"}],
        },
    }
    config_json = _canonical(config)
    return {
        "schema_version": 1, "artifact_kind": "savant_native_module_config",
        "claim_status": CLAIM_STATUS, "module_id": binding.module_id,
        "descriptor_sha256": binding.descriptor_sha256,
        "binding_json": binding_json, "source_socket": binding.source_socket,
        "module_socket": binding.module_socket, "module_config": config,
        "module_config_json": config_json,
        "module_config_sha256": hashlib.sha256(config_json.encode()).hexdigest(),
        "accepted_measurement_evidence_emitted": False, "publication_ready": False,
    }


def build_native_module_matrix(descriptors: Sequence[Mapping[str, Any]], sources: Mapping[int, Mapping[str, Any]]) -> list[dict[str, Any]]:
    _require(bool(descriptors), "Savant native descriptor matrix is empty")
    artifacts = [build_native_module_artifact(row, sources[int(row["stream_id"])])
                 for row in descriptors]
    topologies = {str(row.get("topology_kind", "")) for row in descriptors}
    _require(len(topologies) == 1, "Savant native matrix mixes topologies")
    topology = next(iter(topologies))
    expected = 24 if topology == BASELINE_TOPOLOGY else 6
    _require(len(artifacts) == expected, f"Savant {topology} requires exactly {expected} modules")
    _require(len({row["module_id"] for row in artifacts}) == expected,
             "Savant module identities are not unique")
    _require({int(row["stream_id"]) for row in descriptors} == set(range(6)),
             "Savant native matrix does not cover six streams")
    return artifacts


_RUNTIME_LOCK = threading.RLock()
_RUNTIMES: dict[str, Any] = {}


def register_native_runtime(descriptor_sha256: str, runtime: Any) -> None:
    _require(_SHA.fullmatch(descriptor_sha256) is not None,
             "Savant native runtime key is invalid")
    _require(callable(getattr(runtime, "admit_video_frame", None)),
             "Savant native runtime lacks admission binding")
    with _RUNTIME_LOCK:
        _require(descriptor_sha256 not in _RUNTIMES,
                 "Savant native runtime was registered twice")
        _RUNTIMES[descriptor_sha256] = runtime


def unregister_native_runtime(descriptor_sha256: str, runtime: Any) -> None:
    with _RUNTIME_LOCK:
        _require(_RUNTIMES.get(descriptor_sha256) is runtime,
                 "Savant native runtime teardown identity drifted")
        del _RUNTIMES[descriptor_sha256]


def _runtime(binding: SavantNativeModuleBinding) -> Any:
    with _RUNTIME_LOCK:
        value = _RUNTIMES.get(binding.descriptor_sha256)
    _require(value is not None, "Savant native runtime is not registered; publication fails closed")
    return value


def _attribute_value(attribute: Any) -> Any:
    _require(attribute is not None, "Savant admission attribute is missing")
    values = getattr(attribute, "values", None)
    _require(isinstance(values, list) and len(values) == 1,
             "Savant admission attribute is not scalar")
    value = values[0]
    raw_json = getattr(value, "json", None)
    if isinstance(raw_json, str):
        try:
            tagged = json.loads(raw_json).get("value")
            _require(isinstance(tagged, Mapping) and len(tagged) == 1,
                     "Savant AttributeValue JSON drifted")
            return next(iter(tagged.values()))
        except (json.JSONDecodeError, AttributeError) as exc:
            raise SavantNativeModuleError("Savant AttributeValue JSON is invalid") from exc
    return getattr(value, "value", value)


def _frame_tags(frame: Any) -> dict[str, Any]:
    getter = getattr(frame, "get_attribute", None)
    _require(callable(getter), "Savant frame lacks native attribute API")
    tags = {name: _attribute_value(getter("default", name))
            for name in SAVANT_ADMISSION_TAGS}
    attributes = getattr(frame, "attributes", None)
    if attributes is not None:
        names = tuple(name for namespace, name in attributes
                      if namespace == "default" and str(name).startswith("vast."))
        _require(names == SAVANT_ADMISSION_TAGS,
                 "Savant admission attributes are not the exact eight persistent tags")
    return tags


def _validate_frame(frame: Any, binding: SavantNativeModuleBinding) -> dict[str, Any]:
    _require(getattr(frame, "source_id", None) == binding.source_id,
             "Savant ingress source_id drifted")
    _require(getattr(frame, "codec", None) == ("hevc" if binding.codec == "h265" else "h264"),
             "Savant ingress native codec drifted")
    _require(getattr(frame, "width", None) == binding.width and
             getattr(frame, "height", None) == binding.height,
             "Savant ingress dimensions drifted")
    _require(str(getattr(frame, "framerate", "")) == binding.framerate,
             "Savant ingress framerate drifted")
    _require(tuple(getattr(frame, "time_base", ())) == (1, 1_000_000_000),
             "Savant ingress time base drifted")
    content = getattr(frame, "content", None)
    if isinstance(content, tuple):
        external = content == ("zeromq", None)
    else:
        external = (bool(getattr(content, "is_external", lambda: False)()) and
                    getattr(content, "get_method", lambda: None)() == "zeromq" and
                    getattr(content, "get_location", lambda: None)() is None)
    _require(external, "Savant frame content is not external zeromq")
    tags = _frame_tags(frame)
    _require(tags["vast.event_provenance"] == "native_common_source_coordinator",
             "Savant admission provenance drifted")
    for field in ("vast.access_unit_pts_ns", "vast.transport_pts_ns",
                  "vast.source_cycle", "vast.sequence"):
        _require(type(tags[field]) is int and tags[field] >= 0,
                 f"Savant admission {field} is invalid")
    _require(tags["vast.sequence"] > 0 and
             tags["vast.transport_pts_ns"] == int(getattr(frame, "pts", -1)),
             "Savant admission transport timeline drifted")
    _require(_SHA.fullmatch(str(tags["vast.payload_sha256"])) is not None,
             "Savant admission payload SHA-256 is invalid")
    match = _INPUT_KEY.fullmatch(str(tags["vast.input_frame_key"]))
    _require(match is not None and match.group("dataset") == binding.dataset_id and
             int(match.group("stream")) == binding.stream_id and
             match.group("sha") == binding.source_sha256 and
             int(match.group("cycle")) == tags["vast.source_cycle"] and
             int(match.group("pts")) == tags["vast.access_unit_pts_ns"],
             "Savant admission input_frame_key drifted")
    return tags


try:
    from savant.base.frame_filter import BaseFrameFilter as _FrameFilterBase
except (ImportError, OSError):
    class _FrameFilterBase:  # type: ignore[no-redef]
        def __init__(self, **_: Any) -> None:
            pass


class SavantAdmissionIngressFilter(_FrameFilterBase):
    """Fail closed before decode unless exact common admission is present."""

    def __init__(self, *, binding_json: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.binding = SavantNativeModuleBinding.from_json(binding_json)

    def __call__(self, video_frame: Any) -> bool:
        _validate_frame(video_frame, self.binding)
        _runtime(self.binding).admit_video_frame(video_frame, self.binding)
        return True


def build_native_frame_identity(*, binding: SavantNativeModuleBinding,
                                frame_meta: Any, decoder_factory: str,
                                decoder_gpu_id: int,
                                mux_gst_buffer_pts_ns: int) -> dict[str, Any]:
    _require(type(mux_gst_buffer_pts_ns) is int
             and 0 <= mux_gst_buffer_pts_ns < (1 << 64) - 1,
             "Savant native mux GstBuffer PTS is missing or invalid")
    tags = _validate_frame(frame_meta.video_frame, binding)
    native = getattr(frame_meta, "frame_meta", None)
    _require(native is not None, "Savant native NvDsFrameMeta is missing")
    source_id = int(getattr(native, "source_id", -1))
    frame_num = int(getattr(native, "frame_num", -1))
    buf_pts = int(getattr(native, "buf_pts", -1))
    _require(source_id == binding.stream_id,
             "Savant native NvDs source_id does not bind the frozen stream")
    _require(frame_num >= 0, "Savant native NvDs frame_num is invalid")
    _require(buf_pts == int(tags["vast.transport_pts_ns"]),
             "Savant native NvDs buf_pts drifted")
    _require(decoder_factory == "nvv4l2decoder" and decoder_gpu_id == 0,
             "Savant native decoder placement drifted")
    frame_id = int(tags["vast.sequence"]) - 1
    return {
        "schema_version": 1, "artifact_kind": SAVANT_FRAME_IDENTITY_KIND,
        "savant_version": SAVANT_VERSION, "module_id": binding.module_id,
        "module_frame_id": frame_id, "event_origin": SAVANT_EVENT_ORIGIN,
        "admission_id": str(tags["vast.admission_id"]),
        "input_frame_key": str(tags["vast.input_frame_key"]),
        "stream_id": binding.stream_id, "frame_id": frame_id,
        "transport_pts_ns": int(tags["vast.transport_pts_ns"]),
        "payload_sha256": str(tags["vast.payload_sha256"]),
        "nvds_source_id": source_id, "nvds_frame_num": frame_num,
        "nvds_buf_pts_ns": buf_pts, "decoder_factory": decoder_factory,
        "mux_gst_buffer_pts_ns": mux_gst_buffer_pts_ns,
        "decoder_gpu_id": decoder_gpu_id,
    }


class SavantProtocolNativeRuntime:
    """Runtime context invoking the existing SavantProtocolBridge."""
    publication_ready = False
    accepted_measurement_evidence_emitted = False

    def __init__(self, *, bridge: "SavantProtocolBridge", branch_executor: Any) -> None:
        from checkpoint_savant_protocol_bridge import SavantProtocolBridge

        _require(isinstance(bridge, SavantProtocolBridge), "Savant bridge is invalid")
        _require(callable(branch_executor), "Savant branch executor is missing")
        self.bridge = bridge
        self.branch_executor = branch_executor
        self._decoder: tuple[str, int] | None = None
        self._route_condition = threading.Condition()
        self._route_terminals: dict[str, set[str]] = {}
        self._pending_routes: dict[str, list[str]] = {
            branch: [] for branch in BRANCHES
        }

    def bind_decoder(self, factory: str, gpu_id: int) -> None:
        _require(self._decoder is None, "Savant native decoder was bound twice")
        _require(factory == "nvv4l2decoder" and gpu_id == 0,
                 "Savant native decoder placement drifted")
        self._decoder = (factory, gpu_id)

    def admit_transport_frame(self, frame: Any, **kwargs: Any) -> None:
        self.bridge.admit_transport_frame(frame, **kwargs)

    def admit_video_frame(self, frame: Any, binding: SavantNativeModuleBinding) -> None:
        _validate_frame(frame, binding)

    def _identity(self, binding: SavantNativeModuleBinding, frame_meta: Any,
                  buffer: Any) -> dict[str, Any]:
        _require(self._decoder is not None, "Savant decoder was not physically observed")
        return build_native_frame_identity(
            binding=binding, frame_meta=frame_meta,
            mux_gst_buffer_pts_ns=getattr(buffer, "pts", None),
            decoder_factory=self._decoder[0], decoder_gpu_id=self._decoder[1])

    def observe_prefix(self, buffer: Any, frame_meta: Any,
                       binding: SavantNativeModuleBinding) -> None:
        identity = self._identity(binding, frame_meta, buffer)
        self.bridge.observe_decoded_frame(identity)
        self.bridge.observe_preprocessed_frame(identity)
        with self._route_condition:
            for branch in binding.branches:
                if binding.topology_kind == SHARED_TOPOLOGY:
                    self.bridge.observe_fanout(identity, branch=branch)
                self._pending_routes[branch].append(identity["input_frame_key"])

    def observe_route(self, buffer: Any, frame_meta: Any,
                      binding: SavantNativeModuleBinding, branch: str) -> None:
        identity = self._identity(binding, frame_meta, buffer)
        with self._route_condition:
            pending = self._pending_routes[branch]
            _require(bool(pending) and pending.pop(0) == identity["input_frame_key"],
                     "Savant native route queue order drifted")
        result = self.branch_executor(buffer, frame_meta, binding, branch)
        self.bridge.bind_branch_tensor(identity, branch=branch,
                                       tensor_spec=result["tensor_spec"])
        self.bridge.execute_branch(
            identity["input_frame_key"], branch,
            tensor_payload=result["tensor_payload"], queue_depths=result["queue_depths"],
            deadline_monotonic_ns=result["deadline_monotonic_ns"])
        with self._route_condition:
            terminals = self._route_terminals.setdefault(identity["input_frame_key"], set())
            _require(branch not in terminals, "Savant route terminal was duplicated")
            terminals.add(branch)
            self._route_condition.notify_all()

    def await_route_join(self, input_frame_key: str,
                         binding: SavantNativeModuleBinding) -> None:
        expected = set(binding.branches)
        with self._route_condition:
            ok = self._route_condition.wait_for(
                lambda: self._route_terminals.get(input_frame_key, set()) == expected,
                timeout=max(1.0, float(binding.deadline_ms) / 1000.0 * 4.0),
            )
            _require(ok, "Savant native route join timed out")
            del self._route_terminals[input_frame_key]

    def drop_route(self, frame_meta: Any, binding: SavantNativeModuleBinding,
                   branch: str, *, buffer: Any) -> None:
        identity = self._identity(binding, frame_meta, buffer)
        self.bridge.drop_branch(identity["input_frame_key"], branch, reason=DROP_REASON)

    def queue_overrun(self, *, branch: str, queue_name: str,
                      current_level_buffers: int,
                      binding: SavantNativeModuleBinding) -> None:
        _require(branch in binding.branches and queue_name.endswith(branch) and
                 current_level_buffers >= 1,
                 "Savant native queue overrun observation drifted")
        with self._route_condition:
            pending = self._pending_routes[branch]
            _require(bool(pending), "Savant native queue drop has no causal frame")
            key = pending.pop()
            self.bridge.drop_branch(key, branch, reason=DROP_REASON)
            terminals = self._route_terminals.setdefault(key, set())
            _require(branch not in terminals, "Savant route terminal was duplicated")
            terminals.add(branch)
            self._route_condition.notify_all()


class SavantEngineeringCanaryRuntime:
    """Identity-only pilot observer; never usable as benchmark evidence."""
    publication_ready = False
    accepted_measurement_evidence_emitted = False

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._decoder: tuple[str, int] | None = None
        self._admitted: set[str] = set()
        self._decoded: set[str] = set()
        self._terminals: set[tuple[str, str]] = set()
        self._pending: dict[str, list[str]] = {branch: [] for branch in BRANCHES}
        self._drops = 0

    def bind_decoder(self, factory: str, gpu_id: int) -> None:
        _require(self._decoder is None and factory == "nvv4l2decoder" and gpu_id == 0,
                 "Savant canary decoder placement drifted")
        self._decoder = (factory, gpu_id)

    def admit_video_frame(self, frame: Any, binding: SavantNativeModuleBinding) -> None:
        tags = _validate_frame(frame, binding)
        key = str(tags["vast.input_frame_key"])
        _require(key not in self._admitted, "Savant canary admission duplicated")
        self._admitted.add(key)

    def _identity(self, binding: SavantNativeModuleBinding, frame_meta: Any,
                  buffer: Any) -> dict[str, Any]:
        _require(self._decoder is not None, "Savant canary decoder was not observed")
        return build_native_frame_identity(
            binding=binding, frame_meta=frame_meta,
            mux_gst_buffer_pts_ns=getattr(buffer, "pts", None),
            decoder_factory=self._decoder[0], decoder_gpu_id=self._decoder[1])

    def observe_prefix(self, buffer: Any, frame_meta: Any,
                       binding: SavantNativeModuleBinding) -> None:
        identity = self._identity(binding, frame_meta, buffer)
        key = str(identity["input_frame_key"])
        _require(key in self._admitted and key not in self._decoded,
                 "Savant canary decode identity drifted")
        self._decoded.add(key)
        for branch in binding.branches:
            self._pending[branch].append(key)

    def observe_route(self, buffer: Any, frame_meta: Any,
                      binding: SavantNativeModuleBinding, branch: str) -> None:
        identity = self._identity(binding, frame_meta, buffer)
        key = str(identity["input_frame_key"])
        terminal = (key, branch)
        _require(bool(self._pending[branch]) and self._pending[branch].pop(0) == key,
                 "Savant canary queue order drifted")
        _require(key in self._decoded and terminal not in self._terminals,
                 "Savant canary route terminal drifted")
        with self._condition:
            self._terminals.add(terminal)
            self._condition.notify_all()

    def queue_overrun(self, *, branch: str, queue_name: str,
                      current_level_buffers: int,
                      binding: SavantNativeModuleBinding) -> None:
        _require(branch in binding.branches and queue_name.endswith(branch) and
                 current_level_buffers >= 1 and bool(self._pending[branch]),
                 "Savant canary queue overrun drifted")
        key = self._pending[branch].pop()
        terminal = (key, branch)
        _require(terminal not in self._terminals, "Savant canary terminal duplicated")
        with self._condition:
            self._terminals.add(terminal)
            self._drops += 1
            self._condition.notify_all()

    def await_route_join(self, input_frame_key: str,
                         binding: SavantNativeModuleBinding) -> None:
        with self._condition:
            ok = self._condition.wait_for(
                lambda: {branch for key, branch in self._terminals
                         if key == input_frame_key} == set(binding.branches),
                timeout=max(1.0, float(binding.deadline_ms) / 1000.0 * 4.0),
            )
            _require(ok, "Savant canary route join incomplete")

    def receipt(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "artifact_kind": "savant_native_module_engineering_canary",
            "claim_status": CLAIM_STATUS,
            "admitted_frames": len(self._admitted),
            "decoded_frames": len(self._decoded),
            "branch_terminals": len(self._terminals),
            "branch_drops": self._drops,
            "decoder_factory": self._decoder[0] if self._decoder else None,
            "decoder_gpu_id": self._decoder[1] if self._decoder else None,
            "accepted_measurement_evidence_emitted": False,
            "publication_ready": False,
        }


try:
    from savant.base.pyfunc import BasePyFuncPlugin as _BasePyFuncPlugin
    from savant.deepstream.pyfunc import NvDsPyFuncPlugin as _PyFuncBase
except (ImportError, OSError):
    class _BasePyFuncPlugin:  # type: ignore[no-redef]
        def __init__(self, **_: Any) -> None:
            pass

    class _PyFuncBase:  # type: ignore[no-redef]
        def __init__(self, **_: Any) -> None:
            pass


class SavantNativePrefixPlugin(_PyFuncBase):
    def __init__(self, *, binding_json: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.binding = SavantNativeModuleBinding.from_json(binding_json)
        self._decoder_observation: tuple[str, int] | None = None

    def _observe_decoder(self, runtime: Any) -> None:
        if self._decoder_observation is not None:
            return
        root = self.gst_element.get_parent()
        while root.get_parent() is not None:
            root = root.get_parent()
        iterator = root.iterate_recurse()
        decoders = []
        while True:
            result, element = iterator.next()
            if result == Gst.IteratorResult.OK:
                factory = element.get_factory()
                if factory is not None and factory.get_name() == "nvv4l2decoder":
                    decoders.append(element)
            elif result == Gst.IteratorResult.DONE:
                break
            elif result == Gst.IteratorResult.RESYNC:
                iterator.resync()
            else:
                raise SavantNativeModuleError("Savant decoder graph iteration failed")
        _require(len(decoders) == 1,
                 "Savant native graph does not contain exactly one nvv4l2decoder")
        decoder = decoders[0]
        gpu_id = int(decoder.get_property("gpu-id")) if decoder.find_property("gpu-id") else 0
        _require(gpu_id == 0, "Savant native decoder GPU binding drifted")
        _require(callable(getattr(runtime, "bind_decoder", None)),
                 "Savant runtime lacks decoder placement callback")
        runtime.bind_decoder("nvv4l2decoder", gpu_id)
        graph_callback = getattr(runtime, "bind_loaded_graph", None)
        if callable(graph_callback):
            graph_callback(
                root=root,
                decoder=decoder,
                prefix_element=self.gst_element,
            )
        self._decoder_observation = ("nvv4l2decoder", gpu_id)

    def process_frame(self, buffer: Any, frame_meta: Any) -> None:
        runtime = _runtime(self.binding)
        _require(callable(getattr(runtime, "observe_prefix", None)),
                 "Savant runtime lacks prefix callback")
        self._observe_decoder(runtime)
        runtime.observe_prefix(buffer, frame_meta, self.binding)


class SavantNativeRoutePlugin(_PyFuncBase):
    def __init__(self, *, binding_json: str, branch: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.binding = SavantNativeModuleBinding.from_json(binding_json)
        _require(branch in self.binding.branches, "Savant route branch drifted")
        self.branch = branch

    def process_frame(self, buffer: Any, frame_meta: Any) -> None:
        runtime = _runtime(self.binding)
        _require(callable(getattr(runtime, "observe_route", None)),
                 "Savant runtime lacks route callback")
        runtime.observe_route(buffer, frame_meta, self.binding, self.branch)
        if (self.binding.topology_kind == SHARED_TOPOLOGY and
                self.branch == self.binding.branches[-1]):
            identity = runtime._identity(self.binding, frame_meta, buffer)
            _require(callable(getattr(runtime, "await_route_join", None)),
                     "Savant runtime lacks physical route join")
            runtime.await_route_join(identity["input_frame_key"], self.binding)


class SavantNativeRouteBufferPlugin(_BasePyFuncPlugin):
    """Post-demux terminal that does not depend on removed NvDs batch metadata."""

    def __init__(self, *, binding_json: str, branch: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.binding = SavantNativeModuleBinding.from_json(binding_json)
        _require(branch in self.binding.branches, "Savant route branch drifted")
        self.branch = branch

    def process_buffer(self, buffer: Any) -> None:
        _require(int(getattr(buffer, "pts", -1)) >= 0,
                 "Savant route buffer PTS is invalid")
        runtime = _runtime(self.binding)
        _require(
            Gst is not None and getattr(self, "gst_element", None) is not None,
            "Savant post-demux GStreamer element is unavailable",
        )
        pad = self.gst_element.get_static_pad("sink")
        _require(pad is not None,
                 "Savant post-demux terminal sink pad is missing")
        caps = pad.get_current_caps()
        _require(caps is not None,
                 "Savant post-demux negotiated caps are missing")
        sample = Gst.Sample.new(buffer, caps, None, None)
        _require(sample is not None,
                 "Savant post-demux Gst.Sample allocation failed")
        callback = getattr(runtime, "observe_route_buffer", None)
        _require(callable(callback), "Savant runtime lacks post-demux route callback")
        callback(buffer, self.binding, self.branch, sample=sample, caps=caps)


try:
    from savant.config.schema import PipelineElement, PyFuncElement
    from savant.deepstream.element_factory import NvDsElementFactory as _NvDsElementFactory
    from savant.deepstream.pipeline import NvDsPipeline as _NvDsPipeline
    from savant.gstreamer import Gst
    from savant.gstreamer.utils import (
        gst_post_stream_failed_error as _gst_post_stream_failed_error,
    )
except (ImportError, OSError):
    PipelineElement = PyFuncElement = None  # type: ignore[assignment]
    Gst = None  # type: ignore[assignment]
    _gst_post_stream_failed_error = None

    class _NvDsPipeline:  # type: ignore[no-redef]
        def __init__(self, *_: Any, **__: Any) -> None:
            raise SavantNativeModuleError("Savant 0.5.17 NvDsPipeline API is unavailable")


    class _NvDsElementFactory:  # type: ignore[no-redef]
        @staticmethod
        def create_nvvideoconvert(element: Any) -> Any:
            raise SavantNativeModuleError("Savant 0.5.17 element factory is unavailable")


class _CheckpointNvDsElementFactory(_NvDsElementFactory):
    @staticmethod
    def create_nvvideoconvert(element: Any) -> Any:
        # Savant 0.5.17 defaults to CUDA unified memory on x86. Its managed
        # allocations cause severe conversion overhead under WSL. This graph
        # reads pixels only after the explicit RGB host conversion, so both
        # the stock source converter and our output converter can use device
        # allocations. Keep the upstream factory unchanged for other graphs.
        configured = replace(
            element,
            properties={**element.properties, "nvbuf-memory-type": 2},
        )
        return _NvDsElementFactory.create_nvvideoconvert(configured)


class SavantCheckpointNvDsPipeline(_NvDsPipeline):
    """NvDsPipeline with exact stream-index binding and physical shared tee."""

    _element_factory = _CheckpointNvDsElementFactory()

    def __init__(self, name: str, pipeline_cfg: Any, **kwargs: Any) -> None:
        binding_json = kwargs.get("checkpoint_binding_json")
        topology = kwargs.get("checkpoint_native_topology")
        _require(isinstance(binding_json, str) and isinstance(topology, Mapping),
                 "Savant native NvDsPipeline binding is missing")
        self.checkpoint_binding = SavantNativeModuleBinding.from_json(binding_json)
        self.checkpoint_topology = dict(topology)
        super().__init__(name, pipeline_cfg, **kwargs)

    def _add_sink(self, *args: Any, **kwargs: Any) -> Any:
        result = super()._add_sink(*args, **kwargs)
        stream_id = self.checkpoint_binding.stream_id
        _require(stream_id in self._free_pad_indices,
                 "Savant NvDs stream index cannot be allocated natively")
        self._free_pad_indices.remove(stream_id)
        self._free_pad_indices.insert(0, stream_id)
        return result

    def _add_source_output(self, source_info: Any, *args: Any, **kwargs: Any) -> Any:
        self._check_pipeline_is_running()
        output_sink = super()._add_source_output(
            source_info, link_to_demuxer=False,
            source_output=kwargs.get("source_output"),
            buffer_processor=kwargs.get("buffer_processor"))

        converter = self.add_element(PipelineElement(
            "nvvideoconvert",
            name=f"vast_savant_rgb_converter_{self.checkpoint_binding.stream_id}"),
            link=False)
        rgb_caps = self.add_element(PipelineElement(
            "capsfilter",
            name=f"vast_savant_rgb_caps_{self.checkpoint_binding.stream_id}",
            properties={"caps": "video/x-raw,format=RGB"}),
            link=False)
        _require(converter.link(rgb_caps),
                 "Savant native RGB conversion link failed")
        self._link_demuxer_src_pad(converter.get_static_pad("sink"), source_info)
        converter.sync_state_with_parent()
        rgb_caps.sync_state_with_parent()
        source_info.after_demuxer.extend([converter, rgb_caps])

        tee = None
        if self.checkpoint_binding.topology_kind == SHARED_TOPOLOGY:
            tee = self.add_element(PipelineElement(
                "tee",
                name=f"vast_savant_shared_tee_{self.checkpoint_binding.stream_id}"),
                link=False)
            _require(rgb_caps.link(tee),
                     "Savant native RGB prefix/tee link failed")
            tee.sync_state_with_parent()
            source_info.after_demuxer.append(tee)

        routes = list(self.checkpoint_topology.get("routes") or ())
        _require(
            tuple(str(route.get("branch")) for route in routes)
            == self.checkpoint_binding.branches,
            "Savant physical route order drifted")
        for index, route in enumerate(routes):
            branch = str(route["branch"])
            queue = self.add_element(PipelineElement(
                "vastcheckpointbranchqueue", name=str(route["queue_name"]),
                properties={"max-size-buffers": 1}), link=False)
            queue.connect("buffer-dropped", self._on_queue_buffer_dropped, branch)
            if tee is not None:
                queue_sink = queue.get_static_pad("sink")
                _require(queue_sink is not None,
                         "Savant shared route queue sink is unavailable")
                probe_id = queue_sink.add_probe(
                    Gst.PadProbeType.BUFFER, self._on_queue_buffer_probe, (queue, branch))
                _require(probe_id > 0, "Savant shared queue-entry probe was not installed")
            # Official pyfunc pads accept NVMM/RGBA, not this RGB CPU prefix.
            # Identity hands the real negotiated buffer to the same callback.
            plugin = self.add_element(PipelineElement(
                "identity", name=str(route["terminal_name"]),
                properties={"signal-handoffs": True, "silent": True}),
                link=False)
            terminal = SavantNativeRouteBufferPlugin(
                binding_json=self.checkpoint_binding.to_json(), branch=branch)
            terminal.gst_element = plugin
            plugin.connect("handoff", self._on_rgb_route_handoff, terminal)
            _require(queue.link(plugin), "Savant native route queue link failed")
            if tee is None:
                _require(rgb_caps.link(queue),
                         "Savant native baseline route link failed")
            else:
                tee_pad = tee.request_pad_simple("src_%u")
                _require(
                    tee_pad is not None
                    and tee_pad.link(queue.get_static_pad("sink"))
                    == Gst.PadLinkReturn.OK,
                    "Savant native tee route link failed")
            queue.sync_state_with_parent()
            plugin.sync_state_with_parent()
            source_info.after_demuxer.extend([queue, plugin])
            if tee is None or index == len(routes) - 1:
                _require(plugin.get_static_pad("src").link(output_sink) == Gst.PadLinkReturn.OK,
                         "Savant native owner route output link failed")
            else:
                sink = self.add_element(PipelineElement(
                    "fakesink", name=f"vast_savant_route_sink_{branch}",
                    properties={"sync": 0, "qos": 0, "enable-last-sample": 0}),
                    link=False)
                _require(plugin.link(sink), "Savant native route sink link failed")
                sink.sync_state_with_parent()
                source_info.after_demuxer.append(sink)
        return output_sink

    def _on_rgb_route_handoff(self, element: Any, buffer: Any,
                              terminal: SavantNativeRouteBufferPlugin) -> None:
        try:
            terminal.process_buffer(buffer)
        except Exception as error:
            # PyGObject otherwise prints signal exceptions and continues flow.
            # Report a native bus error so Savant stops the failed pipeline.
            _require(callable(_gst_post_stream_failed_error),
                     "Savant RGB route cannot report a native stream failure")
            _gst_post_stream_failed_error(
                gst_element=element, frame=None, file_path=__file__,
                text="Savant RGB route callback failed",
                debug=f"{type(error).__name__}: {error}"[:4096],
            )

    def _on_queue_buffer_probe(self, pad: Any, info: Any,
                               route: tuple[Any, str]) -> Any:
        queue, branch = route
        try:
            buffer = info.get_buffer()
            _require(buffer is not None, "Savant queue-entry probe has no buffer")
            runtime = _runtime(self.checkpoint_binding)
            callback = getattr(runtime, "observe_queue_buffer", None)
            _require(callable(callback),
                     "Savant shared queue lacks native fanout observation")
            callback(buffer, self.checkpoint_binding, branch, caps=pad.get_current_caps())
            return Gst.PadProbeReturn.OK
        except Exception as error:
            _require(callable(_gst_post_stream_failed_error),
                     "Savant queue-entry probe cannot report a stream failure")
            _gst_post_stream_failed_error(
                gst_element=queue, frame=None, file_path=__file__,
                text="Savant native queue-entry callback failed",
                debug=f"{type(error).__name__}: {error}"[:4096],
            )
            return Gst.PadProbeReturn.DROP

    def _on_queue_buffer_dropped(self, queue: Any, transport_pts_ns: int,
                                 branch: str) -> bool:
        try:
            runtime = _runtime(self.checkpoint_binding)
            callback = getattr(runtime, "queue_dropped", None)
            _require(callable(callback),
                     "Savant native queue lacks causal drop callback")
            callback(
                branch=branch, queue_name=queue.get_name(),
                transport_pts_ns=transport_pts_ns, binding=self.checkpoint_binding,
            )
            return True
        except Exception as error:
            _require(callable(_gst_post_stream_failed_error),
                     "Savant native queue cannot report a stream failure")
            _gst_post_stream_failed_error(
                gst_element=queue, frame=None, file_path=__file__,
                text="Savant native queue drop callback failed",
                debug=f"{type(error).__name__}: {error}"[:4096],
            )
            return False


__all__ = [
    "BASELINE_TOPOLOGY", "BRANCHES", "SHARED_TOPOLOGY",
    "SavantAdmissionIngressFilter", "SavantCheckpointNvDsPipeline",
    "SavantNativeModuleBinding", "SavantNativeModuleError",
    "SavantNativePrefixPlugin", "SavantNativeRoutePlugin",
    "SavantNativeRouteBufferPlugin",
    "SavantProtocolNativeRuntime", "SavantEngineeringCanaryRuntime",
    "build_native_frame_identity",
    "build_native_module_artifact", "build_native_module_matrix",
    "register_native_runtime", "unregister_native_runtime",
]
