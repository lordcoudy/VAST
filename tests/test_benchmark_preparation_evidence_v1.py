from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import benchmark_preparation_evidence_v1 as target  # noqa: E402
import test_checkpoint_gstreamer_analytics_sidecar as sidecar_fixture  # noqa: E402


def canonical_bytes(value: object) -> bytes:
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


def canonical_sha(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)[:-1]).hexdigest()


def descriptor(path: Path) -> dict[str, object]:
    payload = path.read_bytes()
    return {"path": path.name, "size_bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}


def write_json(path: Path, value: object) -> None:
    path.write_bytes(canonical_bytes(value))


class BenchmarkPreparationEvidenceV1Tests(unittest.TestCase):
    def _documents(self, root: Path, *, diagnostic: bool = True) -> dict[str, Path]:
        root.mkdir()
        authority_core = {
            "lifecycle_id": "a" * 32,
            "service_identity_sha256": "b" * 64,
            "status": "live_operational_nonpublication",
        }
        authority = {
            **authority_core,
            "service_authority_sha256": canonical_sha(authority_core),
        }
        authority_path = root / target.AUTHORITY_FILENAME
        write_json(authority_path, authority)

        diagnostic_path = root / target.DIAGNOSTIC_FILENAME
        diagnostic_core = {
            "schema_version": 1,
            "artifact_kind": "vast_gstreamer_analytics_protocol_failure_diagnostic_v1",
            "lifecycle_id": authority["lifecycle_id"],
            "service_authority_sha256": authority["service_authority_sha256"],
            "observed_at_utc": "2026-09-21T00:00:00+00:00",
            "protocol_mode": "gstreamer",
            "attribution": "unavailable",
            "request_id": None,
            "run_id": None,
            "arm_id": None,
            "branch": None,
            "resource": None,
            "expected": {"byte_length": None, "sha256": None, "seals": None},
            "observed": {"byte_length": None, "sha256": None, "seals": None},
            "failure_stage": "control_envelope",
        }
        diagnostic_value = {
            **diagnostic_core,
            "identity": {"algorithm": "sha256", "sha256": canonical_sha(diagnostic_core)},
        }
        if diagnostic:
            write_json(diagnostic_path, diagnostic_value)

        message = "historical guardian failure"
        if diagnostic:
            message += "; protocol_diagnostic=protocol_failure_diagnostic.v1.json; sha256=" + descriptor(diagnostic_path)["sha256"]
        lifecycle_core = {
            "schema_version": 1,
            "artifact_kind": "vast_gstreamer_analytics_production_service_lifecycle_v1",
            "status": "failed_stop_nonpublication",
            "lifecycle_id": authority["lifecycle_id"],
            "service_identity_sha256": authority["service_identity_sha256"],
            "service_authority_sha256": authority["service_authority_sha256"],
            "readiness_artifact": {
                "path": str(authority_path),
                "size_bytes": descriptor(authority_path)["size_bytes"],
                "sha256": descriptor(authority_path)["sha256"],
            },
            "failure": {"type": "ProtocolError", "message": message},
        }
        lifecycle = {
            **lifecycle_core,
            "identity": {"algorithm": "sha256", "sha256": canonical_sha(lifecycle_core)},
        }
        lifecycle_path = root / target.LIFECYCLE_FILENAME
        write_json(lifecycle_path, lifecycle)
        return {
            "authority": authority_path,
            "diagnostic": diagnostic_path,
            "lifecycle": lifecycle_path,
        }

    def test_snapshots_bound_failed_diagnostic_immutably(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            guardian = root / "guardian"
            paths = self._documents(guardian)
            snapshot = root / "snapshot"
            result = target.snapshot_failed_guardian_evidence(guardian, snapshot)
            self.assertEqual(result["status"], "failed_guardian_diagnostic_snapshotted")
            self.assertTrue(result["non_authorizing"])
            self.assertEqual(Path(result["snapshot_directory"]), snapshot)
            for key, source in paths.items():
                copied = snapshot / source.name
                self.assertEqual(copied.read_bytes(), source.read_bytes())
                expected_descriptor = descriptor(copied)
                expected_descriptor["path"] = f"{snapshot.name}/{source.name}"
                self.assertEqual(result["descriptors"][key], expected_descriptor)
            with self.assertRaisesRegex(target.BenchmarkPreparationEvidenceV1Error, "already exists"):
                target.snapshot_failed_guardian_evidence(guardian, snapshot)
            self.assertEqual((snapshot / target.DIAGNOSTIC_FILENAME).read_bytes(), paths["diagnostic"].read_bytes())

    def test_rejects_tampered_diagnostic_and_lifecycle_bindings(self) -> None:
        for mutation in ("diagnostic", "lifecycle", "authority"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                guardian = root / "guardian"
                paths = self._documents(guardian)
                if mutation == "diagnostic":
                    value = json.loads(paths["diagnostic"].read_text(encoding="ascii"))
                    value["failure_stage"] = "tampered"
                    write_json(paths["diagnostic"], value)
                elif mutation == "lifecycle":
                    value = json.loads(paths["lifecycle"].read_text(encoding="ascii"))
                    value["service_authority_sha256"] = "f" * 64
                    core = {key: item for key, item in value.items() if key != "identity"}
                    value["identity"]["sha256"] = canonical_sha(core)
                    write_json(paths["lifecycle"], value)
                else:
                    value = json.loads(paths["authority"].read_text(encoding="ascii"))
                    value["status"] = "tampered"
                    core = {key: item for key, item in value.items() if key != "service_authority_sha256"}
                    value["service_authority_sha256"] = canonical_sha(core)
                    write_json(paths["authority"], value)
                with self.assertRaises(target.BenchmarkPreparationEvidenceV1Error):
                    target.snapshot_failed_guardian_evidence(guardian, root / "snapshot")
                self.assertFalse((root / "snapshot").exists())

    def test_rejects_malformed_marker_and_nonstring_fact_hash(self) -> None:
        for mutation in ("marker", "fact_hash"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                guardian = root / "guardian"
                paths = self._documents(guardian)
                lifecycle = json.loads(paths["lifecycle"].read_text(encoding="ascii"))
                if mutation == "marker":
                    lifecycle["failure"]["message"] = (
                        "failure; protocol_diagnostic=foreign.json; sha256=" + "a" * 64
                    )
                else:
                    diagnostic = json.loads(paths["diagnostic"].read_text(encoding="ascii"))
                    diagnostic["expected"]["sha256"] = 7
                    diagnostic_core = {
                        key: value for key, value in diagnostic.items() if key != "identity"
                    }
                    diagnostic["identity"]["sha256"] = canonical_sha(diagnostic_core)
                    write_json(paths["diagnostic"], diagnostic)
                    lifecycle["failure"]["message"] = (
                        "failure; protocol_diagnostic=protocol_failure_diagnostic.v1.json; sha256="
                        + descriptor(paths["diagnostic"])["sha256"]
                    )
                lifecycle_core = {key: value for key, value in lifecycle.items() if key != "identity"}
                lifecycle["identity"]["sha256"] = canonical_sha(lifecycle_core)
                write_json(paths["lifecycle"], lifecycle)
                with self.assertRaises(target.BenchmarkPreparationEvidenceV1Error):
                    target.snapshot_failed_guardian_evidence(guardian, root / "snapshot")

    def test_output_open_failure_closes_the_opened_source_custody(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            guardian = root / "guardian"
            self._documents(guardian)
            source_custody = mock.Mock()
            with mock.patch.object(
                target.PhysicalRootCustodyV1,
                "open",
                side_effect=(
                    source_custody,
                    target.PublicationPhysicalIoV1Error("injected output open failure"),
                ),
            ):
                with self.assertRaises(target.BenchmarkPreparationEvidenceV1Error):
                    target.snapshot_failed_guardian_evidence(guardian, root / "snapshot")
            source_custody.close.assert_called_once_with()

    def test_actual_sidecar_failure_is_consumable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = sidecar_fixture.GStreamerAnalyticsSidecarTests("runTest")
            fixture.setUp()
            service = fixture._production_service(root, sidecar_fixture._ProcessFactory(fixture.config))
            authority = service.start()
            client = sidecar_fixture.socket.socket(
                sidecar_fixture.socket.AF_UNIX, sidecar_fixture.socket.SOCK_SEQPACKET
            )
            client.connect(str(service.front_socket))
            descriptor_fd = sidecar_fixture.create_sealed_memfd("wrong-content", b"xyz")
            try:
                sidecar_fixture.send_packet(client, sidecar_fixture._request(b"abc"), fds=(descriptor_fd,))
                self.assertTrue(service._stop.wait(5), "sidecar integrity failure stayed live")
                lifecycle = service.stop()
            finally:
                sidecar_fixture.close_fds((descriptor_fd,))
                client.close()
            self.assertEqual(lifecycle["status"], "failed_stop_nonpublication")
            result = target.snapshot_failed_guardian_evidence(
                root / "production-evidence", root / "failed-diagnostic-snapshot"
            )
            self.assertEqual(result["status"], "failed_guardian_diagnostic_snapshotted")
            self.assertEqual(
                result["descriptors"]["diagnostic"]["sha256"],
                hashlib.sha256(
                    (root / "production-evidence" / target.DIAGNOSTIC_FILENAME).read_bytes()
                ).hexdigest(),
            )
    def test_historical_failed_lifecycle_without_diagnostic_is_explicitly_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            guardian = root / "guardian"
            self._documents(guardian, diagnostic=False)
            result = target.snapshot_failed_guardian_evidence(guardian, root / "snapshot")
            self.assertEqual(result["status"], "historical_diagnostic_missing")
            self.assertTrue(result["non_authorizing"])
            self.assertIsNone(result["snapshot_directory"])
            self.assertIsNone(result["source_descriptors"]["diagnostic"])
            self.assertFalse((root / "snapshot").exists())

    def test_persistence_failure_returns_no_snapshot_success(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            guardian = root / "guardian"
            paths = self._documents(guardian)
            original = paths["diagnostic"].read_bytes()
            with mock.patch.object(
                target.PhysicalRootCustodyV1,
                "write_exclusive",
                side_effect=target.PublicationPhysicalIoV1Error("injected persistence failure"),
            ):
                with self.assertRaisesRegex(
                    target.BenchmarkPreparationEvidenceV1Error, "physical custody"
                ):
                    target.snapshot_failed_guardian_evidence(guardian, root / "snapshot")
            self.assertEqual(paths["diagnostic"].read_bytes(), original)
            self.assertFalse((root / "snapshot").exists())
    def test_rejects_unsafe_lifecycle_and_output_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            guardian = root / "guardian"
            self._documents(guardian)
            outside = root / "outside.json"
            outside.write_text("{}\n", encoding="ascii")
            with self.assertRaises(target.BenchmarkPreparationEvidenceV1Error):
                target.snapshot_failed_guardian_evidence(
                    guardian, root / "snapshot", lifecycle_path=outside
                )
            if os.name == "posix":
                nested = root / "nested"
                nested.mkdir()
                unsafe_parent = nested / "unsafe-parent"
                unsafe_parent.symlink_to(root, target_is_directory=True)
                with self.assertRaises(target.BenchmarkPreparationEvidenceV1Error):
                    target.snapshot_failed_guardian_evidence(guardian, unsafe_parent / "snapshot")


if __name__ == "__main__":
    unittest.main()
