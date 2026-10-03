from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from seafile_operator_capacity_attestation_v2 import (  # noqa: E402
    GIB,
    SeafileOperatorCapacityAttestationV2Error,
    build_seafile_operator_capacity_attestation_v2,
    materialize_seafile_operator_capacity_attestation_v2,
    validate_seafile_operator_capacity_attestation_v2,
    write_immutable_attestation_v2,
)
from tests.test_seafile_capacity_attestation_v1 import rows  # noqa: E402


UPLOAD = "https://seafile.example/u/d/UploadSecretToken99"
READ = "https://seafile.example/d/ReadSecretToken99"
DESTINATION = "vast-full-publication-private-v1"


class SimulatedPhysicalCrash(BaseException):
    pass


def preflight(*, count: int = 3, size: int = 46_101_937) -> dict[str, object]:
    return {
        "schema_version": 1,
        "artifact_kind": "vast_seafile_preflight",
        "status": "ready",
        "transport": "https",
        "origin": "https://seafile.example",
        "read_capability": "verified",
        "upload_capability": "verified_get_only",
        "remote_file_count": count,
        "remote_size_bytes": size,
        "quota_visibility": "not_exposed_by_share_link",
    }


def confirmation(*, lower_bound: int = 500 * GIB) -> dict[str, object]:
    return {
        "basis": "operator_explicit_guarantee",
        "available_capacity_lower_bound_bytes": lower_bound,
        "confirmed_at_utc": "2026-08-25T18:00:00Z",
        "confirmation_reference": "codex-user-message-2026-08-25-seafile-500gib",
        "confirmation_statement": (
            "Гарантирую доступность 500+ гигабайтов на seafile"
        ),
    }


def receipt(**overrides: object) -> dict[str, object]:
    arguments: dict[str, object] = {
        "preflight": preflight(),
        "upload_url": UPLOAD,
        "read_url": READ,
        "destination_id": DESTINATION,
        "observed_pair_archives": rows(),
        "observed_at_utc": "2026-08-25T18:05:00Z",
        "operator_confirmation": confirmation(),
    }
    arguments.update(overrides)
    return build_seafile_operator_capacity_attestation_v2(**arguments)


class SeafileOperatorCapacityAttestationV2Tests(unittest.TestCase):
    def test_builds_secret_free_nonempty_destination_attestation(self) -> None:
        value = receipt()
        rendered = json.dumps(value, ensure_ascii=False, sort_keys=True)
        self.assertEqual(value["status"], "accepted_operator_capacity_lower_bound")
        self.assertEqual(
            value["operator_capacity"]["available_capacity_lower_bound_bytes"],
            500 * GIB,
        )
        self.assertEqual(value["preflight_observation"]["remote_file_count"], 3)
        self.assertEqual(value["destination"]["dedicated_namespace_claimed"], False)
        self.assertEqual(value["operator_capacity"]["quota_visibility"], "not_exposed_by_share_link")
        self.assertNotIn("UploadSecretToken99", rendered)
        self.assertNotIn("ReadSecretToken99", rendered)
        self.assertNotIn("confirmation_statement", value["operator_capacity"])
        accepted = validate_seafile_operator_capacity_attestation_v2(
            value,
            upload_url=UPLOAD,
            read_url=READ,
            destination_id=DESTINATION,
        )
        self.assertEqual(accepted, value)

    def test_tamper_rotated_tokens_wrong_origin_and_destination_fail_closed(self) -> None:
        cases: list[tuple[dict[str, object], str, str, str]] = []
        tampered = copy.deepcopy(receipt())
        tampered["operator_capacity"]["available_capacity_lower_bound_bytes"] -= 1
        cases.append((tampered, UPLOAD, READ, DESTINATION))
        cases.append((receipt(), UPLOAD.replace("UploadSecret", "RotatedUpload"), READ, DESTINATION))
        cases.append((receipt(), UPLOAD, READ.replace("seafile.example", "other.example"), DESTINATION))
        cases.append((receipt(), UPLOAD, READ, "vast-other-destination-v1"))
        for value, upload, read, destination in cases:
            with self.subTest(upload=upload, read=read, destination=destination):
                with self.assertRaises(SeafileOperatorCapacityAttestationV2Error):
                    validate_seafile_operator_capacity_attestation_v2(
                        value,
                        upload_url=upload,
                        read_url=read,
                        destination_id=destination,
                    )

    def test_sizing_above_operator_lower_bound_fails_closed(self) -> None:
        oversized = rows()
        for row in oversized:
            row["observed_pair_archive_bytes"] = 3 * GIB
        with self.assertRaisesRegex(
            SeafileOperatorCapacityAttestationV2Error, "lower bound",
        ):
            receipt(
                observed_pair_archives=oversized,
                operator_confirmation=confirmation(lower_bound=500 * GIB),
            )

    def test_preflight_permits_nonempty_but_rejects_unverified_or_wrong_origin(self) -> None:
        value = preflight(count=12, size=999)
        self.assertEqual(
            receipt(preflight=value)["preflight_observation"]["remote_file_count"],
            12,
        )
        for field, replacement in (
            ("read_capability", "not_verified"),
            ("upload_capability", "not_verified"),
            ("origin", "https://other.example"),
        ):
            broken = copy.deepcopy(value)
            broken[field] = replacement
            with self.subTest(field=field), self.assertRaises(
                SeafileOperatorCapacityAttestationV2Error
            ):
                receipt(preflight=broken)

    def test_immutable_writer_allows_identical_replay_and_rejects_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "operator-capacity-v2.json"
            value = receipt()
            first = write_immutable_attestation_v2(path, value)
            second = write_immutable_attestation_v2(path, value)
            self.assertEqual(first, second)
            path.chmod(0o600)
            path.write_text("{}\n", encoding="utf-8")
            with self.assertRaisesRegex(
                SeafileOperatorCapacityAttestationV2Error, "collision",
            ):
                write_immutable_attestation_v2(path, value)

    def test_immutable_writer_recovers_each_physical_crash_window(self) -> None:
        for crash_step in (
            "mid_write",
            "post_fsync_pre_publish",
            "post_publish_pre_parent_fsync",
        ):
            with self.subTest(crash_step=crash_step), tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / "operator-capacity-v2.json"
                value = receipt()
                faulted = False

                def fault(step: str, target: Path) -> None:
                    nonlocal faulted
                    self.assertEqual(target, path)
                    if step == crash_step and not faulted:
                        faulted = True
                        raise SimulatedPhysicalCrash(step)

                with self.assertRaises(SimulatedPhysicalCrash):
                    write_immutable_attestation_v2(
                        path,
                        value,
                        after_physical_commit_step=fault,
                    )
                published_inode = path.stat().st_ino if path.exists() else None
                descriptor = write_immutable_attestation_v2(path, value)
                self.assertTrue(faulted)
                self.assertEqual(
                    descriptor["sha256"], hashlib.sha256(path.read_bytes()).hexdigest()
                )
                if published_inode is not None:
                    self.assertEqual(path.stat().st_ino, published_inode)

    def test_immutable_writer_rejects_racing_foreign_and_rebound_final(self) -> None:
        for attack_step in (
            "post_fsync_pre_publish",
            "post_publish_pre_parent_fsync",
        ):
            with self.subTest(attack_step=attack_step), tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / "operator-capacity-v2.json"
                value = receipt()

                def attack(step: str, target: Path) -> None:
                    if step != attack_step:
                        return
                    if target.exists():
                        target.unlink()
                    target.write_bytes(b"foreign-operator-capacity-attestation\n")
                    target.chmod(0o444)

                with self.assertRaises(SeafileOperatorCapacityAttestationV2Error):
                    write_immutable_attestation_v2(
                        path,
                        value,
                        after_physical_commit_step=attack,
                    )
                foreign_inode = path.stat().st_ino
                foreign_payload = path.read_bytes()
                with self.assertRaisesRegex(
                    SeafileOperatorCapacityAttestationV2Error, "collision",
                ):
                    write_immutable_attestation_v2(path, value)
                self.assertEqual(path.stat().st_ino, foreign_inode)
                self.assertEqual(path.read_bytes(), foreign_payload)

    def test_materializer_ignores_env_links_and_uses_canonical_file(self) -> None:
        observed: dict[str, object] = {}

        class FakeStore:
            def __init__(self, links: object) -> None:
                observed["origin"] = links.base_url

            def preflight(
                self, *, live_upload_readback: bool = False,
            ) -> dict[str, object]:
                observed["live_upload_readback"] = live_upload_readback
                value = preflight()
                value["upload_capability"] = "verified_live_upload_readback"
                return value

        def loader(**arguments: object) -> list[dict[str, object]]:
            observed["loader"] = arguments
            return rows()

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            configs = root / "configs"
            configs.mkdir()
            sizing_index = root / "accepted/q4/index.json"
            sizing_index.parent.mkdir(parents=True)
            sizing_index.write_text("fixture\n", encoding="ascii")
            links_file = root / "seafile.txt"
            links_file.write_text(
                "download link - " + READ + "\n"
                "upload link - " + UPLOAD + "\n",
                encoding="utf-8",
            )
            output = configs / "operator-capacity-v2.json"
            environment = {
                "VAST_SEAFILE_UPLOAD_LINK": "poison-upload",
                "VAST_SEAFILE_READ_LINK": "poison-read",
            }
            with patch.dict(os.environ, environment, clear=False):
                result = materialize_seafile_operator_capacity_attestation_v2(
                    project_root=root,
                    sizing_index_path=sizing_index,
                    output_path=output,
                    destination_id=DESTINATION,
                    observed_at_utc="2026-08-25T18:05:00Z",
                    operator_confirmation=confirmation(),
                    links_file_path=links_file,
                    rows_loader=loader,
                    store_factory=FakeStore,
                )
                self.assertNotIn("VAST_SEAFILE_UPLOAD_LINK", os.environ)
                self.assertNotIn("VAST_SEAFILE_READ_LINK", os.environ)
            self.assertEqual(observed["origin"], "https://seafile.example")
            self.assertIs(observed["live_upload_readback"], True)
            self.assertEqual(observed["loader"]["project_root"], root)
            self.assertEqual(
                Path(observed["loader"]["index_path"]), sizing_index,
            )
            self.assertTrue(output.is_file())
            self.assertEqual(result["status"], "accepted_operator_capacity_lower_bound")
            self.assertEqual(result["capacity_lower_bound_bytes"], 500 * GIB)
            self.assertNotIn("SecretToken", json.dumps(result, sort_keys=True))

    def test_materializer_consumes_direct_link_file_without_environment(self) -> None:
        observed: dict[str, object] = {}

        class FakeStore:
            def __init__(self, links: object) -> None:
                self.links = links

            def preflight(
                self, *, live_upload_readback: bool = False,
            ) -> dict[str, object]:
                observed["live_upload_readback"] = live_upload_readback
                value = preflight()
                value["upload_capability"] = "verified_live_upload_readback"
                return value

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            (root / "configs").mkdir()
            sizing_index = root / "accepted/q4/index.json"
            sizing_index.parent.mkdir(parents=True)
            sizing_index.write_text("fixture\n", encoding="ascii")
            links_file = root / "seafile.txt"
            links_file.write_text(
                "download link - " + READ + "\n"
                "upload link - " + UPLOAD + "\n"
                "capacity - 1000 GB\n",
                encoding="utf-8",
            )
            output = root / "configs/operator-capacity-v2.json"
            with patch.dict(os.environ, {}, clear=True):
                result = materialize_seafile_operator_capacity_attestation_v2(
                    project_root=root,
                    sizing_index_path=sizing_index,
                    output_path=output,
                    destination_id=DESTINATION,
                    observed_at_utc="2026-08-25T18:05:00Z",
                    operator_confirmation=confirmation(),
                    links_file_path=links_file,
                    rows_loader=lambda **_arguments: rows(),
                    store_factory=FakeStore,
                )
            self.assertEqual(result["status"], "accepted_operator_capacity_lower_bound")
            self.assertIs(observed["live_upload_readback"], True)
            self.assertNotIn("SecretToken", json.dumps(result, sort_keys=True))
            alternate = root / "links.txt"
            alternate.write_bytes(links_file.read_bytes())
            with self.assertRaisesRegex(
                SeafileOperatorCapacityAttestationV2Error,
                "project_root/seafile.txt",
            ):
                materialize_seafile_operator_capacity_attestation_v2(
                    project_root=root,
                    sizing_index_path=sizing_index,
                    output_path=root / "configs/alternate-capacity.json",
                    destination_id=DESTINATION,
                    observed_at_utc="2026-08-25T18:05:00Z",
                    operator_confirmation=confirmation(),
                    links_file_path=alternate,
                    rows_loader=lambda **_arguments: rows(),
                    store_factory=FakeStore,
                )


if __name__ == "__main__":
    unittest.main()
