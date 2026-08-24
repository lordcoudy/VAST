from __future__ import annotations

import copy
import hashlib
import inspect
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

import backend_runtime_validator_authority as validator_authority  # noqa: E402
from backend_runtime_validator_authority import (  # noqa: E402
    ARTIFACT_KIND,
    ASSESSMENT_KIND,
    BackendRuntimeValidatorAuthorityError,
    assess_backend_runtime_cell_validator_authority,
    build_backend_runtime_cell_validator_authority,
    validate_backend_runtime_cell_validator_authority,
)


def canonical_sha(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")).hexdigest()


def reseal(value: dict[str, object]) -> None:
    value.pop("authority_sha256", None)
    value["authority_sha256"] = canonical_sha(value)


class BackendRuntimeValidatorAuthorityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        (self.root / "validators").mkdir()
        self.implementation = self.root / "validators" / "cell_validator.py"
        self.implementation.write_bytes(b"def validate_cell(value):\n    return value\n")
        self.protocol_sha = hashlib.sha256(b"protocol-v1").hexdigest()
        self.input_sha = hashlib.sha256(b"input-schema-v3").hexdigest()
        self.output_sha = hashlib.sha256(b"output-schema-v3").hexdigest()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def build(self, *, path: str = "validators/cell_validator.py") -> dict[str, object]:
        return build_backend_runtime_cell_validator_authority(
            project_root=self.root,
            validator_id="backend-runtime-cell-validator-v1",
            implementation_path=path,
            validation_protocol_identity_sha256=self.protocol_sha,
            input_schema_identity_sha256=self.input_sha,
            output_schema_identity_sha256=self.output_sha,
        )

    def test_public_abi_requires_explicit_expected_pin(self) -> None:
        signature = inspect.signature(
            validate_backend_runtime_cell_validator_authority
        )
        parameter = signature.parameters["expected_authority_sha256"]
        self.assertEqual(parameter.kind, inspect.Parameter.KEYWORD_ONLY)
        self.assertIs(parameter.default, inspect.Parameter.empty)

    def test_builder_derives_closed_authority_and_assessment_is_non_authorizing(self) -> None:
        authority = self.build()
        descriptor = authority["implementation"]["descriptor"]
        payload = self.implementation.read_bytes()
        self.assertEqual(authority["artifact_kind"], ARTIFACT_KIND)
        self.assertEqual(descriptor, {
            "path": "validators/cell_validator.py",
            "size_bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        })
        self.assertEqual(
            authority["implementation"]["content_identity_sha256"],
            descriptor["sha256"],
        )
        self.assertEqual(authority["supported_qualification_schema_version"], 3)
        self.assertIs(authority["deterministic"], True)
        validated = validate_backend_runtime_cell_validator_authority(
            authority, expected_authority_sha256=authority["authority_sha256"]
        )
        self.assertEqual(validated, authority)
        assessment = assess_backend_runtime_cell_validator_authority(
            authority, project_root=self.root,
            expected_authority_sha256=authority["authority_sha256"],
        )
        self.assertEqual(assessment["artifact_kind"], ASSESSMENT_KIND)
        self.assertEqual(assessment["status"], "physically_valid")
        self.assertEqual(assessment["checked_artifact_count"], 1)
        self.assertEqual(assessment["blockers"], [])
        self.assertIs(assessment["execution_authorized"], False)
        self.assertIs(assessment["validation_records_authenticated"], False)

    def test_wrong_pin_and_tampering_fail_closed(self) -> None:
        authority = self.build()
        with self.assertRaises(BackendRuntimeValidatorAuthorityError):
            validate_backend_runtime_cell_validator_authority(
                authority, expected_authority_sha256=hashlib.sha256(b"wrong").hexdigest()
            )
        for mutation in ("semantic", "descriptor", "protocol"):
            changed = copy.deepcopy(authority)
            if mutation == "semantic":
                changed["implementation"]["content_identity_sha256"] = "0" * 64
            elif mutation == "descriptor":
                changed["implementation"]["descriptor"]["sha256"] = "1" * 64
            else:
                changed["validation_protocol_identity_sha256"] = "2" * 64
            with self.assertRaises(BackendRuntimeValidatorAuthorityError):
                validate_backend_runtime_cell_validator_authority(
                    changed, expected_authority_sha256=authority["authority_sha256"]
                )

    def test_extra_and_cyclic_downstream_fields_fail_before_hashing(self) -> None:
        authority = self.build()
        for field in ("grant_sha256", "dispatch_sha256", "receipt_sha256"):
            changed = copy.deepcopy(authority)
            changed[field] = "0" * 64
            reseal(changed)
            with self.assertRaises(BackendRuntimeValidatorAuthorityError):
                validate_backend_runtime_cell_validator_authority(
                    changed, expected_authority_sha256=changed["authority_sha256"]
                )
        cyclic = copy.deepcopy(authority)
        cyclic["downstream"] = cyclic
        with self.assertRaises(BackendRuntimeValidatorAuthorityError):
            validate_backend_runtime_cell_validator_authority(
                cyclic, expected_authority_sha256=authority["authority_sha256"]
            )

    def test_cross_platform_path_grammar_rejects_escape_ads_and_reserved_names(self) -> None:
        authority = self.build()
        invalid = (
            "/outside.py", "../outside.py", "validators/../outside.py",
            "C:/outside.py", "C:outside.py", "validators\\cell_validator.py",
            "validators/cell_validator.py:ads", "CON.py", "aux.txt",
            "validators./cell_validator.py", "validators/cell_validator.py.",
            "validators/cell_validator.py ",
        )
        for path in invalid:
            with self.subTest(path=path):
                changed = copy.deepcopy(authority)
                changed["implementation"]["descriptor"]["path"] = path
                reseal(changed)
                with self.assertRaises(BackendRuntimeValidatorAuthorityError):
                    validate_backend_runtime_cell_validator_authority(
                        changed,
                        expected_authority_sha256=changed["authority_sha256"],
                    )

    def test_physical_tamper_blocks_without_authenticating_or_authorizing(self) -> None:
        authority = self.build()
        self.implementation.write_bytes(b"def validate_cell(value):\n    return None\n")
        assessment = assess_backend_runtime_cell_validator_authority(
            authority, project_root=self.root,
            expected_authority_sha256=authority["authority_sha256"],
        )
        self.assertEqual(assessment["status"], "blocked")
        self.assertEqual(assessment["checked_artifact_count"], 0)
        self.assertTrue(assessment["blockers"])
        self.assertIs(assessment["execution_authorized"], False)
        self.assertIs(assessment["validation_records_authenticated"], False)

    def test_noncanonical_project_root_blocks(self) -> None:
        authority = self.build()
        assessment = assess_backend_runtime_cell_validator_authority(
            authority, project_root=Path("."),
            expected_authority_sha256=authority["authority_sha256"],
        )
        self.assertEqual(assessment["status"], "blocked")
        self.assertIs(assessment["execution_authorized"], False)

    def test_hardlink_is_rejected_by_builder(self) -> None:
        alias = self.root / "validators" / "alias.py"
        os.link(self.implementation, alias)
        with self.assertRaises(BackendRuntimeValidatorAuthorityError):
            self.build()

    def test_symlink_is_rejected_by_builder(self) -> None:
        link = self.root / "validators" / "linked_validator.py"
        try:
            link.symlink_to(self.implementation)
        except (OSError, NotImplementedError) as error:
            self.skipTest(f"symlink creation unavailable: {error}")
        with self.assertRaises(BackendRuntimeValidatorAuthorityError):
            self.build(path="validators/linked_validator.py")

    @unittest.skipUnless(os.name == "nt", "Windows handle semantics only")
    def test_windows_parent_handle_denies_directory_replacement(self) -> None:
        authority = self.build()
        target = self.root / "validators"
        backup = self.root / "validators-swapped"
        attempted: list[OSError | None] = []
        original_open = validator_authority._win_open_handle

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
            validator_authority, "_win_open_handle", side_effect=observing_open,
        ):
            assessment = assess_backend_runtime_cell_validator_authority(
                authority, project_root=self.root,
                expected_authority_sha256=authority["authority_sha256"],
            )
        self.assertEqual(len(attempted), 1)
        self.assertIsInstance(attempted[0], OSError)
        self.assertEqual(
            assessment["status"], "physically_valid", assessment["blockers"],
        )

    @unittest.skipUnless(os.name == "nt", "Windows handle semantics only")
    def test_windows_root_handle_denies_directory_replacement(self) -> None:
        authority = self.build()
        target = self.root
        backup = target.with_name(f"{target.name}-swapped")
        attempted: list[OSError | None] = []
        original_open = validator_authority._win_open_handle

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
            validator_authority, "_win_open_handle", side_effect=observing_open,
        ):
            assessment = assess_backend_runtime_cell_validator_authority(
                authority, project_root=self.root,
                expected_authority_sha256=authority["authority_sha256"],
            )
        self.assertEqual(len(attempted), 1)
        self.assertIsInstance(attempted[0], OSError)
        self.assertEqual(
            assessment["status"], "physically_valid", assessment["blockers"],
        )

    @unittest.skipUnless(os.name == "nt", "Windows handle semantics only")
    def test_windows_native_query_failure_is_fail_closed_and_cleans_handle(self) -> None:
        authority = self.build()
        original_open = validator_authority._win_open_handle
        original_close = validator_authority._win_close_handle
        opened: list[int] = []
        closed: list[int] = []
        handle_paths: dict[int, Path] = {}

        def tracking_open(
            path: Path, *, directory: bool, read_data: bool = False,
        ) -> int:
            handle = original_open(
                path, directory=directory, read_data=read_data,
            )
            opened.append(int(handle))
            handle_paths[int(handle)] = Path(path)
            return handle

        def failing_query(handle: int) -> dict[str, object]:
            if handle_paths[int(handle)] == self.implementation:
                raise OSError("injected native query failure")
            return validator_authority_query(handle)

        def tracking_close(handle: int) -> None:
            closed.append(int(handle))
            original_close(handle)

        validator_authority_query = validator_authority._win_query_handle
        with (
            mock.patch.object(
                validator_authority, "_win_open_handle", side_effect=tracking_open,
            ),
            mock.patch.object(
                validator_authority, "_win_query_handle",
                side_effect=failing_query,
            ),
            mock.patch.object(
                validator_authority, "_win_close_handle", side_effect=tracking_close,
            ),
        ):
            assessment = assess_backend_runtime_cell_validator_authority(
                authority, project_root=self.root,
                expected_authority_sha256=authority["authority_sha256"],
            )
        self.assertEqual(assessment["status"], "blocked")
        self.assertTrue(any(
            "native query failure" in blocker
            for blocker in assessment["blockers"]
        ))
        self.assertEqual(len(opened), 3)
        self.assertEqual(Counter(opened), Counter(closed))

    @unittest.skipUnless(os.name == "nt", "Windows handle semantics only")
    def test_windows_rewalk_file_id_mismatch_is_fail_closed(self) -> None:
        authority = self.build()
        original_open = validator_authority._win_open_handle
        original_query = validator_authority._win_query_handle
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
            if key == os.path.normcase(str(self.root)) and counts[key] == 2:
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
                validator_authority, "_win_open_handle", side_effect=tracking_open,
            ),
            mock.patch.object(
                validator_authority, "_win_query_handle", side_effect=drifting_query,
            ),
        ):
            assessment = assess_backend_runtime_cell_validator_authority(
                authority, project_root=self.root,
                expected_authority_sha256=authority["authority_sha256"],
            )
        self.assertEqual(assessment["status"], "blocked")
        self.assertTrue(any(
            "path component changed" in blocker
            for blocker in assessment["blockers"]
        ))

    @unittest.skipUnless(os.name == "nt", "Windows handle semantics only")
    def test_windows_fresh_final_reopen_rejects_hardlink_drift(self) -> None:
        authority = self.build()
        original_open = validator_authority._win_open_handle
        original_query = validator_authority._win_query_handle
        final_open_count = 0
        fresh_final_handles: set[int] = set()

        def tracking_open(
            path: Path, *, directory: bool, read_data: bool = False,
        ) -> int:
            nonlocal final_open_count
            handle = original_open(
                path, directory=directory, read_data=read_data,
            )
            if Path(path) == self.implementation:
                final_open_count += 1
                if final_open_count == 2:
                    fresh_final_handles.add(int(handle))
            return handle

        def drifting_query(handle: int) -> dict[str, object]:
            info = original_query(handle)
            if int(handle) in fresh_final_handles:
                info = dict(info)
                info["nlink"] = 2
            return info

        with (
            mock.patch.object(
                validator_authority, "_win_open_handle", side_effect=tracking_open,
            ),
            mock.patch.object(
                validator_authority, "_win_query_handle", side_effect=drifting_query,
            ),
        ):
            assessment = assess_backend_runtime_cell_validator_authority(
                authority, project_root=self.root,
                expected_authority_sha256=authority["authority_sha256"],
            )
        self.assertEqual(assessment["status"], "blocked")
        self.assertTrue(any(
            "hardlink" in blocker.lower() or "path component changed" in blocker
            for blocker in assessment["blockers"]
        ))

    @unittest.skipUnless(os.name == "nt", "Windows handle semantics only")
    def test_windows_outer_root_identity_mismatch_is_fail_closed(self) -> None:
        authority = self.build()
        original_open = validator_authority._win_open_handle
        original_query = validator_authority._win_query_handle
        root_handles: set[int] = set()

        def tracking_open(
            path: Path, *, directory: bool, read_data: bool = False,
        ) -> int:
            handle = original_open(
                path, directory=directory, read_data=read_data,
            )
            if Path(path) == self.root:
                root_handles.add(int(handle))
            return handle

        def drifting_query(handle: int) -> dict[str, object]:
            info = original_query(handle)
            if int(handle) in root_handles:
                info = dict(info)
                changed = bytearray(info["file_id"])
                changed[-1] ^= 0xFF
                info["file_id"] = bytes(changed)
            return info

        with (
            mock.patch.object(
                validator_authority, "_win_open_handle", side_effect=tracking_open,
            ),
            mock.patch.object(
                validator_authority, "_win_query_handle", side_effect=drifting_query,
            ),
        ):
            assessment = assess_backend_runtime_cell_validator_authority(
                authority, project_root=self.root,
                expected_authority_sha256=authority["authority_sha256"],
            )
        self.assertEqual(assessment["status"], "blocked")
        self.assertTrue(any(
            "project root changed" in blocker
            for blocker in assessment["blockers"]
        ))

    @unittest.skipUnless(os.name == "nt", "Windows handle semantics only")
    def test_windows_reparse_volume_and_duplicate_ids_are_fail_closed(self) -> None:
        for mutation, expected in (
            ("reparse", "reparse"),
            ("volume", "volume"),
            ("duplicate", "duplicate"),
            ("type", "directory"),
            ("delete", "delete-pending"),
        ):
            with self.subTest(mutation=mutation):
                authority = self.build()
                target = self.root / "validators"
                original_open = validator_authority._win_open_handle
                original_query = validator_authority._win_query_handle
                handle_paths: dict[int, Path] = {}
                root_identity: dict[str, object] = {}

                def tracking_open(
                    path: Path, *, directory: bool, read_data: bool = False,
                ) -> int:
                    handle = original_open(
                        path, directory=directory, read_data=read_data,
                    )
                    handle_paths[int(handle)] = Path(path)
                    return handle

                def mutating_query(handle: int) -> dict[str, object]:
                    info = original_query(handle)
                    path = handle_paths[int(handle)]
                    if path == self.root and not root_identity:
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
                        elif mutation == "duplicate":
                            info["file_id"] = root_identity["file_id"]
                        elif mutation == "type":
                            info["is_directory"] = False
                        else:
                            info["delete_pending"] = True
                    return info

                with (
                    mock.patch.object(
                        validator_authority, "_win_open_handle",
                        side_effect=tracking_open,
                    ),
                    mock.patch.object(
                        validator_authority, "_win_query_handle",
                        side_effect=mutating_query,
                    ),
                ):
                    assessment = assess_backend_runtime_cell_validator_authority(
                        authority, project_root=self.root,
                        expected_authority_sha256=authority["authority_sha256"],
                    )
                self.assertEqual(assessment["status"], "blocked")
                self.assertTrue(any(
                    expected in blocker.lower()
                    for blocker in assessment["blockers"]
                ))


if __name__ == "__main__":
    unittest.main()
