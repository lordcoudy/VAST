from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import checkpoint_savant_sdk_runtime_v3 as worker
from checkpoint_savant_container_runtime_v3 import (
    SavantContainerRuntimeV3Error, validate_savant_native_stdio,
)

DEFAULT = b'max_fps_dur 8.33333e+06 min_fps_dur 2e+08\n'
CONFIGURED = b'max_fps_dur 1.66667e+06 min_fps_dur 1.66667e+06\n'


class SavantNativeStdioContractV3Tests(unittest.TestCase):
    def test_exact_six_and_twenty_four_worker_mux_notices_allow_interleaving(self):
        with tempfile.TemporaryDirectory() as name:
            stdout, stderr = Path(name) / 'out', Path(name) / 'err'
            stderr.write_bytes(b'')
            for count in (6, 24):
                with self.subTest(count=count):
                    stdout.write_bytes(DEFAULT * count + CONFIGURED * count)
                    audit = validate_savant_native_stdio(stdout, stderr, expected_worker_count=count)
                    self.assertEqual(audit['nvstreammux_default_timing_line_count'], count)
                    self.assertEqual(audit['nvstreammux_configured_timing_line_count'], count)
                    self.assertEqual(audit['stderr_bytes'], 0)

    def test_native_stdio_rejects_missing_extra_changed_and_unexpected_output(self):
        valid = DEFAULT * 6 + CONFIGURED * 6
        cases = {
            'missing_default': DEFAULT * 5 + CONFIGURED * 6,
            'missing_configured': DEFAULT * 6 + CONFIGURED * 5,
            'extra_default': valid + DEFAULT,
            'extra_configured': valid + CONFIGURED,
            'changed_rate': valid.replace(b'1.66667e+06', b'1.66668e+06', 1),
            'legacy_eos': b'nvstreammux: Successfully handled EOS for source_id=0\n' * 6,
            'worker_json': valid + b'{"artifact_kind":"vast_savant_sdk_worker_exit_v3"}\n',
            'warning': valid + b'WARNING: native failure\n',
            'blank_line': valid + b'\n',
            'non_ascii': valid + b'\xff\n',
        }
        with tempfile.TemporaryDirectory() as name:
            stdout, stderr = Path(name) / 'out', Path(name) / 'err'
            stderr.write_bytes(b'')
            for label, payload in cases.items():
                with self.subTest(case=label):
                    stdout.write_bytes(payload)
                    with self.assertRaises(SavantContainerRuntimeV3Error):
                        validate_savant_native_stdio(stdout, stderr, expected_worker_count=6)
            stdout.write_bytes(valid)
            stderr.write_bytes(b'native warning\n')
            with self.assertRaisesRegex(SavantContainerRuntimeV3Error, 'stderr'):
                validate_savant_native_stdio(stdout, stderr, expected_worker_count=6)

    def test_worker_entrypoint_preserves_receipt_without_duplicate_stdout(self):
        with tempfile.TemporaryDirectory() as name:
            output = Path(name)
            receipt = {'artifact_kind': 'vast_savant_sdk_worker_exit_v3', 'publication_ready': False}

            def complete(args):
                self.assertEqual(args.output_dir, output)
                (output / 'worker.runtime.json').write_text(json.dumps(receipt))
                return receipt

            stdout, stderr = io.StringIO(), io.StringIO()
            with mock.patch.object(worker, 'run_fd_worker', side_effect=complete) as run:
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    result = worker.main(self._arguments(output))
            self.assertEqual(result, 0)
            run.assert_called_once()
            self.assertEqual(json.loads((output / 'worker.runtime.json').read_text()), receipt)
            self.assertEqual(stdout.getvalue(), '')
            self.assertEqual(stderr.getvalue(), '')

    def test_worker_entrypoint_keeps_failure_on_stderr(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.object(worker, 'run_fd_worker', side_effect=worker.SavantSdkRuntimeV3Error('native callback failed')):
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                result = worker.main(self._arguments(Path('/unused')))
        self.assertEqual(result, 2)
        self.assertEqual(stdout.getvalue(), '')
        self.assertEqual(stderr.getvalue(), 'native callback failed\n')

    @staticmethod
    def _arguments(output):
        return ['run', '--codec', 'h264', '--topology-kind', 'independent_processes',
                '--stream-id', '0', '--branches', 'plate_number', '--arm-id', 'test',
                '--output-dir', str(output)]


if __name__ == '__main__':
    unittest.main()
