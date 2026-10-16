"""Fixed task2.10 host execution of the authenticated C1 retained ELF.

This component never grants campaign authority. Its test seams do not supply
physical qualification. All outputs and failed prefixes remain retained.
The raw receipt remains in its single ext4 location. The later 4KiB allowance
is only for one small summary/hash-index form, never a duplicate full receipt.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import signal
import stat
import struct
import subprocess
import time
from typing import Any

from tests.fixtures import accepted_policy_fixture_compiler_component_v1 as recipe
from tests.fixtures import accepted_policy_fixture_compiler_v1 as compiler

ELF_LIMIT = 524288
CONTROL_LIMIT = 524288
OTHER_CONTROL_LIMIT = 98304
RECEIPT_LIMIT = 24576
LATER_INDEX_LIMIT = 4096
LATER_INDEX_ALLOCATION = LATER_INDEX_LIMIT + 256
AGGREGATE_LIMIT = 2097152
CHILD_FILE_LIMIT = 1048576
PROOF_LIMIT = 1024
CHANNEL_LIMIT = 4096
DMESG_LIMIT = 196608
CRASH_LIMIT = 16384
DEADLINE_NS = 10000000000
CRASH_DIRECTORY = Path('/mnt/c/Users/s-a-balashov/AppData/Local/Temp/wsl-crashes')


class StageDRefusal(RuntimeError):
    def __init__(self, cause: str, facts: Any = None):
        super().__init__(cause)
        self.cause, self.facts = cause, facts


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _is_sha(value: Any) -> bool:
    return type(value) is str and re.fullmatch('[0-9a-f]{64}', value) is not None


def _unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('duplicate field')
        value[key] = item
    return value


def validate_preexec_proof_v1(raw: bytes, pid: int) -> dict[str, Any]:
    """Require the actual child identity and exact getrlimit byte values."""
    try:
        if type(raw) is not bytes or not 1 <= len(raw) <= PROOF_LIMIT:
            raise ValueError('proof bound')
        value = json.loads(raw.decode('ascii'), object_pairs_hook=_unique,
                           parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
        fields = {'pid', 'uid', 'euid', 'gid', 'egid', 'pgid', 'sid', 'core', 'fsize'}
        if type(value) is not dict or set(value) != fields or recipe.canonical_json_v1(value) + b'\n' != raw:
            raise ValueError('proof shape')
        if (type(pid) is not int or not 1 <= pid <= 4194304 or
                any(type(value[key]) is not int for key in fields - {'core', 'fsize'}) or
                any(value[key] != pid for key in ('pid', 'pgid', 'sid')) or
                any(value[key] != 1000 for key in ('uid', 'euid', 'gid', 'egid'))):
            raise ValueError('proof identity')
        for key, expected in (('core', [1, 1]), ('fsize', [CHILD_FILE_LIMIT, CHILD_FILE_LIMIT])):
            if type(value[key]) is not list or len(value[key]) != 2 or any(type(n) is not int for n in value[key]) or value[key] != expected:
                raise ValueError('proof limits')
        return value
    except (ValueError, TypeError, UnicodeError, RecursionError) as error:
        raise StageDRefusal('d_preexec_proof') from error


def phase_limits_v1(absolute_deadline_ns: int) -> dict[str, int]:
    if type(absolute_deadline_ns) is not int or absolute_deadline_ns <= 3000000000:
        raise StageDRefusal('d_deadline')
    return {'work': absolute_deadline_ns - 3000000000,
            'term': absolute_deadline_ns - 2000000000,
            'kill': absolute_deadline_ns - 1000000000,
            'final': absolute_deadline_ns}


def child_environment_v1(directory: str) -> dict[str, str]:
    return {'PATH': '/usr/bin:/bin', 'LANG': 'C', 'LC_ALL': 'C',
            'HOME': directory, 'TMPDIR': directory, 'TMP': directory, 'TEMP': directory}


def evaluate_d_v1(value: Any) -> dict[str, Any]:
    """Compare complete observed facts; a valid proof never substitutes for exit."""
    failures = []
    def require(ok, code):
        if not ok and code not in failures:
            failures.append(code)
    if type(value) is not dict:
        return {'passed': False, 'physical_acceptance': False,
                'campaign_authority': False, 'failures': ['d_result_shape']}
    require(type(value.get('schema_version')) is int and value['schema_version'] == 1 and value.get('stage') == 'D', 'd_result_shape')
    require(value.get('source_sha256') == recipe.SOURCE_SHA256['c1'] and
            value.get('command_sha256') == recipe.D_COMMAND_SHA256 and
            value.get('reply_sha256') == recipe.D_REPLY_SHA256, 'd_protocol_binding')
    copied = value.get('copy') if type(value.get('copy')) is dict else {}
    child = value.get('child') if type(value.get('child')) is dict else {}
    state = value.get('state') if type(value.get('state')) is dict else {}
    require(type(copied.get('size_bytes')) is int and 0 < copied['size_bytes'] <= ELF_LIMIT and
            _is_sha(copied.get('sha256')) and copied.get('source_sha256') == copied.get('sha256') and
            type(copied.get('mode')) is int and copied['mode'] == 0o700 and
            type(copied.get('nlink')) is int and copied['nlink'] == 1 and
            copied.get('persisted') is True and copied.get('closed') is True, 'd_copy_binding')
    try:
        proof_raw = child.get('proof')
        proof_bounded = type(proof_raw) is str and 1 <= len(proof_raw) <= PROOF_LIMIT
        require(proof_bounded, 'd_preexec_proof')
        if proof_bounded:
            validate_preexec_proof_v1(proof_raw.encode('ascii'), child.get('pid'))
    except (StageDRefusal, UnicodeError):
        require(False, 'd_preexec_proof')
    require(child.get('identity_verified') is True and child.get('proof_eof') is True, 'd_child_identity')
    require(type(child.get('returncode')) is int and child['returncode'] == 0 and
            type(child.get('wait_status')) is int and child['wait_status'] == 0 and
            child.get('reaped') is True, 'd_child_status')
    require(child.get('stdout') == recipe.D_REPLY.decode('ascii') and child.get('stderr') == '' and
            child.get('stdout_eof') is True and child.get('stderr_eof') is True and
            type(child.get('stdin_written_bytes')) is int and child['stdin_written_bytes'] == len(recipe.D_COMMAND) and
            child.get('stdin_closed') is True, 'd_channels')
    require(child.get('forced') is False and child.get('unknown_closure') is False and
            child.get('late') is False and child.get('signals') == [] and
            child.get('capture_persisted') is True and child.get('capture_closed') is True, 'd_child_closure')
    require(state.get('bytes') == 'ok\n' and type(state.get('size_bytes')) is int and state['size_bytes'] == 3 and
            type(state.get('nlink')) is int and state['nlink'] == 1 and state.get('regular') is True, 'd_state')
    for name in ('boot_unchanged', 'dmesg_unchanged', 'crashes_unchanged', 'identity_verified',
                 'floors_preserved', 'within_deadline'):
        require(value.get(name) is True, 'd_' + name)
    require(type(value.get('control_bytes')) is int and 0 <= value['control_bytes'] <= CONTROL_LIMIT and
            type(value.get('aggregate_reserved_bytes')) is int and value['aggregate_reserved_bytes'] == AGGREGATE_LIMIT,
            'd_allocation')
    require(value.get('causes') == [], 'd_causes')
    require(type(value.get('controlled')) is bool, 'd_controlled_marker')
    require(value.get('handlers_restored') is True, 'd_handlers_restored')
    require(all(type(value.get(key)) is int for key in ('started_ns', 'absolute_deadline_ns', 'finished_ns')) and
            value['started_ns'] >= 0 and value['absolute_deadline_ns'] == value['started_ns'] + DEADLINE_NS and
            value['started_ns'] <= value['finished_ns'] < value['absolute_deadline_ns'], 'd_actual_deadline')
    descriptor = value.get('receipt_descriptor') if type(value.get('receipt_descriptor')) is dict else {}
    ledger = value.get('ledger_after_receipt') if type(value.get('ledger_after_receipt')) is dict else {}
    finalization = (value.get('receipt_persisted') is True and
        descriptor.get('persisted') is True and descriptor.get('closed') is True and
        descriptor.get('extent_unknown') is False and _is_sha(descriptor.get('sha256')) and
        type(descriptor.get('size_bytes')) is int and 0 < descriptor['size_bytes'] <= RECEIPT_LIMIT and
        all(type(ledger.get(key)) is int for key in ('remaining_before', 'charge_bytes', 'remaining_after')) and
        0 <= ledger['charge_bytes'] <= ledger['remaining_before'] <= 536870912 and
        ledger['remaining_after'] == ledger['remaining_before'] - ledger['charge_bytes'] and
        type(value.get('aggregate_accounted_bytes')) is int and
        0 <= value['aggregate_accounted_bytes'] <= AGGREGATE_LIMIT and
        _floors_v1(value.get('final_measurement_after_receipt'), 0))
    return {'passed': not failures, 'finalization_complete': finalization,
            'physical_acceptance': not failures and finalization and value.get('controlled') is False,
            'campaign_authority': False, 'failures': failures}


def _check_time(clock, deadline):
    now = clock()
    if type(now) is not int or now >= deadline:
        raise StageDRefusal('d_deadline')
    return now


def _write_original_v1(path, raw, cap, *, clock, deadline):
    if type(raw) is not bytes or not 0 <= len(raw) <= cap:
        raise StageDRefusal('d_original_bound')
    facts = {'path': str(path), 'size_bytes': None, 'sha256': None,
             'written_bytes': 0, 'persisted_bytes': 0, 'extent_unknown': False,
             'persisted': False, 'closed': False, 'causes': [],
             'flush_completed': False, 'fsync_completed': False, 'close_attempted': False}
    fd, failure, operation = None, None, 'clock'
    try:
        _check_time(clock, deadline)
        operation = 'open'
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        for offset in range(0, len(raw), 65536):
            operation = 'clock'
            _check_time(clock, deadline)
            block = raw[offset:offset + 65536]
            operation = 'write'
            try:
                written = os.write(fd, block)
            except OSError:
                facts['extent_unknown'] = True
                raise
            if type(written) is not int or not 0 <= written <= len(block):
                facts['extent_unknown'] = True
                raise StageDRefusal('d_write_contract')
            facts['written_bytes'] += written
            if written != len(block):
                raise StageDRefusal('d_short_write')
        facts['flush_completed'] = True  # unbuffered os.write has no user buffer
        operation = 'fsync'
        os.fsync(fd)
        facts['fsync_completed'] = True
        facts['persisted_bytes'] = facts['written_bytes']
        facts['persisted'] = True
        operation = 'clock'
        _check_time(clock, deadline)
    except BaseException as error:
        failure = error
        facts['causes'].append(error.cause if isinstance(error, StageDRefusal)
                               else 'd_original_' + operation + '_' + type(error).__name__)
    finally:
        if fd is not None:
            facts['close_attempted'] = True
            try:
                os.close(fd)
                facts['closed'] = True
            except OSError as error:
                facts['causes'].append('d_original_close_' + type(error).__name__)
                failure = failure or error
    if failure is not None:
        facts['confirmed_prefix_sha256'] = _sha(raw[:facts['written_bytes']])
        raise StageDRefusal(facts['causes'][0], facts) from failure
    try:
        _check_time(clock, deadline)
    except StageDRefusal as error:
        facts['causes'].append(error.cause)
        raise StageDRefusal(error.cause, facts) from error
    facts.update(size_bytes=len(raw), sha256=_sha(raw))
    return facts


def _read_bound_v1(path, cap):
    path = Path(path)
    if path.resolve(strict=True) != path:
        raise StageDRefusal('d_input_path')
    with path.open('rb', buffering=0) as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or not 0 <= before.st_size <= cap:
            raise StageDRefusal('d_input_bound')
        raw = stream.read(cap + 1)
        after = os.fstat(stream.fileno())
        fields = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
        if len(raw) != before.st_size or any(getattr(before, k) != getattr(after, k) for k in fields):
            raise StageDRefusal('d_input_drift')
    return raw


def _elf_interpreter_v1(raw):
    if (len(raw) < 64 or raw[:7] != b'\x7fELF\x02\x01\x01' or
            int.from_bytes(raw[16:18], 'little') not in (2, 3) or
            int.from_bytes(raw[18:20], 'little') != 62 or int.from_bytes(raw[20:24], 'little') != 1):
        raise StageDRefusal('d_elf_abi')
    offset = int.from_bytes(raw[32:40], 'little')
    size = int.from_bytes(raw[54:56], 'little')
    count = int.from_bytes(raw[56:58], 'little')
    if not 64 <= offset <= len(raw) or size != 56 or not 1 <= count <= 128 or offset + count * size > len(raw):
        raise StageDRefusal('d_elf_headers')
    paths = []
    for index in range(count):
        header = raw[offset + index * size:offset + (index + 1) * size]
        if int.from_bytes(header[:4], 'little') == 3:  # PT_INTERP
            begin = int.from_bytes(header[8:16], 'little')
            length = int.from_bytes(header[32:40], 'little')
            if not 1 < length <= 4096 or begin + length > len(raw):
                raise StageDRefusal('d_elf_interpreter')
            value = raw[begin:begin + length]
            if value != b'/lib64/ld-linux-x86-64.so.2\0':
                raise StageDRefusal('d_elf_interpreter')
            paths.append(value[:-1].decode('ascii'))
    if len(paths) != 1:
        raise StageDRefusal('d_elf_interpreter')
    return paths[0]


def _copy_c1_elf_v1(root, binding, destination, *, clock, deadline):
    expected = root / 'outputs/C1/engine.compiler-originals/engine.unaccepted'
    if Path(binding.get('elf_path', '')) != expected or binding.get('source_sha256') != recipe.SOURCE_SHA256['c1']:
        raise StageDRefusal('d_c1_binding')
    _check_time(clock, deadline)
    raw = _read_bound_v1(expected, ELF_LIMIT)
    if type(binding.get('elf_size_bytes')) is not int or len(raw) != binding['elf_size_bytes'] or _sha(raw) != binding.get('elf_sha256'):
        raise StageDRefusal('d_c1_elf_hash')
    interpreter = _elf_interpreter_v1(raw)
    result = _write_original_v1(destination, raw, ELF_LIMIT, clock=clock, deadline=deadline)
    destination.chmod(0o700)
    compiler._compiler_directory_sync_v1(destination.parent)
    actual = destination.lstat()
    if not stat.S_ISREG(actual.st_mode) or actual.st_nlink != 1 or stat.S_IMODE(actual.st_mode) != 0o700 or _read_bound_v1(destination, ELF_LIMIT) != raw:
        raise StageDRefusal('d_copy_readback')
    _check_time(clock, deadline)
    return dict(result, source_sha256=_sha(raw), mode=stat.S_IMODE(actual.st_mode),
                nlink=actual.st_nlink, interpreter=interpreter)


def _crash_listing_v1(directory=CRASH_DIRECTORY):
    rows, count = [], 0
    with os.scandir(directory) as entries:
        for entry in entries:
            count += 1
            if count > 16384:
                raise StageDRefusal('d_crash_inventory_bound')
            if not entry.name.startswith('wsl-crash-'):
                continue
            if len(entry.name) > 512 or entry.is_symlink():
                raise StageDRefusal('d_crash_inventory_shape')
            value = entry.stat(follow_symlinks=False)
            if not stat.S_ISREG(value.st_mode) or len(rows) >= 64:
                raise StageDRefusal('d_crash_inventory_shape')
            rows.append([entry.name, value.st_size, value.st_mtime_ns])
    rows.sort()
    if compiler._json_bound(rows) > CRASH_LIMIT:
        raise StageDRefusal('d_crash_inventory_bound')
    raw = recipe.canonical_json_v1(rows)
    if len(raw) > CRASH_LIMIT:
        raise StageDRefusal('d_crash_inventory_bound')
    return raw


def _controls_usage_v1(directory):
    """Inclusive allocation, counting directory/inode reserve and every file."""
    categories = {'dmesg': 0, 'crashes': 0, 'other': 0}
    files = 0
    for parent, dirs, names in os.walk(directory, followlinks=False):
        if len(dirs) + len(names) > 256:
            raise StageDRefusal('d_control_inventory')
        categories['other'] += 4096
        for name in dirs:
            if Path(parent, name).is_symlink():
                raise StageDRefusal('d_control_symlink')
        for name in names:
            files += 1
            if files > 128:
                raise StageDRefusal('d_control_inventory')
            path = Path(parent, name)
            row = path.lstat()
            if not stat.S_ISREG(row.st_mode) or row.st_nlink != 1:
                raise StageDRefusal('d_control_alias')
            allocated = max(((row.st_size + 4095) // 4096) * 4096, getattr(row, 'st_blocks', 0) * 512)
            relative = path.relative_to(directory).as_posix()
            category = ('dmesg' if relative in ('before/dmesg.stdout.original', 'after/dmesg.stdout.original')
                        else 'crashes' if relative in ('before/crashes.original.json', 'after/crashes.original.json')
                        else 'other')
            categories[category] += allocated
            categories['other'] += 256  # conservative inode/allocation metadata reserve
    if categories['dmesg'] > 2 * DMESG_LIMIT or categories['crashes'] > 2 * CRASH_LIMIT or categories['other'] > OTHER_CONTROL_LIMIT:
        raise StageDRefusal('d_control_allocation', categories)
    total = sum(categories.values())
    if total > CONTROL_LIMIT:
        raise StageDRefusal('d_control_allocation', categories)
    return dict(categories, total=total, files=files)


def _info_identity_v1(info, cids):
    from tests.fixtures.accepted_policy_fixture_compiler_gate2_c_v1 import EXPECTED
    if (type(info) is not dict or type(cids) is not list or len(cids) != 9 or len(set(cids)) != 9 or
            any(type(cid) is not str or re.fullmatch('[0-9a-f]{64}', cid) is None for cid in cids)):
        raise StageDRefusal('d_engine_identity')
    expected = {'ID': EXPECTED['engine_id'], 'ServerVersion': EXPECTED['server_version'],
                'KernelVersion': EXPECTED['kernel'], 'Driver': 'overlayfs',
                'CgroupDriver': 'systemd', 'CgroupVersion': '2',
                'DockerRootDir': '/var/lib/docker', 'SecurityOptions': EXPECTED['security_options']}
    if (any(info.get(key) != value for key, value in expected.items()) or
            _sha(recipe.canonical_json_v1(info.get('Runtimes'))) != EXPECTED['runtimes_sha256'] or
            any(type(info.get(key)) is not int or info[key] != number
                for key, number in (('Containers', 9), ('ContainersRunning', 0), ('ContainersPaused', 0)))):
        raise StageDRefusal('d_engine_identity')
    return {'engine_id': info['ID'], 'running': 0, 'paused': 0, 'containers': 9,
            'cids_from_authenticated_c6_chain': cids}


def _validate_child_captures_v1(child, directory):
    if type(child) is not dict or type(child.get('records')) is not dict:
        raise StageDRefusal('d_child_capture_shape')
    total = 0
    for name, key, limit in (('stdout', 'stdout', CHANNEL_LIMIT),
                              ('stderr', 'stderr', CHANNEL_LIMIT),
                              ('preexec', 'proof', PROOF_LIMIT)):
        row = child['records'].get(name)
        path = directory / ('d.' + name + '.original')
        if (type(row) is not dict or row.get('path') != str(path) or row.get('persisted') is not True or
                row.get('closed') is not True or row.get('write_extent_unknown') is not False):
            raise StageDRefusal('d_child_capture_binding')
        raw = _read_bound_v1(path, limit)
        if (any(type(row.get(field)) is not int or row[field] != len(raw)
                for field in ('size_bytes', 'observed_bytes', 'written_bytes')) or
                row.get('sha256') != _sha(raw) or type(child.get(key)) is not str or len(child[key]) > limit or
                child[key].encode('ascii') != raw):
            raise StageDRefusal('d_child_capture_binding')
        if name != 'preexec':
            total += len(raw)
    if total > CHANNEL_LIMIT:
        raise StageDRefusal('d_child_channel_cap')


def _allocated_v1(path):
    row = path.lstat()
    if not stat.S_ISREG(row.st_mode) or row.st_nlink != 1:
        raise StageDRefusal('d_allocation_alias')
    return max(((row.st_size + 4095) // 4096) * 4096, row.st_blocks * 512) + 256


def _floor_metrics_v1(root):
    def free(path):
        row = os.statvfs(path)
        return row.f_bavail * row.f_frsize
    row = os.statvfs('/')
    if type(row.f_frsize) is not int or row.f_frsize != 4096:
        raise StageDRefusal('d_ext4_rounding')
    if root.stat().st_dev != Path('/').stat().st_dev:
        raise StageDRefusal('d_project_not_ext4_root')
    return {'c_free_bytes': free('/mnt/c'), 'project_free_bytes': free(root),
            'ext4_used_bytes': (row.f_blocks - row.f_bfree) * row.f_frsize}


def _floors_v1(metrics, reserve):
    return (type(metrics) is dict and
            all(type(metrics.get(key)) is int for key in ('c_free_bytes', 'project_free_bytes', 'ext4_used_bytes')) and
            metrics['c_free_bytes'] >= recipe.C_BYTES + recipe.ADDITIONAL_DISK_UPPER_BYTES + reserve and
            metrics['project_free_bytes'] >= recipe.PROJECT_BYTES + reserve)


class _DInfoClientV1(compiler._DockerClientV1):
    """One read-only /info observation, below the unchanged owner ceiling."""
    LIMIT = ORDINARY_LIMIT = 32768  # 16KiB total wire, charged2x; owner unchanged
    RPC_LIMIT = 1

    def _observe_endpoint(self):
        # Same three fixed observed rows; JSON-native representation lets the
        # enclosing D receipt apply its pre-encoding scalar/container bound.
        return [list(row) for row in super()._observe_endpoint()]

    def request(self, method, path, body=None, **kwargs):
        if method != 'GET' or path != '/info' or body is not None or kwargs.get('upgrade') or kwargs.get('cleanup'):
            raise self._error('d_info_inventory')
        return super().request(method, path, body, **kwargs)


# Fixed outstanding physical liabilities, including4KiB allocation rounding,
# inode reserve and one later4KiB Git/index form. Native guard metadata is
# enclosed once in d.result; only its bounded raw streams are separate files.
_D_TASKS = (
    ('before-dmesg', 512, DMESG_LIMIT, 0),
    ('before-journal', 4608, 0, 0),
    ('before-gpu', 4608, 0, 0),
    ('before-crashes', 256, 0, CRASH_LIMIT),
    ('child', 13056, 0, 0),
    ('after-dmesg', 512, DMESG_LIMIT, 0),
    ('after-journal', 4608, 0, 0),
    ('after-gpu', 4608, 0, 0),
    ('after-crashes', 256, 0, CRASH_LIMIT),
    ('receipt', RECEIPT_LIMIT + 256 + LATER_INDEX_ALLOCATION, 0, 0),
)


def _reserve_controls_v1(controls, task, *, identity=False):
    usage = _controls_usage_v1(controls)
    names = [row[0] for row in _D_TASKS]
    if task not in names:
        raise StageDRefusal('d_control_task')
    pending = _D_TASKS[names.index(task):]
    proposed = {'other': usage['other'] + sum(row[1] for row in pending) + (20992 if identity else 0),
                'dmesg': usage['dmesg'] + sum(row[2] for row in pending),
                'crashes': usage['crashes'] + sum(row[3] for row in pending)}
    if (proposed['other'] > OTHER_CONTROL_LIMIT or proposed['dmesg'] > 2 * DMESG_LIMIT or
            proposed['crashes'] > 2 * CRASH_LIMIT or sum(proposed.values()) > CONTROL_LIMIT):
        raise StageDRefusal('d_control_reserve', proposed)
    return proposed


def _reserve_aggregate_v1(controls, elf_size):
    """Reserve every rounded D liability before copying or executing the ELF."""
    if type(elf_size) is not int or not 0 < elf_size <= ELF_LIMIT:
        raise StageDRefusal('d_c1_binding')
    control_quote = _reserve_controls_v1(controls, 'child')
    quote = {'controls': control_quote, 'parent_directory_bytes': 4096,
             'elf_bytes': ((elf_size + 4095) // 4096) * 4096 + 256,
             'child_file_bytes': CHILD_FILE_LIMIT + 256}
    quote['aggregate_bytes'] = sum(control_quote.values()) + sum(quote[key] for key in
        ('parent_directory_bytes', 'elf_bytes', 'child_file_bytes'))
    if quote['aggregate_bytes'] > AGGREGATE_LIMIT:
        raise StageDRefusal('d_aggregate_reserve', quote)
    return quote


def _preserve_failure_v1(facts, error):
    code = getattr(error, 'cause', None)
    if type(code) is not str:
        code = 'd_' + type(error).__name__
    if code not in facts['causes']:
        facts['causes'].append(code)
    details = getattr(error, 'facts', None)
    if details is not None and details is not facts:
        if 'failed_operation' not in facts:
            facts['failed_operation'] = details
        else:
            facts.setdefault('secondary_failed_operations', []).append({'cause': code, 'facts': details})
        if type(details) is dict:
            for secondary in details.get('causes', []):
                if type(secondary) is str and secondary not in facts['causes']:
                    facts['causes'].append(secondary)
    facts['evaluation'] = evaluate_d_v1(facts)
    return code


class _NativeObserverV1:
    def __init__(self, root, clock):
        self.root, self.clock = root, clock

    def identity(self, directory, cids, deadline):
        # D creates no container. The exact retained CID set/provider evidence
        # comes from the revalidated C6 chain; fresh /info confirms same engine
        # and zero running/paused containers without duplicating the large list.
        _reserve_controls_v1(directory.parent, 'before-dmesg', identity=True)
        client = _DInfoClientV1(directory, deadline)
        info = client.request('GET', '/info', deadline_ns=min(deadline, self.clock() + 1000000000))
        result = _info_identity_v1(info, cids)
        result['rpc'] = client.facts
        return result

    def measure(self):
        return _floor_metrics_v1(self.root)

    def snapshot(self, directory, deadline):
        from tests.fixtures import accepted_policy_fixture_compiler_gate2_c_v1 as c
        _check_time(self.clock, deadline)
        metrics = _floor_metrics_v1(self.root)
        boot = compiler._compiler_proc_read_v1('/proc/sys/kernel/random/boot_id', 64).decode('ascii').strip()
        if re.fullmatch('[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', boot) is None:
            raise StageDRefusal('d_boot_id')
        captures = {}
        for kind, limit in (('dmesg', DMESG_LIMIT), ('journal', 512), ('gpu', 4096)):
            _reserve_controls_v1(directory.parent, directory.name + '-' + kind)
            row = c.capture_guard_v1(kind, output_dir=directory, absolute_deadline_ns=deadline,
                                     stdout_limit=limit, stderr_limit=0, record_original=False)
            if (type(row.get('returncode')) is not int or row['returncode'] != 0 or row.get('stdout_eof') is not True or
                    row.get('stderr_eof') is not True or row.get('persisted') is not True or
                    row.get('closed') is not True or row.get('forced') is not False or row.get('causes') != []):
                raise StageDRefusal('d_guard_' + kind, row)
            captures[kind] = row
        raw = {}
        for kind, limit in (('dmesg', DMESG_LIMIT), ('journal', 512), ('gpu', 4096)):
            capture = captures[kind]
            if type(capture.get('files')) is not dict:
                raise StageDRefusal('d_guard_original_binding')
            for channel, cap in (('stdout', limit), ('stderr', 0)):
                descriptor, writer = capture.get(channel), capture['files'].get(channel)
                if (type(descriptor) is not dict or type(writer) is not dict or
                        descriptor.get('path') != str(directory / (kind + '.' + channel + '.original'))):
                    raise StageDRefusal('d_guard_original_path')
                value = _read_bound_v1(Path(descriptor['path']), cap)
                digest = _sha(value)
                if (type(descriptor.get('size_bytes')) is not int or len(value) != descriptor['size_bytes'] or
                        digest != descriptor.get('sha256') or
                        type(capture.get(channel + '_observed_bytes')) is not int or
                        capture[channel + '_observed_bytes'] != len(value) or
                        capture.get(channel + '_confirmed_prefix_sha256') != digest or
                        any(type(writer.get(key)) is not int or writer[key] != len(value)
                            for key in ('written_bytes', 'persisted_bytes')) or
                        any(writer.get(key) is not True for key in ('open_completed', 'flush_completed',
                            'fsync_completed', 'close_completed')) or
                        writer.get('write_failed') is not False or writer.get('write_extent_unknown') is not False):
                    raise StageDRefusal('d_guard_original_binding')
                if channel == 'stdout':
                    raw[kind] = value
        if raw['gpu'].strip():
            raise StageDRefusal('d_gpu_busy')
        crashes = _crash_listing_v1()
        _reserve_controls_v1(directory.parent, directory.name + '-crashes')
        crash_descriptor = _write_original_v1(directory / 'crashes.original.json', crashes, CRASH_LIMIT,
                                               clock=self.clock, deadline=deadline)
        _check_time(self.clock, deadline)
        return {'metrics': metrics, 'boot_id': boot, 'captures': captures,
                'crashes': crash_descriptor, 'dmesg_sha256': _sha(raw['dmesg']),
                'crashes_sha256': _sha(crashes), 'journal': raw['journal'].decode('ascii')}


def run_d_v1(*, project_root, packet_descriptor, expected_packet_sha256,
             expected_code_commit, completion_authorities, _observer=None, _child_runner=None, _clock=None):
    """One fixed D attempt after all six externally reviewed C completions.

    The trusted caller supplies completion descriptors obtained from independent
    review of actual native returns and completed outer writes. Leftover C
    footers cannot supply this authority. Preserve and stop on any deviation.
    """
    from tests.fixtures import accepted_policy_fixture_compiler_gate2_c_v1 as c
    from tests.fixtures import accepted_policy_fixture_compiler_gate2_d_child_v1 as child_module
    raw_clock = _clock if _clock is not None else time.monotonic_ns
    started = raw_clock()
    if type(started) is not int or started < 0:
        raise StageDRefusal('d_clock')
    deadline = started + DEADLINE_NS
    last_clock = [started]
    def clock():
        current = raw_clock()
        if type(current) is not int or current < last_clock[0]:
            raise StageDRefusal('d_clock_regressed')
        last_clock[0] = current
        return current
    root = Path(project_root)
    if not root.is_absolute() or root.resolve(strict=True) != root or any(number != 1000 for number in (os.getuid(), os.geteuid(), os.getgid(), os.getegid())):
        raise StageDRefusal('d_host_identity')
    # Freeze only the fixed, bounded descriptor values. C enforces all six
    # authorities and their actual-file/review bindings; no authority is inferred
    # here. Reconstruct equal fresh mappings so neither caller nor callee mutation
    # can substitute different descriptors at the post-execution check.
    if type(completion_authorities) is not dict or len(completion_authorities) > 6:
        raise StageDRefusal('d_completion_authorities')
    authority_copy = {}
    for name, descriptor in completion_authorities.items():
        if (name not in c.STAGES or type(descriptor) is not dict or len(descriptor) != 3
                or set(descriptor) != {'path', 'size_bytes', 'sha256'}
                or type(descriptor['path']) is not str or not 0 < len(descriptor['path']) <= 4096
                or type(descriptor['size_bytes']) is not int or not 0 <= descriptor['size_bytes'] <= 8192
                or not _is_sha(descriptor['sha256'])):
            raise StageDRefusal('d_completion_authorities')
        authority_copy[name] = dict(descriptor)
    authority_raw = recipe.canonical_json_v1(authority_copy)
    binding = c.validated_c1_binding_v1(project_root=root, packet_descriptor=packet_descriptor,
                                       expected_packet_sha256=expected_packet_sha256,
                                       expected_code_commit=expected_code_commit,
                                       completion_authorities=json.loads(authority_raw))
    remaining = binding.get('remaining_seal_bytes')
    if type(remaining) is not int or not AGGREGATE_LIMIT <= remaining <= 536870912:
        raise StageDRefusal('d_global_reserve')
    _check_time(clock, deadline)
    observer = _observer if _observer is not None else _NativeObserverV1(root, clock)
    # V7/V8 charge closed operation intervals. The authenticated remaining
    # balance already carries all earlier charges and reserved forms; an idle
    # review gap after C6 is not a new D allocation or a ledger reset. Measure
    # D before its first directory/write and charge its complete final interval.
    # An old tail credit never offsets unrelated growth in this fresh interval.
    interval_start = observer.measure()
    if not _floors_v1(interval_start, AGGREGATE_LIMIT):
        raise StageDRefusal('d_entry_measurement')
    directory = root / 'outputs/D'
    if directory.parent.resolve(strict=True) != directory.parent or os.path.lexists(directory):
        raise StageDRefusal('d_fresh_directory')
    directory.mkdir(mode=0o700)
    controls = directory / 'controls'
    controls.mkdir(mode=0o700)
    before_dir, after_dir = controls / 'before', controls / 'after'
    before_dir.mkdir(mode=0o700)
    after_dir.mkdir(mode=0o700)
    runner = _child_runner if _child_runner is not None else child_module.run_child_v1
    facts = {'schema_version': 1, 'stage': 'D', 'controlled': any(x is not None for x in (_observer, _child_runner, _clock)),
             'source_sha256': recipe.SOURCE_SHA256['c1'], 'command_sha256': recipe.D_COMMAND_SHA256,
             'reply_sha256': recipe.D_REPLY_SHA256, 'started_ns': started,
             'absolute_deadline_ns': deadline, 'c1_receipt_sha256': binding.get('receipt_sha256'),
             'packet_sha256': expected_packet_sha256, 'code_commit': expected_code_commit,
             'c_completion_authorities_sha256': _sha(authority_raw),
             'aggregate_reserved_bytes': AGGREGATE_LIMIT, 'receipt_persisted': False,
             'interval_start_measurement': interval_start, 'gap_charge_bytes': 0,
             'causes': [], 'child': None, 'copy': None, 'state': None}
    previous, received = [], [None]
    before = after = None
    try:
        compiler._compiler_install_handlers_v1(received, previous)
        facts['identity'] = observer.identity(before_dir, binding.get('all_cids'), deadline)
        facts['identity_verified'] = True
        before = observer.snapshot(before_dir, deadline)
        facts['before'] = before
        if not _floors_v1(before['metrics'], AGGREGATE_LIMIT):
            raise StageDRefusal('d_capacity_floor')
        _controls_usage_v1(controls)  # oversized pre-capture refuses BEFORE exec
        if received[0] is not None:
            raise StageDRefusal('d_operator_signal')
        facts['allocation_quote'] = _reserve_aggregate_v1(controls, binding.get('elf_size_bytes'))
        facts['copy'] = _copy_c1_elf_v1(root, binding, directory / 'engine', clock=clock, deadline=deadline)
        _check_time(clock, deadline)
        if clock() >= phase_limits_v1(deadline)['work']:
            raise StageDRefusal('d_no_work_window')
        facts['allocation_quote'] = _reserve_aggregate_v1(controls, binding.get('elf_size_bytes'))
        facts['child'] = runner(executable_path=directory / 'engine', directory=directory,
                                output_dir=controls, started_ns=started, absolute_deadline_ns=deadline)
        for cause in facts['child'].get('causes', []):
            facts['causes'].append('d_child_' + str(cause))
        _validate_child_captures_v1(facts['child'], controls)
        _check_time(clock, deadline)
        if received[0] is not None:
            raise StageDRefusal('d_operator_signal')
        after = observer.snapshot(after_dir, deadline)
        facts['after'] = after
        post_binding = c.validated_c1_binding_v1(project_root=root, packet_descriptor=packet_descriptor,
                                                expected_packet_sha256=expected_packet_sha256,
                                                expected_code_commit=expected_code_commit,
                                                completion_authorities=json.loads(authority_raw))
        if post_binding != binding:
            raise StageDRefusal('d_packet_post_drift')
        if _sha(_read_bound_v1(directory / 'engine', ELF_LIMIT)) != facts['copy']['sha256']:
            raise StageDRefusal('d_copy_post_drift')
        state_path = directory / recipe.D_STATE_FILE
        state_raw = _read_bound_v1(state_path, CHILD_FILE_LIMIT)
        state_stat = state_path.lstat()
        facts['state'] = {'bytes': state_raw.decode('ascii'), 'size_bytes': len(state_raw),
                          'nlink': state_stat.st_nlink, 'regular': stat.S_ISREG(state_stat.st_mode)}
        facts['boot_unchanged'] = before['boot_id'] == after['boot_id']
        facts['dmesg_unchanged'] = before['dmesg_sha256'] == after['dmesg_sha256']
        facts['crashes_unchanged'] = before['crashes_sha256'] == after['crashes_sha256']
        facts['floors_preserved'] = _floors_v1(after['metrics'], 0)
        facts['within_deadline'] = clock() < deadline
    except BaseException as error:
        _preserve_failure_v1(facts, error)
        if facts['child'] is None and type(getattr(error, 'facts', None)) is dict and 'pid' in error.facts:
            facts['child'] = error.facts
    finally:
        restore = compiler._compiler_restore_handlers_v1(previous)
        facts['causes'].extend(restore)
        facts['handlers_restored'] = not restore
    try:
        usage = _controls_usage_v1(controls)
        facts['control_bytes'] = usage['total']
        facts['control_allocation_before_receipt'] = usage
        facts['finished_ns'] = clock()
        facts['within_deadline'] = facts.get('within_deadline') is True and facts['finished_ns'] < deadline
        facts['evaluation'] = evaluate_d_v1(facts)
        _reserve_controls_v1(controls, 'receipt')
        upper = compiler._json_bound(facts)
        if upper > RECEIPT_LIMIT:
            raise StageDRefusal('d_receipt_reserve')
        raw = recipe.canonical_json_v1(facts)
        descriptor = _write_original_v1(controls / 'd.result.original.json', raw, RECEIPT_LIMIT,
                                         clock=clock, deadline=deadline)
        facts['receipt_descriptor'] = descriptor
        facts['receipt_persisted'] = True
        actual = _controls_usage_v1(controls)
        facts['control_allocation_after_receipt'] = actual
        facts['control_bytes'] = actual['total']
        retained = actual['total'] + 4096 + LATER_INDEX_ALLOCATION
        state_allocation = 0
        for path in (directory / 'engine', directory / recipe.D_STATE_FILE):
            if os.path.lexists(path):
                allocated = _allocated_v1(path)
                retained += allocated
                if path.name == recipe.D_STATE_FILE:
                    state_allocation = allocated
        facts['aggregate_accounted_bytes'] = retained + max(0, CHILD_FILE_LIMIT + 256 - state_allocation)
        if facts['aggregate_accounted_bytes'] > AGGREGATE_LIMIT:
            raise StageDRefusal('d_aggregate_allocation')
        if before is not None and after is not None:
            final_measurement = observer.measure()
            facts['final_measurement_after_receipt'] = final_measurement
            facts['floors_preserved'] = facts.get('floors_preserved') is True and _floors_v1(final_measurement, 0)
            charge = max(retained, interval_start['c_free_bytes'] - final_measurement['c_free_bytes'],
                         final_measurement['ext4_used_bytes'] - interval_start['ext4_used_bytes'], 0)
            facts['ledger_after_receipt'] = {'remaining_before': remaining, 'charge_bytes': charge,
                                             'remaining_after': remaining - charge}
            if charge > remaining:
                raise StageDRefusal('d_global_allocation')
        facts['finished_ns'] = clock()
        facts['within_deadline'] = facts['finished_ns'] < deadline and facts.get('within_deadline') is True
        facts['evaluation'] = evaluate_d_v1(facts)
        if not facts['evaluation']['passed'] or not facts['evaluation']['finalization_complete']:
            raise StageDRefusal('d_component_failed')
        return facts
    except BaseException as error:
        code = _preserve_failure_v1(facts, error)
        raise StageDRefusal(code, facts) from error
