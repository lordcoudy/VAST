from __future__ import annotations

import hashlib
import io
import json
import os
import struct
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import normalize_kpp_iss_metadata as normalizer  # noqa: E402
from normalize_kpp_iss_metadata import (  # noqa: E402
    METADATA_NAME,
    MetadataNormalizationError,
    _TestAdapters,
    _normalize_metadata_impl,
    main,
    normalize_metadata,
)


HEADER_SIZE = 65
SENTINEL = 0xFFFFFFFC
TERMINATOR = 0xFFFFFFFF


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _tag(tag: int, payload: bytes) -> bytes:
    return struct.pack("<II", tag, len(payload)) + payload


def _riff_chunk(
    tag: bytes,
    payload: bytes,
    *,
    pad_byte: bytes = b"\x00",
    include_padding: bool = True,
) -> bytes:
    if len(tag) != 4:
        raise ValueError("RIFF tags are four bytes")
    if len(pad_byte) != 1:
        raise ValueError("RIFF padding is one byte")
    padding = pad_byte if include_padding and len(payload) & 1 else b""
    return tag + struct.pack("<I", len(payload)) + payload + padding


def _riff_segment(form_type: bytes, chunks: bytes, *, pad_byte: bytes = b"\x00") -> bytes:
    if form_type not in (b"AVI ", b"AVIX"):
        raise ValueError("unsupported synthetic RIFF form")
    body = form_type + chunks
    padding = pad_byte if len(body) & 1 else b""
    return b"RIFF" + struct.pack("<I", len(body)) + body + padding


def _archive_packet_payloads(archive_payload: bytes) -> list[bytes]:
    media_offsets: list[int] = []
    cursor = 0
    while True:
        cursor = archive_payload.find(b"\xff\xd8\xff", cursor)
        if cursor < 0:
            break
        media_offsets.append(cursor)
        cursor += 3
    if not media_offsets:
        raise ValueError("synthetic ISS archive must contain media records")
    return [
        archive_payload[
            media_offset : (
                media_offsets[index + 1]
                if index + 1 < len(media_offsets)
                else len(archive_payload)
            )
        ]
        for index, media_offset in enumerate(media_offsets)
    ]


def _avi_from_archive(archive_payload: bytes) -> bytes:
    packets = [
        _riff_chunk(b"00dc", payload)
        for payload in _archive_packet_payloads(archive_payload)
    ]
    movi = _riff_chunk(b"LIST", b"movi" + b"".join(packets))
    return _riff_segment(b"AVI ", movi)


def _status_payload() -> bytes:
    return b'{"status":1}'


def _rich_payload(
    *,
    magnet_time: int = 1747865932086704,
    frame_time: int = 1747865932110721,
) -> bytes:
    value = {
        "data": [[row, -row, row + 10] for row in range(8)],
        "magnet_time": magnet_time,
        "frame_time": frame_time,
    }
    return json.dumps(value, separators=(",", ":")).encode("ascii")


def _record(
    *,
    millisecond: int,
    primary: bytes,
    tag4: bytes | None = None,
    aux: bytes = b"",
    media: bytes = b"\xff\xd8\xff\xe0payload\xff\xd9I+v}",
    tag_order: tuple[int, ...] = (4, 5, 7),
    tag5: bytes | None = None,
    tag7: bytes = struct.pack("<I", 31),
    terminator: int = TERMINATOR,
) -> bytes:
    payloads = {
        4: _status_payload() if tag4 is None else tag4,
        5: primary if tag5 is None else tag5,
        7: tag7,
    }
    timestamp = struct.pack("<8H", 2025, 5, 21, 22, 18, 52, millisecond, 0)
    opaque = (121791848 + millisecond, millisecond, 31, 1, 1700, 236, 1)
    prefix = (
        struct.pack("<I", SENTINEL)
        + timestamp
        + struct.pack(
            "<10I", *opaque, len(media), len(aux), len(primary)
        )
    )
    tlvs = b"".join(_tag(tag, payloads[tag]) for tag in tag_order)
    return prefix + aux + primary + tlvs + struct.pack("<I", terminator) + media


def _archive(records: list[bytes], *, trailing: bytes = b"") -> bytes:
    header = bytearray(HEADER_SIZE)
    header[:6] = b"\x0f\x00\xff\xff\x01\x00"
    struct.pack_into("<I", header, 6, len(records))
    header[44:48] = b"\xde\xc0\xad\xde"
    return bytes(header) + b"".join(records) + trailing


def _fixture_payloads() -> tuple[bytes, bytes]:
    first = b"#@@#MD_TRUE 21-05-2025 22:18:50.001<br>"
    second = first + b"#@@#STITCHING_STARTED 22:18:51.002<br>"
    third = second + b"#@@#IMAGE 22:18:52.003<br>"
    media = [
        b"\xff\xd8\xff\xe0first\xff\xd9I+v}",
        b"\xff\xd8\xff\xe0second\xff\xd9I+v}",
        b"\xff\xd8\xff\xe0third\xff\xd9I+v}",
    ]
    records = [
        _record(millisecond=105, primary=first, media=media[0]),
        _record(millisecond=110, primary=second, tag4=_rich_payload(), media=media[1]),
        _record(millisecond=115, primary=third, media=media[2]),
    ]
    archive_payload = _archive(records)
    return archive_payload, _avi_from_archive(archive_payload)


def _normalize(
    root: Path,
    archive_payload: bytes,
    avi_payload: bytes,
    *,
    frame_count: int = 3,
    expected_source_sha256: str | None = None,
    expected_source_size_bytes: int | None = None,
    expected_avi_sha256: str | None = None,
    expected_avi_size_bytes: int | None = None,
    test_adapters: _TestAdapters | None = None,
) -> dict[str, object]:
    archive = root / "13._03"
    avi = root / "iss_v2_underbody.avi"
    staging = root / "staging" / "metadata-candidate"
    staging.parent.mkdir(parents=True, exist_ok=True)
    archive.write_bytes(archive_payload)
    avi.write_bytes(avi_payload)
    arguments = dict(
        project_root=root,
        source_archive=archive,
        expected_source_sha256=(
            _sha256(archive_payload)
            if expected_source_sha256 is None
            else expected_source_sha256
        ),
        expected_source_size_bytes=(
            len(archive_payload)
            if expected_source_size_bytes is None
            else expected_source_size_bytes
        ),
        exported_avi=avi,
        expected_exported_avi_sha256=(
            _sha256(avi_payload)
            if expected_avi_sha256 is None
            else expected_avi_sha256
        ),
        expected_exported_avi_size_bytes=(
            len(avi_payload)
            if expected_avi_size_bytes is None
            else expected_avi_size_bytes
        ),
        exported_avi_frame_count=frame_count,
        output_path=staging / METADATA_NAME,
    )
    if test_adapters is None:
        return normalize_metadata(**arguments)
    return _normalize_metadata_impl(**arguments, test_adapters=test_adapters)


class NormalizeKppIssMetadataTests(unittest.TestCase):
    def test_unknown_riff_payloads_are_streamed_with_bounded_reads(self) -> None:
        maximum_read = 8 * 1024 * 1024

        class BoundedReadBytesIO(io.BytesIO):
            def read(self, size: int = -1) -> bytes:
                if size > maximum_read:
                    raise AssertionError(f"unbounded RIFF read requested: {size}")
                return super().read(size)

        chunks = _riff_chunk(b"JUNK", b"x" * (maximum_read + 1))
        reader = normalizer._HashingReader(BoundedReadBytesIO(chunks))
        packet_count = normalizer._parse_avi_chunks(
            reader,
            end_offset=len(chunks),
            in_movi=True,
            frames=[],
            packet_index=0,
            depth=0,
        )

        self.assertEqual(packet_count, 0)
        self.assertEqual(reader.offset, len(chunks))
        self.assertEqual(reader.digest.hexdigest(), _sha256(chunks))

    @unittest.skipUnless(os.name == "nt", "Windows custody route only")
    def test_authoritative_route_holds_root_staging_and_working_custody(self) -> None:
        archive_payload, avi_payload = _fixture_payloads()
        opened: list[tuple[Path, object]] = []
        atomically_created: list[tuple[Path, object]] = []
        lifecycle: list[tuple[str, str, str]] = []
        real_open = normalizer._open_windows_directory_custody
        real_create = (
            normalizer._create_windows_private_working_directory_with_custody
        )
        real_validate = normalizer._validate_windows_direct_child_custody
        real_acl = normalizer._windows_private_directory_acl_is_exact
        real_copy = normalizer._copy_pinned_snapshot
        real_publish = normalizer._windows_publish_directory_by_handle

        def recording_open(
            path: Path, *, label: str, require_delete_access: bool
        ) -> object:
            custody = real_open(
                path,
                label=label,
                require_delete_access=require_delete_access,
            )
            opened.append((path.absolute(), custody))
            return custody

        def recording_create(
            *, parent: object, prefix: str, suffix: str, label: str
        ) -> tuple[Path, object]:
            working, custody = real_create(
                parent=parent,
                prefix=prefix,
                suffix=suffix,
                label=label,
            )
            atomically_created.append((working, custody))
            lifecycle.append(("atomic-create", parent.label, custody.label))
            return working, custody

        def recording_validate(
            *, parent: object, child: object, expected_name: str
        ) -> None:
            lifecycle.append(("validate", parent.label, child.label))
            real_validate(
                parent=parent,
                child=child,
                expected_name=expected_name,
            )

        def recording_acl(path: Path) -> bool:
            lifecycle.append(("acl", path.name, "exact"))
            return real_acl(path)

        def recording_copy(
            *, source: Path, target: Path, expected_sha256: str, label: str
        ) -> tuple[dict[str, object], Path]:
            lifecycle.append(("snapshot", label, target.name))
            return real_copy(
                source=source,
                target=target,
                expected_sha256=expected_sha256,
                label=label,
            )

        def recording_publish(
            *, source: object, parent: object, target_name: str
        ) -> None:
            lifecycle.append(("publish", parent.label, source.label))
            real_publish(source=source, parent=parent, target_name=target_name)

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            with (
                patch.object(
                    normalizer,
                    "_open_windows_directory_custody",
                    side_effect=recording_open,
                ),
                patch.object(
                    normalizer,
                    "_create_windows_private_working_directory_with_custody",
                    side_effect=recording_create,
                ),
                patch.object(
                    normalizer,
                    "_validate_windows_direct_child_custody",
                    side_effect=recording_validate,
                ),
                patch.object(
                    normalizer,
                    "_windows_private_directory_acl_is_exact",
                    side_effect=recording_acl,
                ),
                patch.object(
                    normalizer,
                    "_copy_pinned_snapshot",
                    side_effect=recording_copy,
                ),
                patch.object(
                    normalizer,
                    "_windows_publish_directory_by_handle",
                    side_effect=recording_publish,
                ),
            ):
                _normalize(root, archive_payload, avi_payload)

            self.assertEqual(
                [path for path, _ in opened[:2]],
                [root.absolute(), (root / "staging").absolute()],
            )
            self.assertEqual(
                [custody.label for _, custody in opened],
                [
                    "metadata project root",
                    "metadata staging parent",
                ],
            )
            self.assertEqual(
                [custody.label for _, custody in atomically_created],
                ["metadata working directory"],
            )
            publish_index = lifecycle.index(
                (
                    "publish",
                    "metadata staging parent",
                    "metadata working directory",
                )
            )
            create_event = (
                "atomic-create",
                "metadata staging parent",
                "metadata working directory",
            )
            root_edge = (
                "validate",
                "metadata project root",
                "metadata staging parent",
            )
            working_edge = (
                "validate",
                "metadata staging parent",
                "metadata working directory",
            )
            acl_event = (
                "acl",
                atomically_created[0][0].name,
                "exact",
            )
            first_snapshot = (
                "snapshot",
                "source archive",
                "source_archive.iss",
            )
            self.assertLess(
                lifecycle.index(create_event), lifecycle.index(working_edge)
            )
            self.assertLess(
                lifecycle.index(working_edge), lifecycle.index(acl_event)
            )
            self.assertLess(
                lifecycle.index(acl_event), lifecycle.index(first_snapshot)
            )
            self.assertIn(root_edge, lifecycle[:publish_index])
            self.assertIn(working_edge, lifecycle[:publish_index])
            self.assertEqual(
                lifecycle[publish_index + 1 : publish_index + 3],
                [root_edge, working_edge],
            )
            self.assertTrue(
                all(
                    custody._handle is None
                    for _, custody in [*opened, *atomically_created]
                )
            )

    @unittest.skipUnless(os.name == "nt", "Windows custody route only")
    def test_authoritative_failure_retains_custodied_private_candidate(self) -> None:
        archive_payload, avi_payload = _fixture_payloads()
        real_cleanup = normalizer._cleanup_private_tree

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            with (
                patch.object(
                    normalizer,
                    "_cleanup_private_tree",
                    wraps=real_cleanup,
                ) as cleanup,
                self.assertRaises(MetadataNormalizationError),
            ):
                _normalize(
                    root,
                    archive_payload,
                    avi_payload,
                    expected_avi_sha256="0" * 64,
                )

            cleanup.assert_not_called()
            retained = list((root / "staging").iterdir())
            self.assertEqual(len(retained), 1)
            candidate = retained[0]
            self.assertTrue(candidate.is_dir())
            self.assertTrue(
                normalizer._windows_private_directory_acl_is_exact(candidate)
            )
            self.assertEqual(
                {entry.name for entry in candidate.iterdir()},
                {".sources"},
            )
            self.assertEqual(
                {entry.name for entry in (candidate / ".sources").iterdir()},
                {"source_archive.iss"},
            )

    def test_adapter_failure_still_cleans_its_path_only_candidate(self) -> None:
        archive_payload, avi_payload = _fixture_payloads()
        real_cleanup = normalizer._cleanup_private_tree

        def fail_after_snapshots(
            origins: dict[str, Path], snapshots: dict[str, Path]
        ) -> None:
            del origins, snapshots
            raise MetadataNormalizationError("forced adapter failure")

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            with (
                patch.object(
                    normalizer,
                    "_cleanup_private_tree",
                    wraps=real_cleanup,
                ) as cleanup,
                self.assertRaisesRegex(
                    MetadataNormalizationError,
                    "forced adapter failure",
                ),
            ):
                _normalize(
                    root,
                    archive_payload,
                    avi_payload,
                    test_adapters=_TestAdapters(
                        after_snapshots=fail_after_snapshots
                    ),
                )

            cleanup.assert_called_once()
            self.assertEqual(list((root / "staging").iterdir()), [])

    @unittest.skipUnless(os.name == "nt", "Windows custody route only")
    def test_post_publication_tamper_fails_without_deleting_output(self) -> None:
        archive_payload, avi_payload = _fixture_payloads()
        real_publish = normalizer._windows_publish_directory_by_handle

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            output = root / "staging" / "metadata-candidate" / METADATA_NAME

            def publish_then_tamper(
                *, source: object, parent: object, target_name: str
            ) -> None:
                real_publish(
                    source=source,
                    parent=parent,
                    target_name=target_name,
                )
                output.write_bytes(b"tampered-after-publication")

            with (
                patch.object(
                    normalizer,
                    "_windows_publish_directory_by_handle",
                    side_effect=publish_then_tamper,
                ),
                self.assertRaisesRegex(
                    MetadataNormalizationError,
                    "published metadata output",
                ),
            ):
                _normalize(root, archive_payload, avi_payload)

            self.assertEqual(output.read_bytes(), b"tampered-after-publication")

    def test_normalizes_exact_grammar_without_inventing_timestamps(self) -> None:
        archive_payload, avi_payload = _fixture_payloads()
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            receipt = _normalize(root, archive_payload, avi_payload)

            self.assertEqual(receipt["schema_version"], 1)
            self.assertEqual(
                receipt["artifact_kind"], "vast_kpp_legacy_iss_metadata"
            )
            self.assertEqual(receipt["generation_id"], "kpp_legacy_iss_v2")
            self.assertEqual(receipt["source_archive"]["record_count"], 3)
            self.assertEqual(receipt["exported_avi"]["frame_count"], 3)
            self.assertEqual(
                receipt["exported_avi"]["frame_count_authority"],
                "physical_movi_packet_sequence_validation",
            )
            self.assertEqual(len(receipt["frames"]), 3)
            self.assertEqual(
                receipt["frames"][0]["header_clock"]["calendar_text"],
                "2025-05-21 22:18:52.105",
            )
            self.assertIsNone(receipt["frames"][0]["frame_clock"])
            self.assertEqual(
                receipt["frames"][1]["frame_clock"],
                {
                    "frame_time": 1747865932110721,
                    "magnet_time": 1747865932086704,
                },
            )
            self.assertEqual(
                [event["kind"] for event in receipt["events"]],
                ["MD_TRUE", "STITCHING_STARTED", "IMAGE"],
            )
            self.assertEqual(
                [event["first_observed_frame_index"] for event in receipt["events"]],
                [0, 1, 2],
            )
            self.assertFalse(receipt["claims"]["timestamps_interpolated"])
            self.assertFalse(receipt["claims"]["clock_domains_equated"])
            self.assertFalse(receipt["claims"]["timezone_validated"])
            self.assertFalse(receipt["claims"]["event_semantics_validated"])
            self.assertFalse(receipt["claims"]["accuracy_ground_truth_validated"])
            self.assertEqual(
                receipt["exported_avi"]["packetization_contract"],
                "iss_record_media_start_to_next_record_media_start_or_eof_v1",
            )
            self.assertTrue(
                receipt["claims"]["avi_packet_source_interval_binding_validated"]
            )
            self.assertTrue(
                receipt["claims"][
                    "avi_physical_movi_packet_index_alignment_validated"
                ]
            )
            self.assertFalse(
                receipt["claims"][
                    "avi_demuxed_or_decoded_frame_index_alignment_validated"
                ]
            )
            self.assertFalse(
                receipt["claims"]["avi_packet_equals_declared_media_without_trailer"]
            )
            self.assertFalse(
                receipt["claims"]["avi_packet_payload_is_clean_jpeg"]
            )
            self.assertTrue(
                receipt["claims"]["source_and_avi_private_snapshots_verified"]
            )
            self.assertEqual(
                receipt["claims"]["output_set_directory_published_atomically"],
                os.name == "nt",
            )
            self.assertEqual(
                receipt["claims"][
                    "windows_project_root_staging_and_working_directory_"
                    "handle_custody_validated"
                ],
                os.name == "nt",
            )
            interval = receipt["frames"][0]["media"][
                "avi_packet_source_interval"
            ]
            self.assertEqual(
                interval["contract"],
                "iss_record_media_start_to_next_record_media_start_or_eof_v1",
            )
            self.assertGreater(
                interval["size_bytes"], receipt["frames"][0]["media"]["size_bytes"]
            )
            encoded = (
                root / "staging" / "metadata-candidate" / METADATA_NAME
            ).read_bytes()
            self.assertTrue(encoded.endswith(b"\n"))
            self.assertEqual(encoded.decode("ascii").encode("ascii"), encoded)
            self.assertEqual(json.loads(encoded), receipt)
            self.assertNotIn(str(root), encoded.decode("ascii"))
            self.assertEqual(
                list((root / "staging" / "metadata-candidate").iterdir()),
                [root / "staging" / "metadata-candidate" / METADATA_NAME],
            )

    def test_test_adapter_uses_private_snapshots_but_has_no_authority_claims(self) -> None:
        archive_payload, avi_payload = _fixture_payloads()
        observed_snapshot_paths: dict[str, Path] = {}

        def rebound_origins(
            origins: dict[str, Path], snapshots: dict[str, Path]
        ) -> None:
            observed_snapshot_paths.update(snapshots)
            origins["source_archive"].write_bytes(b"rebound-source")
            origins["exported_avi"].write_bytes(b"rebound-avi")

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            receipt = _normalize(
                root,
                archive_payload,
                avi_payload,
                test_adapters=_TestAdapters(after_snapshots=rebound_origins),
            )

            self.assertEqual(
                receipt["source_archive"]["sha256"], _sha256(archive_payload)
            )
            self.assertEqual(
                receipt["exported_avi"]["sha256"], _sha256(avi_payload)
            )
            self.assertEqual(
                receipt["status"],
                "non_authoritative_path_fallback_candidate",
            )
            self.assertTrue(
                receipt["claims"]["source_and_avi_private_snapshots_verified"]
            )
            self.assertFalse(
                receipt["claims"]["output_set_directory_published_atomically"]
            )
            self.assertFalse(
                receipt["claims"][
                    "windows_project_root_staging_and_working_directory_"
                    "handle_custody_validated"
                ]
            )
            self.assertEqual(
                set(observed_snapshot_paths), {"source_archive", "exported_avi"}
            )
            self.assertFalse(any(path.exists() for path in observed_snapshot_paths.values()))
            self.assertEqual(
                {entry.name for entry in (root / "staging").iterdir()},
                {"metadata-candidate"},
            )
            self.assertEqual(
                {entry.name for entry in (root / "staging" / "metadata-candidate").iterdir()},
                {METADATA_NAME},
            )

    def test_rejects_header_sentinel_timestamp_and_length_corruption(self) -> None:
        archive_payload, avi_payload = _fixture_payloads()
        mutations: dict[str, tuple[int, bytes]] = {
            "header prefix": (0, b"\x00"),
            "header marker": (44, b"\x00\x00\x00\x00"),
            "record sentinel": (HEADER_SIZE, struct.pack("<I", 0)),
            "timestamp reserved": (HEADER_SIZE + 4 + 14, struct.pack("<H", 1)),
            "media bound": (
                HEADER_SIZE + 4 + 16 + 7 * 4,
                struct.pack("<I", 512 * 1024 * 1024 + 1),
            ),
        }
        for label, (offset, replacement) in mutations.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as raw:
                corrupt = bytearray(archive_payload)
                corrupt[offset : offset + len(replacement)] = replacement
                with self.assertRaises(MetadataNormalizationError):
                    _normalize(Path(raw), bytes(corrupt), avi_payload)

    def test_rejects_malformed_json_shapes_and_duplicate_keys(self) -> None:
        first = b"#@@#MD_TRUE 21-05-2025 22:18:50.001<br>"
        invalid_payloads = {
            "duplicate": b'{"status":1,"status":1}',
            "boolean": b'{"status":true}',
            "wrong matrix": json.dumps(
                {
                    "data": [[1, 2, 3]] * 7,
                    "magnet_time": 1747865932086704,
                    "frame_time": 1747865932110721,
                },
                separators=(",", ":"),
            ).encode("ascii"),
            "16-digit": json.dumps(
                {
                    "data": [[1, 2, 3]] * 8,
                    "magnet_time": 747865932086704,
                    "frame_time": 1747865932110721,
                },
                separators=(",", ":"),
            ).encode("ascii"),
        }
        for label, tag4 in invalid_payloads.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                payload = _archive(
                    [_record(millisecond=105, primary=first, tag4=tag4)]
                )
                with self.assertRaises(MetadataNormalizationError):
                    _normalize(root, payload, b"avi", frame_count=1)

    def test_rejects_tlv_snapshot_media_and_eof_violations(self) -> None:
        first = b"#@@#MD_TRUE 21-05-2025 22:18:50.001<br>"
        cases = {
            "tag order": _archive(
                [_record(millisecond=105, primary=first, tag_order=(5, 4, 7))]
            ),
            "tag5": _archive(
                [_record(millisecond=105, primary=first, tag5=b"different")]
            ),
            "tag7": _archive(
                [_record(millisecond=105, primary=first, tag7=struct.pack("<I", 30))]
            ),
            "terminator": _archive(
                [_record(millisecond=105, primary=first, terminator=0)]
            ),
            "event regex": _archive(
                [_record(millisecond=105, primary=first + b"junk")]
            ),
            "media SOI": _archive(
                [
                    _record(
                        millisecond=105,
                        primary=first,
                        media=b"bad\xff\xd9I+v}",
                    )
                ]
            ),
            "media suffix": _archive(
                [
                    _record(
                        millisecond=105,
                        primary=first,
                        media=b"\xff\xd8\xffpayload\xff\xd9BAD!",
                    )
                ]
            ),
            "nonempty aux": _archive(
                [_record(millisecond=105, primary=first, aux=b"unexpected")]
            ),
            "EOF": _archive(
                [_record(millisecond=105, primary=first)], trailing=b"x"
            ),
        }
        for label, payload in cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as raw:
                with self.assertRaises(MetadataNormalizationError):
                    _normalize(Path(raw), payload, b"avi", frame_count=1)

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            shrinking = _archive(
                [
                    _record(millisecond=105, primary=first),
                    _record(
                        millisecond=110,
                        primary=b"#@@#IMAGE 22:18:52.003<br>",
                    ),
                ]
            )
            with self.assertRaisesRegex(
                MetadataNormalizationError, "append-only"
            ):
                _normalize(root, shrinking, b"avi", frame_count=2)

    def test_rejects_rebound_or_misaligned_avi_packets_and_clock_regressions(self) -> None:
        archive_payload, avi_payload = _fixture_payloads()
        rebound = bytearray(avi_payload)
        marker = rebound.index(b"second")
        rebound[marker : marker + len(b"second")] = b"SECOND"
        with tempfile.TemporaryDirectory() as raw:
            with self.assertRaisesRegex(MetadataNormalizationError, "packet"):
                _normalize(Path(raw), archive_payload, bytes(rebound))

        first = b"#@@#MD_TRUE 21-05-2025 22:18:50.001<br>"
        media = b"\xff\xd8\xff\xe0clock\xff\xd9I+v}"
        decreasing_header = _archive(
            [
                _record(millisecond=110, primary=first, media=media),
                _record(millisecond=105, primary=first, media=media),
            ]
        )
        with tempfile.TemporaryDirectory() as raw:
            with self.assertRaisesRegex(MetadataNormalizationError, "monotonic"):
                _normalize(
                    Path(raw),
                    decreasing_header,
                    _avi_from_archive(decreasing_header),
                    frame_count=2,
                )

        decreasing_rich_clock = _archive(
            [
                _record(
                    millisecond=105,
                    primary=first,
                    tag4=_rich_payload(
                        magnet_time=1747865932086704,
                        frame_time=1747865932110721,
                    ),
                    media=media,
                ),
                _record(
                    millisecond=110,
                    primary=first,
                    tag4=_rich_payload(
                        magnet_time=1747865932086703,
                        frame_time=1747865932110720,
                    ),
                    media=media,
                ),
            ]
        )
        with tempfile.TemporaryDirectory() as raw:
            with self.assertRaisesRegex(MetadataNormalizationError, "monotonic"):
                _normalize(
                    Path(raw),
                    decreasing_rich_clock,
                    _avi_from_archive(decreasing_rich_clock),
                    frame_count=2,
                )

    def test_accepts_bounded_avix_rec_padding_and_index_chunks(self) -> None:
        archive_payload, _ = _fixture_payloads()
        payloads = _archive_packet_payloads(archive_payload)
        first_movi = _riff_chunk(
            b"LIST",
            b"movi"
            + _riff_chunk(b"JUNK", b"x", pad_byte=b"\xa5")
            + _riff_chunk(b"00dc", payloads[0], pad_byte=b"\x7f")
            + _riff_chunk(b"ix00", b"synthetic-index"),
        )
        rec_payload = b"rec " + b"".join(
            _riff_chunk(b"00db", payload, pad_byte=b"\x5a")
            for payload in payloads[1:]
        )
        second_movi = _riff_chunk(
            b"LIST",
            b"movi" + _riff_chunk(b"LIST", rec_payload),
        )
        avi_payload = _riff_segment(b"AVI ", first_movi) + _riff_segment(
            b"AVIX", second_movi
        )

        with tempfile.TemporaryDirectory() as raw:
            receipt = _normalize(Path(raw), archive_payload, avi_payload)
        self.assertEqual(receipt["exported_avi"]["frame_count"], 3)

    def test_rejects_missing_padding_video_outside_movi_and_excess_nesting(self) -> None:
        archive_payload, _ = _fixture_payloads()
        payloads = _archive_packet_payloads(archive_payload)
        missing_padding = _riff_segment(
            b"AVI ",
            _riff_chunk(
                b"LIST",
                b"movi"
                + _riff_chunk(b"JUNK", b"x", include_padding=False)
                + b"".join(_riff_chunk(b"00dc", payload) for payload in payloads),
            ),
        )
        video_outside_movi = _riff_segment(
            b"AVI ",
            _riff_chunk(
                b"LIST",
                b"hdrl"
                + b"".join(
                    _riff_chunk(b"00dc", payload) for payload in payloads
                ),
            ),
        )
        valid_movi = _riff_chunk(
            b"LIST",
            b"movi"
            + b"".join(_riff_chunk(b"00dc", payload) for payload in payloads),
        )
        nested_payload = _riff_chunk(b"JUNK", b"")
        for _ in range(10):
            nested_payload = _riff_chunk(b"LIST", b"INFO" + nested_payload)
        excessive_nesting = _riff_segment(b"AVI ", valid_movi + nested_payload)

        for label, avi_payload, pattern in (
            ("missing padding", missing_padding, "chunk|padding|bound"),
            ("video outside movi", video_outside_movi, "outside movi"),
            ("nesting", excessive_nesting, "nesting"),
        ):
            with self.subTest(label=label), tempfile.TemporaryDirectory() as raw:
                with self.assertRaisesRegex(MetadataNormalizationError, pattern):
                    _normalize(Path(raw), archive_payload, avi_payload)

    def test_requires_all_external_pins_and_atomic_no_replace_staging_output(self) -> None:
        archive_payload, avi_payload = _fixture_payloads()
        failure_arguments = {
            "source hash": {"expected_source_sha256": "0" * 64},
            "source size": {
                "expected_source_size_bytes": len(archive_payload) + 1
            },
            "AVI hash": {"expected_avi_sha256": "0" * 64},
            "AVI size": {"expected_avi_size_bytes": len(avi_payload) + 1},
            "frame count": {"frame_count": 2},
        }
        for label, changes in failure_arguments.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                with self.assertRaises(MetadataNormalizationError):
                    _normalize(root, archive_payload, avi_payload, **changes)
                retained = list((root / "staging").iterdir())
                if label in {"source size", "AVI size"}:
                    self.assertEqual(retained, [])
                elif os.name == "nt":
                    self.assertEqual(len(retained), 1)
                    self.assertTrue(
                        normalizer._windows_private_directory_acl_is_exact(
                            retained[0]
                        )
                    )
                else:
                    self.assertEqual(retained, [])

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            archive = root / "13._03"
            avi = root / "underbody.avi"
            archive.write_bytes(archive_payload)
            avi.write_bytes(avi_payload)
            outside = root / "outside.json"
            with self.assertRaisesRegex(MetadataNormalizationError, "staging"):
                normalize_metadata(
                    project_root=root,
                    source_archive=archive,
                    expected_source_sha256=_sha256(archive_payload),
                    expected_source_size_bytes=len(archive_payload),
                    exported_avi=avi,
                    expected_exported_avi_sha256=_sha256(avi_payload),
                    expected_exported_avi_size_bytes=len(avi_payload),
                    exported_avi_frame_count=3,
                    output_path=outside,
                )

            output = root / "staging" / "candidate" / METADATA_NAME
            output.parent.mkdir(parents=True)
            sentinel = output.parent / "sentinel.txt"
            sentinel.write_bytes(b"occupied")
            with self.assertRaisesRegex(MetadataNormalizationError, "already exists"):
                normalize_metadata(
                    project_root=root,
                    source_archive=archive,
                    expected_source_sha256=_sha256(archive_payload),
                    expected_source_size_bytes=len(archive_payload),
                    exported_avi=avi,
                    expected_exported_avi_sha256=_sha256(avi_payload),
                    expected_exported_avi_size_bytes=len(avi_payload),
                    exported_avi_frame_count=3,
                    output_path=output,
                )
            self.assertEqual(sentinel.read_bytes(), b"occupied")
            self.assertFalse(output.exists())

            nested = root / "staging" / "outer" / "candidate" / METADATA_NAME
            with self.assertRaisesRegex(MetadataNormalizationError, "direct child"):
                normalize_metadata(
                    project_root=root,
                    source_archive=archive,
                    expected_source_sha256=_sha256(archive_payload),
                    expected_source_size_bytes=len(archive_payload),
                    exported_avi=avi,
                    expected_exported_avi_sha256=_sha256(avi_payload),
                    expected_exported_avi_size_bytes=len(avi_payload),
                    exported_avi_frame_count=3,
                    output_path=nested,
                )

            wrong_name = root / "staging" / "wrong-name" / "metadata.json"
            with self.assertRaisesRegex(MetadataNormalizationError, "fixed filename"):
                normalize_metadata(
                    project_root=root,
                    source_archive=archive,
                    expected_source_sha256=_sha256(archive_payload),
                    expected_source_size_bytes=len(archive_payload),
                    exported_avi=avi,
                    expected_exported_avi_sha256=_sha256(avi_payload),
                    expected_exported_avi_size_bytes=len(avi_payload),
                    exported_avi_frame_count=3,
                    output_path=wrong_name,
                )

    def test_cli_emits_the_same_canonical_receipt(self) -> None:
        archive_payload, avi_payload = _fixture_payloads()
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            archive = root / "13._03"
            avi = root / "iss_v2_underbody.avi"
            output = root / "staging" / "cli" / METADATA_NAME
            output.parent.parent.mkdir(parents=True)
            archive.write_bytes(archive_payload)
            avi.write_bytes(avi_payload)
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                result = main(
                    [
                        "--project-root",
                        str(root),
                        "--source-archive",
                        str(archive),
                        "--expected-source-sha256",
                        _sha256(archive_payload),
                        "--expected-source-size-bytes",
                        str(len(archive_payload)),
                        "--exported-avi",
                        str(avi),
                        "--expected-exported-avi-sha256",
                        _sha256(avi_payload),
                        "--expected-exported-avi-size-bytes",
                        str(len(avi_payload)),
                        "--exported-avi-frame-count",
                        "3",
                        "--output-path",
                        str(output),
                    ]
                )
            self.assertEqual(result, 0)
            self.assertEqual(json.loads(stdout.getvalue()), json.loads(output.read_bytes()))


if __name__ == "__main__":
    unittest.main()
