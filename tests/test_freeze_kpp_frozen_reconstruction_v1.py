from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from freeze_kpp_frozen_reconstruction_v1 import (  # noqa: E402
    AUTHORIZATION_BASIS_ID,
    AUTHORIZATION_RECEIPT_DOMAIN,
    DATASET_IDS,
    GENERATION_ID,
    MANIFEST_DOMAIN,
    ReconstructionFreezeError,
    SOURCE_AUTHORIZATION_DOMAIN,
    SOURCE_MANIFEST_DOMAIN,
    SOURCE_ROOT,
    TARGET_ROOT,
    _TestAdapters,
    _canonical_bytes,
    _freeze_reconstruction_impl,
)


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _seal(value: dict[str, object], *, field: str, domain: bytes) -> None:
    unsigned = dict(value)
    unsigned.pop(field, None)
    value[field] = hashlib.sha256(domain + _canonical_bytes(unsigned)).hexdigest()


def _write(path: Path, payload: bytes) -> dict[str, object]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return {"size_bytes": len(payload), "sha256": _sha(payload)}


class ReconstructionFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.source = root / SOURCE_ROOT
        self.source.mkdir(parents=True)
        self.media: dict[tuple[str, str], dict[str, object]] = {}
        for codec in ("h264", "h265"):
            for role in ("underbody", "front_gate"):
                relative = f"{codec}/iss_v2_{role}.mp4"
                payload = f"{codec}:{role}:physical-bytes".encode("ascii")
                descriptor = _write(self.source / relative, payload)
                self.media[(codec, role)] = {
                    "source_path": f"{SOURCE_ROOT}/{relative}",
                    **descriptor,
                }

        self.receipts: list[dict[str, object]] = []
        for name in ("source_a.json", "source_b.json"):
            payload = _canonical_bytes({"artifact": name, "claim": False})
            descriptor = _write(self.source / "receipts" / name, payload)
            self.receipts.append(
                {
                    "source_path": f"{SOURCE_ROOT}/receipts/{name}",
                    "installed_name": name,
                    **descriptor,
                }
            )

        self.authorization = {
            "schema_version": 1,
            "artifact_kind": "vast_kpp_iss_publication_v3_authorization_receipt",
            "generation_id": "kpp_iss_publication_v3",
            "dataset_ids": {
                "h264": "kpp_iss_publication_v3_h264",
                "h265": "kpp_iss_publication_v3_h265",
            },
            "status": "authorized_for_performance_publication",
            "claims": self.source_claims(),
        }
        _seal(
            self.authorization,
            field="authorization_receipt_sha256",
            domain=SOURCE_AUTHORIZATION_DOMAIN,
        )
        auth_payload = _canonical_bytes(self.authorization)
        auth_relative = "kpp_iss_publication_v3_authorization_receipt.json"
        auth_pin = _write(self.source / auth_relative, auth_payload)
        self.authorization_pin = {
            "source_path": f"{SOURCE_ROOT}/{auth_relative}",
            **auth_pin,
            "authorization_receipt_sha256": self.authorization[
                "authorization_receipt_sha256"
            ],
        }

        self.manifest = {
            "schema_version": 1,
            "artifact_kind": "vast_kpp_iss_publication_v3_manifest",
            "generation_id": "kpp_iss_publication_v3",
            "status": "frozen_publication_corpus",
            "dataset_root": SOURCE_ROOT,
            "dataset_ids": copy.deepcopy(self.authorization["dataset_ids"]),
            "source_generation": {
                "generation_id": "kpp_legacy_iss_v2",
                "identity_equivalent": False,
            },
            "source_receipts": [
                {
                    "path": item["source_path"],
                    "size_bytes": item["size_bytes"],
                    "sha256": item["sha256"],
                }
                for item in self.receipts
            ],
            "media_artifacts": [
                {
                    "codec_variant": codec,
                    "role": role,
                    "path": descriptor["source_path"],
                    "size_bytes": descriptor["size_bytes"],
                    "sha256": descriptor["sha256"],
                }
                for (codec, role), descriptor in self.media.items()
            ],
            "authorization_receipt": {
                "path": self.authorization_pin["source_path"],
                "size_bytes": self.authorization_pin["size_bytes"],
                "sha256": self.authorization_pin["sha256"],
                "authorization_receipt_sha256": self.authorization_pin[
                    "authorization_receipt_sha256"
                ],
            },
            "claims": self.source_claims(),
        }
        _seal(self.manifest, field="manifest_sha256", domain=SOURCE_MANIFEST_DOMAIN)
        manifest_payload = _canonical_bytes(self.manifest)
        manifest_relative = "kpp_iss_publication_v3_manifest.json"
        manifest_pin = _write(self.source / manifest_relative, manifest_payload)
        self.manifest_pin = {
            "source_path": f"{SOURCE_ROOT}/{manifest_relative}",
            **manifest_pin,
            "manifest_sha256": self.manifest["manifest_sha256"],
        }

    @staticmethod
    def source_claims() -> dict[str, bool]:
        return {
            "publication_authorized": True,
            "publication_scope_performance_and_topology_only": True,
            "accuracy_ground_truth_validated": False,
            "production_routing_validated": False,
            "v1_dataset_identity_equivalent": False,
            "source_timestamps_preserved": False,
            "media_reused_without_retranscode": True,
            "source_receipt_graph_exactly_pinned": True,
            "all_media_bytes_and_ffprobe_contracts_verified": True,
            "output_set_directory_published_atomically": True,
        }

    def adapters(self) -> _TestAdapters:
        return _TestAdapters(
            source_pins={
                "manifest": copy.deepcopy(self.manifest_pin),
                "authorization": copy.deepcopy(self.authorization_pin),
                "media": copy.deepcopy(self.media),
                "receipts": copy.deepcopy(self.receipts),
            }
        )

    def freeze(self, *, basis: str = AUTHORIZATION_BASIS_ID):
        return _freeze_reconstruction_impl(
            project_root=self.root,
            authorization_basis=basis,
            test_adapters=self.adapters(),
        )

    def rewrite_manifest_and_repin(self) -> None:
        _seal(self.manifest, field="manifest_sha256", domain=SOURCE_MANIFEST_DOMAIN)
        payload = _canonical_bytes(self.manifest)
        path = self.source / "kpp_iss_publication_v3_manifest.json"
        path.write_bytes(payload)
        self.manifest_pin.update(
            {
                "size_bytes": len(payload),
                "sha256": _sha(payload),
                "manifest_sha256": self.manifest["manifest_sha256"],
            }
        )


class FreezeKppFrozenReconstructionV1Tests(unittest.TestCase):
    def test_happy_path_creates_distinct_standalone_reconstruction(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = ReconstructionFixture(Path(tmp))

            manifest = fixture.freeze()

            target = fixture.root / TARGET_ROOT
            self.assertTrue(target.is_dir())
            self.assertEqual(GENERATION_ID, "kpp_frozen_reconstruction_v1")
            self.assertEqual(
                DATASET_IDS,
                {
                    "h264": "kpp_frozen_reconstruction_v1_h264",
                    "h265": "kpp_frozen_reconstruction_v1_h265",
                },
            )
            for (codec, role), source_descriptor in fixture.media.items():
                source = fixture.root / str(source_descriptor["source_path"])
                copied = target / codec / f"iss_v2_{role}.mp4"
                self.assertEqual(source.read_bytes(), copied.read_bytes())
                self.assertNotEqual(os.stat(source).st_ino, os.stat(copied).st_ino)
            authorization = json.loads(
                (target / "kpp_frozen_reconstruction_v1_authorization_receipt.json")
                .read_text(encoding="ascii")
            )
            self.assertEqual(
                authorization["historical_v1"]["source_bytes_available"], False
            )
            self.assertFalse(
                authorization["claims"]["historical_v1_dataset_identity_equivalent"]
            )
            self.assertTrue(
                authorization["claims"]["reconstruction_identity_distinct"]
            )
            self.assertEqual(
                manifest["source_publication"]["generation_id"],
                "kpp_iss_publication_v3",
            )
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

    def test_rejects_missing_explicit_authorization(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = ReconstructionFixture(Path(tmp))
            with self.assertRaisesRegex(ReconstructionFreezeError, "authorization"):
                fixture.freeze(basis="wrong")

    def test_rejects_tampered_source_manifest_with_only_file_pin_updated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = ReconstructionFixture(Path(tmp))
            fixture.manifest["status"] = "tampered"
            payload = _canonical_bytes(fixture.manifest)
            (fixture.source / "kpp_iss_publication_v3_manifest.json").write_bytes(
                payload
            )
            fixture.manifest_pin.update(
                {"size_bytes": len(payload), "sha256": _sha(payload)}
            )

            with self.assertRaisesRegex(ReconstructionFreezeError, "self hash"):
                fixture.freeze()

    def test_rejects_resealed_historical_v1_identity_spoof(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = ReconstructionFixture(Path(tmp))
            fixture.manifest["claims"]["v1_dataset_identity_equivalent"] = True
            fixture.rewrite_manifest_and_repin()

            with self.assertRaisesRegex(
                ReconstructionFreezeError, "v1.*identity|identity.*v1"
            ):
                fixture.freeze()

    def test_rejects_media_pin_that_disagrees_with_source_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = ReconstructionFixture(Path(tmp))
            descriptor = fixture.media[("h264", "underbody")]
            path = fixture.root / str(descriptor["source_path"])
            path.write_bytes(b"replacement")
            descriptor.update(
                {"size_bytes": len(b"replacement"), "sha256": _sha(b"replacement")}
            )

            with self.assertRaisesRegex(ReconstructionFreezeError, "media graph"):
                fixture.freeze()

    def test_refuses_to_replace_existing_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = ReconstructionFixture(Path(tmp))
            target = fixture.root / TARGET_ROOT
            target.mkdir(parents=True)
            sentinel = target / "sentinel"
            sentinel.write_text("keep", encoding="ascii")

            with self.assertRaisesRegex(ReconstructionFreezeError, "already exists"):
                fixture.freeze()
            self.assertEqual(sentinel.read_text(encoding="ascii"), "keep")


if __name__ == "__main__":
    unittest.main()
