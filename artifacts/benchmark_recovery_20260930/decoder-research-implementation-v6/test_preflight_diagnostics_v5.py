"""Real mmap/files/FDs exercising outer execute; deliberate wrong inode, no GI/source/decoder."""
import contextlib
import hashlib
import io
import json
import mmap
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import research_protocol as p
import guest_consumer


def decoded(path):
    return p.verify_seal(json.loads(path.read_bytes()))


class PreflightDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.library = self.base / 'libgst_original_preflight_fixture.so'
        self.library.write_bytes(b'actual original mapped fixture' * 128)
        os.link(self.library, self.base / 'second-library-link')
        self.file = self.library.open('rb')
        self.mapping = mmap.mmap(self.file.fileno(), 0, access=mmap.ACCESS_READ)
        self.g = guest_consumer.Guest.__new__(guest_consumer.Guest)
        guest = self.g
        guest.begun = time.monotonic()
        guest.overall_deadline = guest.begun + 30
        guest.phase_deadline = guest.begun + 20
        guest.output = self.base / 'guest'
        guest.output.mkdir()
        guest.metadata = p.Evidence(guest.output / 'metadata', p.METADATA_MAX // 2)
        plan = self.base / 'plan.json'
        plan.write_bytes(b'explicit file fixture, no production plan or hardware')
        other = self.base / 'other.bin'
        other.write_bytes(b'actual held pin during failed preflight')
        guest.plan_pin = p.Pin(plan)
        guest.pins = [guest.plan_pin, p.Pin(other)]
        self.held_fds = [pin.fd for pin in guest.pins]
        self.held_fd_count = sum(1+len(pin.directories) for pin in guest.pins)
        guest.packages = {}
        guest.runs = []
        guest.mode = 'research'
        guest.plan = {'mode':'research', 'planning_commit':guest_consumer.PLANNING_COMMIT,
            'source_commit':'1'*40, 'current_checkout_commit':'1'*40}
        guest.failure_stage = 'fixture_preflight.actual_mapped_identity'
        self.primary = None

        def preflight():
            raw = p.read_process_maps(os.getpid())
            identities, rows = p.mapped_library_rows(raw, ('libgst_original_preflight_fixture',))
            actual = identities[str(self.library)]
            snapshot = guest.metadata.document('mapped-inputs-01.v1.json', {
                'artifact_kind':'vast_decoder_research_original_mapped_inputs_v1',
                'process':p.owner(os.getpid()), 'proc_path':f'/proc/{os.getpid()}/maps',
                'snapshot_size_bytes':len(raw), 'snapshot_sha256':hashlib.sha256(raw).hexdigest(),
                'selected_original_rows':rows, 'fixture_fault':'actual mapped inode plus one',
                'accepted':False,'publication_ready':False})
            try:
                guest.pin(self.library, mapped_identity=(actual[0], actual[1]+1))
            except BaseException as exc:
                self.primary = exc
                exc.pin_rejection['mapping_snapshot'] = snapshot
                exc.pin_rejection['original_mapping_row'] = rows[0]
                raise
        guest.preflight = preflight

    def tearDown(self):
        self.g.metadata.close()
        for pin in self.g.pins:
            pin.close()
        self.mapping.close()
        self.file.close()
        self.temp.cleanup()

    def execute_failed(self):
        before = len(list(Path('/proc/self/fd').iterdir()))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = self.g.execute()
        self.assertEqual(rc, 1)
        for fd in self.held_fds:
            with self.assertRaises(OSError):os.fstat(fd)
        self.assertEqual(len(list(Path('/proc/self/fd').iterdir())), before-self.held_fd_count-1)
        terminal = decoded(self.g.metadata.directory / 'research-terminal.v1.json')
        self.assertEqual(terminal['failure'], 'mapped input identity differs')
        self.assertEqual(terminal['failure_type'], 'research_protocol.ResearchError')
        self.assertEqual(terminal['failure_stage'], 'fixture_preflight.actual_mapped_identity')
        self.assertEqual(terminal['runs_completed'], 0)
        self.assertIsNone(terminal['result'])
        self.assertFalse(json.loads(out.getvalue())['successful'])
        self.assertFalse(any(path.name.startswith('run-') for path in self.g.output.iterdir()))
        return terminal, json.loads(out.getvalue())

    def test_original_mapped_rejection_persists_before_remaining_pin_retirement(self):
        original = self.g.record_inner_failure
        def observe(evidence, exc, *args):
            for fd in self.held_fds:os.fstat(fd)
            self.assertIs(exc, self.primary)
            return original(evidence, exc, *args)
        self.g.record_inner_failure = observe
        terminal, _ = self.execute_failed()
        path = self.g.metadata.directory / 'original-inner-failure.v1.json'
        self.assertLessEqual(path.stat().st_size, p.EVENT_MAX)
        record = decoded(path)
        self.assertEqual(terminal['original_primary_failure']['sha256'], hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertIsNone(terminal['primary_failure_capture_error'])
        self.assertEqual((record['run'],record['clip'],record['setting']), (None,None,None))
        self.assertEqual(record['stage'], terminal['failure_stage'])
        self.assertIn('preflight', record['traceback'])
        self.assertIn('Pin', record['traceback'])
        facts = record['pin_rejection']
        self.assertEqual(facts['requested_path'], str(self.library))
        self.assertEqual(facts['fstat']['nlink'], 2)
        self.assertEqual(facts['fstat'], facts['failure_fstat'])
        self.assertEqual(facts['pin_stage'],'mapped_identity_join')
        self.assertEqual(facts['predicate_results'],
            {'regular_file':True,'single_link':False,'within_size_cap':True})
        self.assertEqual(facts['mapped_named_lstat']['epoch'][1], facts['fstat']['epoch'][1])
        self.assertEqual(facts['mapped_identity'][1], facts['fstat']['epoch'][1]+1)
        self.assertEqual(facts['original_mapping_row']['mapped_identity'][1], facts['fstat']['epoch'][1])
        self.assertTrue((self.g.metadata.directory / 'mapped-inputs-01.v1.json').is_file())
        self.assertFalse(record['accepted'])

    def test_outer_record_cap_failure_preserves_original_cause_without_truncation(self):
        original = self.g.record_inner_failure
        self.g.record_inner_failure = lambda ev,exc,stage,*args:original(ev,exc,'X'*p.EVENT_MAX,*args)
        terminal, _ = self.execute_failed()
        self.assertIsNone(terminal['original_primary_failure'])
        self.assertEqual(terminal['primary_failure_capture_error'], 'original inner failure record16KiB cap exceeded')
        self.assertFalse((self.g.metadata.directory/'original-inner-failure.v1.json').exists())
        self.assertIn('mapped input identity differs', (self.g.metadata.directory/'original-failure-traceback.txt').read_text())

    def test_exclusive_collision_keeps_prior_bytes_and_original_primary(self):
        prior = b'explicit immutable fixture collision'
        (self.g.metadata.directory/'original-inner-failure.v1.json').write_bytes(prior)
        terminal, _ = self.execute_failed()
        self.assertIsNone(terminal['original_primary_failure'])
        self.assertIn('File exists', terminal['primary_failure_capture_error'])
        self.assertEqual((self.g.metadata.directory/'original-inner-failure.v1.json').read_bytes(), prior)

    def actual_readonly_write(self, target):
        original = p.Evidence.append
        def append(evidence,name,raw,**kwargs):
            if name != target:return original(evidence,name,raw,**kwargs)
            writer = evidence.streams[name]
            readonly = os.open(evidence.directory/name, os.O_RDONLY)
            evidence.streams[name] = readonly
            try:return original(evidence,name,raw,**kwargs)
            finally:
                evidence.streams[name] = writer
                os.close(readonly)
        return patch.object(p.Evidence,'append',append)

    def test_actual_readonly_primary_write_keeps_original_cause_and_retires_fds(self):
        with self.actual_readonly_write('original-inner-failure.v1.json'):
            terminal, _ = self.execute_failed()
        self.assertIsNone(terminal['original_primary_failure'])
        self.assertIn('Bad file descriptor',terminal['primary_failure_capture_error'])
        self.assertEqual((self.g.metadata.directory/'original-inner-failure.v1.json').read_bytes(),b'')

    def test_actual_trace_write_failure_does_not_replace_structured_primary(self):
        with self.actual_readonly_write('original-failure-traceback.txt'):
            terminal, _ = self.execute_failed()
        self.assertIsNotNone(terminal['original_primary_failure'])
        self.assertIn('Bad file descriptor',terminal['failure_traceback_error'])

    def test_metadata_close_failure_keeps_primary_and_retires_all_remaining_fds(self):
        original = p.Evidence.close
        failed = False
        def close(evidence):
            nonlocal failed
            original(evidence)
            if evidence is self.g.metadata and not failed:
                failed = True
                raise OSError('explicit close failure after actual FD retirement')
        with patch.object(p.Evidence,'close',close):
            terminal, out = self.execute_failed()
        self.assertIsNotNone(terminal['original_primary_failure'])
        close_record = decoded(self.g.metadata.directory/'guest-close-failure.v1.json')
        self.assertEqual(close_record['original_failure'],terminal['failure'])
        self.assertEqual(close_record['metadata_close_error'],'explicit close failure after actual FD retirement')
        self.assertEqual(out['close_failure']['sha256'],hashlib.sha256((self.g.metadata.directory/'guest-close-failure.v1.json').read_bytes()).hexdigest())

    def test_terminal_persistence_failure_raises_original_primary_and_retires_fds(self):
        original = self.g.metadata.document
        def document(name,*args,**kwargs):
            if name == 'research-terminal.v1.json':raise OSError('explicit final terminal persistence failure')
            return original(name,*args,**kwargs)
        self.g.metadata.document = document
        with self.assertRaisesRegex(p.ResearchError,'mapped input identity differs') as caught:
            self.g.execute()
        self.assertIs(caught.exception,self.primary)
        self.assertIn('guest terminal persistence failed: explicit final terminal persistence failure',caught.exception.__notes__)
        for fd in self.held_fds:
            with self.assertRaises(OSError):os.fstat(fd)
        self.assertEqual(decoded(self.g.metadata.directory/'original-inner-failure.v1.json')['message'],'mapped input identity differs')

    def test_close_companion_write_failure_stays_nonzero_and_reports_capture_error(self):
        original = p.Evidence.close
        failed = False
        def close(evidence):
            nonlocal failed
            original(evidence)
            if evidence is self.g.metadata and not failed:
                failed = True
                raise OSError('explicit original close failure')
        with patch.object(p.Evidence,'close',close), self.actual_readonly_write('guest-close-failure.v1.json'):
            terminal, out = self.execute_failed()
        self.assertEqual(out['metadata_close_error'],'explicit original close failure')
        self.assertIn('Bad file descriptor',out['close_failure_capture_error'])
        self.assertIsNone(out['close_failure'])
        self.assertEqual((self.g.metadata.directory/'guest-close-failure.v1.json').read_bytes(),b'')
        self.assertEqual(terminal['failure'],'mapped input identity differs')


if __name__ == '__main__':
    unittest.main(verbosity=2)
