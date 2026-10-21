"""Ordinary authored fixed D27 TEST caller; geometry remains unadmitted."""
import hashlib
import json
import os
from pathlib import Path
import types
import unittest


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode('ascii')


class D27CaseError(RuntimeError):
    def __init__(self,metadata):
        super().__init__('d27_case_transport')
        self.metadata=json.loads(canonical(metadata))
        self.capture=self.metadata


_D27_CASES=('codec_vectors','codec_malformed','codec_overflow','geometry')
_D27_DRIVER_CAUSES=('d27_codec_absent','d27_driver_assertion','d27_driver_input','d27_driver_error','d27_node_version')


def _d27_main_module_v1():
    """Use canonical first, otherwise discovery, with no import or source reopening."""
    import sys
    names = ('tests.test_accepted_policy_fixture_compiler_gate2_dictionary_v1',
             'test_accepted_policy_fixture_compiler_gate2_dictionary_v1')
    expected = Path(__file__).with_name('test_accepted_policy_fixture_compiler_gate2_dictionary_v1.py').absolute()
    present = [(name, sys.modules[name]) for name in names if name in sys.modules]
    if not present:
        raise RuntimeError('d27_held_main_unavailable')
    selected_name, selected = present[0]
    for name, module in present:
        if type(module) is not types.ModuleType:
            raise RuntimeError('d27_held_main_unavailable')
        namespace = vars(module)
        if (namespace.get('__name__') != name and module is not selected
                or type(namespace.get('__file__')) is not str
                or Path(namespace['__file__']).absolute() != expected):
            raise RuntimeError('d27_held_main_unavailable')
    namespace = vars(selected)
    getter = namespace.get('d27_node_driver_v1')
    if (namespace.get('__name__') != selected_name or type(getter) is not types.FunctionType
            or getter.__name__ != 'd27_node_driver_v1' or getter.__module__ != selected_name
            or getter.__globals__ is not namespace or Path(getter.__code__.co_filename).absolute() != expected):
        raise RuntimeError('d27_held_main_unavailable')
    return selected


def _d27_run_fixed_driver_v1(case, raw, deadline, geometry=False):
    """Run one closed DATA case in the fixed D27 driver with bounded capture.

    A valid completed:false driver report returns normally. Only transport or
    protocol refusal raises D27CaseError with immutable metadata, never raw DATA.
    The original finite caller deadline also bounds startup, cleanup and return.
    """
    import copy
    import math
    import shutil
    import subprocess
    import threading
    import time

    started = time.monotonic()
    buffers = {'stdout': bytearray(), 'stderr': bytearray()}
    channels = {name: {'observed_bytes': 0, 'retained_bytes': 0, 'eof': False,
                       'overflow': False, 'io_error': None, 'closed': False,
                       'unknown_remainder': True} for name in buffers}
    facts = {'schema_version': 1, 'data_only': True, 'spawned': False, 'pid': None,
             'returncode': None, 'timed_out': False, 'kill_requested': False,
             'stdin_bytes': 0, 'stdin_closed': False, 'stdin_complete': False,
             'stdin_extent_unknown': False, 'stdin_write_attempted': False,
             'stdin_write_in_flight': False, 'threads_started': 0, 'reaped': False,
             'threads_joined': False, 'causes': [], 'node_version': None,
             'case': case if type(case) is str and case in _D27_CASES else None,
             'case_completed': None, 'case_cause': None, 'parent_observed_completion': False,
             'descendant_quiescence': 'UNKNOWN', 'input_bytes': None,
             'input_sha256': None, 'data_bytes': None, 'data_sha256': None,
             'report_bytes': None, 'report_sha256': None, 'checks_count': None,
             'measurements_count': None, 'environment_keys': [], 'program_sha256': None,
             'source_kind': 'd27_fixed_test_driver_v1', 'program_bytes': None,
             'driver_role': ('geometry' if geometry else 'codec') if type(geometry) is bool else None,
             'driver_getter': ('d27_geometry_driver_v1' if geometry else 'd27_node_driver_v1') if type(geometry) is bool else None}
    lock = threading.RLock()
    def cause(value):
        with lock:
            if value not in facts['causes']:
                facts['causes'].append(value)
    def has_causes():
        with lock:
            return bool(facts['causes'])
    def finish(report=None):
        # Capture related facts, channels, causes and byte prefixes at one shared
        # lock boundary. Later worker changes cannot mix these captured values.
        with lock:
            snapshot = copy.deepcopy(facts)
            captured_channels = {name: dict(channel) for name, channel in channels.items()}
            prefixes = {name: bytes(buffer) for name, buffer in buffers.items()}
        for name, channel in captured_channels.items():
            prefix = prefixes[name]
            snapshot[name] = {**channel, 'retained_bytes': len(prefix),
                              'prefix_sha256': hashlib.sha256(prefix).hexdigest(),
                              'unknown_remainder': not channel['eof'] or channel['overflow'] or channel['io_error'] is not None}
        observed = time.monotonic()
        snapshot['elapsed_seconds'] = observed - started
        snapshot['finished_before_deadline'] = observed < end if end is not None else False
        snapshot['child_completion_observed_before_deadline'] = (
            snapshot['spawned'] and child_total_end is not None and observed < child_total_end)
        if snapshot['spawned'] and not snapshot['child_completion_observed_before_deadline']:
            if 'child_completion_late' not in snapshot['causes']:
                snapshot['causes'].append('child_completion_late')
        if not snapshot['finished_before_deadline'] and 'parent_deadline' not in snapshot['causes']:
            snapshot['causes'].append('parent_deadline')
        if snapshot['spawned'] and observed >= cleanup_end:
            if 'cleanup_late' not in snapshot['causes']:
                snapshot['causes'].append('cleanup_late')
        snapshot['parent_observed_completion'] = report is not None and not snapshot['causes']
        encoded = canonical(snapshot)
        if len(encoded) > 32768:
            raise RuntimeError('D27 capture metadata bound')
        # Publication is immutable; the shared capture does not establish
        # continuous custody or quiescence of unjoined workers/descendants.
        frozen = json.loads(encoded)
        if frozen['causes']:
            raise D27CaseError(frozen)
        return report, frozen
    end = None
    child_total_end = None
    if type(deadline) not in (int, float):
        cause('deadline_invalid');return finish()
    try:
        end = float(deadline)
    except (OverflowError, ValueError):
        cause('deadline_invalid');return finish()
    if not math.isfinite(end):
        end = None;cause('deadline_invalid');return finish()
    if end - started > 300:
        cause('deadline_limit');return finish()
    if type(case) is not str or case not in _D27_CASES:
        cause('case_invalid');return finish()
    if type(geometry) is not bool or geometry != (case == 'geometry'):
        cause('geometry_invalid');return finish()
    if type(raw) is not bytes:
        cause('input_type');return finish()
    if len(raw) > 262144:
        cause('input_limit');return finish()
    if not raw.isascii():
        cause('input_ascii');return finish()
    if time.monotonic() >= end - 8:
        cause('deadline_no_window');return finish()
    try:
        def unique_input(rows):
            value = dict(rows)
            if len(value) != len(rows):
                raise ValueError('duplicate DATA field')
            return value
        def reject_constant(value):
            raise ValueError('nonfinite DATA')
        data = json.loads(raw, object_pairs_hook=unique_input, parse_constant=reject_constant)
        wire = canonical({'case': case, 'data': data})
        if len(wire) > 262144:
            cause('input_envelope_limit');return finish()
    except (ValueError, TypeError, RecursionError, OverflowError):
        cause('input_json');return finish()
    with lock:
        facts.update(data_bytes=len(raw), data_sha256=hashlib.sha256(raw).hexdigest(),
                     input_bytes=len(wire), input_sha256=hashlib.sha256(wire).hexdigest())
    raw = wire
    work_end = min(started + 27, end - 8)
    child_total_end = min(started + 30, end - 5)
    cleanup_end = min(child_total_end, work_end + 3)
    with lock:
        facts.update(started_monotonic=started, caller_deadline=end, work_deadline=work_end,
                     child_total_deadline=child_total_end, cleanup_deadline=cleanup_end, child_total_limit_seconds=30,
                     child_work_limit_seconds=27, cleanup_limit_seconds=3, final_reserve_seconds=5)
    if time.monotonic() >= work_end:
        cause('deadline_no_window');return finish()
    try:
        module = _d27_main_module_v1()
        program = module.d27_geometry_driver_v1() if geometry else module.d27_node_driver_v1()
    except Exception:
        cause('driver_source_error');return finish()
    if type(program) is not str:
        cause('driver_source_kind');return finish()
    if not 0 < len(program) <= 24576:
        cause('driver_source_limit');return finish()
    try:
        program_bytes = program.encode('ascii')
    except UnicodeEncodeError:
        cause('driver_source_ascii');return finish()
    # Hold one exact immutable source/argv buffer; DATA never selects a program.
    program = program_bytes.decode('ascii')
    with lock:
        facts.update(program_bytes=len(program_bytes), program_sha256=hashlib.sha256(program_bytes).hexdigest())
    node = shutil.which('node') or shutil.which('node.exe')
    if node is None:
        cause('node_unavailable');return finish()
    try:
        node = str(Path(node).resolve(strict=True))
        environment = {'PATH': str(Path(node).parent)}
        if os.name == 'nt':
            environment['SystemRoot'] = os.environ['SystemRoot']
        argv = [node, '--max-old-space-size=256', '--input-type=commonjs', '-e', program]
        if os.name == 'nt' and len(subprocess.list2cmdline(argv)) > 32767:
            cause('driver_command_limit');return finish()
        with lock:
            facts.update(node_executable=node, command_options=argv[1:4], environment_keys=sorted(environment))
        if time.monotonic() >= work_end:
            cause('deadline_before_spawn');return finish()
        process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, env=environment, bufsize=0,
                                   start_new_session=os.name != 'nt',
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except (OSError, KeyError, ValueError) as error:
        cause('spawn_' + type(error).__name__);return finish()
    with lock:
        facts.update(spawned=True, pid=process.pid)
    if time.monotonic() >= work_end:
        with lock:
            facts['timed_out'] = True;cause('deadline_after_spawn')
    def read_channel(name, pipe, limit):
        channel = channels[name]
        try:
            while True:
                with lock:
                    read_size = min(4096, limit + 1 - len(buffers[name]))
                part = pipe.read(read_size)
                with lock:
                    if type(part) is not bytes:
                        channel['io_error'] = 'invalid_read';cause(name + '_read_error');break
                    if part == b'':
                        channel['eof'] = True;break
                    channel['observed_bytes'] += len(part)
                    room = limit - len(buffers[name])
                    buffers[name].extend(part[:room])
                    if len(part) > room:
                        channel['overflow'] = True;cause(name + '_overflow');break
        except (OSError, ValueError) as error:
            with lock:
                channel['io_error'] = type(error).__name__;cause(name + '_read_error')
        finally:
            try:
                pipe.close()
                with lock:
                    channel['closed'] = True
            except (OSError, ValueError):
                cause(name + '_close_error')
    def write_input():
        try:
            while True:
                with lock:
                    offset = facts['stdin_bytes']
                    if offset >= len(raw):
                        break
                    if time.monotonic() >= work_end:
                        cause('stdin_deadline');break
                    remaining = len(raw) - offset
                    facts.update(stdin_write_attempted=True, stdin_write_in_flight=True,
                                 stdin_extent_unknown=True)
                count = process.stdin.write(raw[offset:])
                with lock:
                    facts['stdin_write_in_flight'] = False
                    if type(count) is not int or not 0 < count <= remaining:
                        cause('stdin_short_write');break
                    facts['stdin_bytes'] += count
                    facts['stdin_extent_unknown'] = False
                if time.monotonic() >= work_end:
                    cause('stdin_deadline');break
            with lock:
                facts['stdin_complete'] = (facts['stdin_bytes'] == len(raw)
                                           and not facts['stdin_extent_unknown'])
        except (OSError, ValueError):
            with lock:
                facts.update(stdin_write_in_flight=False, stdin_extent_unknown=True)
                cause('stdin_write_error')
        finally:
            try:
                process.stdin.close()
                with lock:
                    facts['stdin_closed'] = True
            except (OSError, ValueError):
                cause('stdin_close_error')
    threads = [threading.Thread(target=read_channel, args=('stdout', process.stdout, 1048576), daemon=True),
               threading.Thread(target=read_channel, args=('stderr', process.stderr, 16384), daemon=True),
               threading.Thread(target=write_input, daemon=True)]
    started_threads = []
    for thread in threads:
        if has_causes():
            break
        if time.monotonic() >= work_end:
            with lock:
                facts['timed_out'] = True;cause('worker_start_deadline')
            break
        try:
            thread.start()
            started_threads.append(thread)
            if time.monotonic() >= work_end:
                with lock:
                    facts['timed_out'] = True;cause('worker_start_late')
                break
        except RuntimeError:
            if thread.ident is not None:
                started_threads.append(thread)
            cause('thread_start_error');break
    with lock:
        facts['threads_started'] = len(started_threads)
    def status():
        try:
            return process.poll()
        except (OSError, ValueError):
            cause('child_status_error');return None
    while True:
        if time.monotonic() >= work_end:
            with lock:
                facts['timed_out'] = True;cause('child_timeout')
            break
        if has_causes() or (status() is not None and all(not thread.is_alive() for thread in started_threads)):
            break
        time.sleep(min(.005, max(0, work_end - time.monotonic())))
    cleanup_end = min(cleanup_end, time.monotonic() + 3)
    with lock:
        facts['cleanup_deadline'] = cleanup_end
    if status() is None:
        with lock:
            facts['kill_requested'] = True
        try:
            process.kill()
        except OSError:
            cause('child_kill_error')
    for thread, pipe, name in zip(threads, (process.stdout, process.stderr, process.stdin), ('stdout', 'stderr', 'stdin')):
        if thread not in started_threads:
            try:
                pipe.close()
                with lock:
                    if name == 'stdin':
                        facts['stdin_closed'] = True
                    else:
                        channels[name]['closed'] = True
            except (OSError, ValueError):
                cause(name + '_unstarted_close_error')
    try:
        returned = process.wait(timeout=max(0, cleanup_end - time.monotonic()))
        with lock:
            facts['reaped'] = type(returned) is int
            if not facts['reaped']:
                cause('child_reap_unknown')
    except (OSError, ValueError, subprocess.TimeoutExpired):
        cause('child_reap_unknown')
    for thread in started_threads:
        try:
            thread.join(max(0, cleanup_end - time.monotonic()))
        except RuntimeError:
            cause('thread_join_error')
    returned_status = status()
    joined = len(started_threads) == len(threads) and all(not thread.is_alive() for thread in started_threads)
    with lock:
        facts.update(returncode=returned_status, threads_joined=joined)
        if not facts['threads_joined']:
            cause('pipe_completion_unknown')
        if type(facts['returncode']) is not int or facts['returncode'] != 0:
            cause('child_status')
        if facts['kill_requested']:
            cause('child_forced')
        if not facts['stdin_complete'] or not facts['stdin_closed'] or not all(c['eof'] for c in channels.values()):
            cause('io_completion_unknown')
        stdout_data, stderr_data = bytes(buffers['stdout']), bytes(buffers['stderr'])
    if has_causes():
        return finish()
    if stderr_data:
        cause('unexpected_stderr');return finish()
    try:
        if len(stdout_data) > 32768 or not stdout_data.isascii():
            raise ValueError('report extent')
        def unique_pairs(rows):
            result = dict(rows)
            if len(result) != len(rows):
                raise ValueError('duplicate report field')
            return result
        result = json.loads(stdout_data, object_pairs_hook=unique_pairs, parse_constant=reject_constant)
        if (type(result) is not dict or set(result) != {'schema_version', 'case', 'node_version',
                'completed', 'cause', 'checks', 'measurements'}
                or type(result['schema_version']) is not int or result['schema_version'] != 1
                or result['case'] != case or type(result['case']) is not str
                or result['node_version'] != '25.2.1' or type(result['completed']) is not bool
                or result['cause'] is not None and (type(result['cause']) is not str
                    or result['cause'] not in _D27_DRIVER_CAUSES and not (geometry
                        and case == 'geometry' and result['cause'] == 'd27_geometry_hold'))
                or type(result['checks']) is not list or len(result['checks']) > 512
                or type(result['measurements']) is not list or len(result['measurements']) > 128):
            raise ValueError('report shape')
        import re
        def identifier(value):
            return type(value) is str and re.fullmatch(r'[A-Za-z0-9_]{1,64}', value) is not None
        for item in result['checks']:
            if (type(item) is not dict or set(item) != {'id', 'ok'}
                    or not identifier(item['id']) or type(item['ok']) is not bool):
                raise ValueError('report check')
        for item in result['measurements']:
            if (type(item) is not dict or set(item) != {'id', 'size_bytes', 'sha256'}
                    or not identifier(item['id']) or type(item['size_bytes']) is not int
                    or not 0 <= item['size_bytes'] <= 262144
                    or type(item['sha256']) is not str
                    or re.fullmatch(r'[0-9a-f]{64}', item['sha256']) is None):
                raise ValueError('report measurement')
    except (ValueError, TypeError, RecursionError, OverflowError):
        cause('child_protocol');return finish()
    with lock:
        facts.update(node_version=result['node_version'], case_completed=result['completed'],
                     case_cause=result['cause'], report_bytes=len(stdout_data),
                     report_sha256=hashlib.sha256(stdout_data).hexdigest(),
                     checks_count=len(result['checks']), measurements_count=len(result['measurements']))
    return finish(result)


def d27_run_case_v1(case,raw,deadline):
    """Closed codec cases only; geometry has a separately admitted entry."""
    if case=='geometry':
        raise ValueError('d27_geometry_requires_separate_admission')
    return _d27_run_fixed_driver_v1(case,raw,deadline,False)


class D27WireCodecTests(unittest.TestCase):
    def test_selected_and_observed_small_canonical_round_trip(self):
        import time
        report,capture=d27_run_case_v1('codec_vectors',b'{}',time.monotonic()+30)
        self.assertTrue(capture['parent_observed_completion'])
        self.assertEqual(capture['node_version'],'25.2.1')
        self.assertTrue(report['completed'],report['cause'])
        self.assertIsNone(report['cause'])
        self.assertEqual(report['checks'],[{'id':'selected_round_trip','ok':True},{'id':'observed_round_trip','ok':True}])


D27_CODEC_TEST_ENTRY = 'import sys\nsys.stdout.reconfigure(encoding=\'utf-8\')\nimport hashlib,json,os,pathlib,stat,types,unittest\nif not (sys.flags.isolated and sys.flags.no_site and sys.flags.dont_write_bytecode and sys.flags.optimize==0):raise RuntimeError(\'d27_entry_python_flags\')\nroot=pathlib.Path(\'C:/Users/s-a-balashov/.codex/worktrees/fix-accepted-policy-preprocessing/VAST\')\nexpected=json.loads(sys.argv[1]);assert type(expected) is dict and set(expected)=={\'main\',\'caller\'}\nfixed=((\'main\',\'tests.test_accepted_policy_fixture_compiler_gate2_dictionary_v1\',\'test_accepted_policy_fixture_compiler_gate2_dictionary_v1.py\'),(\'caller\',\'tests.test_accepted_policy_fixture_compiler_gate2_dictionary_caller_v1\',\'test_accepted_policy_fixture_compiler_gate2_dictionary_caller_v1.py\'))\ndef epoch(s,cross=False):return(s.st_dev,s.st_ino,s.st_mode,s.st_nlink,s.st_size,s.st_mtime_ns,getattr(s,"st_birthtime_ns",None),None if cross and os.name=="nt" else s.st_ctime_ns)\nheld=[]\nfor role,name,filename in fixed:\n path=root/\'tests\'/filename;pin=expected[role];assert type(pin) is list and len(pin)==2 and type(pin[0]) is int and 0<pin[0]<=524288 and type(pin[1]) is str and len(pin[1])==64\n before=path.lstat();assert path.resolve(strict=True)==path and stat.S_ISREG(before.st_mode) and before.st_nlink==1 and before.st_size==pin[0]\n fd=os.open(path,os.O_RDONLY|getattr(os,\'O_BINARY\',0))\n try:\n  opened=os.fstat(fd);assert epoch(opened,True)==epoch(before,True)\n  raw=b\'\'\n  while len(raw)<pin[0]:\n   part=os.read(fd,min(65536,pin[0]-len(raw)));assert part;raw+=part\n  assert os.read(fd,1)==b\'\' and epoch(os.fstat(fd))==epoch(opened) and epoch(path.lstat())==epoch(before)\n finally:os.close(fd)\n assert len(raw)==pin[0] and hashlib.sha256(raw).hexdigest()==pin[1];held.append((name,path,raw))\n# Both immutable buffers have been authenticated and held before either compile.\nmodules=[]\nfor name,path,raw in held:\n module=types.ModuleType(name);module.__file__=str(path);module.__package__=\'tests\';sys.modules[name]=module;modules.append(module)\nfor module,(_,path,raw) in zip(modules,held):exec(compile(raw,str(path),\'exec\'),vars(module))\nsuite=unittest.defaultTestLoader.loadTestsFromTestCase(modules[1].D27WireCodecTests)\nresult=unittest.TextTestRunner(verbosity=2).run(suite)\nraise SystemExit(0 if result.wasSuccessful() else 1)\n'
