"""Real files/maps/FDs; inner tests inject a strict-default collector fault, no GI/decoder."""
import hashlib
import json
import mmap
import os
from pathlib import Path
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import research_protocol as p
import guest_consumer


def fd_count():
    return len(list(Path('/proc/self/fd').iterdir()))


class PinDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.path = self.base / 'input.bin'
        self.path.write_bytes(b'original')

    def tearDown(self):
        self.temp.cleanup()

    def rejected(self, path, message, **kwargs):
        before = fd_count()
        with self.assertRaises(Exception) as caught:
            p.Pin(path, **kwargs)
        self.assertEqual(str(caught.exception), message)
        self.assertEqual(fd_count(), before, 'rejected original file/ancestor FDs must close')
        facts = caught.exception.pin_rejection
        self.assertEqual(facts['requested_path'], os.fspath(path))
        self.assertIs(type(facts['observed_at_ns']), int)
        return caught.exception, facts

    def test_hardlink_preserves_original_rejection_and_actual_predicate_facts(self):
        os.link(self.path, self.base / 'second.bin')
        exc, facts = self.rejected(self.path, 'pin is not a bounded single-link regular file')
        self.assertIs(type(exc), p.ResearchError)
        self.assertEqual(facts['pin_stage'], 'fstat_predicate')
        self.assertEqual(facts['fstat']['nlink'], 2)
        self.assertEqual(facts['predicate_results'],
            {'regular_file': True, 'single_link': False, 'within_size_cap': True})
        self.assertEqual(facts['fstat'], facts['failure_fstat'])
        self.assertEqual(facts['resolved_lstat']['epoch'][1], self.path.stat().st_ino)

    def test_actual_directory_type_rejects_and_closes_fds(self):
        _, facts = self.rejected(self.base, 'pin is not a bounded single-link regular file')
        self.assertEqual(facts['fstat']['type'], 'directory')
        self.assertFalse(facts['predicate_results']['regular_file'])

    def test_actual_oversize_retains_original_size_and_limit_before_hash(self):
        with patch.object(p.Pin, 'digest', side_effect=AssertionError('must not hash rejected size')):
            _, facts = self.rejected(self.path, 'pin is not a bounded single-link regular file', maximum=7)
        self.assertEqual(facts['maximum_size_bytes'], 7)
        self.assertEqual(facts['fstat']['size_bytes'], 8)
        self.assertFalse(facts['predicate_results']['within_size_cap'])

    def test_requested_symlink_and_resolved_target_are_distinct_original_facts(self):
        os.link(self.path, self.base / 'second.bin')
        link = self.base / 'requested.so'
        link.symlink_to(self.path)
        _, facts = self.rejected(link, 'pin is not a bounded single-link regular file')
        self.assertEqual(facts['resolved_path'], str(self.path))
        self.assertEqual(facts['requested_lstat']['type'], 'symlink')
        self.assertEqual(facts['resolved_lstat']['type'], 'regular')
        self.assertEqual(facts['resolved_lstat']['nlink'], 2)

    def test_missing_resolve_retains_original_exception_and_unavailable_stats(self):
        missing = self.base / 'missing'
        before = fd_count()
        with self.assertRaises(FileNotFoundError) as caught:
            p.Pin(missing)
        self.assertEqual(fd_count(), before)
        facts = caught.exception.pin_rejection
        self.assertEqual(facts['pin_stage'], 'resolve')
        self.assertIsNone(facts['resolved_path'])
        self.assertIsNone(facts['fstat'])
        self.assertIsNone(facts['predicate_results'])
        self.assertIn('requested_lstat', facts['unavailable'])

    def test_substituted_inode_retains_held_and_named_failure_epochs(self):
        digest = p.Pin.digest
        def replace(pin):
            result = digest(pin)
            self.path.rename(self.base / 'original-held.bin')
            self.path.write_bytes(b'replacement')
            return result
        with patch.object(p.Pin, 'digest', replace):
            _, facts = self.rejected(self.path, 'held input changed')
        self.assertEqual(facts['pin_stage'], 'verify')
        self.assertNotEqual(facts['failure_fstat']['epoch'][1], facts['resolved_lstat']['epoch'][1])
        self.assertEqual(facts['fstat']['size_bytes'], 8)
        self.assertTrue(all(facts['predicate_results'].values()))


class InnerFailureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.library = self.base / 'libgst_real_mmap_fixture.so'
        self.library.write_bytes(b'actual mapped fixture bytes' * 128)
        os.link(self.library, self.base / 'second-library-link')
        self.map_file = self.library.open('rb')
        self.mapping = mmap.mmap(self.map_file.fileno(), 0, access=mmap.ACCESS_READ)
        media = self.base / 'media.bin'
        media.write_bytes(b'explicit fixture media; no source launched')
        self.media_pin = p.Pin(media)
        output = self.base / 'guest'
        output.mkdir()
        dummy = types.SimpleNamespace(find_property=lambda _: types.SimpleNamespace(minimum=-1, maximum=16, flags=3),
            get_property=lambda _: -1)
        pipeline = types.SimpleNamespace(get_by_name=lambda _: dummy, set_state=lambda _: 0)
        gst = types.SimpleNamespace(parse_launch=lambda _: pipeline, State=types.SimpleNamespace(NULL=0),
            StateChangeReturn=types.SimpleNamespace(FAILURE=-1))
        guest = self.g = guest_consumer.Guest.__new__(guest_consumer.Guest)
        guest.Gst = gst
        guest.GstVideo = None
        guest.output = output
        guest.begun = time.monotonic()
        guest.overall_deadline = guest.begun + 20
        guest.phase_deadline = guest.overall_deadline
        guest.media = {'front_gate': self.media_pin}
        guest.packages = {str(media): self.media_pin}
        guest.pins = [self.media_pin]
        guest.runs = []
        guest.metadata = p.Evidence(output / 'metadata', p.METADATA_MAX // 2)
        guest.metadata.close()
        guest.mapping_snapshot_count = 0
        guest.last_mapped_inputs = None
        original_pin = guest.pin
        def default_policy_fault(path, expected=None, *, mapped_identity=None):
            # V4 correctly allows this actual mapping; force the strict default to test the old first-error contract.
            return original_pin(path, expected)
        guest.pin = default_policy_fault
        self.clip = {'role': 'front_gate'}

    def tearDown(self):
        self.g.metadata.close()
        for pin in self.g.pins:
            pin.close()
        self.mapping.close()
        self.map_file.close()
        self.temp.cleanup()

    def failed_run(self):
        before = fd_count()
        with self.assertRaisesRegex(p.ResearchError, 'original research run failed'):
            self.g.run(1, self.clip, 'default')
        self.g.metadata.close()
        self.assertEqual(fd_count(), before)
        self.assertEqual(self.g.runs, [])
        directory = self.g.output / 'run-01-front_gate-default'
        terminal = p.verify_seal(json.loads((directory / 'terminal.v1.json').read_bytes()))
        self.assertFalse(terminal['run_successful'])
        self.assertEqual(terminal['errors'][0], 'pin is not a bounded single-link regular file')
        self.assertIsNone(terminal['source_returncode'])
        self.assertIsNone(terminal['observations'])
        self.assertEqual((directory / 'events.jsonl').read_bytes(), b'')
        self.assertFalse(any(path.name.startswith('source-') for path in directory.iterdir()))
        return directory, terminal

    def test_actual_maps_failure_retains_first_inner_stack_before_cleanup(self):
        directory, terminal = self.failed_run()
        path = directory / 'original-inner-failure.v1.json'
        raw = path.read_bytes()
        self.assertLessEqual(len(raw), p.EVENT_MAX)
        record = p.verify_seal(json.loads(raw))
        self.assertEqual(terminal['original_inner_failure']['sha256'], hashlib.sha256(raw).hexdigest())
        self.assertIsNone(terminal['inner_failure_capture_error'])
        self.assertEqual(record['stage'], 'pipeline_created.loaded_pins')
        self.assertEqual(record['pin_rejection']['requested_path'], str(self.library))
        self.assertEqual(record['pin_rejection']['fstat']['nlink'], 2)
        self.assertIn('loaded_pins', record['traceback'])
        self.assertIn('Pin', record['traceback'])
        self.assertIn('pin is not a bounded single-link regular file', record['traceback'])
        self.assertFalse(record['accepted'])
        self.assertTrue(terminal['cleanup_errors'], 'cleanup repeats the strict mapping check without replacing first error')

    def test_exclusive_diagnostic_collision_keeps_original_cause_and_prior_bytes(self):
        original = self.g.record_inner_failure
        def collision(evidence, *args):
            (evidence.directory / 'original-inner-failure.v1.json').write_bytes(b'explicit immutable collision fixture')
            return original(evidence, *args)
        self.g.record_inner_failure = collision
        directory, terminal = self.failed_run()
        self.assertEqual((directory / 'original-inner-failure.v1.json').read_bytes(), b'explicit immutable collision fixture')
        self.assertIsNone(terminal['original_inner_failure'])
        self.assertIn('File exists', terminal['inner_failure_capture_error'])

    def test_diagnostic_cap_failure_is_sticky_without_truncating_original_error(self):
        original = self.g.record_inner_failure
        def overlong(evidence, exc, stage, *args):
            return original(evidence, exc, 'X' * p.EVENT_MAX, *args)
        self.g.record_inner_failure = overlong
        directory, terminal = self.failed_run()
        self.assertFalse((directory / 'original-inner-failure.v1.json').exists())
        self.assertIsNone(terminal['original_inner_failure'])
        self.assertEqual(terminal['inner_failure_capture_error'], 'original inner failure record16KiB cap exceeded')

    def test_actual_readonly_fd_write_failure_closes_and_keeps_original_cause(self):
        append = p.Evidence.append
        def fail_write(evidence, name, raw, **kwargs):
            if name != 'original-inner-failure.v1.json':
                return append(evidence, name, raw, **kwargs)
            writer = evidence.streams[name]
            readonly = os.open(evidence.directory / name, os.O_RDONLY)
            evidence.streams[name] = readonly
            try:
                return append(evidence, name, raw, **kwargs)
            finally:
                evidence.streams[name] = writer
                os.close(readonly)
        with patch.object(p.Evidence, 'append', fail_write):
            directory, terminal = self.failed_run()
        self.assertEqual((directory / 'original-inner-failure.v1.json').read_bytes(), b'')
        self.assertIsNone(terminal['original_inner_failure'])
        self.assertIn('Bad file descriptor', terminal['inner_failure_capture_error'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
