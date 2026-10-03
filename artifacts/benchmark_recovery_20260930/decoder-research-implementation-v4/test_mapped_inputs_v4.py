"""Actual hardlinks/mmap/CPython child; synthetic malformed rows, no GPU/GI/source run."""
import hashlib
import json
import mmap
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import research_protocol as p
import guest_consumer


class MappedInputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.path = self.base / 'libgst_actual_mapped_fixture.so'
        self.path.write_bytes(b'real backing file fixture bytes' * 128)
        self.alias = self.base / 'second-link'
        os.link(self.path, self.alias)
        self.file = self.path.open('rb')
        self.mapping = mmap.mmap(self.file.fileno(), 0, access=mmap.ACCESS_READ)
        info = self.path.stat()
        self.identity = (info.st_dev, info.st_ino)
        guest = self.g = guest_consumer.Guest.__new__(guest_consumer.Guest)
        guest.phase_deadline = time.monotonic() + 20
        guest.packages = {}
        guest.pins = []
        guest.metadata = p.Evidence(self.base / 'metadata', p.METADATA_MAX // 2)
        guest.mapping_snapshot_count = 0
        guest.last_mapped_inputs = None

    def tearDown(self):
        self.g.metadata.close()
        for pin in self.g.pins:
            pin.close()
        self.mapping.close()
        self.file.close()
        self.temp.cleanup()

    def row(self, path=None, identity=None):
        device, inode = self.identity if identity is None else identity
        return f'1000-2000 r--p 00000000 {os.major(device):02x}:{os.minor(device):02x} {inode} {path or self.path}'

    def test_actual_mapped_hardlink_accepts_join_but_default_still_rejects(self):
        identities, rows = p.mapped_library_rows(p.read_process_maps(os.getpid()), ('libgst',))
        self.assertEqual(identities[str(self.path)], self.identity)
        self.assertTrue(any(row['path'] == str(self.path) for row in rows))
        with self.assertRaisesRegex(p.ResearchError, 'single-link'):
            p.Pin(self.path)
        pin = p.Pin(self.path, mapped_identity=identities[str(self.path)])
        try:
            self.assertEqual(pin.initial_epoch[3], 2)
            self.assertEqual(pin.descriptor['sha256'], hashlib.sha256(self.path.read_bytes()).hexdigest())
            pin.verify(rehash=True)
        finally:
            pin.close()

    def test_wrong_device_inode_and_invalid_tuple_reject_before_hash_and_close(self):
        before = len(list(Path('/proc/self/fd').iterdir()))
        for identity in ((self.identity[0] + 1, self.identity[1]),
                (self.identity[0], self.identity[1] + 1), [*self.identity], (True, 1), (0, False), (0, 0), (-1, 1)):
            with patch.object(p.Pin, 'digest', side_effect=AssertionError('bad identity must not hash')):
                with self.assertRaises(p.ResearchError) as caught:
                    p.Pin(self.path, mapped_identity=identity)
            self.assertEqual(caught.exception.pin_rejection['mapped_identity'], identity)
            self.assertEqual(len(list(Path('/proc/self/fd').iterdir())), before)

    def test_named_substitution_cannot_match_original_mapping_identity(self):
        identities, _ = p.mapped_library_rows(p.read_process_maps(os.getpid()), ('libgst',))
        self.path.rename(self.base / 'held-original')
        self.path.write_bytes(b'same pathname, replacement inode')
        with self.assertRaisesRegex(p.ResearchError, 'mapped input identity differs') as caught:
            p.Pin(self.path, mapped_identity=identities[str(self.path)])
        facts = caught.exception.pin_rejection
        self.assertEqual(facts['pin_stage'], 'mapped_identity_join')
        self.assertNotEqual(facts['fstat']['epoch'][1], facts['mapped_identity'][1])

    def test_mapped_byte_mutation_remains_full_epoch_failure(self):
        pin = p.Pin(self.path, mapped_identity=self.identity)
        try:
            self.path.write_bytes(b'changed actual backing bytes')
            with self.assertRaisesRegex(p.ResearchError, 'held input changed'):
                pin.verify(rehash=True)
        finally:
            pin.close()

    def test_mapped_link_count_mutation_remains_full_epoch_failure(self):
        pin = p.Pin(self.path, mapped_identity=self.identity)
        try:
            self.alias.unlink()
            self.assertEqual(self.path.stat().st_nlink, 1)
            with self.assertRaisesRegex(p.ResearchError, 'held input changed'):
                pin.verify(rehash=True)
        finally:
            pin.close()

    def test_cached_default_cannot_inherit_mapping_policy_or_wrong_identity(self):
        pin = self.g.pin(self.path, mapped_identity=self.identity)
        self.assertIs(self.g.pin(self.path, mapped_identity=self.identity), pin)
        with self.assertRaisesRegex(p.ResearchError, 'single-link'):
            self.g.pin(self.path)
        with self.assertRaisesRegex(p.ResearchError, 'mapped input identity differs'):
            self.g.pin(self.path, mapped_identity=(self.identity[0], self.identity[1] + 1))
        with self.assertRaisesRegex(p.ResearchError, 'pin expected SHA differs'):
            self.g.pin(self.path, {'sha256': '0' * 64}, mapped_identity=self.identity)
        self.path.write_bytes(b'cached original changed')
        with self.assertRaisesRegex(p.ResearchError, 'held input changed'):
            self.g.pin(self.path, mapped_identity=self.identity)

    def test_correct_identity_does_not_bypass_type_size_or_expected_hash(self):
        info = self.base.stat()
        with self.assertRaisesRegex(p.ResearchError, 'positive-link regular file'):
            p.Pin(self.base, mapped_identity=(info.st_dev, info.st_ino))
        with self.assertRaisesRegex(p.ResearchError, 'positive-link regular file'):
            p.Pin(self.path, maximum=1, mapped_identity=self.identity)
        with self.assertRaisesRegex(p.ResearchError, 'physical input descriptor mismatch'):
            p.Pin(self.path, {'size_bytes': self.path.stat().st_size, 'sha256': '0' * 64}, mapped_identity=self.identity)

    def test_repeated_rows_keep_original_rows_and_conflicts_or_aliases_fail(self):
        row = self.row()
        identities, original = p.mapped_library_rows((row + '\n' + row + '\n').encode(), ('libgst',))
        self.assertEqual(identities, {str(self.path): self.identity})
        self.assertEqual(len(original), 2)
        conflict = self.row(identity=(self.identity[0], self.identity[1] + 1))
        with self.assertRaisesRegex(p.ResearchError, 'conflicting'):
            p.mapped_library_rows((row + '\n' + conflict).encode(), ('libgst',))
        symlink = self.base / 'libgst_alias.so'
        symlink.symlink_to(self.path)
        with self.assertRaisesRegex(p.ResearchError, 'conflicting'):
            p.mapped_library_rows((row + '\n' + self.row(symlink, (self.identity[0], self.identity[1] + 1))).encode(), ('libgst',))

    def test_deleted_ambiguous_malformed_missing_inode_and_absent_name_fail(self):
        bad = [self.row() + ' (deleted)', self.row(str(self.path) + '\\012suffix'),
            f'1000-2000 r--p 0000 ZZ:00 1 {self.path}',
            self.row(identity=(self.identity[0], 0)), f'1000-2000 r--p 0000 00:00 {self.path}']
        for row in bad:
            with self.assertRaises(p.ResearchError):
                p.mapped_library_rows(row.encode(), ('libgst',))
        with self.assertRaises(FileNotFoundError):
            p.mapped_library_rows(self.row(self.base / 'libgst_absent.so').encode(), ('libgst',))

    def test_maps_limit_reads_only_original_limit_plus_one_sentinel(self):
        huge = self.base / 'explicit-proc-stream-fixture'
        huge.write_bytes(b'x' * (p.CHANNEL_MAX + 10))
        opened = []
        def stream(path, *args, **kwargs):
            file = huge.open('rb')
            opened.append(file)
            return file
        original_open = Path.open
        def redirected(path, *args, **kwargs):
            if str(path) == '/proc/999999/maps':
                file = original_open(huge, 'rb'); opened.append(file); return file
            return original_open(path, *args, **kwargs)
        with patch.object(p.Path, 'open', redirected):
            with self.assertRaisesRegex(p.ResearchError, 'maps1MiB cap'):
                p.read_process_maps(999999)
        self.assertTrue(opened[0].closed)
        with self.assertRaisesRegex(p.ResearchError, 'maps1MiB cap'):
            p.mapped_library_rows(b'x' * (p.CHANNEL_MAX + 1), ('libgst',))

    def test_actual_guest_maps_snapshot_joins_cached_pin_and_backing_identity(self):
        libraries = self.g.mapped_library_pins(os.getpid(), ('libgst',))
        self.assertTrue(any(row['path'] == str(self.path) for row in libraries))
        desc = self.g.last_mapped_inputs
        raw = Path(desc['path']).read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), desc['sha256'])
        snapshot = p.verify_seal(json.loads(raw))
        self.assertEqual(snapshot['process']['pid'], os.getpid())
        row = next(row for row in snapshot['selected_original_rows'] if row['path'] == str(self.path))
        self.assertEqual(tuple(row['mapped_identity']), self.identity)
        self.g.mapped_library_pins(os.getpid(), ('libgst',))
        self.assertEqual(len(self.g.pins), 1)
        with self.assertRaisesRegex(p.ResearchError, 'single-link'):
            self.g.pin(self.path)

    def test_tiny_original_child_uses_same_actual_source_pid_maps_parser(self):
        program = "import mmap,sys;f=open(sys.argv[1],'rb');m=mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ);print('READY',flush=True);sys.stdin.buffer.read(1);m.close();f.close()"
        process = subprocess.Popen([sys.executable, '-I', '-B', '-c', program, str(self.path)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            self.assertEqual(process.stdout.readline(6), b'READY\n')
            libraries = self.g.mapped_library_pins(process.pid, ('libgst', 'libglib', 'libgobject'))
            self.assertTrue(any(row['path'] == str(self.path) for row in libraries))
            snapshot = p.verify_seal(json.loads(Path(self.g.last_mapped_inputs['path']).read_bytes()))
            self.assertEqual(snapshot['process']['pid'], process.pid)
            self.assertEqual(snapshot['process']['ppid'], os.getpid())
            process.stdin.write(b'X'); process.stdin.flush()
            stdout, stderr = process.communicate(timeout=2)
            self.assertEqual(process.returncode, 0)
            self.assertEqual(stderr, b'')
        finally:
            if process.poll() is None:
                process.kill(); process.wait(timeout=2)
            for stream in (process.stdin, process.stdout, process.stderr):
                stream.close()

    def test_snapshot_cap_failure_cannot_authorize_mapped_pin(self):
        self.g.metadata.maximum = 2 * p.EVENT_MAX + 64
        with self.assertRaisesRegex(p.ResearchError, 'namespace byte cap'):
            self.g.mapped_library_pins(os.getpid(), ('libgst',))
        self.assertEqual(self.g.pins, [])
        self.assertIsNone(self.g.last_mapped_inputs)
        path = self.g.metadata.directory / 'mapped-inputs-01.v1.json'
        self.assertEqual(path.read_bytes(), b'')


if __name__ == '__main__':
    unittest.main(verbosity=2)
