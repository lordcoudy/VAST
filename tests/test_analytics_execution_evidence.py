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
            with mock.patch(
                "analytics_execution_evidence.shutil.rmtree"
            ) as remove_tree:
                manifest = persist_execution_bundle(
                    root,
                    request=request,
                    response=response,
                    input_tensor=input_tensor,
                    output_tensor=output,
                    capability=capability(),
                )
            remove_tree.assert_not_called()
            bundle = root / request["request_id"]
            self.assertTrue(bundle.is_dir())
            self.assertEqual(manifest["request_id"], request["request_id"])
            verified = verify_execution_bundle(bundle, capability=capability())
            self.assertEqual(verified, manifest)
            self.assertEqual((bundle / "input.tensor.bin").read_bytes(), input_tensor)
            self.assertEqual((bundle / "output.tensor.bin").read_bytes(), output)

            with self.assertRaisesRegex(EvidenceError, "already exists"):
                persist_execution_bundle(
                    root,
                    request=request,
                    response=response,
                    input_tensor=input_tensor,
                    output_tensor=output,
                    capability=capability(),
                )

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
                mock.patch("analytics_execution_evidence.shutil.rmtree") as remove_tree,
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

            remove_tree.assert_not_called()
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

            def replace_with_symlink(source: Path, destination: Path) -> None:
                staging = Path(source)
                saved = staging.with_name(staging.name + ".saved")
                real_replace(staging, saved)
                staging.symlink_to(canary, target_is_directory=True)
                raise OSError("injected replace failure")

            with (
                mock.patch(
                    "analytics_execution_evidence.tempfile.mkdtemp",
                    side_effect=tracked_mkdtemp,
                ),
                mock.patch(
                    "analytics_execution_evidence.os.replace",
                    side_effect=replace_with_symlink,
                ),
                mock.patch("analytics_execution_evidence.shutil.rmtree") as remove_tree,
                self.assertRaisesRegex(EvidenceError, "symlink|junction|reparse"),
            ):
                persist_execution_bundle(
                    root,
                    request=request,
                    response=response,
                    input_tensor=input_tensor,
                    output_tensor=output,
                    capability=capability(),
                )

            self.assertEqual(len(staging_holder), 1)
            remove_tree.assert_not_called()
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

            with (
                mock.patch("analytics_execution_evidence.shutil.rmtree") as remove_tree,
                self.assertRaisesRegex(EvidenceError, "already exists or is unsafe"),
            ):
                persist_execution_bundle(
                    root,
                    request=request,
                    response=response,
                    input_tensor=input_tensor,
                    output_tensor=output,
                    capability=capability(),
                )

            remove_tree.assert_not_called()
            self.assertTrue(target.is_symlink())


if __name__ == "__main__":
    unittest.main()
