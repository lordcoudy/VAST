"""V6 pure regressions: real FD/mmap/child, explicit synthetic view and GI seams."""
import contextlib
import hashlib
import io
import json
import mmap
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import research_protocol as p
import guest_consumer as g


def decoded(path):
    return p.verify_seal(json.loads(path.read_bytes()))


def fd_count():
    return len(list(Path('/proc/self/fd').iterdir()))


class BackingSuccessorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.path = self.base / 'libgst_v6_fixture.so'
        self.path.write_bytes(b'real original bytes' * 512)
        self.file = self.path.open('rb')
        self.mapping = mmap.mmap(self.file.fileno(), 0, access=mmap.ACCESS_READ)
        st = self.path.stat()
        self.identity = (st.st_dev, st.st_ino)
        self.guest = g.Guest.__new__(g.Guest)
        self.guest.phase_deadline = time.monotonic() + 10
        self.guest.packages = {}
        self.guest.pins = []
        self.guest.metadata = p.Evidence(self.base / 'metadata', p.METADATA_MAX // 2)
        self.guest.mapping_snapshot_count = 0
        self.guest.last_mapped_inputs = None

    def tearDown(self):
        self.guest.metadata.close()
        for pin in self.guest.pins:
            pin.close()
        self.mapping.close()
        self.file.close()
        self.tmp.cleanup()

    @contextlib.contextmanager
    def synthetic_visible_device(self):
        """Only stat's visible device is synthetic; FD, mmap and proc rows are real."""
        fstat, lstat = os.fstat, Path.lstat
        def view(st):
            fields = ('st_dev', 'st_ino', 'st_mode', 'st_nlink', 'st_size',
                'st_mtime_ns', 'st_ctime_ns', 'st_uid', 'st_gid')
            return types.SimpleNamespace(**{k: getattr(st, k) for k in fields},
                **{})
        def change(st):
            if (st.st_dev, st.st_ino) == self.identity:
                st = view(st)
                st.st_dev += 65536
            return st
        with patch.object(p.os, 'fstat', lambda fd: change(fstat(fd))), \
                patch.object(p.Path, 'lstat', lambda path: change(lstat(path))):
            yield

    def test_real_held_fd_bridge_accepts_explicit_synthetic_visible_device(self):
        before = fd_count()
        with self.synthetic_visible_device():
            pin = p.Pin(self.path, mapped_identity=self.identity)
            try:
                obs = pin.mapping_observation
                self.assertEqual(obs['view'], 'readonly_backing_bridge')
                self.assertEqual(tuple(obs['selected_identity']), self.identity)
                self.assertNotEqual(tuple(obs['visible_identity']), self.identity)
                self.assertTrue(obs['probe']['export_released'])
                self.assertTrue(obs['probe']['mapping_closed'])
                self.assertEqual(obs['probe']['vma']['permissions'], 'r--p')
                pin.verify(rehash=True)
            finally:
                pin.close()
        self.assertEqual(fd_count(), before)

    def test_cached_bridge_uses_same_proof_and_expected_size_and_sha(self):
        expected = {'size_bytes': self.path.stat().st_size,
            'sha256': hashlib.sha256(self.path.read_bytes()).hexdigest()}
        with self.synthetic_visible_device():
            pin = self.guest.pin(self.path, expected, mapped_identity=self.identity)
            self.assertIs(self.guest.pin(self.path, expected, mapped_identity=self.identity), pin)
            self.assertEqual(pin.mapping_observation['view'], 'readonly_backing_bridge')
            with self.assertRaises(p.ResearchError):
                self.guest.pin(self.path, dict(expected, size_bytes=expected['size_bytes']+1),
                    mapped_identity=self.identity)

    def test_cached_expected_size_cannot_be_ignored(self):
        pin = self.guest.pin(self.path, mapped_identity=self.identity)
        with self.assertRaises(p.ResearchError):
            self.guest.pin(self.path, {'size_bytes': pin.descriptor['size_bytes']+1,
                'sha256': pin.descriptor['sha256']}, mapped_identity=self.identity)

    def test_cached_bridge_rechecks_real_ancestor_mode_after_probe_retirement(self):
        release = p._release_buffer
        with self.synthetic_visible_device():
            self.guest.pin(self.path, mapped_identity=self.identity)
            before = fd_count()
            def changed(view):
                release(view)
                os.chmod(self.base, self.base.stat().st_mode ^ 1)
            with patch.object(p, '_release_buffer', changed):
                with self.assertRaisesRegex(p.ResearchError, 'held ancestor changed'):
                    self.guest.pin(self.path, mapped_identity=self.identity)
            self.assertEqual(fd_count(), before)

    def test_cached_same_bytes_rewrite_during_rehash_keeps_full_epoch_guard(self):
        pin = self.guest.pin(self.path)
        digest = pin.digest
        original = self.path.read_bytes()
        def rewritten():
            value = digest()
            self.path.write_bytes(original)
            os.utime(self.path, ns=(self.path.stat().st_atime_ns, pin.initial_epoch[5]+1))
            return value
        with patch.object(pin, 'digest', rewritten):
            with self.assertRaisesRegex(p.ResearchError, 'held input changed'):
                self.guest.pin(self.path)
        self.assertEqual(self.path.read_bytes(), original)

    def test_growth_after_admission_cannot_enlarge_original_hash_read_bound(self):
        maximum = self.path.stat().st_size
        digest, pread = p.Pin.digest, os.pread
        reads = []
        def grown(pin):
            with self.path.open('ab') as leaf:
                leaf.write(b'!')
            return digest(pin)
        def observed(fd, size, offset):
            reads.append((size, offset))
            return pread(fd, size, offset)
        with patch.object(p.Pin, 'digest', grown), patch.object(p.os, 'pread', observed):
            with self.assertRaises(p.ResearchError):
                p.Pin(self.path, maximum=maximum)
        self.assertTrue(reads)
        self.assertLessEqual(max(size for size, _ in reads), maximum)
        self.assertTrue(all(offset+size <= maximum or (size, offset) == (1, maximum)
            for size, offset in reads))

    def test_selected_ambiguous_escapes_fail_classifier_and_actual_collector(self):
        raw = p.read_process_maps(os.getpid())
        _, selected = p.mapped_library_rows(raw, ('libgst_v6_fixture',))
        row = selected[0]
        for suffix in ('\\040', '\\134', '\\bad'):
            changed = raw.replace(row['original_row'].encode(),
                (row['original_row']+suffix).encode())
            with self.subTest(suffix=suffix):
                with self.assertRaisesRegex(p.ResearchError, 'ambiguous'):
                    p.mapped_library_rows(changed, ('libgst_v6_fixture',))
                with patch.object(g, 'read_process_maps', return_value=changed), \
                        patch.object(self.guest, 'pin') as pin:
                    with self.assertRaisesRegex(p.ResearchError, 'ambiguous'):
                        self.guest.mapped_library_pins(os.getpid(), ('libgst_v6_fixture',))
                    pin.assert_not_called()
                self.assertIsNone(self.guest.last_mapped_inputs)

    def test_wrong_pybuffer_field_offsets_reject_before_mapping_or_c_api(self):
        class WrongLayout(p.ctypes.Structure):
            _fields_ = [(name, kind) for name, kind in p._PyBuffer._fields_]
        # Same80-byte total and format offset40; only readonly/ndim are exchanged.
        class SwappedLayout(p.ctypes.Structure):
            _fields_ = [(('ndim' if name == 'readonly' else 'readonly' if name == 'ndim'
                else name), kind) for name, kind in WrongLayout._fields_]
        with patch.object(p, '_PyBuffer', SwappedLayout), \
                patch.object(p.mmap, 'mmap', side_effect=AssertionError('ABI must fail before mapping')) as mapping:
            with self.assertRaisesRegex(p.ResearchError, 'ABI unavailable'):
                p.readonly_backing_probe(self.file.fileno(), self.identity, time.monotonic()+5)
            mapping.assert_not_called()

    def test_real_readonly_probe_retires_export_mapping_and_fd(self):
        before = fd_count()
        obs = p.readonly_backing_probe(self.file.fileno(), self.identity, time.monotonic()+5)
        self.assertGreater(obs['buffer_address'], 0)
        self.assertGreater(obs['buffer_length'], 0)
        self.assertEqual(obs['vma']['offset'] + obs['buffer_address'] - obs['vma']['address_start'], 0)
        self.assertEqual(tuple(obs['vma']['mapped_identity']), self.identity)
        self.assertEqual(obs['abi']['version'], list(sys.version_info[:3]))
        self.assertEqual(obs['abi']['field_offsets'], {'buf': 0, 'obj': 8, 'len': 16,
            'itemsize': 24, 'readonly': 32, 'ndim': 36, 'format': 40, 'shape': 48,
            'strides': 56, 'suboffsets': 64, 'internal': 72})
        self.assertTrue(obs['export_released'] and obs['mapping_closed'])
        self.assertEqual(fd_count(), before)

    def test_wrong_backing_identity_fails_and_retires_real_probe(self):
        before = fd_count()
        for identity in ((self.identity[0]+1, self.identity[1]),
                (self.identity[0], self.identity[1]+1)):
            with self.assertRaisesRegex(p.ResearchError, 'mapped input identity differs'):
                p.readonly_backing_probe(self.file.fileno(), identity, time.monotonic()+5)
        self.assertEqual(fd_count(), before)

    def test_expired_real_probe_rejects_before_success(self):
        before = fd_count()
        with self.assertRaisesRegex(p.ResearchError, 'deadline'):
            p.readonly_backing_probe(self.file.fileno(), self.identity, time.monotonic()-1)
        self.assertEqual(fd_count(), before)

    def test_actual_full_maps_rejects_duplicate_but_classifier_retains_it(self):
        raw = p.read_process_maps(os.getpid())
        _, selected = p.mapped_library_rows(raw, ('libgst_v6_fixture',))
        duplicated = (selected[0]['original_row']+'\n') .encode() * 2
        self.assertEqual(len(p.mapped_library_rows(duplicated, ('libgst_v6_fixture',))[1]), 2)
        with self.assertRaisesRegex(p.ResearchError, 'overlap|duplicate'):
            p.parse_process_maps(duplicated)
        with patch.object(g, 'read_process_maps', return_value=duplicated):
            with self.assertRaisesRegex(p.ResearchError, 'overlap|duplicate'):
                self.guest.mapped_library_pins(os.getpid(), ('libgst_v6_fixture',))
        self.assertIsNone(self.guest.last_mapped_inputs)

    def test_anonymous_inode_zero_and_strict_ranges_permissions_offsets(self):
        row = b'1000-2000 rw-p 00000000 00:00 0 [heap]\n'
        self.assertEqual(p.parse_process_maps(row)[0]['mapped_identity'][1], 0)
        for bad in (b'2000-1000 rw-p 0 00:00 0', b'1000-2000 QQQQ 0 00:00 0',
                b'1000-2000 rw-p garbage 00:00 0', b'1000-2000 rw-p 0 ZZ:00 0',
                row+b'1800-3000 rw-p 0 00:00 0\n'):
            with self.assertRaises(p.ResearchError):
                p.parse_process_maps(bad)

    def test_original_selected_owner_and_complete_ranges_are_bracketed(self):
        self.guest.mapped_library_pins(os.getpid(), ('libgst_v6_fixture',))
        record = decoded(Path(self.guest.last_mapped_inputs['path']))
        self.assertEqual(record['owner_before'], record['owner_after'])
        self.assertEqual(record['selected_rows_before'], record['selected_rows_after'])
        row = record['selected_rows_before'][0]
        self.assertLess(row['address_start'], row['address_end'])
        self.assertIn('permissions', row)
        self.assertIn('offset', row)
        self.assertEqual(record['process']['pid'], os.getpid())

    def test_owner_change_and_selected_range_change_refuse_before_final_snapshot(self):
        actual_owner = p.owner(os.getpid())
        with patch.object(g, 'owner', side_effect=[actual_owner, dict(actual_owner,
                starttime_ticks=actual_owner['starttime_ticks']+1)]):
            with self.assertRaisesRegex(p.ResearchError, 'owner'):
                self.guest.mapped_library_pins(os.getpid(), ('libgst_v6_fixture',))
        self.assertIsNone(self.guest.last_mapped_inputs)
        raw = p.read_process_maps(os.getpid())
        _, selected = p.mapped_library_rows(raw, ('libgst_v6_fixture',))
        row = selected[0]
        changed = row['original_row'].replace(
            f"{row['address_start']:x}-{row['address_end']:x}",
            f"{row['address_start']+1:x}-{row['address_end']:x}", 1)
        after = raw.replace(row['original_row'].encode(), changed.encode())
        with patch.object(g, 'read_process_maps', side_effect=[raw, after]):
            with self.assertRaisesRegex(p.ResearchError, 'multiset changed'):
                self.guest.mapped_library_pins(os.getpid(), ('libgst_v6_fixture',))
        self.assertIsNone(self.guest.last_mapped_inputs)

    def test_bridge_wrong_permissions_offset_deleted_and_missing_range_reject(self):
        read = p.read_process_maps
        for fault in ('permissions', 'offset', 'deleted', 'range'):
            def altered(pid):
                raw = read(pid)
                rows = [r for r in p.parse_process_maps(raw) if r['path'] == str(self.path)
                    and r['permissions'] == 'r--p']
                self.assertEqual(len(rows), 1)
                row = rows[0]
                text = row['original_row']
                if fault == 'permissions':
                    changed = text.replace('r--p', 'r--s', 1)
                elif fault == 'offset':
                    fields = text.split(None, 5)
                    fields[2] = '1000'
                    changed = ' '.join(fields)
                elif fault == 'deleted':
                    changed = text+' (deleted)'
                else:
                    changed = text.replace(f"{row['address_start']:x}-", f"{row['address_start']+1:x}-", 1)
                return raw.replace(text.encode(), changed.encode())
            before = fd_count()
            with patch.object(p, 'read_process_maps', altered):
                with self.assertRaises(p.ResearchError):
                    p.readonly_backing_probe(self.file.fileno(), self.identity, time.monotonic()+5)
            self.assertEqual(fd_count(), before)

    def test_buffer_acquisition_error_retires_mapping_without_release_obligation(self):
        error = OSError('explicit buffer acquisition error')
        before = fd_count()
        def failed(*args):
            raise error
        with patch.object(p.ctypes.pythonapi, 'PyObject_GetBuffer', failed), \
                patch.object(p, '_release_buffer') as release:
            with self.assertRaises(OSError) as caught:
                p.readonly_backing_probe(self.file.fileno(), self.identity, time.monotonic()+5)
        self.assertIs(caught.exception, error)
        release.assert_not_called()
        self.assertTrue(error.backing_observation['mapping_closed'])
        self.assertFalse(error.backing_observation['export_released'])
        self.assertEqual(fd_count(), before)

    def test_parse_primary_survives_release_and_mapping_close_errors(self):
        primary = p.ResearchError('original explicit parse failure')
        release, close = p._release_buffer, p._close_mapping
        calls = []
        def release_fault(view):
            calls.append('release')
            release(view)
            raise OSError('release failed after actual retirement')
        def close_fault(mapping):
            calls.append('close')
            close(mapping)
            raise OSError('mapping close failed after actual retirement')
        before = fd_count()
        with patch.object(p, 'parse_process_maps', side_effect=primary), \
                patch.object(p, '_release_buffer', release_fault), \
                patch.object(p, '_close_mapping', close_fault):
            with self.assertRaises(p.ResearchError) as caught:
                p.readonly_backing_probe(self.file.fileno(), self.identity, time.monotonic()+5)
        self.assertIs(caught.exception, primary)
        self.assertEqual(calls, ['release', 'close'])
        self.assertEqual(len(primary.backing_observation['cleanup_errors']), 2)
        self.assertFalse(primary.backing_observation['export_released'])
        self.assertFalse(primary.backing_observation['mapping_closed'])
        self.assertEqual(fd_count(), before)

    def test_cancellation_primary_retires_probe_and_propagates_original_identity(self):
        error = KeyboardInterrupt('explicit fixture cancellation')
        before = fd_count()
        with patch.object(p, 'read_process_maps', side_effect=error):
            with self.assertRaises(KeyboardInterrupt) as caught:
                p.readonly_backing_probe(self.file.fileno(), self.identity, time.monotonic()+5)
        self.assertIs(caught.exception, error)
        self.assertTrue(error.backing_observation['export_released'])
        self.assertTrue(error.backing_observation['mapping_closed'])
        self.assertEqual(fd_count(), before)

    def test_held_bytes_changed_during_probe_remain_epoch_failure(self):
        release = p._release_buffer
        def changed(view):
            release(view)
            self.path.write_bytes(b'original fixture mutation during bridge')
        with self.synthetic_visible_device(), patch.object(p, '_release_buffer', changed):
            with self.assertRaisesRegex(p.ResearchError, 'held input changed'):
                p.Pin(self.path, mapped_identity=self.identity)

    def test_self_selected_bracket_excludes_only_actual_unique_bridge(self):
        with self.synthetic_visible_device():
            self.guest.mapped_library_pins(os.getpid(), ('libgst_v6_fixture',))
        record = decoded(Path(self.guest.last_mapped_inputs['path']))
        bridge = record['pin_observations'][0]['mapping_observation']['probe']
        self.assertEqual(bridge['selected_rows_during_without_probe'], record['selected_rows_before'])
        self.assertEqual(record['selected_rows_before'], record['selected_rows_after'])

    def test_final_snapshot_persistence_error_never_authorizes_collection(self):
        document = self.guest.metadata.document
        primary = OSError('explicit closed snapshot persistence error')
        def failed(name, *args, **kwargs):
            if '-closed.' in name:
                raise primary
            return document(name, *args, **kwargs)
        with patch.object(self.guest.metadata, 'document', failed):
            with self.assertRaises(OSError) as caught:
                self.guest.mapped_library_pins(os.getpid(), ('libgst_v6_fixture',))
        self.assertIs(caught.exception, primary)
        self.assertIsNone(self.guest.last_mapped_inputs)
        self.assertFalse(getattr(self.guest, 'mapped_library_collections', []))
        # Cached base Pin belongs to Guest; temporary probe resources are retired.
        self.assertEqual(len(self.guest.pins), 1)
        os.fstat(self.guest.pins[0].fd)

    def test_owner_reads_use_original_channel_limit_and_sentinel(self):
        huge = self.base/'owner-oversize-fixture'
        huge.write_bytes(b'x'*(p.CHANNEL_MAX+10))
        opened = []
        reads = []
        original = Path.open
        class Reader:
            def __init__(self, file):
                self.file = file
            def __enter__(self):
                return self
            def __exit__(self, *args):
                self.file.close()
            def read(self, size):
                raw = self.file.read(size)
                reads.append((size, len(raw)))
                return raw
        def redirected(path, *args, **kwargs):
            if str(path).startswith('/proc/'):
                f = original(huge, 'rb')
                opened.append(f)
                return Reader(f)
            return original(path, *args, **kwargs)
        with patch.object(p.Path, 'open', redirected):
            with self.assertRaisesRegex(p.ResearchError, 'owner1MiB cap'):
                p.owner(os.getpid())
        self.assertEqual(reads, [(p.CHANNEL_MAX+1, p.CHANNEL_MAX+1)])
        self.assertTrue(opened[0].closed)

    def test_unreleased_real_export_causes_genuine_mapping_close_failure(self):
        release, close = p._release_buffer, p._close_mapping
        views, mappings = [], []
        primary = OSError('explicit release refusal before actual retirement')
        def refused(view):
            views.append(view)
            raise primary
        def attempted(mapping):
            mappings.append(mapping)
            close(mapping)  # Genuine BufferError while actual exported pointer is held.
        before = fd_count()
        try:
            with patch.object(p, '_release_buffer', refused), patch.object(p, '_close_mapping', attempted):
                with self.assertRaises(OSError) as caught:
                    p.readonly_backing_probe(self.file.fileno(), self.identity, time.monotonic()+5)
            self.assertIs(caught.exception, primary)
            self.assertEqual(len(views), 1)
            self.assertEqual(len(mappings), 1)
            self.assertTrue(any('BufferError' in s for s in primary.backing_observation['cleanup_errors']))
            self.assertFalse(primary.backing_observation['mapping_closed'])
        finally:
            # Fixture-owned teardown only; original failed observation stays failed/unknown.
            for view in views:
                release(view)
            for mapping in mappings:
                close(mapping)
        self.assertEqual(fd_count(), before)

    def test_original_tiny_child_exit_during_collection_is_rejected(self):
        program = "import mmap,sys;f=open(sys.argv[1],'rb');m=mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ);print('READY',flush=True);sys.stdin.buffer.read(1);m.close();f.close()"
        child = subprocess.Popen([sys.executable, '-I', '-B', '-c', program, str(self.path)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            self.assertEqual(child.stdout.readline(6), b'READY\n')
            recorded = p.owner(child.pid)
            pin = self.guest.pin
            def exit_after_pin(*args, **kwargs):
                value = pin(*args, **kwargs)
                child.stdin.write(b'X'); child.stdin.flush()
                child.wait(timeout=2)
                return value
            with patch.object(self.guest, 'pin', exit_after_pin):
                with self.assertRaises((OSError, p.ResearchError)):
                    self.guest.mapped_library_pins(child.pid, ('libgst_v6_fixture',), recorded)
            self.assertIsNone(self.guest.last_mapped_inputs)
            self.assertEqual(child.returncode, 0)
        finally:
            if child.poll() is None:
                child.kill(); child.wait(timeout=2)
            for stream in (child.stdin, child.stdout, child.stderr):
                stream.close()

    def test_duplicate_full_bridge_snapshot_rejects_and_retires(self):
        raw = p.read_process_maps(os.getpid())
        before = fd_count()
        with patch.object(p, 'read_process_maps', return_value=raw+raw):
            with self.assertRaisesRegex(p.ResearchError, 'overlap|duplicate'):
                p.readonly_backing_probe(self.file.fileno(), self.identity, time.monotonic()+5)
        self.assertEqual(fd_count(), before)

    def test_failed_ancestor_fstat_retires_partially_acquired_fd(self):
        before = fd_count()
        fstat = os.fstat
        calls = 0
        def fail(fd):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise OSError('explicit ancestor fstat failure')
            return fstat(fd)
        with patch.object(p.os, 'fstat', fail):
            with self.assertRaisesRegex(OSError, 'ancestor fstat'):
                p.Pin(self.path)
        self.assertEqual(fd_count(), before)

    def test_pin_close_attempts_all_descriptors_and_preserves_first_error(self):
        pin = p.Pin(self.path)
        fds = [pin.fd]+[fd for _, fd, _ in pin.directories]
        close = os.close
        calls = []
        def failing(fd):
            calls.append(fd)
            close(fd)
            if fd == fds[0]:
                raise OSError('explicit close error after real retirement')
        with patch.object(p.os, 'close', failing):
            with self.assertRaisesRegex(OSError, 'explicit close error'):
                pin.close()
        self.assertCountEqual(calls, fds)
        for fd in fds:
            with self.assertRaises(OSError):
                os.fstat(fd)


class GuestModeSuccessorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.guest = g.Guest.__new__(g.Guest)
        x = self.guest
        x.begun = time.monotonic()
        x.overall_deadline = x.begun+20
        x.phase_deadline = x.begun+10
        x.mode = 'metadata-only'
        x.plan = {'mode': x.mode, 'planning_commit': '3aa35c3b2eedc05d22cf16ba37d470143d080f6b',
            'source_commit': '1'*40, 'current_checkout_commit': '1'*40,
            'sources': [{'role': 'front_gate'}, {'role': 'underbody'}]}
        plan = self.base / 'plan'
        plan.write_bytes(b'explicit fixture plan; no execution authority')
        x.plan_pin = p.Pin(plan)
        x.pins = [x.plan_pin]
        x.output = self.base / 'guest'
        x.output.mkdir()
        x.metadata = p.Evidence(x.output / 'metadata', p.METADATA_MAX//2)
        x.runs = []
        x.failure_stage = 'fixture_preflight'
        x.preflight = lambda: None
        x.run = lambda *a: (_ for _ in ()).throw(AssertionError('metadata must not create pipeline/source/run'))

    def tearDown(self):
        self.guest.metadata.close()
        for pin in self.guest.pins:
            pin.close()
        self.tmp.cleanup()

    def execute(self):
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            rc = self.guest.execute()
        return rc, json.loads(stream.getvalue())

    def test_metadata_completion_has_no_source_cohort_result_or_research_authority(self):
        rc, stdout = self.execute()
        self.assertEqual(rc, 0)
        self.assertTrue(stdout['successful'])
        terminal = decoded(self.guest.metadata.directory/'metadata-preflight-terminal.v1.json')
        self.assertTrue(terminal['operation_completed'] and terminal['metadata_preflight_completed'])
        self.assertTrue(terminal['provisional_until_owner_final_close'])
        self.assertEqual(terminal['mode'], 'metadata-only')
        self.assertEqual(terminal['runs_completed'], 0)
        self.assertIsNone(terminal['result'])
        self.assertFalse(terminal['research_complete'])
        self.assertFalse(any(f.name.startswith('run-') for f in self.guest.output.iterdir()))
        self.assertFalse(terminal['accepted'] or terminal['publication_ready'] or terminal['model_or_parity_evidence'])

    def test_metadata_original_preflight_error_keeps_identity_and_zero_runs(self):
        error = p.ResearchError('original fixture preflight failure')
        self.guest.preflight = lambda: (_ for _ in ()).throw(error)
        rc, out = self.execute()
        self.assertEqual(rc, 1)
        self.assertFalse(out['successful'])
        terminal = decoded(self.guest.metadata.directory/'metadata-preflight-terminal.v1.json')
        self.assertEqual(terminal['failure'], str(error))
        self.assertFalse(terminal['operation_completed'])
        self.assertEqual(terminal['runs_completed'], 0)

    def test_metadata_final_close_obeys_remaining_prelaunch_not_new600_clock(self):
        self.guest.phase_deadline = time.monotonic()+0.05
        close = p.Evidence.close
        def crossing(evidence):
            close(evidence)
            if evidence is self.guest.metadata:
                time.sleep(max(0, self.guest.phase_deadline-time.monotonic())+0.01)
        with patch.object(p.Evidence, 'close', crossing):
            rc, out = self.execute()
        self.assertEqual(rc, 1)
        self.assertIsNotNone(out['receipt_time_limit_failure'])
        late = decoded(self.guest.metadata.directory/'receipt-time-limit-failure.v1.json')
        self.assertEqual(late['deadline_monotonic_s'], self.guest.phase_deadline)
        self.assertLess(late['observed_after_final_close_monotonic_s'], self.guest.overall_deadline)

    def test_missing_or_mismatched_mode_never_enters_preflight(self):
        for mode in (None, 'invalid', 'research'):
            self.guest.mode = mode
            called = []
            self.guest.preflight = lambda: called.append(True)
            # Each iteration needs a fresh exclusive evidence owner.
            if self.guest.metadata.files:
                self.guest.metadata.close()
                self.guest.metadata = p.Evidence(self.base/('case-'+str(mode)))
            rc, out = self.execute()
            self.assertEqual(rc, 1)
            self.assertFalse(called)
            self.assertFalse(out['successful'])

    def test_metadata_pin_close_failure_blocks_provisional_success(self):
        pin = self.guest.plan_pin
        close = pin.close
        def fail():
            close()
            raise OSError('explicit pin close failure')
        with patch.object(pin, 'close', fail):
            rc, out = self.execute()
        self.assertEqual(rc, 1)
        self.assertEqual(out['pin_close_error'], 'explicit pin close failure')
        self.assertIsNotNone(out['close_failure'])
        self.assertFalse(out['successful'])

    def test_metadata_unexpected_run_namespace_blocks_body_completion(self):
        self.guest.preflight = lambda: (self.guest.output/'run-foreign').mkdir()
        rc, out = self.execute()
        self.assertEqual(rc, 1)
        self.assertFalse(out['successful'])
        self.assertFalse(decoded(self.guest.metadata.directory/'metadata-preflight-terminal.v1.json')['operation_completed'])

    def test_primary_survives_late_companion_write_and_close_failure(self):
        error = p.ResearchError('original failed fixture body before late persistence')
        self.guest.preflight = lambda: (_ for _ in ()).throw(error)
        self.guest.phase_deadline = time.monotonic()-1
        document, close = self.guest.metadata.document, self.guest.metadata.close
        def write(name, *args, **kwargs):
            if name == 'receipt-time-limit-failure.v1.json':
                raise OSError('late companion write failure')
            return document(name, *args, **kwargs)
        count = 0
        def close_fault():
            nonlocal count
            count += 1
            close()
            if count > 1:
                raise OSError('late companion close failure')
        with patch.object(self.guest.metadata, 'document', write), \
                patch.object(self.guest.metadata, 'close', close_fault):
            with self.assertRaises(p.ResearchError) as caught:
                self.execute()
        self.assertIs(caught.exception, error)
        self.assertTrue(any('late companion write failure' in n for n in error.__notes__))

    def test_research_first_failure_stops_before_later_setting(self):
        self.guest.mode = self.guest.plan['mode'] = 'research'
        calls = []
        def run(index, clip, setting):
            calls.append((clip['role'], setting))
            raise p.ResearchError('original first research failure')
        self.guest.run = run
        rc, out = self.execute()
        self.assertEqual(rc, 1)
        self.assertEqual(calls, [('front_gate', 'default')])
        terminal = decoded(self.guest.metadata.directory/'research-terminal.v1.json')
        self.assertEqual(terminal['failure'], 'original first research failure')
        self.assertFalse(out['successful'])

    def test_research_exact_four_order_and_complete_pairing_are_preserved(self):
        self.guest.mode = self.guest.plan['mode'] = 'research'
        calls = []
        def run(index, clip, setting):
            calls.append((clip['role'], setting))
            self.guest.runs.append({'explicit_synthetic_run':index})
            return {'clip':clip['role'], 'input_pts_decode_order':list(range(32)),
                'packets':[{'sequence':i+1} for i in range(32)],
                'outputs':[{'pts':i,'width':1,'height':1,'format':'RGB',
                    'caps':'video/x-raw,format=RGB','caps_features':[], 'pixel_sha256':'a'*64}
                    for i in range(32)],
                'timings':[{'residence_ns':index,'cohort':'startup' if i<8 else 'central' if i<24 else 'tail',
                    'after_actual_decoder_sink_eos':False} for i in range(32)],
                'central_steady_state_sufficient':True}
        self.guest.run = run
        rc, out = self.execute()
        self.assertEqual(rc, 0)
        self.assertEqual(calls, g.FIXED_ORDER)
        terminal = decoded(self.guest.metadata.directory/'research-terminal.v1.json')
        self.assertTrue(terminal['research_complete'])
        self.assertEqual(terminal['runs_completed'], 4)
        self.assertFalse(terminal['metadata_preflight_completed'])
        paired = decoded(self.guest.metadata.directory/'paired-timing.v1.json')
        self.assertEqual(len(paired['observations']), 64)
        self.assertTrue(out['successful'])


class GuestConstructionSuccessorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        code = Path(g.__file__).resolve().parent
        self.plan = {'artifact_kind':'vast_decoder_research_plan_v1',
            'planning_commit':g.PLANNING_COMMIT, 'mode':'metadata-only',
            'source_commit':'1'*40, 'current_checkout_commit':'1'*40,
            'review_repository_root':str(code), 'project_root':str(self.base),
            'fixed_order':[list(x) for x in g.FIXED_ORDER], 'guest_prelaunch_budget_s':7.5,
            'code':[{'path':str(code/name), 'size_bytes':(code/name).stat().st_size,
                'sha256':hashlib.sha256((code/name).read_bytes()).hexdigest()}
                for name in ('controller.py','guest_consumer.py','research_protocol.py')],
            'planning_files':[{'explicit_fixture':i} for i in range(4)]}

    def tearDown(self):
        self.tmp.cleanup()

    def construct(self, mode='metadata-only'):
        plan = self.base/'plan.json'
        plan.write_bytes(p.canonical(p.seal(self.plan))+b'\n')
        output = self.base/'output'
        output.mkdir(exist_ok=True)
        return g.Guest(plan, output, mode)

    def test_required_mode_validated_before_metadata_and_no_fd_leak(self):
        before = fd_count()
        for mode in (None, 'invalid', 'research'):
            with self.assertRaises(p.ResearchError):
                self.construct(mode)
            self.assertEqual(fd_count(), before)
            self.assertFalse((self.base/'output/metadata').exists())

    def test_remaining_budget_and_exact_mounted_code_are_bound(self):
        guest = self.construct()
        try:
            self.assertAlmostEqual(guest.phase_deadline-guest.begun, 7.5)
            self.assertEqual(len(guest.pins), 4)
            self.assertEqual(guest.mode, self.plan['mode'])
        finally:
            guest.metadata.close()
            for pin in guest.pins:
                pin.close()

    def test_code_descriptor_drift_and_nonfinite_budget_retire_acquired_pins(self):
        before = fd_count()
        self.plan['code'][1]['sha256'] = '0'*64
        with self.assertRaisesRegex(p.ResearchError, 'physical input descriptor mismatch'):
            self.construct()
        self.assertEqual(fd_count(), before)
        self.plan['guest_prelaunch_budget_s'] = True
        with self.assertRaisesRegex(p.ResearchError, 'budget invalid'):
            self.construct()
        self.assertEqual(fd_count(), before)
        self.assertFalse((self.base/'output/metadata').exists())
        raw = p.canonical(p.seal(dict(self.plan, guest_prelaunch_budget_s=7.5)))
        bad = self.base/'nonfinite-plan.json'
        bad.write_bytes(raw.replace(b'"guest_prelaunch_budget_s":7.5', b'"guest_prelaunch_budget_s":NaN'))
        with self.assertRaisesRegex(p.ResearchError, 'nonfinite'):
            g.Guest(bad, self.base/'output', 'metadata-only')
        self.assertEqual(fd_count(), before)


class GuestRunRetirementTests(unittest.TestCase):
    @contextlib.contextmanager
    def run_fixture(self, *, second_pipe_error=False, pipe_close_error=False,
            stream_close_error=False, thread_start_error=False):
        """Only Gst/source seams are synthetic; registry, Pins, Evidence and pipes are real."""
        before = fd_count()
        real_pipe, real_close, real_dup, real_owner = os.pipe, os.close, os.dup, g.owner
        acquired, retired, streams, evidences = [], [], [], []
        pipe_calls = 0
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            (base/'tmp').mkdir()
            guest = g.Guest.__new__(g.Guest)
            guest.begun = time.monotonic()
            guest.overall_deadline = guest.begun+20
            guest.phase_deadline = guest.begun+10
            guest.output = base/'guest'
            guest.output.mkdir()
            guest.packages, guest.pins, guest.runs = {}, [], []
            guest.active_source = guest.active_abort = guest.last_mapped_inputs = None
            guest.loaded_pins = lambda: []
            for leaf in ('registry', 'media', 'source'):
                (base/leaf).write_bytes(('real fixture '+leaf).encode())
            guest.registry = base/'registry'
            guest.pin(guest.registry)
            guest.media = {'front_gate':guest.pin(base/'media')}
            guest.source_pin = guest.pin(base/'source')
            pad = types.SimpleNamespace(add_probe=lambda *args: None)
            decoder = types.SimpleNamespace(find_property=lambda name:types.SimpleNamespace(
                minimum=-1, maximum=16, flags=3), get_property=lambda name:-1,
                get_static_pad=lambda name:pad)
            pipeline = types.SimpleNamespace(get_by_name=lambda name:decoder,
                set_state=lambda state:0, get_bus=lambda:None)
            guest.Gst = types.SimpleNamespace(parse_launch=lambda text:pipeline,
                PadProbeType=types.SimpleNamespace(BUFFER=1, EVENT_DOWNSTREAM=2),
                State=types.SimpleNamespace(PLAYING=1, NULL=0),
                StateChangeReturn=types.SimpleNamespace(FAILURE=-1))
            guest.GstVideo = None
            params = {'source_sha256':'1'*64, 'source_container':'mp4', 'source_codec':'h264',
                'source_duration_ns':32_000_000_000} if stream_close_error or thread_start_error else {}
            clip = {'role':'front_gate', 'dataset_id':'fixture', 'stream_id':1,
                'stock_source_parameters':params}
            def tracked_pipe():
                nonlocal pipe_calls
                pipe_calls += 1
                if second_pipe_error and pipe_calls == 2:
                    raise OSError(5, 'fixture second pipe acquisition')
                pair = real_pipe()
                acquired.extend((fd, os.fstat(fd).st_ino) for fd in pair)
                return pair
            def tracked_close(fd):
                identity = next((row for row in acquired if row[0] == fd and
                    os.fstat(fd).st_ino == row[1]), None)
                if identity is not None:
                    retired.append(identity)
                real_close(fd)
                if pipe_close_error and identity is not None and identity == acquired[0]:
                    raise OSError(9, 'fixture pipe retired then close error')
            def tracked_dup(fd):
                duplicate = real_dup(fd)
                acquired.append((duplicate, os.fstat(duplicate).st_ino))
                return duplicate
            def evidence(*args, **kwargs):
                value = p.Evidence(*args, **kwargs)
                evidences.append(value)
                return value
            def synthetic_source(*args, **kwargs):
                for index in range(2):
                    read_fd, write_fd = real_pipe()
                    real_close(write_fd)
                    raw = os.fdopen(read_fd, 'rb')
                    state = {'raw':raw, 'close_calls':0}
                    def close(state=state, index=index):
                        state['close_calls'] += 1
                        state['raw'].close()
                        if stream_close_error and index == 0:
                            raise OSError(9, 'fixture stdout retired then close error')
                    streams.append(dict(state, stream=types.SimpleNamespace(close=close, fileno=raw.fileno), state=state))
                return types.SimpleNamespace(pid=-12345, returncode=1, poll=lambda:1,
                    wait=lambda **kwargs:1, stdout=streams[0]['stream'], stderr=streams[1]['stream'])
            def owner(pid):
                if pid == -12345 and stream_close_error:
                    raise p.ResearchError('fixture source owner primary')
                if pid == -12345:
                    return real_owner(os.getpid())
                return real_owner(pid)
            try:
                with patch.object(g, 'Path', lambda value:base/'tmp' if value == '/tmp' else Path(value)), \
                        patch.object(g.os, 'pipe', tracked_pipe), patch.object(g.os, 'close', tracked_close), \
                        patch.object(g.os, 'dup', tracked_dup), \
                        patch.object(g, 'Evidence', evidence), patch.object(g, 'owner', owner), \
                        patch.object(g.subprocess, 'Popen', synthetic_source if stream_close_error or thread_start_error else
                            lambda *a, **k:(_ for _ in ()).throw(AssertionError('fixture must fail before source'))):
                    yield guest, clip, acquired, retired, streams
            finally:
                # RED can leak resources in the subject; the fixture retires only
                # positively matched original pipe inodes, never a reused FD number.
                for item in streams:
                    item['raw'].close()
                for fd, inode in acquired:
                    try:
                        if os.fstat(fd).st_ino == inode:
                            real_close(fd)
                    except OSError:
                        pass
                for item in evidences:
                    item.close()
                for pin in reversed(guest.pins):
                    pin.close()
        self.assertEqual(fd_count(), before)

    def assert_retired(self, acquired, retired):
        self.assertCountEqual(retired, acquired)
        for fd, inode in acquired:
            with self.assertRaises(OSError):
                os.fstat(fd)

    def test_run_partial_pipe_acquisition_retires_real_first_pair(self):
        with self.run_fixture(second_pipe_error=True) as (guest, clip, acquired, retired, streams):
            with self.assertRaisesRegex(p.ResearchError, 'no retry or subsequent setting'):
                guest.run(1, clip, 'default')
            self.assertEqual(len(acquired), 2)
            self.assert_retired(acquired, retired)
            directory = guest.output/'run-01-front_gate-default'
            failure = decoded(directory/'original-inner-failure.v1.json')
            terminal = decoded(directory/'terminal.v1.json')
            self.assertEqual(failure['message'], '[Errno 5] fixture second pipe acquisition')
            self.assertEqual(terminal['errors'], [failure['message']])
            self.assertFalse(terminal['run_successful'])
            self.assertEqual(guest.runs, [])
            self.assertEqual([path.name for path in guest.output.iterdir()], [directory.name])

    def test_run_retirement_errors_preserve_primary_and_attempt_remaining(self):
        for stream_error in (False, True):
            with self.subTest(stream_close_error=stream_error), self.run_fixture(
                    pipe_close_error=not stream_error, stream_close_error=stream_error) as values:
                guest, clip, acquired, retired, streams = values
                with self.assertRaisesRegex(p.ResearchError, 'no retry or subsequent setting'):
                    guest.run(1, clip, 'default')
                self.assertEqual(len(acquired), 10)
                self.assert_retired(acquired, retired)
                directory = guest.output/'run-01-front_gate-default'
                failure = decoded(directory/'original-inner-failure.v1.json')
                terminal = decoded(directory/'terminal.v1.json')
                expected = 'fixture source owner primary' if stream_error else "'source_sha256'"
                self.assertEqual(failure['message'], expected)
                self.assertEqual(terminal['errors'], [expected])
                self.assertTrue(any(('stdout retired' if stream_error else 'pipe retired') in error
                    for error in terminal['cleanup_errors']))
                self.assertFalse(terminal['run_successful'])
                self.assertEqual(guest.runs, [])
                self.assertEqual([path.name for path in guest.output.iterdir()], [directory.name])
                if stream_error:
                    self.assertEqual([item['state']['close_calls'] for item in streams], [1, 1])
                    self.assertTrue(all(item['raw'].closed for item in streams))

    def test_run_drain_handoff_and_retirement_keep_real_fd_and_first_cause(self):
        with self.subTest(stage='thread_start'), self.run_fixture(thread_start_error=True) as values:
            guest, clip, acquired, retired, streams = values
            with patch.object(g.threading.Thread, 'start',
                    side_effect=p.ResearchError('fixture Thread.start primary')):
                with self.assertRaisesRegex(p.ResearchError, 'no retry or subsequent setting'):
                    guest.run(1, clip, 'default')
            self.assertEqual(len(acquired), 11)  # Five pairs plus one actual duplicate.
            self.assert_retired(acquired, retired)
            directory = guest.output/'run-01-front_gate-default'
            failure = decoded(directory/'original-inner-failure.v1.json')
            terminal = decoded(directory/'terminal.v1.json')
            self.assertEqual(failure['message'], 'fixture Thread.start primary')
            self.assertEqual(terminal['errors'], [failure['message']])
            self.assertFalse(terminal['run_successful'])
            self.assertEqual(guest.runs, [])
        with self.subTest(stage='drain_read_and_close'):
            before = fd_count()
            real_close = os.close
            read_fd, write_fd = os.pipe()
            inode = os.fstat(read_fd).st_ino
            os.write(write_fd, b'original fixture pipe bytes')
            os.close(write_fd)
            guest = g.Guest.__new__(g.Guest)
            guest.overall_deadline = time.monotonic()+2
            failures = []
            def close_fault(fd):
                real_close(fd)
                raise OSError(9, 'fixture drain retired then close error')
            try:
                with patch.object(g.os, 'read', side_effect=OSError(5, 'fixture drain read primary')), \
                        patch.object(g.os, 'close', close_fault):
                    guest.drain(read_fd, None, None, g.threading.Event(), failures.append)
                self.assertEqual([str(error) for error in failures],
                    ['[Errno 5] fixture drain read primary', '[Errno 9] fixture drain retired then close error'])
                with self.assertRaises(OSError):
                    os.fstat(read_fd)
            finally:
                try:
                    if os.fstat(read_fd).st_ino == inode:
                        real_close(read_fd)
                except OSError:
                    pass
            self.assertEqual(fd_count(), before)


    def test_registry_reader_start_failure_preserves_primary_and_retires_auxiliary_fds(self):
        before = fd_count()
        real_popen, real_dup, real_close = subprocess.Popen, os.dup, os.close
        children, duplicates, stream_states = [], [], []
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            guest = g.Guest.__new__(g.Guest)
            guest.begun = time.monotonic()
            guest.overall_deadline = guest.begun+20
            guest.phase_deadline = guest.begun+10
            guest.mode = 'metadata-only'
            guest.output = base/'guest'
            guest.output.mkdir()
            guest.metadata = p.Evidence(guest.output/'metadata')
            guest.packages, guest.pins, guest.media, guest.runs = {}, [], {}, []
            guest.active_source = guest.active_abort = None
            guest.failure_stage = 'fixture_registry'
            routes = {}
            for requested, leaf in (('/usr/local/bin/vast_checkpoint_source', 'source'),
                    ('/opt/intel/dlstreamer/gstreamer/lib/gstreamer-1.0/libgstnvcodec.so', 'plugin'),
                    ('/opt/vast/media/front_gate.mp4', 'media')):
                path = base/leaf
                path.write_bytes(('real fixture '+leaf).encode())
                routes[requested] = path
            plan_path = base/'plan'
            plan_path.write_bytes(b'fixture-only plan, no registry or research authority')
            guest.plan_pin = p.Pin(plan_path)
            guest.pins.append(guest.plan_pin)
            guest.plan = {'mode':'metadata-only', 'planning_commit':g.PLANNING_COMMIT,
                'source_commit':'1'*40, 'current_checkout_commit':'1'*40,
                'source_binary':p.physical_descriptor(base/'source'),
                'nvcodec_plugin':p.physical_descriptor(base/'plugin'),
                'sources':[{'role':'front_gate','media':p.physical_descriptor(base/'media')}]}
            pin = guest.pin
            guest.pin = lambda path, expected=None, **kwargs:pin(routes.get(str(path), path), expected, **kwargs)
            def start(argv, **kwargs):
                # A real auxiliary child exercises custody/close; no gst-inspect or GI.
                child = real_popen([sys.executable, '-I', '-B', '-c',
                    'import time; time.sleep(30)'], **kwargs)
                children.append(child)
                wrapped = []
                for index, raw in enumerate((child.stdout, child.stderr)):
                    state = {'raw':raw, 'close_calls':0}
                    def close(state=state, index=index):
                        state['close_calls'] += 1
                        state['raw'].close()
                        if index == 0:
                            raise OSError(9, 'fixture registry stdout retired then close error')
                    stream_states.append(state)
                    wrapped.append(types.SimpleNamespace(close=close, fileno=raw.fileno))
                child.stdout, child.stderr = wrapped
                return child
            def duplicate(fd):
                value = real_dup(fd)
                duplicates.append((value, os.fstat(value).st_ino))
                return value
            try:
                with patch.object(g, 'Path', lambda value:base/'registry.bin'
                        if value == '/tmp/decoder-research-registry.bin' else Path(value)), \
                        patch.object(g.shutil, 'which', lambda name:sys.executable), \
                        patch.object(g.subprocess, 'Popen', start), patch.object(g.os, 'dup', duplicate), \
                        patch.object(g.threading.Thread, 'start',
                            side_effect=p.ResearchError('fixture registry Thread.start primary')), \
                        contextlib.redirect_stdout(io.StringIO()):
                    rc = guest.execute()
                terminal = decoded(guest.metadata.directory/'metadata-preflight-terminal.v1.json')
                self.assertEqual(rc, 1)
                with self.subTest(predicate='primary'):
                    self.assertEqual(terminal['failure'], 'fixture registry Thread.start primary')
                    primary = decoded(Path(terminal['original_primary_failure']['path']))
                    self.assertEqual(primary['message'], terminal['failure'])
                    self.assertIn('fixture registry stdout retired then close error', primary['traceback'])
                with self.subTest(predicate='streams'):
                    self.assertEqual([state['close_calls'] for state in stream_states], [1, 1])
                    self.assertTrue(all(state['raw'].closed for state in stream_states))
                with self.subTest(predicate='duplicate'):
                    self.assertEqual(len(duplicates), 1)
                    for fd, inode in duplicates:
                        with self.assertRaises(OSError):
                            os.fstat(fd)
                self.assertIsNotNone(children[0].poll())
                self.assertFalse(terminal['operation_completed'])
                self.assertEqual(terminal['runs_completed'], 0)
            finally:
                for child in children:
                    if child.poll() is None:
                        child.kill()
                    child.wait(timeout=2)
                for state in stream_states:
                    if not state['raw'].closed:
                        state['raw'].close()
                for fd, inode in duplicates:
                    try:
                        if os.fstat(fd).st_ino == inode:
                            real_close(fd)
                    except OSError:
                        pass
                guest.metadata.close()
                for pin in reversed(guest.pins):
                    pin.close()
        self.assertEqual(fd_count(), before)


if __name__ == '__main__':
    unittest.main(verbosity=2)
