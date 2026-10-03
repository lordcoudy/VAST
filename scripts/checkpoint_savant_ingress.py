#!/usr/bin/env python3
"""Byte-exact VASTAU01 to native Savant SourceRunner ingress.

This adapter preserves the native admission identity and compressed access
unit inside an official Savant VideoFrame and sends it over a local IPC
endpoint. It does not implement topology routing, accepted resource evidence,
or publication.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol, Sequence

from checkpoint_deepstream_sdk_runtime import (
    MISSING_TIMESTAMP,
    AdmissionTransportFrame,
    read_admission_transport_frame,
)


CLAIM_STATUS = "engineering_savant_native_ingress_nonpublication"
SAVANT_ADMISSION_TAGS = (
    "vast.admission_id",
    "vast.input_frame_key",
    "vast.payload_sha256",
    "vast.access_unit_pts_ns",
    "vast.transport_pts_ns",
    "vast.source_cycle",
    "vast.sequence",
    "vast.event_provenance",
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SOURCE_ID_RE = re.compile(r"^kpp_(?:plate|underbody)_avi-stream-(?P<stream>[0-5])$")
_INPUT_KEY_RE = re.compile(
    r"^(?P<dataset>kpp_iss_publication_v3_h26[45]):(?P<stream>[0-5]):"
    r"(?P<source_sha>[0-9a-f]{64}):(?P<cycle>[0-9]+):(?P<pts>[0-9]+)$"
)
_LOCAL_SOCKET_RE = re.compile(
    r"^dealer[+]connect:ipc:///tmp/vast-savant-[A-Za-z0-9._-]{1,96}/"
    r"module-[A-Za-z0-9._-]{1,96}[.]ipc$"
)


class SavantIngressError(RuntimeError):
    """The local native Savant ingress contract failed closed."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SavantIngressError(message)


class SavantSourceRunner(Protocol):
    def send(self, source: Any, send_eos: bool = True) -> Any: ...
    def send_eos(self, source_id: str) -> Any: ...
    def send_shutdown(self, zmq_topic: str, auth: str) -> Any: ...


@dataclass(frozen=True)
class SavantSourceBinding:
    stream_id: int
    source_id: str
    codec: str
    width: int
    height: int
    framerate: str
    dataset_id: str
    source_sha256: str
    source_duration_ns: int
    socket: str

    def validate(self) -> "SavantSourceBinding":
        _require(type(self.stream_id) is int and 0 <= self.stream_id < 6,
                 "Savant ingress stream_id is invalid")
        match = _SOURCE_ID_RE.fullmatch(self.source_id)
        _require(match is not None and int(match.group("stream")) == self.stream_id,
                 "Savant ingress source_id is outside the frozen KPP streams")
        _require(self.codec in {"h264", "h265"}, "Savant ingress codec is invalid")
        _require(
            self.dataset_id == f"kpp_iss_publication_v3_{self.codec}",
            "Savant ingress dataset/codec binding drifted",
        )
        _require(type(self.width) is int and self.width > 0
                 and type(self.height) is int and self.height > 0,
                 "Savant ingress dimensions are invalid")
        _require(self.framerate == "600/1", "Savant ingress framerate drifted")
        _require(_SHA256_RE.fullmatch(self.source_sha256) is not None,
                 "Savant ingress source SHA-256 is invalid")
        _require(
            type(self.source_duration_ns) is int and self.source_duration_ns > 0,
            "Savant ingress source duration is invalid",
        )
        _require(_LOCAL_SOCKET_RE.fullmatch(self.socket) is not None,
                 "Savant ingress socket must be a dedicated local IPC endpoint")
        return self


@dataclass(frozen=True)
class SavantVideoFrameRecord:
    source_id: str
    framerate: str
    width: int
    height: int
    pts: int
    keyframe: bool
    content: tuple[str, None]
    codec: str
    dts: int | None
    duration: int | None
    tags: dict[str, bool | int | float | str]
    time_base: tuple[int, int]


def build_savant_video_frame_record(
    frame: AdmissionTransportFrame,
    binding: SavantSourceBinding,
) -> SavantVideoFrameRecord:
    """Validate one delivery and preserve its native timeline and content."""

    checked = binding.validate()
    _require(isinstance(frame, AdmissionTransportFrame), "invalid VASTAU01 frame")
    _require(hashlib.sha256(frame.payload).hexdigest() == frame.payload_sha256,
             "Savant ingress payload digest mismatch")
    match = _INPUT_KEY_RE.fullmatch(frame.input_frame_key)
    _require(match is not None, "Savant ingress input_frame_key is invalid")
    _require(
        match.group("dataset") == checked.dataset_id
        and int(match.group("stream")) == checked.stream_id
        and match.group("source_sha") == checked.source_sha256
        and int(match.group("cycle")) == frame.source_cycle
        and int(match.group("pts")) == frame.access_unit_pts_ns,
        "Savant ingress admission/source identity drifted",
    )
    _require(frame.sequence > 0 and frame.transport_pts_ns >= frame.access_unit_pts_ns,
             "Savant ingress timeline is invalid")
    dts: int | None = None
    if frame.access_unit_dts_ns != MISSING_TIMESTAMP:
        dts = (
            int(frame.source_cycle) * checked.source_duration_ns
            + int(frame.access_unit_dts_ns)
        )
        _require(dts >= 0, "Savant ingress scaled DTS is negative")
    duration = None if frame.duration_ns == 0 else int(frame.duration_ns)
    tags: dict[str, bool | int | float | str] = {
        "vast.admission_id": frame.admission_id,
        "vast.input_frame_key": frame.input_frame_key,
        "vast.payload_sha256": frame.payload_sha256,
        "vast.access_unit_pts_ns": frame.access_unit_pts_ns,
        "vast.transport_pts_ns": frame.transport_pts_ns,
        "vast.source_cycle": frame.source_cycle,
        "vast.sequence": frame.sequence,
        "vast.event_provenance": "native_common_source_coordinator",
    }
    _require(tuple(tags) == SAVANT_ADMISSION_TAGS, "Savant admission tag order drifted")
    return SavantVideoFrameRecord(
        source_id=checked.source_id,
        framerate=checked.framerate,
        width=checked.width,
        height=checked.height,
        pts=frame.transport_pts_ns,
        keyframe=frame.keyframe,
        content=("zeromq", None),
        codec="hevc" if checked.codec == "h265" else "h264",
        dts=dts,
        duration=duration,
        tags=tags,
        time_base=(1, 1_000_000_000),
    )


class SavantNativeIngress:
    """Send exact records through an already constructed Savant SourceRunner."""

    publication_ready = False
    accepted_measurement_evidence_emitted = False

    def __init__(
        self,
        *,
        binding: SavantSourceBinding,
        runner: SavantSourceRunner,
        frame_builder: Callable[..., Any],
        shutdown_auth: str | None = None,
    ) -> None:
        self.binding = binding.validate()
        _require(callable(getattr(runner, "send", None))
                 and callable(getattr(runner, "send_eos", None)),
                 "Savant SourceRunner is invalid")
        _require(callable(frame_builder), "Savant VideoFrame builder is invalid")
        if shutdown_auth is not None:
            _require(
                type(shutdown_auth) is str
                and re.fullmatch(r"vast-savant-[0-9a-f]{64}", shutdown_auth) is not None,
                "Savant module shutdown authority is invalid",
            )
            _require(callable(getattr(runner, "send_shutdown", None)),
                     "Savant SourceRunner shutdown capability is missing")
        self.runner = runner
        self.frame_builder = frame_builder
        self._shutdown_auth = shutdown_auth
        self._last_sequence = 0
        self._finished = False

    def send_frame(self, frame: AdmissionTransportFrame) -> dict[str, Any]:
        _require(not self._finished, "Savant ingress is already closed")
        record = build_savant_video_frame_record(frame, self.binding)
        _require(frame.sequence == self._last_sequence + 1,
                 "Savant ingress sequence is not gap-free")
        native = self.frame_builder(**record.__dict__)
        result = self.runner.send((native, bytes(frame.payload)), send_eos=False)
        status = (
            result.get("status")
            if isinstance(result, Mapping)
            else getattr(result, "status", None)
        )
        _require(status == "ok", "Savant SourceRunner rejected an admitted frame")
        self._last_sequence = frame.sequence
        return {
            "schema_version": 1,
            "artifact_kind": "savant_native_ingress_receipt",
            "claim_status": CLAIM_STATUS,
            "stream_id": self.binding.stream_id,
            "sequence": frame.sequence,
            "admission_id": frame.admission_id,
            "input_frame_key": frame.input_frame_key,
            "payload_sha256": frame.payload_sha256,
            "source_runner_status": status,
            "accepted_measurement_evidence_emitted": False,
            "publication_ready": False,
        }

    def finish(self) -> None:
        _require(not self._finished, "Savant ingress EOS was duplicated")
        result = self.runner.send_eos(self.binding.source_id)
        status = (
            result.get("status")
            if isinstance(result, Mapping)
            else getattr(result, "status", None)
        )
        _require(status == "ok", "Savant SourceRunner rejected EOS")
        self._finished = True
        if self._shutdown_auth is not None:
            # EOS ends one source, not the official Savant module. An owned
            # worker must request authenticated shutdown after that EOS so its
            # main thread can return and commit DRAINED before the deadline.
            # Never replay EOS if the shutdown transport subsequently fails.
            result = self.runner.send_shutdown(
                self.binding.source_id, self._shutdown_auth
            )
            status = (
                result.get("status")
                if isinstance(result, Mapping)
                else getattr(result, "status", None)
            )
            _require(status == "ok", "Savant SourceRunner rejected Shutdown")


class _CheckedSavantWriter:
    """Keep the pinned SDK from turning a native send timeout into status=ok."""

    def __init__(self, writer: Any, *, successful_result_types: tuple[type, ...]) -> None:
        self._writer = writer
        self._successful_result_types = successful_result_types

    def send_message(self, topic: str, message: Any, content: bytes = b"") -> Any:
        result = self._writer.send_message(topic, message, content)
        # Savant 0.5.17 SourceRunner discards this return value and reports ok.
        # Check the actual Rust outcome for frames, EOS, and Shutdown alike.
        # Do not retry an ambiguous delivery or fabricate a successful receipt.
        _require(
            type(result) in self._successful_result_types,
            "Savant ZeroMQ writer did not confirm delivery: " + type(result).__name__,
        )
        return result

    def shutdown(self) -> None:
        self._writer.shutdown()


def _native_dependencies() -> tuple[Callable[..., Any], Callable[[str], SavantSourceRunner]]:
    try:
        from savant.api.builder import build_video_frame
        from savant.client import SourceBuilder
        from savant_rs.zmq import WriterResultAck, WriterResultSuccess
    except ImportError as exc:
        raise SavantIngressError("Savant 0.5.17 native client API is unavailable") from exc

    def source(socket: str) -> SavantSourceRunner:
        runner = (
            SourceBuilder()
            .with_socket(socket)
            .with_telemetry_disabled()
            .build()
        )
        # Instance-local adapter for the exact pinned 0.5.17 SDK, not a global
        # patch. Its initialized writer and transport settings stay unchanged.
        writer = getattr(runner, "_writer", None)
        _require(callable(getattr(writer, "send_message", None))
                 and callable(getattr(writer, "shutdown", None)),
                 "Savant SourceRunner native writer contract drifted")
        runner._writer = _CheckedSavantWriter(
            writer, successful_result_types=(WriterResultAck, WriterResultSuccess)
        )
        return runner

    return build_video_frame, source


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="VASTAU01 to native Savant ingress")
    parser.add_argument("--admission-fd", type=int, default=None)
    parser.add_argument("--binding-json", required=True)
    args = parser.parse_args(argv)
    try:
        raw = json.loads(args.binding_json)
        _require(isinstance(raw, Mapping), "Savant binding JSON is not an object")
        binding = SavantSourceBinding(**dict(raw)).validate()
        admission_fd = (
            args.admission_fd
            if args.admission_fd is not None
            else int(os.environ["VAST_CHECKPOINT_ADMISSION_DATA_FD"])
        )
        _require(admission_fd >= 0, "Savant admission FD is invalid")
        frame_builder, source_factory = _native_dependencies()
        ingress = SavantNativeIngress(
            binding=binding,
            runner=source_factory(binding.socket),
            frame_builder=frame_builder,
        )
        while True:
            frame = read_admission_transport_frame(admission_fd)
            if frame is None:
                break
            ingress.send_frame(frame)
        ingress.finish()
    except (KeyError, TypeError, ValueError, SavantIngressError) as exc:
        print(str(exc), file=os.sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
