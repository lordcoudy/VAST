"""Bounded journal header/cleanup regressions; all I/O and replay are doubles."""
import hashlib
import io
import os
from pathlib import Path
import stat
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from tests.fixtures import accepted_policy_guardian_journal_fixture_v1 as journal


class HeaderStream(io.BytesIO):
    def __init__(self, payload, *, read_error=None, close_error=None):
        super().__init__(payload)
        self.bounds, self.close_calls = [], 0
        self.read_error, self.close_error = read_error, close_error

    def readline(self, size=-1):
        self.bounds.append(size)
        if self.read_error is not None:
            raise self.read_error
        return super().readline(size)

    def fileno(self):
        return 77

    def close(self):
        self.close_calls += 1
        super().close()
        if self.close_error is not None:
            raise self.close_error


class JournalHeaderBoundsTests(unittest.TestCase):
    def run_case(self, payload=b"{}\n", *, before=None, opened=None, after=None,
                 read_error=None, close_error=None, finish_error=None,
                 recorder_close_error=None, fdopen_error=None, fdclose_error=None,
                 custody_close_error=None, descriptor_path=None):
        """No filesystem, process, source/authority or actual native-domain replay."""
        root = Path.cwd()
        path = root / "native-no-file.jsonl"
        companion = {"path": str(root / "companion-no-file.json"), "size_bytes": 2,
                     "sha256": hashlib.sha256(b"{}").hexdigest()}
        normal = SimpleNamespace(st_mode=stat.S_IFREG | 0o600, st_nlink=1, st_dev=4,
                                 st_ino=5, st_size=len(payload), st_mtime_ns=7, st_ctime_ns=8)
        before, opened, after = before or normal, opened or normal, after or normal
        stream = HeaderStream(payload, read_error=read_error, close_error=close_error)
        self.stream = stream

        class Custody:
            def __enter__(self):
                return self

            def __exit__(self, *ignored):
                self.close()

            def close(self):
                if custody_close_error is not None:
                    raise custody_close_error

            def verify(self):
                pass

            def stat_regular_identity(self, *args, **kwargs):
                return 0o600, (before.st_dev, before.st_ino)

            def read_descriptor(self, *args, **kwargs):
                return companion, None

        class Recorder:
            def finish(self, counters):
                if finish_error is not None:
                    raise finish_error
                return companion

            def close(self):
                if recorder_close_error is not None:
                    raise recorder_close_error

        descriptor = {"path": str(descriptor_path or path), "size_bytes": before.st_size,
                      "sha256": "0" * 64}
        self.descriptor = descriptor
        with patch.object(journal, "GuardianOperationalRecorder", return_value=Recorder()), \
                patch.object(journal.PhysicalRootCustodyV1, "open", return_value=Custody()), \
                patch.object(journal, "iter_native_domain_v1", return_value=iter(())) as replay, \
                patch.object(Path, "open", return_value=stream), \
                patch.object(Path, "lstat", side_effect=[before, after]), \
                patch.object(os, "open", return_value=77) as fdopen, \
                patch.object(os, "fdopen", side_effect=fdopen_error, return_value=stream), \
                patch.object(os, "fstat", side_effect=[opened, after]), \
                patch.object(os, "close", side_effect=fdclose_error) as fdclose:
            self.fdopen, self.fdclose, self.replay = fdopen, fdclose, replay
            return journal.write_fixture_guardian_operational_journals_v1(
                output_dir=root, headers_by_route={},
                native_domains=[{"descriptor": descriptor, "operation_id": "controlled"}],
                capability_manifest={})

    def assert_primary(self, raised, primary, secondary=()):
        error = raised.exception
        self.assertIs(getattr(error, "primary", error), primary)
        self.assertEqual(getattr(error, "secondary", ()), secondary)

    def test_valid_header_uses_fixed_read_bound_and_nonfollowing_fd(self):
        self.run_case()
        self.assertEqual(self.stream.bounds, [65537])
        self.assertEqual(self.stream.close_calls, 1)
        self.assertTrue(self.fdopen.call_args.args[1] & os.O_NOFOLLOW)
        self.replay.assert_called_once()

    def test_exact_header_ceiling_preserves_valid_json(self):
        self.run_case(b'{"pad":"' + b"a" * (65536 - 11) + b'"}\n')
        self.assertEqual(self.stream.bounds, [65537])

    def test_oversized_header_refuses_before_replay(self):
        with self.assertRaises(ValueError):
            self.run_case(b" " * 65536 + b"\n")
        self.assertEqual(self.stream.bounds, [65537])
        self.replay.assert_not_called()

    def test_truncated_header_refuses_before_replay(self):
        with self.assertRaisesRegex(ValueError, "truncated"):
            self.run_case(b"{}")
        self.replay.assert_not_called()

    def test_noncanonical_header_refuses_before_replay(self):
        with self.assertRaisesRegex(ValueError, "canonical"):
            self.run_case(b'{ "a":1}\n')
        self.replay.assert_not_called()

    def test_duplicate_key_header_refuses_before_replay(self):
        with self.assertRaises(ValueError):
            self.run_case(b'{"a":1,"a":1}\n')
        self.replay.assert_not_called()

    def test_nonobject_header_refuses_before_replay(self):
        with self.assertRaises(ValueError):
            self.run_case(b"[]\n")
        self.replay.assert_not_called()

    def test_unsafe_leaf_or_size_refuses_before_open(self):
        for change in ({"st_mode": stat.S_IFLNK}, {"st_mode": stat.S_IFIFO},
                       {"st_nlink": 2}, {"st_size": 64 * 1024**2 + 1}):
            metadata = dict(st_mode=stat.S_IFREG | 0o600, st_nlink=1, st_dev=4,
                            st_ino=5, st_size=3, st_mtime_ns=7, st_ctime_ns=8)
            metadata.update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.run_case(before=SimpleNamespace(**metadata))
            self.fdopen.assert_not_called()
            self.replay.assert_not_called()

    def test_opened_inode_and_postread_epoch_drift_refuse(self):
        for label, change in (("opened", {"st_ino": 6}), ("after", {"st_mtime_ns": 9})):
            metadata = dict(st_mode=stat.S_IFREG | 0o600, st_nlink=1, st_dev=4,
                            st_ino=5, st_size=3, st_mtime_ns=7, st_ctime_ns=8)
            metadata.update(change)
            with self.subTest(stage=label), self.assertRaises(ValueError):
                self.run_case(**{label: SimpleNamespace(**metadata)})
            self.replay.assert_not_called()

    def test_header_read_and_distinct_close_failures_are_retained(self):
        primary, secondary = OSError("controlled read"), OSError("controlled close")
        with self.assertRaises(BaseException) as raised:
            self.run_case(read_error=primary, close_error=secondary)
        self.assert_primary(raised, primary, (secondary,))

    def test_fdopen_failure_retains_descriptor_close_failure(self):
        primary, secondary = OSError("controlled fdopen"), OSError("controlled fd close")
        with self.assertRaises(BaseException) as raised:
            self.run_case(fdopen_error=primary, fdclose_error=secondary)
        self.assert_primary(raised, primary, (secondary,))
        self.fdclose.assert_called_once_with(77)

    def test_failed_buffer_construction_cannot_release_then_reclose_raw_fd(self):
        primary = OSError("controlled buffer construction")

        def partial_wrapper(fd, *args, closefd=True, **kwargs):
            # CPython closes raw FileIO on buffered construction failure.
            # A released integer could already name another owner's descriptor.
            if closefd:
                os.close(fd)
            raise primary

        with self.assertRaises(BaseException) as raised:
            self.run_case(fdopen_error=partial_wrapper)
        self.assert_primary(raised, primary)
        self.fdclose.assert_called_once_with(77)

    def test_successful_buffer_keeps_raw_descriptor_under_one_explicit_owner(self):
        self.run_case()
        self.assertEqual(self.stream.close_calls, 1)
        self.fdclose.assert_called_once_with(77)

    def test_recorder_close_preserves_header_primary_and_two_close_causes(self):
        primary, first, second = OSError("read"), OSError("stream close"), OSError("recorder close")
        with self.assertRaises(BaseException) as raised:
            self.run_case(read_error=primary, close_error=first, recorder_close_error=second)
        self.assert_primary(raised, primary, (first, second))

    def test_recorder_finish_primary_survives_distinct_close(self):
        primary, secondary = OSError("controlled finish"), OSError("controlled recorder close")
        with self.assertRaises(BaseException) as raised:
            self.run_case(finish_error=primary, recorder_close_error=secondary)
        self.assert_primary(raised, primary, (secondary,))

    def test_identical_read_and_close_failure_is_not_duplicated(self):
        primary = OSError("same object")
        with self.assertRaises(BaseException) as raised:
            self.run_case(read_error=primary, close_error=primary)
        self.assert_primary(raised, primary)

    def test_custody_close_failure_is_retained_with_header_primary(self):
        primary, secondary = OSError("read"), OSError("custody close")
        with self.assertRaises(BaseException) as raised:
            self.run_case(read_error=primary, custody_close_error=secondary)
        self.assert_primary(raised, primary, (secondary,))


if __name__ == "__main__":
    unittest.main()
