from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import backend_publication_runtime_authority as runtime_authority  # noqa: E402
from backend_publication_runtime_authority import (  # noqa: E402
    ARTIFACT_KIND,
    BackendPublicationRuntimeAuthorityError,
    assess_backend_publication_runtime_authority,
    build_backend_publication_runtime_authority,
    validate_backend_publication_runtime_authority,
)


def canonical_sha(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")).hexdigest()


def descriptor(root: Path, relative: str, payload: bytes) -> dict[str, object]:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return {
        "path": relative,
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def artifact(role: str, value: dict[str, object]) -> dict[str, object]:
    return {
        "role": role,
        "descriptor": copy.deepcopy(value),
        "content_identity_sha256": value["sha256"],
    }


def content_record(content: dict[str, object]) -> dict[str, object]:
    return {"content": content, "content_identity_sha256": canonical_sha(content)}


def fixture_fields(root: Path, *, policy: str = "cpu_only") -> dict[str, object]:
    manifest = descriptor(root, "dataset/manifest.json", b"dataset-manifest")
    dataset_file = descriptor(root, "dataset/kpp-h264.mp4", b"kpp-h264")
    source = artifact(
        "source_binary", descriptor(root, "runtime/source.bin", b"source")
    )
    backend = artifact(
        "runtime_binary", descriptor(root, "runtime/backend.bin", b"backend")
    )
    analytics_capability = artifact(
        "analytics_endpoint_capability",
        descriptor(root, "authority/analytics-capability.json", b"analytics-capability"),
    )
    analytics_binding = artifact(
        "analytics_worker_binding",
        descriptor(root, "authority/analytics-binding.json", b"analytics-binding"),
    )
    policy_capability = artifact(
        "policy_capability",
        descriptor(root, "authority/policy-capability.json", b"policy-capability"),
    )
    policy_calibration = artifact(
        "policy_calibration",
        descriptor(root, "authority/policy-calibration.json", b"policy-calibration"),
    )
    static_map = (
        artifact(
            "policy_static_map",
            descriptor(root, "authority/policy-static-map.json", b"policy-static-map"),
        )
        if policy == "static_hybrid" else None
    )
    return {
        "system": "gstreamer_custom",
        "policy": policy,
        "topology_kind": "shared_video_dag",
        "codec": "h264",
        "dataset_manifest": manifest,
        "dataset_files": [dataset_file],
        "source_runtime_artifacts": [source],
        "backend_runtime_artifacts": [backend],
        "analytics_authority": {
            "endpoint_authority": {
                "transport": "AF_UNIX/SOCK_SEQPACKET",
                "path_derivation_contract_sha256": "1" * 64,
                "peer_capability_identity_sha256": "2" * 64,
                "peer_binding_identity_sha256": "3" * 64,
                "bind_before_backend_launch": True,
                "peer_credentials_required": True,
            },
            "capability": analytics_capability,
            "bindings": [analytics_binding],
            "preprocessing_contract_sha256": "4" * 64,
        },
        "model_parity_acceptance_binding_sha256": "5" * 64,
        "policy_authority": {
            "capability": policy_capability,
            "calibration": policy_calibration,
            "static_map": static_map,
        },
        "cohort_topology_plan": content_record({
            "topology_kind": "shared_video_dag", "warmup_s": 30,
            "measurement_s": 180, "source_decode_count": 1,
        }),
        "resource_contract": content_record({"contract_version": 2}),
        "system_specific_launcher_input": content_record({
            "system": "gstreamer_custom",
            "launcher_kind": "dedicated_publication_runtime",
        }),
    }


def build_fixture(root: Path, *, policy: str = "cpu_only") -> dict[str, object]:
    return build_backend_publication_runtime_authority(
        project_root=root, **fixture_fields(root, policy=policy)
    )


class RuntimeAuthorityTest(unittest.TestCase):
    def test_build_validate_and_physical_assessment_without_acceptance_claim(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            authority = build_fixture(root)
            validated = validate_backend_publication_runtime_authority(
                authority, expected_system="gstreamer_custom",
                expected_policy="cpu_only",
                expected_topology_kind="shared_video_dag", expected_codec="h264",
            )
            self.assertEqual(validated, authority)
            assessment = assess_backend_publication_runtime_authority(
                authority, project_root=root,
            )
            self.assertEqual(assessment["status"], "physically_valid")
            self.assertEqual(assessment["blockers"], [])
            self.assertGreaterEqual(assessment["checked_artifact_count"], 8)
            self.assertNotIn("publication_ready", assessment)
            self.assertNotIn("accepted", assessment)

    def test_closed_schema_coordinate_and_self_hash_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            authority = build_fixture(root)
            extra = copy.deepcopy(authority)
            extra["grant_sha256"] = "f" * 64
            with self.assertRaises(BackendPublicationRuntimeAuthorityError):
                validate_backend_publication_runtime_authority(extra)
            with self.assertRaises(BackendPublicationRuntimeAuthorityError):
                validate_backend_publication_runtime_authority(
                    authority, expected_system="deepstream",
                )
            drifted = copy.deepcopy(authority)
            drifted["coordinate"]["codec"] = "h265"
            with self.assertRaisesRegex(
                BackendPublicationRuntimeAuthorityError, "self-hash",
            ):
                validate_backend_publication_runtime_authority(drifted)

    def test_live_socket_identity_and_circular_authorities_are_not_schema_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            authority = build_fixture(root)
            endpoint = authority["analytics_authority"]["endpoint_authority"]
            endpoint["socket_path"] = "/tmp/live.sock"
            endpoint["inode"] = 42
            unsigned = {
                key: value for key, value in authority.items()
                if key != "authority_sha256"
            }
            authority["authority_sha256"] = canonical_sha(unsigned)
            with self.assertRaisesRegex(
                BackendPublicationRuntimeAuthorityError, "endpoint authority fields",
            ):
                validate_backend_publication_runtime_authority(authority)
            for forbidden in (
                "runtime_binding_identity_sha256", "qualification_receipt_sha256",
                "identity_artifact_binding_sha256", "grant_sha256", "run_id",
                "output_dir", "receipt_sha256",
            ):
                with self.subTest(forbidden=forbidden):
                    value = build_fixture(root)
                    value[forbidden] = "a" * 64
                    with self.assertRaises(BackendPublicationRuntimeAuthorityError):
                        validate_backend_publication_runtime_authority(value)

    def test_static_map_is_required_only_for_static_hybrid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            self.assertEqual(
                build_fixture(root, policy="static_hybrid")["coordinate"]["policy"],
                "static_hybrid",
            )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            authority = build_fixture(root)
            authority["policy_authority"]["static_map"] = artifact(
                "policy_static_map",
                descriptor(root, "authority/forbidden-map.json", b"forbidden"),
            )
            unsigned = {k: v for k, v in authority.items() if k != "authority_sha256"}
            authority["authority_sha256"] = canonical_sha(unsigned)
            with self.assertRaisesRegex(
                BackendPublicationRuntimeAuthorityError, "prohibited",
            ):
                validate_backend_publication_runtime_authority(authority)

    def test_physical_tamper_links_and_aliases_block_assessment_and_build(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            fields = fixture_fields(root)
            authority = build_backend_publication_runtime_authority(
                project_root=root, **fields,
            )
            runtime_path = root / authority["backend_runtime_artifacts"][0]["descriptor"]["path"]
            runtime_path.write_bytes(b"tampered")
            assessment = assess_backend_publication_runtime_authority(
                authority, project_root=root,
            )
            self.assertEqual(assessment["status"], "blocked")
            self.assertTrue(any("drifted" in item for item in assessment["blockers"]))
            with self.assertRaisesRegex(
                BackendPublicationRuntimeAuthorityError, "physical assessment blocked",
            ):
                build_backend_publication_runtime_authority(
                    project_root=root, **fields,
                )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            authority = build_fixture(root)
            path = root / authority["source_runtime_artifacts"][0]["descriptor"]["path"]
            os.link(path, path.with_name("source-alias.bin"))
            assessment = assess_backend_publication_runtime_authority(
                authority, project_root=root,
            )
            self.assertEqual(assessment["status"], "blocked")
            self.assertTrue(any("hardlink" in item for item in assessment["blockers"]))

    def test_content_validator_is_pure_and_authority_is_leaf_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            authority = build_fixture(root)
            before = copy.deepcopy(authority)
            validated = validate_backend_publication_runtime_authority(authority)
            self.assertEqual(authority, before)
            self.assertEqual(validated, before)
            self.assertIsNot(validated, authority)
            self.assertEqual(authority["artifact_kind"], ARTIFACT_KIND)

    def test_artifact_content_identity_cannot_be_self_declared(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            authority = build_fixture(root)
            artifact_value = authority["analytics_authority"]["capability"]
            artifact_value["content_identity_sha256"] = "f" * 64
            unsigned = {
                key: value for key, value in authority.items()
                if key != "authority_sha256"
            }
            authority["authority_sha256"] = canonical_sha(unsigned)

            with self.assertRaisesRegex(
                BackendPublicationRuntimeAuthorityError,
                "content identity.*physical SHA-256",
            ):
                validate_backend_publication_runtime_authority(authority)
            assessment = assess_backend_publication_runtime_authority(
                authority, project_root=root,
            )
            self.assertEqual(assessment["status"], "blocked")
            self.assertTrue(any(
                "content identity" in blocker
                for blocker in assessment["blockers"]
            ))

    def test_descriptor_paths_reject_windows_escape_and_ads_grammar(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            original = build_fixture(root)
            unsafe_paths = (
                "/outside.bin", "\\outside.bin", "D:outside.bin",
                "file:stream", "runtime/CON.bin", "runtime/trailing.",
                "runtime/trailing ",
            )
            for unsafe_path in unsafe_paths:
                with self.subTest(path=unsafe_path):
                    authority = copy.deepcopy(original)
                    authority["dataset"]["manifest"]["path"] = unsafe_path
                    authority["dataset"]["content_identity_sha256"] = canonical_sha({
                        "manifest": authority["dataset"]["manifest"],
                        "files": authority["dataset"]["files"],
                    })
                    unsigned = {
                        key: value for key, value in authority.items()
                        if key != "authority_sha256"
                    }
                    authority["authority_sha256"] = canonical_sha(unsigned)
                    with self.assertRaisesRegex(
                        BackendPublicationRuntimeAuthorityError,
                        "descriptor path is unsafe",
                    ):
                        validate_backend_publication_runtime_authority(authority)

    @unittest.skipUnless(os.name == "nt", "Windows handle semantics only")
    def test_windows_parent_handles_deny_directory_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            authority = build_fixture(root)
            target = root / "dataset"
            backup = root / "dataset-swapped"
            attempted: list[OSError | None] = []
            original_open = runtime_authority._win_open_handle

            def observing_open(
                path: Path, *, directory: bool, read_data: bool = False,
            ) -> int:
                handle = original_open(
                    path, directory=directory, read_data=read_data,
                )
                if Path(path) == target and not attempted:
                    try:
                        target.rename(backup)
                    except OSError as error:
                        attempted.append(error)
                    else:
                        attempted.append(None)
                        backup.rename(target)
                return handle

            with mock.patch.object(
                runtime_authority, "_win_open_handle",
                side_effect=observing_open,
            ):
                assessment = assess_backend_publication_runtime_authority(
                    authority, project_root=root,
                )
            self.assertEqual(len(attempted), 1)
            self.assertIsInstance(attempted[0], OSError)
            self.assertEqual(
                assessment["status"], "physically_valid",
                assessment["blockers"],
            )

    @unittest.skipUnless(os.name == "nt", "Windows handle semantics only")
    def test_windows_native_query_failure_is_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            authority = build_fixture(root)
            with mock.patch.object(
                runtime_authority, "_win_query_handle",
                side_effect=OSError("injected native query failure"),
            ):
                assessment = assess_backend_publication_runtime_authority(
                    authority, project_root=root,
                )
            self.assertEqual(assessment["status"], "blocked")
            self.assertTrue(any(
                "native query failure" in item
                for item in assessment["blockers"]
            ))

    @unittest.skipUnless(os.name == "nt", "Windows handle semantics only")
    def test_windows_rewalk_file_id_mismatch_is_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            authority = build_fixture(root)
            original_open = runtime_authority._win_open_handle
            original_query = runtime_authority._win_query_handle
            counts: Counter[str] = Counter()
            drift_handles: set[int] = set()

            def tracking_open(
                path: Path, *, directory: bool, read_data: bool = False,
            ) -> int:
                handle = original_open(
                    path, directory=directory, read_data=read_data,
                )
                key = os.path.normcase(str(path))
                counts[key] += 1
                if key == os.path.normcase(str(root)) and counts[key] == 2:
                    drift_handles.add(int(handle))
                return handle

            def drifting_query(handle: int) -> dict[str, object]:
                info = original_query(handle)
                if int(handle) in drift_handles:
                    info = dict(info)
                    changed = bytearray(info["file_id"])
                    changed[0] ^= 0xFF
                    info["file_id"] = bytes(changed)
                return info

            with (
                mock.patch.object(
                    runtime_authority, "_win_open_handle",
                    side_effect=tracking_open,
                ),
                mock.patch.object(
                    runtime_authority, "_win_query_handle",
                    side_effect=drifting_query,
                ),
            ):
                assessment = assess_backend_publication_runtime_authority(
                    authority, project_root=root,
                )
            self.assertEqual(assessment["status"], "blocked")
            self.assertTrue(any(
                "path component changed" in item
                for item in assessment["blockers"]
            ))

    @unittest.skipUnless(os.name == "nt", "Windows handle semantics only")
    def test_windows_reparse_volume_and_duplicate_ids_are_fail_closed(self) -> None:
        for mutation, expected in (
            ("reparse", "reparse"),
            ("volume", "volume"),
            ("duplicate", "duplicate"),
        ):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                authority = build_fixture(root)
                target = root / "dataset"
                original_open = runtime_authority._win_open_handle
                original_query = runtime_authority._win_query_handle
                handle_paths: dict[int, Path] = {}
                root_identity: dict[str, object] = {}

                def tracking_open(
                    path: Path, *, directory: bool,
                    read_data: bool = False,
                ) -> int:
                    handle = original_open(
                        path, directory=directory, read_data=read_data,
                    )
                    handle_paths[int(handle)] = Path(path)
                    return handle

                def mutating_query(handle: int) -> dict[str, object]:
                    info = original_query(handle)
                    path = handle_paths[int(handle)]
                    if path == root and not root_identity:
                        root_identity.update(info)
                    if path == target:
                        info = dict(info)
                        if mutation == "reparse":
                            info["file_attributes"] = (
                                int(info["file_attributes"]) | 0x400
                            )
                        elif mutation == "volume":
                            info["volume_serial"] = (
                                int(root_identity["volume_serial"]) + 1
                            )
                        else:
                            info["file_id"] = root_identity["file_id"]
                    return info

                with (
                    mock.patch.object(
                        runtime_authority, "_win_open_handle",
                        side_effect=tracking_open,
                    ),
                    mock.patch.object(
                        runtime_authority, "_win_query_handle",
                        side_effect=mutating_query,
                    ),
                ):
                    assessment = assess_backend_publication_runtime_authority(
                        authority, project_root=root,
                    )
                self.assertEqual(assessment["status"], "blocked")
                self.assertTrue(any(
                    expected in item.lower()
                    for item in assessment["blockers"]
                ))


if __name__ == "__main__":
    unittest.main()
