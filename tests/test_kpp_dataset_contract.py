from __future__ import annotations

import copy
import hashlib
import json
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from kpp_dataset_contract import (  # noqa: E402
    DATASET_CONTRACT_VERSION,
    DATASET_NAMES,
    GENERATION_ID,
    KppDatasetContractError,
    PREDECESSOR_MANIFEST_IDENTITIES,
    build_dataset_entries,
)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("ascii")


def _self_hash(value: dict[str, object], *, field: str, domain: bytes) -> None:
    unsigned = dict(value)
    unsigned.pop(field, None)
    value[field] = hashlib.sha256(domain + _canonical_bytes(unsigned)).hexdigest()


def _artifact(path: str, value: dict[str, object]) -> dict[str, object]:
    payload = _canonical_bytes(value)
    return {
        "path": path,
        "size_bytes": len(payload),
        "sha256": _sha256(payload),
    }


def _reseal_extraction(bundle: dict[str, dict[str, object]]) -> None:
    receipt = bundle["extraction_receipt"]
    _self_hash(
        receipt,
        field="extraction_receipt_sha256",
        domain=b"VAST:kpp-legacy-iss-extraction-receipt:v1\0",
    )
    artifact = _artifact(
        str(bundle["extraction_receipt_artifact"]["path"]), receipt
    )
    bundle["extraction_receipt_artifact"] = artifact
    source = bundle["transcode_receipt"]["source_extraction"]
    source.update(
        {
            "path": artifact["path"],
            "size_bytes": artifact["size_bytes"],
            "file_sha256": artifact["sha256"],
            "extraction_receipt_sha256": receipt[
                "extraction_receipt_sha256"
            ],
            "status": receipt["status"],
        }
    )
    _reseal_transcode(bundle)


def _reseal_transcode(bundle: dict[str, dict[str, object]]) -> None:
    receipt = bundle["transcode_receipt"]
    _self_hash(
        receipt,
        field="transcode_receipt_sha256",
        domain=b"VAST:kpp-legacy-iss-v2-transcode-receipt:v1\0",
    )
    bundle["transcode_receipt_artifact"] = _artifact(
        str(bundle["transcode_receipt_artifact"]["path"]), receipt
    )


def _reseal_metadata(bundle: dict[str, dict[str, object]]) -> None:
    receipt = bundle["metadata_receipt"]
    _self_hash(
        receipt,
        field="normalization_receipt_sha256",
        domain=b"VAST:kpp-legacy-iss-metadata:v1\0",
    )
    bundle["metadata_receipt_artifact"] = _artifact(
        str(bundle["metadata_receipt_artifact"]["path"]), receipt
    )


def _media(
    role: str,
    *,
    variant: str = "avi",
) -> dict[str, object]:
    source = {
        "underbody": {
            "codec_name": "mjpeg",
            "width": 1700,
            "height": 236,
            "r_frame_rate": "200/1",
            "avg_frame_rate": "200/1",
            "frame_count": 11882,
            "duration_ns": 59_410_000_000,
        },
        "front_gate": {
            "codec_name": "h264",
            "width": 1920,
            "height": 1080,
            "r_frame_rate": "25/1",
            "avg_frame_rate": "25/1",
            "frame_count": 1380,
            "duration_ns": 55_200_000_000,
        },
    }[role]
    if variant == "avi":
        return dict(source)
    frame_count = 35646 if role == "underbody" else 33120
    return {
        "codec_name": "h264" if variant == "h264" else "hevc",
        "pix_fmt": "yuv420p",
        "width": source["width"],
        "height": source["height"],
        "r_frame_rate": "600/1",
        "avg_frame_rate": "600/1",
        "frame_count": frame_count,
        "duration_ns": source["duration_ns"],
        "color_range": "tv",
        "stream_time_base": "1/600",
        "stream_duration_ts": frame_count,
        "decoded_frame_count": frame_count,
        "decoded_first_pts": 0,
        "decoded_last_pts": frame_count - 1,
        "decoded_pts_steps": [1],
        "decoded_frame_signatures": [
            {
                "width": source["width"],
                "height": source["height"],
                "pix_fmt": "yuv420p",
                "color_range": "tv",
            }
        ],
    }


def _transcode_recipe(variant: str, role: str) -> dict[str, object]:
    geometry = {
        "underbody": (1700, 236, 35646),
        "front_gate": (1920, 1080, 33120),
    }[role]
    width, height, frame_count = geometry
    return {
        "codec_variant": variant,
        "role": role,
        "ffmpeg_filter": (
            f"scale=w={width}:h={height}:in_range=auto:out_range=tv,"
            "format=pix_fmts=yuv420p,"
            "fps=fps=600:start_time=0:round=near:eof_action=round"
        ),
        "reinit_filter": 0,
        "encoder": "libx264" if variant == "h264" else "libx265",
        "preset": "veryfast" if variant == "h264" else "ultrafast",
        "crf": 23 if variant == "h264" else 30,
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


def _metadata_frames(
    *, source_size_bytes: int, frame_count: int, first_media_offset: int
) -> list[dict[str, object]]:
    start = datetime(2025, 5, 21, 22, 18, 52, 105000)
    packet_sha = _sha256(b"packet interval")
    media_sha = _sha256(b"declared media")
    jpeg_sha = _sha256(b"jpeg payload")
    primary_sha = _sha256(b"primary event snapshot")
    empty_sha = _sha256(b"")
    stride = 100
    frames: list[dict[str, object]] = []
    for index in range(frame_count):
        observed = start + timedelta(milliseconds=index)
        media_offset = first_media_offset + index * stride
        interval_end = (
            first_media_offset + (index + 1) * stride
            if index + 1 < frame_count
            else source_size_bytes
        )
        rich = index == 1
        frames.append(
            {
                "frame_index": index,
                "record_offset_bytes": 65 + index * stride,
                "header_clock": {
                    "calendar_text": observed.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
                    "fields": {
                        "year": observed.year,
                        "month": observed.month,
                        "day": observed.day,
                        "hour": observed.hour,
                        "minute": observed.minute,
                        "second": observed.second,
                        "millisecond": observed.microsecond // 1000,
                    },
                },
                "frame_clock": (
                    {
                        "frame_time": 1_747_865_932_110_721,
                        "magnet_time": 1_747_865_932_086_704,
                    }
                    if rich
                    else None
                ),
                "tag4_status": None if rich else 1,
                "sensor_data_8x3": (
                    [[row, -row, row + 10] for row in range(8)]
                    if rich
                    else None
                ),
                "source_fields_u32": [121_791_848 + index, index, 31, 1, 1700, 236, 1],
                "aux": {"size_bytes": 0, "sha256": empty_sha},
                "primary_event_snapshot": {
                    "size_bytes": 1,
                    "sha256": primary_sha,
                },
                "media": {
                    "offset_bytes": media_offset,
                    "size_bytes": 20,
                    "sha256": media_sha,
                    "jpeg_payload_size_bytes": 16,
                    "jpeg_payload_sha256": jpeg_sha,
                    "avi_packet_source_interval": {
                        "contract": (
                            "iss_record_media_start_to_next_record_media_start_or_eof_v1"
                        ),
                        "offset_bytes": media_offset,
                        "size_bytes": interval_end - media_offset,
                        "sha256": packet_sha,
                    },
                },
            }
        )
    return frames


def _bundle() -> dict[str, dict[str, object]]:
    underbody_source_size = 1_300_000
    underbody_archive_sha = _sha256(b"underbody legacy ISS archive")
    front_archive_sha = _sha256(b"front legacy ISS archive")
    avi_hashes = {
        "underbody": _sha256(b"underbody AVI bytes"),
        "front_gate": _sha256(b"front AVI bytes"),
    }
    tools = [
        {
            "role": role,
            "executable_sha256": _sha256(f"{role} executable".encode("ascii")),
            "version_output_sha256": _sha256(
                f"{role} version output".encode("ascii")
            ),
        }
        for role in ("ffmpeg", "ffprobe")
    ]
    extraction: dict[str, object] = {
        "schema_version": 1,
        "artifact_kind": "vast_kpp_legacy_iss_extraction_receipt",
        "generation_id": GENERATION_ID,
        "status": "headless_stream_copy_candidate",
        "source_archives": [
            {
                "archive_logical_id": "13._03",
                "size_bytes": underbody_source_size,
                "sha256": underbody_archive_sha,
                "role": "underbody",
                "payload_offset": 1313,
            },
            {
                "archive_logical_id": "13._03_2",
                "size_bytes": 1002,
                "sha256": front_archive_sha,
                "role": "front_gate",
                "payload_offset": 17,
            },
        ],
        "tools": copy.deepcopy(tools),
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
                "payload_offset": 17,
                "codec_mode": "stream_copy",
                "container": "avi",
            },
        ],
        "outputs": [
            {
                "role": role,
                "path": f"staging/extracted/iss_v2_{role}.avi",
                "size_bytes": 2000 + index,
                "sha256": avi_hashes[role],
                "media": _media(role),
            }
            for index, role in enumerate(("underbody", "front_gate"))
        ],
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
    _self_hash(
        extraction,
        field="extraction_receipt_sha256",
        domain=b"VAST:kpp-legacy-iss-extraction-receipt:v1\0",
    )
    extraction_artifact = _artifact(
        "staging/extracted/kpp_iss_v2_extraction_receipt.json", extraction
    )

    outputs: list[dict[str, object]] = []
    for variant in ("h264", "h265"):
        for index, role in enumerate(("underbody", "front_gate")):
            outputs.append(
                {
                    "codec_variant": variant,
                    "role": role,
                    "path": (
                        f"staging/transcoded/{variant}/iss_v2_{role}.mp4"
                    ),
                    "size_bytes": 3000 + len(outputs),
                    "sha256": _sha256(f"{variant}/{role}".encode("ascii")),
                    "media": _media(role, variant=variant),
                }
            )
    transcode: dict[str, object] = {
        "schema_version": 1,
        "artifact_kind": "vast_kpp_legacy_iss_v2_transcode_receipt",
        "generation_id": GENERATION_ID,
        "status": "pinned_codec_transcode_candidate",
        "source_extraction": {
            "artifact_logical_id": "kpp_iss_v2_extraction_receipt.json",
            "path": extraction_artifact["path"],
            "size_bytes": extraction_artifact["size_bytes"],
            "file_sha256": extraction_artifact["sha256"],
            "extraction_receipt_sha256": extraction[
                "extraction_receipt_sha256"
            ],
            "status": extraction["status"],
        },
        "sources": [
            {
                "role": item["role"],
                "artifact_logical_id": f"iss_v2_{item['role']}.avi",
                "path": item["path"],
                "size_bytes": item["size_bytes"],
                "sha256": item["sha256"],
                "media": item["media"],
            }
            for item in extraction["outputs"]
        ],
        "tools": copy.deepcopy(tools),
        "recipes": [
            _transcode_recipe(variant, role)
            for variant in ("h264", "h265")
            for role in ("underbody", "front_gate")
        ],
        "outputs": outputs,
        "claims": {
            "authoritative_extraction_receipt_consumed": True,
            "source_avi_bytes_verified_against_extraction_receipt": True,
            "source_avi_private_snapshots_verified": True,
            "tool_bytes_and_version_outputs_externally_pinned": True,
            "transcodes_executed_by_pinned_ffmpeg": True,
            "outputs_validated_by_pinned_ffprobe": True,
            "output_bytes_post_hashed": True,
            "output_set_directory_published_atomically": True,
            "windows_project_root_staging_and_working_directory_handle_custody_validated": True,
            "source_timestamps_preserved": False,
            "accuracy_ground_truth_validated": False,
            "v1_dataset_identity_equivalent": False,
            "publication_authorized": False,
        },
    }
    _self_hash(
        transcode,
        field="transcode_receipt_sha256",
        domain=b"VAST:kpp-legacy-iss-v2-transcode-receipt:v1\0",
    )
    transcode_artifact = _artifact(
        "staging/transcoded/kpp_iss_v2_transcode_receipt.json", transcode
    )

    metadata: dict[str, object] = {
        "schema_version": 1,
        "artifact_kind": "vast_kpp_legacy_iss_metadata",
        "generation_id": GENERATION_ID,
        "status": "authoritative_windows_candidate",
        "source_archive": {
            "archive_logical_id": "13._03",
            "sha256": underbody_archive_sha,
            "size_bytes": underbody_source_size,
            "header_size_bytes": 65,
            "header_sha256": _sha256(b"header"),
            "record_count": 11882,
            "avi_packet_source_interval_sequence_sha256": _sha256(
                b"packet interval sequence"
            ),
        },
        "exported_avi": {
            "artifact_logical_id": "iss_v2_underbody.avi",
            "sha256": avi_hashes["underbody"],
            "size_bytes": 2000,
            "frame_count": 11882,
            "frame_count_authority": (
                "physical_movi_packet_sequence_validation"
            ),
            "packetization_contract": (
                "iss_record_media_start_to_next_record_media_start_or_eof_v1"
            ),
        },
        "clock_domains": {
            "header_clock": {
                "source": "record_header_8xu16_calendar_fields",
                "resolution": "millisecond",
                "timezone": None,
            },
            "frame_clock": {
                "source": "tag_4_frame_time_and_magnet_time_integers",
                "unit": None,
                "epoch": None,
                "present_only_when_observed": True,
            },
        },
        "frames": _metadata_frames(
            source_size_bytes=underbody_source_size,
            frame_count=11882,
            first_media_offset=1313,
        ),
        "events": [
            {
                "event_index": 0,
                "kind": "MD_TRUE",
                "timestamp_text": "21-05-2025 22:18:50.001",
                "timestamp_has_date": True,
                "first_observed_frame_index": 0,
            }
        ],
        "claims": {
            "timestamps_interpolated": False,
            "clock_domains_equated": False,
            "timezone_validated": False,
            "frame_clock_unit_validated": False,
            "frame_clock_epoch_validated": False,
            "event_semantics_validated": False,
            "avi_packet_source_interval_binding_validated": True,
            "avi_physical_movi_packet_index_alignment_validated": True,
            "avi_demuxed_or_decoded_frame_index_alignment_validated": False,
            "avi_packet_jpeg_prefix_binding_validated": True,
            "avi_packet_equals_declared_media_without_trailer": False,
            "avi_packet_payload_is_clean_jpeg": False,
            "source_and_avi_private_snapshots_verified": True,
            "output_set_directory_published_atomically": True,
            "windows_project_root_staging_and_working_directory_handle_custody_validated": True,
            "accuracy_ground_truth_validated": False,
            "v1_dataset_identity_equivalent": False,
            "publication_authorized": False,
        },
    }
    _self_hash(
        metadata,
        field="normalization_receipt_sha256",
        domain=b"VAST:kpp-legacy-iss-metadata:v1\0",
    )
    metadata_artifact = _artifact(
        "staging/metadata/iss_v2_underbody_metadata.json", metadata
    )
    return {
        "extraction_receipt": extraction,
        "extraction_receipt_artifact": extraction_artifact,
        "transcode_receipt": transcode,
        "transcode_receipt_artifact": transcode_artifact,
        "metadata_receipt": metadata,
        "metadata_receipt_artifact": metadata_artifact,
    }


class KppDatasetContractTests(unittest.TestCase):
    def test_builds_three_distinct_v2_entries_from_crossbound_receipts(self) -> None:
        entries = build_dataset_entries(**_bundle())

        self.assertEqual(GENERATION_ID, "kpp_legacy_iss_v2")
        self.assertEqual(DATASET_CONTRACT_VERSION, 2)
        self.assertEqual(
            set(entries),
            {
                "kpp_legacy_iss_v2_avi",
                "kpp_legacy_iss_v2_h264",
                "kpp_legacy_iss_v2_h265",
            },
        )
        self.assertEqual(set(entries), set(DATASET_NAMES.values()))
        for variant, name in DATASET_NAMES.items():
            with self.subTest(variant=variant):
                dataset = entries[name]
                self.assertEqual(dataset["dataset_contract_version"], 2)
                self.assertEqual(dataset["generation_id"], GENERATION_ID)
                self.assertFalse(dataset["publishable"])
                self.assertEqual(
                    dataset["status"], "physically_unassessed_candidate"
                )
                self.assertFalse(
                    dataset["provenance"]["physical_artifact_bytes_assessed"]
                )
                self.assertFalse(
                    dataset["provenance"]["publication_authorized"]
                )
                self.assertFalse(dataset["lineage"]["identity_equivalent"])
                self.assertEqual(
                    dataset["lineage"]["predecessor_manifest_identity_sha256"],
                    PREDECESSOR_MANIFEST_IDENTITIES[
                        dataset["lineage"]["predecessor_dataset"]
                    ],
                )

        avi = entries[DATASET_NAMES["avi"]]
        self.assertEqual(
            avi["provenance"]["metadata_receipt"]["status"],
            "authoritative_windows_candidate",
        )
        self.assertEqual(
            [stream["camera_role"] for stream in avi["streams"]],
            [
                "plate_number",
                "plate_number",
                "vehicle_type",
                "damage",
                "damage",
                "foreign_object",
            ],
        )
        self.assertEqual(
            avi["streams"][0]["path"],
            "data/videos/kpp/kpp_legacy_iss_v2/avi/iss_v2_front_gate.avi",
        )
        self.assertEqual(
            avi["streams"][5]["path"],
            "data/videos/kpp/kpp_legacy_iss_v2/avi/iss_v2_underbody.avi",
        )
        self.assertEqual(
            entries[DATASET_NAMES["h264"]]["streams"][5]["path"],
            "data/videos/kpp/kpp_legacy_iss_v2/h264/iss_v2_underbody.mp4",
        )
        self.assertEqual(
            entries[DATASET_NAMES["h265"]]["streams"][0]["path"],
            "data/videos/kpp/kpp_legacy_iss_v2/h265/iss_v2_front_gate.mp4",
        )

    def test_exposes_truthful_timestamp_limits_and_bound_metadata_hash(self) -> None:
        bundle = _bundle()
        entries = build_dataset_entries(**bundle)
        expected_metadata_sha = bundle["metadata_receipt_artifact"]["sha256"]

        for variant, name in DATASET_NAMES.items():
            contract = entries[name]["timestamp_contract"]
            with self.subTest(variant=variant):
                self.assertEqual(contract["schema_version"], 1)
                self.assertFalse(contract["source_timestamps_preserved"])
                self.assertFalse(contract["timestamps_interpolated"])
                self.assertFalse(contract["clock_domains_equated"])
                self.assertFalse(contract["timezone_validated"])
                self.assertFalse(contract["accuracy_ground_truth"])
                self.assertEqual(
                    entries[name]["annotations"]["sha256"],
                    expected_metadata_sha,
                )
                self.assertEqual(
                    contract["derived_codec_frame_index_alignment"],
                    "not_applicable" if variant == "avi" else "not_claimed",
                )
                self.assertEqual(
                    contract[
                        "underbody_avi_physical_movi_packet_index_alignment"
                    ],
                    "validated_exact_physical_packet_sequence",
                )
                self.assertEqual(
                    contract["demuxed_or_decoded_frame_index_alignment"],
                    "not_claimed",
                )
                self.assertNotIn("underbody_avi_frame_index_alignment", contract)

    def test_exports_two_role_specific_recipes_per_codec_dataset(self) -> None:
        entries = build_dataset_entries(**_bundle())

        for variant in ("h264", "h265"):
            with self.subTest(variant=variant):
                transcode = entries[DATASET_NAMES[variant]]["transcode"]
                self.assertEqual(
                    transcode,
                    {
                        "source_paths": [
                            (
                                "data/videos/kpp/kpp_legacy_iss_v2/avi/"
                                "iss_v2_underbody.avi"
                            ),
                            (
                                "data/videos/kpp/kpp_legacy_iss_v2/avi/"
                                "iss_v2_front_gate.avi"
                            ),
                        ],
                        "recipes": [
                            _transcode_recipe(variant, "underbody"),
                            _transcode_recipe(variant, "front_gate"),
                        ],
                    },
                )

    def test_confines_all_final_paths_to_atomic_v2_subtree_without_v1_collision(
        self,
    ) -> None:
        entries = build_dataset_entries(**_bundle())
        root = "data/videos/kpp/kpp_legacy_iss_v2/"
        expected_paths = {
            f"{root}avi/iss_v2_underbody.avi",
            f"{root}avi/iss_v2_front_gate.avi",
            f"{root}h264/iss_v2_underbody.mp4",
            f"{root}h264/iss_v2_front_gate.mp4",
            f"{root}h265/iss_v2_underbody.mp4",
            f"{root}h265/iss_v2_front_gate.mp4",
            f"{root}metadata/iss_v2_underbody_metadata.json",
        }
        final_paths: set[str] = set()
        receipt_paths: set[str] = set()
        for entry in entries.values():
            final_paths.add(entry["annotations"]["path"])
            final_paths.update(
                descriptor["path"]
                for descriptor in entry["provenance"]["media_artifacts"]
            )
            for stream in entry["streams"]:
                final_paths.add(stream["path"])
                if "source_path" in stream:
                    final_paths.add(stream["source_path"])
            if "transcode" in entry:
                final_paths.update(entry["transcode"]["source_paths"])
            receipt_paths.update(
                provenance["path"]
                for key, provenance in entry["provenance"].items()
                if key.endswith("_receipt")
            )

        self.assertEqual(final_paths, expected_paths)
        self.assertTrue(all(path.startswith(root) for path in final_paths))
        self.assertEqual(
            receipt_paths,
            {
                "staging/extracted/kpp_iss_v2_extraction_receipt.json",
                "staging/transcoded/kpp_iss_v2_transcode_receipt.json",
                "staging/metadata/iss_v2_underbody_metadata.json",
            },
        )
        self.assertTrue(
            final_paths.isdisjoint(
                {
                    "data/videos/kpp/1.avi",
                    "data/videos/kpp/2.avi",
                    "data/videos/kpp/h264/1.mp4",
                    "data/videos/kpp/h264/2.mp4",
                    "data/videos/kpp/h265/1.mp4",
                    "data/videos/kpp/h265/2.mp4",
                    "data/videos/kpp/Timestamps.txt",
                }
            )
        )

    def test_rejects_every_transcode_command_recipe_mutation(self) -> None:
        mutations = {
            "codec_variant": "h266",
            "role": "side_gate",
            "ffmpeg_filter": "fps=600",
            "reinit_filter": False,
            "encoder": "libx264rgb",
            "preset": "medium",
            "crf": 24,
            "pix_fmt": "yuv444p",
            "color_range": "pc",
            "output_frame_rate": "599/1",
            "fps_mode": "vfr",
            "encoder_time_base": "1/599",
            "expected_frame_count": 35645,
            "video_track_timescale": 19200,
            "bitstream_filter": "h264_metadata=video_full_range_flag=1",
            "container": "mkv",
        }
        for field, invalid_value in mutations.items():
            with self.subTest(field=field):
                bundle = _bundle()
                bundle["transcode_receipt"]["recipes"][0][field] = invalid_value
                _reseal_transcode(bundle)
                with self.assertRaisesRegex(
                    KppDatasetContractError,
                    r"transcode recipes|recipe .* mismatch",
                ):
                    build_dataset_entries(**bundle)

    def test_rejects_closed_bitstream_filter_contract_after_resealing(self) -> None:
        cases = (
            ("h264", "missing", None),
            (
                "h264",
                "wrong",
                "h264_metadata=video_full_range_flag=1",
            ),
            (
                "h264",
                "cross_codec",
                "hevc_metadata=video_full_range_flag=0",
            ),
            ("h265", "missing", None),
            (
                "h265",
                "wrong",
                "hevc_metadata=video_full_range_flag=1",
            ),
            (
                "h265",
                "cross_codec",
                "h264_metadata=video_full_range_flag=0",
            ),
        )
        for variant, case, invalid_value in cases:
            with self.subTest(variant=variant, case=case):
                bundle = _bundle()
                recipe = next(
                    item
                    for item in bundle["transcode_receipt"]["recipes"]
                    if item["codec_variant"] == variant
                    and item["role"] == "underbody"
                )
                if invalid_value is None:
                    recipe.pop("bitstream_filter")
                else:
                    recipe["bitstream_filter"] = invalid_value
                _reseal_transcode(bundle)
                with self.assertRaisesRegex(
                    KppDatasetContractError,
                    rf"{variant}/underbody recipe .*mismatch",
                ):
                    build_dataset_entries(**bundle)

        bundle = _bundle()
        bundle["transcode_receipt"]["recipes"][0][
            "bitstream_filter_alias"
        ] = "h264_metadata=video_full_range_flag=0"
        _reseal_transcode(bundle)
        with self.assertRaisesRegex(
            KppDatasetContractError,
            r"h264/underbody recipe schema mismatch",
        ):
            build_dataset_entries(**bundle)

    def test_rejects_every_transcode_decoded_media_evidence_mutation(self) -> None:
        mutations = {
            "color_range": "pc",
            "stream_time_base": "1/19200",
            "stream_duration_ts": 35645,
            "decoded_frame_count": 35645,
            "decoded_first_pts": False,
            "decoded_last_pts": 35644,
            "decoded_pts_steps": [True],
            "decoded_frame_signatures": [
                {
                    "width": 1700,
                    "height": 236,
                    "pix_fmt": "yuv420p",
                    "color_range": "pc",
                }
            ],
        }
        for field, invalid_value in mutations.items():
            with self.subTest(field=field):
                bundle = _bundle()
                bundle["transcode_receipt"]["outputs"][0]["media"][field] = (
                    invalid_value
                )
                _reseal_transcode(bundle)
                with self.assertRaisesRegex(
                    KppDatasetContractError,
                    r"h264/underbody output media",
                ):
                    build_dataset_entries(**bundle)

    def test_rejects_test_adapter_or_unpinned_receipts(self) -> None:
        for receipt_name, mutation, reseal, message in (
            (
                "extraction_receipt",
                lambda receipt: receipt.__setitem__(
                    "status", "test_adapter_candidate"
                ),
                _reseal_extraction,
                "extraction receipt is not authoritative",
            ),
            (
                "extraction_receipt",
                lambda receipt: receipt["claims"].__setitem__(
                    "video_payloads_stream_copied", False
                ),
                _reseal_extraction,
                "extraction receipt claim",
            ),
            (
                "transcode_receipt",
                lambda receipt: receipt.__setitem__(
                    "status", "test_adapter_candidate"
                ),
                _reseal_transcode,
                "transcode receipt is not authoritative",
            ),
            (
                "transcode_receipt",
                lambda receipt: receipt["claims"].__setitem__(
                    "outputs_validated_by_pinned_ffprobe", False
                ),
                _reseal_transcode,
                "transcode receipt claim",
            ),
        ):
            with self.subTest(mutation=mutation):
                bundle = _bundle()
                mutation(bundle[receipt_name])
                reseal(bundle)
                with self.assertRaisesRegex(KppDatasetContractError, message):
                    build_dataset_entries(**bundle)

    def test_rejects_receipt_self_hash_file_hash_and_lineage_rebinding(self) -> None:
        mutations = (
            (
                lambda bundle: bundle["extraction_receipt"].__setitem__(
                    "extraction_receipt_sha256", "0" * 64
                ),
                lambda bundle: None,
                "self hash",
            ),
            (
                lambda bundle: bundle["transcode_receipt_artifact"].__setitem__(
                    "sha256", "0" * 64
                ),
                lambda bundle: None,
                "artifact SHA-256",
            ),
            (
                lambda bundle: bundle["transcode_receipt"][
                    "source_extraction"
                ].__setitem__("file_sha256", "0" * 64),
                _reseal_transcode,
                "does not bind the extraction receipt artifact",
            ),
            (
                lambda bundle: bundle["metadata_receipt"][
                    "exported_avi"
                ].__setitem__("sha256", "0" * 64),
                _reseal_metadata,
                "all-zero SHA-256",
            ),
        )
        for mutation, reseal, message in mutations:
            with self.subTest(mutation=mutation):
                bundle = _bundle()
                mutation(bundle)
                reseal(bundle)
                with self.assertRaisesRegex(KppDatasetContractError, message):
                    build_dataset_entries(**bundle)

    def test_rejects_timestamp_invention_or_false_frame_alignment(self) -> None:
        mutations = (
            lambda receipt: receipt["claims"].__setitem__(
                "timestamps_interpolated", True
            ),
            lambda receipt: receipt["claims"].__setitem__(
                "clock_domains_equated", True
            ),
            lambda receipt: receipt["claims"].__setitem__(
                "timezone_validated", True
            ),
            lambda receipt: receipt["clock_domains"]["header_clock"].__setitem__(
                "timezone", "Europe/Moscow"
            ),
            lambda receipt: receipt["claims"].__setitem__(
                "avi_physical_movi_packet_index_alignment_validated", False
            ),
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                bundle = _bundle()
                mutation(bundle["metadata_receipt"])
                _reseal_metadata(bundle)
                with self.assertRaisesRegex(
                    KppDatasetContractError,
                    r"metadata (?:receipt claim|timestamp contract)",
                ):
                    build_dataset_entries(**bundle)

    def test_rejects_missing_variant_role_and_placeholder_hash(self) -> None:
        bundle = _bundle()
        bundle["transcode_receipt"]["outputs"].pop()
        _reseal_transcode(bundle)
        with self.assertRaisesRegex(KppDatasetContractError, "outputs role/variant set"):
            build_dataset_entries(**bundle)

        bundle = _bundle()
        bundle["extraction_receipt"]["outputs"][0]["sha256"] = "SET_SHA256"
        _reseal_extraction(bundle)
        with self.assertRaisesRegex(KppDatasetContractError, "exact lowercase SHA-256"):
            build_dataset_entries(**bundle)

    def test_rejects_tool_provenance_drift(self) -> None:
        bundle = _bundle()
        bundle["transcode_receipt"]["tools"][0][
            "version_output_sha256"
        ] = _sha256(b"different ffmpeg version output")
        _reseal_transcode(bundle)
        with self.assertRaisesRegex(
            KppDatasetContractError,
            "transcode tools do not bind extraction tool provenance",
        ):
            build_dataset_entries(**bundle)

    def test_rejects_non_authoritative_metadata_receipt(self) -> None:
        bundle = _bundle()
        bundle["metadata_receipt"][
            "status"
        ] = "non_authoritative_path_fallback_candidate"
        bundle["metadata_receipt"]["claims"][
            "output_set_directory_published_atomically"
        ] = False
        bundle["metadata_receipt"]["claims"][
            "windows_project_root_staging_and_working_directory_handle_custody_validated"
        ] = False
        _reseal_metadata(bundle)
        with self.assertRaisesRegex(
            KppDatasetContractError, "metadata receipt is not authoritative"
        ):
            build_dataset_entries(**bundle)

    def test_rejects_unknown_receipt_and_claim_fields_after_resealing(self) -> None:
        cases = (
            (
                "extraction_receipt",
                lambda receipt: receipt.__setitem__("unexpected", False),
                _reseal_extraction,
            ),
            (
                "extraction_receipt",
                lambda receipt: receipt["claims"].__setitem__(
                    "unknown_claim", False
                ),
                _reseal_extraction,
            ),
            (
                "transcode_receipt",
                lambda receipt: receipt["claims"].__setitem__(
                    "unknown_claim", False
                ),
                _reseal_transcode,
            ),
            (
                "metadata_receipt",
                lambda receipt: receipt.__setitem__("unexpected", False),
                _reseal_metadata,
            ),
            (
                "metadata_receipt",
                lambda receipt: receipt["claims"].__setitem__(
                    "windows_directory_handle_custody_validated",
                    receipt["claims"].pop(
                        "windows_project_root_staging_and_working_directory_handle_custody_validated"
                    ),
                ),
                _reseal_metadata,
            ),
        )
        for receipt_name, mutate, reseal in cases:
            with self.subTest(receipt=receipt_name):
                bundle = _bundle()
                mutate(bundle[receipt_name])
                reseal(bundle)
                with self.assertRaisesRegex(
                    KppDatasetContractError, "schema mismatch"
                ):
                    build_dataset_entries(**bundle)

    def test_rejects_boolean_versions_and_counts(self) -> None:
        for receipt_name, reseal in (
            ("extraction_receipt", _reseal_extraction),
            ("transcode_receipt", _reseal_transcode),
            ("metadata_receipt", _reseal_metadata),
        ):
            with self.subTest(receipt=receipt_name):
                bundle = _bundle()
                bundle[receipt_name]["schema_version"] = True
                reseal(bundle)
                with self.assertRaisesRegex(
                    KppDatasetContractError, "schema_version"
                ):
                    build_dataset_entries(**bundle)

        bundle = _bundle()
        bundle["metadata_receipt"]["exported_avi"]["frame_count"] = True
        _reseal_metadata(bundle)
        with self.assertRaisesRegex(KppDatasetContractError, "frame_count"):
            build_dataset_entries(**bundle)

    def test_rejects_payload_offset_outside_source_and_all_zero_hashes(self) -> None:
        bundle = _bundle()
        source = bundle["extraction_receipt"]["source_archives"][0]
        source["payload_offset"] = source["size_bytes"]
        bundle["extraction_receipt"]["recipes"][0]["payload_offset"] = source[
            "payload_offset"
        ]
        _reseal_extraction(bundle)
        with self.assertRaisesRegex(KppDatasetContractError, "payload_offset"):
            build_dataset_entries(**bundle)

        bundle = _bundle()
        bundle["extraction_receipt"]["outputs"][0]["sha256"] = "0" * 64
        _reseal_extraction(bundle)
        bundle["transcode_receipt"]["sources"][0]["sha256"] = "0" * 64
        _reseal_transcode(bundle)
        bundle["metadata_receipt"]["exported_avi"]["sha256"] = "0" * 64
        _reseal_metadata(bundle)
        with self.assertRaisesRegex(KppDatasetContractError, "all-zero"):
            build_dataset_entries(**bundle)

    def test_rejects_malformed_metadata_frame_and_event_shapes(self) -> None:
        bundle = _bundle()
        bundle["metadata_receipt"]["frames"][0] = None
        _reseal_metadata(bundle)
        with self.assertRaisesRegex(KppDatasetContractError, "metadata frame"):
            build_dataset_entries(**bundle)

        bundle = _bundle()
        bundle["metadata_receipt"]["frames"][1]["frame_index"] = True
        _reseal_metadata(bundle)
        with self.assertRaisesRegex(KppDatasetContractError, "frame_index"):
            build_dataset_entries(**bundle)

        bundle = _bundle()
        bundle["metadata_receipt"]["events"][0]["timestamp_has_date"] = 1
        _reseal_metadata(bundle)
        with self.assertRaisesRegex(KppDatasetContractError, "metadata event"):
            build_dataset_entries(**bundle)

    def test_rejects_metadata_first_media_offset_before_or_after_payload(self) -> None:
        for delta in (-1, 1):
            with self.subTest(delta=delta):
                bundle = _bundle()
                frames = bundle["metadata_receipt"]["frames"]
                media = frames[0]["media"]
                interval = media["avi_packet_source_interval"]
                changed_offset = media["offset_bytes"] + delta
                next_offset = frames[1]["media"]["offset_bytes"]
                media["offset_bytes"] = changed_offset
                interval["offset_bytes"] = changed_offset
                interval["size_bytes"] = next_offset - changed_offset
                _reseal_metadata(bundle)
                with self.assertRaisesRegex(
                    KppDatasetContractError,
                    "first media offset.*payload_offset",
                ):
                    build_dataset_entries(**bundle)

    def test_rejects_non_boolean_clock_presence_and_wrong_jpeg_size(self) -> None:
        for invalid_value in (1, False):
            with self.subTest(invalid_value=invalid_value):
                bundle = _bundle()
                bundle["metadata_receipt"]["clock_domains"]["frame_clock"][
                    "present_only_when_observed"
                ] = invalid_value
                _reseal_metadata(bundle)
                with self.assertRaisesRegex(
                    KppDatasetContractError,
                    "present_only_when_observed.*boolean true",
                ):
                    build_dataset_entries(**bundle)

        bundle = _bundle()
        bundle["metadata_receipt"]["frames"][0]["media"][
            "jpeg_payload_size_bytes"
        ] -= 1
        _reseal_metadata(bundle)
        with self.assertRaisesRegex(
            KppDatasetContractError,
            "JPEG payload size_bytes.*media size_bytes minus 4",
        ):
            build_dataset_entries(**bundle)

    def test_exposes_predecessor_constants_without_claiming_v1_validation(self) -> None:
        expected = {
            "kpp_real_avi": (
                "940cf02d9f7fd7b0179fd4eaf858fb7f095bc860df1dfb72681a4f86ca69379f"
            ),
            "kpp_real_h264": (
                "1d3b7a0c7e4b9b0a51c901371763e6f52019d69f257fd78a6c74664f4e233951"
            ),
            "kpp_real_h265": (
                "0f166e745e36ae979a3cb89fb3214636422a4a55f5255664d9b5089af7ec59db"
            ),
        }
        self.assertEqual(dict(PREDECESSOR_MANIFEST_IDENTITIES), expected)

        entries = build_dataset_entries(**_bundle())
        self.assertTrue(set(entries).isdisjoint(expected))

    def test_does_not_retain_mutable_caller_state(self) -> None:
        bundle = _bundle()
        snapshot = copy.deepcopy(bundle)
        entries = build_dataset_entries(**bundle)
        entries[DATASET_NAMES["avi"]]["streams"][0]["sha256"] = "0" * 64
        self.assertEqual(bundle, snapshot)


if __name__ == "__main__":
    unittest.main()
