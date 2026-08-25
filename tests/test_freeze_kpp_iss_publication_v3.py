from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from freeze_kpp_iss_publication_v3 import (  # noqa: E402
    AUTHORIZATION_BASIS_ID,
    AUTHORIZATION_RECEIPT_DOMAIN,
    DATASET_IDS,
    GENERATION_ID,
    MANIFEST_DOMAIN,
    PublicationCorpusFreezeError,
    _TestAdapters,
    _canonical_bytes,
    _freeze_publication_corpus_impl,
)


SOURCE_ROOT = "data/videos/kpp/kpp_legacy_iss_v2"
TARGET_ROOT = "data/videos/kpp/kpp_iss_publication_v3"


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _seal(value: dict[str, object], *, field: str, domain: bytes) -> None:
    unsigned = dict(value)
    unsigned.pop(field, None)
    value[field] = hashlib.sha256(domain + _canonical_bytes(unsigned)).hexdigest()


def _media_contract(variant: str, role: str) -> dict[str, object]:
    underbody = role == "underbody"
    frame_count = 35646 if underbody else 33120
    width = 1700 if underbody else 1920
    height = 236 if underbody else 1080
    duration_ns = 59_410_000_000 if underbody else 55_200_000_000
    codec_name = "h264" if variant == "h264" else "hevc"
    return {
        "codec_name": codec_name,
        "pix_fmt": "yuv420p",
        "width": width,
        "height": height,
        "r_frame_rate": "600/1",
        "avg_frame_rate": "600/1",
        "frame_count": frame_count,
        "duration_ns": duration_ns,
        "color_range": "tv",
        "stream_time_base": "1/600",
        "stream_duration_ts": frame_count,
        "decoded_frame_count": frame_count,
        "decoded_first_pts": 0,
        "decoded_last_pts": frame_count - 1,
        "decoded_pts_steps": [1],
        "decoded_frame_signatures": [
            {
                "width": width,
                "height": height,
                "pix_fmt": "yuv420p",
                "color_range": "tv",
            }
        ],
    }


class CorpusFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.source_root = root / SOURCE_ROOT
        self.receipt_root = self.source_root / "receipts"
        self.receipt_root.mkdir(parents=True)
        (self.source_root / "metadata").mkdir()
        self.source_archives = [
            {
                "archive_logical_id": "13._03",
                "size_bytes": 2464770411,
                "sha256": "1" * 64,
                "role": "underbody",
                "payload_offset": 1313,
            },
            {
                "archive_logical_id": "13._03_2",
                "size_bytes": 33049105,
                "sha256": "2" * 64,
                "role": "front_gate",
                "payload_offset": 278,
            },
        ]
        self.media: dict[tuple[str, str], dict[str, object]] = {}
        for variant in ("h264", "h265"):
            directory = self.source_root / variant
            directory.mkdir()
            for role in ("underbody", "front_gate"):
                payload = f"frozen-{variant}-{role}\n".encode("ascii")
                path = directory / f"iss_v2_{role}.mp4"
                path.write_bytes(payload)
                self.media[(variant, role)] = {
                    "source_path": path.relative_to(root).as_posix(),
                    "size_bytes": len(payload),
                    "sha256": _sha(payload),
                    "media": _media_contract(variant, role),
                }

        self.receipts: dict[str, dict[str, object]] = {}
        extraction = {
            "schema_version": 1,
            "artifact_kind": "vast_kpp_legacy_iss_extraction_receipt",
            "generation_id": "kpp_legacy_iss_v2",
            "status": "headless_stream_copy_candidate",
            "source_archives": copy.deepcopy(self.source_archives),
            "outputs": [
                {
                    "role": "underbody",
                    "sha256": "3" * 64,
                    "size_bytes": 2465052990,
                },
                {
                    "role": "front_gate",
                    "sha256": "4" * 64,
                    "size_bytes": 33088368,
                },
            ],
            "claims": {
                "publication_authorized": False,
                "v1_dataset_identity_equivalent": False,
                "accuracy_ground_truth_validated": False,
                "source_timestamps_preserved": False,
            },
        }
        _seal(
            extraction,
            field="extraction_receipt_sha256",
            domain=b"VAST:kpp-legacy-iss-extraction-receipt:v1\0",
        )
        self.receipts["extraction"] = extraction

        transcode = {
            "schema_version": 1,
            "artifact_kind": "vast_kpp_legacy_iss_v2_transcode_receipt",
            "generation_id": "kpp_legacy_iss_v2",
            "status": "pinned_codec_transcode_candidate",
            "source_extraction": {},
            "outputs": [
                {
                    "codec_variant": variant,
                    "role": role,
                    "size_bytes": descriptor["size_bytes"],
                    "sha256": descriptor["sha256"],
                    "media": copy.deepcopy(descriptor["media"]),
                }
                for (variant, role), descriptor in self.media.items()
            ],
            "tools": [
                {
                    "role": "ffprobe",
                    "executable_sha256": "5" * 64,
                    "version_output_sha256": "6" * 64,
                }
            ],
            "claims": {
                "publication_authorized": False,
                "v1_dataset_identity_equivalent": False,
                "accuracy_ground_truth_validated": False,
                "source_timestamps_preserved": False,
                "outputs_validated_by_pinned_ffprobe": True,
            },
        }
        self.receipts["transcode"] = transcode

        metadata = {
            "schema_version": 1,
            "artifact_kind": "vast_kpp_legacy_iss_metadata",
            "generation_id": "kpp_legacy_iss_v2",
            "status": "authoritative_windows_candidate",
            "source_archive": copy.deepcopy(self.source_archives[0]),
            "exported_avi": {
                "sha256": extraction["outputs"][0]["sha256"],
                "size_bytes": extraction["outputs"][0]["size_bytes"],
            },
            "claims": {
                "publication_authorized": False,
                "v1_dataset_identity_equivalent": False,
                "accuracy_ground_truth_validated": False,
                "source_timestamps_preserved": False,
            },
        }
        _seal(
            metadata,
            field="normalization_receipt_sha256",
            domain=b"VAST:kpp-legacy-iss-metadata:v1\0",
        )
        self.receipts["metadata"] = metadata

        self.pins: dict[str, object] = {
            "source_archives": copy.deepcopy(self.source_archives),
            "receipts": {},
            "media": copy.deepcopy(self.media),
            "ffprobe": {
                "executable_sha256": "5" * 64,
                "version_output_sha256": "6" * 64,
            },
        }
        self._write_receipt("extraction")
        extraction_pin = self.pins["receipts"]["extraction"]
        transcode["source_extraction"] = {
            "file_sha256": extraction_pin["sha256"],
            "extraction_receipt_sha256": extraction[
                "extraction_receipt_sha256"
            ],
        }
        _seal(
            transcode,
            field="transcode_receipt_sha256",
            domain=b"VAST:kpp-legacy-iss-v2-transcode-receipt:v1\0",
        )
        self._write_receipt("transcode")
        self._write_receipt("metadata")

        materialization = {
            "schema_version": 1,
            "artifact_kind": "vast_kpp_legacy_iss_v2_materialization_receipt",
            "generation_id": "kpp_legacy_iss_v2",
            "status": "physically_assessed_candidate",
            "publishable": False,
            "publication_authorized": False,
            "source_receipt_external_pins": {
                role: self.pins["receipts"][role]["sha256"]
                for role in ("extraction", "transcode", "metadata")
            },
            "installed_artifacts": [
                {
                    "installed_path": descriptor["source_path"],
                    "size_bytes": descriptor["size_bytes"],
                    "sha256": descriptor["sha256"],
                }
                for descriptor in self.media.values()
            ],
            "claims": {
                "publication_authorized": False,
                "publishable": False,
            },
        }
        _seal(
            materialization,
            field="materialization_receipt_sha256",
            domain=(
                b"VAST:kpp-legacy-iss-v2-materialization-receipt:v1\0"
            ),
        )
        self.receipts["materialization"] = materialization
        self._write_receipt("materialization")

    def _receipt_path(self, role: str) -> Path:
        names = {
            "extraction": "receipts/kpp_iss_v2_extraction_receipt.json",
            "transcode": "receipts/kpp_iss_v2_transcode_receipt.json",
            "metadata": "metadata/iss_v2_underbody_metadata.json",
            "materialization": "kpp_iss_v2_materialization_receipt.json",
        }
        return self.source_root / names[role]

    def _self_field(self, role: str) -> str:
        return {
            "extraction": "extraction_receipt_sha256",
            "transcode": "transcode_receipt_sha256",
            "metadata": "normalization_receipt_sha256",
            "materialization": "materialization_receipt_sha256",
        }[role]

    def _write_receipt(self, role: str) -> None:
        value = self.receipts[role]
        payload = _canonical_bytes(value)
        path = self._receipt_path(role)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        self.pins["receipts"][role] = {
            "source_path": path.relative_to(self.root).as_posix(),
            "size_bytes": len(payload),
            "sha256": _sha(payload),
            "self_hash_field": self._self_field(role),
            "self_hash": value[self._self_field(role)],
        }

    def reseal_and_repin(self, role: str, *, domain: bytes) -> None:
        _seal(
            self.receipts[role],
            field=self._self_field(role),
            domain=domain,
        )
        self._write_receipt(role)

    def adapters(self, *, prober=None) -> _TestAdapters:
        if prober is None:
            by_name = {
                f"{variant}/iss_v2_{role}.mp4": copy.deepcopy(
                    descriptor["media"]
                )
                for (variant, role), descriptor in self.media.items()
            }
            prober = lambda path: copy.deepcopy(
                by_name[f"{path.parent.name}/{path.name}"]
            )
        return _TestAdapters(
            source_pins=copy.deepcopy(self.pins),
            prober=prober,
            ffprobe_descriptor=copy.deepcopy(self.pins["ffprobe"]),
        )

    def freeze(self, *, adapters: _TestAdapters | None = None):
        return _freeze_publication_corpus_impl(
            project_root=self.root,
            authorization_basis=AUTHORIZATION_BASIS_ID,
            ffprobe=None,
            test_adapters=adapters or self.adapters(),
        )


class FreezeKppIssPublicationV3Tests(unittest.TestCase):
    def test_happy_path_freezes_distinct_authorized_corpus_without_retranscode(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = CorpusFixture(Path(tmp))

            manifest = fixture.freeze()

            target = fixture.root / TARGET_ROOT
            self.assertTrue(target.is_dir())
            self.assertEqual(GENERATION_ID, "kpp_iss_publication_v3")
            self.assertEqual(
                DATASET_IDS,
                {
                    "h264": "kpp_iss_publication_v3_h264",
                    "h265": "kpp_iss_publication_v3_h265",
                },
            )
            for (variant, role), descriptor in fixture.media.items():
                source = fixture.root / descriptor["source_path"]
                frozen = target / variant / f"iss_v2_{role}.mp4"
                self.assertEqual(frozen.read_bytes(), source.read_bytes())
            authorization = json.loads(
                (target / "kpp_iss_publication_v3_authorization_receipt.json")
                .read_text(encoding="ascii")
            )
            manifest_from_disk = json.loads(
                (target / "kpp_iss_publication_v3_manifest.json").read_text(
                    encoding="ascii"
                )
            )
            self.assertEqual(manifest, manifest_from_disk)
            self.assertEqual(
                authorization["authorization_basis"]["basis_id"],
                AUTHORIZATION_BASIS_ID,
            )
            for value in (authorization, manifest):
                self.assertTrue(value["claims"]["publication_authorized"])
                self.assertFalse(
                    value["claims"]["accuracy_ground_truth_validated"]
                )
                self.assertFalse(value["claims"]["production_routing_validated"])
                self.assertFalse(value["claims"]["v1_dataset_identity_equivalent"])
                self.assertTrue(value["claims"]["media_reused_without_retranscode"])
            auth_unsigned = dict(authorization)
            auth_hash = auth_unsigned.pop("authorization_receipt_sha256")
            self.assertEqual(
                auth_hash,
                hashlib.sha256(
                    AUTHORIZATION_RECEIPT_DOMAIN + _canonical_bytes(auth_unsigned)
                ).hexdigest(),
            )
            manifest_unsigned = dict(manifest)
            manifest_hash = manifest_unsigned.pop("manifest_sha256")
            self.assertEqual(
                manifest_hash,
                hashlib.sha256(
                    MANIFEST_DOMAIN + _canonical_bytes(manifest_unsigned)
                ).hexdigest(),
            )

    def test_rejects_tampered_receipt_even_when_file_pin_is_updated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = CorpusFixture(Path(tmp))
            fixture.receipts["extraction"]["claims"]["source_timestamps_preserved"] = True
            fixture._write_receipt("extraction")

            with self.assertRaisesRegex(
                PublicationCorpusFreezeError, "self hash"
            ):
                fixture.freeze(adapters=fixture.adapters())

    def test_rejects_resealed_v1_identity_spoof(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = CorpusFixture(Path(tmp))
            fixture.receipts["extraction"]["claims"][
                "v1_dataset_identity_equivalent"
            ] = True
            fixture.reseal_and_repin(
                "extraction",
                domain=b"VAST:kpp-legacy-iss-extraction-receipt:v1\0",
            )

            with self.assertRaisesRegex(
                PublicationCorpusFreezeError, "v1.*equivalence|v1.*identity"
            ):
                fixture.freeze(adapters=fixture.adapters())

    def test_rejects_resealed_accuracy_ground_truth_claim(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = CorpusFixture(Path(tmp))
            fixture.receipts["metadata"]["claims"][
                "accuracy_ground_truth_validated"
            ] = True
            fixture.reseal_and_repin(
                "metadata", domain=b"VAST:kpp-legacy-iss-metadata:v1\0"
            )

            with self.assertRaisesRegex(
                PublicationCorpusFreezeError, "accuracy ground truth"
            ):
                fixture.freeze(adapters=fixture.adapters())

    def test_rejects_media_byte_drift_before_publish(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = CorpusFixture(Path(tmp))
            media = fixture.root / fixture.media[("h265", "front_gate")][
                "source_path"
            ]
            media.write_bytes(media.read_bytes() + b"tamper")

            with self.assertRaisesRegex(
                PublicationCorpusFreezeError, "size|SHA-256"
            ):
                fixture.freeze(adapters=fixture.adapters())
            self.assertFalse((fixture.root / TARGET_ROOT).exists())

    def test_rejects_ffprobe_contract_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = CorpusFixture(Path(tmp))

            def drifted_probe(path: Path) -> dict[str, object]:
                variant = path.parent.name
                role = "underbody" if "underbody" in path.name else "front_gate"
                observed = _media_contract(variant, role)
                observed["frame_count"] = int(observed["frame_count"]) - 1
                return observed

            with self.assertRaisesRegex(
                PublicationCorpusFreezeError, "ffprobe|frame_count"
            ):
                fixture.freeze(adapters=fixture.adapters(prober=drifted_probe))

    def test_existing_target_is_never_replaced_or_merged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = CorpusFixture(Path(tmp))
            target = fixture.root / TARGET_ROOT
            target.mkdir(parents=True)
            sentinel = target / "sentinel.txt"
            sentinel.write_text("keep", encoding="ascii")

            with self.assertRaisesRegex(
                PublicationCorpusFreezeError, "already exists"
            ):
                fixture.freeze(adapters=fixture.adapters())

            self.assertEqual(sentinel.read_text(encoding="ascii"), "keep")
            self.assertEqual(list(target.iterdir()), [sentinel])


if __name__ == "__main__":
    unittest.main()
