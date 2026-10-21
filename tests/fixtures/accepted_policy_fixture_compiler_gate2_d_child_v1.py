"""One fixed Linux Stage-D child; controlled effects never qualify execution.

Popen/preexec and individual kernel/file calls are trusted synchronous syscall
boundaries, not claims of kernel-call preemption. Their completion is measured
against the original deadline; late/unknown completion cannot pass. There is no
blocking wait, communicate, retry, deadline reset or post-deadline grace.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import select
import signal
import subprocess
import time

from tests.fixtures import accepted_policy_fixture_compiler_component_v1 as recipe
from tests.fixtures import accepted_policy_fixture_compiler_gate2_d_v1 as stage
from tests.fixtures import accepted_policy_fixture_compiler_v1 as compiler


def _preexec_proof_v1(fd, *, _effects=None):
    import resource
    effects = dict(set_limit=lambda name, value: resource.setrlimit(getattr(resource, 'RLIMIT_' + name), value),
        get_limit=lambda name: resource.getrlimit(getattr(resource, 'RLIMIT_' + name)),
        getpid=os.getpid, getuid=os.getuid, geteuid=os.geteuid, getgid=os.getgid,
        getegid=os.getegid, getpgid=os.getpgid, getsid=os.getsid, write=os.write, close=os.close)
    if _effects is not None:
        effects.update(_effects)
    try:
        effects['set_limit']('CORE', (1, 1))
        effects['set_limit']('FSIZE', (1048576, 1048576))
        value = {key: effects['get' + key]() for key in ('pid', 'uid', 'euid', 'gid', 'egid')}
        value.update(pgid=effects['getpgid'](0), sid=effects['getsid'](0),
                     core=list(effects['get_limit']('CORE')), fsize=list(effects['get_limit']('FSIZE')))
        raw = recipe.canonical_json_v1(value) + b'\n'
        stage.validate_preexec_proof_v1(raw, value['pid'])
        if len(raw) > stage.PROOF_LIMIT or effects['write'](fd, raw) != len(raw):
            raise stage.StageDRefusal('d_preexec_write')
    finally:
        effects['close'](fd)  # Explicitly absent from the subsequently exec'd ELF.


def _identity_v1(pid):
    raw = compiler._compiler_proc_read_v1('/proc/%d/stat' % pid, 4096)
    end = raw.rfind(b') ')
    fields = raw[end + 2:].split()
    if end < 1 or len(fields) < 20 or int(raw.split(b' ', 1)[0]) != pid:
        raise stage.StageDRefusal('d_child_identity')
    status = compiler._compiler_proc_read_v1('/proc/%d/status' % pid, 8192)
    rows = {line.split(b':', 1)[0]: line.split()[1:] for line in status.splitlines() if line.startswith((b'Uid:', b'Gid:'))}
    if rows.get(b'Uid') != [b'1000'] * 4 or rows.get(b'Gid') != [b'1000'] * 4:
        raise stage.StageDRefusal('d_child_identity')
    return dict(pid=pid, start_ticks=int(fields[19]), pgid=os.getpgid(pid), sid=os.getsid(pid),
                uid=1000, euid=1000, gid=1000, egid=1000)


def _physical_directory_v1(path):
    return path.is_absolute() and path.resolve(strict=True) == path and path.is_dir()


def run_child_v1(*, executable_path: Path, directory: Path, output_dir: Path,
                 started_ns: int, absolute_deadline_ns: int, _effects=None):
    """Run the outer-authenticated ELF once, returning status and custody facts."""
    effects = dict(clock=time.monotonic_ns, popen=subprocess.Popen,
        pipe=lambda: os.pipe2(os.O_CLOEXEC | os.O_NONBLOCK), fd_close=os.close,
        fd_read=os.read, nonblocking=lambda fd: os.set_blocking(fd, False),
        select=select.select, waitpid=os.waitpid, identity=_identity_v1, killpg=os.killpg,
        open_capture=lambda path: path.open('xb', buffering=0), sync=os.fsync,
        preexec=_preexec_proof_v1, physical_directory=_physical_directory_v1)
    if _effects is not None:
        if type(_effects) is not dict or set(_effects) - set(effects):
            raise stage.StageDRefusal('d_child_effects')
        effects.update(_effects)
    if (type(started_ns) is not int or started_ns < 0 or type(absolute_deadline_ns) is not int or
            absolute_deadline_ns != started_ns + stage.DEADLINE_NS or
            not all(isinstance(path, Path) for path in (executable_path, directory, output_dir)) or
            executable_path.parent != directory or not executable_path.is_absolute() or
            not effects['physical_directory'](directory) or not effects['physical_directory'](output_dir)):
        raise stage.StageDRefusal('d_child_binding')
    facts = dict(pid=None, identity_verified=False, identity=None, proof='', proof_eof=False,
        returncode=None, wait_status=None, reaped=False, core_dumped=None, stdout='', stderr='',
        stdin_written_bytes=0, stdin_closed=False, stdout_eof=False, stderr_eof=False,
        signals=[], forced=False, unknown_closure=False, late=False, capture_persisted=False,
        capture_closed=False, controlled=_effects is not None, causes=[], timings={}, records={})
    process = None
    identity = None
    proof_read = proof_write = None
    proof_valid = False
    captures = {}
    failed_streams = set()
    stdin_close_failed = False
    last_clock = started_ns
    phase = 'work'
    work_end = absolute_deadline_ns - 3_000_000_000
    phase_end = work_end
    pipes_closed = True

    def cause(code):
        if code not in facts['causes']:
            facts['causes'].append(code)

    def now():
        nonlocal last_clock
        try:
            value = effects['clock']()
        except BaseException as error:
            cause('d_child_clock_' + type(error).__name__)
            facts['late'] = True
            last_clock = absolute_deadline_ns
            return absolute_deadline_ns
        if type(value) is not int or value < last_clock:
            cause('d_child_clock')
            facts['late'] = True
            last_clock = absolute_deadline_ns
            return absolute_deadline_ns
        last_clock = value
        if value >= absolute_deadline_ns:
            facts['late'] = True
        return value

    def own_identity(value):
        return (type(value) is dict and type(value.get('start_ticks')) is int and value['start_ticks'] > 0 and
            all(type(value.get(key)) is int and value[key] == facts['pid'] for key in ('pid', 'pgid', 'sid')) and
            all(type(value.get(key)) is int and value[key] == 1000 for key in ('uid', 'euid', 'gid', 'egid')))

    def signal_group(number):
        if facts['reaped'] or facts['pid'] is None:
            return
        facts['forced'] = True
        try:
            if identity is None or effects['identity'](facts['pid']) != identity:
                raise stage.StageDRefusal('d_child_identity_drift')
            if now() >= absolute_deadline_ns:
                return
            name = 'TERM' if number == signal.SIGTERM else 'KILL'
            facts['signals'].append(name)
            facts['timings'][name.lower()] = last_clock
            effects['killpg'](facts['pid'], number)
            now()
        except BaseException as error:
            cause(error.cause if isinstance(error, stage.StageDRefusal) else 'd_child_signal_' + type(error).__name__)
            facts['unknown_closure'] = True

    def retain(name, raw):
        entry = captures[name]
        entry['data'].extend(raw)
        if entry['failed']:
            return
        returned = False
        try:
            count = entry['file'].write(raw)
            returned = True
            if type(count) is not int or not 0 <= count <= len(raw):
                entry['unknown'] = True
                raise ValueError('write contract')
            entry['written'] += count
            if count != len(raw):
                raise OSError('short write')
        except BaseException as error:
            if not returned:
                entry['unknown'] = True
            entry['failed'] = True
            cause('d_child_capture_' + type(error).__name__)

    try:
        if now() >= work_end:
            raise stage.StageDRefusal('d_child_spawn_window')
        for name in ('stdout', 'stderr', 'preexec'):
            captures[name] = dict(file=effects['open_capture'](output_dir / ('d.' + name + '.original')),
                data=bytearray(), written=0, observed=0, unknown=False, failed=False,
                persisted=False, closed=False)
        proof_read, proof_write = effects['pipe']()
        facts['timings']['before_spawn'] = now()
        if last_clock >= work_end:
            raise stage.StageDRefusal('d_child_spawn_window')
        process = effects['popen']([str(executable_path)], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=str(directory),
            env=stage.child_environment_v1(str(directory)), start_new_session=True,
            close_fds=True, pass_fds=(proof_write,), preexec_fn=lambda: effects['preexec'](proof_write), bufsize=0)
        facts['pid'] = process.pid
        facts['timings']['after_spawn'] = now()
        effects['fd_close'](proof_write)
        proof_write = None
        if last_clock >= absolute_deadline_ns:
            cause('d_child_spawn_late')
            facts['unknown_closure'] = True
        else:
            if type(process.pid) is not int or not 1 < process.pid <= 4194304:
                raise stage.StageDRefusal('d_child_identity')
            identity = effects['identity'](process.pid)
            if not own_identity(identity):
                raise stage.StageDRefusal('d_child_identity')
            facts['identity'] = identity
            try:
                for stream in (process.stdin, process.stdout, process.stderr):
                    effects['nonblocking'](stream.fileno())
                effects['nonblocking'](proof_read)
            except BaseException as error:
                cause('d_child_nonblocking_' + type(error).__name__)
        while now() < absolute_deadline_ns:
            current = last_clock
            if phase == 'work' and (facts['causes'] or current >= work_end):
                if not facts['causes']:
                    cause('d_child_work_deadline')
                phase = 'term'
                signal_group(signal.SIGTERM)
                phase_end = min(last_clock + 1_000_000_000, absolute_deadline_ns - 2_000_000_000)
            if phase == 'term' and current >= phase_end and not facts['reaped']:
                phase = 'kill'
                signal_group(signal.SIGKILL)
                phase_end = min(last_clock + 1_000_000_000, absolute_deadline_ns - 1_000_000_000)
            if phase == 'kill' and current >= phase_end:
                phase = 'final'
                phase_end = min(last_clock + 1_000_000_000, absolute_deadline_ns)
            if phase == 'final' and current >= phase_end:
                break
            current = now()
            if current >= absolute_deadline_ns:
                break
            if not facts['reaped']:
                try:
                    pid, status = effects['waitpid'](facts['pid'], os.WNOHANG)
                    if pid:
                        if pid != facts['pid'] or type(status) is not int or not (os.WIFEXITED(status) or os.WIFSIGNALED(status)):
                            raise stage.StageDRefusal('d_child_wait_status')
                        facts.update(wait_status=status, returncode=os.waitstatus_to_exitcode(status), reaped=True,
                                     core_dumped=bool(os.WIFSIGNALED(status) and os.WCOREDUMP(status)))
                        process.returncode = facts['returncode']
                        if status != 0:
                            cause('d_child_status')
                except BaseException as error:
                    cause(error.cause if isinstance(error, stage.StageDRefusal) else 'd_child_wait_' + type(error).__name__)
            current = now()
            if current >= absolute_deadline_ns:
                break
            if (facts['reaped'] and facts['stdout_eof'] and facts['stderr_eof'] and facts['proof_eof']):
                if not facts['stdin_closed'] or facts['stdin_written_bytes'] != len(recipe.D_COMMAND):
                    cause('d_child_stdin_incomplete')
                break
            if facts['reaped'] and phase != 'final':
                phase = 'final'
                phase_end = min(last_clock + 1_000_000_000, absolute_deadline_ns)
            readers = []
            if not facts['proof_eof'] and 'preexec' not in failed_streams:
                readers.append(proof_read)
            for name in ('stdout', 'stderr'):
                if not facts[name + '_eof'] and name not in failed_streams:
                    readers.append(getattr(process, name))
            writers = [process.stdin] if proof_valid and not facts['stdin_closed'] and not facts['causes'] else []
            timeout = max(0, min(50_000_000, phase_end - current, absolute_deadline_ns - current)) / 1_000_000_000
            try:
                ready, writable, _ = effects['select'](readers, writers, [], timeout)
            except BaseException as error:
                cause('d_child_select_' + type(error).__name__)
                continue
            if now() >= absolute_deadline_ns:
                break
            for name, stream in [('preexec', proof_read), ('stdout', process.stdout), ('stderr', process.stderr)]:
                if stream not in ready:
                    continue
                entry = captures[name]
                try:
                    limit = stage.PROOF_LIMIT if name == 'preexec' else stage.CHANNEL_LIMIT
                    used = len(entry['data']) if name == 'preexec' else sum(len(captures[k]['data']) for k in ('stdout', 'stderr'))
                    overflow_code = 'd_child_proof_cap' if name == 'preexec' else 'd_child_channel_cap'
                    count = 4096 if overflow_code in facts['causes'] else min(4096, max(1, limit - used + 1))
                    raw = effects['fd_read'](stream, count) if name == 'preexec' else stream.read(count)
                    if raw is None:
                        continue
                    if type(raw) is not bytes or len(raw) > count:
                        raise ValueError('read contract')
                    entry['observed'] += len(raw)
                    keep = min(len(raw), max(0, limit - used))
                    retain(name, raw[:keep])
                    if keep != len(raw):
                        cause(overflow_code)
                    if not raw:
                        facts['proof_eof' if name == 'preexec' else name + '_eof'] = True
                        if name == 'preexec':
                            stage.validate_preexec_proof_v1(bytes(entry['data']), facts['pid'])
                            proof_valid = True
                            facts['identity_verified'] = identity is not None
                except BlockingIOError:
                    pass
                except BaseException as error:
                    failed_streams.add(name)
                    cause(error.cause if isinstance(error, stage.StageDRefusal) else 'd_child_read_' + type(error).__name__)
                if now() >= absolute_deadline_ns:
                    break
            if now() < absolute_deadline_ns and process.stdin in writable:
                closing_stdin = False
                try:
                    raw = recipe.D_COMMAND[facts['stdin_written_bytes']:]
                    count = process.stdin.write(raw)
                    if count is not None:
                        if type(count) is not int or not 0 < count <= len(raw):
                            raise ValueError('stdin write contract')
                        facts['stdin_written_bytes'] += count
                    if facts['stdin_written_bytes'] == len(recipe.D_COMMAND):
                        closing_stdin = True
                        process.stdin.close()
                        facts['stdin_closed'] = True
                except BlockingIOError:
                    pass
                except BaseException as error:
                    cause('d_child_stdin_' + type(error).__name__)
                    if closing_stdin:
                        stdin_close_failed = True
                        pipes_closed = False
                now()
    except BaseException as error:
        cause(error.cause if isinstance(error, stage.StageDRefusal) else 'd_child_operation_' + type(error).__name__)
        facts['unknown_closure'] = process is not None and not facts['reaped']
        # No alternate cleanup loop: unexpected observation failures are unknown.
        # A still-owned, verified group receives at most this one TERM, within
        # the original budget; the outer caller must stop on unknown closure.
        if process is not None and not facts['signals'] and now() < absolute_deadline_ns:
            signal_group(signal.SIGTERM)
    finally:
        for fd in (proof_write, proof_read):
            if fd is not None:
                try:
                    effects['fd_close'](fd)
                except BaseException as error:
                    pipes_closed = False
                    cause('d_child_pipe_close_' + type(error).__name__)
        if process is not None:
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is process.stdin and stdin_close_failed:
                    continue
                try:
                    if not stream.closed:
                        stream.close()
                    if stream is process.stdin:
                        facts['stdin_closed'] = True
                except BaseException as error:
                    pipes_closed = False
                    cause('d_child_pipe_close_' + type(error).__name__)
        for name, entry in captures.items():
            try:
                if not entry['failed'] and now() < absolute_deadline_ns:
                    entry['file'].flush()
                    if now() < absolute_deadline_ns:
                        effects['sync'](entry['file'].fileno())
                        entry['persisted'] = now() < absolute_deadline_ns and not entry['unknown']
            except BaseException as error:
                cause('d_child_capture_persist_' + type(error).__name__)
            finally:
                try:
                    entry['file'].close()
                    entry['closed'] = True
                except BaseException as error:
                    cause('d_child_capture_close_' + type(error).__name__)
            raw = bytes(entry['data'])
            facts['proof' if name == 'preexec' else name] = raw.decode('ascii', errors='backslashreplace')
            facts['records'][name] = dict(path=str(output_dir / ('d.' + name + '.original')),
                observed_bytes=entry['observed'], written_bytes=entry['written'],
                size_bytes=None if entry['unknown'] else entry['written'],
                sha256=None if entry['unknown'] or entry['written'] != len(raw) else hashlib.sha256(raw).hexdigest(),
                write_extent_unknown=entry['unknown'], persisted=entry['persisted'], closed=entry['closed'])
        facts['capture_persisted'] = len(captures) == 3 and all(entry['persisted'] for entry in captures.values())
        facts['capture_closed'] = pipes_closed and len(captures) == 3 and all(entry['closed'] for entry in captures.values())
        facts['unknown_closure'] |= not facts['reaped'] or not all(facts[key] for key in ('proof_eof', 'stdout_eof', 'stderr_eof')) or not pipes_closed
        facts['timings']['finished'] = now()
    return facts
