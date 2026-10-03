from __future__ import annotations

import socket
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from analytics_execution_evidence import (  # noqa: E402
    EvidenceError,
    persist_execution_bundle,
    verify_execution_bundle,
)
import analytics_execution_evidence as evidence_module  # noqa: E402
from analytics_execution_worker import ExecutionClient, WorkerHarness  # noqa: E402
from test_analytics_execution_worker import FakeBackend, capability, request_for  # noqa: E402


@unittest.skipUnless(hasattr(socket, "SOCK_SEQPACKET"), "Linux SOCK_SEQPACKET is required")
class AnalyticsExecutionEvidenceTests(unittest.TestCase):
    def completed_inference(self):
        server, client_socket = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        worker = WorkerHarness(server, FakeBackend(), max_requests=1)
        thread = threading.Thread(target=worker.serve, daemon=True)
        thread.start()
        client = ExecutionClient(client_socket, expected_capability=capability())
        client.handshake()
        input_tensor = bytes(range(12))
        request = request_for(input_tensor)
        response, output = client.infer(request, input_tensor)
        client_socket.close()
        thread.join(timeout=5)
        server.close()
        self.assertFalse(thread.is_alive())
        return request, response, input_tensor, output

    def test_persisted_bundle_is_atomic_hash_bound_and_reverifiable(self) -> None:
        request, response, input_tensor, output = self.completed_inference()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "evidence"
            manifest = persist_execution_bundle(
                root,
                request=request,
                response=response,
                input_tensor=input_tensor,
                output_tensor=output,
                capability=capability(),
            )
            bundle = root / request["request_id"]
            self.assertTrue(bundle.is_dir())
            self.assertEqual(manifest["request_id"], request["request_id"])
            verified = verify_execution_bundle(bundle, capability=capability())
            self.assertEqual(verified, manifest)
            self.assertEqual((bundle / "input.tensor.bin").read_bytes(), input_tensor)
            self.assertEqual((bundle / "output.tensor.bin").read_bytes(), output)

            identity = bundle.stat().st_dev, bundle.stat().st_ino
            self.assertEqual(
                persist_execution_bundle(
                    root,
                    request=request,
                    response=response,
                    input_tensor=input_tensor,
                    output_tensor=output,
                    capability=capability(),
                ),
                manifest,
            )
            self.assertEqual((bundle.stat().st_dev, bundle.stat().st_ino), identity)

    def test_mutated_raw_output_is_rejected(self) -> None:
        request, response, input_tensor, output = self.completed_inference()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "evidence"
            persist_execution_bundle(
                root,
                request=request,
                response=response,
                input_tensor=input_tensor,
                output_tensor=output,
                capability=capability(),
            )
            output_path = root / request["request_id"] / "output.tensor.bin"
            output_path.chmod(0o644)
            output_path.write_bytes(b"tampered")
            with self.assertRaisesRegex(EvidenceError, "byte length|SHA-256"):
                verify_execution_bundle(output_path.parent, capability=capability())

    def test_evidence_directory_adopts_all_three_crash_windows(self) -> None:
        request, response, input_tensor, output = self.completed_inference()
        for step in (
            "mid_write",
            "post_fsync_pre_publish",
            "post_publish_pre_parent_fsync",
        ):
            with self.subTest(step=step), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp) / "evidence"

                def crash(observed: str) -> None:
                    if observed == step:
                        raise OSError("injected evidence crash")

                with self.assertRaisesRegex(OSError, "injected evidence crash"):
                    persist_execution_bundle(
                        root,
                        request=request,
                        response=response,
                        input_tensor=input_tensor,
                        output_tensor=output,
                        capability=capability(),
                        after_directory_publish_step=crash,
                    )
                manifest = persist_execution_bundle(
                    root,
                    request=request,
                    response=response,
                    input_tensor=input_tensor,
                    output_tensor=output,
                    capability=capability(),
                )
                bundle = root / request["request_id"]
                identity = bundle.stat().st_dev, bundle.stat().st_ino
                self.assertEqual(
                    persist_execution_bundle(
                        root,
                        request=request,
                        response=response,
                        input_tensor=input_tensor,
                        output_tensor=output,
                        capability=capability(),
                    ),
                    manifest,
                )
                self.assertEqual((bundle.stat().st_dev, bundle.stat().st_ino), identity)

    def test_adoption_rebind_before_cleanup_preserves_evidence_and_foreign_staging(self) -> None:
        request, response, input_tensor, output = self.completed_inference()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "evidence"
            expected = persist_execution_bundle(
                root,
                request=request,
                response=response,
                input_tensor=input_tensor,
                output_tensor=output,
                capability=capability(),
            )
            bundle = root / request["request_id"]
            final_identity = bundle.stat().st_dev, bundle.stat().st_ino
            real_commit = evidence_module.commit_or_adopt_immutable_directory_v1
            rebound: list[tuple[Path, Path]] = []

            def adopt_then_rebind(**kwargs):
                result = real_commit(**kwargs)
                staging = Path(kwargs["staging"])
                stolen = staging.with_name(staging.name + ".stolen")
                os.replace(staging, stolen)
                staging.mkdir()
                (staging / "FOREIGN").write_text("foreign\n", encoding="utf-8")
                rebound.append((staging, stolen))
                return result

            with (
                mock.patch.object(
                    evidence_module,
                    "commit_or_adopt_immutable_directory_v1",
                    side_effect=adopt_then_rebind,
                ),
                self.assertRaisesRegex(EvidenceError, "mutated|rebound|changed"),
            ):
                persist_execution_bundle(
                    root,
                    request=request,
                    response=response,
                    input_tensor=input_tensor,
                    output_tensor=output,
                    capability=capability(),
                )

            self.assertEqual(len(rebound), 1)
            foreign, stolen = rebound[0]
            self.assertEqual((bundle.stat().st_dev, bundle.stat().st_ino), final_identity)
            self.assertEqual(verify_execution_bundle(bundle, capability=capability()), expected)
            self.assertEqual((foreign / "FOREIGN").read_text(), "foreign\n")
            self.assertTrue(stolen.is_dir())

    def test_rejects_evidence_root_alias(self) -> None:
        request, response, input_tensor, output = self.completed_inference()
        with tempfile.TemporaryDirectory() as tmp:
            real_root = Path(tmp) / "real-evidence"
            real_root.mkdir()
            alias = Path(tmp) / "evidence-alias"
            try:
                alias.symlink_to(real_root, target_is_directory=True)
            except (NotImplementedError, OSError) as error:
                self.skipTest(f"directory symlinks unavailable: {error}")

            with self.assertRaisesRegex(EvidenceError, "alias|symlink|reparse"):
                persist_execution_bundle(
                    alias,
                    request=request,
                    response=response,
                    input_tensor=input_tensor,
                    output_tensor=output,
                    capability=capability(),
                )

            self.assertEqual(list(real_root.iterdir()), [])

    def test_rejects_staging_path_that_equals_its_parent(self) -> None:
        request, response, input_tensor, output = self.completed_inference()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "evidence"
            root.mkdir()

            with (
                mock.patch(
                    "analytics_execution_evidence.tempfile.mkdtemp",
                    return_value=str(root),
                ),
                self.assertRaisesRegex(EvidenceError, "staging.*parent"),
            ):
                persist_execution_bundle(
                    root,
                    request=request,
                    response=response,
                    input_tensor=input_tensor,
                    output_tensor=output,
                    capability=capability(),
                )
            self.assertTrue(root.is_dir())

    def test_replaced_staging_symlink_is_never_recursively_removed(self) -> None:
        request, response, input_tensor, output = self.completed_inference()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "evidence"
            canary = Path(tmp) / "canary"
            canary.mkdir()
            (canary / "KEEP").write_text("keep\n", encoding="utf-8")
            staging_holder: list[Path] = []
            real_mkdtemp = tempfile.mkdtemp
            real_replace = os.replace

            def tracked_mkdtemp(*args, **kwargs) -> str:
                staging = Path(real_mkdtemp(*args, **kwargs))
                staging_holder.append(staging)
                return str(staging)

            def replace_with_symlink(step: str) -> None:
                if step != "mid_write":
                    return
                staging = staging_holder[-1]
                saved = staging.with_name(staging.name + ".saved")
                real_replace(staging, saved)
                staging.symlink_to(canary, target_is_directory=True)
                raise OSError("injected replace failure")

            with (
                mock.patch(
                    "analytics_execution_evidence.tempfile.mkdtemp",
                    side_effect=tracked_mkdtemp,
                ),
                self.assertRaisesRegex(
                    EvidenceError, "symlink|junction|reparse|mutated|rebound"
                ),
            ):
                persist_execution_bundle(
                    root,
                    request=request,
                    response=response,
                    input_tensor=input_tensor,
                    output_tensor=output,
                    capability=capability(),
                    after_directory_publish_step=replace_with_symlink,
                )

            self.assertEqual(len(staging_holder), 1)
            self.assertEqual((canary / "KEEP").read_text(encoding="utf-8"), "keep\n")

    def test_evidence_root_must_not_be_the_current_directory(self) -> None:
        request, response, input_tensor, output = self.completed_inference()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "evidence"
            root.mkdir()

            with (
                mock.patch(
                    "analytics_execution_evidence.Path.cwd",
                    return_value=root.resolve(),
                ),
                self.assertRaisesRegex(EvidenceError, "current directory"),
            ):
                persist_execution_bundle(
                    root,
                    request=request,
                    response=response,
                    input_tensor=input_tensor,
                    output_tensor=output,
                    capability=capability(),
                )

    def test_unlinked_ambient_cwd_does_not_block_project_bound_bundle(self) -> None:
        request, response, input_tensor, output = self.completed_inference()
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            project_root.mkdir()
            root = project_root / "evidence"
            vanished_cwd = Path(tmp) / "vanished-cwd"
            vanished_cwd.mkdir()
            original_cwd = os.open(".", os.O_RDONLY)
            try:
                os.chdir(vanished_cwd)
                vanished_cwd.rmdir()
                manifest = persist_execution_bundle(
                    root,
                    request=request,
                    response=response,
                    input_tensor=input_tensor,
                    output_tensor=output,
                    capability=capability(),
                    project_root=project_root,
                )
            finally:
                os.fchdir(original_cwd)
                os.close(original_cwd)

            self.assertEqual(manifest["request_id"], request["request_id"])
            self.assertEqual(
                verify_execution_bundle(root / request["request_id"], capability=capability()),
                manifest,
            )

    def test_broken_symlink_bundle_collision_is_preserved(self) -> None:
        request, response, input_tensor, output = self.completed_inference()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "evidence"
            root.mkdir()
            target = root / request["request_id"]
            try:
                target.symlink_to(root / "missing", target_is_directory=True)
            except (NotImplementedError, OSError) as error:
                self.skipTest(f"directory symlinks unavailable: {error}")

            with self.assertRaisesRegex(EvidenceError, "already exists or is unsafe"):
                persist_execution_bundle(
                    root,
                    request=request,
                    response=response,
                    input_tensor=input_tensor,
                    output_tensor=output,
                    capability=capability(),
                )
            self.assertTrue(target.is_symlink())


if __name__ == "__main__":
    unittest.main()
