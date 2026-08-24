from __future__ import annotations

import copy
import ctypes
import hashlib
import inspect
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ctypes import wintypes


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import materialize_kpp_legacy_iss_v2 as materializer  # noqa: E402
from materialize_kpp_legacy_iss_v2 import (  # noqa: E402
    DATASET_ROOT,
    MATERIALIZATION_RECEIPT_NAME,
    MaterializationError,
    _TestAdapters,
    _materialize_kpp_legacy_iss_v2_impl,
    materialize_kpp_legacy_iss_v2,
)
from tests.test_kpp_dataset_contract import (  # noqa: E402
    _bundle,
    _canonical_bytes,
    _reseal_extraction,
    _reseal_metadata,
)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _set_windows_permissive_directory_dacl(path: Path) -> None:
    if os.name != "nt":
        raise AssertionError("Windows ACL mutation is unavailable")
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    convert = advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW
    convert.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(wintypes.DWORD),
    ]
    convert.restype = wintypes.BOOL
    set_file_security = advapi32.SetFileSecurityW
    set_file_security.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.c_void_p,
    ]
    set_file_security.restype = wintypes.BOOL
    local_free = kernel32.LocalFree
    local_free.argtypes = [ctypes.c_void_p]
    local_free.restype = ctypes.c_void_p

    descriptor = ctypes.c_void_p()
    descriptor_size = wintypes.DWORD()
    if not convert(
        "D:(A;OICI;GA;;;WD)",
        1,
        ctypes.byref(descriptor),
        ctypes.byref(descriptor_size),
    ):
        raise OSError(
            ctypes.get_last_error(),
            "could not construct permissive test DACL",
        )
    try:
        if not set_file_security(str(path), 0x00000004, descriptor):
            raise OSError(
                ctypes.get_last_error(),
                "could not install permissive test DACL",
            )
    finally:
        local_free(descriptor)


class MaterializeKppLegacyIssV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        bundle = _bundle()
        media_payloads = {
            ("avi", "underbody"): b"synthetic underbody AVI\n",
            ("avi", "front_gate"): b"synthetic front-gate AVI\n",
            ("h264", "underbody"): b"synthetic underbody H.264 MP4\n",
            ("h264", "front_gate"): b"synthetic front-gate H.264 MP4\n",
            ("h265", "underbody"): b"synthetic underbody H.265 MP4\n",
            ("h265", "front_gate"): b"synthetic front-gate H.265 MP4\n",
        }

        extraction_outputs = {
            str(item["role"]): item
            for item in bundle["extraction_receipt"]["outputs"]
        }
        for role in ("underbody", "front_gate"):
            payload = media_payloads[("avi", role)]
            extraction_outputs[role]["size_bytes"] = len(payload)
            extraction_outputs[role]["sha256"] = _sha256(payload)

        transcode_sources = {
            str(item["role"]): item
            for item in bundle["transcode_receipt"]["sources"]
        }
        for role in ("underbody", "front_gate"):
            output = extraction_outputs[role]
            transcode_sources[role].update(
                {
                    "path": output["path"],
                    "size_bytes": output["size_bytes"],
                    "sha256": output["sha256"],
                    "media": copy.deepcopy(output["media"]),
                }
            )

        transcode_outputs = {
            (str(item["codec_variant"]), str(item["role"])): item
            for item in bundle["transcode_receipt"]["outputs"]
        }
        for key, payload in media_payloads.items():
            if key[0] == "avi":
                continue
            transcode_outputs[key]["size_bytes"] = len(payload)
            transcode_outputs[key]["sha256"] = _sha256(payload)

        metadata = bundle["metadata_receipt"]
        underbody_avi = media_payloads[("avi", "underbody")]
        metadata["exported_avi"].update(
            {
                "size_bytes": len(underbody_avi),
                "sha256": _sha256(underbody_avi),
            }
        )

        _reseal_extraction(bundle)
        _reseal_metadata(bundle)
        cls.bundle = bundle
        cls.media_payloads = media_payloads
        cls.receipt_payloads = {
            name: _canonical_bytes(bundle[f"{name}_receipt"])
            for name in ("extraction", "transcode", "metadata")
        }

    def _write_fixture(self, root: Path) -> dict[str, object]:
        bundle = self.bundle
        receipt_paths: dict[str, Path] = {}
        pins: dict[str, str] = {}
        for name in ("extraction", "transcode", "metadata"):
            relative = Path(
                str(bundle[f"{name}_receipt_artifact"]["path"])
            )
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = self.receipt_payloads[name]
            path.write_bytes(payload)
            receipt_paths[name] = path
            pins[name] = _sha256(payload)

        for item in bundle["extraction_receipt"]["outputs"]:
            role = str(item["role"])
            path = root / str(item["path"])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(self.media_payloads[("avi", role)])
        for item in bundle["transcode_receipt"]["outputs"]:
            variant = str(item["codec_variant"])
            role = str(item["role"])
            path = root / str(item["path"])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(self.media_payloads[(variant, role)])
        return {"receipt_paths": receipt_paths, "pins": pins}

    def _materialize(
        self,
        root: Path,
        fixture: dict[str, object],
        *,
        adapters: _TestAdapters | None = None,
        pin_overrides: dict[str, str] | None = None,
    ) -> dict[str, object]:
        receipt_paths = fixture["receipt_paths"]
        pins = dict(fixture["pins"])
        pins.update(pin_overrides or {})
        return _materialize_kpp_legacy_iss_v2_impl(
            project_root=root,
            extraction_receipt=receipt_paths["extraction"],
            expected_extraction_receipt_sha256=pins["extraction"],
            transcode_receipt=receipt_paths["transcode"],
            expected_transcode_receipt_sha256=pins["transcode"],
            metadata_receipt=receipt_paths["metadata"],
            expected_metadata_receipt_sha256=pins["metadata"],
            test_adapters=adapters or _TestAdapters(),
        )

    def test_public_surface_has_only_three_receipts_and_their_external_pins(self) -> None:
        self.assertEqual(
            list(inspect.signature(materialize_kpp_legacy_iss_v2).parameters),
            [
                "project_root",
                "extraction_receipt",
                "expected_extraction_receipt_sha256",
                "transcode_receipt",
                "expected_transcode_receipt_sha256",
                "metadata_receipt",
                "expected_metadata_receipt_sha256",
            ],
        )
        parser = materializer._build_parser()
        destinations = {action.dest for action in parser._actions}
        self.assertNotIn("output", destinations)
        self.assertNotIn("media", destinations)

    def test_materializes_exact_fixed_tree_and_physically_assesses_entries(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            fixture = self._write_fixture(root)

            receipt = self._materialize(root, fixture)

            target = root / DATASET_ROOT
            expected_files = {
                "avi/iss_v2_underbody.avi",
                "avi/iss_v2_front_gate.avi",
                "h264/iss_v2_underbody.mp4",
                "h264/iss_v2_front_gate.mp4",
                "h265/iss_v2_underbody.mp4",
                "h265/iss_v2_front_gate.mp4",
                "metadata/iss_v2_underbody_metadata.json",
                "receipts/kpp_iss_v2_extraction_receipt.json",
                "receipts/kpp_iss_v2_transcode_receipt.json",
                MATERIALIZATION_RECEIPT_NAME,
            }
            observed_files = {
                path.relative_to(target).as_posix()
                for path in target.rglob("*")
                if path.is_file()
            }
            self.assertEqual(observed_files, expected_files)
            self.assertEqual(
                (target / "metadata/iss_v2_underbody_metadata.json").read_bytes(),
                self.receipt_payloads["metadata"],
            )
            self.assertEqual(
                (target / "receipts/kpp_iss_v2_extraction_receipt.json").read_bytes(),
                self.receipt_payloads["extraction"],
            )
            self.assertEqual(
                (target / "receipts/kpp_iss_v2_transcode_receipt.json").read_bytes(),
                self.receipt_payloads["transcode"],
            )
            self.assertEqual(receipt["status"], "physically_assessed_candidate")
            self.assertFalse(receipt["publishable"])
            self.assertFalse(receipt["publication_authorized"])
            self.assertEqual(len(receipt["installed_artifacts"]), 9)
            self.assertTrue(receipt["claims"]["authoritative_receipt_graph_validated"])
            self.assertTrue(receipt["claims"]["physical_artifact_bytes_assessed"])
            self.assertFalse(receipt["claims"]["publication_authorized"])
            for entry in receipt["dataset_entries"].values():
                self.assertEqual(entry["status"], "physically_assessed_candidate")
                self.assertFalse(entry["publishable"])
                self.assertTrue(
                    entry["provenance"]["physical_artifact_bytes_assessed"]
                )
                self.assertFalse(entry["provenance"]["publication_authorized"])
                for stream in entry["streams"]:
                    self.assertTrue(str(stream["path"]).startswith(DATASET_ROOT + "/"))

            installed_receipt = json.loads(
                (target / MATERIALIZATION_RECEIPT_NAME).read_text("ascii")
            )
            self.assertEqual(installed_receipt, receipt)

    def test_wrong_external_receipt_pin_fails_before_target_publication(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            fixture = self._write_fixture(root)

            with self.assertRaisesRegex(
                MaterializationError,
                "extraction receipt SHA-256 does not match its external pin",
            ):
                self._materialize(
                    root,
                    fixture,
                    pin_overrides={"extraction": "f" * 64},
                )

            self.assertFalse((root / DATASET_ROOT).exists())

    def test_media_sources_are_derived_from_receipts_and_reverified(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            fixture = self._write_fixture(root)
            source = root / str(
                self.bundle["transcode_receipt"]["outputs"][0]["path"]
            )
            source.write_bytes(b"mutated media")

            with self.assertRaisesRegex(
                MaterializationError,
                "SHA-256 does not match",
            ):
                self._materialize(root, fixture)

            self.assertFalse((root / DATASET_ROOT).exists())

    def test_candidate_tamper_is_detected_before_publication(self) -> None:
        tampered_candidate: Path | None = None

        def tamper(working: Path) -> None:
            nonlocal tampered_candidate
            tampered_candidate = working
            (working / "avi/iss_v2_underbody.avi").write_bytes(b"tampered")

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            fixture = self._write_fixture(root)
            with self.assertRaisesRegex(
                MaterializationError,
                "installed .* does not match",
            ):
                self._materialize(
                    root,
                    fixture,
                    adapters=_TestAdapters(after_copies=tamper),
                )

            self.assertIsNotNone(tampered_candidate)
            self.assertFalse((root / DATASET_ROOT).exists())
            self.assertFalse(tampered_candidate.exists())

    def test_candidate_rejects_hardlinked_receipt_with_identical_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            fixture = self._write_fixture(root)
            metadata_source = fixture["receipt_paths"]["metadata"]

            def hardlink_receipt(working: Path) -> None:
                installed = working / "metadata/iss_v2_underbody_metadata.json"
                installed.unlink()
                os.link(metadata_source, installed)

            with self.assertRaisesRegex(
                MaterializationError,
                "link count must remain exactly one",
            ):
                self._materialize(
                    root,
                    fixture,
                    adapters=_TestAdapters(after_copies=hardlink_receipt),
                )

            self.assertFalse((root / DATASET_ROOT).exists())

    def test_candidate_rejects_same_bytes_identity_swap_for_media_and_receipt(
        self,
    ) -> None:
        targets = (
            "avi/iss_v2_underbody.avi",
            "receipts/kpp_iss_v2_extraction_receipt.json",
        )
        for relative in targets:
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                fixture = self._write_fixture(root)

                def replace_with_same_bytes(working: Path) -> None:
                    installed = working / relative
                    payload = installed.read_bytes()
                    replacement = working / "same-bytes-replacement.tmp"
                    replacement.write_bytes(payload)
                    os.replace(replacement, installed)

                with self.assertRaisesRegex(
                    MaterializationError,
                    "identity changed after it was frozen",
                ):
                    self._materialize(
                        root,
                        fixture,
                        adapters=_TestAdapters(
                            after_copies=replace_with_same_bytes
                        ),
                    )

                self.assertFalse((root / DATASET_ROOT).exists())

    def test_candidate_rejects_same_bytes_generated_receipt_swap(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            fixture = self._write_fixture(root)

            def replace_generated_receipt(working: Path) -> None:
                installed = working / MATERIALIZATION_RECEIPT_NAME
                payload = installed.read_bytes()
                replacement = working / "same-bytes-replacement.tmp"
                replacement.write_bytes(payload)
                os.replace(replacement, installed)

            with self.assertRaisesRegex(
                MaterializationError,
                "identity changed after it was frozen",
            ):
                self._materialize(
                    root,
                    fixture,
                    adapters=_TestAdapters(
                        after_receipt=replace_generated_receipt
                    ),
                )

            self.assertFalse((root / DATASET_ROOT).exists())

    def test_post_rename_same_bytes_swap_fails_without_deleting_target(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            fixture = self._write_fixture(root)
            real_publish = materializer._atomic_publish_directory

            def publish_then_replace(source: Path, target: Path) -> None:
                real_publish(source, target)
                installed = target / "avi/iss_v2_underbody.avi"
                payload = installed.read_bytes()
                replacement = target / "same-bytes-replacement.tmp"
                replacement.write_bytes(payload)
                os.replace(replacement, installed)

            with (
                mock.patch.object(
                    materializer,
                    "_atomic_publish_directory",
                    side_effect=publish_then_replace,
                ),
                self.assertRaisesRegex(
                    MaterializationError,
                    "identity changed after it was frozen",
                ),
            ):
                self._materialize(root, fixture)

            target = root / DATASET_ROOT
            self.assertTrue(target.is_dir())
            self.assertEqual(
                (target / "avi/iss_v2_underbody.avi").read_bytes(),
                self.media_payloads[("avi", "underbody")],
            )

    def test_existing_target_is_never_replaced_or_modified(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            fixture = self._write_fixture(root)
            target = root / DATASET_ROOT
            target.mkdir(parents=True)
            marker = target / "owner-marker.txt"
            marker.write_bytes(b"pre-existing")

            with self.assertRaisesRegex(
                MaterializationError,
                "existing materialization",
            ):
                self._materialize(root, fixture)

            self.assertEqual(marker.read_bytes(), b"pre-existing")
            self.assertEqual({path.name for path in target.iterdir()}, {marker.name})

    def test_exact_rerun_is_read_only_and_returns_existing_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            fixture = self._write_fixture(root)
            first = self._materialize(root, fixture)
            target = root / DATASET_ROOT
            before = {
                path.relative_to(target).as_posix(): (
                    path.stat().st_dev,
                    path.stat().st_ino,
                    path.stat().st_nlink,
                    path.stat().st_mtime_ns,
                    _sha256(path.read_bytes()),
                )
                for path in target.rglob("*")
                if path.is_file()
            }
            kpp_children_before = {
                path.name for path in target.parent.iterdir()
            }

            second = self._materialize(root, fixture)

            after = {
                path.relative_to(target).as_posix(): (
                    path.stat().st_dev,
                    path.stat().st_ino,
                    path.stat().st_nlink,
                    path.stat().st_mtime_ns,
                    _sha256(path.read_bytes()),
                )
                for path in target.rglob("*")
                if path.is_file()
            }
            self.assertEqual(second, first)
            self.assertEqual(after, before)
            self.assertEqual(
                {path.name for path in target.parent.iterdir()},
                kpp_children_before,
            )

    def test_exact_rerun_uses_receipt_hashes_not_staging_media_availability(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            fixture = self._write_fixture(root)
            first = self._materialize(root, fixture)
            for item in self.bundle["extraction_receipt"]["outputs"]:
                (root / str(item["path"])).unlink()
            for item in self.bundle["transcode_receipt"]["outputs"]:
                (root / str(item["path"])).unlink()

            second = self._materialize(root, fixture)

            self.assertEqual(second, first)

    def test_drifted_existing_target_fails_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            fixture = self._write_fixture(root)
            self._materialize(root, fixture)
            target = root / DATASET_ROOT
            drifted = target / "avi/iss_v2_underbody.avi"
            drifted.write_bytes(b"hostile drift")
            before = {
                path.relative_to(target).as_posix(): path.read_bytes()
                for path in target.rglob("*")
                if path.is_file()
            }

            with self.assertRaisesRegex(
                MaterializationError,
                "existing materialization .* does not match",
            ):
                self._materialize(root, fixture)

            after = {
                path.relative_to(target).as_posix(): path.read_bytes()
                for path in target.rglob("*")
                if path.is_file()
            }
            self.assertEqual(after, before)

    def test_hardlinked_existing_target_fails_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            fixture = self._write_fixture(root)
            self._materialize(root, fixture)
            target = root / DATASET_ROOT
            installed = target / "metadata/iss_v2_underbody_metadata.json"
            source = fixture["receipt_paths"]["metadata"]
            installed.unlink()
            os.link(source, installed)
            before_nlink = installed.stat().st_nlink

            with self.assertRaisesRegex(
                MaterializationError,
                "link count must remain exactly one",
            ):
                self._materialize(root, fixture)

            self.assertEqual(installed.stat().st_nlink, before_nlink)
            self.assertEqual(installed.read_bytes(), source.read_bytes())

    @unittest.skipUnless(os.name == "nt", "Windows custody route only")
    def test_windows_route_bootstraps_and_holds_full_destination_custody(self) -> None:
        opened: list[object] = []
        created: list[object] = []
        publications: list[str] = []
        real_open = materializer._open_windows_directory_custody
        real_create = materializer._create_windows_private_working_directory_with_custody
        real_publish = materializer._windows_publish_directory_by_handle

        def recording_open(
            path: Path, *, label: str, require_delete_access: bool
        ) -> object:
            custody = real_open(
                path,
                label=label,
                require_delete_access=require_delete_access,
            )
            opened.append(custody)
            return custody

        def recording_create(
            *, parent: object, prefix: str, suffix: str, label: str
        ) -> tuple[Path, object]:
            path, custody = real_create(
                parent=parent,
                prefix=prefix,
                suffix=suffix,
                label=label,
            )
            created.append(custody)
            return path, custody

        def recording_publish(
            *, source: object, parent: object, target_name: str
        ) -> None:
            publications.append(target_name)
            real_publish(source=source, parent=parent, target_name=target_name)

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            fixture = self._write_fixture(root)
            paths = fixture["receipt_paths"]
            pins = fixture["pins"]
            with (
                mock.patch.object(
                    materializer,
                    "_open_windows_directory_custody",
                    side_effect=recording_open,
                ),
                mock.patch.object(
                    materializer,
                    "_create_windows_private_working_directory_with_custody",
                    side_effect=recording_create,
                ),
                mock.patch.object(
                    materializer,
                    "_windows_publish_directory_by_handle",
                    side_effect=recording_publish,
                ),
            ):
                materialize_kpp_legacy_iss_v2(
                    project_root=root,
                    extraction_receipt=paths["extraction"],
                    expected_extraction_receipt_sha256=pins["extraction"],
                    transcode_receipt=paths["transcode"],
                    expected_transcode_receipt_sha256=pins["transcode"],
                    metadata_receipt=paths["metadata"],
                    expected_metadata_receipt_sha256=pins["metadata"],
                )

            self.assertEqual(
                publications,
                ["data", "videos", "kpp", "kpp_legacy_iss_v2"],
            )
            self.assertEqual(
                [custody.label for custody in created],
                [
                    "materialization data directory",
                    "materialization videos directory",
                    "materialization kpp directory",
                    "materialization working directory",
                ],
            )
            self.assertTrue(
                all(custody._handle is None for custody in [*opened, *created])
            )

    @unittest.skipUnless(os.name == "nt", "Windows custody route only")
    def test_windows_exact_rerun_holds_target_custody_without_creating(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            fixture = self._write_fixture(root)
            paths = fixture["receipt_paths"]
            pins = fixture["pins"]
            arguments = dict(
                project_root=root,
                extraction_receipt=paths["extraction"],
                expected_extraction_receipt_sha256=pins["extraction"],
                transcode_receipt=paths["transcode"],
                expected_transcode_receipt_sha256=pins["transcode"],
                metadata_receipt=paths["metadata"],
                expected_metadata_receipt_sha256=pins["metadata"],
            )
            first = materialize_kpp_legacy_iss_v2(**arguments)
            opened_labels: list[str] = []
            real_open = materializer._open_windows_directory_custody

            def recording_open(
                path: Path, *, label: str, require_delete_access: bool
            ) -> object:
                custody = real_open(
                    path,
                    label=label,
                    require_delete_access=require_delete_access,
                )
                opened_labels.append(label)
                return custody

            with (
                mock.patch.object(
                    materializer,
                    "_open_windows_directory_custody",
                    side_effect=recording_open,
                ),
                mock.patch.object(
                    materializer,
                    "_create_windows_private_working_directory_with_custody",
                    side_effect=AssertionError(
                        "exact rerun must not create any directory"
                    ),
                ),
                mock.patch.object(
                    materializer,
                    "_windows_publish_directory_by_handle",
                    side_effect=AssertionError(
                        "exact rerun must not publish any directory"
                    ),
                ),
            ):
                second = materialize_kpp_legacy_iss_v2(**arguments)

            self.assertEqual(second, first)
            self.assertEqual(
                opened_labels,
                [
                    "materialization project root",
                    "materialization data directory",
                    "materialization videos directory",
                    "materialization kpp directory",
                    "existing materialization directory",
                ],
            )

    @unittest.skipUnless(os.name == "nt", "Windows ACL route only")
    def test_windows_rerun_rejects_permissive_target_acl_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            fixture = self._write_fixture(root)
            paths = fixture["receipt_paths"]
            pins = fixture["pins"]
            arguments = dict(
                project_root=root,
                extraction_receipt=paths["extraction"],
                expected_extraction_receipt_sha256=pins["extraction"],
                transcode_receipt=paths["transcode"],
                expected_transcode_receipt_sha256=pins["transcode"],
                metadata_receipt=paths["metadata"],
                expected_metadata_receipt_sha256=pins["metadata"],
            )
            materialize_kpp_legacy_iss_v2(**arguments)
            target = root / DATASET_ROOT
            self.assertTrue(
                materializer._windows_private_directory_acl_is_exact(target)
            )
            _set_windows_permissive_directory_dacl(target)
            self.assertFalse(
                materializer._windows_private_directory_acl_is_exact(target)
            )
            before = {
                path.relative_to(target).as_posix(): (
                    path.stat().st_dev,
                    path.stat().st_ino,
                    path.stat().st_nlink,
                    path.stat().st_size,
                    path.stat().st_mtime_ns,
                    _sha256(path.read_bytes()),
                )
                for path in target.rglob("*")
                if path.is_file()
            }

            with (
                mock.patch.object(
                    materializer,
                    "_create_windows_private_working_directory_with_custody",
                    side_effect=AssertionError(
                        "ACL-drift rerun must not create a directory"
                    ),
                ),
                mock.patch.object(
                    materializer,
                    "_windows_publish_directory_by_handle",
                    side_effect=AssertionError(
                        "ACL-drift rerun must not publish a directory"
                    ),
                ),
                self.assertRaisesRegex(
                    MaterializationError,
                    "existing materialization target ACL is not private-exact",
                ),
            ):
                materialize_kpp_legacy_iss_v2(**arguments)

            after = {
                path.relative_to(target).as_posix(): (
                    path.stat().st_dev,
                    path.stat().st_ino,
                    path.stat().st_nlink,
                    path.stat().st_size,
                    path.stat().st_mtime_ns,
                    _sha256(path.read_bytes()),
                )
                for path in target.rglob("*")
                if path.is_file()
            }
            self.assertEqual(after, before)
            self.assertFalse(
                materializer._windows_private_directory_acl_is_exact(target)
            )

    @unittest.skipUnless(os.name == "nt", "Windows ACL route only")
    def test_windows_rerun_rechecks_target_acl_after_long_verification(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            fixture = self._write_fixture(root)
            paths = fixture["receipt_paths"]
            pins = fixture["pins"]
            arguments = dict(
                project_root=root,
                extraction_receipt=paths["extraction"],
                expected_extraction_receipt_sha256=pins["extraction"],
                transcode_receipt=paths["transcode"],
                expected_transcode_receipt_sha256=pins["transcode"],
                metadata_receipt=paths["metadata"],
                expected_metadata_receipt_sha256=pins["metadata"],
            )
            materialize_kpp_legacy_iss_v2(**arguments)
            target = root / DATASET_ROOT
            real_validate = materializer._validate_existing_materialization

            def validate_then_drift(*args: object, **kwargs: object) -> dict[str, object]:
                result = real_validate(*args, **kwargs)
                _set_windows_permissive_directory_dacl(target)
                return result

            with (
                mock.patch.object(
                    materializer,
                    "_validate_existing_materialization",
                    side_effect=validate_then_drift,
                ),
                self.assertRaisesRegex(
                    MaterializationError,
                    "target ACL changed during verification",
                ),
            ):
                materialize_kpp_legacy_iss_v2(**arguments)

            self.assertFalse(
                materializer._windows_private_directory_acl_is_exact(target)
            )

    @unittest.skipUnless(os.name == "nt", "Windows NtCreateFile route only")
    def test_windows_bootstrap_never_path_creates_a_destination_component(self) -> None:
        source = inspect.getsource(materializer._bootstrap_windows_dataset_parent)
        self.assertIn("_create_windows_private_working_directory_with_custody", source)
        self.assertIn("_windows_publish_directory_by_handle", source)
        self.assertIn("_validate_windows_direct_child_custody", source)
        self.assertNotIn(".mkdir(", source)

    @unittest.skipUnless(os.name == "nt", "Windows custody route only")
    def test_windows_bootstrap_failure_closes_every_locally_acquired_handle(self) -> None:
        created: list[object] = []
        real_create = materializer._create_windows_private_working_directory_with_custody

        def recording_create(
            *, parent: object, prefix: str, suffix: str, label: str
        ) -> tuple[Path, object]:
            path, custody = real_create(
                parent=parent,
                prefix=prefix,
                suffix=suffix,
                label=label,
            )
            created.append(custody)
            return path, custody

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            fixture = self._write_fixture(root)
            paths = fixture["receipt_paths"]
            pins = fixture["pins"]
            try:
                with (
                    mock.patch.object(
                        materializer,
                        "_create_windows_private_working_directory_with_custody",
                        side_effect=recording_create,
                    ),
                    mock.patch.object(
                        materializer,
                        "_windows_publish_directory_by_handle",
                        side_effect=materializer.ExtractionError(
                            "forced bootstrap publication failure"
                        ),
                    ),
                    self.assertRaisesRegex(
                        MaterializationError,
                        "forced bootstrap publication failure",
                    ),
                ):
                    materialize_kpp_legacy_iss_v2(
                        project_root=root,
                        extraction_receipt=paths["extraction"],
                        expected_extraction_receipt_sha256=pins["extraction"],
                        transcode_receipt=paths["transcode"],
                        expected_transcode_receipt_sha256=pins["transcode"],
                        metadata_receipt=paths["metadata"],
                        expected_metadata_receipt_sha256=pins["metadata"],
                    )
                self.assertTrue(created)
                self.assertTrue(all(custody._handle is None for custody in created))
                self.assertEqual(
                    list(root.rglob("*.bootstrap-candidate")),
                    [],
                )
            finally:
                # RED cleanup only: a broken implementation leaves the handle open.
                for custody in created:
                    if custody._handle is not None:
                        custody.close()

    @unittest.skipUnless(os.name == "nt", "Windows custody route only")
    def test_each_unpublished_bootstrap_failure_leaves_no_random_orphan(self) -> None:
        for fail_at in (1, 2, 3):
            with self.subTest(fail_at=fail_at), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                fixture = self._write_fixture(root)
                paths = fixture["receipt_paths"]
                pins = fixture["pins"]
                real_publish = materializer._windows_publish_directory_by_handle
                call_count = 0

                def fail_selected_publish(
                    *, source: object, parent: object, target_name: str
                ) -> None:
                    nonlocal call_count
                    call_count += 1
                    if call_count == fail_at:
                        raise materializer.ExtractionError(
                            f"forced bootstrap failure {fail_at}"
                        )
                    real_publish(
                        source=source,
                        parent=parent,
                        target_name=target_name,
                    )

                with (
                    mock.patch.object(
                        materializer,
                        "_windows_publish_directory_by_handle",
                        side_effect=fail_selected_publish,
                    ),
                    self.assertRaisesRegex(
                        MaterializationError,
                        f"forced bootstrap failure {fail_at}",
                    ),
                ):
                    materialize_kpp_legacy_iss_v2(
                        project_root=root,
                        extraction_receipt=paths["extraction"],
                        expected_extraction_receipt_sha256=pins["extraction"],
                        transcode_receipt=paths["transcode"],
                        expected_transcode_receipt_sha256=pins["transcode"],
                        metadata_receipt=paths["metadata"],
                        expected_metadata_receipt_sha256=pins["metadata"],
                    )

                self.assertEqual(
                    list(root.rglob("*.bootstrap-candidate")),
                    [],
                )
                expected_fixed = ["data", "videos", "kpp"][: fail_at - 1]
                current = root
                observed_fixed: list[str] = []
                for component in ("data", "videos", "kpp"):
                    current = current / component
                    if current.is_dir():
                        observed_fixed.append(component)
                    else:
                        break
                self.assertEqual(observed_fixed, expected_fixed)
                self.assertFalse((root / DATASET_ROOT).exists())


if __name__ == "__main__":
    unittest.main()
