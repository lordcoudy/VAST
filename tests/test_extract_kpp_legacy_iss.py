from __future__ import annotations

import hashlib
import inspect
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import extract_kpp_legacy_iss as extractor  # noqa: E402
from extract_kpp_legacy_iss import (  # noqa: E402
    ExtractionError,
    _extract_pair_with_test_adapters,
    build_ffmpeg_command,
    detect_payload_offset,
    extract_pair,
    main,
)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _make_tools(root: Path) -> tuple[Path, Path, dict[str, bytes]]:
    ffmpeg = root / "ffmpeg.exe"
    ffprobe = root / "ffprobe.exe"
    ffmpeg.write_bytes(b"pinned-ffmpeg-binary")
    ffprobe.write_bytes(b"pinned-ffprobe-binary")
    versions = {
        ffmpeg.name: b"ffmpeg version pinned\n",
        ffprobe.name: b"ffprobe version pinned\n",
    }
    return ffmpeg, ffprobe, versions


def _tool_arguments(root: Path) -> dict[str, object]:
    ffmpeg, ffprobe, versions = _make_tools(root)
    return {
        "ffmpeg": ffmpeg,
        "expected_ffmpeg_sha256": _sha256(ffmpeg.read_bytes()),
        "expected_ffmpeg_version_sha256": _sha256(versions[ffmpeg.name]),
        "ffprobe": ffprobe,
        "expected_ffprobe_sha256": _sha256(ffprobe.read_bytes()),
        "expected_ffprobe_version_sha256": _sha256(versions[ffprobe.name]),
        "version_reader": lambda tool: versions[tool.name],
    }


class ExtractKppLegacyIssTests(unittest.TestCase):
    def test_public_wrapper_selects_authoritative_adapters_internally(self) -> None:
        values = {
            "project_root": Path("project"),
            "underbody_archive": Path("underbody.iss"),
            "front_archive": Path("front.iss"),
            "output_dir": Path("staging/candidate"),
            "expected_underbody_sha256": "1" * 64,
            "expected_front_sha256": "2" * 64,
            "ffmpeg": Path("ffmpeg.exe"),
            "expected_ffmpeg_sha256": "3" * 64,
            "expected_ffmpeg_version_sha256": "4" * 64,
            "ffprobe": Path("ffprobe.exe"),
            "expected_ffprobe_sha256": "5" * 64,
            "expected_ffprobe_version_sha256": "6" * 64,
        }
        with mock.patch.object(
            extractor,
            "_extract_pair_impl",
            autospec=True,
            return_value={"status": "captured"},
        ) as implementation:
            self.assertEqual(extract_pair(**values), {"status": "captured"})

        implementation.assert_called_once_with(**values, test_adapters=None)

    def test_private_directory_is_created_privately_without_recursive_acl_tool(self) -> None:
        source = (SCRIPTS / "extract_kpp_legacy_iss.py").read_text(encoding="utf-8")
        self.assertIn("_create_private_working_directory", source)
        self.assertIn("OpenThreadToken", source)
        self.assertIn("OpenProcessToken", source)
        self.assertIn('f"O:{user_sid}D:P"', source)
        self.assertNotIn("icacls", source.casefold())
        self.assertNotIn('"/reset"', source)
        self.assertNotIn("candidate.mkdir()", source)

        with tempfile.TemporaryDirectory() as raw:
            parent = Path(raw)
            working = extractor._create_private_working_directory(
                parent=parent,
                prefix=".acl-test.",
                suffix=".candidate",
            )
            try:
                self.assertEqual(working.parent, parent)
                self.assertTrue(working.is_dir())
                self.assertFalse(extractor._is_reparse_or_symlink(working))
                if os.name == "nt":
                    self.assertTrue(extractor._windows_private_directory_acl_is_exact(working))
                else:
                    self.assertEqual(stat.S_IMODE(working.stat().st_mode), 0o700)
            finally:
                working.rmdir()

    @unittest.skipUnless(os.name == "nt", "Windows atomic private create only")
    def test_windows_private_create_returns_custody_without_create_open_gap(self) -> None:
        helper_source = inspect.getsource(
            extractor._create_windows_private_working_directory_with_custody
        )
        self.assertIn("NtCreateFile", helper_source)
        self.assertIn("RootDirectory", helper_source)
        self.assertIn("FILE_CREATE", helper_source)
        self.assertIn("FILE_DIRECTORY_FILE", helper_source)
        self.assertIn("FILE_OPEN_REPARSE_POINT", helper_source)
        self.assertNotIn("_open_windows_directory_custody", helper_source)

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            staging = root / "staging"
            staging.mkdir()
            parent_custody = extractor._open_windows_directory_custody(
                staging,
                label="atomic-create staging parent",
                require_delete_access=False,
            )
            working_custody = None
            working = staging / "not-created"
            try:
                with mock.patch.object(
                    extractor.secrets,
                    "token_hex",
                    return_value="a" * 32,
                ), mock.patch.object(
                    extractor,
                    "_open_windows_directory_custody",
                    side_effect=AssertionError("created directory must not be reopened"),
                ):
                    working, working_custody = (
                        extractor._create_windows_private_working_directory_with_custody(
                            parent=parent_custody,
                            prefix=".atomic.",
                            suffix=".candidate",
                            label="atomic working directory",
                        )
                    )
                self.assertEqual(working.name, f".atomic.{'a' * 32}.candidate")
                extractor._validate_windows_direct_child_custody(
                    parent=parent_custody,
                    child=working_custody,
                    expected_name=working.name,
                )
                self.assertTrue(
                    extractor._windows_private_directory_acl_is_exact(working)
                )
                with self.assertRaises(OSError):
                    os.rename(working, staging / "moved-working")
            finally:
                if working_custody is not None:
                    working_custody.close()
                if working.exists():
                    working.rmdir()
                parent_custody.close()

    @unittest.skipUnless(os.name == "nt", "Windows exact-handle rollback only")
    def test_windows_private_create_rolls_back_every_post_create_validation_failure(
        self,
    ) -> None:
        disposition_source = inspect.getsource(
            extractor._mark_windows_directory_delete_pending_by_handle
        )
        allocator_source = inspect.getsource(
            extractor._create_windows_private_working_directory_with_custody
        )
        self.assertIn("SetFileInformationByHandle", disposition_source)
        self.assertIn("FileDispositionInfo", disposition_source)
        self.assertIn(
            "_mark_windows_directory_delete_pending_by_handle", allocator_source
        )
        self.assertNotIn("unlink", disposition_source)
        self.assertNotIn("rmdir", disposition_source)
        self.assertNotIn("RemoveDirectory", disposition_source)

        prefix_patterns = (
            (".atomic.", ".candidate"),
            (".data.", ".bootstrap-candidate"),
        )
        validation_seams = (
            "identity",
            "final_path",
            "direct_child",
            "acl",
        )
        real_information = extractor._windows_directory_information
        real_final_path = extractor._windows_directory_final_path

        for prefix, suffix in prefix_patterns:
            for seam in validation_seams:
                with self.subTest(prefix=prefix, suffix=suffix, seam=seam):
                    with tempfile.TemporaryDirectory() as raw:
                        root = Path(raw)
                        staging = root / "staging"
                        staging.mkdir()
                        parent_custody = extractor._open_windows_directory_custody(
                            staging,
                            label="rollback staging parent",
                            require_delete_access=False,
                        )

                        def information(
                            handle: int, *, label: str
                        ) -> tuple[int, int]:
                            if seam == "identity" and handle != parent_custody.handle:
                                raise ExtractionError("injected identity validation failure")
                            return real_information(handle, label=label)

                        def final_path(handle: int, *, label: str) -> str:
                            if seam == "final_path" and handle != parent_custody.handle:
                                raise ExtractionError("injected final-path validation failure")
                            return real_final_path(handle, label=label)

                        direct_child = (
                            mock.patch.object(
                                extractor,
                                "_validate_windows_direct_child_custody",
                                side_effect=ExtractionError(
                                    "injected direct-child validation failure"
                                ),
                            )
                            if seam == "direct_child"
                            else mock.patch.object(
                                extractor,
                                "_validate_windows_direct_child_custody",
                                wraps=extractor._validate_windows_direct_child_custody,
                            )
                        )
                        acl = (
                            mock.patch.object(
                                extractor,
                                "_windows_private_directory_acl_is_exact",
                                side_effect=ExtractionError(
                                    "injected ACL validation failure"
                                ),
                            )
                            if seam == "acl"
                            else mock.patch.object(
                                extractor,
                                "_windows_private_directory_acl_is_exact",
                                wraps=extractor._windows_private_directory_acl_is_exact,
                            )
                        )
                        try:
                            with mock.patch.object(
                                extractor.secrets,
                                "token_hex",
                                return_value="b" * 32,
                            ), mock.patch.object(
                                extractor,
                                "_windows_directory_information",
                                side_effect=information,
                            ), mock.patch.object(
                                extractor,
                                "_windows_directory_final_path",
                                side_effect=final_path,
                            ), direct_child, acl, self.assertRaisesRegex(
                                ExtractionError,
                                "injected",
                            ):
                                extractor._create_windows_private_working_directory_with_custody(
                                    parent=parent_custody,
                                    prefix=prefix,
                                    suffix=suffix,
                                    label="rollback working directory",
                                )
                        finally:
                            parent_custody.close()

                        self.assertEqual(
                            list(staging.glob(f"{prefix}*{suffix}")),
                            [],
                        )

    @unittest.skipUnless(os.name == "nt", "Windows rollback fail-safe only")
    def test_windows_private_create_retains_explicitly_when_disposition_fails(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            staging = root / "staging"
            staging.mkdir()
            parent_custody = extractor._open_windows_directory_custody(
                staging,
                label="retention staging parent",
                require_delete_access=False,
            )
            candidate = staging / f".retained.{'c' * 32}.candidate"
            disposition = mock.Mock(
                side_effect=ExtractionError("injected FileDispositionInfo failure")
            )
            try:
                with mock.patch.object(
                    extractor.secrets,
                    "token_hex",
                    return_value="c" * 32,
                ), mock.patch.object(
                    extractor,
                    "_validate_windows_direct_child_custody",
                    side_effect=ExtractionError(
                        "injected post-create validation failure"
                    ),
                ), mock.patch.object(
                    extractor,
                    "_mark_windows_directory_delete_pending_by_handle",
                    disposition,
                ), self.assertRaisesRegex(ExtractionError, "retained"):
                    extractor._create_windows_private_working_directory_with_custody(
                        parent=parent_custody,
                        prefix=".retained.",
                        suffix=".candidate",
                        label="retained working directory",
                    )

                disposition.assert_called_once()
                self.assertTrue(candidate.is_dir())
                self.assertTrue(
                    extractor._windows_private_directory_acl_is_exact(candidate)
                )
                candidate.rmdir()
            finally:
                parent_custody.close()

    @unittest.skipUnless(os.name == "nt", "Windows directory-handle custody only")
    def test_windows_directory_handles_hold_custody_and_publish_no_replace(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            root_custody = extractor._open_windows_directory_custody(
                root,
                label="project root",
                require_delete_access=False,
            )
            staging = root / "staging"
            staging.mkdir()
            working = extractor._create_private_working_directory(
                parent=staging,
                prefix=".candidate.",
                suffix=".work",
            )
            (working / "artifact.bin").write_bytes(b"complete")

            parent_custody = extractor._open_windows_directory_custody(
                staging,
                label="staging parent",
                require_delete_access=False,
            )
            working_custody = extractor._open_windows_directory_custody(
                working,
                label="working directory",
                require_delete_access=True,
            )
            try:
                extractor._validate_windows_direct_child_custody(
                    parent=root_custody,
                    child=parent_custody,
                    expected_name=staging.name,
                )
                extractor._validate_windows_direct_child_custody(
                    parent=parent_custody,
                    child=working_custody,
                    expected_name=working.name,
                )
                with self.assertRaises(OSError):
                    os.rename(root, root.with_name(root.name + "-moved"))
                with self.assertRaises(OSError):
                    os.rename(staging, root / "moved-staging")
                with self.assertRaises(OSError):
                    os.rename(working, staging / "moved-working")

                published = staging / "published"
                extractor._windows_publish_directory_by_handle(
                    source=working_custody,
                    parent=parent_custody,
                    target_name=published.name,
                )
                extractor._validate_windows_direct_child_custody(
                    parent=parent_custody,
                    child=working_custody,
                    expected_name=published.name,
                )
                extractor._validate_windows_direct_child_custody(
                    parent=root_custody,
                    child=parent_custody,
                    expected_name=staging.name,
                )
                self.assertEqual((published / "artifact.bin").read_bytes(), b"complete")

                collision = extractor._create_private_working_directory(
                    parent=staging,
                    prefix=".collision.",
                    suffix=".work",
                )
                collision_custody = extractor._open_windows_directory_custody(
                    collision,
                    label="collision directory",
                    require_delete_access=True,
                )
                try:
                    with self.assertRaisesRegex(ExtractionError, "already exists"):
                        extractor._windows_publish_directory_by_handle(
                            source=collision_custody,
                            parent=parent_custody,
                            target_name=published.name,
                        )
                    self.assertTrue(collision.is_dir())
                finally:
                    collision_custody.close()
                    collision.rmdir()
            finally:
                working_custody.close()
                parent_custody.close()
                root_custody.close()

    @unittest.skipUnless(os.name == "nt", "Windows reparse-point rejection only")
    def test_windows_custody_rejects_directory_link_swap_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            real = root / "real"
            real.mkdir()
            linked = root / "linked"
            try:
                os.symlink(real, linked, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"directory symlinks unavailable: {exc}")
            with self.assertRaisesRegex(ExtractionError, "plain existing directory"):
                extractor._open_windows_directory_custody(
                    linked,
                    label="swap candidate",
                    require_delete_access=False,
                )

    def test_authoritative_mode_is_windows_only_and_target_is_direct_staging_child(self) -> None:
        source = inspect.getsource(extractor._extract_pair_impl)
        publication_source = inspect.getsource(
            extractor._windows_publish_directory_by_handle
        )
        self.assertIn("_windows_publish_directory_by_handle", source)
        self.assertIn("authoritative extraction requires Windows", source)
        self.assertRegex(
            source,
            r"if authoritative:\s+[\s\S]*?_windows_publish_directory_by_handle\([\s\S]*?"
            r"\s+else:\s+_atomic_publish_directory\(",
        )
        self.assertIn("SetFileInformationByHandle", publication_source)
        self.assertIn("ReplaceIfExists = False", publication_source)
        self.assertIn(
            "_windows_directory_final_path(parent.handle", publication_source
        )
        self.assertNotIn("MoveFileEx", publication_source)
        self.assertLess(
            source.index("root_custody = _open_windows_directory_custody"),
            source.index("destination.parent.mkdir"),
        )
        self.assertIn(
            "windows_project_root_staging_and_working_directory_handle_custody_validated",
            source,
        )
        native_create = source.index(
            "working, working_custody = "
            "_create_windows_private_working_directory_with_custody"
        )
        exact_acl = source.index(
            "_windows_private_directory_acl_is_exact(working)", native_create
        )
        custody_validation = source.index(
            "_validate_windows_direct_child_custody(", native_create
        )
        snapshots = source.index('snapshot_dir = working / ".sources"')
        self.assertLess(native_create, custody_validation)
        self.assertLess(custody_validation, exact_acl)
        self.assertLess(exact_acl, snapshots)
        self.assertRegex(
            source,
            r"if authoritative:\s+[\s\S]*?"
            r"_create_windows_private_working_directory_with_custody\("
            r"[\s\S]*?else:\s+[\s\S]*?_create_private_working_directory\(",
        )

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            nested = root / "staging" / "outer" / "candidate"
            with self.assertRaisesRegex(ExtractionError, "direct child"):
                extractor._validated_output_dir(root, nested)

        if os.name != "nt":
            with self.assertRaisesRegex(ExtractionError, "requires Windows"):
                extract_pair(
                    project_root=Path("project"),
                    underbody_archive=Path("underbody.iss"),
                    front_archive=Path("front.iss"),
                    output_dir=Path("staging/candidate"),
                    expected_underbody_sha256="1" * 64,
                    expected_front_sha256="2" * 64,
                    ffmpeg=Path("ffmpeg"),
                    expected_ffmpeg_sha256="3" * 64,
                    expected_ffmpeg_version_sha256="4" * 64,
                    ffprobe=Path("ffprobe"),
                    expected_ffprobe_sha256="5" * 64,
                    expected_ffprobe_version_sha256="6" * 64,
                )

    def test_authoritative_api_has_no_dependency_injection(self) -> None:
        parameters = inspect.signature(extract_pair).parameters
        self.assertNotIn("runner", parameters)
        self.assertNotIn("prober", parameters)
        self.assertNotIn("version_reader", parameters)
        main_parameters = inspect.signature(main).parameters
        self.assertEqual(list(main_parameters), ["argv"])

    def test_detects_payload_offsets_and_builds_exact_commands(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            underbody = root / "13._03"
            front = root / "13._03_2"
            underbody.write_bytes(b"ISS-header" + b"\xff\xd8\xff\xe0jpeg\xff\xd9")
            front.write_bytes(b"ISS-header" + b"\x00\x00\x00\x01\x67h264")

            self.assertEqual(detect_payload_offset(underbody, "mjpeg"), 10)
            self.assertEqual(detect_payload_offset(front, "h264"), 10)

            underbody_command = build_ffmpeg_command(
                source=underbody,
                target=root / "underbody.avi",
                role="underbody",
                payload_offset=10,
                ffmpeg="ffmpeg-fixed",
            )
            self.assertEqual(
                underbody_command,
                (
                    "ffmpeg-fixed",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-nostdin",
                    "-r",
                    "200",
                    "-f",
                    "mjpeg",
                    "-skip_initial_bytes",
                    "10",
                    "-i",
                    str(underbody),
                    "-map",
                    "0:v:0",
                    "-c:v",
                    "copy",
                    "-f",
                    "avi",
                    str(root / "underbody.avi"),
                ),
            )
            front_command = build_ffmpeg_command(
                source=front,
                target=root / "front.avi",
                role="front_gate",
                payload_offset=10,
                ffmpeg="ffmpeg-fixed",
            )
            self.assertEqual(front_command[6:10], ("25", "-f", "h264", "-skip_initial_bytes"))

    def test_extracts_pair_atomically_and_emits_canonical_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            staging = root / "staging" / "candidate"
            underbody_payload = b"prefix" + b"\xff\xd8\xff\xe0jpeg\xff\xd9"
            front_payload = b"prefix" + b"\x00\x00\x00\x01\x67h264"
            underbody = root / "underbody.iss"
            front = root / "front.iss"
            underbody.write_bytes(underbody_payload)
            front.write_bytes(front_payload)
            calls: list[tuple[str, ...]] = []

            def runner(command: tuple[str, ...]) -> None:
                calls.append(command)
                target = Path(command[-1])
                target.write_bytes(
                    b"underbody-avi" if "mjpeg" in command else b"front-avi"
                )

            def probe(path: Path) -> dict[str, object]:
                if path.name.startswith("iss_v2_underbody"):
                    return {
                        "codec_name": "mjpeg",
                        "width": 1700,
                        "height": 236,
                        "r_frame_rate": "200/1",
                        "avg_frame_rate": "200/1",
                        "frame_count": 11882,
                        "duration_ns": 59_410_000_000,
                    }
                return {
                    "codec_name": "h264",
                    "width": 1920,
                    "height": 1080,
                    "r_frame_rate": "25/1",
                    "avg_frame_rate": "25/1",
                    "frame_count": 1380,
                    "duration_ns": 55_200_000_000,
                }

            receipt = _extract_pair_with_test_adapters(
                project_root=root,
                underbody_archive=underbody,
                front_archive=front,
                output_dir=staging,
                expected_underbody_sha256=_sha256(underbody_payload),
                expected_front_sha256=_sha256(front_payload),
                runner=runner,
                prober=probe,
                **_tool_arguments(root),
            )

            self.assertEqual(len(calls), 2)
            self.assertEqual(receipt["schema_version"], 1)
            self.assertEqual(receipt["artifact_kind"], "vast_kpp_legacy_iss_extraction_receipt")
            self.assertEqual(receipt["generation_id"], "kpp_legacy_iss_v2")
            self.assertEqual(receipt["status"], "test_adapter_candidate")
            self.assertFalse(
                receipt["claims"]["tool_bytes_and_version_outputs_externally_pinned"]
            )
            self.assertFalse(receipt["claims"]["video_payloads_stream_copied"])
            self.assertFalse(
                receipt["claims"]["output_set_directory_published_atomically"]
            )
            self.assertFalse(
                receipt["claims"][
                    "windows_project_root_staging_and_working_directory_handle_custody_validated"
                ]
            )
            self.assertEqual(
                [item["role"] for item in receipt["outputs"]],
                ["underbody", "front_gate"],
            )
            self.assertNotIn(str(root), json.dumps(receipt, sort_keys=True))
            receipt_path = staging / "kpp_iss_v2_extraction_receipt.json"
            encoded = receipt_path.read_bytes()
            self.assertTrue(encoded.endswith(b"\n"))
            self.assertEqual(json.loads(encoded), receipt)
            self.assertTrue((staging / "iss_v2_underbody.avi").is_file())
            self.assertTrue((staging / "iss_v2_front_gate.avi").is_file())

    def test_rejects_aliases_bad_hashes_existing_targets_and_missing_markers(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            staging = root / "staging" / "candidate"
            source = root / "source.iss"
            source.write_bytes(b"not-a-stream")
            with self.assertRaisesRegex(ExtractionError, "payload marker"):
                detect_payload_offset(source, "mjpeg")
            with self.assertRaisesRegex(ExtractionError, "child directory"):
                _extract_pair_with_test_adapters(
                    project_root=root,
                    underbody_archive=source,
                    front_archive=source,
                    output_dir=root / "staging",
                    expected_underbody_sha256=_sha256(source.read_bytes()),
                    expected_front_sha256=_sha256(source.read_bytes()),
                    runner=lambda command: None,
                    prober=lambda path: {},
                    **_tool_arguments(root),
                )

            good = root / "good.iss"
            good.write_bytes(b"x\xff\xd8\xff\xe0jpeg\xff\xd9")
            with self.assertRaisesRegex(ExtractionError, "physically distinct"):
                _extract_pair_with_test_adapters(
                    project_root=root,
                    underbody_archive=good,
                    front_archive=good,
                    output_dir=staging,
                    expected_underbody_sha256=_sha256(good.read_bytes()),
                    expected_front_sha256=_sha256(good.read_bytes()),
                    runner=lambda command: None,
                    prober=lambda path: {},
                    **_tool_arguments(root),
                )

            front = root / "front.iss"
            front.write_bytes(b"x\x00\x00\x00\x01\x67h264")
            with self.assertRaisesRegex(ExtractionError, "SHA-256"):
                _extract_pair_with_test_adapters(
                    project_root=root,
                    underbody_archive=good,
                    front_archive=front,
                    output_dir=staging,
                    expected_underbody_sha256="0" * 64,
                    expected_front_sha256=_sha256(front.read_bytes()),
                    runner=lambda command: None,
                    prober=lambda path: {},
                    **_tool_arguments(root),
                )

            staging.mkdir(parents=True)
            (staging / "iss_v2_underbody.avi").write_bytes(b"occupied")
            with self.assertRaisesRegex(ExtractionError, "already exists"):
                _extract_pair_with_test_adapters(
                    project_root=root,
                    underbody_archive=good,
                    front_archive=front,
                    output_dir=staging,
                    expected_underbody_sha256=_sha256(good.read_bytes()),
                    expected_front_sha256=_sha256(front.read_bytes()),
                    runner=lambda command: None,
                    prober=lambda path: {},
                    **_tool_arguments(root),
                )

    def test_pins_tools_and_rolls_back_the_whole_output_set(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            staging = root / "staging" / "candidate"
            underbody = root / "underbody.iss"
            front = root / "front.iss"
            underbody.write_bytes(b"x\xff\xd8\xff\xe0jpeg\xff\xd9")
            front.write_bytes(b"x\x00\x00\x00\x01\x67h264")
            tool_arguments = _tool_arguments(root)

            bad_tool_arguments = dict(tool_arguments)
            bad_tool_arguments["expected_ffmpeg_sha256"] = "0" * 64
            with self.assertRaisesRegex(ExtractionError, "ffmpeg executable SHA-256"):
                _extract_pair_with_test_adapters(
                    project_root=root,
                    underbody_archive=underbody,
                    front_archive=front,
                    output_dir=staging,
                    expected_underbody_sha256=_sha256(underbody.read_bytes()),
                    expected_front_sha256=_sha256(front.read_bytes()),
                    runner=lambda command: self.fail("runner must not be called"),
                    prober=lambda path: self.fail("prober must not be called"),
                    **bad_tool_arguments,
                )

            calls = 0

            def failing_runner(command: tuple[str, ...]) -> None:
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise ExtractionError("synthetic second-stream failure")
                Path(command[-1]).write_bytes(b"first-output")

            with self.assertRaisesRegex(ExtractionError, "second-stream"):
                _extract_pair_with_test_adapters(
                    project_root=root,
                    underbody_archive=underbody,
                    front_archive=front,
                    output_dir=staging,
                    expected_underbody_sha256=_sha256(underbody.read_bytes()),
                    expected_front_sha256=_sha256(front.read_bytes()),
                    runner=failing_runner,
                    prober=lambda path: {
                        "codec_name": "mjpeg",
                        "width": 1700,
                        "height": 236,
                        "r_frame_rate": "200/1",
                        "avg_frame_rate": "200/1",
                        "frame_count": 11882,
                        "duration_ns": 59_410_000_000,
                    },
                    **tool_arguments,
                )
            self.assertFalse(staging.exists())
            self.assertEqual(list((root / "staging").glob(".*.candidate")), [])

    @unittest.skipUnless(os.name == "nt", "Windows retained failure candidate only")
    def test_authoritative_failure_retains_custodied_private_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            underbody = root / "underbody.iss"
            front = root / "front.iss"
            underbody.write_bytes(b"x\xff\xd8\xff\xe0jpeg\xff\xd9")
            front.write_bytes(b"x\x00\x00\x00\x01\x67h264")
            ffmpeg, ffprobe, versions = _make_tools(root)
            cleanup = mock.Mock(side_effect=AssertionError("must retain candidate"))
            with mock.patch.object(
                extractor,
                "_windows_private_directory_acl_is_exact",
                side_effect=[True, False],
            ), mock.patch.object(
                extractor,
                "_cleanup_private_tree",
                cleanup,
            ), mock.patch.object(
                extractor,
                "_run",
                side_effect=AssertionError("media tool must not run"),
            ), mock.patch.object(
                extractor,
                "_read_tool_version",
                side_effect=AssertionError("tool version must not be read"),
            ):
                with self.assertRaisesRegex(ExtractionError, "ACL"):
                    extract_pair(
                        project_root=root,
                        underbody_archive=underbody,
                        front_archive=front,
                        output_dir=root / "staging" / "retained",
                        expected_underbody_sha256=_sha256(underbody.read_bytes()),
                        expected_front_sha256=_sha256(front.read_bytes()),
                        ffmpeg=ffmpeg,
                        expected_ffmpeg_sha256=_sha256(ffmpeg.read_bytes()),
                        expected_ffmpeg_version_sha256=_sha256(
                            versions[ffmpeg.name]
                        ),
                        ffprobe=ffprobe,
                        expected_ffprobe_sha256=_sha256(ffprobe.read_bytes()),
                        expected_ffprobe_version_sha256=_sha256(
                            versions[ffprobe.name]
                        ),
                    )

            cleanup.assert_not_called()
            candidates = list((root / "staging").glob(".retained.*.candidate"))
            self.assertEqual(len(candidates), 1)
            candidate = candidates[0]
            self.assertTrue(
                extractor._windows_private_directory_acl_is_exact(candidate)
            )
            self.assertEqual(list(candidate.iterdir()), [])
            candidate.rmdir()

    def test_rejects_incomplete_but_decodable_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            underbody = root / "underbody.iss"
            front = root / "front.iss"
            underbody.write_bytes(b"x\xff\xd8\xff\xe0jpeg\xff\xd9")
            front.write_bytes(b"x\x00\x00\x00\x01\x67h264")

            def runner(command: tuple[str, ...]) -> None:
                Path(command[-1]).write_bytes(b"decodable-but-partial")

            with self.assertRaisesRegex(ExtractionError, "frame_count mismatch"):
                _extract_pair_with_test_adapters(
                    project_root=root,
                    underbody_archive=underbody,
                    front_archive=front,
                    output_dir=root / "staging" / "partial",
                    expected_underbody_sha256=_sha256(underbody.read_bytes()),
                    expected_front_sha256=_sha256(front.read_bytes()),
                    runner=runner,
                    prober=lambda path: {
                        "codec_name": "mjpeg",
                        "width": 1700,
                        "height": 236,
                        "r_frame_rate": "200/1",
                        "avg_frame_rate": "200/1",
                        "frame_count": 1,
                        "duration_ns": 5_000_000,
                    },
                    **_tool_arguments(root),
                )

    def test_cli_requires_all_explicit_paths_and_pins(self) -> None:
        with self.assertRaises(SystemExit) as caught:
            main([])
        self.assertEqual(caught.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
