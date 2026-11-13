"""Captured-engine pin ownership through public setup; all effects are doubles."""
from contextlib import nullcontext
import hashlib
from pathlib import Path
import stat
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from publication_physical_io_v1 import PhysicalRootCustodyV1
from tests.fixtures import accepted_policy_physical_fixture_v2 as fixture


class CapturedEnginePinTests(unittest.TestCase):
    def run_pin(self, *, hash_error=None, open_error=None, stat_error=None,
                fd_close_error=None, custody_close_error=None, body_error=None,
                opened=None, final=None, oversize=False):
        root = Path.cwd()
        raw = b"controlled captured ELF bytes; never executed"
        normal = SimpleNamespace(st_dev=4, st_ino=5, st_mode=stat.S_IFREG | 0o500,
            st_nlink=1, st_size=len(raw), st_mtime_ns=7, st_ctime_ns=8, st_uid=0, st_gid=0)
        self.normal, self.raw, self.reads, self.events = normal, raw, [], []
        self.custody = Mock()

        def hash_read(path, *, label, maximum, capture=False):
            self.reads.append((maximum, capture))
            if hash_error is not None:
                raise hash_error
            if oversize:
                raise ValueError("controlled captured engine exceeds16MiB")
            return {"path": Path(path).name, "size_bytes": len(raw),
                    "sha256": hashlib.sha256(raw).hexdigest()}, None, (4, 5)

        def close_custody():
            self.events.append("custody")
            if custody_close_error is not None:
                raise custody_close_error

        def close_fd(fd):
            self.events.append("fd")
            if fd_close_error is not None:
                raise fd_close_error

        self.custody.read_descriptor_identity.side_effect = hash_read
        self.custody.close.side_effect = close_custody
        engine = SimpleNamespace(engine=SimpleNamespace(path=root / "controlled-source-engine"),
                                 engine_socket={"path": root / "controlled-source-socket"})
        common = {key: root / key for key in ("candidate_index_path", "candidate_manifest_path",
            "candidate_receipt_path", "bootstrap_mapping_path", "bootstrap_receipt_path",
            "bootstrap_dir", "transaction_receipt_path")}
        front, control = Mock(), Mock()
        front.accept.return_value = (Mock(), None)
        stat_results = [opened or normal, final or normal]
        providers = {
            "preflight_original_fixture_engine_v1": Mock(),
            "prepare_original_fixture_engine_v1": Mock(return_value=nullcontext(engine)),
            "materialize_publication_policy_qualification_transaction_v2": Mock(return_value=common),
            "materialize_guardian_preprocessing_contract_v1": Mock(return_value={
                "contract_path": root / "contract", "receipt_path": root / "receipt"}),
            "materialize_execution_code_closure_v1": Mock(return_value={}),
            "prepare_stock_operational_capture_plan_v1": Mock(return_value={"descriptor": {"path": root / "plan"}}),
            "held_operational_capture_plan_v1": Mock(return_value=nullcontext({})),
            "materialize_publication_policy_qualification_runtime_inputs_v2": Mock(return_value={
                "runtime_input_root": root / "controlled-runtime-never-created"}),
        }
        from contextlib import ExitStack
        with ExitStack() as stack:
            for name, value in providers.items():
                stack.enter_context(patch.object(fixture, name, value))
            stack.enter_context(patch.object(fixture.fixture_admission, "_compiler_preparation_clock_v1"))
            stack.enter_context(patch.object(fixture.tempfile, "mkdtemp", return_value="/var/tmp/controlled-engine-pin"))
            stack.enter_context(patch.object(fixture.socket, "socket", side_effect=[front, control]))
            stack.enter_context(patch.object(Path, "mkdir"))
            stack.enter_context(patch.object(Path, "exists", return_value=False))
            stack.enter_context(patch.object(Path, "is_symlink", return_value=False))
            stack.enter_context(patch.object(Path, "lstat", return_value=normal))
            stack.enter_context(patch.object(Path, "read_bytes", side_effect=hash_error, return_value=raw))
            stack.enter_context(patch.object(PhysicalRootCustodyV1, "open", return_value=self.custody))
            self.open_fd = stack.enter_context(patch.object(fixture.os, "open", side_effect=open_error, return_value=77))
            self.close_fd = stack.enter_context(patch.object(fixture.os, "close", side_effect=close_fd))
            stack.enter_context(patch.object(fixture.os, "fstat", side_effect=stat_error or stat_results))
            with fixture.prepared_complete_fixture_inputs_v2(project_root=root,
                    output_dir=root / "controlled-pin-output-never-created",
                    identity_patch_path=root / "unused-patch",
                    accepted_model_parity_manifest_path=root / "unused-manifest",
                    accepted_model_parity_assessment_path=root / "unused-assessment",
                    accepted_model_parity_receipt_path=root / "unused-receipt",
                    image_inspections={}, device_probes={} ) as prepared:
                self.pin = prepared["capture_engine"]
                if body_error is not None:
                    raise body_error
        return self.pin

    def assert_causes(self, raised, primary, secondary=()):
        self.assertIs(getattr(raised.exception, "primary", raised.exception), primary)
        self.assertEqual(getattr(raised.exception, "secondary", ()), secondary)

    def test_pin_stream_hash_has16MiB_cap_and_no_payload_capture(self):
        pin = self.run_pin()
        self.assertEqual(self.reads, [(16 * 1024**2, False)])
        self.assertEqual(pin.size, len(self.raw))
        self.assertEqual(pin.sha256, hashlib.sha256(self.raw).hexdigest())
        self.assertEqual(pin.fd, 77)
        self.assertEqual(pin.proc_path, "/proc/self/fd/77")
        self.assertEqual(self.events, ["fd", "custody"])

    def test_hash_failure_precedes_raw_fd_allocation(self):
        primary = OSError("controlled hash read")
        with self.assertRaises(OSError) as raised:
            self.run_pin(hash_error=primary)
        self.assert_causes(raised, primary)
        self.open_fd.assert_not_called()

    def test_oversized_engine_refuses_before_fd_allocation(self):
        with self.assertRaisesRegex(ValueError, "16MiB"):
            self.run_pin(oversize=True)
        self.open_fd.assert_not_called()

    def test_opened_fd_is_closed_when_stat_raises_before_yield(self):
        primary = OSError("controlled fstat")
        with self.assertRaises(OSError) as raised:
            self.run_pin(stat_error=primary)
        self.assert_causes(raised, primary)
        self.close_fd.assert_called_once_with(77)

    def test_body_failure_survives_distinct_fd_close(self):
        primary, secondary = OSError("body"), OSError("fd close")
        with self.assertRaises(BaseException) as raised:
            self.run_pin(body_error=primary, fd_close_error=secondary)
        self.assert_causes(raised, primary, (secondary,))

    def test_body_failure_survives_distinct_custody_close(self):
        primary, secondary = OSError("body"), OSError("custody close")
        with self.assertRaises(BaseException) as raised:
            self.run_pin(body_error=primary, custody_close_error=secondary)
        self.assert_causes(raised, primary, (secondary,))

    def test_open_failure_survives_distinct_custody_close(self):
        primary, secondary = OSError("open"), OSError("custody close")
        with self.assertRaises(BaseException) as raised:
            self.run_pin(open_error=primary, custody_close_error=secondary)
        self.assert_causes(raised, primary, (secondary,))

    def test_identical_body_and_fd_close_object_is_not_duplicated(self):
        primary = OSError("same")
        with self.assertRaises(BaseException) as raised:
            self.run_pin(body_error=primary, fd_close_error=primary)
        self.assert_causes(raised, primary)

    def test_fd_close_alone_remains_primary(self):
        primary = OSError("close alone")
        with self.assertRaises(BaseException) as raised:
            self.run_pin(fd_close_error=primary)
        self.assert_causes(raised, primary)

    def test_wrong_opened_inode_refuses(self):
        changed = SimpleNamespace(st_dev=4, st_ino=6, st_mode=stat.S_IFREG | 0o500,
            st_nlink=1, st_size=len(b"controlled captured ELF bytes; never executed"),
            st_mtime_ns=7, st_ctime_ns=8, st_uid=0, st_gid=0)
        with self.assertRaisesRegex(ValueError, "identity"):
            self.run_pin(opened=changed)

    def test_epoch_change_during_body_refuses(self):
        changed = SimpleNamespace(st_dev=4, st_ino=5, st_mode=stat.S_IFREG | 0o500,
            st_nlink=1, st_size=len(b"controlled captured ELF bytes; never executed"),
            st_mtime_ns=9, st_ctime_ns=8, st_uid=0, st_gid=0)
        with self.assertRaisesRegex(ValueError, "identity"):
            self.run_pin(final=changed)

    def test_pin_open_is_nonfollowing_and_nonblocking(self):
        self.run_pin()
        flags = self.open_fd.call_args.args[1]
        self.assertTrue(flags & fixture.os.O_NOFOLLOW)
        self.assertTrue(flags & fixture.os.O_NONBLOCK)


if __name__ == "__main__":
    unittest.main()
