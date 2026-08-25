from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import seafile_capacity_attestation_v1 as target  # noqa: E402


GIB = 1024**3


def rows(size_bytes: int = 1024**2) -> list[dict[str, object]]:
    return [
        {
            "system": system,
            "codec": codec,
            "policy": policy,
            "deadline_ms": deadline,
            "observed_pair_archive_bytes": size_bytes,
            "pair_receipt_sha256": hashlib.sha256(
                f"{system}:{codec}:{policy}:{deadline}".encode("ascii")
            ).hexdigest(),
        }
        for system in target.SYSTEMS
        for codec in target.CODECS
        for policy in target.POLICIES
        for deadline in target.DEADLINES_MS
    ]


def build(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "account_info": {"total": 900 * GIB, "usage": 100 * GIB},
        "repository": {
            "repo_id": "01234567-89ab-cdef-8123-456789abcdef",
            "name": "VAST full publication 2026-08-25",
        },
        "preflight": {
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
        "upload_url": "https://seafile.example/u/d/UploadSecretToken99",
        "read_url": "https://seafile.example/d/ReadSecretToken99",
        "observed_pair_archives": rows(),
        "observed_at_utc": "2026-08-25T18:00:00Z",
        "server_identity": {
            "deployment_id": "external-seafile-publication-store-v1",
            "server_version": "13.0.0",
            "storage_scope": "account_quota_api",
        },
    }
    values.update(overrides)
    return target.build_seafile_capacity_attestation_v1(**values)


class SeafileCapacityAttestationV1Tests(unittest.TestCase):
    def test_exact_280_cell_projection_and_empty_dedicated_destination_are_accepted(self) -> None:
        value = build()
        self.assertEqual(value["status"], "accepted_dedicated_capacity")
        projection = value["sizing_projection"]
        self.assertEqual(projection["observed_cell_count"], 280)
        self.assertEqual(projection["measurement_repeat_multiplier"], 10)
        self.assertEqual(projection["projected_remote_bytes"], 2800 * 1024**2)
        self.assertEqual(projection["required_capacity_bytes"], 500 * GIB)
        self.assertEqual(value["account_quota"]["available_bytes"], 800 * GIB)
        self.assertEqual(value["destination"]["remote_file_count"], 0)
        rendered = json.dumps(value, sort_keys=True)
        self.assertNotIn("UploadSecretToken99", rendered)
        self.assertNotIn("ReadSecretToken99", rendered)
        unsigned = dict(value)
        observed_sha = unsigned.pop("sha256")
        self.assertEqual(
            observed_sha,
            hashlib.sha256(
                json.dumps(
                    unsigned,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=True,
                    allow_nan=False,
                ).encode("utf-8")
            ).hexdigest(),
        )

    def test_projection_formula_scales_above_the_500_gib_floor(self) -> None:
        value = build(
            account_info={"total": 5000 * GIB, "usage": 100 * GIB},
            observed_pair_archives=rows(GIB),
        )
        projection = value["sizing_projection"]
        self.assertEqual(projection["projected_remote_bytes"], 2800 * GIB)
        self.assertEqual(projection["required_capacity_bytes"], 3505 * GIB)

    def test_missing_or_duplicate_sizing_cell_quota_shortfall_and_foreign_file_fail_closed(self) -> None:
        incomplete = rows()[:-1]
        with self.assertRaisesRegex(target.SeafileCapacityAttestationV1Error, "280"):
            build(observed_pair_archives=incomplete)

        duplicate = rows()
        duplicate[-1] = dict(duplicate[0])
        with self.assertRaisesRegex(target.SeafileCapacityAttestationV1Error, "coordinate"):
            build(observed_pair_archives=duplicate)

        with self.assertRaisesRegex(target.SeafileCapacityAttestationV1Error, "quota"):
            build(account_info={"total": 550 * GIB, "usage": 100 * GIB})

        preflight = dict(build()["preflight_observation"])
        preflight["remote_file_count"] = 1
        preflight["remote_size_bytes"] = 7
        with self.assertRaisesRegex(target.SeafileCapacityAttestationV1Error, "empty"):
            build(preflight=preflight)

    def test_capability_origin_and_repository_identity_are_cross_bound(self) -> None:
        with self.assertRaisesRegex(target.SeafileCapacityAttestationV1Error, "origin"):
            build(read_url="https://other.example/d/ReadSecretToken99")
        with self.assertRaisesRegex(target.SeafileCapacityAttestationV1Error, "repo"):
            build(repository={"repo_id": "not-a-uuid", "name": "invalid"})

    def test_immutable_atomic_output_rejects_collision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "capacity.json"
            descriptor = target.write_immutable_attestation(output, build())
            self.assertEqual(descriptor["path"], str(output))
            self.assertEqual(descriptor["sha256"], hashlib.sha256(output.read_bytes()).hexdigest())
            target.write_immutable_attestation(output, build())
            output.write_text("tampered\n", encoding="utf-8")
            with self.assertRaisesRegex(
                target.SeafileCapacityAttestationV1Error, "collision"
            ):
                target.write_immutable_attestation(output, build())


if __name__ == "__main__":
    unittest.main()
