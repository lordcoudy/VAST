from __future__ import annotations

import hashlib
import sys
import unittest
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from checkpoint_deepstream_sdk_runtime import AdmissionTransportFrame, MISSING_TIMESTAMP  # noqa: E402
from checkpoint_savant_ingress import (  # noqa: E402
    SAVANT_ADMISSION_TAGS,
    SavantIngressError,
    SavantNativeIngress,
    SavantSourceBinding,
    build_savant_video_frame_record,
)


@dataclass
class FakeVideoFrame:
    source_id: str
    framerate: str
    width: int
    height: int
    pts: int
    keyframe: bool
    content: bytes
    codec: str
    dts: int | None
    duration: int | None
    tags: dict
    time_base: tuple[int, int]


class FakeRunner:
    def __init__(self) -> None:
        self.sent: list[tuple[FakeVideoFrame, bytes]] = []
        self.eos: list[str] = []

    def send(self, source, send_eos=True):
        self.sent.append(source)
        if send_eos:
            raise AssertionError("per-frame EOS is prohibited")
        return {"status": "ok"}

    def send_eos(self, source_id: str):
        self.eos.append(source_id)
        return {"status": "ok"}


def frame(*, keyframe: bool = True, dts: int = MISSING_TIMESTAMP) -> AdmissionTransportFrame:
    payload = b"\x00\x00\x00\x01\x65native-savant"
    return AdmissionTransportFrame(
        sequence=1,
        keyframe=keyframe,
        source_cycle=2,
        access_unit_pts_ns=90_000,
        transport_pts_ns=20_000_090_000,
        access_unit_dts_ns=dts,
        duration_ns=33_333_333,
        admission_id="run-savant:3:admission:1",
        input_frame_key=(
            "kpp_iss_publication_v3_h264:3:" + "a" * 64 + ":2:90000"
        ),
        payload_sha256=hashlib.sha256(payload).hexdigest(),
        payload=payload,
    )


def binding() -> SavantSourceBinding:
    return SavantSourceBinding(
        stream_id=3,
        source_id="kpp_plate_avi-stream-3",
        codec="h264",
        width=1920,
        height=1080,
        framerate="600/1",
        dataset_id="kpp_iss_publication_v3_h264",
        source_sha256="a" * 64,
        socket="dealer+connect:ipc:///tmp/vast-savant-run/module-3.ipc",
    )


class SavantIngressTests(unittest.TestCase):
    def test_vastau01_maps_byte_exactly_to_native_savant_frame(self) -> None:
        value = build_savant_video_frame_record(frame(), binding())
        self.assertEqual(value.source_id, "kpp_plate_avi-stream-3")
        self.assertEqual(value.codec, "h264")
        self.assertEqual(value.pts, 20_000_090_000)
        self.assertIsNone(value.dts)
        self.assertEqual(value.duration, 33_333_333)
        self.assertEqual(value.time_base, (1, 1_000_000_000))
        self.assertTrue(value.keyframe)
        self.assertEqual(value.content, ("zeromq", None))
        self.assertEqual(set(value.tags), set(SAVANT_ADMISSION_TAGS))
        self.assertEqual(value.tags["vast.admission_id"], frame().admission_id)
        self.assertEqual(value.tags["vast.input_frame_key"], frame().input_frame_key)
        self.assertEqual(value.tags["vast.payload_sha256"], frame().payload_sha256)
        self.assertEqual(value.tags["vast.access_unit_pts_ns"], frame().access_unit_pts_ns)
        self.assertEqual(value.tags["vast.transport_pts_ns"], frame().transport_pts_ns)
        self.assertEqual(value.tags["vast.source_cycle"], frame().source_cycle)
        self.assertEqual(value.tags["vast.sequence"], 1)
        self.assertEqual(value.tags["vast.event_provenance"], "native_common_source_coordinator")

    def test_native_ingress_uses_source_runner_without_per_frame_eos(self) -> None:
        runner = FakeRunner()
        ingress = SavantNativeIngress(
            binding=binding(),
            runner=runner,
            frame_builder=lambda **kwargs: FakeVideoFrame(**kwargs),
        )
        receipt = ingress.send_frame(frame(keyframe=False, dts=80_000))
        self.assertEqual(receipt["claim_status"], "engineering_savant_native_ingress_nonpublication")
        self.assertEqual(receipt["sequence"], 1)
        self.assertEqual(receipt["payload_sha256"], frame().payload_sha256)
        self.assertFalse(receipt["publication_ready"])
        self.assertEqual(len(runner.sent), 1)
        native, content = runner.sent[0]
        self.assertEqual(content, frame().payload)
        self.assertEqual(native.content, ("zeromq", None))
        self.assertFalse(native.keyframe)
        self.assertEqual(native.dts, 20_000_080_000)
        self.assertEqual(native.pts, 20_000_090_000)
        ingress.finish()
        self.assertEqual(runner.eos, ["kpp_plate_avi-stream-3"])

    def test_wrong_stream_dataset_codec_or_payload_fails_closed(self) -> None:
        value = frame()
        for change in (
            {
                "input_frame_key": (
                    "kpp_iss_publication_v3_h264:4:"
                    + "a" * 64
                    + ":2:90000"
                )
            },
            {"input_frame_key": "other:3:" + "a" * 64 + ":2:90000"},
            {
                "input_frame_key": (
                    "kpp_iss_publication_v3_h264:3:"
                    + "b" * 64
                    + ":2:90000"
                )
            },
            {"payload_sha256": "0" * 64},
        ):
            with self.subTest(change=change), self.assertRaises(SavantIngressError):
                build_savant_video_frame_record(
                    AdmissionTransportFrame(**{**value.__dict__, **change}),
                    binding(),
                )
        with self.assertRaises(SavantIngressError):
            build_savant_video_frame_record(value, SavantSourceBinding(
                **{**binding().__dict__, "codec": "h265"}
            ))

    def test_binding_rejects_nonlocal_or_alias_socket_and_invalid_source(self) -> None:
        for socket in (
            "tcp://127.0.0.1:5000",
            "dealer+connect:ipc:///tmp/../etc/vast.ipc",
            "dealer+connect:ipc://relative.ipc",
        ):
            with self.subTest(socket=socket), self.assertRaises(SavantIngressError):
                SavantSourceBinding(**{**binding().__dict__, "socket": socket}).validate()
        with self.assertRaises(SavantIngressError):
            SavantSourceBinding(**{**binding().__dict__, "source_id": "generic-uri"}).validate()


if __name__ == "__main__":
    unittest.main()
