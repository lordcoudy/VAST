"""Controlled real-child lifetime observations, not a hosted-cause reproduction."""
import hashlib
import json
import os
from pathlib import Path
import select
import subprocess
import sys

ROOT = Path('/home/s-a-balashov/work/vast-current-source-ci-20261001-4cb9d831')
OUT = Path(sys.argv[1])
sys.path.insert(0, str(ROOT / 'tests'))
import test_publication_operational_process_custody_v1 as test
observer = test.observer
fixture = test.ProcessCustodyTests('test_genuine_original_process_launch_and_terminal_are_physically_bound')
fixture.setUp()
facts = []

def retain(label, capture):
    raw = Path(capture.receipt_descriptor['path']).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == capture.receipt_descriptor['sha256']
    path = OUT / (label + '.original-fixture-receipt.json')
    with path.open('xb') as output:
        output.write(raw)
    value = json.loads(raw)
    return {'retained_path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(),
            'status': value['status'], 'call_count': value['call_count'], 'body_error': value['body_error']}

def gated_capture(label, ready):
    capture = None
    process = None
    exception = None
    released = False
    token_returned = False
    try:
        with fixture.capture(output_dir=fixture.root / ('outputs/' + label)) as capture, test.original_engine_phase_v1('measurement'):
            program = "import sys;raise SystemExit(7)" if not ready else (
                "import sys;sys.stdout.buffer.write(b'READY\\n');sys.stdout.buffer.flush();"
                "gate=sys.stdin.buffer.read(1);"
                "sys.exit(77) if gate!=b'G' else print('original gated output')")
            argv = ['-c', program, '--mount', f"type=bind,src={fixture.root / 'inputs'},dst=/workspace/project,readonly",
                '--mount', f'type=bind,src={fixture.source},dst=/opt/vast/operational',
                '--operational-request-context', '/workspace/project/context.json',
                '--operational-output-dir', '/opt/vast/operational']
            process = subprocess.Popen([fixture.engine.proc_path, *argv], executable=fixture.engine.proc_path,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, pass_fds=(fixture.engine_fd,))
            try:
                readable, _, _ = select.select([process.stdout], [], [], 5)
                if not readable:
                    raise RuntimeError('original fixture readiness deadline')
                prefix = process.stdout.readline(7)
                if prefix != b'READY\n':
                    raise RuntimeError('original fixture failed before readiness')
                token = test.engine_process_started_v1(process, fixture.engine, fixture.socket_pin, argv)
                token_returned = token is not None
                assert token_returned and process.poll() is None
                process.stdin.write(b'G')
                process.stdin.flush()
                released = True
                stdout, stderr = process.communicate(timeout=5)
                stdout = prefix + stdout
                test.engine_process_terminal_v1(token, process, stdout, stderr, False, False, False)
                assert process.returncode == 0
                fixture.transfer()
            finally:
                if process.poll() is None:
                    process.kill()
                process.communicate(timeout=5)
    except BaseException as error:
        exception = {'type': type(error).__name__, 'message': str(error)}
    record = {'case': label, 'released_only_after_real_registration': released and token_returned,
              'registered': token_returned, 'error': exception, 'original_pid': process.pid,
              'returncode': process.returncode, 'original_process_absent': not Path(f'/proc/{process.pid}').exists(),
              'receipt': retain(label, capture)}
    if ready:
        assert exception is None and record['receipt']['status'] == 'complete_original_cli_capture'
        validated = fixture.validate(capture)
        record['actual_cold_process_validation'] = {'measurement_pid': validated['measurement']['launch']['child']['pid'],
            'returncode': validated['measurement']['terminal']['returncode'],
            'container_quiescence_verified': validated['receipt']['container_quiescence_verified']}
    else:
        assert exception == {'type': 'RuntimeError', 'message': 'original fixture failed before readiness'}
        assert not released and not token_returned and record['receipt']['call_count'] == 0
        assert record['receipt']['status'] == 'failed_original_cli_capture'
    facts.append(record)

try:
    capture = process = None
    failure = None
    try:
        with fixture.capture(output_dir=fixture.root / 'outputs/reaped') as capture, test.original_engine_phase_v1('image_inspect'), fixture.process("print('original fast output')") as (process, argv):
            process.wait(timeout=5)
            assert not Path(f'/proc/{process.pid}').exists()
            test.engine_process_started_v1(process, fixture.engine, fixture.socket_pin, argv)
            raise AssertionError('reaped original process was accepted')
    except FileNotFoundError as error:
        failure = {'type': type(error).__name__, 'errno': error.errno, 'message': str(error)}
    assert failure is not None
    facts.append({'case': 'genuine_child_reaped_before_registration', 'error': failure,
        'original_pid': process.pid, 'returncode': process.returncode,
        'original_process_absent': not Path(f'/proc/{process.pid}').exists(), 'receipt': retain('reaped', capture)})
    gated_capture('gated-positive', True)
    gated_capture('gated-before-ready-failure', False)
finally:
    fixture.doCleanups()
    with (OUT / 'original-lifecycle-probe.v1.json').open('xb') as output:
        output.write((json.dumps({'cases': facts,
            'limitations': ['The original unchanged local capacity unit passed; hosted first swallowed ValueError is unknown.',
                'A reaped child is deliberately refused with FileNotFoundError, not the original hosted swallowed ValueError.',
                'Unreaped zombies remain supported by the production observer and the existing unchanged intentional-zombie unit.',
                'Readiness is a unit-fixture lifecycle precondition, never a fabricated production identity or hardware grant.',
                'No production/test source was changed by this controlled probe.']}, sort_keys=True, indent=2) + '\n').encode())
print('THREE_GENUINE_CONTROLLED_LIFECYCLE_CASES_PASSED_NO_HOSTED_CAUSE_CLAIM')
