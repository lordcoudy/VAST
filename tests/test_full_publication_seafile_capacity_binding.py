from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import full_publication_entrypoint as target  # noqa: E402
from seafile_artifact_store import SeafileShareLinks  # noqa: E402
from seafile_capacity_attestation_v1 import (  # noqa: E402
    build_seafile_capacity_attestation_v1,
)
from tests.test_seafile_capacity_attestation_v1 import GIB, rows  # noqa: E402


REPO_ID = "01234567-89ab-cdef-8123-456789abcdef"
UPLOAD = "https://seafile.example/u/d/UploadSecretToken99"
READ = "https://seafile.example/d/ReadSecretToken99"


def receipt() -> dict[str, object]:
    return build_seafile_capacity_attestation_v1(
        account_info={"total": 900 * GIB, "usage": 100 * GIB},
        repository={"repo_id": REPO_ID, "name": "VAST final"},
        preflight={
            "schema_version": 1,
            "artifact_kind": "vast_seafile_preflight",
            "status": "ready",
            "transport": "https",
            "origin": "https://seafile.example",
            "read_capability": "verified",
            "upload_capability": "verified_get_only",
            "remote_file_count": 0,
            "remote_size_bytes": 0,
            "quota_visibility": "not_exposed_by_share_link",
        },
        upload_url=UPLOAD,
        read_url=READ,
        observed_pair_archives=rows(),
        observed_at_utc="2026-08-25T18:00:00Z",
        server_identity={
            "deployment_id": "external-seafile-publication-store-v1",
            "server_version": "13.0.0",
            "storage_scope": "account_quota_api",
        },
    )


class FullPublicationSeafileCapacityBindingTests(unittest.TestCase):
    def test_physical_attestation_is_rehashed_and_cross_bound_to_live_capabilities(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "configs/capacity.json"
            path.parent.mkdir()
            path.write_text(json.dumps(receipt(), sort_keys=True) + "\n", encoding="utf-8")
            value = target._load_seafile_capacity_attestation(
                project_root=root,
                path=path,
                links=SeafileShareLinks.from_urls(UPLOAD, READ),
                destination_id=REPO_ID,
            )
            self.assertEqual(value["attestation"]["status"], "accepted_dedicated_capacity")
            self.assertEqual(value["descriptor"]["path"], "configs/capacity.json")
            self.assertEqual(value["capacity_confirmed_gib"], 800.0)
            self.assertNotIn("SecretToken", json.dumps(value, sort_keys=True))

    def test_tamper_destination_and_rotated_capability_fail_closed(self) -> None:
        mutations = []
        tampered = receipt()
        tampered["account_quota"]["available_bytes"] -= 1
        mutations.append((tampered, UPLOAD, READ, REPO_ID, "self-hash"))
        mutations.append((receipt(), UPLOAD, READ, "11234567-89ab-cdef-8123-456789abcdef", "destination"))
        mutations.append((receipt(), UPLOAD.replace("UploadSecretToken99", "RotatedUploadToken99"), READ, REPO_ID, "capability"))
        for value, upload, read, destination, message in mutations:
            with self.subTest(message=message), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                path = root / "capacity.json"
                path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
                with self.assertRaisesRegex(target.ContractError, message):
                    target._load_seafile_capacity_attestation(
                        project_root=root,
                        path=path,
                        links=SeafileShareLinks.from_urls(upload, read),
                        destination_id=destination,
                    )

    def test_legacy_capacity_number_is_not_a_production_authority(self) -> None:
        parser = target.build_parser()
        args = parser.parse_args(
            ["--run-root", "runs/full_publication/x", "--capacity-confirmed-gib", "500", "preflight"]
        )
        with self.assertRaisesRegex(target.ContractError, "attestation"):
            target._capacity_attestation_path_from_args(args)


if __name__ == "__main__":
    unittest.main()
