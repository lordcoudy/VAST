"""Unexecuted tiny physical fixture for the finite artifact setup collector.

Loads only the actual file/ancestor functions through AST, never its dispatch
body. No repository clone, model, Docker, source input or benchmark is touched.
"""
import ast
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import selectors
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch


HELPER = Path(__file__).with_name('setup_finite_ext4_root_v1.py')


class FiniteTransferFixtureTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='vast-d27-transfer-fixture-')
        self.root = Path(self.temporary.name)
        self.source = self.root/'source'
        self.target = self.root/'target'
        self.source.mkdir()
        self.target.mkdir()
        self.file = self.source/'leaf.bin'
        self.payload = b'original tiny fixture\x00'*193
        self.file.write_bytes(self.payload)
        self.ns = {'Path': Path, 'PurePosixPath': PurePosixPath, 'os': os,
                   'stat': stat, 'time': time, 'hashlib': hashlib,
                   'DEADLINE': time.monotonic()+30, 'held': [], 'directory_pins': {}}
        tree = ast.parse(HELPER.read_bytes())
        wanted = {'clock', 'epoch', 'canonical_directory', 'directory_barrier',
                  'path_for', 'pin', 'digest', 'copy_original', 'namespace_files', 'tracked_snapshot'}
        definitions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in wanted]
        self.assertEqual({node.name for node in definitions}, wanted)
        exec(compile(ast.Module(body=definitions, type_ignores=[]), str(HELPER), 'exec'), self.ns)
        self.expected = {'path': 'leaf.bin', 'size_bytes': len(self.payload),
                         'sha256': hashlib.sha256(self.payload).hexdigest(),
                         'current_epoch': self.ns['epoch'](self.file.lstat())}

    def tearDown(self):
        for row in self.ns['held']:
            os.close(row['fd'])
        for row in self.ns['directory_pins'].values():
            os.close(row['fd'])
        self.temporary.cleanup()

    def pinned(self):
        return self.ns['pin'](self.file, self.expected)

    def test_actual_original_stream_copy_has_new_inode_and_exact_bytes(self):
        src = self.pinned()
        dst = self.target/'leaf.bin'
        target = self.ns['copy_original'](src, dst, self.expected)
        self.assertEqual(dst.read_bytes(), self.payload)
        self.assertEqual(target['epoch'], self.ns['epoch'](dst.lstat()))
        self.assertNotEqual(src['epoch'][:2], target['epoch'][:2])
        self.ns['digest'](src, self.expected)
        self.ns['digest'](target, self.expected)

    def test_occupied_target_is_not_replaced(self):
        dst = self.target/'leaf.bin'
        dst.write_bytes(b'owned existing fixture')
        before = self.ns['epoch'](dst.lstat())
        with self.assertRaises(AssertionError):
            self.ns['copy_original'](self.pinned(), dst, self.expected)
        self.assertEqual(dst.read_bytes(), b'owned existing fixture')
        self.assertEqual(before, self.ns['epoch'](dst.lstat()))

    def test_same_bytes_source_leaf_replacement_rejects_real_fd_name_mismatch(self):
        src = self.pinned()
        self.file.rename(self.source/'old.bin')
        self.file.write_bytes(self.payload)
        with self.assertRaises(AssertionError):
            self.ns['digest'](src, self.expected)

    def test_actual_ancestor_symlink_rejects_even_same_original_leaf_inode(self):
        src = self.pinned()
        original = self.root/'original-source'
        self.source.rename(original)
        self.source.symlink_to(original, target_is_directory=True)
        with self.assertRaises(AssertionError):
            self.ns['digest'](src, self.expected)

    def test_actual_source_byte_change_is_not_accepted(self):
        src = self.pinned()
        self.file.write_bytes(b'x'*len(self.payload))
        with self.assertRaises(AssertionError):
            self.ns['digest'](src, self.expected)

    def test_same_bytes_target_leaf_replacement_rejects(self):
        dst = self.target/'leaf.bin'
        target = self.ns['copy_original'](self.pinned(), dst, self.expected)
        dst.rename(self.target/'old-target.bin')
        dst.write_bytes(self.payload)
        with self.assertRaises(AssertionError):
            self.ns['digest'](target, self.expected)

    def test_hardlinked_leaf_is_rejected(self):
        os.link(self.file, self.source/'alias.bin')
        with self.assertRaises(AssertionError):
            self.ns['pin'](self.file)

    def test_wrong_declared_raw_hash_leaves_failed_prefix_without_success(self):
        src = self.pinned()
        wrong = {**self.expected, 'sha256': '0'*64}
        dst = self.target/'leaf.bin'
        with self.assertRaises(AssertionError):
            self.ns['copy_original'](src, dst, wrong)
        self.assertTrue(dst.is_file())
        self.assertEqual(len(self.ns['held']), 1)

    def test_actual_target_name_substitution_during_fsync_is_rejected(self):
        src = self.pinned()
        dst = self.target/'leaf.bin'
        real_fsync = os.fsync
        replaced = False

        def fsync_and_replace(fd):
            nonlocal replaced
            real_fsync(fd)
            if not replaced and dst.exists():
                replaced = True
                dst.rename(self.target/'old-target.bin')
                dst.write_bytes(self.payload)

        with patch.object(os, 'fsync', side_effect=fsync_and_replace):
            with self.assertRaises(AssertionError):
                self.ns['copy_original'](src, dst, self.expected)
        self.assertTrue(replaced)

    def test_legitimate_sibling_creation_preserves_actual_ancestor_identity(self):
        src = self.pinned()
        (self.source/'legitimate-sibling').write_bytes(b'fixture output')
        self.ns['digest'](src, self.expected)

    def test_relative_escape_is_rejected_before_any_output(self):
        with self.assertRaises(AssertionError):
            self.ns['path_for'](self.target, '../escape.bin', create_parents=True)
        self.assertFalse((self.root/'escape.bin').exists())
        self.assertEqual(list(self.target.iterdir()), [])

    def test_expired_original_deadline_is_failed_not_a_successful_copy(self):
        src = self.pinned()
        self.ns['DEADLINE'] = time.monotonic()-1
        dst = self.target/'leaf.bin'
        with self.assertRaises(TimeoutError):
            self.ns['copy_original'](src, dst, self.expected)
        self.assertEqual(len(self.ns['held']), 1)
        self.assertEqual(self.file.read_bytes(), self.payload)
        self.assertEqual(dst.stat().st_size, 0)


    def test_exact_fresh_namespace_accepts_only_declared_tracked_and_copied_leaves(self):
        (self.target/'.git').mkdir()
        (self.target/'tracked.py').write_bytes(b'fixture tracked\n')
        (self.target/'copied').mkdir()
        (self.target/'copied/leaf.bin').write_bytes(self.payload)
        result = self.ns['namespace_files'](self.target, {'tracked.py', 'copied/leaf.bin'})
        self.assertEqual(result['file_count'], 2)
        self.assertEqual(result['directory_count'], 2)

    def test_unlisted_leaf_and_empty_directory_are_both_rejected(self):
        (self.target/'.git').mkdir()
        (self.target/'unexpected.txt').write_bytes(b'undeclared')
        with self.assertRaises(AssertionError):
            self.ns['namespace_files'](self.target, set())
        (self.target/'unexpected.txt').unlink()
        (self.target/'unlisted-empty').mkdir()
        with self.assertRaises(AssertionError):
            self.ns['namespace_files'](self.target, set())

    def test_exact_git_blob_raw_bytes_reject_line_ending_conversion(self):
        dst = self.target/'tracked.json'
        original = b'{"fixture":true}\r\n'
        dst.write_bytes(original)
        objects = {'tracked.json': {'mode': '100644', 'object': hashlib.sha1(b'blob '+str(len(original)).encode()+b'\0'+original).hexdigest()}}
        before, errors = self.ns['tracked_snapshot'](self.target, objects)
        self.assertEqual(errors, [])
        self.assertEqual(before['tracked.json']['sha256'], hashlib.sha256(original).hexdigest())
        dst.write_bytes(original.replace(b'\r\n', b'\n'))
        _, errors = self.ns['tracked_snapshot'](self.target, objects)
        self.assertEqual([row['path'] for row in errors], ['tracked.json'])


class ClosureCaptureFixtureTests(unittest.TestCase):
    """Real tiny child cleanup; only actual collector definitions are loaded."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='vast-d27-capture-fixture-')
        self.root = Path(self.temporary.name)
        self.output = self.root/'observation'
        self.output.mkdir()
        self.ns = {'Path': Path, 'os': os, 'stat': stat, 'time': time, 'hashlib': hashlib,
                   'json': json, 'selectors': selectors, 'signal': signal, 'subprocess': subprocess,
                   'ROOT': self.root, 'OUTPUT': self.output, 'MAX_CHANNEL': 4096,
                   'DEADLINE': time.monotonic()+5, 'HARD_DEADLINE': time.monotonic()+7, 'commands': []}
        helper = HELPER.with_name('capture_selected_host_closure_ext4_v1.py')
        wanted = {'clock', 'hard_clock', 'error', 'canonical_directory', 'facts', 'write', 'owner', 'command'}
        definitions = [node for node in ast.parse(helper.read_bytes()).body if isinstance(node, ast.FunctionDef) and node.name in wanted]
        self.assertEqual({node.name for node in definitions}, wanted)
        exec(compile(ast.Module(body=definitions, type_ignores=[]), str(helper), 'exec'), self.ns)

    def tearDown(self):
        self.temporary.cleanup()

    def argv(self, code):
        return [sys.executable, '-I', '-B', '-c', code]

    def assert_quiescent(self):
        row = self.ns['commands'][-1]
        self.assertIs(row['original_pid_absent'], True)
        self.assertIs(row['original_group_absent'], True)
        self.assertTrue((self.output/'fixture.terminal.v1.json').is_file())
        return row

    def test_original_small_child_success_has_actual_owner_and_bounded_raw_channels(self):
        result = self.ns['command'](self.argv('print("original tiny fixture")'), 'fixture')
        self.assertEqual(result['returncode'], 0)
        self.assertEqual((self.output/'fixture.stdout.raw').read_bytes(), b'original tiny fixture\n')
        self.assertGreater(result['owner']['startticks'], 0)
        self.assertEqual(result['owner']['uid'], os.getuid())
        self.assert_quiescent()

    def test_nonzero_original_child_preserves_failed_terminal(self):
        with self.assertRaises(AssertionError):
            self.ns['command'](self.argv('raise SystemExit(7)'), 'fixture')
        self.assertEqual(self.assert_quiescent()['returncode'], 7)

    def test_actual_channel_overflow_is_contained_and_failed(self):
        with self.assertRaises(AssertionError):
            self.ns['command'](self.argv('import os,time;os.write(1,b"x"*5000);time.sleep(30)'), 'fixture')
        row = self.assert_quiescent()
        self.assertIs(row['capture_exceeded'], True)
        self.assertLessEqual((self.output/'fixture.stdout.raw').stat().st_size, 4096)

    def test_actual_original_absolute_timeout_contains_child_without_reset(self):
        self.ns['DEADLINE'] = time.monotonic()+.1
        started = time.monotonic()
        with self.assertRaises(AssertionError):
            self.ns['command'](self.argv('import time;time.sleep(30)'), 'fixture')
        self.assertIs(self.assert_quiescent()['timed_out'], True)
        self.assertLess(time.monotonic()-started, 2)

    def test_actual_owner_observation_failure_still_contains_started_child(self):
        def refuse_owner(pid):
            raise OSError('fixture owner observation failure')
        self.ns['owner'] = refuse_owner
        with self.assertRaises(AssertionError):
            self.ns['command'](self.argv('import time;time.sleep(30)'), 'fixture')
        row = self.assert_quiescent()
        self.assertIsNone(row['owner'])
        self.assertEqual(row['errors'][0]['type'], 'OSError')

    def test_actual_launch_persistence_failure_still_contains_started_child(self):
        original_write = self.ns['write']
        def refuse_launch(name, value):
            if name.endswith('.launch.v1.json'):
                raise OSError('fixture launch persistence failure')
            return original_write(name, value)
        self.ns['write'] = refuse_launch
        with self.assertRaises(AssertionError):
            self.ns['command'](self.argv('import time;time.sleep(30)'), 'fixture')
        self.assertEqual(self.assert_quiescent()['errors'][0]['type'], 'OSError')

    def test_expired_original_cleanup_limit_cannot_publish_success(self):
        self.ns['HARD_DEADLINE'] = time.monotonic()-1
        with self.assertRaises(TimeoutError):
            self.ns['write']('unaccepted.json', {'status': 'captured'})
        self.assertFalse((self.output/'unaccepted.json').exists())


if __name__ == '__main__':
    unittest.main()
