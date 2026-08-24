from __future__ import annotations

import hashlib
import inspect
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import extract_kpp_legacy_iss as extractor  # noqa: E402
import freeze_kpp_legacy_iss_v2_transcodes as freezer  # noqa: E402
from freeze_kpp_legacy_iss_v2_transcodes import (  # noqa: E402
    TranscodeFreezeError,
    _freeze_transcodes_with_test_adapters,
    build_ffmpeg_command,
    freeze_transcodes,
    main,
)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        + "\n"
    ).encode("ascii")


def _extraction_receipt_hash(value: dict[str, object]) -> str:
    return hashlib.sha256(
        b"VAST:kpp-legacy-iss-extraction-receipt:v1\0" + _canonical_bytes(value)
    ).hexdigest()


def _transcode_receipt_hash(value: dict[str, object]) -> str:
    return hashlib.sha256(
        b"VAST:kpp-legacy-iss-v2-transcode-receipt:v1\0"
        + _canonical_bytes(value)
    ).hexdigest()


def _make_tools(root: Path) -> tuple[dict[str, object], dict[str, bytes]]:
    ffmpeg = root / "ffmpeg.exe"
    ffprobe = root / "ffprobe.exe"
    ffmpeg.write_bytes(b"pinned-ffmpeg-binary")
    ffprobe.write_bytes(b"pinned-ffprobe-binary")
    versions = {
        ffmpeg.name: b"ffmpeg version pinned\n",
        ffprobe.name: b"ffprobe version pinned\n",
    }
    arguments: dict[str, object] = {
        "ffmpeg": ffmpeg,
        "expected_ffmpeg_sha256": _sha256(ffmpeg.read_bytes()),
        "expected_ffmpeg_version_sha256": _sha256(versions[ffmpeg.name]),
        "ffprobe": ffprobe,
        "expected_ffprobe_sha256": _sha256(ffprobe.read_bytes()),
        "expected_ffprobe_version_sha256": _sha256(versions[ffprobe.name]),
    }
    return arguments, versions


def _write_authoritative_extraction(
    root: Path,
) -> tuple[Path, Path, Path, bytes, bytes]:
    extraction_dir = root / "staging" / "extracted"
    extraction_dir.mkdir(parents=True)
    underbody_payload = b"authoritative-underbody-avi"
    front_payload = b"authoritative-front-avi"
    underbody = extraction_dir / "iss_v2_underbody.avi"
    front = extraction_dir / "iss_v2_front_gate.avi"
    underbody.write_bytes(underbody_payload)
    front.write_bytes(front_payload)
    outputs = [
        {
            "role": "underbody",
            "path": underbody.relative_to(root).as_posix(),
            "size_bytes": len(underbody_payload),
            "sha256": _sha256(underbody_payload),
            "media": {
                "codec_name": "mjpeg",
                "width": 1700,
                "height": 236,
                "r_frame_rate": "200/1",
                "avg_frame_rate": "200/1",
                "frame_count": 11882,
                "duration_ns": 59_410_000_000,
            },
        },
        {
            "role": "front_gate",
            "path": front.relative_to(root).as_posix(),
            "size_bytes": len(front_payload),
            "sha256": _sha256(front_payload),
            "media": {
                "codec_name": "h264",
                "width": 1920,
                "height": 1080,
                "r_frame_rate": "25/1",
                "avg_frame_rate": "25/1",
                "frame_count": 1380,
                "duration_ns": 55_200_000_000,
            },
        },
    ]
    receipt: dict[str, object] = {
        "schema_version": 1,
        "artifact_kind": "vast_kpp_legacy_iss_extraction_receipt",
        "generation_id": "kpp_legacy_iss_v2",
        "status": "headless_stream_copy_candidate",
        "source_archives": [
            {
                "archive_logical_id": "13._03",
                "size_bytes": 1,
                "sha256": "1" * 64,
                "role": "underbody",
                "payload_offset": 1313,
            },
            {
                "archive_logical_id": "13._03_2",
                "size_bytes": 1,
                "sha256": "2" * 64,
                "role": "front_gate",
                "payload_offset": 278,
            },
        ],
        "tools": [
            {
                "role": "ffmpeg",
                "executable_sha256": "3" * 64,
                "version_output_sha256": "4" * 64,
            },
            {
                "role": "ffprobe",
                "executable_sha256": "5" * 64,
                "version_output_sha256": "6" * 64,
            },
        ],
        "recipes": [
            {
                "role": "underbody",
                "demuxer": "mjpeg",
                "source_fps": 200,
                "payload_offset": 1313,
                "codec_mode": "stream_copy",
                "container": "avi",
            },
            {
                "role": "front_gate",
                "demuxer": "h264",
                "source_fps": 25,
                "payload_offset": 278,
                "codec_mode": "stream_copy",
                "container": "avi",
            },
        ],
        "outputs": outputs,
        "claims": {
            "source_bytes_externally_pinned": True,
            "source_private_snapshots_verified": True,
            "tool_bytes_and_version_outputs_externally_pinned": True,
            "payload_offsets_detected": True,
            "video_payloads_stream_copied": True,
            "output_set_directory_published_atomically": True,
            "windows_project_root_staging_and_working_directory_handle_custody_validated": True,
            "source_timestamps_preserved": False,
            "archiveplayer_export_reproduced": False,
            "v1_dataset_identity_equivalent": False,
            "accuracy_ground_truth_validated": False,
            "publication_authorized": False,
        },
    }
    receipt["extraction_receipt_sha256"] = _extraction_receipt_hash(receipt)
    receipt_path = extraction_dir / "kpp_iss_v2_extraction_receipt.json"
    receipt_path.write_bytes(_canonical_bytes(receipt))
    return receipt_path, underbody, front, underbody_payload, front_payload


def _probe_for(path: Path) -> dict[str, object]:
    name = path.name
    if name.endswith(".avi"):
        if "underbody" in name:
            return {
                "codec_name": "mjpeg",
                "pix_fmt": "yuvj422p",
                "width": 1700,
                "height": 236,
                "r_frame_rate": "200/1",
                "avg_frame_rate": "200/1",
                "frame_count": 11882,
                "duration_ns": 59_410_000_000,
            }
        return {
            "codec_name": "h264",
            "pix_fmt": "yuv420p",
            "width": 1920,
            "height": 1080,
            "r_frame_rate": "25/1",
            "avg_frame_rate": "25/1",
            "frame_count": 1380,
            "duration_ns": 55_200_000_000,
        }
    codec = "hevc" if "h265" in path.parts else "h264"
    role = "underbody" if "underbody" in name else "front_gate"
    width = 1700 if role == "underbody" else 1920
    height = 236 if role == "underbody" else 1080
    frame_count = 35646 if role == "underbody" else 33120
    return {
        "codec_name": codec,
        "pix_fmt": "yuv420p",
        "width": width,
        "height": height,
        "r_frame_rate": "600/1",
        "avg_frame_rate": "600/1",
        "frame_count": frame_count,
        "duration_ns": 59_410_000_000 if role == "underbody" else 55_200_000_000,
        "decoded_frame_count": frame_count,
        "decoded_frame_signatures": [
            {
                "width": width,
                "height": height,
                "pix_fmt": "yuv420p",
                "color_range": "tv",
            }
        ],
        "stream_time_base": "1/600",
        "stream_duration_ts": frame_count,
        "decoded_first_pts": 0,
        "decoded_last_pts": frame_count - 1,
        "decoded_pts_steps": [1],
    }


class FreezeKppLegacyIssV2TranscodesTests(unittest.TestCase):
    def test_public_wrapper_selects_authoritative_adapters_internally(self) -> None:
        values = {
            "project_root": Path("project"),
            "extraction_receipt": Path("receipt.json"),
            "expected_extraction_receipt_file_sha256": "0" * 64,
            "underbody_avi": Path("underbody.avi"),
            "front_avi": Path("front.avi"),
            "output_dir": Path("staging/transcodes"),
            "ffmpeg": Path("ffmpeg.exe"),
            "expected_ffmpeg_sha256": "1" * 64,
            "expected_ffmpeg_version_sha256": "2" * 64,
            "ffprobe": Path("ffprobe.exe"),
            "expected_ffprobe_sha256": "3" * 64,
            "expected_ffprobe_version_sha256": "4" * 64,
        }
        with mock.patch.object(
            freezer,
            "_freeze_transcodes_impl",
            autospec=True,
            return_value={"status": "captured"},
        ) as implementation:
            self.assertEqual(
                freeze_transcodes(**values), {"status": "captured"}
            )
        implementation.assert_called_once_with(**values, test_adapters=None)

    def test_command_pins_limited_range_and_exact_underbody_timeline(self) -> None:
        root = Path("C:/fixture")
        source = root / "source.avi"
        target = root / "target.mp4"

        command = build_ffmpeg_command(
            source=source,
            target=target,
            codec_variant="h264",
            role="underbody",
            ffmpeg="pinned-ffmpeg",
        )

        self.assertEqual(command[command.index("-reinit_filter:v") + 1], "0")
        self.assertEqual(
            command[command.index("-vf") + 1],
            (
                "scale=w=1700:h=236:in_range=auto:out_range=tv,"
                "format=pix_fmts=yuv420p,"
                "fps=fps=600:start_time=0:round=near:eof_action=round"
            ),
        )
        self.assertEqual(command[command.index("-color_range") + 1], "tv")
        self.assertEqual(command[command.index("-r") + 1], "600")
        self.assertEqual(command[command.index("-fps_mode") + 1], "cfr")
        self.assertEqual(command[command.index("-enc_time_base:v") + 1], "1:600")
        self.assertEqual(command[command.index("-frames:v") + 1], "35646")
        self.assertEqual(
            command[command.index("-video_track_timescale") + 1], "600"
        )
        self.assertEqual(
            command[command.index("-bsf:v") + 1],
            "h264_metadata=video_full_range_flag=0",
        )

    def test_rejects_any_decoded_output_frame_outside_contract(self) -> None:
        value = _probe_for(
            Path("C:/fixture/h264/iss_v2_underbody.mp4")
        )
        value["decoded_frame_count"] = 35646
        value["decoded_frame_signatures"] = [
            {
                "width": 1700,
                "height": 236,
                "pix_fmt": "yuv420p",
                "color_range": "tv",
            },
            {
                "width": 1700,
                "height": 300,
                "pix_fmt": "yuv420p",
                "color_range": "tv",
            },
        ]

        with self.assertRaisesRegex(
            TranscodeFreezeError, "decoded frame contract mismatch"
        ):
            freezer._validate_output_probe("underbody", "h264", value)

    def test_rejects_non_contiguous_decoded_output_pts(self) -> None:
        value = _probe_for(
            Path("C:/fixture/h264/iss_v2_underbody.mp4")
        )
        value["decoded_pts_steps"] = [1, 2]

        with self.assertRaisesRegex(
            TranscodeFreezeError, "decoded frame PTS contract mismatch"
        ):
            freezer._validate_output_probe("underbody", "h264", value)

    def test_probe_summarizes_every_decoded_frame_and_pts(self) -> None:
        payload = {
            "streams": [
                {
                    "codec_name": "h264",
                    "pix_fmt": "yuv420p",
                    "width": 1700,
                    "height": 236,
                    "r_frame_rate": "600/1",
                    "avg_frame_rate": "600/1",
                    "nb_frames": "3",
                    "nb_read_frames": "3",
                    "duration": "0.005000",
                    "time_base": "1/600",
                    "duration_ts": "3",
                }
            ],
            "frames": [
                {
                    "pts": index,
                    "width": 1700,
                    "height": 236,
                    "pix_fmt": "yuv420p",
                    "color_range": "tv",
                }
                for index in range(3)
            ],
        }
        completed = freezer.subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps(payload).encode("utf-8"),
            stderr=b"",
        )
        with mock.patch.object(
            freezer.subprocess, "run", autospec=True, return_value=completed
        ) as run:
            observed = freezer._probe(
                Path("C:/fixture/output.mp4"),
                ffprobe=Path("C:/fixture/ffprobe.exe"),
            )

        command = run.call_args.args[0]
        self.assertIn("-show_frames", command)
        self.assertIn(
            "frame=pts,width,height,pix_fmt,color_range",
            command[command.index("-show_entries") + 1],
        )
        self.assertEqual(observed["decoded_frame_count"], 3)
        self.assertEqual(observed["stream_time_base"], "1/600")
        self.assertEqual(observed["stream_duration_ts"], 3)
        self.assertEqual(observed["decoded_first_pts"], 0)
        self.assertEqual(observed["decoded_last_pts"], 2)
        self.assertEqual(observed["decoded_pts_steps"], [1])
        self.assertEqual(
            observed["decoded_frame_signatures"],
            [
                {
                    "width": 1700,
                    "height": 236,
                    "pix_fmt": "yuv420p",
                    "color_range": "tv",
                }
            ],
        )

    def test_builds_the_four_exact_repository_recipe_commands(self) -> None:
        root = Path("C:/fixture")
        source = root / "source.avi"
        target = root / "target.mp4"
        self.assertEqual(
            build_ffmpeg_command(
                source=source,
                target=target,
                codec_variant="h264",
                role="underbody",
                ffmpeg="pinned-ffmpeg",
            ),
            (
                "pinned-ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-reinit_filter:v",
                "0",
                "-i",
                str(source),
                "-vf",
                (
                    "scale=w=1700:h=236:in_range=auto:out_range=tv,"
                    "format=pix_fmts=yuv420p,"
                    "fps=fps=600:start_time=0:round=near:eof_action=round"
                ),
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "23",
                "-pix_fmt",
                "yuv420p",
                "-color_range",
                "tv",
                "-r",
                "600",
                "-fps_mode",
                "cfr",
                "-enc_time_base:v",
                "1:600",
                "-frames:v",
                "35646",
                "-video_track_timescale",
                "600",
                "-bsf:v",
                "h264_metadata=video_full_range_flag=0",
                str(target),
            ),
        )
        h265 = build_ffmpeg_command(
            source=source,
            target=target,
            codec_variant="h265",
            role="front_gate",
            ffmpeg="pinned-ffmpeg",
        )
        self.assertEqual(h265[h265.index("-c:v") + 1], "libx265")
        self.assertEqual(h265[h265.index("-preset") + 1], "ultrafast")
        self.assertEqual(h265[h265.index("-crf") + 1], "30")
        self.assertEqual(h265[h265.index("-frames:v") + 1], "33120")
        self.assertEqual(
            h265[h265.index("-bsf:v") + 1],
            "hevc_metadata=video_full_range_flag=0",
        )
        self.assertEqual(
            h265[h265.index("-vf") + 1],
            (
                "scale=w=1920:h=1080:in_range=auto:out_range=tv,"
                "format=pix_fmts=yuv420p,"
                "fps=fps=600:start_time=0:round=near:eof_action=round"
            ),
        )

    def test_rejects_missing_or_wrong_codec_bitstream_filters(self) -> None:
        cases = (
            ("h264", None),
            ("h264", "h264_metadata=video_full_range_flag=1"),
            ("h264", "hevc_metadata=video_full_range_flag=0"),
            ("h265", None),
            ("h265", "hevc_metadata=video_full_range_flag=1"),
            ("h265", "h264_metadata=video_full_range_flag=0"),
        )
        for variant, observed_filter in cases:
            with self.subTest(variant=variant, observed_filter=observed_filter):
                recipe = dict(freezer.TRANSCODE_RECIPES[variant])
                if observed_filter is None:
                    recipe.pop("bitstream_filter", None)
                else:
                    recipe["bitstream_filter"] = observed_filter
                with mock.patch.dict(
                    freezer.TRANSCODE_RECIPES,
                    {variant: recipe},
                    clear=False,
                ):
                    with self.subTest(consumer="command"):
                        with self.assertRaisesRegex(
                            TranscodeFreezeError,
                            f"{variant} bitstream filter contract mismatch",
                        ):
                            build_ffmpeg_command(
                                source=Path("C:/fixture/source.avi"),
                                target=Path("C:/fixture/target.mp4"),
                                codec_variant=variant,
                                role="underbody",
                                ffmpeg="pinned-ffmpeg",
                            )
                    with self.subTest(consumer="receipt"):
                        with self.assertRaisesRegex(
                            TranscodeFreezeError,
                            f"{variant} bitstream filter contract mismatch",
                        ):
                            freezer._transcode_recipe_descriptor(
                                variant, "underbody"
                            )

    def test_freezes_exact_set_atomically_and_emits_canonical_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            receipt_path, underbody, front, _, _ = _write_authoritative_extraction(root)
            expected_receipt_file_sha256 = _sha256(receipt_path.read_bytes())
            output_dir = root / "staging" / "transcodes"
            tool_arguments, versions = _make_tools(root)
            commands: list[tuple[str, ...]] = []

            def runner(command: tuple[str, ...]) -> None:
                commands.append(command)
                target = Path(command[-1])
                target.write_bytes((target.parent.name + ":" + target.name).encode("ascii"))

            receipt = _freeze_transcodes_with_test_adapters(
                project_root=root,
                extraction_receipt=receipt_path,
                expected_extraction_receipt_file_sha256=(
                    expected_receipt_file_sha256
                ),
                underbody_avi=underbody,
                front_avi=front,
                output_dir=output_dir,
                runner=runner,
                prober=_probe_for,
                version_reader=lambda tool: versions[tool.name],
                **tool_arguments,
            )

            self.assertEqual(len(commands), 4)
            self.assertEqual(
                [(item["codec_variant"], item["role"]) for item in receipt["outputs"]],
                [
                    ("h264", "underbody"),
                    ("h264", "front_gate"),
                    ("h265", "underbody"),
                    ("h265", "front_gate"),
                ],
            )
            self.assertEqual(receipt["schema_version"], 1)
            self.assertEqual(
                receipt["artifact_kind"],
                "vast_kpp_legacy_iss_v2_transcode_receipt",
            )
            self.assertEqual(receipt["generation_id"], "kpp_legacy_iss_v2")
            self.assertEqual(receipt["status"], "test_adapter_candidate")
            expected_recipes: list[dict[str, object]] = []
            for variant, encoder, preset, crf in (
                ("h264", "libx264", "veryfast", 23),
                ("h265", "libx265", "ultrafast", 30),
            ):
                for role, width, height, frame_count in (
                    ("underbody", 1700, 236, 35646),
                    ("front_gate", 1920, 1080, 33120),
                ):
                    expected_recipes.append(
                        {
                            "codec_variant": variant,
                            "role": role,
                            "ffmpeg_filter": (
                                f"scale=w={width}:h={height}:"
                                "in_range=auto:out_range=tv,"
                                "format=pix_fmts=yuv420p,"
                                "fps=fps=600:start_time=0:round=near:"
                                "eof_action=round"
                            ),
                            "reinit_filter": 0,
                            "encoder": encoder,
                            "preset": preset,
                            "crf": crf,
                            "pix_fmt": "yuv420p",
                            "color_range": "tv",
                            "output_frame_rate": "600/1",
                            "fps_mode": "cfr",
                            "encoder_time_base": "1/600",
                            "expected_frame_count": frame_count,
                            "video_track_timescale": 600,
                            "bitstream_filter": (
                                "h264_metadata=video_full_range_flag=0"
                                if variant == "h264"
                                else "hevc_metadata=video_full_range_flag=0"
                            ),
                            "container": "mp4",
                        }
                    )
            self.assertEqual(receipt["recipes"], expected_recipes)
            first_media = receipt["outputs"][0]["media"]
            self.assertEqual(first_media["color_range"], "tv")
            self.assertEqual(first_media["stream_time_base"], "1/600")
            self.assertEqual(first_media["stream_duration_ts"], 35646)
            self.assertEqual(first_media["decoded_frame_count"], 35646)
            self.assertEqual(first_media["decoded_first_pts"], 0)
            self.assertEqual(first_media["decoded_last_pts"], 35645)
            self.assertEqual(first_media["decoded_pts_steps"], [1])
            self.assertEqual(
                first_media["decoded_frame_signatures"],
                [
                    {
                        "width": 1700,
                        "height": 236,
                        "pix_fmt": "yuv420p",
                        "color_range": "tv",
                    }
                ],
            )
            self.assertEqual(
                receipt["source_extraction"]["file_sha256"],
                expected_receipt_file_sha256,
            )
            unsigned_receipt = dict(receipt)
            claimed_receipt_hash = unsigned_receipt.pop(
                "transcode_receipt_sha256"
            )
            self.assertEqual(
                claimed_receipt_hash,
                _transcode_receipt_hash(unsigned_receipt),
            )
            self.assertFalse(
                receipt["claims"]["tool_bytes_and_version_outputs_externally_pinned"]
            )
            self.assertFalse(
                receipt["claims"]["transcodes_executed_by_pinned_ffmpeg"]
            )
            self.assertFalse(
                receipt["claims"]["outputs_validated_by_pinned_ffprobe"]
            )
            self.assertFalse(
                receipt["claims"]["output_set_directory_published_atomically"]
            )
            self.assertFalse(
                receipt["claims"][
                    "windows_project_root_staging_and_working_directory_handle_custody_validated"
                ]
            )
            self.assertFalse(receipt["claims"]["publication_authorized"])
            self.assertFalse(receipt["claims"]["accuracy_ground_truth_validated"])
            self.assertFalse(receipt["claims"]["v1_dataset_identity_equivalent"])
            self.assertNotIn(str(root), json.dumps(receipt, sort_keys=True))
            expected_files = {
                "h264/iss_v2_underbody.mp4",
                "h264/iss_v2_front_gate.mp4",
                "h265/iss_v2_underbody.mp4",
                "h265/iss_v2_front_gate.mp4",
                "kpp_iss_v2_transcode_receipt.json",
            }
            self.assertEqual(
                {
                    path.relative_to(output_dir).as_posix()
                    for path in output_dir.rglob("*")
                    if path.is_file()
                },
                expected_files,
            )
            self.assertFalse((output_dir / ".sources").exists())
            self.assertFalse((output_dir / ".tools").exists())
            if os.name == "nt":
                self.assertTrue(
                    extractor._windows_private_directory_acl_is_exact(output_dir)
                )
            else:
                self.assertEqual(stat.S_IMODE(output_dir.stat().st_mode), 0o700)
            encoded = (output_dir / "kpp_iss_v2_transcode_receipt.json").read_bytes()
            self.assertTrue(encoded.endswith(b"\n"))
            self.assertEqual(json.loads(encoded), receipt)

    def test_rejects_non_authoritative_tampered_or_mismatched_extraction_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            receipt_path, underbody, front, _, _ = _write_authoritative_extraction(root)
            tool_arguments, versions = _make_tools(root)
            original_receipt_file_sha256 = _sha256(receipt_path.read_bytes())

            def invoke(
                expected_receipt_file_sha256: str = original_receipt_file_sha256,
            ) -> dict[str, object]:
                return _freeze_transcodes_with_test_adapters(
                    project_root=root,
                    extraction_receipt=receipt_path,
                    expected_extraction_receipt_file_sha256=(
                        expected_receipt_file_sha256
                    ),
                    underbody_avi=underbody,
                    front_avi=front,
                    output_dir=root / "staging" / "transcodes",
                    runner=lambda command: Path(command[-1]).write_bytes(b"output"),
                    prober=_probe_for,
                    version_reader=lambda tool: versions[tool.name],
                    **tool_arguments,
                )

            original = json.loads(receipt_path.read_bytes())
            non_authoritative = dict(original)
            non_authoritative["status"] = "test_adapter_candidate"
            non_authoritative.pop("extraction_receipt_sha256")
            non_authoritative["extraction_receipt_sha256"] = _extraction_receipt_hash(
                non_authoritative
            )
            receipt_path.write_bytes(_canonical_bytes(non_authoritative))
            with self.assertRaisesRegex(TranscodeFreezeError, "file SHA-256"):
                invoke()
            with self.assertRaisesRegex(TranscodeFreezeError, "authoritative"):
                invoke(_sha256(receipt_path.read_bytes()))

            receipt_path.write_bytes(_canonical_bytes(original))
            missing_custody = dict(original)
            missing_custody["claims"] = dict(original["claims"])
            missing_custody["claims"].pop(
                "windows_project_root_staging_and_working_directory_handle_custody_validated"
            )
            missing_custody.pop("extraction_receipt_sha256")
            missing_custody["extraction_receipt_sha256"] = _extraction_receipt_hash(
                missing_custody
            )
            receipt_path.write_bytes(_canonical_bytes(missing_custody))
            with self.assertRaisesRegex(TranscodeFreezeError, "file SHA-256"):
                invoke()
            with self.assertRaisesRegex(TranscodeFreezeError, "claims schema"):
                invoke(_sha256(receipt_path.read_bytes()))

            receipt_path.write_bytes(b"{not-json}\n")
            with self.assertRaisesRegex(TranscodeFreezeError, "file SHA-256"):
                invoke()

            receipt_path.write_bytes(_canonical_bytes(original))
            underbody.write_bytes(b"x" * underbody.stat().st_size)
            with self.assertRaisesRegex(TranscodeFreezeError, "SHA-256"):
                invoke()

    def test_rejects_bad_tool_pin_partial_output_probe_drift_and_existing_target(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            receipt_path, underbody, front, _, _ = _write_authoritative_extraction(root)
            tool_arguments, versions = _make_tools(root)
            expected_receipt_file_sha256 = _sha256(receipt_path.read_bytes())
            output_dir = root / "staging" / "transcodes"
            bad_tools = dict(tool_arguments)
            bad_tools["expected_ffmpeg_sha256"] = "0" * 64
            with self.assertRaisesRegex(TranscodeFreezeError, "ffmpeg executable SHA-256"):
                _freeze_transcodes_with_test_adapters(
                    project_root=root,
                    extraction_receipt=receipt_path,
                    expected_extraction_receipt_file_sha256=(
                        expected_receipt_file_sha256
                    ),
                    underbody_avi=underbody,
                    front_avi=front,
                    output_dir=output_dir,
                    runner=lambda command: self.fail("runner must not run"),
                    prober=lambda path: self.fail("prober must not run"),
                    version_reader=lambda tool: versions[tool.name],
                    **bad_tools,
                )

            calls = 0

            def partial_runner(command: tuple[str, ...]) -> None:
                nonlocal calls
                calls += 1
                if calls == 3:
                    raise TranscodeFreezeError("synthetic partial failure")
                Path(command[-1]).write_bytes(b"output")

            with self.assertRaisesRegex(TranscodeFreezeError, "partial failure"):
                _freeze_transcodes_with_test_adapters(
                    project_root=root,
                    extraction_receipt=receipt_path,
                    expected_extraction_receipt_file_sha256=(
                        expected_receipt_file_sha256
                    ),
                    underbody_avi=underbody,
                    front_avi=front,
                    output_dir=output_dir,
                    runner=partial_runner,
                    prober=_probe_for,
                    version_reader=lambda tool: versions[tool.name],
                    **tool_arguments,
                )
            self.assertFalse(output_dir.exists())
            self.assertEqual(list((root / "staging").glob(".*.candidate")), [])

            def runner(command: tuple[str, ...]) -> None:
                Path(command[-1]).write_bytes(b"output")

            def drifted_probe(path: Path) -> dict[str, object]:
                value = _probe_for(path)
                if path.suffix == ".mp4":
                    value["frame_count"] = int(value["frame_count"]) - 1
                return value

            with self.assertRaisesRegex(TranscodeFreezeError, "frame_count mismatch"):
                _freeze_transcodes_with_test_adapters(
                    project_root=root,
                    extraction_receipt=receipt_path,
                    expected_extraction_receipt_file_sha256=(
                        expected_receipt_file_sha256
                    ),
                    underbody_avi=underbody,
                    front_avi=front,
                    output_dir=output_dir,
                    runner=runner,
                    prober=drifted_probe,
                    version_reader=lambda tool: versions[tool.name],
                    **tool_arguments,
                )
            self.assertFalse(output_dir.exists())

            output_dir.mkdir()
            sentinel = output_dir / "sentinel"
            sentinel.write_bytes(b"occupied")
            with self.assertRaisesRegex(TranscodeFreezeError, "already exists"):
                _freeze_transcodes_with_test_adapters(
                    project_root=root,
                    extraction_receipt=receipt_path,
                    expected_extraction_receipt_file_sha256=(
                        expected_receipt_file_sha256
                    ),
                    underbody_avi=underbody,
                    front_avi=front,
                    output_dir=output_dir,
                    runner=lambda command: self.fail("runner must not run"),
                    prober=lambda path: self.fail("prober must not run"),
                    version_reader=lambda tool: versions[tool.name],
                    **tool_arguments,
                )
            self.assertEqual(sentinel.read_bytes(), b"occupied")

    def test_public_api_and_cli_do_not_expose_dependency_injection(self) -> None:
        parameters = inspect.signature(freeze_transcodes).parameters
        self.assertIn("expected_extraction_receipt_file_sha256", parameters)
        self.assertEqual(
            [
                name
                for name in parameters
                if "extraction_receipt" in name and "sha256" in name
            ],
            ["expected_extraction_receipt_file_sha256"],
        )
        self.assertNotIn("runner", parameters)
        self.assertNotIn("prober", parameters)
        self.assertNotIn("version_reader", parameters)
        implementation_parameters = inspect.signature(
            freezer._freeze_transcodes_impl
        ).parameters
        self.assertIn("test_adapters", implementation_parameters)
        self.assertNotIn("authoritative", implementation_parameters)
        self.assertNotIn("runner", implementation_parameters)
        self.assertNotIn("prober", implementation_parameters)
        self.assertNotIn("version_reader", implementation_parameters)
        self.assertEqual(list(inspect.signature(main).parameters), ["argv"])
        parser_source = inspect.getsource(freezer._build_parser)
        self.assertEqual(
            parser_source.count("--expected-extraction-receipt-file-sha256"),
            1,
        )
        with self.assertRaises(SystemExit) as caught:
            main([])
        self.assertEqual(caught.exception.code, 2)

    def test_cli_emits_the_same_canonical_receipt_via_public_api_shape(self) -> None:
        source = inspect.getsource(main)
        self.assertIn("freeze_transcodes(", source)
        self.assertNotIn("_freeze_transcodes_with_test_adapters", source)
        self.assertNotIn("runner=", source)
        self.assertNotIn("prober=", source)
        self.assertNotIn("version_reader=", source)

    def test_private_directory_policy_uses_native_helper_without_acl_reset(self) -> None:
        source = (SCRIPTS / "freeze_kpp_legacy_iss_v2_transcodes.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("_create_private_working_directory", source)
        self.assertIn(
            "_create_windows_private_working_directory_with_custody", source
        )
        self.assertIn("_validate_private_publication_set", source)
        self.assertNotIn("tempfile.mkdtemp", source)
        self.assertNotIn("icacls", source.casefold())
        self.assertNotIn('"/reset"', source)
        self.assertNotIn("def _reset_acl_for_publication", source)
        remove_sources = source.index("source_snapshot_dir.rmdir()")
        remove_tools = source.index("tool_snapshot_dir.rmdir()")
        validate_set = source.index("_validate_private_publication_set(", remove_tools)
        self.assertLess(remove_sources, validate_set)
        self.assertLess(remove_tools, validate_set)

    def test_authoritative_freeze_uses_windows_custody_and_direct_staging_child(self) -> None:
        source = inspect.getsource(freezer._freeze_transcodes_impl)
        self.assertIn("authoritative transcode freeze requires Windows", source)
        self.assertIn("_open_windows_directory_custody", source)
        self.assertIn("_validate_windows_direct_child_custody", source)
        self.assertLess(
            source.index("root_custody = _open_windows_directory_custody"),
            source.index("destination.parent.mkdir"),
        )
        self.assertIn(
            "windows_project_root_staging_and_working_directory_handle_custody_validated",
            source,
        )
        native_create = source.index(
            "working, working_custody = "
            "_create_windows_private_working_directory_with_custody"
        )
        exact_acl = source.index(
            "_windows_private_directory_acl_is_exact(working)", native_create
        )
        custody_validation = source.index(
            "_validate_windows_direct_child_custody(", native_create
        )
        snapshots = source.index('source_snapshot_dir = working / ".sources"')
        self.assertLess(native_create, custody_validation)
        self.assertLess(custody_validation, exact_acl)
        self.assertLess(exact_acl, snapshots)
        self.assertRegex(
            source,
            r"if authoritative:\s+[\s\S]*?"
            r"_create_windows_private_working_directory_with_custody\("
            r"[\s\S]*?else:\s+[\s\S]*?_create_private_working_directory\(",
        )
        self.assertRegex(
            source,
            r"if authoritative:\s+[\s\S]*?_windows_publish_directory_by_handle\("
            r"[\s\S]*?\s+else:\s+_atomic_publish_directory\(",
        )

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            nested = root / "staging" / "outer" / "transcodes"
            with self.assertRaisesRegex(TranscodeFreezeError, "direct child"):
                freezer._validated_output_dir(root, nested)

    @unittest.skipUnless(os.name == "nt", "Windows custody negatives only")
    def test_windows_freeze_custody_blocks_rename_and_preserves_collision(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            root_custody = extractor._open_windows_directory_custody(
                root,
                label="freeze project root",
                require_delete_access=False,
            )
            staging = root / "staging"
            staging.mkdir()
            working = extractor._create_private_working_directory(
                parent=staging,
                prefix=".freeze.",
                suffix=".candidate",
            )
            (working / "receipt.json").write_bytes(b"complete")
            parent_custody = extractor._open_windows_directory_custody(
                staging,
                label="freeze staging parent",
                require_delete_access=False,
            )
            working_custody = extractor._open_windows_directory_custody(
                working,
                label="freeze working directory",
                require_delete_access=True,
            )
            try:
                extractor._validate_windows_direct_child_custody(
                    parent=root_custody,
                    child=parent_custody,
                    expected_name=staging.name,
                )
                extractor._validate_windows_direct_child_custody(
                    parent=parent_custody,
                    child=working_custody,
                    expected_name=working.name,
                )
                with self.assertRaises(OSError):
                    os.rename(root, root.with_name(root.name + "-moved"))
                with self.assertRaises(OSError):
                    os.rename(staging, root / "moved-staging")
                with self.assertRaises(OSError):
                    os.rename(working, staging / "moved-working")

                published = staging / "frozen"
                extractor._windows_publish_directory_by_handle(
                    source=working_custody,
                    parent=parent_custody,
                    target_name=published.name,
                )
                extractor._validate_windows_direct_child_custody(
                    parent=root_custody,
                    child=parent_custody,
                    expected_name=staging.name,
                )
                extractor._validate_windows_direct_child_custody(
                    parent=parent_custody,
                    child=working_custody,
                    expected_name=published.name,
                )
                collision = extractor._create_private_working_directory(
                    parent=staging,
                    prefix=".collision.",
                    suffix=".candidate",
                )
                collision_custody = extractor._open_windows_directory_custody(
                    collision,
                    label="freeze collision directory",
                    require_delete_access=True,
                )
                try:
                    with self.assertRaisesRegex(
                        extractor.ExtractionError, "already exists"
                    ):
                        extractor._windows_publish_directory_by_handle(
                            source=collision_custody,
                            parent=parent_custody,
                            target_name=published.name,
                        )
                    self.assertTrue(collision.is_dir())
                    self.assertEqual(
                        (published / "receipt.json").read_bytes(), b"complete"
                    )
                finally:
                    collision_custody.close()
                    collision.rmdir()
            finally:
                working_custody.close()
                parent_custody.close()
                root_custody.close()

    @unittest.skipUnless(os.name == "nt", "Windows retained failure candidate only")
    def test_authoritative_freeze_failure_retains_private_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            receipt_path, underbody, front, _, _ = _write_authoritative_extraction(root)
            tool_arguments, _ = _make_tools(root)
            cleanup = mock.Mock(side_effect=AssertionError("must retain candidate"))
            with mock.patch.object(
                freezer,
                "_windows_private_directory_acl_is_exact",
                return_value=False,
            ), mock.patch.object(
                freezer,
                "_cleanup_private_tree",
                cleanup,
            ), mock.patch.object(
                freezer,
                "_run",
                side_effect=AssertionError("media tool must not run"),
            ), mock.patch.object(
                freezer,
                "_read_tool_version",
                side_effect=AssertionError("tool version must not be read"),
            ):
                with self.assertRaisesRegex(TranscodeFreezeError, "ACL"):
                    freeze_transcodes(
                        project_root=root,
                        extraction_receipt=receipt_path,
                        expected_extraction_receipt_file_sha256=_sha256(
                            receipt_path.read_bytes()
                        ),
                        underbody_avi=underbody,
                        front_avi=front,
                        output_dir=root / "staging" / "freeze-retained",
                        **tool_arguments,
                    )

            cleanup.assert_not_called()
            candidates = list(
                (root / "staging").glob(".freeze-retained.*.candidate")
            )
            self.assertEqual(len(candidates), 1)
            candidate = candidates[0]
            self.assertTrue(
                extractor._windows_private_directory_acl_is_exact(candidate)
            )
            self.assertEqual(list(candidate.iterdir()), [])
            candidate.rmdir()


if __name__ == "__main__":
    unittest.main()
