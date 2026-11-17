"""Capture real-config-loader regression in isolated overlays, not campaign evidence."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import stat

ROOT = Path('/mnt/c/Users/s-a-balashov/.codex/worktrees/fix-accepted-policy-preprocessing/VAST')
SOURCE = Path('/home/s-a-balashov/work/vast-accepted-policy-repair-20261011a-source-65c9fa91e2c396265183ec47cb090629ccdd174a')
BASE = Path('/mnt/e/STUDY/VAST/tmp/host-cache-cleanup-20261012/guardian-config-tdd-01')
OVERLAYS = Path('/var/tmp/vast-guardian-config-tdd-20261013a')
PYTHON = '/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python'
TEST = 'tests/test_publication_guardian_accepted_policy_preprocessing_contract_v1.py'
GUARDIAN = 'scripts/publication_guardian_accepted_policy_preprocessing_contract_v1.py'
OLD_GUARDIAN = '3b649aea69120fbf3968a55802ac6ed9695625bdfa2c9f729b058dc7b04283a1'
UNCHANGED = {
    'scripts/publication_policy_qualification.py': 'f4478804491922c3e25ab414ba8f000c1964b46633f9dfb3a5bc87212748dbde',
    'scripts/publication_policy_qualification_pilot_validation_v2.py': '48fbc62494cdc40bd5f925cee6ff16dad02269feacf1803d263a9d165523f246',
}
TARGET = 'tests.test_publication_guardian_accepted_policy_preprocessing_contract_v1'
RED_TARGET = TARGET + '.AcceptedPolicyGuardianPreprocessingContractV1Tests.test_default_execution_config_loader_materializes_and_cold_loads_raw_config'


def sha(path):
    plain(path, directory=False)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def plain(path, *, directory):
    if not path.is_absolute() or path.resolve(strict=True) != path or path.is_symlink():
        raise RuntimeError('noncanonical or linked path: ' + str(path))
    mode = path.stat().st_mode
    if not (stat.S_ISDIR(mode) if directory else stat.S_ISREG(mode)):
        raise RuntimeError('nonordinary path: ' + str(path))
    for parent in path.parents:
        if parent.is_symlink() or not stat.S_ISDIR(parent.stat().st_mode):
            raise RuntimeError('nonordinary or linked ancestor: ' + str(parent))


def fresh_directory(path):
    plain(path.parent, directory=True)
    if path.exists() or path.is_symlink():
        raise RuntimeError('exclusive directory already exists: ' + str(path))
    path.mkdir(exist_ok=False)
    plain(path, directory=True)


def fresh_json(path, value):
    plain(path.parent, directory=True)
    with path.open('x', encoding='ascii') as stream:
        json.dump(value, stream, sort_keys=True, indent=2)
        stream.write('\n')


def snapshot():
    result = {
        'managed_files': {name: sha(ROOT / name) for name in (TEST, GUARDIAN)},
        'frozen_guardian': sha(SOURCE / GUARDIAN),
        'managed_locked': {name: sha(ROOT / name) for name in UNCHANGED},
        'frozen_locked': {name: sha(SOURCE / name) for name in UNCHANGED},
        'sidecar_managed': sha(ROOT / 'scripts/checkpoint_gstreamer_analytics_sidecar.py'),
        'sidecar_frozen': sha(SOURCE / 'scripts/checkpoint_gstreamer_analytics_sidecar.py'),
        'capturer_sha256': sha(Path(__file__)),
    }
    if (result['frozen_guardian'] != OLD_GUARDIAN
            or result['managed_locked'] != UNCHANGED or result['frozen_locked'] != UNCHANGED
            or result['sidecar_managed'] != result['sidecar_frozen']):
        raise RuntimeError('frozen guardian or unchanged stock/F5/default sidecar differs')
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--phase', choices=('red', 'green'), required=True)
    args = parser.parse_args()
    if (sys.executable != PYTHON or sys.version_info[:3] != (3, 12, 3)
            or sys.flags.optimize != 0 or os.getuid() != 1000 or os.getgid() != 1000
            or os.environ.get('HOME') != '/home/s-a-balashov'
            or os.environ.get('TMPDIR') != '/var/tmp'):
        raise RuntimeError('canonical ordinary unoptimized runtime required')
    before = snapshot()
    if args.phase == 'red':
        if before['managed_files'][GUARDIAN] != OLD_GUARDIAN:
            raise RuntimeError('RED requires unchanged current guardian')
        fresh_directory(BASE)
        fresh_directory(OVERLAYS)
    else:
        plain(BASE, directory=True)
        plain(OVERLAYS, directory=True)
        plain(BASE / 'red/result.v1.json', directory=False)
        red = json.loads((BASE / 'red/result.v1.json').read_bytes())
        if (red['original_exit_code'] != 1 or not red['source_hashes_unchanged']
                or not red['overlay_bytes_unchanged'] or red['capture_errors']):
            raise RuntimeError('retained natural RED1 with unchanged sources required')
        if sha(BASE / 'red/stderr.raw') != red['stderr']['sha256']:
            raise RuntimeError('original RED stderr physical hash differs')
        red_stderr = (BASE / 'red/stderr.raw').read_text(encoding='utf-8')
        if not all(value in red_stderr for value in (
                RED_TARGET.rsplit('.', 1)[1], 'Ran 1 test', 'FAILED (errors=1)',
                'AcceptedPolicyGuardianPreprocessingContractV1Error: execution config content identity drifted from v4 parity authority')):
            raise RuntimeError('RED must be the actual one-test guardian config boundary')
        plain(BASE / 'red/source-hashes.before.json', directory=False)
        red_before = json.loads((BASE / 'red/source-hashes.before.json').read_bytes())
        if red_before['managed_files'][TEST] != before['managed_files'][TEST]:
            raise RuntimeError('GREEN test bytes differ from the retained RED regression')
        if before['managed_files'][GUARDIAN] == OLD_GUARDIAN:
            raise RuntimeError('GREEN requires an explicit production correction')
    directory = BASE / args.phase
    overlay = OVERLAYS / args.phase
    fresh_directory(directory)
    fresh_directory(overlay)
    copied = {}
    for name in (TEST, GUARDIAN):
        raw = (ROOT / name).read_bytes()
        expected = before['managed_files'][name]
        if hashlib.sha256(raw).hexdigest() != expected:
            raise RuntimeError('authored source drift before copy')
        destination = overlay / name
        if not destination.parent.exists():
            fresh_directory(destination.parent)
        plain(destination.parent, directory=True)
        with destination.open('xb') as stream:
            stream.write(raw)
        copied[name] = expected
    bootstrap = '\n'.join((
        'import importlib,json,sys',
        'from pathlib import Path',
        'sys.path[:0]=' + repr([str(overlay / 'scripts'), str(SOURCE), str(SOURCE / 'scripts')]),
        'import tests',
        'tests.__path__=[' + repr(str(overlay / 'tests')) + ',*tests.__path__]',
        'import publication_guardian_accepted_policy_preprocessing_contract_v1 as guardian',
        'assert Path(guardian.__file__).resolve() == Path(' + repr(str(overlay / GUARDIAN)) + ').resolve()',
        'module=importlib.import_module(' + repr(TARGET) + ')',
        'assert Path(module.__file__).resolve() == Path(' + repr(str(overlay / TEST)) + ').resolve()',
        "print(json.dumps({'guardian_path':guardian.__file__,'test_path':module.__file__}),flush=True)",
        'import unittest',
        'unittest.main(module=None,argv=' + repr(['unittest', RED_TARGET if args.phase == 'red' else TARGET, '-v']) + ')',
    ))
    command = [PYTHON, '-B', '-c', bootstrap]
    started = datetime.now(timezone.utc).isoformat()
    fresh_json(directory / 'command.v1.json', {
        'argv': command, 'cwd': str(overlay), 'started_utc': started,
        'uid': os.getuid(), 'gid': os.getgid(), 'python_version': sys.version,
        'dependency_source_commit': '65c9fa91e2c396265183ec47cb090629ccdd174a',
        'no_complete_consumer_or_campaign': True,
        'real_config_loader_with_explicit_upstream_fixture_stubs': True,
    })
    fresh_json(directory / 'source-hashes.before.json', before)
    child = None
    original_rc = None
    errors = []
    try:
        with (directory / 'stdout.raw').open('xb') as stdout, (directory / 'stderr.raw').open('xb') as stderr:
            child = subprocess.Popen(command, cwd=overlay, stdout=stdout, stderr=stderr, start_new_session=True)
            while original_rc is None:
                try:
                    original_rc = child.wait()
                except BaseException as error:
                    errors.append({'phase': 'same_child_wait', 'type': type(error).__name__, 'message': str(error)})
    except BaseException as error:
        errors.append({'phase': 'launch_or_stream_close', 'type': type(error).__name__, 'message': str(error)})
    finally:
        while child is not None and original_rc is None:
            try:
                original_rc = child.wait()
            except BaseException as error:
                errors.append({'phase': 'same_child_final_wait', 'type': type(error).__name__, 'message': str(error)})
    after = None
    overlay_unchanged = False
    try:
        after = snapshot()
        fresh_json(directory / 'source-hashes.after.json', after)
    except BaseException as error:
        errors.append({'phase': 'source_after', 'type': type(error).__name__, 'message': str(error)})
    try:
        overlay_unchanged = all(sha(overlay / name) == value for name, value in copied.items())
    except BaseException as error:
        errors.append({'phase': 'overlay_after', 'type': type(error).__name__, 'message': str(error)})
    captured = {}
    for name in ('stdout', 'stderr'):
        try:
            path = directory / (name + '.raw')
            captured[name] = {'bytes': path.stat().st_size, 'sha256': sha(path)}
        except BaseException as error:
            captured[name] = None
            errors.append({'phase': name + '_after', 'type': type(error).__name__, 'message': str(error)})
    result = {
        'phase': args.phase, 'started_utc': started,
        'finished_utc': datetime.now(timezone.utc).isoformat(), 'original_exit_code': original_rc,
        'source_hashes_unchanged': after is not None and before == after,
        'overlay_bytes_unchanged': overlay_unchanged, 'capture_errors': errors,
        'original_child_started': child is not None, 'original_child_naturally_closed': original_rc is not None,
        'stdout': captured['stdout'], 'stderr': captured['stderr'],
        'no_complete_consumer_or_campaign': True,
    }
    fresh_json(directory / 'result.v1.json', result)
    print(json.dumps(result, sort_keys=True), flush=True)
    if errors or after is None or before != after or not overlay_unchanged or original_rc is None:
        return 1
    return original_rc


if __name__ == '__main__':
    sys.exit(main())
