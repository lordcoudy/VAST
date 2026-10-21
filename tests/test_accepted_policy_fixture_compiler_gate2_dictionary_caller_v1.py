"""Ordinary authored fixed D27 TEST caller; geometry remains unadmitted."""
import hashlib
import base64
import math
import re
from typing import Any
import io
import json
import os
import sys
from pathlib import Path,PurePosixPath
import types
import unittest
from unittest import mock


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode('ascii')


class D27CaseError(RuntimeError):
    def __init__(self,metadata):
        super().__init__('d27_case_transport')
        self.metadata=json.loads(canonical(metadata))
        self.capture=self.metadata


_D27_CASES=('codec_vectors','codec_malformed','codec_overflow','geometry')
_D27_DRIVER_CAUSES=('d27_codec_absent','d27_driver_assertion','d27_driver_input','d27_driver_error','d27_node_version')


def _d27_main_module_v1(geometry=False):
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
    if type(geometry) is not bool:
        raise RuntimeError('d27_held_main_unavailable')
    getter_name = 'd27_geometry_driver_v1' if geometry else 'd27_node_driver_v1'
    getter = namespace.get(getter_name)
    if (namespace.get('__name__') != selected_name or type(getter) is not types.FunctionType
            or getter.__name__ != getter_name or getter.__module__ != selected_name
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
        module = _d27_main_module_v1(geometry)
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
        check_ids=set()
        for item in result['checks']:
            if (type(item) is not dict or set(item) != {'id', 'ok'}
                    or not identifier(item['id']) or type(item['ok']) is not bool):
                raise ValueError('report check')
            if item['id'] in check_ids:raise ValueError('duplicate report check')
            check_ids.add(item['id'])
        measurement_ids=set()
        for item in result['measurements']:
            if (type(item) is not dict or set(item) != {'id', 'size_bytes', 'sha256'}
                    or not identifier(item['id']) or type(item['size_bytes']) is not int
                    or not 0 <= item['size_bytes'] <= 262144
                    or type(item['sha256']) is not str
                    or re.fullmatch(r'[0-9a-f]{64}', item['sha256']) is None):
                raise ValueError('report measurement')
            if item['id'] in measurement_ids:raise ValueError('duplicate report measurement')
            measurement_ids.add(item['id'])
        if canonical(result)+b'\n' != stdout_data:
            raise ValueError('report canonical LF')
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
    def run_case(self,case,required):
        import time
        report,capture=d27_run_case_v1(case,b'{}',time.monotonic()+30)
        self.assertTrue(capture['parent_observed_completion'])
        self.assertEqual(capture['node_version'],'25.2.1')
        self.assertTrue(report['completed'],(report['cause'],report['checks'][-3:]))
        self.assertIsNone(report['cause'])
        checks={r['id']:r['ok'] for r in report['checks']}
        self.assertEqual(len(checks),len(report['checks']))
        for name in required:self.assertIs(checks[name],True)

    def test_literal_widths_and_reference_roundtrips(self):
        self.run_case('codec_vectors',('literal_widths_7_through_13','kwkwk_legal_previous_plus_first','original_exact_32768','all_low_radix_digits_positive_packet','all_byte_padding_extents','all_group_padding_extents','decode_virtual_N_above_9216'))

    def test_malformed_transport_and_cause_precedence(self):
        self.run_case('codec_malformed',('all_457_forbidden_pairs_before_tokens','invalid_next_before_expansion','valid_next_expansion','short_complete_binding','recovered_spelling_binding','impossible_header_extent'))

    def test_allocation_access_charges_and_clock_boundaries(self):
        self.run_case('codec_overflow',('each_dictionary_stack_access_separately_charged','exact_three_dictionary_arrays','sample_before_257th_work','post_throw_clock_precedence','zero_premature_payload_vectors','cache_backward_body_reload_zero','cache_backward_body_reload_nonzero','saturation_impossibility_arithmetic'))


class D27CaptureControlTests(unittest.TestCase):
    """Controlled external process/I/O only; no geometry or actual Node claim."""

    def report(self):
        return {'schema_version':1,'case':'codec_vectors','node_version':'25.2.1',
                'completed':True,'cause':None,'checks':[{'id':'one','ok':True}],
                'measurements':[]}

    def capture(self,report=None,stdout=None,stderr=b'',status=0,chunk=None,write_error=False):
        import io
        import subprocess
        import sys
        import time
        from unittest.mock import patch
        if stdout is None:stdout=canonical(self.report() if report is None else report)+b'\n'
        class Input(io.BytesIO):
            def write(inner,data):
                if write_error and inner.tell()>0:raise OSError('controlled_stdin')
                return super().write(data if chunk is None else data[:chunk])
        class Child:
            pid=12345
            def __init__(inner):
                inner.stdin=Input();inner.stdout=io.BytesIO(stdout);inner.stderr=io.BytesIO(stderr)
            def poll(inner):return status
            def wait(inner,timeout):return status
            def kill(inner):raise AssertionError('completed controlled child must not be killed')
        with patch('subprocess.Popen',return_value=Child()),patch('shutil.which',return_value=sys.executable):
            return d27_run_case_v1('codec_vectors',b'{}',time.monotonic()+30)

    def assert_protocol_refused(self,raw):
        with self.assertRaises(D27CaseError) as cm:self.capture(stdout=raw)
        self.assertIn('child_protocol',cm.exception.metadata['causes'])
        self.assertFalse(cm.exception.metadata['parent_observed_completion'])

    def test_canonical_report_and_completed_capture_correspond(self):
        report,capture=self.capture(chunk=3)
        self.assertTrue(capture['parent_observed_completion'])
        self.assertEqual(capture['threads_started'],3)
        self.assertFalse(capture['stdin_write_in_flight'])
        self.assertEqual(capture['report_sha256'],hashlib.sha256(canonical(report)+b'\n').hexdigest())
        for channel in ('stdout','stderr'):
            self.assertTrue(capture[channel]['eof'])
            self.assertEqual(capture[channel]['observed_bytes'],capture[channel]['retained_bytes'])
        self.assertEqual(capture['stderr']['prefix_sha256'],hashlib.sha256(b'').hexdigest())
        self.assertEqual(capture['descendant_quiescence'],'UNKNOWN')

    def test_duplicate_check_ids_refuse(self):
        r=self.report();r['checks']*=2
        self.assert_protocol_refused(canonical(r)+b'\n')

    def test_duplicate_measurement_ids_refuse(self):
        r=self.report();m={'id':'same','size_bytes':0,'sha256':hashlib.sha256(b'').hexdigest()}
        r['measurements']=[m,m]
        self.assert_protocol_refused(canonical(r)+b'\n')

    def test_noncanonical_report_or_lf_refuses(self):
        r=self.report();c=canonical(r)
        for raw in (c,c+b'\n\n',c+b' \n',json.dumps(r).encode()+b'\n',b' '+c+b'\n'):
            with self.subTest(size=len(raw)):self.assert_protocol_refused(raw)

    def test_exact_report_cap_and_one_byte_refusal(self):
        r=self.report();r['checks']=[{'id':f'c{i:03d}','ok':True} for i in range(512)]
        missing=32767-len(canonical(r))
        self.assertGreater(missing,0)
        for row in r['checks']:
            extra=min(missing,64-len(row['id']));row['id']+='_'*extra;missing-=extra
        self.assertEqual(missing,0)
        raw=canonical(r)+b'\n';self.assertEqual(len(raw),32768)
        actual,capture=self.capture(stdout=raw)
        self.assertTrue(capture['parent_observed_completion']);self.assertEqual(len(actual['checks']),512)
        r['checks'][-1]['id']+='_'
        self.assert_protocol_refused(canonical(r)+b'\n')

    def test_channel_overflow_preserves_bounded_known_prefix(self):
        for name,limit in (('stdout',1048576),('stderr',16384)):
            kwargs={name:b'x'*(limit+1)}
            with self.subTest(channel=name),self.assertRaises(D27CaseError) as cm:self.capture(**kwargs)
            facts=cm.exception.metadata
            self.assertIn(name+'_overflow',facts['causes'])
            self.assertEqual(facts[name]['retained_bytes'],limit)
            self.assertEqual(facts[name]['observed_bytes'],limit+1)
            self.assertTrue(facts[name]['unknown_remainder'])
            self.assertFalse(facts['parent_observed_completion'])

    def test_stderr_nonzero_status_and_partial_stdin_do_not_accept(self):
        for kwargs,cause in (({'stderr':b'known'},'unexpected_stderr'),({'status':7},'child_status'),({'chunk':3,'write_error':True},'stdin_write_error')):
            with self.subTest(cause=cause),self.assertRaises(D27CaseError) as cm:self.capture(**kwargs)
            self.assertIn(cause,cm.exception.metadata['causes'])
            self.assertFalse(cm.exception.metadata['parent_observed_completion'])
        with self.assertRaises(D27CaseError) as cm:self.capture(chunk=3,write_error=True)
        self.assertGreater(cm.exception.metadata['stdin_bytes'],0)
        self.assertTrue(cm.exception.metadata['stdin_extent_unknown'])

    def test_pre_spawn_input_and_deadline_refusals(self):
        import time
        cases=((b'x'*262145,time.monotonic()+30,'input_limit'),(b'\xff',time.monotonic()+30,'input_ascii'),
               (b'{}',float('nan'),'deadline_invalid'),(b'{}',time.monotonic()+301,'deadline_limit'),
               (b'{}',time.monotonic()+7,'deadline_no_window'))
        for raw,end,cause in cases:
            with self.subTest(cause=cause),self.assertRaises(D27CaseError) as cm:d27_run_case_v1('codec_vectors',raw,end)
            self.assertIn(cause,cm.exception.metadata['causes']);self.assertFalse(cm.exception.metadata['spawned'])

    def test_foreign_driver_getter_refuses_before_spawn(self):
        import time
        from unittest.mock import patch
        module=_d27_main_module_v1()
        def foreign():return 'not_a_fixed_driver'
        with patch.object(module,'d27_node_driver_v1',foreign),self.assertRaises(D27CaseError) as cm:
            d27_run_case_v1('codec_vectors',b'{}',time.monotonic()+30)
        self.assertIn('driver_source_error',cm.exception.metadata['causes'])
        self.assertFalse(cm.exception.metadata['spawned'])

    def test_fixed_entry_rejects_wrong_python_before_source_hold(self):
        import subprocess
        import sys
        program='import sys\nsys.version_info=(3,14,6)\n'+D27_CODEC_TEST_ENTRY
        p=subprocess.run([sys.executable,'-I','-S','-B','-c',program],stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=5)
        self.assertLessEqual(len(p.stdout),32768);self.assertLessEqual(len(p.stderr),16384)
        self.assertNotEqual(p.returncode,0)
        self.assertIn(b'd27_entry_python_version',p.stderr)


def d27_run_geometry_v1(raw,deadline):
    """Fixed geometry transport; execution requires the separate recorded admission."""
    return _d27_run_fixed_driver_v1('geometry',raw,deadline,True)


# Authored external-I/O control port; no operational geometry subject is executed.
class D27FixedDriverTransportTests(unittest.TestCase):
    def setUpClass():
        D27FixedDriverTransportTests.observations = []

    def setUp(self):
        import sys
        self.fixed_loader = _d27_main_module_v1
        self.fixed_program = "'use strict';/* fixed DATA transport fixture, never executed */"
        self.loader = mock.patch.object(sys.modules[__name__], '_d27_main_module_v1', return_value=types.SimpleNamespace(
            d27_node_driver_v1=lambda: self.fixed_program))
        self.loaded = self.loader.start()
        self.resolver = mock.patch('shutil.which', return_value=sys.executable)
        self.resolver.start()
        self.addCleanup(self.resolver.stop)
        self.addCleanup(self.loader.stop)

    def _capture(self, call):
        try:
            result = call()
        except D27CaseError as error:
            self.observations.append(error.metadata)
            return None, error.metadata
        self.observations.append(result[1])
        return result

    def _wire(self, data=None, case='codec_vectors'):
        return canonical({'case': case, 'data': {} if data is None else data})

    def _output(self, case='codec_vectors', completed=True, cause=None):
        return canonical({'schema_version': 1, 'case': case, 'node_version': '25.2.1',
            'completed': completed, 'cause': cause,
            'checks': [{'id': 'transport_fixture', 'ok': completed}], 'measurements': []}) + b'\n'

    def _fake_process(self, stdout=b'', stderr=b'', status=0, blocked=False):
        import threading
        stopped = threading.Event()
        state = {'status': None if blocked else status}
        class Reader(io.BytesIO):
            def read(self, size=-1):
                if blocked:
                    stopped.wait(2)
                return super().read(size)
        def kill():
            state['status'] = -9
            stopped.set()
        def wait(timeout=None):
            import subprocess
            if state['status'] is None:
                stopped.wait(timeout)
            if state['status'] is None:
                raise subprocess.TimeoutExpired('controlled DATA child', timeout)
            return state['status']
        return types.SimpleNamespace(pid=12345, stdin=io.BytesIO(), stdout=Reader(stdout),
                                     stderr=Reader(stderr), poll=lambda: state['status'], kill=kill, wait=wait)

    def test_fixed_driver_and_behavioral_failure_have_separate_completion_facts(self):
        import time
        for case in sorted(case for case in _D27_CASES if case != 'geometry'):
            for completed, cause in ((True, None), (False, 'd27_codec_absent')):
                output = self._output(case, completed, cause)
                with self.subTest(case=case, completed=completed), mock.patch('subprocess.Popen',
                        return_value=self._fake_process(stdout=output)) as spawn, mock.patch.dict(
                        os.environ, {'NODE_OPTIONS': 'forbidden', 'NODE_PATH': 'forbidden',
                                     'NODE_REPL_HISTORY': 'forbidden'}):
                    report, facts = self._capture(lambda: d27_run_case_v1(case, b'{}', time.monotonic() + 40))
                self.assertTrue(facts['parent_observed_completion'])
                self.assertIs(facts['case_completed'], completed)
                self.assertIs(report['completed'], completed)
                self.assertEqual(facts['case_cause'], cause)
                self.assertEqual(facts['program_sha256'], hashlib.sha256(self.fixed_program.encode('ascii')).hexdigest())
                self.assertEqual(facts['source_kind'], 'd27_fixed_test_driver_v1')
                self.assertEqual(facts['driver_role'], 'codec')
                self.assertEqual(facts['driver_getter'], 'd27_node_driver_v1')
                self.assertEqual(facts['program_bytes'], len(self.fixed_program.encode('ascii')))
                argv = spawn.call_args.args[0]
                self.assertEqual(argv[1:], ['--max-old-space-size=256', '--input-type=commonjs', '-e', self.fixed_program])
                self.assertFalse(set(spawn.call_args.kwargs['env']) - {'PATH', 'SystemRoot'})
                self.assertFalse(any(k in facts for k in ('stderr_prefix_b64', 'stdout_data', 'stderr_data')))
                self.assertLessEqual(len(canonical(facts)), 32768)

    def test_mock_geometry_capture_rejects_known_identity_and_clock_mutations(self):
        import copy,time
        self.loaded.return_value.d27_geometry_driver_v1=lambda:self.fixed_program
        with mock.patch('subprocess.Popen',return_value=self._fake_process(stdout=self._output('geometry'))):
            report,facts=d27_run_geometry_v1(b'{}',time.monotonic()+40)
        self.assertIs(d27_capture_metadata_v1(facts),facts)
        for key,bad in (('schema_version',2),('node_version','25.2.2'),('returncode',False),
                        ('threads_started',2),('stdin_write_in_flight',True),
                        ('caller_deadline',facts['started_monotonic']+10),('cleanup_deadline',facts['child_total_deadline']+1)):
            changed=copy.deepcopy(facts);changed[key]=bad
            with self.subTest(key=key),self.assertRaises(ValueError):d27_capture_metadata_v1(changed)
        changed=copy.deepcopy(facts);changed['stdout']['observed_bytes']+=1
        with self.assertRaises(ValueError):d27_capture_metadata_v1(changed)
        self.assertEqual(report['case'],'geometry')

    def test_mock_compression_capture_rejects_bool_status_and_float_quality(self):
        import copy,time
        raw=canonical({'node_version':'25.2.1','packed_b64':base64.b64encode(b'control-packed').decode('ascii'),
                       'quality':11,'roundtrip':True})+b'\n'
        with mock.patch('subprocess.Popen',return_value=self._fake_process(stdout=raw)):
            packed,facts=d27_compress_data_v1(b'{}',time.monotonic()+40)
        self.assertEqual(packed,b'control-packed');self.assertIs(d27_capture_metadata_v1(facts),facts)
        for key,bad in (('returncode',False),('quality',11.0),('schema_version',True),('node_version','26.0.0'),
                        ('pid',None),('input_bytes',None),('program_sha256',None),('packed_sha256',None)):
            changed=copy.deepcopy(facts);changed[key]=bad
            with self.subTest(key=key),self.assertRaises(ValueError):d27_capture_metadata_v1(changed)

    def test_invalid_input_and_budget_refuse_before_driver_loading_or_spawn(self):
        import time
        now = time.monotonic()
        cases = [('unknown', b'{}', now + 40), (True, b'{}', now + 40),
                 ('codec_vectors', None, now + 40), ('codec_vectors', b'\xff', now + 40),
                 ('codec_vectors', b'x' * 262145, now + 40), ('codec_vectors', b'{', now + 40),
                 ('codec_vectors', b'{"x":1,"x":2}', now + 40), ('codec_vectors', b'NaN', now + 40),
                 ('codec_vectors', b'1e9999', now + 40),
                 ('codec_vectors', b'[' * 1100 + b'0', now + 40)]
        cases += [('codec_vectors', b'{}', end) for end in (True, None, float('nan'), float('inf'), now - 1, now + 301)]
        for case, raw, end in cases:
            with self.subTest(kind=type(raw).__name__), mock.patch('subprocess.Popen') as spawn:
                report, facts = self._capture(lambda: d27_run_case_v1(case, raw, end))
                self.assertIsNone(report)
                self.assertFalse(facts['spawned'] or facts['stdin_write_attempted'] or facts['stdin_extent_unknown'])
                self.assertFalse(facts['parent_observed_completion'])
                self.loaded.assert_not_called()
                spawn.assert_not_called()

    def test_full_envelope_exact_limit_and_one_byte_over(self):
        import time
        overhead = len(self._wire('', 'codec_vectors'))
        data = 'x' * (262144 - overhead)
        raw = canonical(data)
        self.assertEqual(len(self._wire(data)), 262144)
        with mock.patch('subprocess.Popen', return_value=self._fake_process(stdout=self._output())):
            report, facts = self._capture(lambda: d27_run_case_v1('codec_vectors', raw, time.monotonic() + 40))
        self.assertTrue(facts['parent_observed_completion'])
        self.assertEqual(facts['input_bytes'], 262144)
        self.loaded.reset_mock()
        with mock.patch('subprocess.Popen') as spawn:
            report, facts = self._capture(lambda: d27_run_case_v1('codec_vectors', canonical(data + 'x'), time.monotonic() + 40))
        self.assertIn('input_envelope_limit', facts['causes'])
        self.loaded.assert_not_called()
        spawn.assert_not_called()

    def test_fixed_driver_kind_ascii_and_size_are_bounded_before_spawn(self):
        import time
        for program, expected in ((None, 'driver_source_kind'), ('x' * 24577, 'driver_source_limit'),
                                  ('', 'driver_source_limit'), ('\u0080', 'driver_source_ascii')):
            with self.subTest(cause=expected), mock.patch.object(sys.modules[__name__], '_d27_main_module_v1',
                    return_value=types.SimpleNamespace(d27_node_driver_v1=lambda: program)), mock.patch('subprocess.Popen') as spawn:
                report, facts = self._capture(lambda: d27_run_case_v1('codec_vectors', b'{}', time.monotonic() + 40))
            self.assertIn(expected, facts['causes'])
            spawn.assert_not_called()

    def test_channel_overflow_status_errors_and_stderr_never_publish_raw_data(self):
        import time
        secret = b'GENERATED_SOURCE_MUST_STAY_RAM'
        variants = [(self._fake_process(stdout=b'x' * 1048577), 'stdout_overflow'),
                    (self._fake_process(stderr=secret * 600), 'stderr_overflow'),
                    (self._fake_process(stdout=self._output(), stderr=secret), 'unexpected_stderr'),
                    (self._fake_process(stdout=self._output(), status=7), 'child_status')]
        class RefusingReader(io.BytesIO):
            def read(self, size=-1):raise OSError('GENERATED_SOURCE_MUST_STAY_RAM')
        broken = self._fake_process();broken.stdout = RefusingReader()
        variants.append((broken, 'stdout_read_error'))
        class UnknownEOFReader(io.BytesIO):
            def read(self, size=-1):return None
        no_eof = self._fake_process();no_eof.stdout = UnknownEOFReader()
        variants.append((no_eof, 'stdout_read_error'))
        def unavailable_status():raise OSError('GENERATED_SOURCE_MUST_STAY_RAM')
        no_status = self._fake_process(stdout=self._output());no_status.poll = unavailable_status
        variants.append((no_status, 'child_status_error'))
        for process, expected in variants:
            with self.subTest(cause=expected), mock.patch('subprocess.Popen', return_value=process):
                report, facts = self._capture(lambda: d27_run_case_v1('codec_vectors', b'{}', time.monotonic() + 40))
            self.assertIsNone(report)
            self.assertIn(expected, facts['causes'])
            self.assertFalse(facts['parent_observed_completion'])
            self.assertTrue(secret not in canonical(facts), 'raw child DATA must never enter retained metadata')
            self.assertLessEqual(len(canonical(facts)), 32768)

    def test_report_schema_and_report_extent_are_independently_bounded(self):
        import time
        base = json.loads(self._output())
        invalid = []
        for key, value in [('schema_version', True), ('case', 'geometry'), ('node_version', '0'),
                           ('completed', 1), ('cause', 'unbounded error text'), ('extra', None),
                           ('checks', [{'id': 'bad-id', 'ok': True}]),
                           ('checks', [{'id': 'ok', 'ok': 1}]),
                           ('checks', [{'id': 'x', 'ok': True}] * 513),
                           ('measurements', [{'id': 'x', 'size_bytes': True, 'sha256': '0' * 64}]),
                           ('measurements', [{'id': 'x', 'size_bytes': 262145, 'sha256': '0' * 64}]),
                           ('measurements', [{'id': 'x', 'size_bytes': 0, 'sha256': 'X' * 64}]),
                           ('measurements', [{'id': 'x', 'size_bytes': 0, 'sha256': '0' * 64}] * 129)]:
            value_report = dict(base);value_report[key] = value;invalid.append(canonical(value_report))
        invalid += [b'{"case":"codec_vectors","case":"codec_vectors"}', b'[' * 1100 + b'0' + b']' * 1100,
                    self._output() + b'{}', self._output() + b' ' * 32768]
        for output in invalid:
            with self.subTest(kind='closed bounded report'), mock.patch('subprocess.Popen', return_value=self._fake_process(stdout=output)):
                report, facts = self._capture(lambda: d27_run_case_v1('codec_vectors', b'{}', time.monotonic() + 40))
            self.assertIsNone(report)
            self.assertIn('child_protocol', facts['causes'])
        output = self._output();output += b' ' * (32768 - len(output))
        with mock.patch('subprocess.Popen', return_value=self._fake_process(stdout=output)):
            report, facts = self._capture(lambda: d27_run_case_v1('codec_vectors', b'{}', time.monotonic() + 40))
        self.assertFalse(facts['parent_observed_completion'])
        self.assertIn('child_protocol',facts['causes'])

    def test_late_driver_or_node_resolution_cannot_spawn(self):
        for phase in ('driver', 'node'):
            clock = [1000.0]
            def driver():
                if phase == 'driver':clock[0] = 1027.0
                return self.fixed_program
            def resolve(name):
                import sys
                if phase == 'node':clock[0] = 1027.0
                return sys.executable
            with self.subTest(phase=phase), mock.patch('time.monotonic', side_effect=lambda: clock[0]), \
                    mock.patch.object(sys.modules[__name__], '_d27_main_module_v1', return_value=types.SimpleNamespace(d27_node_driver_v1=driver)), \
                    mock.patch('shutil.which', resolve), mock.patch('subprocess.Popen') as spawn:
                report, facts = self._capture(lambda: d27_run_case_v1('codec_vectors', b'{}', 1040.0))
            self.assertIn('deadline_before_spawn', facts['causes'])
            spawn.assert_not_called()

    def test_driver_loading_failure_is_bounded_and_never_exposes_its_message(self):
        import time
        with mock.patch.object(sys.modules[__name__], '_d27_main_module_v1', side_effect=RuntimeError('GENERATED_SOURCE_MUST_STAY_RAM')), \
                mock.patch('subprocess.Popen') as spawn:
            report, facts = self._capture(lambda: d27_run_case_v1('codec_vectors', b'{}', time.monotonic() + 40))
        self.assertIsNone(report)
        self.assertEqual(facts['causes'], ['driver_source_error'])
        self.assertTrue(b'GENERATED_SOURCE_MUST_STAY_RAM' not in canonical(facts))
        spawn.assert_not_called()

    def test_report_accepts_boundary_measurements_without_behavioral_pass_inference(self):
        import time
        value = json.loads(self._output(completed=False, cause='d27_driver_assertion'))
        value['measurements'] = [{'id': ('a' if size==0 else 'b') * 64, 'size_bytes': size, 'sha256': '0' * 64}
                                 for size in (0, 262144)]
        with mock.patch('subprocess.Popen', return_value=self._fake_process(stdout=canonical(value) + b'\n')):
            report, facts = self._capture(lambda: d27_run_case_v1('codec_vectors', b'{}', time.monotonic() + 40))
        self.assertTrue(facts['parent_observed_completion'])
        self.assertFalse(facts['case_completed'])
        self.assertEqual(facts['measurements_count'], 2)
        self.assertFalse(report['completed'])

    def test_work_timeout_keeps_channel_and_stdin_unknowns_nonaccepting(self):
        clock, started, after_start = [1000.0], [], [0]
        process = self._fake_process(blocked=True)
        class PendingThread:
            ident = None
            def __init__(self, target, args=(), daemon=None):pass
            def start(self):
                self.ident = 1
                started.append(self)
            def join(self, timeout=None):return None
            def is_alive(self):return True
        def now():
            if len(started) == 3:
                after_start[0] += 1
                if after_start[0] >= 2:clock[0] = 1027.0
            return clock[0]
        with mock.patch('threading.Thread', PendingThread), mock.patch('time.monotonic', now), \
                mock.patch('subprocess.Popen', return_value=process):
            report, facts = self._capture(lambda: d27_run_case_v1('codec_vectors', b'{}', 1040.0))
        self.assertIsNone(report)
        self.assertIn('child_timeout', facts['causes'])
        self.assertTrue(facts['timed_out'] and facts['kill_requested'])
        self.assertFalse(facts['stdout']['eof'] or facts['stderr']['eof'] or facts['stdin_complete'])
        self.assertFalse(facts['parent_observed_completion'])
        self.assertLessEqual(facts['cleanup_deadline'], facts['started_monotonic'] + 30)

    def test_partial_thread_start_has_three_second_cleanup_and_known_unknowns(self):
        import threading
        import time
        process = self._fake_process(blocked=True)
        original_start, original_join = threading.Thread.start, threading.Thread.join
        calls, waits = [], []
        def start(thread):
            calls.append(thread)
            if len(calls) == 2:
                raise RuntimeError('controlled partial startup')
            original_start(thread)
        def join(thread, timeout=None):
            waits.append(timeout)
            original_join(thread, timeout)
        with mock.patch('subprocess.Popen', return_value=process), \
                mock.patch('threading.Thread.start', start), mock.patch('threading.Thread.join', join):
            report, facts = self._capture(lambda: d27_run_case_v1('codec_vectors', b'{}', time.monotonic() + 295))
        self.assertIsNone(report)
        self.assertIn('thread_start_error', facts['causes'])
        self.assertEqual(facts['threads_started'], 1)
        self.assertTrue(facts['kill_requested'] and facts['reaped'])
        self.assertFalse(facts['threads_joined'])
        self.assertTrue(facts['stderr']['closed'] and facts['stderr']['unknown_remainder'])
        self.assertTrue(bool(waits) and all(0 <= value <= 3 for value in waits))
        self.assertLessEqual(facts['cleanup_deadline'], facts['work_deadline'] + 3)
        self.assertLessEqual(facts['work_deadline'], facts['started_monotonic'] + 27)
        self.assertLessEqual(facts['cleanup_deadline'], facts['started_monotonic'] + 30)
        self.assertEqual((facts['child_total_limit_seconds'], facts['child_work_limit_seconds'],
                          facts['cleanup_limit_seconds'], facts['final_reserve_seconds']), (30, 27, 3, 5))

    def test_late_spawn_starts_no_worker_or_stdin_write(self):
        process = self._fake_process(blocked=True)
        writes, clock = [], [1000.0]
        class Input(io.BytesIO):
            def write(self, value):
                writes.append(len(value))
                return len(value)
        process.stdin = Input()
        def spawn(*args, **kwargs):
            clock[0] = 1027.0
            return process
        with mock.patch('time.monotonic', side_effect=lambda: clock[0]), \
                mock.patch('subprocess.Popen', spawn), mock.patch('threading.Thread.start') as start:
            report, facts = self._capture(lambda: d27_run_case_v1('codec_vectors', b'{}', 1040.0))
        self.assertIsNone(report)
        self.assertIn('deadline_after_spawn', facts['causes'])
        self.assertTrue(facts['spawned'] and facts['kill_requested'] and facts['reaped'])
        self.assertEqual(facts['threads_started'], 0)
        self.assertTrue(not writes and facts['stdin_bytes'] == 0)
        self.assertTrue(facts['stdout']['unknown_remainder'] and facts['stderr']['unknown_remainder'])
        self.assertEqual(facts['returncode'], -9)
        start.assert_not_called()

    def test_each_worker_start_has_pre_and_post_work_guards(self):
        for mode, expected in (('post', 'worker_start_late'), ('next', 'worker_start_deadline')):
            with self.subTest(boundary=mode):
                clock, starts, reads = [1000.0], [], [0]
                process = self._fake_process()
                class InlineThread:
                    ident = None
                    def __init__(self, target, args=(), daemon=None):
                        self.target, self.args = target, args
                    def start(self):
                        starts.append(self)
                        self.ident = 1
                        self.target(*self.args)
                    def join(self, timeout=None):
                        return None
                    def is_alive(self):
                        return False
                def now():
                    if starts:
                        reads[0] += 1
                        if mode == 'post' or reads[0] >= 2:
                            clock[0] = 1027.0
                    return clock[0]
                with mock.patch('time.monotonic', now), mock.patch('threading.Thread', InlineThread), \
                        mock.patch('subprocess.Popen', return_value=process):
                    report, facts = self._capture(lambda: d27_run_case_v1('codec_vectors', b'{}', 1040.0))
                self.assertIsNone(report)
                self.assertIn(expected, facts['causes'])
                self.assertEqual(len(starts), 1)
                self.assertEqual(facts['stdin_bytes'], 0)
                self.assertFalse(facts['stdin_complete'])

    def test_late_wait_join_or_status_cannot_publish_completion(self):
        output = self._output()
        for phase in ('wait', 'join', 'status'):
            with self.subTest(observation=phase):
                clock, polls = [1000.0], [0]
                process = self._fake_process(stdout=output)
                class InlineThread:
                    ident = None
                    def __init__(self, target, args=(), daemon=None):
                        self.target, self.args = target, args
                    def start(self):
                        self.ident = 1
                        self.target(*self.args)
                    def join(self, timeout=None):
                        if phase == 'join':
                            clock[0] = 1030.0
                    def is_alive(self):
                        return False
                def status():
                    polls[0] += 1
                    if phase == 'status' and polls[0] >= 2:
                        clock[0] = 1030.0
                    return 0
                def wait(timeout=None):
                    if phase == 'wait':
                        clock[0] = 1030.0
                    return 0
                process.poll, process.wait = status, wait
                with mock.patch('time.monotonic', side_effect=lambda: clock[0]), \
                        mock.patch('threading.Thread', InlineThread), mock.patch('subprocess.Popen', return_value=process):
                    report, facts = self._capture(lambda: d27_run_case_v1('codec_vectors', b'{}', 1040.0))
                self.assertIsNone(report)
                self.assertIn('child_completion_late', facts['causes'])
                self.assertTrue(facts['finished_before_deadline'])
                self.assertFalse(facts['child_completion_observed_before_deadline'])
                self.assertFalse(facts['parent_observed_completion'])
                self.assertEqual(facts['descendant_quiescence'], 'UNKNOWN')

    def test_unjoined_reader_capture_binds_prefix_counters_eof_and_causes(self):
        import threading
        import time
        for terminal in ('eof', 'error'):
            with self.subTest(reader_terminal=terminal):
                released, closed = threading.Event(), threading.Event()
                process = self._fake_process()
                process.poll = lambda: -9
                process.wait = lambda timeout=None: -9
                class LateReader(io.BytesIO):
                    def read(self, size=-1):
                        if not released.wait(2):
                            raise OSError('controlled release deadline')
                        part = super().read(size)
                        if not part and terminal == 'error':
                            raise OSError('controlled late read refusal')
                        return part
                    def close(self):
                        super().close()
                        closed.set()
                process.stdout = LateReader(b'bounded DATA')
                original_start, original_join = threading.Thread.start, threading.Thread.join
                original_sha256 = hashlib.sha256
                workers, triggered, settled = [], [], []
                def start(thread):
                    if len(workers) == 2:
                        raise RuntimeError('controlled third startup')
                    workers.append(thread)
                    original_start(thread)
                def hash_after_capture(value=b'', *args, **kwargs):
                    if value == b'' and not triggered:
                        triggered.append(True)
                        released.set()
                        settled.append(closed.wait(2))
                    return original_sha256(value, *args, **kwargs)
                try:
                    with mock.patch('subprocess.Popen', return_value=process), \
                            mock.patch('threading.Thread.start', start), \
                            mock.patch('threading.Thread.join', return_value=None), \
                            mock.patch('hashlib.sha256', hash_after_capture):
                        report, facts = self._capture(lambda: d27_run_case_v1('codec_vectors', b'{}', time.monotonic() + 40))
                    before = canonical(facts)
                finally:
                    released.set()
                    for worker in workers:
                        original_join(worker, 3)
                self.assertIsNone(report)
                self.assertTrue(bool(triggered) and settled == [True], 'controlled reader must finish during prefix hashing')
                self.assertEqual((facts['stdout']['observed_bytes'], facts['stdout']['retained_bytes']), (0, 0))
                self.assertEqual(facts['stdout']['prefix_sha256'], original_sha256(b'').hexdigest())
                self.assertFalse(facts['stdout']['eof'] or facts['stdout']['closed'])
                self.assertIsNone(facts['stdout']['io_error'])
                self.assertTrue(facts['stdout']['unknown_remainder'])
                self.assertEqual(set(facts['causes']), {'thread_start_error', 'pipe_completion_unknown',
                                                       'child_status', 'io_completion_unknown'})
                self.assertTrue(canonical(facts) == before, 'captured refusal must stay fixed after late reader completion')

    def test_blocked_second_write_keeps_known_count_and_pending_unknown_extent(self):
        import threading
        import time
        blocked, released = threading.Event(), threading.Event()
        process = self._fake_process()
        process.poll = lambda: -9
        process.wait = lambda timeout=None: -9
        writes = []
        class PendingInput(io.BytesIO):
            def write(self, value):
                writes.append(len(value))
                if len(writes) == 1:
                    return 1
                blocked.set()
                if not released.wait(2):
                    raise OSError('controlled write release deadline')
                return len(value)
        class RefusalAfterWrite(io.BytesIO):
            def read(self, size=-1):
                if not blocked.wait(2):
                    raise OSError('controlled write entry deadline')
                raise OSError('controlled capture refusal')
        process.stdin, process.stdout = PendingInput(), RefusalAfterWrite()
        original_start, original_join = threading.Thread.start, threading.Thread.join
        workers = []
        def start(thread):
            workers.append(thread)
            original_start(thread)
        try:
            with mock.patch('subprocess.Popen', return_value=process), \
                    mock.patch('threading.Thread.start', start), \
                    mock.patch('threading.Thread.join', return_value=None):
                report, facts = self._capture(lambda: d27_run_case_v1('codec_vectors', b'{}', time.monotonic() + 40))
            before = canonical(facts)
        finally:
            released.set()
            for worker in workers:
                original_join(worker, 3)
        self.assertIsNone(report)
        self.assertEqual(writes, [len(self._wire()), len(self._wire()) - 1])
        self.assertEqual(facts['stdin_bytes'], 1)
        self.assertTrue(facts['stdin_write_attempted'] and facts['stdin_write_in_flight']
                        and facts['stdin_extent_unknown'])
        self.assertFalse(facts['stdin_complete'] or facts['stdin_closed'] or facts['parent_observed_completion'])
        self.assertIn('stdout_read_error', facts['causes'])
        self.assertIn('pipe_completion_unknown', facts['causes'])
        self.assertTrue(canonical(facts) == before, 'pending-write snapshot must stay fixed after a valid late count')

    def test_invalid_stdin_count_preserves_unknown_extent(self):
        import time
        process = self._fake_process()
        class InvalidCount(io.BytesIO):
            def write(self, value):
                return len(value) + 1
        process.stdin = InvalidCount()
        with mock.patch('subprocess.Popen', return_value=process):
            report, facts = self._capture(lambda: d27_run_case_v1('codec_vectors', b'{}', time.monotonic() + 40))
        self.assertIsNone(report)
        self.assertIn('stdin_short_write', facts['causes'])
        self.assertTrue(facts['stdin_extent_unknown'])
        self.assertFalse(facts['stdin_complete'])



    def test_early_cleanup_wait_join_or_status_lateness_refuses_before_child_total_end(self):
        for phase in ('wait', 'join', 'status'):
            with self.subTest(observation=phase):
                clock, polls = [1000.0], [0]
                process = self._fake_process(stdout=self._output())
                class InlineThread:
                    ident = None
                    def __init__(self, target, args=(), daemon=None):
                        self.target, self.args = target, args
                    def start(self):
                        self.ident = 1
                        self.target(*self.args)
                    def join(self, timeout=None):
                        if phase == 'join':clock[0] = 1003.0
                    def is_alive(self):return False
                def status():
                    polls[0] += 1
                    if phase == 'status' and polls[0] >= 3:clock[0] = 1003.0
                    return 0
                def wait(timeout=None):
                    if phase == 'wait':clock[0] = 1003.0
                    return 0
                process.poll, process.wait = status, wait
                with mock.patch('time.monotonic', side_effect=lambda: clock[0]), \
                        mock.patch('threading.Thread', InlineThread), mock.patch('subprocess.Popen', return_value=process):
                    report, facts = self._capture(lambda: d27_run_case_v1('codec_vectors', b'{}', 1040.0))
                self.assertIsNone(report)
                self.assertEqual(facts['causes'], ['cleanup_late'])
                self.assertEqual(facts['cleanup_deadline'], 1003.0)
                self.assertLess(clock[0], facts['child_total_deadline'])
                self.assertTrue(facts['finished_before_deadline'])
                self.assertTrue(facts['child_completion_observed_before_deadline'])
                self.assertFalse(facts['parent_observed_completion'])
                self.assertEqual(facts['returncode'], 0)
                self.assertTrue(facts['reaped'] and facts['threads_joined'])
                self.assertTrue(facts['stdout']['eof'] and facts['stderr']['eof'])
                self.assertEqual(facts['descendant_quiescence'], 'UNKNOWN')

    def test_fixed_main_aliases_use_canonical_priority_without_reopening(self):
        import sys
        names = ('tests.test_accepted_policy_fixture_compiler_gate2_dictionary_v1',
                 'test_accepted_policy_fixture_compiler_gate2_dictionary_v1')
        expected = Path(__file__).with_name('test_accepted_policy_fixture_compiler_gate2_dictionary_v1.py').absolute()
        first = types.ModuleType(names[0]);other = types.ModuleType(names[1])
        for module in (first, other):
            module.__file__ = str(expected)
            module.d27_node_driver_v1 = types.FunctionType(
                (lambda: None).__code__.replace(co_filename=str(expected)), vars(module), 'd27_node_driver_v1')
        for mode in ('canonical', 'discovery', 'same', 'different', 'absent', 'wrong_type', 'wrong_origin', 'bad_canonical'):
            with self.subTest(mode=mode), mock.patch.dict(sys.modules), mock.patch(
                    'builtins.open', side_effect=AssertionError('fixed alias must not reopen')), mock.patch.object(
                    Path, 'open', side_effect=AssertionError('fixed alias must not reopen')):
                for name in names:sys.modules.pop(name, None)
                if mode in ('canonical', 'same', 'different', 'wrong_origin'):sys.modules[names[0]] = first
                if mode == 'same':sys.modules[names[1]] = first
                if mode in ('discovery', 'different', 'bad_canonical'):sys.modules[names[1]] = other
                if mode in ('wrong_type', 'bad_canonical'):sys.modules[names[0]] = types.SimpleNamespace(__name__=names[0])
                if mode == 'wrong_origin':first.__file__ = str(expected.with_name('wrong.py'))
                try:
                    if mode in ('canonical', 'discovery', 'same', 'different'):
                        self.assertIs(self.fixed_loader(), other if mode == 'discovery' else first)
                    else:
                        with self.assertRaisesRegex(RuntimeError, '^d27_held_main_unavailable$'):
                            self.fixed_loader()
                finally:first.__file__ = str(expected)


    def test_geometry_fixed_driver_binding_and_hold_cause_stay_separate(self):
        import time
        raw = canonical({'case': 'geometry'})
        geometry_program = "'use strict';/* separate fixed geometry DATA fixture, never executed */"
        module = self.loaded.return_value
        codec_getter = mock.Mock(return_value=self.fixed_program)
        geometry_getter = mock.Mock(return_value=geometry_program)
        with mock.patch.object(module, 'd27_node_driver_v1', codec_getter), mock.patch.object(
                module, 'd27_geometry_driver_v1', geometry_getter, create=True):
            with mock.patch('subprocess.Popen', return_value=self._fake_process(
                    stdout=self._output('codec_vectors'))) as spawn:
                report, codec = self._capture(lambda: d27_run_case_v1(
                    'codec_vectors', raw, time.monotonic() + 40))
                self.assertTrue(codec['parent_observed_completion'])
                self.assertTrue(report['completed'])
                codec_getter.assert_called_once_with()
                geometry_getter.assert_not_called()
                self.assertEqual(spawn.call_args.args[0][-1], self.fixed_program)
                self.assertEqual(codec['source_kind'], 'd27_fixed_test_driver_v1')
                self.assertEqual(codec['driver_role'], 'codec')
                self.assertEqual(codec['driver_getter'], 'd27_node_driver_v1')
                self.assertEqual(codec['program_bytes'], len(self.fixed_program))
                self.assertEqual(codec['program_sha256'], hashlib.sha256(self.fixed_program.encode('ascii')).hexdigest())
            codec_getter.reset_mock()
            with mock.patch('subprocess.Popen', return_value=self._fake_process(
                    stdout=self._output('geometry', False, 'd27_geometry_hold'))) as spawn:
                report, geometry = self._capture(lambda: d27_run_geometry_v1(
                    raw, time.monotonic() + 40))
                self.assertIsNotNone(report)
                self.assertTrue(geometry['parent_observed_completion'])
                self.assertFalse(geometry['case_completed'])
                self.assertEqual(geometry['case_cause'], 'd27_geometry_hold')
                self.assertEqual(geometry['causes'], [])
                codec_getter.assert_not_called()
                geometry_getter.assert_called_once_with()
                self.assertEqual(spawn.call_args.args[0][-1], geometry_program)
                self.assertEqual(geometry['source_kind'], 'd27_fixed_test_driver_v1')
                self.assertEqual(geometry['driver_role'], 'geometry')
                self.assertEqual(geometry['driver_getter'], 'd27_geometry_driver_v1')
                self.assertEqual(geometry['program_bytes'], len(geometry_program))
                self.assertEqual(geometry['program_sha256'], hashlib.sha256(geometry_program.encode('ascii')).hexdigest())
                self.assertNotEqual(geometry['program_sha256'], codec['program_sha256'])
                self.assertNotEqual(geometry['input_sha256'], codec['input_sha256'])
            geometry_getter.reset_mock()
            with mock.patch('subprocess.Popen', return_value=self._fake_process(
                    stdout=self._output('codec_vectors', False, 'd27_geometry_hold'))) as spawn:
                report, refused = self._capture(lambda: d27_run_case_v1(
                    'codec_vectors', raw, time.monotonic() + 40))
                self.assertIsNone(report)
                self.assertFalse(refused['parent_observed_completion'])
                self.assertIn('child_protocol', refused['causes'])
                codec_getter.assert_called_once_with()
                geometry_getter.assert_not_called()
                self.assertEqual(refused['program_sha256'], codec['program_sha256'])
            for facts in (codec, geometry, refused):
                self.assertFalse(any(key in facts for key in (
                    'stderr_prefix_b64', 'stdout_data', 'stderr_data', 'program', 'raw')))
                self.assertLessEqual(len(canonical(facts)), 32768)

    def test_invalid_geometry_mode_refuses_before_loading_or_spawn(self):
        import time
        end = time.monotonic() + 40
        for case, geometry in (('geometry', 1), ('geometry', None), ('codec_vectors', True), ('geometry', False)):
            with self.subTest(case=case, mode_type=type(geometry).__name__), mock.patch(
                    'subprocess.Popen') as spawn:
                report, facts = self._capture(lambda: _d27_run_fixed_driver_v1(
                    case, b'{}', end, geometry=geometry))
                self.assertIsNone(report)
                self.assertEqual(facts['causes'], ['geometry_invalid'])
                self.assertFalse(facts['spawned'] or facts['stdin_write_attempted']
                                 or facts['stdin_extent_unknown'])
                self.assertFalse(facts['parent_observed_completion'])
                self.loaded.assert_not_called()
                spawn.assert_not_called()

# Authored fixed helper closure; not invoked by ordinary capture tests.
CD_FACTORY_SOURCE = r"""var cdCore=gate2Resume;
if(Object.hasOwn(cdCore,'cd'))throw Error('cd_install_once');
var cdSaved={now:cdCore.now,track:cdCore.track,send:cdCore.send,snapshot:cdCore.snapshot,writerProof:cdCore.writerProof,decode:cdCore.decode,hash:cdCore.hash,canon:cdCore.canon,view:cdCore.view,keys:cdCore.keys,uint:cdCore.uint,sha:cdCore.sha,setupView:cdCore.setupView};
var cdSource,cdHeld,cdWriter,cdSpawn,cdHash,cdPins,cdIndex=0,cdState=null,cdStatePins,cdExternal,cdExternalSHA,cdPrepared=cdCore.last_setup;
function cdGate(s){let n=cdSaved.now();if(n>=s.end)throw Error('cd_original_deadline');return n;}
function cdRecord(v){
 if(v===null||typeof v!=='object')return false;
 let p=Object.getPrototypeOf(v);if(p!==null&&p!==Object.prototype)return false;
 for(let k of Reflect.ownKeys(v)){if(typeof k!=='string')return false;let d=Object.getOwnPropertyDescriptor(v,k);if(!d||d.enumerable!==true||!Object.hasOwn(d,'value'))return false;}return true;
}
function cdStopped(s,role,phase,error){
 let child=s[role+'_child'],f=s[role+'_failure']={cause:'cd_'+role+'_'+phase,initiating_message:String(error?.message??error).replace(/[^\x20-\x7e]/g,'?').slice(0,80),[role+'_attempted']:true,pid:Number.isSafeInteger(child?.pid)?child.pid:null,tracking_completed:false,unknown_closure:true,stdin_extent_unknown:true,stdin_error_handler_installed:false,stdin_close_attempted:false,stdin_close_returned:false,secondary:[],omitted_or_unknown:true};
 if(child){
  let note=label=>{try{if(!f.secondary.includes(label)&&f.secondary.length<9)f.secondary.push(label);}catch(e){}};
  for(let [name,emitter] of [['child',child],['stdin',child.stdin],['stdout',child.stdout],['stderr',child.stderr]])if(emitter&&typeof emitter.on==='function')try{emitter.on('error',()=>note('cd_'+role+'_'+name+'_error'));if(name==='stdin')f.stdin_error_handler_installed=true;}catch(e){note('cd_'+role+'_'+name+'_error_handler');}else if(name==='stdin')note('cd_'+role+(emitter?'_stdin_error_handler_missing':'_stdin_missing'));
  try{if(f.stdin_error_handler_installed&&child.stdin&&typeof child.stdin.end==='function'&&child.stdin.writableEnded!==true){f.stdin_close_attempted=true;child.stdin.end();f.stdin_close_returned=true;}}catch(closeError){note('cd_'+role+'_stdin_close');}
 }
 let stopped=Error(cdSaved.canon(f));stopped.facts=f;return stopped;
}
function cdAuth(){
 if(cdCore.retention_complete!==true||cdCore.setup_success!==true||cdCore.selected.sha256!==cdPins[0]||cdCore.factory_sha256!==cdPins[1]||cdCore.cd_factory_sha256!==cdPins[2]||Object.keys(cdSaved).some(k=>cdCore[k]!==cdSaved[k]))throw Error('cd_core_drift');
 for(let [i,b] of cdHeld.entries()){let d=cdSource[i][1];if(b.length!==d.size_bytes||cdCore.hash(b)!==d.sha256||cdHash('sha1').update('blob '+b.length+'\0').update(b).digest('hex')!==d.git_blob||!cdCore.held[i].equals(b))throw Error('cd_source_binding');}
}
function cdOnce(s,a,b){if(s.split(a).length!==2)throw Error('cd_writer_source');return s.replace(a,b);}
function cdWriterFor(stage){
 let s=cdOnce(cdWriter,'MAX_SELECTED_BYTES=12288','MAX_SELECTED_BYTES=4096');
 s=cdOnce(s,'ACK_CAP=24576','ACK_CAP=16384');s=cdOnce(s,'p,b,12288,gate,comp','p,b,4096,gate,comp');
 s=cdOnce(s,"allocated_bytes']<=12288","allocated_bytes']<=4096");
 return cdOnce(s,'gate2-p0-exception.outer-tool.original.json','gate2-'+stage.toLowerCase()+'.outer-tool.original.json');
}
function cdNative(s){try{
 let raw=s.snapshot.raw[0],k=cdSaved.keys,u=cdSaved.uint;
 if(!s.snapshot.facts.completed||!raw.length||raw.at(-1)!==10||!raw.every(x=>x<128))return false;
 let v=cdSaved.view(raw.subarray(0,-1).toString('ascii'));
 if(s.stage==='D'){
  if(!k(v,'stage,receipt_sha256,receipt_size_bytes,final_measurement,ledger,deadline_ns,finished_ns,control_bytes,aggregate_bytes,passed,finalization_complete,controlled,external_return_required')||v.stage!=='D'||!cdSaved.sha(v.receipt_sha256)||!u(v.receipt_size_bytes,20480n)||v.receipt_size_bytes===0n||v.passed!==true||v.finalization_complete!==true||v.controlled!==false||v.external_return_required!==true||!u(v.control_bytes,524288n)||!u(v.aggregate_bytes,2097152n)||v.aggregate_bytes<v.control_bytes||!u(v.deadline_ns)||!u(v.finished_ns)||v.finished_ns>=v.deadline_ns)return false;
  let m=v.final_measurement,l=v.ledger;return k(m,'c_free_bytes,ext4_used_bytes,project_free_bytes')&&Object.values(m).every(x=>u(x))&&m.c_free_bytes>=43620761600n&&m.project_free_bytes>=1073741824n&&k(l,'remaining_before,charge_bytes,remaining_after')&&Object.values(l).every(x=>u(x,536870912n))&&l.charge_bytes<=2097152n&&l.remaining_before-l.charge_bytes===l.remaining_after;
 }
 if(!k(v,'descriptor,write_facts,completion_deadline_ns,external_approval')||v.external_approval!==false||!u(v.completion_deadline_ns)||v.completion_deadline_ns===0n)return false;
 let d=v.descriptor,q=v.write_facts,path='/home/s-a-balashov/work/vast-fixture-compiler-gate2-465ab7986939c67ae3594344ee3b6266cd2abd7a-01/r1/outputs/'+s.stage+'/outer.invocation.original.json';
 return k(d,'path,size_bytes,sha256')&&d.path===path&&cdSaved.sha(d.sha256)&&u(d.size_bytes,8192n)&&d.size_bytes>0n&&k(q,'path,open_completed,written_bytes,write_extent_unknown,flush_completed,fsync_completed,close_completed,directory_persisted,complete,deadline_failed,failure_causes')&&q.path===path&&q.written_bytes===d.size_bytes&&['open_completed','flush_completed','fsync_completed','close_completed','directory_persisted','complete'].every(k=>q[k]===true)&&q.write_extent_unknown===false&&q.deadline_failed===false&&Array.isArray(q.failure_causes)&&q.failure_causes.length===0;
}catch(e){return false;}}
cdCore.cd={
 begin:async(stage,args,selectedSHA,coreSHA,factorySHA,external)=>{
  let started=cdSaved.now(),pins=[selectedSHA,coreSHA,factorySHA];
  if(pins.some(v=>typeof v!=='string'||!/^[0-9a-f]{64}$/.test(v))||cdCore.retention_complete!==true||cdCore.setup_success!==true||cdCore.selected.sha256!==selectedSHA||cdCore.factory_sha256!==coreSHA||cdCore.cd_factory_sha256!==factorySHA)throw Error('cd_prior_retention');
  if(!['C1','C2','C3','C4','C5','C6','D'].includes(stage)||stage!==['C1','C2','C3','C4','C5','C6','D'][cdIndex]||cdState&&(!cdState.nativeSuccess||!cdState.retained))throw Error('cd_stage_order');
  let s=cdState={stage,start:started,end:started+(stage==='D'?10000:150000),calls:0,retained:false,nativeSuccess:false};
  cdGate(s);
  if(!Array.isArray(args)||args.length!==4||args.some(x=>typeof x!=='string')||!/^[0-9a-f]{40}$/.test(args[0])||!/^[1-9][0-9]{0,4}$/.test(args[1])||+args[1]>32768||!/^[0-9a-f]{64}$/.test(args[2]))throw Error('cd_arguments');
  let prior=args[3]==='-'?[]:args[3].split(',');
  if(prior.length!==cdIndex||prior.some(x=>!/^[1-9][0-9]{0,3}:[0-9a-f]{64}$/.test(x)||+x.split(':')[0]>8192))throw Error('cd_completions');
  if(cdIndex&&cdCore.canon(args.slice(0,3))!==cdCore.canon(cdStatePins))throw Error('cd_packet_drift');
  if(!cdIndex)cdStatePins=args.slice(0,3);
  if(Object.keys(cdSaved).some(k=>cdCore[k]!==cdSaved[k])||cdCore.last_setup!==cdPrepared)throw Error('cd_core_drift');
  if(!cdIndex){
   if(!cdRecord(external))throw Error('cd_external_delivery');
   let k=cdSaved.keys,h=cdSaved.hash,c=cdSaved.canon,sha=cdSaved.sha,r=external.receipt,a=external.approval;
   if(!cdRecord(r)||!cdRecord(a))throw Error('cd_external_delivery');
   if(!k(external,'receipt,approval')||!k(r,'version,context_sha256,record_size_bytes,record_sha256,executor_call_sha256,max_output_tokens,terminal,tool_reference')||r.version!==1||!Number.isSafeInteger(r.record_size_bytes)||r.record_size_bytes<1||r.record_size_bytes>65536||!sha(r.record_sha256)||!sha(r.executor_call_sha256)||r.max_output_tokens!==100000||r.terminal!=='complete_untruncated'||typeof r.tool_reference!=='string'||!/^[\x20-\x7e]{1,96}$/.test(r.tool_reference)||r.context_sha256!==h(c(['vast.gate2.external-delivery.v1',args[0],Number(args[1]),args[2],...pins]))||!k(a,'reference,body_sha256,receipt_sha256')||typeof a.reference!=='string'||a.reference.length>96||!/^https:\/\/github\.com\/lordcoudy\/VAST\/pull\/9#issuecomment-[1-9][0-9]*$/.test(a.reference)||!sha(a.body_sha256)||a.receipt_sha256!==h(c(r)))throw Error('cd_external_delivery');
   let prepared=cdSaved.setupView(cdPrepared);if(prepared.code_commit!==args[0]||prepared.packet.size_bytes!==BigInt(args[1])||prepared.packet.sha256!==args[2])throw Error('cd_prepared_packet');
   cdExternal=c(external);cdExternalSHA=h(cdExternal);
  }else if(typeof external!=='string'||!/^[0-9a-f]{64}$/.test(external)||external!==cdExternalSHA)throw Error('cd_external_delivery');
  if(!cdSource){cdPins=pins;
   ({spawn:cdSpawn}=await import('node:child_process'));cdGate(s);({createHash:cdHash}=await import('node:crypto'));cdGate(s);
   cdSource=cdCore.sources.map(r=>[r[0],{...r[1]}]);cdHeld=cdCore.held.map(b=>Buffer.from(b));cdWriter=cdCore.writer;
  }
  if(cdCore.canon(pins)!==cdCore.canon(cdPins))throw Error('cd_core_drift');cdAuth();cdGate(s);
  let source=cdHeld[1].toString('utf8'),match=source.match(/NATIVE_BOOTSTRAP\s*=\s*r'''([\s\S]*?)'''/);
  if(!match||Buffer.byteLength(match[1])>2048)throw Error('cd_bootstrap');
  let header=Buffer.from(cdCore.canon({current:{[cdSource[1][0].split('/VAST/')[1]]:cdSource[1][1]}})+'\n');
  cdGate(s);let nativePhase='spawn';s.native_attempted=true;
  try{s.native_child=cdSpawn('C:/Windows/System32/wsl.exe',['-d','Ubuntu','-u','s-a-balashov','--cd','/','--exec','/usr/bin/python3','-I','-S','-B','-c',match[1],stage,...args],{cwd:'C:/',stdio:['pipe','pipe','pipe'],windowsHide:true});nativePhase='track';cdGate(s);
   s.child=cdCore.track(s.native_child,[2048,768],s.end);
  }catch(error){throw cdStopped(s,'native',nativePhase,error);}
  cdGate(s);cdCore.send(s.child,header);cdGate(s);return cdCore.cd.poll(1000);
 },
 poll:async(cap=30000)=>{
  let s=cdState;cdGate(s);if(s.final||!Number.isSafeInteger(cap)||cap<1||cap>30000||++s.calls>6)throw Error('cd_poll_state');
  if(!s.child.closed&&!s.child.causes.length)await new Promise(done=>{let timer=setTimeout(done,Math.min(cap,s.end-cdCore.now()));s.child.wake=()=>{clearTimeout(timer);done();};});
  let now=cdCore.now();cdGate(s);
  if(!s.child.closed&&!s.child.causes.length&&s.calls<6){nodeRepl.write(JSON.stringify([0,s.stage,s.child.pid,s.child.returncode]));return;}
  s.final=true;s.snapshot=cdCore.snapshot(s.child,2,[s.start,s.end],now,s.end);s.nativeSuccess=cdNative(s);
  nodeRepl.write(s.snapshot.text);
 },
 finish:async selected=>{
  let s=cdState;if(!s||!s.final||s.writer_attempted)throw Error('cd_writer_once');s.writer_attempted=true;cdGate(s);cdAuth();
  if(typeof selected!=='string'||selected.length<1||selected.length>4096||/[^\x00-\x7f]/.test(selected))throw Error('cd_selected_bound');
  let x=JSON.parse(selected);if(cdCore.canon(x)!==selected||!x.call||x.call.tool!=='mcp__node_repl__js'||x.call.timeout_ms!==32000||!Array.isArray(x.call.codes)||!Array.isArray(x.frames)||x.frames.length!==s.calls||x.frames.length>6||x.call.codes.length!==x.frames.length||x.call.codes.some(v=>typeof v!=='string')||x.frames.at(-1)?.content?.[0]?.text!==s.snapshot.text)throw Error('cd_selected_binding');
  if(x.frames.some((r,i)=>r?.isError!==false||!Array.isArray(r.content)||r.content.length!==1||r.content[0]?.type!=='text'||typeof r.content[0]?.text!=='string'||i<x.frames.length-1&&!r.content[0].text.startsWith('[0,')))throw Error('cd_selected_provider');
  let b=Buffer.from(selected,'ascii');s.selected={size_bytes:b.length,sha256:cdCore.hash(b),selected_base64:b.toString('base64')};
  let program=cdWriterFor(s.stage),sent=false;cdGate(s);
  let writerPhase='spawn';
  try{
  s.writer_child=cdSpawn('C:/Python314/python.exe',['-I','-S','-B','-c',program,cdCore.canon(cdSource.map(r=>r[1]))],{cwd:'C:/',stdio:['pipe','pipe','pipe'],windowsHide:true});writerPhase='track';cdGate(s);
  s.writer=cdCore.track(s.writer_child,[2112,2112],s.end,(state,i,row)=>{
   if(i!==0||sent)return;let line=Buffer.concat(row.raw).toString('latin1');if(line.length>64)throw Error('cd_writer_ready');if(!line.endsWith('\n'))return;
   if(line!=='{"ready":true,"schema_version":1}\n')throw Error('cd_writer_ready');cdGate(s);let remaining=Math.floor(s.end-cdCore.now());if(remaining<1||remaining>150000)throw Error('cd_writer_remaining');
   sent=true;state.ack_ms=remaining;cdCore.send(state,Buffer.concat([Buffer.from(cdCore.canon({remaining_ms:remaining,...s.selected})+'\n'),...cdHeld]));
  });
  }catch(error){throw cdStopped(s,'writer',writerPhase,error);}
  if(!s.writer.closed&&!s.writer.causes.length)await new Promise(done=>{let timer=setTimeout(done,s.end-cdCore.now());s.writer.wake=()=>{clearTimeout(timer);done();};});
  let now=cdCore.now();cdGate(s);s.writerSnapshot=cdCore.snapshot(s.writer,2,[s.start,s.end],now,s.end);nodeRepl.write(s.writerSnapshot.text);
 },
 verifyReturn:delivered=>{
  let s=cdState;cdGate(s);cdAuth();if(s.retained)throw Error('cd_verify_once');cdSaved.writerProof(delivered,s.writerSnapshot,s.selected,s.writer,4096,16384);let after=cdGate(s);
  s.retained=true;if(s.nativeSuccess)cdIndex++;nodeRepl.write(JSON.stringify([3,s.stage,after,s.end,s.nativeSuccess,true,s.selected.sha256]));
 }
};"""

_D27_BROTLI_DATA_PROGRAM = r"""'use strict';
const z=require('node:zlib');let chunks=[],size=0,failed=false;
function fail(c){if(!failed){failed=true;process.stderr.write(c+'\n');process.exitCode=2;}}
if(process.versions.node!=='25.2.1'){fail('d22_node_version');process.stdin.resume();}
process.stdin.on('error',()=>fail('d22_stdin_error'));
process.stdin.on('data',b=>{if(failed)return;size+=b.length;if(size>262144){fail('d22_input_limit');process.stdin.destroy();return;}chunks.push(b);});
process.stdin.on('end',()=>{if(failed)return;try{
 const raw=Buffer.concat(chunks);chunks=[];
 if(raw.length>16384||raw.some(v=>v>127)){fail('d22_ascii_data');return;}
 const packed=z.brotliCompressSync(raw,{params:{[z.constants.BROTLI_PARAM_QUALITY]:11}});
 const back=z.brotliDecompressSync(packed,{maxOutputLength:16384});
 if(!back.equals(raw)){fail('d22_roundtrip');return;}
 process.stdout.write(JSON.stringify({node_version:process.versions.node,packed_b64:packed.toString('base64'),quality:11,roundtrip:true})+'\n');
}catch(e){fail('d22_brotli_error');}});
"""

class D27CompressionError(RuntimeError):
    def __init__(self, metadata):
        self.metadata = metadata
        super().__init__('D22 DATA compression refused: ' + metadata['causes'][0])


class D27ConstructionError(RuntimeError):
    def __init__(self,metadata):
        super().__init__('d27_compression_capture_incomplete')
        self.metadata=json.loads(canonical(metadata))

def d27_compress_data_v1(raw, deadline):
    """Compress ASCII DATA in a fixed builtin-only child; never evaluate the DATA.

    Returns (packed bytes, bounded metadata). Refusals raise D27CompressionError
    carrying the same bounded metadata schema. The absolute caller deadline is
    never reset; eight seconds remain for cleanup and the caller's final return.
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
             'quality': 11, 'roundtrip': False, 'parent_observed_completion': False,
             'descendant_quiescence': 'UNKNOWN', 'input_bytes': None,
             'input_sha256': None, 'packed_bytes': None, 'packed_sha256': None,
             'environment_keys': [], 'program_sha256': hashlib.sha256(_D27_BROTLI_DATA_PROGRAM.encode('ascii')).hexdigest()}
    lock = threading.RLock()
    def cause(value):
        with lock:
            if value not in facts['causes']:
                facts['causes'].append(value)
    def has_causes():
        with lock:
            return bool(facts['causes'])
    def finish(packed=None):
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
        snapshot['stderr_prefix_b64'] = base64.b64encode(prefixes['stderr']).decode('ascii')
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
        snapshot['parent_observed_completion'] = packed is not None and not snapshot['causes']
        encoded = canonical(snapshot)
        if len(encoded) > 32768:
            raise RuntimeError('D22 compression metadata bound')
        # Publication is immutable; the shared capture does not establish
        # continuous custody or quiescence of unjoined workers/descendants.
        frozen = json.loads(encoded)
        if frozen['causes']:
            raise D27CompressionError(frozen)
        return packed, frozen
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
    if type(raw) is not bytes:
        cause('input_type');return finish()
    if len(raw) > 16384:
        cause('input_limit');return finish()
    if not raw.isascii():
        cause('input_ascii');return finish()
    with lock:
        facts.update(input_bytes=len(raw), input_sha256=hashlib.sha256(raw).hexdigest())
    work_end = min(started + 27, end - 8)
    child_total_end = min(started + 30, end - 5)
    cleanup_end = min(child_total_end, work_end + 3)
    with lock:
        facts.update(started_monotonic=started, caller_deadline=end, work_deadline=work_end,
                     child_total_deadline=child_total_end, cleanup_deadline=cleanup_end, child_total_limit_seconds=30,
                     child_work_limit_seconds=27, cleanup_limit_seconds=3, final_reserve_seconds=5)
    if time.monotonic() >= work_end:
        cause('deadline_no_window');return finish()
    node = shutil.which('node') or shutil.which('node.exe')
    if node is None:
        cause('node_unavailable');return finish()
    try:
        node = str(Path(node).resolve(strict=True))
        environment = {'PATH': str(Path(node).parent)}
        if os.name == 'nt':
            environment['SystemRoot'] = os.environ['SystemRoot']
        argv = [node, '--max-old-space-size=256', '--input-type=commonjs', '-e', _D27_BROTLI_DATA_PROGRAM]
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
                    if not part:
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
        if facts['returncode'] != 0:
            cause('child_status')
        if not facts['stdin_complete'] or not facts['stdin_closed'] or not all(c['eof'] for c in channels.values()):
            cause('io_completion_unknown')
        stdout_data, stderr_data = bytes(buffers['stdout']), bytes(buffers['stderr'])
    if has_causes():
        return finish()
    if stderr_data:
        cause('unexpected_stderr');return finish()
    try:
        def unique_pairs(rows):
            result = dict(rows)
            if len(result) != len(rows):
                raise ValueError('duplicate DATA result field')
            return result
        result = json.loads(stdout_data, object_pairs_hook=unique_pairs)
        if (type(result) is not dict or set(result) != {'node_version', 'packed_b64', 'quality', 'roundtrip'}
                or result['node_version'] != '25.2.1' or type(result['quality']) is not int
                or result['quality'] != 11 or result['roundtrip'] is not True
                or type(result['packed_b64']) is not str or stdout_data != canonical(result) + b'\n'):
            raise ValueError('invalid DATA result')
        if len(result['packed_b64']) > 4 * ((32768 + 2) // 3):
            raise ValueError('DATA encoding bound')
        packed = base64.b64decode(result['packed_b64'], validate=True)
        if len(packed) > 32768 or base64.b64encode(packed).decode('ascii') != result['packed_b64']:
            raise ValueError('invalid DATA encoding')
    except (ValueError, TypeError, RecursionError, OverflowError):
        cause('child_protocol');return finish()
    with lock:
        facts.update(node_version=result['node_version'], roundtrip=True,
                     packed_bytes=len(packed), packed_sha256=hashlib.sha256(packed).hexdigest())
    return finish(packed)

def d27_node_codec_v1(codec):
    """Authenticate the fixed v4 literal and its dependency-closed decoder role."""
    m=_d27_main_module_v1()
    pins=m.D27_CODEC_SOURCE_PINS
    if type(codec) is not str or not codec.isascii() or codec is not m.D27_WIRE_CODEC:
        raise RuntimeError('d27_codec_source_kind')
    def pin(s):
        raw=s.encode('ascii')
        return len(raw),hashlib.sha256(raw).hexdigest()
    if pin(codec)!=pins[0] or pins[0][0]>6907:
        raise RuntimeError('d27_codec_source_binding')
    marker='function gate2WireEncode(text,tag,sha,canon,guard){'
    if codec.count(marker)!=1:raise RuntimeError('d27_codec_marker')
    at=codec.index(marker);prefix,tail=codec[:at],codec[at:]
    if (pin(prefix)!=pins[1] or pin(tail)!=pins[2] or prefix+tail!=codec
            or pin(codec[:949])!=(949,'d15dca0b287943b37e43143397e8c753f6bca0170862d3d924ca15e01965cd7b')):
        raise RuntimeError('d27_codec_role_binding')
    return prefix,{'kind':'d27_node_codec_role_v1','full_codec_bytes':pins[0][0],
        'full_codec_sha256':pins[0][1],'node_codec_bytes':pins[1][0],'node_codec_sha256':pins[1][1],
        'excluded_encoder_bytes':pins[2][0],'excluded_encoder_sha256':pins[2][1],
        'marker_occurrences':1,'role_is_exact_prefix':True,'encoder_excluded':True}

def d27_finalizer_source_v1(initial, deferred, codec, main, caller):
    m = _d27_main_module_v1()
    if main is not m:
        raise RuntimeError('d27_finalizer_main_binding')
    expected, _ = d27_node_codec_v1(vars(m).get('D27_WIRE_CODEC'))
    if codec != expected or _d27_main_module_v1() is not m:
        raise RuntimeError('d27_finalizer_role_binding')
    # Existing construction preserves every effect/custody/clock site. The one
    # selected-view call changes version only; the supplied role is already v4.
    finalizer, old_facts = m._d27_finalizer_base_v1(initial, deferred, codec, main, caller)
    before = "gate2WireDecode(text,'gate2-selected-lz77-v1',g2.hash,gate2Canonical,guard)"
    after = "gate2WireDecode(text,'gate2-selected-lzw-v4',g2.hash,gate2Canonical,guard)"
    if finalizer.count(before) != 1:
        raise RuntimeError('d27_finalizer_tag_site')
    updated = finalizer.replace(before, after, 1)
    if updated.replace(after, before, 1) != finalizer or before in updated:
        raise RuntimeError('d27_finalizer_tag_inverse')
    facts = dict(old_facts)
    facts.update(finalizer_size_bytes=len(updated),
                 finalizer_sha256=hashlib.sha256(updated.encode('ascii')).hexdigest())
    return updated, facts

def d27_root_wire_sources_v1(codec):
    m = _d27_main_module_v1()
    d27_node_codec_v1(codec)
    if _d27_main_module_v1() is not m:
        raise RuntimeError('d27_root_main_binding')
    # The legacy builder remains unchanged. Both returned variants have exactly
    # one selected and one observed call site; no version autodetection exists.
    sources = m._d27_root_wire_base_v1(codec)
    result = {}
    for role in ('orchestrator', 'receiver'):
        old = sources[role]
        new = old
        for before, after in (('gate2-selected-lz77-v1', 'gate2-selected-lzw-v4'),
                              ('gate2-observed-lz77-v1', 'gate2-observed-lzw-v4')):
            if new.count(before) != 1:
                raise RuntimeError('d27_root_tag_site')
            new = new.replace(before, after, 1)
        restored = new.replace('gate2-selected-lzw-v4', 'gate2-selected-lz77-v1').replace(
            'gate2-observed-lzw-v4', 'gate2-observed-lz77-v1')
        if restored != old or 'gate2-selected-lz77-v1' in new or 'gate2-observed-lz77-v1' in new:
            raise RuntimeError('d27_root_tag_inverse')
        result[role] = new
    return result


# Exact finite pure formatter closure; the four external files remain DATA only.
def canonical_json_v1(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("ascii")
SOURCE_LIMIT = 8 * 1024 * 1024

STRING_LIMIT = 1024 * 1024

TABLE_LIMIT = 4096

def _json_bound(value, *, depth=0, ancestors=None, nodes=None):
    """Count before serialization; reject cycles, huge scalars and fanout first."""
    if ancestors is None:
        ancestors, nodes = set(), [0]
    nodes[0] += 1
    if depth > 32 or nodes[0] > 65536:
        raise ValueError("fixture JSON depth/node bound exceeded")
    if type(value) is str:
        if len(value) > STRING_LIMIT:
            raise ValueError("fixture JSON string bound exceeded")
        size = 2
        for char in value:
            point = ord(char)
            size += (2 if char in '\\"\b\f\n\r\t' else
                     6 if point < 32 or 127 <= point <= 65535 else 12 if point > 65535 else 1)
            if size > SOURCE_LIMIT:
                raise ValueError("fixture JSON byte bound exceeded")
        return size
    if value is None or type(value) is bool:
        return 5
    if type(value) is int:
        if value.bit_length() > 64:
            raise ValueError("fixture JSON integer bound exceeded")
        return 21
    if type(value) is float and math.isfinite(value):
        return 32
    if type(value) not in (dict, list) or len(value) > TABLE_LIMIT or id(value) in ancestors:
        raise ValueError("fixture JSON type/container bound exceeded")
    ancestors.add(id(value))
    try:
        size = 2
        items = value.items() if type(value) is dict else ((None, item) for item in value)
        for key, item in items:
            if type(value) is dict:
                if type(key) is not str:
                    raise ValueError("fixture JSON requires string keys")
                size += _json_bound(key, depth=depth+1, ancestors=ancestors, nodes=nodes) + 1
            size += _json_bound(item, depth=depth+1, ancestors=ancestors, nodes=nodes) + 1
            if size > SOURCE_LIMIT:
                raise ValueError("fixture JSON byte bound exceeded")
        return size
    finally:
        ancestors.remove(id(value))
PRODUCER='465ab7986939c67ae3594344ee3b6266cd2abd7a'

OWNER=PurePosixPath('/home/s-a-balashov/work/vast-fixture-compiler-gate2-'+PRODUCER+'-01')

ROOT,AUX=OWNER/'r1',OWNER/'r1.operator-originals'

class ResumeRefusal(RuntimeError):
  def __init__(self,cause,facts=None):
    super().__init__(cause)
    self.cause=cause
    self.facts={} if facts is None else facts
CONTROL_LIMIT = 4194304

RESUME_PRODUCER_COMMIT_V1 = "465ab7986939c67ae3594344ee3b6266cd2abd7a"

RESUME_OWNER_ROOT_V1 = Path("/home/s-a-balashov/work/vast-fixture-compiler-gate2-" + RESUME_PRODUCER_COMMIT_V1 + "-01")

RESUME_ROOT_V1 = RESUME_OWNER_ROOT_V1 / "r1"

class Gate2Refusal(RuntimeError):
  def __init__(self, cause, facts=None):
    super().__init__(cause)
    self.cause, self.facts = cause, {} if facts is None else facts

def _require(condition, cause):
  if not condition:
    raise Gate2Refusal(cause)

def _sha(raw):
  return hashlib.sha256(raw).hexdigest()

def native_failure_bytes_v1(error):
  cause = getattr(error, "cause", type(error).__name__)
  def label(value):
    return re.sub("[^a-zA-Z0-9_.:/-]", "?", value[:32]) if type(value) is str else "unknown"
  facts = getattr(error, "facts", None)
  value = {"cause": label(cause), "causes": [], "physical_acceptance": False,
    "external_status_eof_required": True, "facts_unknown": True, "facts_remainder_unknown": True}
  if type(cause) is not str or label(cause) != cause:
    value["cause_remainder_unknown"] = True
  pending, seen, observations = [("", facts, 0)], set(), []
  for _ in range(24):
    if not pending:
      break
    path, row, depth = pending.pop(0)
    if type(row) is not dict or id(row) in seen:
      continue
    seen.add(id(row))
    causes = row.get("causes", row.get("failure_causes", []))
    candidates = ([row["cause"]] if type(row.get("cause")) is str else [])
    if type(causes) is list:
      candidates += causes[:4]
    for item in candidates:
      item = label(item)
      if item not in value["causes"] and len(value["causes"]) < 4:
        value["causes"].append(item)
    for key in ("write_extent_unknown", "unknown_closure", "closed", "stdout_eof", "stderr_eof", "returncode", "written_bytes"):
      item = row.get(key)
      if len(observations) < 2 and (type(item) is bool or type(item) is int and -(2**63) <= item < 2**63):
        observations.append([path, key, item])
    if depth < 3:
      for key in ("failure_facts", "owner_facts", "refusal_write_failure", "write_facts", "child", "files", "stdout", "stderr"):
        if type(row.get(key)) is dict:
          pending.append(((path + "." + key).lstrip("."), row[key], depth + 1))
  if observations:
    value["observations"] = observations
  try:
    _require(_json_bound(facts) <= CONTROL_LIMIT, "native_failure_facts_bound")
    raw = canonical_json_v1(facts)
    value.update(facts_unknown=False, facts_bytes=len(raw), facts_sha256=_sha(raw),
      facts_prefix_base64=base64.b64encode(raw[:16]).decode("ascii"))
  except (Gate2Refusal, ValueError, TypeError, RecursionError, OverflowError):
    pass
  raw = canonical_json_v1(value) + b"\n"
  if len(raw) > 768:
    value.pop("facts_prefix_base64", None)
    raw = canonical_json_v1(value) + b"\n"
  while len(raw) > 768 and value.get("observations"):
    value["observations"].pop()
    raw = canonical_json_v1(value) + b"\n"
  return raw

def resume_terminal_v1(*, error=None, result=None):
  value = {'completed':error is None, 'physical_acceptance':False,
      'external_terminal_and_packet_review_required':True,'native_raw_originals_retained':0}
  if error is None:
    value.update(result or {})
  else:
    facts = getattr(error, 'facts', {})
    raw = None
    try:
      _require(_json_bound(facts)<=CONTROL_LIMIT,'terminal_facts_bound')
      raw=canonical_json_v1(facts)
    except (Gate2Refusal,ValueError,TypeError,RecursionError,OverflowError): pass
    causes, known = [str(error)[:64]], []
    keys = {'pid','returncode','stdout_eof','stderr_eof','unknown_closure','close_completed',
        'stdout_bytes','stderr_bytes','stdout_sha256','stderr_sha256','stdout_prefix_base64','stderr_prefix_base64',
        'eof_stdout','eof_stderr','forced_parent_termination','write_extent_unknown',
        'request_write_extent_unknown','reply_write_extent_unknown',
        'fsync_completed','extent_unknown','written_bytes','late','completed','linux_child_closure','stdin_closed','stdin_extent_unknown'}
    def visit(node, path='', depth=0):
      if depth > 7 or len(known) >= 16:
        return
      if type(node) is dict:
        for role in ('control_record','completion_record'):
          if type(node.get(role)) is dict: visit(node[role],path+'/'+role,depth+1)
        for count,(key,item) in enumerate(node.items()):
          if count>=24: break
          if key in ('control_record','completion_record') or key=='late' and path.endswith('/write_proof'): continue
          if key == 'secondary' or key == 'causes':
            if type(item) is list:
              for cause in item[:5]:
                if type(cause) is str and cause[:48] not in causes and len(causes) < 5:
                  causes.append(cause[:48])
          if key in keys and (item is None or type(item) in (bool,str) or type(item) is int and -2**64<=item<2**64) and len(known) < 16:
            known.append({'path':(path+'/'+key)[-48:], 'value':item[:64] if type(item) is str else item})
          elif type(item) in (dict,list):
            visit(item, path+'/'+(key[:48] if type(key) is str else '?'), depth+1)
      elif type(node) is list:
        for i, item in enumerate(node[:4]): visit(item,path+'/'+str(i),depth+1)
    visit(facts)
    value.update(causes=[c.encode('ascii','backslashreplace').decode()[:64] for c in causes],
      cause_remainder_unknown=True, known=known, omitted_or_unknown=True)
    if raw is None: value['facts_unknown']=True
    else: value.update(facts_bytes=len(raw),facts_sha256=_sha(raw),prefix_base64=base64.b64encode(raw[:48]).decode('ascii'))
    original_count=len(known)
    while len(canonical_json_v1(value))+1>2048 and known:
      known.pop();value['known_omitted']=original_count-len(known)
  raw = canonical_json_v1(value)
  _require(len(raw) + 1 <= 2048, 'terminal_bound')
  return raw

def _invocation_record_v1(stage, commit, packet_sha, result_sha, accounting_sha, previous_completion_sha):
  return {"schema_version": 1, "artifact_kind": "vast_fixture_compiler_gate2_c_invocation_v1", "stage": stage,
    "code_commit": commit, "packet_sha256": packet_sha, "result_sha256": result_sha,
    "accounting_sha256": accounting_sha, "previous_completion_sha256": previous_completion_sha,
    "returned_successfully": True}

def _d27_setup_success_output_v1(anchor=1755772592209100):
        desc=lambda name:{'path':AUX.as_posix()+'/'+name,'size_bytes':4096,'sha256':hashlib.sha256(name.encode()).hexdigest()}
        meter={'native_pid':4194304,'fresh_interval_N':2650112,'native_bytes':1048576,'outside_bytes':524288,
            'active_f2_debit':7995392,'outstanding_tail_bytes':45312,'historical_closing_meter_available':False,
            'physical_acceptance':False,'final_measurement':{'c_free_bytes':99685629952,'ext4_used_bytes':313124622336,
            'project_free_bytes':100000000000,'fragment_bytes':4096,'backing_device':2112}}
        return resume_terminal_v1(result={'code_commit':hashlib.sha1(b'controlled-current-review').hexdigest(),
            'packet':{'path':ROOT.as_posix()+'/gate2.packet.original.json','size_bytes':32768,'sha256':hashlib.sha256(b'packet').hexdigest()},
            'authority':desc('operator.authority.original.json'),'events':desc('resume.events.original.json'),'final_meter':meter,
            'final_return':[4294967295,0,True,True,4096,hashlib.sha256(b'final-return').hexdigest(),0,hashlib.sha256(b'').hexdigest()],
            'windows_start_ns':anchor,'absolute_deadline_ns':anchor+150000000000,'c_or_d_invoked':False}).decode()+'\n'

def _d27_setup_failure_output_v1(unicode=False):
        import base64
        rows=[{'stdout_sha256':hashlib.sha256(('stdout'+str(i)).encode()).hexdigest(),
               'stderr_sha256':hashlib.sha256(('stderr'+str(i)).encode()).hexdigest(),
               'stdout_prefix_base64':base64.b64encode(hashlib.sha512(('prefix'+str(i)).encode()).digest()[:48]).decode(),
               'linux_child_closure':'unknown_'+hashlib.sha256(('closure'+str(i)).encode()).hexdigest()[:56]} for i in range(4)]
        candidates=[]
        for n in range(1,65):
            facts={'failure_facts':rows,'causes':[hashlib.sha256(('cause'+str(i)).encode()).hexdigest()[:n] for i in range(4)],
              'completion_record':{'write_proof':{'returncode':None,'eof_stdout':True,'eof_stderr':True,'close_completed':False,'write_extent_unknown':True}}}
            if unicode:facts['failure_facts'][0]['linux_child_closure']='\U0001f4a5'*n
            candidates.append(resume_terminal_v1(error=ResumeRefusal(('\U0001f4a5' if unicode else 'observed_failure_')*n,facts)).decode()+'\n')
        return max(candidates,key=len)

def _d27_geometry_program_v1():
    """Return only the fixed inert geometry TEST program from the held new pair."""
    m=_d27_main_module_v1()
    codec=m.D27_WIRE_CODEC
    d27_node_codec_v1(codec)
    model,stdio=m.D27_GEOMETRY_MODEL,m.D27_GEOMETRY_STDIO
    for source,pin in zip((model,stdio),m.D27_GEOMETRY_SOURCE_PINS):
        if type(source) is not str or not source.isascii() or (len(source),hashlib.sha256(source.encode('ascii')).hexdigest())!=pin:
            raise RuntimeError('d27_geometry_source_binding')
    if (model.count('gate2-selected-lzw-v4')!=2 or model.count('gate2-observed-lzw-v4')!=2
            or stdio.count('gate2-selected-lzw-v4')!=2 or 'lzss-v' in model+stdio
            or _d27_main_module_v1() is not m):
        raise RuntimeError('d27_geometry_version_binding')
    value=m.ROOT_ENCODER+'\n'+m.ROOT_SHA256+'\n'+codec+'\n'+model+'\n'+stdio
    if not value.isascii() or not 0<len(value)<=24576:
        raise RuntimeError('d27_geometry_program_bound')
    return value

def d27_inert_bundle_v1(deadline):
    import base64
    import math
    import sys
    import time
    caller=sys.modules[__name__]

    last = None
    def gate():
        nonlocal last
        now = time.monotonic()
        if (type(deadline) not in (int, float) or not math.isfinite(deadline)
                or not math.isfinite(now) or deadline - now > 300
                or (last is not None and now < last)
                or now >= deadline - 5):
            raise RuntimeError('d27_construction_deadline')
        last = now

    def canonical(value):
        return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True,
                          allow_nan=False).encode('ascii')

    def digest(value):
        return hashlib.sha256(value).hexdigest()

    gate()
    d27_assert_fixed_data_v1(deadline)
    m = _d27_main_module_v1()
    node_codec, role_facts = d27_node_codec_v1(vars(m).get('D27_WIRE_CODEC'))
    root = Path(m.__file__).resolve().parents[1]
    descriptors = (
        ('tests/fixtures/accepted_policy_fixture_compiler_component_v1.py', 32732,
         '329fb13f2c6dcee0872e5a29ec1fd769dc6e57ce92ee1076fef6737f1da86d88',
         '5a342c2c2efa44aa5add3f91ae94518c143acece'),
        ('tests/fixtures/accepted_policy_fixture_compiler_gate2_resume_v1.py', 32739,
         '5fd7d2d6ee62ff584d2a4662757ca804a3d3300d30bb966319901870c4c85670',
         'cc9b6a1b7e6e6ff2f9b750ea67b20cf7213d09b0'))
    held = []
    source_rows = []
    for rel, size, sha, blob in descriptors:
        gate()
        with (root / rel).open('rb') as handle:
            raw = handle.read(32769)
        gate()
        if (len(raw), digest(raw), hashlib.sha1(b'blob ' + str(len(raw)).encode()
                + b'\0' + raw).hexdigest()) != (size, sha, blob):
            raise RuntimeError('d27_fixture_binding')
        held.append(base64.b64encode(raw).decode('ascii'))
        source_rows.append({'size_bytes': size, 'sha256': sha, 'git_blob': blob})
    gate()
    initial, baseline, parts, source_facts = m.d27_phase_initial_v1(deadline)
    compressed = source_facts['compression']
    if (compressed['parent_observed_completion'] is not True or compressed['causes']
            or compressed['returncode'] != 0 or compressed['timed_out']
            or compressed['kill_requested'] or not compressed['reaped']
            or not compressed['threads_joined']
            or compressed['started_monotonic'] + compressed['elapsed_seconds']
               >= compressed['cleanup_deadline']
            or any(not compressed[name]['eof'] or compressed[name]['overflow']
                   or compressed[name]['io_error'] is not None
                   or compressed[name]['unknown_remainder'] for name in ('stdout', 'stderr'))):
        raise D27ConstructionError(compressed)
    if (set(source_facts) != set('kind source_bytes source_sha256 escaped_source_bytes baseline_bytes baseline_sha256 original_builder_bytes original_builder_sha256 baseline_body_bytes baseline_body_sha256 prefix_bytes prefix_sha256 decoder_bytes decoder_sha256 canonical_data_bytes canonical_data_sha256 compressed_data_bytes compressed_data_sha256 base64_data_bytes base64_data_sha256 data_fields strings_field_absent deferred_definition_bytes deferred_definition_sha256 exact_decoder_inverse exact_phase_inverse exact_inverse_source source_contribution_fits source_only_over_cap_by complete_geometry_qualified behavior_conformance_complete finalizer_implemented generated_operational_program_executed generated_full_subject_files_written status task_2_10_complete compression'.split())
            or source_facts['kind'] != 'd24_initial_source_only_v1'
            or set(role_facts) != set('kind full_codec_bytes full_codec_sha256 node_codec_bytes node_codec_sha256 excluded_encoder_bytes excluded_encoder_sha256 marker_occurrences role_is_exact_prefix encoder_excluded'.split())
            or set(parts) != {'phase_body', 'restored', 'deferred'}
            or parts['restored'] != baseline
            or (len(initial), digest(initial.encode('ascii'))) !=
               (source_facts['source_bytes'], source_facts['source_sha256'])
            or (len(baseline), digest(baseline.encode('ascii'))) !=
               (source_facts['baseline_bytes'], source_facts['baseline_sha256'])
            or (len(parts['deferred']), digest(parts['deferred'].encode('ascii'))) !=
               (source_facts['deferred_definition_bytes'], source_facts['deferred_definition_sha256'])
            or not initial.startswith(m.D22_PREFIX) or source_facts['data_fields'] != 9
            or source_facts['strings_field_absent'] is not True
            or any(source_facts[name] is not True for name in
                   ('exact_decoder_inverse', 'exact_phase_inverse', 'exact_inverse_source'))):
        raise RuntimeError('d27_initial_binding')
    expected_initial = (
        (source_facts['source_bytes'], source_facts['source_sha256'],
         14162, '4032a534147aada87931734f3b06cde67988d62c75851b959945399843a3770d'),
        (source_facts['canonical_data_bytes'], source_facts['canonical_data_sha256'],
         6566, '8ca48e37f97d03af660960f75afab79db162e8f8997f39f6c1c5c55dd896c97e'),
        (source_facts['compressed_data_bytes'], source_facts['compressed_data_sha256'],
         2365, 'a7caf17aa8d2d5d6beb60880d415e7328947d188623bf5fa0d1ad566e1fd2f2f'))
    if any((size, sha) != (expected_size, expected_sha)
           for size, sha, expected_size, expected_sha in expected_initial):
        raise RuntimeError('d27_unchanged_initial_binding')
    gate()
    program = m.d27_geometry_driver_v1()
    if type(program) is not str or not program.isascii() or not 0 < len(program) <= 24576:
        raise RuntimeError('d27_geometry_driver_binding')
    driver_facts = {'source_kind': 'd27_fixed_test_driver_v1', 'driver_role': 'geometry',
                    'driver_getter': 'd27_geometry_driver_v1', 'program_bytes': len(program),
                    'program_sha256': digest(program.encode('ascii'))}
    gate()
    finalizer, finalizer_facts = d27_finalizer_source_v1(
        initial, parts['deferred'], node_codec, m, caller)
    if (finalizer.count(node_codec) != 1 or m.D27_WIRE_CODEC in finalizer
            or 'function gate2WireEncode(text,tag,sha,canon,guard){' in finalizer
            or finalizer.count(m.ROOT_ENCODER) != 1):
        raise RuntimeError('d27_finalizer_codec_role')
    root_sources = d27_root_wire_sources_v1(m.D27_WIRE_CODEC)
    commit = hashlib.sha1(b'controlled-current-review').hexdigest()
    packet_sha = digest(b'packet')
    factory_sha = digest(caller.CD_FACTORY_SOURCE.encode('ascii'))
    profile = {'max_output_tokens': 100000, 'max_record_bytes': 65536}
    expected = {'code_commit': commit, 'core_sha256': digest(initial.encode('ascii')),
                'factory_sha256': factory_sha}
    prefix = ('// @exec: {"yield_time_ms":1,"max_output_tokens":100000}\n'
              + m.ROOT_ENCODER + '\n' + m.ROOT_SHA256 + '\n' + m.D27_WIRE_CODEC + '\n'
              + root_sources['orchestrator'] + '\n' + root_sources['receiver']
              + '\nconst profile=' + canonical(profile).decode('ascii')
              + ';const record=await gate2Complete(tools,')
    suffix = (',profile,' + canonical(expected).decode('ascii')
              + ');text(gate2Export(record,profile));\n')
    # Factor only the fixed TEST transport. The complete executor below is
    # independently pinned, and the fixed driver reconstructs exactly these
    # bytes in RAM for full-chain measurement. Operational wires stay complete.
    executor = (prefix + json.dumps(initial, ensure_ascii=True, separators=(',', ':'))
                + ',' + json.dumps(finalizer, ensure_ascii=True, separators=(',', ':')) + suffix)
    executor_pin = {'size_bytes': len(executor), 'sha256': digest(executor.encode('ascii'))}
    success = _d27_setup_success_output_v1()
    structured = _d27_setup_failure_output_v1()
    unicode_failure = _d27_setup_failure_output_v1(unicode=True)
    forms = [
        {'id': 'success', 'stdout': success, 'stderr': '', 'success': True},
        {'id': 'structured_failure', 'stdout': '', 'stderr': structured,
         'success': False, 'failure': True},
        {'id': 'unicode_failure', 'stdout': '', 'stderr': unicode_failure,
         'success': False, 'failure': True},
        {'id': 'partial_emission', 'stdout': success[:1024], 'stderr': '',
         'success': False, 'partial': True},
        {'id': 'unknown_closure', 'stdout': success, 'stderr': '',
         'success': False, 'unknown': True},
        {'id': 'setup_refusal', 'stdout': '{}\n', 'stderr': '', 'success': False}]
    gate()
    # This is a DECLARED FUTURE CONTROLLED chain model with every field present.
    # No historical output is filtered or claimed to be a new acquired original.
    chain = [
        {'call': {'type': 'custom_tool_call', 'id': 'd27_exec', 'status': 'completed',
                  'call_id': 'd27_exec_call', 'name': 'exec', 'input': '',
                  'internal_chat_message_metadata_passthrough': {'turn_id': 'd27_controlled_geometry',
                                                              'create_time': 1792314000.25}},
         'result': {'type': 'custom_tool_call_output', 'id': 'd27_exec_output',
                    'call_id': 'd27_exec_call',
                    'output': 'Script running with cell ID d27geometry\nWall time 0.0 seconds\nOutput:\n',
                    'internal_chat_message_metadata_passthrough': {'turn_id': 'd27_controlled_geometry',
                                                                'create_time': 1792314000.5}}},
        {'call': {'type': 'function_call', 'id': 'd27_wait', 'name': 'wait',
                  'arguments': canonical({'cell_id': 'd27geometry', 'max_tokens': 100000,
                                          'yield_time_ms': 1000}).decode('ascii'),
                  'call_id': 'd27_wait_call',
                  'internal_chat_message_metadata_passthrough': {'turn_id': 'd27_controlled_geometry',
                                                              'create_time': 1792314001.25}},
         'result': {'type': 'function_call_output', 'id': 'd27_wait_output',
                    'call_id': 'd27_wait_call',
                    'output': [{'type': 'input_text',
                                'text': 'Script completed\nWall time 0.0 seconds\nOutput:\n'},
                               {'type': 'input_text', 'text': ''}],
                    'internal_chat_message_metadata_passthrough': {'turn_id': 'd27_controlled_geometry',
                                                                'create_time': 1792314001.5}}}]
    # Pure canonical native-format DATA, including the genuine C failure
    # formatter. No native_main, writer, temporary directory or stage is called.
    native_root = RESUME_OWNER_ROOT_V1.as_posix() + '/r1'
    if len(native_root) != 98:
        raise RuntimeError('d27_native_model_root')
    maximum = 2**64 - 1
    completions = []
    later = []
    native_input = canonical({'current': {descriptors[1][0]: source_rows[1]}}).decode('ascii') + '\n'
    for stage in ('C1', 'C2', 'C3', 'C4', 'C5', 'C6'):
        gate()
        previous = None if stage == 'C1' else completions[-1]['descriptor']['sha256']
        record = _invocation_record_v1(stage, commit, packet_sha, digest(stage.encode()),
                                         digest(('accounting-' + stage).encode()), previous)
        raw = canonical(record)
        path = native_root + '/outputs/' + stage + '/outer.invocation.original.json'
        complete = {'descriptor': {'path': path, 'size_bytes': len(raw), 'sha256': digest(raw)},
                    'write_facts': {'path': path, 'open_completed': True, 'written_bytes': len(raw),
                                    'write_extent_unknown': False, 'flush_completed': True,
                                    'fsync_completed': True, 'close_completed': True,
                                    'directory_persisted': True, 'complete': True,
                                    'deadline_failed': False, 'failure_causes': []},
                    'completion_deadline_ns': maximum, 'external_approval': False}
        args = [commit, '32768', packet_sha,
                '-' if not completions else ','.join(
                    str(row['descriptor']['size_bytes']) + ':' + row['descriptor']['sha256']
                    for row in completions)]
        completions.append(complete)
        if stage in ('C1', 'C6'):
            stdout = canonical_json_v1(complete).decode('ascii') + '\n'
            failure = native_failure_bytes_v1(Gate2Refusal('native_stdout_deadline',
                {'written_bytes': len(stdout), 'write_extent_unknown': False,
                 'flush_completed': False})).decode('ascii')
            if len(stdout.encode('ascii')) > 2048 or len(failure.encode('ascii')) > 768:
                raise RuntimeError('d27_c_model_pipe_bound')
            for failed in (False, True):
                later.append({'id': stage + ('_failure' if failed else '_success'),
                              'stage': stage, 'args': args, 'stdout': stdout,
                              'stderr': failure if failed else '', 'failure': failed,
                              'duration_ms': 150000, 'native_input': native_input})
    summary = {'stage': 'D', 'receipt_sha256': digest(b'controlled-D-receipt'),
               'receipt_size_bytes': 20480,
               'final_measurement': {key: maximum for key in
                                     ('c_free_bytes', 'ext4_used_bytes', 'project_free_bytes')},
               'ledger': {'remaining_before': 536870912, 'charge_bytes': 2097152,
                          'remaining_after': 534773760},
               'deadline_ns': maximum, 'finished_ns': maximum - 1,
               'control_bytes': 524288, 'aggregate_bytes': 2097152, 'passed': True,
               'finalization_complete': True, 'controlled': False, 'external_return_required': True}
    d_stdout = canonical_json_v1(summary).decode('ascii') + '\n'
    d_failure = native_failure_bytes_v1(Gate2Refusal('native_stdout_deadline',
        {'written_bytes': len(d_stdout), 'write_extent_unknown': False,
         'flush_completed': False})).decode('ascii')
    if len(d_stdout.encode('ascii')) > 768 or len(d_failure.encode('ascii')) > 768:
        raise RuntimeError('d27_d_model_pipe_bound')
    d_args = [commit, '32768', packet_sha, ','.join(
        str(row['descriptor']['size_bytes']) + ':' + row['descriptor']['sha256']
        for row in completions)]
    for failed in (False, True):
        later.append({'id': 'D_failure' if failed else 'D_success', 'stage': 'D',
                      'args': d_args, 'stdout': d_stdout, 'stderr': d_failure if failed else '',
                      'failure': failed, 'duration_ms': 10000, 'native_input': native_input})
    approval_template = {
        'version': 1, 'kind': 'vast_gate2_external_delivery_approval_v1',
        'receipt_sha256': None, 'context_sha256': None, 'code_commit': commit,
        'packet_size_bytes': 32768, 'packet_sha256': packet_sha, 'selected_sha256': None,
        'core_sha256': expected['core_sha256'], 'factory_sha256': factory_sha,
        'decision': 'approved_for_C1', 'approval_type': 'delegated_agent_self_approval',
        'independent_review_reference': 'https://github.com/lordcoudy/VAST/pull/9#issuecomment-6312880447'}
    approval_reference = 'https://github.com/lordcoudy/VAST/pull/9#issuecomment-' + '9' * 20
    data = {'initial': initial, 'finalizer': finalizer,
            'executor_prefix': prefix, 'executor_suffix': suffix, 'executor_pin': executor_pin,
            'fields': list(m.NODE_FIELDS), 'pipe_fields': list(m.NODE_PIPE_FIELDS), 'held': held,
            'commit': commit, 'packet_sha256': packet_sha, 'factory_sha256': factory_sha,
            'forms': forms, 'chain': chain, 'later': later,
            'approval_template': approval_template, 'approval_reference': approval_reference}
    gate()
    encoded = canonical(data)
    facts = {'kind': 'd27_inert_source_construction_metadata_v1',
             'initial': source_facts, 'node_codec': role_facts, 'driver': driver_facts,
             'finalizer': finalizer_facts, 'executor': executor_pin,
             'input_data_size_bytes': len(encoded), 'input_data_sha256': digest(encoded),
             'modeled_setup_form_count': len(forms), 'modeled_later_form_count': len(later),
             'controlled_synthetic_geometry_only': True,
             'independent_actual_acquisition_proven': False,
             'generated_operational_program_execution': False,
             'generated_full_subject_files_written': False,
             'behavior_conformance_complete': False, 'physical_acceptance': False}
    if len(canonical(facts)) > 32768:
        raise RuntimeError('d27_source_metadata_bound')
    return encoded, facts


def d27_assert_fixed_data_v1(deadline):
    """Check the old three and four formatter identities as bounded DATA only."""
    import stat
    import time
    if type(deadline) not in (int,float) or not math.isfinite(deadline):
        raise RuntimeError('d27_data_deadline')
    last=time.monotonic()
    if deadline-last>300:raise RuntimeError('d27_data_deadline')
    def gate():
        nonlocal last
        n=time.monotonic()
        if not math.isfinite(n) or n<last or n>=deadline-5:
            raise RuntimeError('d27_data_deadline')
        last=n
    def epoch(s,cross=False):
        return (s.st_dev,s.st_ino,s.st_mode,s.st_nlink,s.st_size,s.st_mtime_ns,
                getattr(s,'st_birthtime_ns',None),None if cross and os.name=='nt' else s.st_ctime_ns)
    root=Path(__file__).absolute().parents[1]
    rows=(
        ('tests/test_accepted_policy_fixture_compiler_gate2_resume_v1.py',521029,'bdfaca98fbd3825cf383a4d3f22ae60ffaced76cee27f42cf462ba6dba7bd704'),
        ('tests/test_accepted_policy_fixture_compiler_gate2_resume_caller_v1.py',520323,'3742a391657a85932a3ba776b36fbef87c7a097b7be067cf79ea27cfb3e5b24f'),
        ('tests/fixtures/gate2/d26-geometry-retained-v1.json',102199,'408379cb8ee0d7ce2fd233d963a0939889485156e7c42a07481d3726b419578f'),
        ('tests/fixtures/accepted_policy_fixture_compiler_component_v1.py',32732,'329fb13f2c6dcee0872e5a29ec1fd769dc6e57ce92ee1076fef6737f1da86d88'),
        ('tests/fixtures/accepted_policy_fixture_compiler_gate2_resume_v1.py',32739,'5fd7d2d6ee62ff584d2a4662757ca804a3d3300d30bb966319901870c4c85670'),
        ('tests/fixtures/accepted_policy_fixture_compiler_gate2_c_v1.py',130783,'5a6c4b08ce3d381c355cbf72f93057c991b4adcb9d6ca8c43a638acd64f2ecf9'),
        ('tests/fixtures/accepted_policy_fixture_compiler_v1.py',103925,'1e40d4786fd03543ac43df7fe0e42a4349d55bad9288ead28f5d2a6ad87bcb03'))
    for rel,size,digest in rows:
        gate();path=root/rel;before=path.lstat()
        if (path.resolve(strict=True)!=path or not stat.S_ISREG(before.st_mode)
                or before.st_nlink!=1 or before.st_size!=size):
            raise RuntimeError('d27_data_identity')
        gate();fd=os.open(path,os.O_RDONLY|getattr(os,'O_BINARY',0))
        try:
            opened=os.fstat(fd)
            if epoch(opened,True)!=epoch(before,True):raise RuntimeError('d27_data_identity')
            raw=b''
            while len(raw)<=size:
                gate();part=os.read(fd,min(65536,size+1-len(raw)));gate()
                if not part:break
                raw+=part
            if (len(raw)!=size or hashlib.sha256(raw).hexdigest()!=digest
                    or epoch(os.fstat(fd))!=epoch(opened) or epoch(path.lstat())!=epoch(before)):
                raise RuntimeError('d27_data_identity')
        finally:os.close(fd)
        gate()
    return {'protected_files':3,'formatter_files':4}


class D27SourceCustodyTests(unittest.TestCase):
    def test_fixed_old_three_and_four_formatter_data_pins(self):
        import time
        self.assertEqual(d27_assert_fixed_data_v1(time.monotonic()+30),
                         {'protected_files':3,'formatter_files':4})

    def test_decoder_role_is_exact_new_prefix_and_old_primitives(self):
        m=_d27_main_module_v1()
        prefix,facts=d27_node_codec_v1(m.D27_WIRE_CODEC)
        self.assertTrue(facts['role_is_exact_prefix'] and facts['encoder_excluded'])
        self.assertEqual(facts['kind'],'d27_node_codec_role_v1')
        self.assertEqual(prefix,m.D27_WIRE_CODEC[:facts['node_codec_bytes']])
        self.assertNotIn('function gate2WireEncode(',prefix)
        self.assertEqual(hashlib.sha256(prefix[:949].encode()).hexdigest(),
                         'd15dca0b287943b37e43143397e8c753f6bca0170862d3d924ca15e01965cd7b')

    def test_fixed_driver_source_and_windows_command_bounds(self):
        import ast
        import shutil
        import subprocess
        m=_d27_main_module_v1()
        program=m.d27_node_driver_v1()
        self.assertLessEqual(len(program.encode('ascii')),24576)
        self.assertIn(m.ROOT_ENCODER,program)
        tree=ast.parse(Path(m.__file__).read_bytes())
        literal={n.targets[0].id:ast.literal_eval(n.value) for n in tree.body
                 if type(n) is ast.Assign and len(n.targets)==1 and isinstance(n.targets[0],ast.Name)
                 and n.targets[0].id in ('ROOT_ENCODER','ROOT_SHA256','D27_WIRE_CODEC','D27_GEOMETRY_MODEL','D27_GEOMETRY_STDIO')}
        # Static TEST-source link arithmetic; the geometry getter/bundle is never called.
        geometry='\n'.join(literal[k] for k in ('ROOT_ENCODER','ROOT_SHA256','D27_WIRE_CODEC','D27_GEOMETRY_MODEL','D27_GEOMETRY_STDIO'))
        self.assertLessEqual(len(geometry.encode('ascii')),24576)
        node=shutil.which('node') or 'node'
        for fixed in (program,geometry):
            self.assertLessEqual(len(subprocess.list2cmdline([node,'--max-old-space-size=256','--input-type=commonjs','-e',fixed])),32767)

    @unittest.skipUnless(sys.version_info[:3]==(3,14,7) and os.name=='nt',
                         'D27 held-entry control requires fixed Windows Python3.14.7 worktree')
    def test_wrong_held_pin_refuses_before_either_source_compiles(self):
        import subprocess
        root=Path(__file__).absolute().parents[1]
        rows={}
        for role,filename in (('main','test_accepted_policy_fixture_compiler_gate2_dictionary_v1.py'),
                              ('caller','test_accepted_policy_fixture_compiler_gate2_dictionary_caller_v1.py')):
            raw=(root/'tests'/filename).read_bytes()
            self.assertLessEqual(len(raw),524288)
            rows[role]=[len(raw),hashlib.sha256(raw).hexdigest()]
        rows['main'][1]='0'*64
        observe="import builtins\nold_compile=builtins.compile\ndef watch_compile(source,filename,*args,**kwargs):\n if str(filename).endswith(('test_accepted_policy_fixture_compiler_gate2_dictionary_v1.py','test_accepted_policy_fixture_compiler_gate2_dictionary_caller_v1.py')):raise RuntimeError('D27_ROLE_COMPILE_REACHED')\n return old_compile(source,filename,*args,**kwargs)\nbuiltins.compile=watch_compile\n"
        p=subprocess.run([sys.executable,'-I','-S','-B','-c',observe+D27_CODEC_TEST_ENTRY,json.dumps(rows)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=5)
        self.assertNotEqual(p.returncode,0)
        self.assertLessEqual(len(p.stdout),32768);self.assertLessEqual(len(p.stderr),16384)
        self.assertIn(b'AssertionError',p.stderr)
        self.assertNotIn(b'D27_ROLE_COMPILE_REACHED',p.stderr)


def d27_source_rows_v1(raw,owner):
    """Inspect authored TEST bytes as DATA; only the fixed new class is excluded."""
    import ast
    def require(ok):
        if not ok:raise ValueError('d27_source_rows')
    require(type(raw) is bytes and 0<len(raw)<=524288 and b'\r' not in raw and owner in ('main','caller'))
    try:text=raw.decode('utf-8');tree=ast.parse(text)
    except (UnicodeError,SyntaxError):raise ValueError('d27_source_rows') from None
    def segment(node):
        require(not getattr(node,'decorator_list',[]))
        value=ast.get_source_segment(text,node);require(type(value) is str)
        return value.encode('utf-8')
    rows=[];development=None
    for node in tree.body:
        if type(node) is ast.ClassDef and node.name=='D27CompleteGeometryTests':
            require(owner=='caller' and development is None and not node.decorator_list
                    and not node.keywords and not getattr(node,'type_params',[]) and len(node.bases)==1)
            base=node.bases[0]
            require(type(base) is ast.Attribute and type(base.value) is ast.Name
                    and base.value.id=='unittest' and base.attr=='TestCase' and len(node.body)==1)
            method=node.body[0]
            require(type(method) is ast.FunctionDef and method.name=='test_complete_form_bounds_preserve_hold'
                    and not method.decorator_list and not getattr(method,'type_params',[])
                    and not method.args.defaults and not method.args.kw_defaults and len(method.args.args)==1
                    and method.args.args[0].arg=='self' and not method.args.posonlyargs
                    and not method.args.kwonlyargs and method.args.vararg is None and method.args.kwarg is None
                    and method.returns is None and method.args.args[0].annotation is None)
            class_raw=segment(node);method_raw=segment(method)
            # AST columns are UTF8 byte offsets; subtract the exact class origin.
            lines=raw.splitlines(keepends=True)
            class_start=sum(map(len,lines[:node.lineno-1]))+node.col_offset
            method_start=sum(map(len,lines[:method.lineno-1]))+method.col_offset-class_start
            end=method_start+len(method_raw)
            require(0<=method_start<end<=len(class_raw) and class_raw[method_start:end]==method_raw)
            development={'owner_role':'caller','class_name':'D27CompleteGeometryTests',
                'method_name':'test_complete_form_bounds_preserve_hold',
                'class_source':{'size_bytes':len(class_raw),'sha256':hashlib.sha256(class_raw).hexdigest(),
                                'bytes_base64':base64.b64encode(class_raw).decode('ascii')},
                'method':{'start_byte':method_start,'end_byte':end,'size_bytes':len(method_raw),
                          'sha256':hashlib.sha256(method_raw).hexdigest()}}
            continue
        kind=type(node).__name__
        require(kind in ('Expr','Import','ImportFrom','Assign','AnnAssign','FunctionDef','AsyncFunctionDef','ClassDef','Assert','If'))
        if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)):names=[node.name]
        elif isinstance(node,ast.Import):names=[item.asname or item.name.split('.')[0] for item in node.names]
        elif isinstance(node,ast.ImportFrom):names=[item.asname or item.name for item in node.names]
        elif isinstance(node,(ast.Assign,ast.AnnAssign)):
            targets=node.targets if isinstance(node,ast.Assign) else [node.target]
            names=sorted({item.id for target in targets for item in ast.walk(target)
                          if isinstance(item,ast.Name) and isinstance(item.ctx,ast.Store)})
        else:names=[]
        require(len(names)<=16 and len(set(names))==len(names)
                and all(re.fullmatch('[A-Za-z_][A-Za-z0-9_]{0,127}',name) for name in names))
        part=segment(node);require(0<len(part)<=524288)
        rows.append([kind,names,len(part),hashlib.sha256(part).hexdigest(),
                     hashlib.sha256(ast.dump(node,include_attributes=False).encode('utf-8')).hexdigest()])
    require(1<=len(rows)<=256 and (development is not None)==(owner=='caller'))
    return {'excluded_class':'D27CompleteGeometryTests' if owner=='caller' else None,
            'ordered_rows':rows,'ordered_rows_sha256':hashlib.sha256(canonical(rows)).hexdigest()},development


def d27_inventory_v1():
    """Return the complete fixed inventory, independent of any measured outcome."""
    setups=('success','structured_failure','unicode_failure','partial_emission','unknown_closure','setup_refusal')
    later=('C1_success','C1_failure','C6_success','C6_failure','D_success','D_failure')
    groups=('c1_success','c1_failure','c6_success','c6_failure','d_success','d_failure')
    checks=['source_bindings','initial_source_bound','finalizer_source_bound','executor_source_bound','six_setup_forms']
    measures=['initial_source','finalizer_source','executor_source']
    for form in setups:
        checks += [form+s for s in ('_setup','_provider_pipes','_pipe0_inverse','_pipe1_inverse','_pipe2_inverse',
            '_selected_original_bound','_observed_original_bound','_selected_wire_bound','_observed_wire_bound',
            '_full_roundtrip','_uint64','_writer_pipe0_inverse','_writer_pipe1_inverse','_ack_bound',
            '_writer_stdout_bound','_writer_input_bound','_forms_bound','_chain_join','_root_bound','_chain_bound')]
        measures += [form+s for s in ('_selected_original','_observed_original','_selected_wire','_observed_wire',
                                     '_ack','_writer_stdout','_root','_chain')]
    checks += ['approval_slots','six_later_forms','later_measured_upstream']
    conditional=[]
    for group,form in zip(groups,later):
        conditional.append({'id':group,'check_ids':[form+s for s in ('_later','_pipe_limits','_pipe0_inverse',
            '_pipe1_inverse','_selected_bound','_native_input_bound','_uint64','_writer_pipe0_inverse',
            '_writer_pipe1_inverse','_ack_bound','_writer_stdout_bound','_writer_forms_bound','_writer_input_bound')],
            'measurement_ids':[form+s for s in ('_selected','_native_input','_ack','_writer_stdout')]})
    value={'always':{'check_ids':checks,'measurement_ids':measures},'conditional':conditional,
           'diagnostic':{'check_ids':[form+'_wire_geometry' for form in setups],
                         'measurement_ids':[form+'_wire_refusal' for form in setups]}}
    all_c=checks+value['diagnostic']['check_ids'];all_m=measures+value['diagnostic']['measurement_ids']
    for group in conditional:all_c+=group['check_ids'];all_m+=group['measurement_ids']
    if (len(all_c)!=212 or len(set(all_c))!=212 or len(all_m)!=81 or len(set(all_m))!=81
            or any(re.fullmatch('[A-Za-z0-9_]{1,64}',name) is None for name in all_c+all_m)):
        raise ValueError('d27_inventory')
    return value


def d27_json_object_bound_v1(lengths):
    """Count keys, colons and delimiters without fabricating unknown values."""
    if (type(lengths) is not dict or any(type(k) is not str or type(v) is not int or v<0
                                       for k,v in lengths.items())):
        raise ValueError('d27_symbolic_json_bound')
    return 2+max(0,len(lengths)-1)+sum(len(canonical(k))+1+v for k,v in lengths.items())


def d27_retention_preflight_v1(main_raw,caller_raw,entry_raw):
    """After implemented-source approval only: freeze T in RAM, never in a file.

    Unknown future values below are encoded lengths, not invented observations.
    This helper neither constructs an operational subject nor admits an attempt.
    """
    import ast
    def require(ok):
        if not ok:raise ValueError('d27_retention_preflight')
    obj=d27_json_object_bound_v1
    def arr(lengths):return 2+max(0,len(lengths)-1)+sum(lengths)
    def scalar(value):return len(canonical(value))
    require(type(entry_raw) is bytes and 0<len(entry_raw)<=524288)
    main_rows,none=d27_source_rows_v1(main_raw,'main')
    caller_rows,development=d27_source_rows_v1(caller_raw,'caller')
    require(none is None and development is not None)
    tree=ast.parse(caller_raw.decode('utf-8'))
    builders=[n for n in tree.body if type(n) is ast.FunctionDef and n.name=='d27_pure_class_source_v1']
    entries=[n for n in tree.body if type(n) is ast.Assign and len(n.targets)==1
             and type(n.targets[0]) is ast.Name and n.targets[0].id=='D27_GEOMETRY_TEST_ENTRY']
    require(len(builders)==len(entries)==1)
    require(ast.literal_eval(entries[0].value).encode('ascii')==entry_raw)
    assignments={n.targets[0].id:n.value for n in builders[0].body if type(n) is ast.Assign
                 and len(n.targets)==1 and type(n.targets[0]) is ast.Name}
    require('body' in assignments and 'head' in assignments)
    body=ast.literal_eval(assignments['body']);require(type(body) is str)
    # Syntax inspection only: no future actual-pin class is rendered or compiled.
    ast.parse('class D27CompleteGeometryTests(unittest.TestCase):\n'
              '    def test_complete_form_bounds_preserve_hold(self):\n'+body)
    fixtures=[{'path':p,'size_bytes':n,'sha256':h} for p,n,h in (
        ('tests/fixtures/accepted_policy_fixture_compiler_component_v1.py',32732,'329fb13f2c6dcee0872e5a29ec1fd769dc6e57ce92ee1076fef6737f1da86d88'),
        ('tests/fixtures/accepted_policy_fixture_compiler_gate2_resume_v1.py',32739,'5fd7d2d6ee62ff584d2a4662757ca804a3d3300d30bb966319901870c4c85670'),
        ('tests/fixtures/accepted_policy_fixture_compiler_gate2_c_v1.py',130783,'5a6c4b08ce3d381c355cbf72f93057c991b4adcb9d6ca8c43a638acd64f2ecf9'),
        ('tests/fixtures/accepted_policy_fixture_compiler_v1.py',103925,'1e40d4786fd03543ac43df7fe0e42a4349d55bad9288ead28f5d2a6ad87bcb03'))]
    sources={'main':main_rows,'caller':caller_rows,'fixtures':fixtures};inventory=d27_inventory_v1()
    template={'schema_version':1,'kind':'d27_retention_template_v1','development':development,
              'source_rows':sources,'inventory':inventory}
    template_raw=canonical(template)
    # Required PIN and observed descriptor scalar maxima, including null/reasons.
    pin_bound=obj({'size_bytes':6,'sha256':66})
    observed_bound=obj({'available':5,'size_bytes':16,'sha256':66,
                        'unavailable_reason':scalar('CAPTURE_INCOMPLETE')})
    risk_bound=obj({'entry':pin_bound,'main':pin_bound,'caller':pin_bound,'driver':pin_bound,
                    'codec':obj({r:pin_bound for r in ('full','decoder','tail')}),
                    'initial':observed_bound,'finalizer':observed_bound,'executor':observed_bound,
                    'template_sha256':66})
    original_scaffolds={}
    for name,cap in (('stdout',1048576),('stderr',16384),('parent',32768),('canonical_report',32768)):
        original_scaffolds[name]=obj({'name':scalar(name),'available':5,'size_bytes':len(str(cap)),
             'sha256':66,'bytes_base64':4,'unavailable_reason':scalar('CAPTURE_INCOMPLETE')})
    # Sixfold raw allowance covers Base64 contents independently of availability.
    originals_scaffold=obj(original_scaffolds)
    conditional=[]
    for group in inventory['conditional']:
        conditional.append(obj({'id':scalar(group['id']),'coverage':scalar('COMPLETE_APPLICABLE'),
             'missing_check_ids':scalar(group['check_ids']),'missing_measurement_ids':scalar(group['measurement_ids']),
             'unavailable_reason':scalar('UPSTREAM_UNAVAILABLE')}))
    external_bound=obj({'attribution':scalar('root_observed_tool_result_not_child_self_receipt'),
                         'reference':194,'completed':5,'exit_code':11,'wall_time_seconds':32})
    outcome_bound=obj({'status':scalar('ALL_GEOMETRY_TRUE_NOT_READY'),'parent_transport_complete':5,
        'inventory':scalar(inventory),'missing_check_ids':scalar(inventory['always']['check_ids']),
        'missing_measurement_ids':scalar(inventory['always']['measurement_ids']),
        'conditional_groups':arr(conditional),'unknowns':scalar({k:'UNKNOWN' for k in
            ('descendant_quiescence','native_activity','native_closure','namespace')}),
        'external_observation':external_bound})
    overhead=obj({'schema_version':1,'kind':scalar('d27_retained_geometry_outcome_v1'),
        'originals':originals_scaffold,'development':scalar(development),'risk_inputs':risk_bound,
        'source_rows':scalar(sources),'outcome':outcome_bound})+1
    conservative=6782976+overhead
    require(overhead<=1605632 and conservative<=8388608)
    # Independently check every authored scaffold in the canonical-Base64 proof.
    class_row=development['class_source'];method=development['method']
    development_scaffold=obj({'owner_role':scalar(development['owner_role']),
        'class_name':scalar(development['class_name']),'method_name':scalar(development['method_name']),
        'class_source':obj({'size_bytes':len(str(class_row['size_bytes'])),'sha256':66,'bytes_base64':2}),
        'method':scalar(method)})
    modules={}
    node_count=0;max_node=0
    for role in ('main','caller'):
        row=sources[role];nodes=row['ordered_rows'];node_count+=len(nodes)
        for node in nodes:max_node=max(max_node,scalar(node))
        modules[role]=obj({'excluded_class':scalar(row['excluded_class']),
                           'ordered_rows':arr([0]*len(nodes)),'ordered_rows_sha256':66})
    source_scaffold=obj({**modules,'fixtures':scalar(fixtures)})
    top_scaffold=obj({'schema_version':1,'kind':scalar('d27_retained_geometry_outcome_v1'),
                     **{key:0 for key in ('originals','development','risk_inputs','source_rows','outcome')}})+1
    require(originals_scaffold<=2048 and development_scaffold<=4096 and source_scaffold<=8192
            and risk_bound<=8192 and outcome_bound<=262144 and top_scaffold<=1024
            and node_count<=512 and max_node<=4096 and len(class_row['bytes_base64'])<=699052)
    base64_bound=1507336+2048+699052+4096+512*4096+8192+8192+262144+1024
    require(base64_bound==4589236 and base64_bound<8388608)
    # Python repr adds spaces and may escape REF apostrophes. Bound it separately.
    def pyobj(lengths):return 2+2*max(0,len(lengths)-1)+sum(len(repr(k))+2+v for k,v in lengths.items())
    py_pin=pyobj({'size_bytes':7,'sha256':66})
    py_admitted=pyobj({**{r:py_pin for r in ('entry','main','caller','driver')},
                       'codec':pyobj({r:py_pin for r in ('full','decoder','tail')})})
    py_external=pyobj({'attribution':len(repr('root_observed_tool_result_not_child_self_receipt')),
                       'reference':386,'completed':5,'exit_code':11,'wall_time_seconds':32})
    head_fixed=sum(len(n.value.encode('utf-8')) for n in ast.walk(assignments['head'])
                   if type(n) is ast.Constant and type(n.value) is str)
    header_bound=head_fixed+py_pin+66+py_admitted+py_external
    pure_class_bound=header_bound+len(body.encode('utf-8'))
    future_module_bound=len(caller_raw)-class_row['size_bytes']+pure_class_bound+16
    require(header_bound<=4096 and pure_class_bound<=524288 and future_module_bound<=524288)
    return {'template_bytes':template_raw,'template_pin':{'size_bytes':len(template_raw),
             'sha256':hashlib.sha256(template_raw).hexdigest()},
        'proofs':{'conservative_original_allowance':6782976,'delimiter_inclusive_overhead':overhead,
             'conservative_fixture_bound':conservative,'canonical_base64_fixture_bound':base64_bound,
             'originals_scaffold':originals_scaffold,'development_scaffold':development_scaffold,
             'source_scaffold':source_scaffold,'risk_inputs_bound':risk_bound,'outcome_bound':outcome_bound,
             'top_scaffold':top_scaffold,'node_count':node_count,'maximum_encoded_NODE':max_node,
             'prospective_pure_header_bound':header_bound,'prospective_pure_class_bound':pure_class_bound,
             'prospective_final_caller_bound':future_module_bound},'geometry_admitted':False}


class D27RetentionSourceTests(unittest.TestCase):
    def test_portable_source_rows_and_utf8_method_span(self):
        raw=('"\u00e9"\nclass D27CompleteGeometryTests(unittest.TestCase):\n'
             '    def test_complete_form_bounds_preserve_hold(self):\n'
             '        self.assertEqual("\u00e9", "\u00e9")\n').encode('utf-8')
        row,dev=d27_source_rows_v1(raw,'caller')
        self.assertEqual(row['excluded_class'],'D27CompleteGeometryTests')
        self.assertEqual([r[0] for r in row['ordered_rows']],['Expr'])
        self.assertEqual(row['ordered_rows'][0][2],4)
        source=base64.b64decode(dev['class_source']['bytes_base64'],validate=True)
        span=dev['method'];method=source[span['start_byte']:span['end_byte']]
        self.assertTrue(method.startswith(b'def test_complete_form_bounds_preserve_hold(self):'))
        self.assertEqual(len(method),span['size_bytes'])
        self.assertEqual(hashlib.sha256(method).hexdigest(),span['sha256'])
        self.assertEqual(hashlib.sha256(canonical(row['ordered_rows'])).hexdigest(),row['ordered_rows_sha256'])
        main,none=d27_source_rows_v1(b'a,b=1,2\n','main')
        self.assertIsNone(none)
        self.assertEqual(main['ordered_rows'][0][1],['a','b'])

    def test_source_modifiers_limits_and_exclusion_refuse(self):
        good=('class D27CompleteGeometryTests(unittest.TestCase):\n'
              '    def test_complete_form_bounds_preserve_hold(self):\n'
              '        pass\n')
        bad=(good.replace('class ','@decorator\nclass ',1),
             good.replace('    def ','    @decorator\n    def ',1),
             good.replace('(self):','(self,extra=None):'),
             good.replace('unittest.TestCase','object'),
             good+'    value=1\n',good+good,good.replace('def test_','async def test_'),
             'while True:\n    pass\n',good.replace('\n','\r\n'))
        for source in bad:
            with self.subTest(source_sha=hashlib.sha256(source.encode()).hexdigest()):
                with self.assertRaises(ValueError):d27_source_rows_v1(source.encode(),'caller')
        with self.assertRaises(ValueError):d27_source_rows_v1(good.encode(),'main')
        with self.assertRaises(ValueError):d27_source_rows_v1(b'a=1\n'*257,'main')
        with self.assertRaises(ValueError):d27_source_rows_v1(b'a=1\n','other')

    def test_inventory_is_fixed_disjoint_and_complete(self):
        value=d27_inventory_v1();self.assertEqual(set(value),{'always','conditional','diagnostic'})
        self.assertEqual(len(value['always']['check_ids']),128)
        self.assertEqual(len(value['always']['measurement_ids']),51)
        self.assertEqual([r['id'] for r in value['conditional']],['c1_success','c1_failure','c6_success','c6_failure','d_success','d_failure'])
        checks=value['always']['check_ids']+value['diagnostic']['check_ids']
        measures=value['always']['measurement_ids']+value['diagnostic']['measurement_ids']
        for row in value['conditional']:
            self.assertEqual((len(row['check_ids']),len(row['measurement_ids'])),(13,4))
            checks+=row['check_ids'];measures+=row['measurement_ids']
        self.assertEqual((len(checks),len(measures)),(212,81))
        self.assertEqual((len(set(checks)),len(set(measures))),(212,81))
        value['always']['check_ids'].clear()
        self.assertEqual(len(d27_inventory_v1()['always']['check_ids']),128)

    def test_symbolic_delimiters_match_independent_json(self):
        for value in ({},{'a':1},{'a':[True,None,'\u00e9'],'b':{'quote':'"\\'}}):
            lengths={key:len(canonical(item)) for key,item in value.items()}
            self.assertEqual(d27_json_object_bound_v1(lengths),len(canonical(value)))
        with self.assertRaises(ValueError):d27_json_object_bound_v1({'a':True})
        with self.assertRaises(ValueError):d27_json_object_bound_v1({'a':-1})


def d27_original_protocol_v1(stdout,stderr,parent,admitted):
    """Validate fixed metadata originals without constructing or executing a subject."""
    CLASS_NAME="D27CompleteGeometryTests"
    MODULE_PATHS=("tests/test_accepted_policy_fixture_compiler_gate2_dictionary_v1.py",
                  "tests/test_accepted_policy_fixture_compiler_gate2_dictionary_caller_v1.py")
    def require(ok,cause):
     if not ok: raise AssertionError(cause)
    def samekeys(value,keys):
     require(type(value) is dict and set(value)==set(keys),'closed_keys')
    def integer(value,lo,hi):
     require(type(value) is int and lo<=value<=hi,'integer')
    def hex64(value):
     require(type(value) is str and re.fullmatch('[0-9a-f]{64}',value) is not None,'hex64')
    def ids(values,cap):
     require(type(values) is list and len(values)<=cap and len(set(values))==len(values),'ids')
     require(all(type(v) is str and re.fullmatch('[A-Za-z0-9_]{1,64}',v) for v in values),'id')
    def sha(raw): return hashlib.sha256(raw).hexdigest()
    def validate_report(value):
     samekeys(value,('schema_version','case','node_version','completed','cause','checks','measurements'))
     require(type(value['schema_version']) is int and value['schema_version']==1 and value['case']=='geometry' and value['node_version']=='25.2.1' and type(value['completed']) is bool,'report_identity')
     require(value['cause'] in (None,'d27_codec_absent','d27_driver_assertion','d27_driver_input','d27_driver_error','d27_node_version','d27_geometry_hold'),'report_cause')
     require(type(value['checks']) is list and len(value['checks'])<=512 and type(value['measurements']) is list and len(value['measurements'])<=128,'report_counts')
     for row in value['checks']:samekeys(row,('id','ok'));require(type(row['ok']) is bool,'check_boolean')
     for row in value['measurements']:samekeys(row,('id','size_bytes','sha256'));integer(row['size_bytes'],0,262144);hex64(row['sha256'])
     ids([r['id'] for r in value['checks']],512);ids([r['id'] for r in value['measurements']],128)
     require(len(canonical(value))+1<=32768,'report_bound')
     return {r['id']:r['ok'] for r in value['checks']},{r['id']:r for r in value['measurements']}
    def original_protocol(stdout,stderr,parent,admitted):
     import base64,math
     def canon(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode('ascii')
     CAPTURE_KEYS=set('caller_deadline case case_cause case_completed causes checks_count child_completion_observed_before_deadline child_total_deadline child_total_limit_seconds child_work_limit_seconds cleanup_deadline cleanup_limit_seconds command_options data_bytes data_only data_sha256 descendant_quiescence elapsed_seconds environment_keys final_reserve_seconds finished_before_deadline input_bytes input_sha256 kill_requested measurements_count node_executable node_version parent_observed_completion pid program_sha256 reaped report_bytes report_sha256 returncode schema_version spawned started_monotonic stderr stdin_bytes stdin_closed stdin_complete stdin_extent_unknown stdin_write_attempted stdin_write_in_flight stdout threads_joined threads_started timed_out work_deadline'.split())
     PIPE_KEYS=set('observed_bytes retained_bytes eof overflow io_error closed unknown_remainder prefix_sha256'.split())
     COMP_KEYS=(CAPTURE_KEYS-set('case case_cause case_completed data_bytes data_sha256 report_bytes report_sha256 checks_count measurements_count'.split()))|set('quality roundtrip packed_bytes packed_sha256 stderr_prefix_b64'.split())
     CAPTURE_KEYS|={'source_kind','driver_role','driver_getter','program_bytes'}
     INITIAL_KEYS=set('kind source_bytes source_sha256 escaped_source_bytes baseline_bytes baseline_sha256 original_builder_bytes original_builder_sha256 baseline_body_bytes baseline_body_sha256 prefix_bytes prefix_sha256 decoder_bytes decoder_sha256 canonical_data_bytes canonical_data_sha256 compressed_data_bytes compressed_data_sha256 base64_data_bytes base64_data_sha256 data_fields strings_field_absent deferred_definition_bytes deferred_definition_sha256 exact_decoder_inverse exact_phase_inverse exact_inverse_source source_contribution_fits source_only_over_cap_by complete_geometry_qualified behavior_conformance_complete finalizer_implemented generated_operational_program_executed generated_full_subject_files_written status task_2_10_complete compression'.split())
     FINAL_KEYS=set('initial_size_bytes initial_sha256 finalizer_size_bytes finalizer_sha256 factory_size_bytes factory_sha256 wrapper_prefix_size_bytes wrapper_suffix_size_bytes python_head_size_bytes python_head_sha256 python_tail_size_bytes python_tail_sha256 python_common_size_bytes python_common_sha256 generated_operational_program_execution generated_full_subject_files_written'.split())
     ROLE_KEYS=set('kind full_codec_bytes full_codec_sha256 node_codec_bytes node_codec_sha256 excluded_encoder_bytes excluded_encoder_sha256 marker_occurrences role_is_exact_prefix encoder_excluded'.split())
     SOURCE_KEYS=set('kind driver initial node_codec finalizer executor input_data_size_bytes input_data_sha256 modeled_setup_form_count modeled_later_form_count controlled_synthetic_geometry_only independent_actual_acquisition_proven generated_operational_program_execution generated_full_subject_files_written behavior_conformance_complete physical_acceptance'.split())
     FAIL_KEYS=set('kind error_type message_size_bytes message_sha256 capture capture_metadata_unavailable capture_metadata_size_bytes capture_metadata_sha256 generated_operational_program_execution generated_full_subject_files_written physical_acceptance'.split())
     SAFE_KEYS=CAPTURE_KEYS|COMP_KEYS|PIPE_KEYS|INITIAL_KEYS|FINAL_KEYS|ROLE_KEYS|SOURCE_KEYS|FAIL_KEYS|{'size_bytes','sha256'}
     require(stdout is None or type(stdout) is bytes and len(stdout)<=1048576,'original_stdout_bound')
     require(stderr is None or type(stderr) is bytes and len(stderr)<=16384,'original_stderr_bound')
     ROLE_EXPECTED=None;FIXED_DRIVER=None
     def pairs(rows):
      value={}
      for key,item in rows:
       if key in value:raise AssertionError('d27_test_metadata_duplicate')
       value[key]=item
      return value

     def sha_text(value):return type(value) is str and re.fullmatch('[0-9a-f]{64}',value) is not None
     def bounded(value):
      todo=[('',value)];nodes=0
      while todo:
       key,item=todo.pop();nodes+=1
       if nodes>4096:raise ValueError('d27_metadata_nodes')
       if type(item) is dict:
        if any(type(k) is not str or k not in SAFE_KEYS for k in item):raise ValueError('d27_metadata_key')
        todo.extend(item.items())
       elif type(item) is list:
        if len(item)>128:raise ValueError('d27_metadata_list')
        todo.extend((key,v) for v in item)
       elif type(item) is str:
        if key=='stderr_prefix_b64':
         if len(item)>21848 or re.fullmatch('[A-Za-z0-9+/]*={0,2}',item) is None:raise ValueError('d27_metadata_stderr')
         b=base64.b64decode(item,validate=True)
         if len(b)>16384 or base64.b64encode(b).decode('ascii')!=item:raise ValueError('d27_metadata_stderr')
        elif len(item)>256 or not item.isascii() or any(ord(c)<32 or ord(c)>126 for c in item):raise ValueError('d27_metadata_string')
        if key.endswith('sha256') and not sha_text(item):raise ValueError('d27_metadata_sha256')
       elif type(item) is float:
        if not math.isfinite(item):raise ValueError('d27_metadata_number')
       elif type(item) is int:
        if not -(2**64)<=item<=2**64:raise ValueError('d27_metadata_integer')
       elif item is not None and type(item) is not bool:raise ValueError('d27_metadata_type')
      return value
     def capture_metadata(value):
         if type(value) is not dict:raise ValueError('d27_capture_shape')
         compression='quality' in value
         allowed=COMP_KEYS if compression else CAPTURE_KEYS
         if not set(value)<=allowed:raise ValueError('d27_capture_keys')
         bounded(value)
         def want(ok):
             if not ok:raise ValueError('d27_capture_correspondence')
         def number(item):return type(item) in (int,float) and math.isfinite(item) and item>=0
         def integer(item,lo=0,hi=9007199254740991):return type(item) is int and lo<=item<=hi
         want(type(value.get('schema_version')) is int and value['schema_version']==1)
         bools=('data_only','spawned','timed_out','kill_requested','stdin_closed','stdin_complete',
                'stdin_extent_unknown','stdin_write_attempted','stdin_write_in_flight','reaped',
                'threads_joined','parent_observed_completion','finished_before_deadline',
                'child_completion_observed_before_deadline')
         for key in bools:
             if key in value:want(type(value[key]) is bool)
         want(value.get('data_only') is True and value.get('descendant_quiescence')=='UNKNOWN')
         for key in ('pid','returncode'):
             if key in value and value[key] is not None:
                 want(integer(value[key],1,2147483647) if key=='pid' else integer(value[key],-2147483648,2147483647))
         for key in ('stdin_bytes','input_bytes','data_bytes','report_bytes','checks_count','measurements_count','packed_bytes','program_bytes'):
             if key in value and value[key] is not None:want(integer(value[key]))
         if 'threads_started' in value:want(integer(value['threads_started'],0,3))
         for key in ('program_sha256','input_sha256','data_sha256','report_sha256','packed_sha256'):
             if key in value and value[key] is not None:want(sha_text(value[key]))
         for key in ('started_monotonic','elapsed_seconds','caller_deadline','work_deadline','child_total_deadline','cleanup_deadline'):
             if key in value and value[key] is not None:want(number(value[key]))
         for key,expected in (('child_total_limit_seconds',30),('child_work_limit_seconds',27),('cleanup_limit_seconds',3),('final_reserve_seconds',5)):
             if key in value:want(type(value[key]) is int and value[key]==expected)
         if 'node_version' in value and value['node_version'] is not None:
             want(type(value['node_version']) is str and re.fullmatch('[0-9]{1,8}\\.[0-9]{1,8}\\.[0-9]{1,8}',value['node_version']) is not None)
         want(type(value.get('causes')) is list and len(value['causes'])<=128
              and all(type(v) is str and v.isascii() and 1<=len(v)<=128 and all(32<=ord(c)<=126 for c in v) for v in value['causes'])
              and len(set(value['causes']))==len(value['causes']))
         for key in ('environment_keys','command_options'):
             if key in value:want(type(value[key]) is list and len(value[key])<=16 and all(type(v) is str and v.isascii() and len(v)<=256 for v in value[key]))
         if 'node_executable' in value:want(type(value['node_executable']) is str and 0<len(value['node_executable'])<=256)
         if compression:
             want(type(value['quality']) is int and value['quality']==11 and type(value.get('roundtrip')) is bool)
         else:
             want(value.get('source_kind')=='d27_fixed_test_driver_v1')
             if value.get('case') is not None:want(value['case']=='geometry')
             if value.get('driver_role') is not None:want(value['driver_role']=='geometry')
             if value.get('driver_getter') is not None:want(value['driver_getter']=='d27_geometry_driver_v1')
             if value.get('case_completed') is not None:want(type(value['case_completed']) is bool)
             if value.get('case_cause') is not None:want(value['case_cause'] in ('d27_codec_absent','d27_driver_assertion','d27_driver_input','d27_driver_error','d27_node_version','d27_geometry_hold'))
             if value.get('program_bytes') is not None:want(0<value['program_bytes']<=24576)
         for name,cap in (('stdout',1048576),('stderr',16384)):
             channel=value.get(name);want(type(channel) is dict and set(channel)==PIPE_KEYS)
             for key in ('eof','overflow','closed','unknown_remainder'):want(type(channel[key]) is bool)
             want(integer(channel['observed_bytes']) and integer(channel['retained_bytes'],0,cap)
                  and channel['observed_bytes']>=channel['retained_bytes'] and sha_text(channel['prefix_sha256']))
             want(channel['io_error'] is None or type(channel['io_error']) is str and re.fullmatch('[A-Za-z_][A-Za-z0-9_]{0,127}',channel['io_error']) is not None)
             want(channel['unknown_remainder'] is (not channel['eof'] or channel['overflow'] or channel['io_error'] is not None))
         if value.get('parent_observed_completion') is True:
             want(integer(value.get('pid'),1) and integer(value.get('input_bytes'),1,262144)
                  and sha_text(value.get('input_sha256')) and sha_text(value.get('program_sha256')))
             want(set(value)==allowed and value.get('node_version')=='25.2.1'
                  and type(value.get('returncode')) is int and value['returncode']==0 and value['causes']==[])
             for key in ('spawned','reaped','threads_joined','stdin_complete','stdin_closed','stdin_write_attempted',
                         'finished_before_deadline','child_completion_observed_before_deadline'):want(value[key] is True)
             for key in ('timed_out','kill_requested','stdin_extent_unknown','stdin_write_in_flight'):want(value[key] is False)
             want(value['threads_started']==3 and value['command_options']==['--max-old-space-size=256','--input-type=commonjs','-e'])
             want(value['environment_keys'] in (['PATH'],['PATH','SystemRoot']))
             for key in ('started_monotonic','elapsed_seconds','caller_deadline','work_deadline','child_total_deadline','cleanup_deadline'):want(number(value[key]))
             start=value['started_monotonic'];end=value['caller_deadline'];work=min(start+27,end-8);total=min(start+30,end-5);observed=start+value['elapsed_seconds']
             want(value['work_deadline']==work and value['child_total_deadline']==total
                  and value['cleanup_deadline']<=min(total,work+3)
                  and observed<end and observed<total and observed<value['cleanup_deadline'])
             want(value['stdin_bytes']==value['input_bytes'])
             for channel in (value['stdout'],value['stderr']):
                 want(channel['eof'] is True and channel['closed'] is True and channel['overflow'] is False
                      and channel['io_error'] is None and channel['unknown_remainder'] is False
                      and channel['observed_bytes']==channel['retained_bytes'])
             want(value['stderr']['retained_bytes']==0 and value['stderr']['prefix_sha256']=='e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855')
             if compression:
                 want(value['roundtrip'] is True and value['stderr_prefix_b64']==''
                      and integer(value.get('packed_bytes'),1,32768) and sha_text(value.get('packed_sha256')))
             else:
                 want(type(value['case_completed']) is bool and value['case']=='geometry' and value['node_version']=='25.2.1'
                      and integer(value.get('program_bytes'),1,24576) and integer(value.get('data_bytes'),0,262144)
                      and sha_text(value.get('data_sha256')) and integer(value.get('report_bytes'),1,32768)
                      and sha_text(value.get('report_sha256')) and integer(value.get('checks_count'),0,512)
                      and integer(value.get('measurements_count'),0,128))
         return value
     def driver_metadata(value):
      if type(value) is not dict or set(value)!={'source_kind','driver_role','driver_getter','program_bytes','program_sha256'} or value['source_kind']!='d27_fixed_test_driver_v1' or value['driver_role']!='geometry' or value['driver_getter']!='d27_geometry_driver_v1' or type(value['program_bytes']) is not int or not 0<value['program_bytes']<=24576 or not sha_text(value['program_sha256']):raise ValueError('d27_driver_binding')
      return value
     def role_metadata(value):
      if type(value) is not dict or set(value)!=ROLE_KEYS or value['kind']!='d27_node_codec_role_v1' or value['marker_occurrences']!=1 or type(value['marker_occurrences']) is not int or value['role_is_exact_prefix'] is not True or value['encoder_excluded'] is not True:raise ValueError('d27_role_shape')
      for name in ('full_codec_bytes','node_codec_bytes','excluded_encoder_bytes'):
       if type(value[name]) is not int or not 0<value[name]<=6907 or not sha_text(value[name.replace('_bytes','_sha256')]):raise ValueError('d27_role_pin')
      if value['node_codec_bytes']+value['excluded_encoder_bytes']!=value['full_codec_bytes'] or value['full_codec_sha256'] in ('56708c18c942acfb6e8153971a0013ca79c955e4182efff590ad7ae3a2ba2432','c65b73fe0e7d274040dda413b7871ee83c4c952f9bb2c1e74962b0e3e5f34767'):raise ValueError('d27_role_extent_or_legacy')
      return value
     def source_metadata(value):
      if type(value) is not dict:raise ValueError('d27_source_shape')
      if value.get('kind')=='d27_construction_failure_metadata_v1':
       if set(value)!=FAIL_KEYS or type(value['error_type']) is not str or not re.fullmatch('[A-Za-z_][A-Za-z0-9_]{0,95}',value['error_type']) or type(value['message_size_bytes']) is not int or value['message_size_bytes']<0 or not sha_text(value['message_sha256']):raise ValueError('d27_construction_shape')
       if type(value['capture_metadata_unavailable']) is not bool or not (value['capture_metadata_size_bytes'] is None and value['capture_metadata_sha256'] is None) and (type(value['capture_metadata_size_bytes']) is not int or value['capture_metadata_size_bytes']<0 or not sha_text(value['capture_metadata_sha256'])):raise ValueError('d27_construction_capture')
       if value['capture'] is not None:
        capture_metadata(value['capture']);encoded=canon(value['capture'])
        if value['capture_metadata_unavailable'] or len(encoded)>30000 or len(encoded)!=value['capture_metadata_size_bytes'] or hashlib.sha256(encoded).hexdigest()!=value['capture_metadata_sha256']:raise ValueError('d27_construction_capture')
       elif value['capture_metadata_unavailable'] is not True:raise ValueError('d27_construction_unavailable')
       for name in ('generated_operational_program_execution','generated_full_subject_files_written','physical_acceptance'):
        if value[name] is not False:raise ValueError('d27_construction_authority')
       return bounded(value)
      if set(value)!=SOURCE_KEYS or value.get('kind')!='d27_inert_source_construction_metadata_v1':raise ValueError('d27_source_shape')
      initial=value['initial'];final=value['finalizer'];executor=value['executor']
      if type(initial) is not dict or set(initial)!=INITIAL_KEYS or initial['kind']!='d24_initial_source_only_v1' or type(final) is not dict or set(final)!=FINAL_KEYS or type(executor) is not dict or set(executor)!={'size_bytes','sha256'}:raise ValueError('d27_source_nested')
      if (initial['source_bytes'],initial['source_sha256'],initial['canonical_data_bytes'],initial['canonical_data_sha256'],initial['compressed_data_bytes'],initial['compressed_data_sha256'])!=(14162,'4032a534147aada87931734f3b06cde67988d62c75851b959945399843a3770d',6566,'8ca48e37f97d03af660960f75afab79db162e8f8997f39f6c1c5c55dd896c97e',2365,'a7caf17aa8d2d5d6beb60880d415e7328947d188623bf5fa0d1ad566e1fd2f2f'):raise ValueError('d27_initial_expected_recipe')
      driver_metadata(value['driver'])
      if FIXED_DRIVER is None or value['driver']!=FIXED_DRIVER:raise ValueError('d27_source_driver_join')
      if initial['prefix_bytes']!=295 or initial['prefix_sha256']!='ea63175835e2149d61c71d52696c62033d17b908f76ca0a20cf25e32b18f142b' or type(initial['data_fields']) is not int or initial['data_fields']!=9 or initial['strings_field_absent'] is not True:raise ValueError('d27_source_initial')
      if any(initial[name] is not True for name in ('exact_decoder_inverse','exact_phase_inverse','exact_inverse_source')):raise ValueError('d27_source_initial_inverse')
      escaped=initial['escaped_source_bytes'];fits=initial['source_contribution_fits'];over=initial['source_only_over_cap_by']
      if type(escaped) is not int or escaped<=0 or type(fits) is not bool or fits is not (escaped<=12288) or type(over) is not int or over!=max(0,escaped-12288) or initial['status']!=('UNQUALIFIED_SOURCE_ONLY' if fits else 'HOLD_SOURCE_CONTRIBUTION_OVER_CAP'):raise ValueError('d27_source_initial_state')
      if initial['baseline_bytes']!=initial['prefix_bytes']+initial['decoder_bytes']+initial['baseline_body_bytes'] or not 0<initial['canonical_data_bytes']<=16384 or initial['base64_data_bytes']!=4*((initial['compressed_data_bytes']+2)//3):raise ValueError('d27_source_data_extent')
      role=value['node_codec']
      if type(role) is not dict or set(role)!=ROLE_KEYS or role['kind']!='d27_node_codec_role_v1' or type(role['marker_occurrences']) is not int or role['marker_occurrences']!=1 or role['role_is_exact_prefix'] is not True or role['encoder_excluded'] is not True:raise ValueError('d27_node_role_shape')
      role_metadata(role)
      if ROLE_EXPECTED is None or role!=ROLE_EXPECTED:raise ValueError('d27_node_role_binding')
      for name in ('complete_geometry_qualified','behavior_conformance_complete','finalizer_implemented','generated_operational_program_executed','generated_full_subject_files_written','task_2_10_complete'):
       if initial[name] is not False:raise ValueError('d27_source_initial_authority')
      compression=capture_metadata(initial['compression'])
      if compression.get('parent_observed_completion') is not True or compression.get('returncode')!=0 or compression.get('causes') or compression.get('quality')!=11 or compression.get('roundtrip') is not True:raise ValueError('d27_source_compression')
      for name in ('data_only','finished_before_deadline','child_completion_observed_before_deadline','reaped','threads_joined','stdin_complete','stdin_closed'):
       if compression.get(name) is not True:raise ValueError('d27_source_compression_completion')
      for name in ('timed_out','kill_requested','stdin_extent_unknown'):
       if compression.get(name) is not False:raise ValueError('d27_source_compression_unknown')
      if compression['started_monotonic']+compression['elapsed_seconds']>=compression['cleanup_deadline']:raise ValueError('d27_source_compression_cleanup')
      for channel in (compression['stdout'],compression['stderr']):
       if channel['eof'] is not True or channel['closed'] is not True or channel['overflow'] is not False or channel['io_error'] is not None or channel['unknown_remainder'] is not False:raise ValueError('d27_source_compression_pipe')
      if compression.get('input_bytes')!=initial['canonical_data_bytes'] or compression.get('input_sha256')!=initial['canonical_data_sha256'] or compression.get('stdin_bytes')!=initial['canonical_data_bytes'] or compression.get('packed_bytes')!=initial['compressed_data_bytes'] or compression.get('packed_sha256')!=initial['compressed_data_sha256']:raise ValueError('d27_source_compression_data_join')
      for name in ('generated_operational_program_execution','generated_full_subject_files_written'):
       if final[name] is not False:raise ValueError('d27_finalizer_authority')
      if final['initial_size_bytes']!=initial['source_bytes'] or final['initial_sha256']!=initial['source_sha256'] or final['factory_size_bytes']!=13073 or final['factory_sha256']!='997579f8ffcc50d6e05ae859dd9164b1dc08ce5a71e82a1d8070633c3cdf3677':raise ValueError('d27_finalizer_binding')
      for record in (initial,final,role):
       for name,item in record.items():
        if name.endswith('_sha256') and not sha_text(item):raise ValueError('d27_source_hash_kind')
        if name.endswith('_bytes') and (type(item) is not int or item<=0):raise ValueError('d27_source_size_kind')
      if value['modeled_setup_form_count']!=6 or value['modeled_later_form_count']!=6 or value['controlled_synthetic_geometry_only'] is not True:raise ValueError('d27_source_counts')
      for name in ('independent_actual_acquisition_proven','generated_operational_program_execution','generated_full_subject_files_written','behavior_conformance_complete','physical_acceptance'):
       if value[name] is not False:raise ValueError('d27_source_authority')
      for item in (executor,{'size_bytes':value['input_data_size_bytes'],'sha256':value['input_data_sha256']},{'size_bytes':final['finalizer_size_bytes'],'sha256':final['finalizer_sha256']}):
       if type(item['size_bytes']) is not int or not 0<item['size_bytes']<=9007199254740991 or not sha_text(item['sha256']):raise ValueError('d27_source_pin')
      return bounded(value)
     def metadata(value):
      if type(value) is not dict or set(value)!={'case','report','capture'} or value['case']!='geometry':raise ValueError('d27_case_shape')
      report=value['report'];capture=value['capture']
      if type(report) is not dict or set(report)!={'schema_version','case','node_version','completed','cause','checks','measurements'} or type(report['schema_version']) is not int or report['schema_version']!=1 or report['case']!='geometry' or report['node_version']!='25.2.1' or type(report['completed']) is not bool:raise ValueError('d27_case_identity')
      if report['cause'] not in (None,'d27_geometry_hold','d27_codec_absent','d27_driver_assertion','d27_driver_input','d27_node_version','d27_driver_error'):raise ValueError('d27_case_cause')
      if type(report['checks']) is not list or len(report['checks'])>512 or type(report['measurements']) is not list or len(report['measurements'])>128:raise ValueError('d27_case_rows')
      for row in report['checks']:
       if type(row) is not dict or set(row)!={'id','ok'} or type(row['id']) is not str or not re.fullmatch('[A-Za-z0-9_]{1,64}',row['id']) or type(row['ok']) is not bool:raise ValueError('d27_case_check')
      for row in report['measurements']:
       if type(row) is not dict or set(row)!={'id','size_bytes','sha256'} or type(row['id']) is not str or not re.fullmatch('[A-Za-z0-9_]{1,64}',row['id']) or type(row['size_bytes']) is not int or not 0<=row['size_bytes']<=262144 or not sha_text(row['sha256']):raise ValueError('d27_case_measurement')
      capture_metadata(capture)
      if capture.get('case')!='geometry':raise ValueError('d27_case_capture')
      if set(capture)!=CAPTURE_KEYS or capture.get('source_kind')!='d27_fixed_test_driver_v1' or FIXED_DRIVER is None or {key:capture.get(key) for key in FIXED_DRIVER}!=FIXED_DRIVER:raise ValueError('d27_case_driver_join')
      for key in ('checks_count','measurements_count','report_bytes','input_bytes','data_bytes','stdin_bytes','program_bytes'):
       if type(capture.get(key)) is not int or capture[key]<0:raise ValueError('d27_case_counter')
      return value
     def exception_capture(error):
      value=getattr(error,'metadata',None);encoded=None;result={'capture':None,'capture_metadata_unavailable':True,'capture_metadata_size_bytes':None,'capture_metadata_sha256':None}
      try:
       encoded=canon(value);result.update(capture_metadata_size_bytes=len(encoded),capture_metadata_sha256=hashlib.sha256(encoded).hexdigest())
       if value is not None and len(encoded)<=30000:capture_metadata(value);result.update(capture=value,capture_metadata_unavailable=False)
      except BaseException:pass
      return result
     def validate_exception_capture(value):
      if type(value) is not dict or set(value)!={'capture','capture_metadata_unavailable','capture_metadata_size_bytes','capture_metadata_sha256'} or type(value['capture_metadata_unavailable']) is not bool:raise ValueError('d27_exception_capture')
      n=value['capture_metadata_size_bytes'];h=value['capture_metadata_sha256']
      if not (n is None and h is None) and (type(n) is not int or n<0 or not sha_text(h)):raise ValueError('d27_exception_capture_pin')
      if value['capture'] is not None:
       capture_metadata(value['capture']);raw=canon(value['capture'])
       if value['capture_metadata_unavailable'] or len(raw)>30000 or n!=len(raw) or h!=hashlib.sha256(raw).hexdigest():raise ValueError('d27_exception_capture_binding')
      elif value['capture_metadata_unavailable'] is not True:raise ValueError('d27_exception_capture_unavailable')
      return value
     def geometry_evidence(source,case,collection_only=False):
      if source.get('kind')!='d27_inert_source_construction_metadata_v1' or case is None:return False,False
      report=case['report'];capture=case['capture'];checks={r['id']:r['ok'] for r in report['checks']};measurements={r['id']:r for r in report['measurements']}
      if not checks or len(checks)!=len(report['checks']) or len(measurements)!=len(report['measurements']) or capture.get('parent_observed_completion') is not True:return False,False
      if capture.get('data_bytes')!=source['input_data_size_bytes'] or capture.get('data_sha256')!=source['input_data_sha256'] or capture.get('input_bytes')!=source['input_data_size_bytes']+27:return False,False
      report_bytes=canon(report)+b'\n'
      if capture.get('report_bytes')!=len(report_bytes) or capture.get('report_sha256')!=hashlib.sha256(report_bytes).hexdigest() or capture.get('checks_count')!=len(report['checks']) or capture.get('measurements_count')!=len(report['measurements']) or capture.get('case_completed') is not report['completed'] or capture.get('case_cause')!=report['cause']:return False,False
      for name in ('data_only','spawned','finished_before_deadline','child_completion_observed_before_deadline','reaped','threads_joined','stdin_complete','stdin_closed'):
       if capture.get(name) is not True:return False,False
      for name in ('timed_out','kill_requested','stdin_extent_unknown','stdin_write_in_flight'):
       if capture.get(name) is not False:return False,False
      if capture.get('causes') or type(capture.get('returncode')) is not int or capture['returncode']!=0 or capture.get('descendant_quiescence')!='UNKNOWN' or capture.get('stdin_bytes')!=capture.get('input_bytes'):return False,False
      for name in ('stdout','stderr'):
       channel=capture[name]
       if channel['eof'] is not True or channel['closed'] is not True or channel['overflow'] is not False or channel['io_error'] is not None or channel['unknown_remainder'] is not False:return False,False
      if capture['stdout']['retained_bytes']!=len(report_bytes) or capture['stdout']['prefix_sha256']!=hashlib.sha256(report_bytes).hexdigest() or capture['stderr']['retained_bytes']!=0:return False,False
      caps={};required={'source_bindings','six_setup_forms','six_later_forms','approval_slots','later_measured_upstream'}
      for name in ('initial_source','finalizer_source','executor_source'):caps[name]=262144
      for prefix in ('success','structured_failure','unicode_failure','partial_emission','unknown_closure','setup_refusal'):
       for suffix,cap in (('selected_original',32768),('observed_original',32768),('selected_wire',12288),('observed_wire',12288),('ack',24576),('writer_stdout',2112),('root',65536),('chain',262144)):caps[prefix+'_'+suffix]=cap
       required.update(prefix+suffix for suffix in ('_setup','_provider_pipes','_pipe0_inverse','_pipe1_inverse','_pipe2_inverse','_full_roundtrip','_uint64','_writer_pipe0_inverse','_writer_pipe1_inverse','_chain_join'))
      for stage in ('C1_success','C1_failure','C6_success','C6_failure','D_success','D_failure'):
       selected=stage+'_selected';caps[selected]=4096;caps[stage+'_native_input']=32768
       required.update(stage+suffix for suffix in ('_later','_pipe_limits','_pipe0_inverse','_pipe1_inverse'))
       if selected not in measurements:return False,False
       if measurements[selected]['size_bytes']<=4096:
        caps[stage+'_ack']=16384;caps[stage+'_writer_stdout']=2112
        required.update(stage+suffix for suffix in ('_uint64','_writer_pipe0_inverse','_writer_pipe1_inverse'))
      if set(measurements)!=set(caps):return False,False
      for name,cap in caps.items():
       require(measurements[name]['size_bytes']>0,'geometry_positive_measurement')
       if name+'_bound' not in checks:return False,False
       require(checks[name+'_bound'] is (measurements[name]['size_bytes']<=cap),'geometry_bound_correspondence')
      required.update(name+'_bound' for name in caps)
      for prefix in ('success','structured_failure','unicode_failure','partial_emission','unknown_closure','setup_refusal'):
       wire=measurements[prefix+'_selected_wire']['size_bytes'];q=((wire+4095)//4096)*4096
       expected={prefix+'_writer_input_bound':measurements[prefix+'_ack']['size_bytes']+65471<=90112,prefix+'_forms_bound':max(12288,q)+q+8192<=32768}
       for name,ok in expected.items():
        if name not in checks:return False,False
        require(checks[name] is ok,'geometry_allocation_correspondence')
       required.update(expected)
      for stage in ('C1_success','C1_failure','C6_success','C6_failure','D_success','D_failure'):
       if measurements[stage+'_selected']['size_bytes']<=4096:
        wire=measurements[stage+'_selected']['size_bytes'];q=((wire+4095)//4096)*4096
        expected={stage+'_writer_input_bound':measurements[stage+'_ack']['size_bytes']+65471<=81920,stage+'_writer_forms_bound':max(4096,q)+q+8192<=16384}
        for name,ok in expected.items():
         if name not in checks:return False,False
         require(checks[name] is ok,'geometry_allocation_correspondence')
        required.update(expected)
      if set(checks)!=required:return False,False
      for name,n,h in (('initial_source',source['initial']['source_bytes'],source['initial']['source_sha256']),('finalizer_source',source['finalizer']['finalizer_size_bytes'],source['finalizer']['finalizer_sha256']),('executor_source',source['executor']['size_bytes'],source['executor']['sha256'])):
       if measurements[name]['size_bytes']!=n or measurements[name]['sha256']!=h:return False,False
      require(all(ok or name.endswith('_bound') for name,ok in checks.items()),'geometry_complete_nonbound_failure')
      require(report['completed'] is all(checks.values()) and report['cause']==(None if all(checks.values()) else 'd27_geometry_hold'),'geometry_complete_report_status')
      if collection_only:return True,False
      return True,report['completed']
     ROLE_EXPECTED={'kind':'d27_node_codec_role_v1','full_codec_bytes':admitted['codec']['full']['size_bytes'],'full_codec_sha256':admitted['codec']['full']['sha256'],'node_codec_bytes':admitted['codec']['decoder']['size_bytes'],'node_codec_sha256':admitted['codec']['decoder']['sha256'],'excluded_encoder_bytes':admitted['codec']['tail']['size_bytes'],'excluded_encoder_sha256':admitted['codec']['tail']['sha256'],'marker_occurrences':1,'role_is_exact_prefix':True,'encoder_excluded':True}
     FIXED_DRIVER={'source_kind':'d27_fixed_test_driver_v1','driver_role':'geometry','driver_getter':'d27_geometry_driver_v1','program_bytes':admitted['driver']['size_bytes'],'program_sha256':admitted['driver']['sha256']}
     pins=[{'path':path,**admitted[role]} for path,role in zip(MODULE_PATHS,('main','caller'))]
     expected_id='tests.test_accepted_policy_fixture_compiler_gate2_dictionary_caller_v1.D27CompleteGeometryTests.test_complete_form_bounds_preserve_hold'
     wire_events=('source_bindings','test_started','test_terminal','subtest_issue','parent_issue','test_summary','entry_failure')
     error_fields={'error_type','message_size_bytes','message_sha256','exception_capture'}
     binding_fields=set('event sources both_buffers_verified_before_either_compile held_driver_loader_bound held_driver_module execution_reopens_test_paths held_driver_aliases_bound held_caller_aliases_bound codec_role fixed_driver'.split())
     summary_fields=set('event selected_class tests_run expected_metadata_records geometry_source_records geometry_case_records successes failures errors skips expected_failures unexpected_successes issue_events subtest_callbacks parent_outcomes successful test_streams generated_operational_program_execution descendant_quiescence'.split())
     stream_fields=set('observed_bytes sha256 metadata_records geometry_source_records geometry_case_records unexpected_or_unterminated raw_values_retained'.split())
     def count(value):require(type(value) is int and 0<=value<=1048576,'protocol_counter')
     def error_facts(row):
         require(type(row['error_type']) is str and re.fullmatch('[A-Za-z_][A-Za-z0-9_]{0,95}',row['error_type']) is not None,'protocol_error_type')
         if 'message_unavailable' in row:
             require(row['message_unavailable'] is True and row['message_size_bytes'] is None and row['message_sha256'] is None,'protocol_unavailable_message')
         else:integer(row['message_size_bytes'],0,9007199254740991);hex64(row['message_sha256'])
         if 'exception_capture' in row:validate_exception_capture(row['exception_capture'])
     def event_shape(row):
         require(type(row) is dict and row.get('event') in wire_events,'protocol_event')
         event=row['event'];optional={'message_unavailable'} if 'message_unavailable' in row else set()
         if event=='source_bindings':
             samekeys(row,binding_fields)
             require(row['sources']==pins and row['both_buffers_verified_before_either_compile'] is True and row['held_driver_loader_bound'] is True and row['held_driver_module']=='tests.test_accepted_policy_fixture_compiler_gate2_dictionary_v1' and row['execution_reopens_test_paths'] is False and row['held_driver_aliases_bound'] is True and row['held_caller_aliases_bound'] is True,'protocol_binding')
             require(role_metadata(row['codec_role'])==ROLE_EXPECTED and driver_metadata(row['fixed_driver'])==FIXED_DRIVER,'protocol_role_binding')
         elif event=='test_started':samekeys(row,('event','test_id'));require(row['test_id']==expected_id,'protocol_test_id')
         elif event in ('subtest_issue','parent_issue'):
             samekeys(row,{'event','test_id','issue_index','subtest_ordinal','outcome'}|error_fields|optional)
             require(row['test_id']==expected_id and row['outcome'] in ('failure','error','expected_failure'),'protocol_issue_identity')
             integer(row['issue_index'],1,512);error_facts(row)
             if event=='subtest_issue':integer(row['subtest_ordinal'],1,512);require(row['outcome'] in ('failure','error'),'protocol_subtest_outcome')
             else:require(row['subtest_ordinal'] is None,'protocol_parent_ordinal')
         elif event=='test_terminal':
             base={'event','test_id','subtest_callbacks','issue_counts','outcome'}
             require(row['outcome'] in ('success','failure','error','skip','expected_failure','unexpected_success'),'protocol_terminal_outcome')
             samekeys(row,base|error_fields|optional if row['outcome'] in ('failure','error','expected_failure') else base)
             require(row['test_id']==expected_id,'protocol_terminal_identity');integer(row['subtest_callbacks'],0,512)
             samekeys(row['issue_counts'],('subtest_issue','parent_issue'))
             for value in row['issue_counts'].values():integer(value,0,512)
             if row['outcome'] in ('failure','error','expected_failure'):error_facts(row)
         elif event=='entry_failure':
             samekeys(row,{'event','error_type','message_size_bytes','message_sha256','secondary'}|optional);error_facts(row)
             require(type(row['secondary']) is list and len(row['secondary'])<=128 and all(type(v) is str and re.fullmatch('[A-Za-z_][A-Za-z0-9_]{0,95}',v) for v in row['secondary']),'protocol_entry_secondary')
         else:
             samekeys(row,summary_fields)
             require(row['selected_class']==CLASS_NAME and type(row['successful']) is bool and row['generated_operational_program_execution'] is False and row['descendant_quiescence']=='UNKNOWN','protocol_summary_identity')
             for key in ('tests_run','expected_metadata_records','geometry_source_records','geometry_case_records','successes','failures','errors','skips','expected_failures','unexpected_successes','issue_events','subtest_callbacks'):count(row[key])
             outcomes=row['parent_outcomes']
             require(type(outcomes) is dict and set(outcomes)<=set(('success','failure','error','skip','expected_failure','unexpected_success')),'protocol_parent_outcomes')
             for value in outcomes.values():integer(value,1,512)
             samekeys(row['test_streams'],('stdout','stderr'))
             for stream in row['test_streams'].values():
                 samekeys(stream,stream_fields);integer(stream['observed_bytes'],0,9007199254740991);hex64(stream['sha256'])
                 for key in ('metadata_records','geometry_source_records','geometry_case_records'):count(stream[key])
                 require(type(stream['unexpected_or_unterminated']) is bool and stream['raw_values_retained'] is False,'protocol_stream_flags')
     rows=[];incomplete=type(stdout) is not bytes or type(stderr) is not bytes or bool(stderr)
     if type(stdout) is bytes:
         for line in stdout.splitlines(keepends=True):
             if len(line)>32768 or not line.endswith(b'\n') or not line.isascii():incomplete=True;continue
             tagged=None;payload=line[:-1]
             for prefix,event in ((b'D27_GEOMETRY_SOURCE_METADATA ','source_metadata'),(b'D27_CASE_METADATA ','case_metadata')):
                 if payload.startswith(prefix):tagged=event;payload=payload[len(prefix):];break
             try:value=json.loads(payload,object_pairs_hook=pairs,parse_constant=lambda unused: (_ for _ in ()).throw(AssertionError('protocol_nonfinite')))
             except (json.JSONDecodeError,UnicodeError):incomplete=True;continue
             require(canon(value)==payload,'protocol_canonical_record')
             if tagged is not None:
                 try:value={'event':tagged,'data':source_metadata(value) if tagged=='source_metadata' else metadata(value)}
                 except (ValueError,TypeError,KeyError):raise AssertionError('contradictory_tagged_metadata') from None
             elif type(value) is dict and value.get('event') in ('source_metadata','case_metadata'):
                 raise AssertionError('untagged_metadata_impersonation')
             elif type(value) is not dict or value.get('event') not in wire_events:incomplete=True;continue
             else:
                 try:event_shape(value)
                 except (ValueError,TypeError,KeyError):raise AssertionError('contradictory_protocol_record') from None
             rows.append(value)
     sources=[row['data'] for row in rows if row['event']=='source_metadata']
     cases=[row['data'] for row in rows if row['event']=='case_metadata']
     summaries=[row for row in rows if row['event']=='test_summary']
     bindings=[row for row in rows if row['event']=='source_bindings']
     starts=[row for row in rows if row['event']=='test_started'];terminals=[row for row in rows if row['event']=='test_terminal']
     require(len(sources)<=1 and len(cases)<=1 and len(summaries)<=1 and len(bindings)<=1 and len(starts)<=1 and len(terminals)<=1,'duplicate_protocol_record')
     if bindings:require(rows[0] is bindings[0],'protocol_binding_order')
     active=False;issues=[];last_subtest=0
     for index,row in enumerate(rows):
         event=row['event']
         if event=='test_started':require(not active,'protocol_start_order');active=True
         elif event in ('source_metadata','case_metadata'):
             require(active,'protocol_metadata_parent')
             if event=='case_metadata':require(sources and any(v['event']=='source_metadata' for v in rows[:index]),'protocol_metadata_order')
         elif event in ('subtest_issue','parent_issue'):
             require(active and row['issue_index']==len(issues)+1,'protocol_issue_order')
             if event=='subtest_issue':require(last_subtest<row['subtest_ordinal'],'protocol_subtest_order');last_subtest=row['subtest_ordinal']
             issues.append(row)
         elif event=='test_terminal':
             require(active,'protocol_terminal_order');active=False
             require(row['subtest_callbacks']>=last_subtest and row['issue_counts']=={name:sum(v['event']==name for v in issues) for name in ('subtest_issue','parent_issue')},'protocol_terminal_counts')
             selected=next((v for kind in ('error','failure','expected_failure') for v in issues if v['outcome']==kind),None)
             if selected is not None:
                 require(row['outcome']==selected['outcome'],'protocol_issue_precedence')
                 for key in error_fields|{'message_unavailable'}:require(row.get(key)==selected.get(key),'protocol_terminal_error_join')
             else:require(row['outcome'] in ('success','skip','unexpected_success'),'protocol_terminal_issue_absent')
         elif event=='test_summary':require(index==len(rows)-1,'protocol_summary_order')
     if sources and sources[0]['kind']=='d27_construction_failure_metadata_v1':require(not cases,'protocol_failed_construction_case')
     if cases:
         report=cases[0]['report'];capture=cases[0]['capture'];validate_report(report)
         known=canon(report)+b'\n'
         require(capture['report_bytes']==len(known) and capture['report_sha256']==sha(known) and capture['stdout']['retained_bytes']==len(known) and capture['stdout']['prefix_sha256']==sha(known) and capture['checks_count']==len(report['checks']) and capture['measurements_count']==len(report['measurements']) and capture['case_completed'] is report['completed'] and capture['case_cause']==report['cause'],'protocol_report_capture_join')
         if sources and sources[0]['kind']=='d27_inert_source_construction_metadata_v1':
             source=sources[0]
             require(capture['data_bytes']==source['input_data_size_bytes'] and capture['data_sha256']==source['input_data_sha256'] and capture['input_bytes']==source['input_data_size_bytes']+27,'protocol_input_join')
             measurements={v['id']:v for v in report['measurements']}
             for name,n,h in (('initial_source',source['initial']['source_bytes'],source['initial']['source_sha256']),('finalizer_source',source['finalizer']['finalizer_size_bytes'],source['finalizer']['finalizer_sha256']),('executor_source',source['executor']['size_bytes'],source['executor']['sha256'])):
                 if name in measurements:require(measurements[name]['size_bytes']==n and measurements[name]['sha256']==h,'protocol_observed_source_join')
     if summaries:
         summary=summaries[0];counts={name:sum(row['outcome']==name for row in terminals) for name in ('success','failure','error','skip','expected_failure','unexpected_success')}
         require(summary['tests_run']==len(starts)==len(terminals) and not active and summary['parent_outcomes']=={name:n for name,n in counts.items() if n},'protocol_summary_terminals')
         expected={'successes':counts['success'],'failures':sum(v['outcome']=='failure' for v in issues),'errors':sum(v['outcome']=='error' for v in issues),'skips':counts['skip'],'expected_failures':sum(v['outcome']=='expected_failure' for v in issues),'unexpected_successes':counts['unexpected_success'],'issue_events':len(issues),'subtest_callbacks':sum(v['subtest_callbacks'] for v in terminals),'expected_metadata_records':2,'geometry_source_records':len(sources),'geometry_case_records':len(cases)}
         require(all(summary[key]==value for key,value in expected.items()),'protocol_summary_counts')
         out=summary['test_streams']['stdout'];err=summary['test_streams']['stderr']
         require(out['metadata_records']==len(sources)+len(cases) and out['geometry_source_records']==len(sources) and out['geometry_case_records']==len(cases) and all(err[k]==0 for k in ('metadata_records','geometry_source_records','geometry_case_records')),'protocol_stream_counts')
         # The D27 producer rejects every nonmetadata write, including blank LFs.
         forwarded=b''.join((b'D27_GEOMETRY_SOURCE_METADATA ' if row['event']=='source_metadata' else b'D27_CASE_METADATA ')+canon(row['data'])+b'\n' for row in rows if row['event'] in ('source_metadata','case_metadata'))
         if out['unexpected_or_unterminated'] is False:require(out['observed_bytes']==len(forwarded) and out['sha256']==sha(forwarded),'protocol_forwarded_stream_join')
         if err['observed_bytes']==0:require(err['sha256']==sha(b''),'protocol_empty_stderr_sha')
         green=(counts['success']==1 and not issues and not any(counts[name] for name in ('failure','error','skip','expected_failure','unexpected_success')) and len(sources)==len(cases)==1 and sources[0]['kind']=='d27_inert_source_construction_metadata_v1' and out['metadata_records']==2 and out['unexpected_or_unterminated'] is False and err['unexpected_or_unterminated'] is False and err['observed_bytes']==0)
         require(summary['successful'] is green,'protocol_summary_success')
     else:summary=None;green=False
     complete=(not incomplete and len(bindings)==len(starts)==len(terminals)==len(summaries)==1 and len(sources)==1 and not any(row['event'] in ('entry_failure','fixture_terminal') for row in rows))
     source=sources[0] if sources else None;case=cases[0] if cases else None
     if parent is not None:
         for helper in ([source['initial']['compression']] if source and source['kind']=='d27_inert_source_construction_metadata_v1' else [])+([case['capture']] if case else []):
             if helper.get('parent_observed_completion') is True:require(helper['caller_deadline']==parent['work_deadline'],'protocol_parent_helper_clock')
         require(parent['protocol_error_type']==(None if complete else 'd27_protocol_incomplete'),'original_protocol_contradiction')
         if complete:
             require(type(parent['returncode']) is int and parent['returncode']==(0 if green else 1),'protocol_child_status')
             require(parent['fixed_driver_binding']==FIXED_DRIVER and parent['codec_role_binding']==ROLE_EXPECTED,'protocol_parent_roles')
     if not complete:return source,case,None,False,False,False
     full,passed=geometry_evidence(source,case) if source else (False,False)
     collected=geometry_evidence(source,case,True)[0] if source else False
     return source,case,summary,full,passed,collected
    return original_protocol(stdout,stderr,parent,admitted)


def d27_capture_metadata_v1(value):
    """Validate finite capture DATA before any serialization."""
    CAPTURE_KEYS=set('caller_deadline case case_cause case_completed causes checks_count child_completion_observed_before_deadline child_total_deadline child_total_limit_seconds child_work_limit_seconds cleanup_deadline cleanup_limit_seconds command_options data_bytes data_only data_sha256 descendant_quiescence elapsed_seconds environment_keys final_reserve_seconds finished_before_deadline input_bytes input_sha256 kill_requested measurements_count node_executable node_version parent_observed_completion pid program_sha256 reaped report_bytes report_sha256 returncode schema_version spawned started_monotonic stderr stdin_bytes stdin_closed stdin_complete stdin_extent_unknown stdin_write_attempted stdin_write_in_flight stdout threads_joined threads_started timed_out work_deadline'.split())
    PIPE_KEYS=set('observed_bytes retained_bytes eof overflow io_error closed unknown_remainder prefix_sha256'.split())
    COMP_KEYS=(CAPTURE_KEYS-set('case case_cause case_completed data_bytes data_sha256 report_bytes report_sha256 checks_count measurements_count'.split()))|set('quality roundtrip packed_bytes packed_sha256 stderr_prefix_b64'.split())
    CAPTURE_KEYS|={'source_kind','driver_role','driver_getter','program_bytes'}
    INITIAL_KEYS=set('kind source_bytes source_sha256 escaped_source_bytes baseline_bytes baseline_sha256 original_builder_bytes original_builder_sha256 baseline_body_bytes baseline_body_sha256 prefix_bytes prefix_sha256 decoder_bytes decoder_sha256 canonical_data_bytes canonical_data_sha256 compressed_data_bytes compressed_data_sha256 base64_data_bytes base64_data_sha256 data_fields strings_field_absent deferred_definition_bytes deferred_definition_sha256 exact_decoder_inverse exact_phase_inverse exact_inverse_source source_contribution_fits source_only_over_cap_by complete_geometry_qualified behavior_conformance_complete finalizer_implemented generated_operational_program_executed generated_full_subject_files_written status task_2_10_complete compression'.split())
    FINAL_KEYS=set('initial_size_bytes initial_sha256 finalizer_size_bytes finalizer_sha256 factory_size_bytes factory_sha256 wrapper_prefix_size_bytes wrapper_suffix_size_bytes python_head_size_bytes python_head_sha256 python_tail_size_bytes python_tail_sha256 python_common_size_bytes python_common_sha256 generated_operational_program_execution generated_full_subject_files_written'.split())
    ROLE_KEYS=set('kind full_codec_bytes full_codec_sha256 node_codec_bytes node_codec_sha256 excluded_encoder_bytes excluded_encoder_sha256 marker_occurrences role_is_exact_prefix encoder_excluded'.split())
    SOURCE_KEYS=set('kind driver initial node_codec finalizer executor input_data_size_bytes input_data_sha256 modeled_setup_form_count modeled_later_form_count controlled_synthetic_geometry_only independent_actual_acquisition_proven generated_operational_program_execution generated_full_subject_files_written behavior_conformance_complete physical_acceptance'.split())
    FAIL_KEYS=set('kind error_type message_size_bytes message_sha256 capture capture_metadata_unavailable capture_metadata_size_bytes capture_metadata_sha256 generated_operational_program_execution generated_full_subject_files_written physical_acceptance'.split())
    SAFE_KEYS=CAPTURE_KEYS|COMP_KEYS|PIPE_KEYS|INITIAL_KEYS|FINAL_KEYS|ROLE_KEYS|SOURCE_KEYS|FAIL_KEYS|{'size_bytes','sha256'}
    def sha_text(value):return type(value) is str and re.fullmatch('[0-9a-f]{64}',value) is not None
    def bounded(value):
     todo=[('',value)];nodes=0
     while todo:
      key,item=todo.pop();nodes+=1
      if nodes>4096:raise ValueError('d27_metadata_nodes')
      if type(item) is dict:
       if any(type(k) is not str or k not in SAFE_KEYS for k in item):raise ValueError('d27_metadata_key')
       todo.extend(item.items())
      elif type(item) is list:
       if len(item)>128:raise ValueError('d27_metadata_list')
       todo.extend((key,v) for v in item)
      elif type(item) is str:
       if key=='stderr_prefix_b64':
        if len(item)>21848 or re.fullmatch('[A-Za-z0-9+/]*={0,2}',item) is None:raise ValueError('d27_metadata_stderr')
        b=base64.b64decode(item,validate=True)
        if len(b)>16384 or base64.b64encode(b).decode('ascii')!=item:raise ValueError('d27_metadata_stderr')
       elif len(item)>256 or not item.isascii() or any(ord(c)<32 or ord(c)>126 for c in item):raise ValueError('d27_metadata_string')
       if key.endswith('sha256') and not sha_text(item):raise ValueError('d27_metadata_sha256')
      elif type(item) is float:
       if not math.isfinite(item):raise ValueError('d27_metadata_number')
      elif type(item) is int:
       if not -(2**64)<=item<=2**64:raise ValueError('d27_metadata_integer')
      elif item is not None and type(item) is not bool:raise ValueError('d27_metadata_type')
     return value
    def capture_metadata(value):
        if type(value) is not dict:raise ValueError('d27_capture_shape')
        compression='quality' in value
        allowed=COMP_KEYS if compression else CAPTURE_KEYS
        if not set(value)<=allowed:raise ValueError('d27_capture_keys')
        bounded(value)
        def want(ok):
            if not ok:raise ValueError('d27_capture_correspondence')
        def number(item):return type(item) in (int,float) and math.isfinite(item) and item>=0
        def integer(item,lo=0,hi=9007199254740991):return type(item) is int and lo<=item<=hi
        want(type(value.get('schema_version')) is int and value['schema_version']==1)
        bools=('data_only','spawned','timed_out','kill_requested','stdin_closed','stdin_complete',
               'stdin_extent_unknown','stdin_write_attempted','stdin_write_in_flight','reaped',
               'threads_joined','parent_observed_completion','finished_before_deadline',
               'child_completion_observed_before_deadline')
        for key in bools:
            if key in value:want(type(value[key]) is bool)
        want(value.get('data_only') is True and value.get('descendant_quiescence')=='UNKNOWN')
        for key in ('pid','returncode'):
            if key in value and value[key] is not None:
                want(integer(value[key],1,2147483647) if key=='pid' else integer(value[key],-2147483648,2147483647))
        for key in ('stdin_bytes','input_bytes','data_bytes','report_bytes','checks_count','measurements_count','packed_bytes','program_bytes'):
            if key in value and value[key] is not None:want(integer(value[key]))
        if 'threads_started' in value:want(integer(value['threads_started'],0,3))
        for key in ('program_sha256','input_sha256','data_sha256','report_sha256','packed_sha256'):
            if key in value and value[key] is not None:want(sha_text(value[key]))
        for key in ('started_monotonic','elapsed_seconds','caller_deadline','work_deadline','child_total_deadline','cleanup_deadline'):
            if key in value and value[key] is not None:want(number(value[key]))
        for key,expected in (('child_total_limit_seconds',30),('child_work_limit_seconds',27),('cleanup_limit_seconds',3),('final_reserve_seconds',5)):
            if key in value:want(type(value[key]) is int and value[key]==expected)
        if 'node_version' in value and value['node_version'] is not None:
            want(type(value['node_version']) is str and re.fullmatch('[0-9]{1,8}\\.[0-9]{1,8}\\.[0-9]{1,8}',value['node_version']) is not None)
        want(type(value.get('causes')) is list and len(value['causes'])<=128
             and all(type(v) is str and v.isascii() and 1<=len(v)<=128 and all(32<=ord(c)<=126 for c in v) for v in value['causes'])
             and len(set(value['causes']))==len(value['causes']))
        for key in ('environment_keys','command_options'):
            if key in value:want(type(value[key]) is list and len(value[key])<=16 and all(type(v) is str and v.isascii() and len(v)<=256 for v in value[key]))
        if 'node_executable' in value:want(type(value['node_executable']) is str and 0<len(value['node_executable'])<=256)
        if compression:
            want(type(value['quality']) is int and value['quality']==11 and type(value.get('roundtrip')) is bool)
        else:
            want(value.get('source_kind')=='d27_fixed_test_driver_v1')
            if value.get('case') is not None:want(value['case']=='geometry')
            if value.get('driver_role') is not None:want(value['driver_role']=='geometry')
            if value.get('driver_getter') is not None:want(value['driver_getter']=='d27_geometry_driver_v1')
            if value.get('case_completed') is not None:want(type(value['case_completed']) is bool)
            if value.get('case_cause') is not None:want(value['case_cause'] in ('d27_codec_absent','d27_driver_assertion','d27_driver_input','d27_driver_error','d27_node_version','d27_geometry_hold'))
            if value.get('program_bytes') is not None:want(0<value['program_bytes']<=24576)
        for name,cap in (('stdout',1048576),('stderr',16384)):
            channel=value.get(name);want(type(channel) is dict and set(channel)==PIPE_KEYS)
            for key in ('eof','overflow','closed','unknown_remainder'):want(type(channel[key]) is bool)
            want(integer(channel['observed_bytes']) and integer(channel['retained_bytes'],0,cap)
                 and channel['observed_bytes']>=channel['retained_bytes'] and sha_text(channel['prefix_sha256']))
            want(channel['io_error'] is None or type(channel['io_error']) is str and re.fullmatch('[A-Za-z_][A-Za-z0-9_]{0,127}',channel['io_error']) is not None)
            want(channel['unknown_remainder'] is (not channel['eof'] or channel['overflow'] or channel['io_error'] is not None))
        if value.get('parent_observed_completion') is True:
            want(integer(value.get('pid'),1) and integer(value.get('input_bytes'),1,262144)
                 and sha_text(value.get('input_sha256')) and sha_text(value.get('program_sha256')))
            want(set(value)==allowed and value.get('node_version')=='25.2.1'
                 and type(value.get('returncode')) is int and value['returncode']==0 and value['causes']==[])
            for key in ('spawned','reaped','threads_joined','stdin_complete','stdin_closed','stdin_write_attempted',
                        'finished_before_deadline','child_completion_observed_before_deadline'):want(value[key] is True)
            for key in ('timed_out','kill_requested','stdin_extent_unknown','stdin_write_in_flight'):want(value[key] is False)
            want(value['threads_started']==3 and value['command_options']==['--max-old-space-size=256','--input-type=commonjs','-e'])
            want(value['environment_keys'] in (['PATH'],['PATH','SystemRoot']))
            for key in ('started_monotonic','elapsed_seconds','caller_deadline','work_deadline','child_total_deadline','cleanup_deadline'):want(number(value[key]))
            start=value['started_monotonic'];end=value['caller_deadline'];work=min(start+27,end-8);total=min(start+30,end-5);observed=start+value['elapsed_seconds']
            want(value['work_deadline']==work and value['child_total_deadline']==total
                 and value['cleanup_deadline']<=min(total,work+3)
                 and observed<end and observed<total and observed<value['cleanup_deadline'])
            want(value['stdin_bytes']==value['input_bytes'])
            for channel in (value['stdout'],value['stderr']):
                want(channel['eof'] is True and channel['closed'] is True and channel['overflow'] is False
                     and channel['io_error'] is None and channel['unknown_remainder'] is False
                     and channel['observed_bytes']==channel['retained_bytes'])
            want(value['stderr']['retained_bytes']==0 and value['stderr']['prefix_sha256']=='e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855')
            if compression:
                want(value['roundtrip'] is True and value['stderr_prefix_b64']==''
                     and integer(value.get('packed_bytes'),1,32768) and sha_text(value.get('packed_sha256')))
            else:
                want(type(value['case_completed']) is bool and value['case']=='geometry' and value['node_version']=='25.2.1'
                     and integer(value.get('program_bytes'),1,24576) and integer(value.get('data_bytes'),0,262144)
                     and sha_text(value.get('data_sha256')) and integer(value.get('report_bytes'),1,32768)
                     and sha_text(value.get('report_sha256')) and integer(value.get('checks_count'),0,512)
                     and integer(value.get('measurements_count'),0,128))
        return value
    return capture_metadata(value)


def d27_error_facts_v1(error):
    """Hash bounded exact-string messages and validated plain capture DATA."""
    import time
    main=_d27_main_module_v1()
    phase_error=vars(main).get('D27PhaseConstructionError')
    if type(phase_error) is not type or type.__getattribute__(phase_error,'__module__')!=main.__name__:
        raise RuntimeError('d27_owned_phase_error_binding')
    owned=(D27CaseError,D27CompressionError,D27ConstructionError,phase_error)
    kind=type.__getattribute__(type(error),'__name__')
    if re.fullmatch('[A-Za-z_][A-Za-z0-9_]{0,95}',kind) is None:kind='Exception'
    capture={'capture':None,'capture_metadata_unavailable':True,
             'capture_metadata_size_bytes':None,'capture_metadata_sha256':None}
    value=object.__getattribute__(error,'__dict__').get('metadata') if type(error) in owned else None
    try:
        if value is not None:d27_capture_metadata_v1(value)
        encoder=json.JSONEncoder(sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False)
        digest=hashlib.sha256();extent=0;parts=[];retain=True
        for index,part in enumerate(encoder.iterencode(value)):
            if index>=32768:raise ValueError('d27_capture_encoding_steps')
            if index%32==0 and len(sys.argv)==4 and sys.argv[3]=='--d27-sole-inert-geometry-child':
                now=time.monotonic()
                if not math.isfinite(now) or now>=float(sys.argv[2]):raise ValueError('d27_capture_encoding_deadline')
            raw=part.encode('ascii');extent+=len(raw)
            if extent>8388608:raise ValueError('d27_capture_encoding_bound')
            digest.update(raw)
            if extent<=30000 and retain:parts.append(raw)
            else:retain=False;parts=[]
        capture.update(capture_metadata_size_bytes=extent,capture_metadata_sha256=digest.hexdigest())
        if value is not None and retain:
            capture.update(capture=json.loads(b''.join(parts)),capture_metadata_unavailable=False)
    except (ValueError,TypeError,KeyError,AssertionError,OverflowError,RecursionError,UnicodeError):
        pass
    result={'error_type':kind,'message_size_bytes':None,'message_sha256':None,'exception_capture':capture}
    try:
        if type(error) not in owned+(RuntimeError,ValueError,AssertionError,TypeError,OverflowError,TimeoutError):
            raise ValueError('unowned_error_message')
        args=BaseException.args.__get__(error)
        if type(args) is not tuple or len(args)!=1 or type(args[0]) is not str or len(args[0])>4096:
            raise ValueError('unavailable_error_message')
        raw=args[0].encode('utf-8')
        result.update(message_size_bytes=len(raw),message_sha256=hashlib.sha256(raw).hexdigest())
    except (ValueError,TypeError,UnicodeError):result['message_unavailable']=True
    return result


def d27_recover_canonical_report_v1(stdout,admitted):
    """Recover one complete canonical report from its actual tagged capture join."""
    if type(stdout) is not bytes or len(stdout)>1048576:raise ValueError('d27_report_original_bound')
    found=[]
    def pairs(rows):
        value={}
        for key,item in rows:
            if key in value:raise ValueError('d27_report_duplicate')
            value[key]=item
        return value
    for line in stdout.splitlines(keepends=True):
        if not line.startswith(b'D27_CASE_METADATA ') or not line.endswith(b'\n') or len(line)>32768:continue
        try:
            value=json.loads(line[18:-1],object_pairs_hook=pairs,
                parse_constant=lambda unused: (_ for _ in ()).throw(ValueError('d27_report_nonfinite')))
            if type(value) is not dict or set(value)!={'case','report','capture'} or value['case']!='geometry':raise ValueError()
            if b'D27_CASE_METADATA '+canonical(value)+b'\n'!=line:raise ValueError()
            report=value['report'];capture=value['capture']
            d27_capture_metadata_v1(capture)
            if (type(report) is not dict or set(report)!={'schema_version','case','node_version','completed','cause','checks','measurements'}
                    or type(report['schema_version']) is not int or report['schema_version']!=1
                    or report['case']!='geometry' or report['node_version']!='25.2.1' or type(report['completed']) is not bool
                    or report['cause'] not in (None,*_D27_DRIVER_CAUSES,'d27_geometry_hold')
                    or type(report['checks']) is not list or len(report['checks'])>512
                    or type(report['measurements']) is not list or len(report['measurements'])>128):raise ValueError()
            seen=set()
            for row in report['checks']:
                if (type(row) is not dict or set(row)!={'id','ok'} or type(row['id']) is not str
                        or re.fullmatch('[A-Za-z0-9_]{1,64}',row['id']) is None
                        or row['id'] in seen or type(row['ok']) is not bool):raise ValueError()
                seen.add(row['id'])
            seen=set()
            for row in report['measurements']:
                if (type(row) is not dict or set(row)!={'id','size_bytes','sha256'} or type(row['id']) is not str
                        or re.fullmatch('[A-Za-z0-9_]{1,64}',row['id']) is None or row['id'] in seen
                        or type(row['size_bytes']) is not int or not 0<=row['size_bytes']<=262144
                        or type(row['sha256']) is not str or re.fullmatch('[0-9a-f]{64}',row['sha256']) is None):raise ValueError()
                seen.add(row['id'])
            raw=canonical(report)+b'\n';digest=hashlib.sha256(raw).hexdigest()
            if (len(raw)>32768 or type(capture) is not dict or capture.get('case')!='geometry'
                    or capture.get('source_kind')!='d27_fixed_test_driver_v1' or capture.get('driver_role')!='geometry'
                    or capture.get('driver_getter')!='d27_geometry_driver_v1'
                    or type(capture.get('program_bytes')) is not int or capture['program_bytes']!=admitted['driver']['size_bytes']
                    or capture.get('program_sha256')!=admitted['driver']['sha256']
                    or type(capture.get('report_bytes')) is not int or capture['report_bytes']!=len(raw)
                    or capture.get('report_sha256')!=digest or capture.get('case_completed') is not report['completed']
                    or capture.get('case_cause')!=report['cause']
                    or type(capture.get('checks_count')) is not int or capture['checks_count']!=len(report['checks'])
                    or type(capture.get('measurements_count')) is not int or capture['measurements_count']!=len(report['measurements'])
                    or type(capture.get('stdout')) is not dict or type(capture['stdout'].get('retained_bytes')) is not int
                    or capture['stdout']['retained_bytes']!=len(raw) or capture['stdout'].get('prefix_sha256')!=digest):raise ValueError()
            found.append(raw)
        except (ValueError,TypeError,KeyError,UnicodeError,RecursionError,OverflowError):continue
    return found[0] if len(found)==1 else None


D27_GEOMETRY_TEST_ENTRY = 'import sys,hashlib,json,re\nsys.stdout.reconfigure(encoding=\'utf-8\')\ndef _d27_entry():\n import sys\n sys.stdout.reconfigure(encoding=\'utf-8\')\n import hashlib,json,os,pathlib,stat,types,unittest,re,math\n if not (sys.flags.isolated and sys.flags.no_site and sys.flags.dont_write_bytecode and sys.flags.optimize==0):raise RuntimeError(\'d27_entry_python_flags\')\n if sys.version_info[:3]!=(3,14,7):raise RuntimeError(\'d27_entry_python_version\')\n root=pathlib.Path(\'C:/Users/s-a-balashov/.codex/worktrees/fix-accepted-policy-preprocessing/VAST\')\n assert len(sys.argv)==2 or len(sys.argv)==4 and sys.argv[3]==\'--d27-sole-inert-geometry-child\'\n assert pathlib.Path.cwd().resolve()==root.resolve(strict=True)\n assert len(sys.argv[1])<=1024\n def pairs(rows):\n  value={}\n  for key,item in rows:\n   assert key not in value;value[key]=item\n  return value\n expected=json.loads(sys.argv[1],object_pairs_hook=pairs);assert type(expected) is dict and set(expected)=={\'main\',\'caller\'}\n if len(sys.argv)==4:\n  assert len(sys.argv[2])<=32 and math.isfinite(float(sys.argv[2])) and repr(float(sys.argv[2]))==sys.argv[2]\n fixed=((\'main\',\'tests.test_accepted_policy_fixture_compiler_gate2_dictionary_v1\',\'test_accepted_policy_fixture_compiler_gate2_dictionary_v1.py\'),(\'caller\',\'tests.test_accepted_policy_fixture_compiler_gate2_dictionary_caller_v1\',\'test_accepted_policy_fixture_compiler_gate2_dictionary_caller_v1.py\'))\n def epoch(s,cross=False):return(s.st_dev,s.st_ino,s.st_mode,s.st_nlink,s.st_size,s.st_mtime_ns,getattr(s,"st_birthtime_ns",None),None if cross and os.name=="nt" else s.st_ctime_ns)\n held=[]\n for role,name,filename in fixed:\n  path=root/\'tests\'/filename;pin=expected[role];assert type(pin) is list and len(pin)==2 and type(pin[0]) is int and 0<pin[0]<=524288 and type(pin[1]) is str and re.fullmatch(\'[0-9a-f]{64}\',pin[1]) is not None\n  before=path.lstat();assert path.resolve(strict=True)==path and stat.S_ISREG(before.st_mode) and before.st_nlink==1 and before.st_size==pin[0]\n  fd=os.open(path,os.O_RDONLY|getattr(os,\'O_BINARY\',0))\n  try:\n   opened=os.fstat(fd);assert epoch(opened,True)==epoch(before,True)\n   raw=b\'\'\n   while len(raw)<pin[0]:\n    part=os.read(fd,min(65536,pin[0]-len(raw)));assert part;raw+=part\n   assert os.read(fd,1)==b\'\' and epoch(os.fstat(fd))==epoch(opened) and epoch(path.lstat())==epoch(before)\n  finally:os.close(fd)\n  assert len(raw)==pin[0] and hashlib.sha256(raw).hexdigest()==pin[1];held.append((name,path,raw))\n # Both immutable buffers have been authenticated and held before either compile.\n modules=[]\n for name,path,raw in held:\n  module=types.ModuleType(name);module.__file__=str(path);module.__package__=\'tests\';sys.modules[name]=module;sys.modules[name.rsplit(\'.\',1)[-1]]=module;modules.append(module)\n for module,(_,path,raw) in zip(modules,held):exec(compile(raw,str(path),\'exec\'),vars(module))\n for module,(name,path,raw) in zip(modules,held):\n  assert sys.modules[name] is module and sys.modules[name.rsplit(\'.\',1)[-1]] is module and vars(module)[\'__name__\']==name\n for module,(_,path,_),getter_name in zip(modules,held,(\'d27_geometry_driver_v1\',\'_d27_geometry_program_v1\')):\n  getter=vars(module).get(getter_name)\n  assert type(getter) is types.FunctionType and getter.__name__==getter_name and getter.__module__==module.__name__ and getter.__globals__ is vars(module) and pathlib.Path(getter.__code__.co_filename)==path\n return modules[1].d27_geometry_child_v1(expected) if len(sys.argv)==4 else modules[1].d27_geometry_root_v1(expected)\n\ntry:status=_d27_entry()\nexcept BaseException as error:\n status=1\n try:\n  kind=type.__getattribute__(type(error),\'__name__\')\n  if type(kind) is not str or re.fullmatch(\'[A-Za-z_][A-Za-z0-9_]{0,95}\',kind) is None:kind=\'Exception\'\n  facts={\'event\':\'entry_failure\',\'error_type\':kind,\'message_size_bytes\':None,\'message_sha256\':None,\'message_unavailable\':True,\'secondary\':[]}\n  try:\n   args=BaseException.args.__get__(error)\n   if type(error) in (RuntimeError,ValueError,AssertionError,TypeError,OverflowError,TimeoutError) and type(args) is tuple and len(args)==1 and type(args[0]) is str and len(args[0])<=4096:\n    raw=args[0].encode(\'utf-8\');facts.update(message_size_bytes=len(raw),message_sha256=hashlib.sha256(raw).hexdigest());del facts[\'message_unavailable\']\n  except BaseException:pass\n  encoded=json.dumps(facts,sort_keys=True,separators=(\',\',\':\'),ensure_ascii=True,allow_nan=False).encode(\'ascii\')+b\'\\n\'\n  if len(encoded)>32768:raise RuntimeError(\'d27_entry_failure_record_bound\')\n  sys.stdout.buffer.write(encoded);sys.stdout.buffer.flush();status=1\n except BaseException:pass\nraise SystemExit(status) from None\n'


def d27_geometry_parent_v1(pins):
    """Capture the single admitted fixed child; return sealed metadata originals in RAM."""
    import subprocess,threading,time,copy
    started=time.monotonic()
    if not math.isfinite(started) or started<0:raise RuntimeError('d27_parent_clock')
    total_end=started+30;work_end=total_end-3;cleanup_end=total_end
    main=_d27_main_module_v1(True);_,role=d27_node_codec_v1(vars(main).get('D27_WIRE_CODEC'))
    program=main.d27_geometry_driver_v1()
    if type(program) is not str or not program.isascii() or not 0<len(program)<=24576:
        raise RuntimeError('d27_parent_driver')
    driver={'source_kind':'d27_fixed_test_driver_v1','driver_role':'geometry','driver_getter':'d27_geometry_driver_v1',
            'program_bytes':len(program),'program_sha256':hashlib.sha256(program.encode('ascii')).hexdigest()}
    admitted={r:{'size_bytes':pins[r][0],'sha256':pins[r][1]} for r in ('main','caller')}
    admitted.update(driver={'size_bytes':driver['program_bytes'],'sha256':driver['program_sha256']},
        codec={r:{'size_bytes':n,'sha256':h} for r,n,h in (
            ('full',role['full_codec_bytes'],role['full_codec_sha256']),
            ('decoder',role['node_codec_bytes'],role['node_codec_sha256']),
            ('tail',role['excluded_encoder_bytes'],role['excluded_encoder_sha256']))})
    command=[sys.executable,'-I','-S','-B','-c',D27_GEOMETRY_TEST_ENTRY,
             json.dumps(pins,separators=(',',':')),repr(work_end),'--d27-sole-inert-geometry-child']
    command_chars=len(subprocess.list2cmdline(command))
    if command_chars>32767:raise RuntimeError('d27_parent_command_bound')
    root=Path('C:/Users/s-a-balashov/.codex/worktrees/fix-accepted-policy-preprocessing/VAST')
    caps={'stdout':1048576,'stderr':16384};buffers={k:bytearray() for k in caps}
    states={k:{'eof':False,'overflow':False,'error':None,'secondary':[],'closed':False,
               'close_attempted':False,'observed_bytes':0} for k in caps}
    lock=threading.Lock();causes=[];workers=[];proc=None;forced=False;timed_out=False
    joined=False;returncode=None;observed=None;last=started
    def cause(name):
        with lock:
            if name not in causes:causes.append(name)
    def clock():
        nonlocal last
        now=time.monotonic()
        if not math.isfinite(now) or now<last:
            cause('parent_clock');raise RuntimeError('d27_parent_clock')
        last=now;return now
    def read_channel(name,stream):
        state=states[name]
        try:
            while True:
                part=stream.read(65536)
                if type(part) is not bytes:raise TypeError('d27_parent_pipe_type')
                with lock:
                    if not part:state['eof']=True;break
                    state['observed_bytes']+=len(part)
                    room=caps[name]-len(buffers[name]);buffers[name].extend(part[:room])
                    if len(part)>room:state['overflow']=True
                    overflow=state['overflow']
                if overflow:cause(name+'_overflow');break
        except BaseException as error:
            with lock:state['error']=type(error).__name__[:128]
            cause(name+'_read')
        finally:
            with lock:state['close_attempted']=True
            try:
                stream.close()
                with lock:state['closed']=True
            except BaseException as error:
                with lock:state['secondary'].append(type(error).__name__[:128])
                cause(name+'_close')
    try:
        if clock()>=work_end:raise RuntimeError('d27_parent_prespan_deadline')
        proc=subprocess.Popen(command,cwd=root,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                              bufsize=0,close_fds=True)
        for name in ('stdout','stderr'):
            worker=threading.Thread(target=read_channel,args=(name,getattr(proc,name)),daemon=True)
            worker.start();workers.append(worker)
        while True:
            now=clock();status=proc.poll()
            if status is not None:
                returncode=status;observed=now;break
            with lock:bad=bool(causes)
            if bad or now>=work_end:
                if now>=work_end:timed_out=True;cause('parent_work_deadline')
                forced=True
                try:proc.kill()
                except BaseException as error:cause('child_kill_'+type(error).__name__[:64])
                break
            time.sleep(min(.01,max(0,work_end-now)))
    except BaseException as error:
        cause('parent_'+type(error).__name__[:64])
        if proc is not None:
            forced=True
            try:proc.kill()
            except BaseException as secondary:cause('child_kill_'+type(secondary).__name__[:64])
    finally:
        try:cleanup_end=min(total_end,clock()+3)
        except BaseException:cleanup_end=total_end
        if proc is not None:
            try:
                wait=max(0,cleanup_end-clock())
                status=proc.wait(timeout=wait)
                if returncode is None:returncode=status;observed=clock()
            except BaseException as error:cause('child_wait_'+type(error).__name__[:64])
        for worker in workers:
            try:worker.join(max(0,cleanup_end-clock()))
            except BaseException as error:cause('thread_join_'+type(error).__name__[:64])
        joined=len(workers)==2 and all(not worker.is_alive() for worker in workers)
        if not joined:cause('threads_unjoined')
    with lock:
        raw={k:bytes(v) for k,v in buffers.items()};channels=copy.deepcopy(states);ordered=list(causes)
    for name,row in channels.items():
        row.update(size_bytes=len(raw[name]),sha256=hashlib.sha256(raw[name]).hexdigest(),
                   remainder_unknown=not row['eof'] or row['overflow'] or row['error'] is not None or not joined,
                   closure_unknown=not row['closed'])
    source=case=summary=None;full=passed=collected=False;protocol_error=None
    try:
        source,case,summary,full,passed,collected=d27_original_protocol_v1(raw['stdout'],raw['stderr'],None,admitted)
        for helper in ([source['initial']['compression']] if source and source['kind']=='d27_inert_source_construction_metadata_v1' else [])+([case['capture']] if case else []):
            if helper.get('parent_observed_completion') is True and helper['caller_deadline']!=work_end:
                raise AssertionError('d27_parent_helper_clock')
        if summary is None:protocol_error='d27_protocol_incomplete'
        elif type(returncode) is not int or returncode!=(0 if summary['successful'] else 1):
            protocol_error='d27_protocol_contradiction'
    except (AssertionError,ValueError,TypeError,KeyError,RecursionError,OverflowError):
        protocol_error='d27_protocol_contradiction'
    normal=(type(returncode) is int and returncode in (0,1) and not forced and not timed_out and joined
            and not ordered and observed is not None and observed<total_end and observed<cleanup_end
            and protocol_error is None and all(not row['remainder_unknown'] for row in channels.values()))
    parent={'kind':'d27_local_inert_geometry_test_parent_observation_v1',
        'source_pins':[{'path':path,**admitted[r]} for path,r in (
            ('tests/test_accepted_policy_fixture_compiler_gate2_dictionary_v1.py','main'),
            ('tests/test_accepted_policy_fixture_compiler_gate2_dictionary_caller_v1.py','caller'))],
        'suite_mode':'geometry','selected_class':'D27CompleteGeometryTests',
        'source_binding_policy':'both_held_test_buffers_before_either_compile',
        'source_binding_record_validated':protocol_error is None,'held_driver_loader_binding_validated':protocol_error is None,
        'fixed_driver_binding':driver,'codec_role_binding':role,'python':'.'.join(map(str,sys.version_info[:3])),
        'deadline_seconds':300,'elapsed_before_report_write_s':time.monotonic()-started,'returncode':returncode,
        'forced_test_child':forced,'timed_out':timed_out,'channels':channels,'threads_joined':joined,
        'io_failure':bool(ordered),'ordered_causes':ordered,'test_child_command_chars':command_chars,
        'child_work_seconds':27,'child_total_seconds':30,'work_deadline':work_end,'cleanup_deadline':cleanup_end,
        'child_total_deadline':total_end,'child_completion_observed_at':observed,
        'child_completion_before_total_end':observed is not None and observed<total_end,
        'child_completion_before_cleanup_end':observed is not None and observed<cleanup_end,
        'protocol_error_type':protocol_error,'parent_observed_test_transport_complete':normal,
        'test_summary':summary,'geometry_source_kind':source['kind'] if source is not None else None,
        'geometry_fully_measured':normal and full,'geometry_risk_passed':normal and passed and bool(summary and summary['successful']),
        'source_execution_reopens_paths':False,'generated_operational_program_execution':False,
        'descendant_quiescence':'UNKNOWN','self_report_persistence_or_whole_process_attested':False}
    parent_raw=canonical(parent)+b'\n'
    if len(parent_raw)>32768:raise RuntimeError('d27_parent_report_bound')
    report=d27_recover_canonical_report_v1(raw['stdout'],admitted)
    return {'stdout':raw['stdout'],'stderr':raw['stderr'],'parent':parent_raw,'canonical_report':report},parent


def d27_geometry_root_v1(pins):
    """Seal only actual post-attempt metadata; never create a pre-attempt outcome."""
    import stat
    def error_type(error):
        kind=type.__getattribute__(type(error),'__name__')
        return kind if type(kind) is str and re.fullmatch('[A-Za-z_][A-Za-z0-9_]{0,95}',kind) else 'Exception'
    def identity(row):
        return row.st_dev,row.st_ino,row.st_mode,row.st_nlink,row.st_size,row.st_mtime_ns
    base=Path('C:/Users/s-a-balashov/AppData/Local/Temp')
    targets={name:base/('vast-d27-sole-inert-geometry-v1.'+name+'.original.txt')
             for name in ('stdout','stderr','parent','canonical_report')}
    if any(os.path.lexists(path) for path in targets.values()):
        raise RuntimeError('d27_actual_metadata_target_already_exists')
    fixture=Path('C:/Users/s-a-balashov/.codex/worktrees/fix-accepted-policy-preprocessing/VAST/tests/fixtures/gate2/d27-geometry-retained-v1.json')
    if os.path.lexists(fixture):raise RuntimeError('d27_outcome_already_exists')
    originals,parent=d27_geometry_parent_v1(pins)
    descriptors={};retention_complete=True
    for name in ('stdout','stderr','parent','canonical_report'):
        raw=originals[name]
        if raw is None:descriptors[name]={'available':False,'unavailable_reason':'CAPTURE_INCOMPLETE'};continue
        cap={'stdout':1048576,'stderr':16384,'parent':32768,'canonical_report':32768}[name]
        if type(raw) is not bytes or len(raw)>cap:
            descriptors[name]={'available':False,'unavailable_reason':'RETENTION_FAILED'}
            retention_complete=False;continue
        target=targets[name]
        facts={'open_completed':False,'written_bytes':0,'write_extent_unknown':False,
               'flush_completed':False,'fsync_completed':False,'close_completed':False,'failure_types':[],
               'readback_completed':False,'readback_close_completed':False,
               'readback_size_bytes':None,'readback_sha256':None}
        handle=None;owned_identity=None
        try:
            handle=target.open('xb',buffering=0);facts['open_completed']=True
            owned_identity=identity(os.fstat(handle.fileno()))[:4]
            while facts['written_bytes']<len(raw):
                facts['write_extent_unknown']=True
                count=handle.write(raw[facts['written_bytes']:])
                if type(count) is not int or not 0<count<=len(raw)-facts['written_bytes']:
                    raise RuntimeError('d27_metadata_write')
                facts['written_bytes']+=count;facts['write_extent_unknown']=False
            handle.flush();facts['flush_completed']=True
            os.fsync(handle.fileno());facts['fsync_completed']=True
        except BaseException as error:
            facts['failure_types'].append(error_type(error))
        finally:
            if handle is not None:
                try:handle.close();facts['close_completed']=True
                except BaseException as error:facts['failure_types'].append(error_type(error))
        fd=None
        try:
            if not facts['open_completed'] or owned_identity is None:
                raise RuntimeError('d27_metadata_not_created')
            before=target.lstat()
            if (not stat.S_ISREG(before.st_mode) or before.st_nlink!=1 or not 0<=before.st_size<=cap
                    or identity(before)[:4]!=owned_identity):
                raise RuntimeError('d27_metadata_readback_kind')
            fd=os.open(target,os.O_RDONLY|getattr(os,'O_BINARY',0)|getattr(os,'O_NOFOLLOW',0))
            opened=os.fstat(fd)
            if identity(opened)!=identity(before):raise RuntimeError('d27_metadata_readback_open_drift')
            digest=hashlib.sha256();extent=0
            while True:
                chunk=os.read(fd,min(65536,cap+1-extent))
                if not chunk:break
                extent+=len(chunk)
                if extent>cap:raise RuntimeError('d27_metadata_readback_bound')
                digest.update(chunk)
            if (extent!=opened.st_size or identity(os.fstat(fd))!=identity(opened)
                    or identity(target.lstat())!=identity(before)):
                raise RuntimeError('d27_metadata_readback_drift')
            facts.update(readback_completed=True,readback_size_bytes=extent,readback_sha256=digest.hexdigest())
        except BaseException as error:facts['failure_types'].append(error_type(error))
        finally:
            if fd is not None:
                try:os.close(fd);facts['readback_close_completed']=True
                except BaseException as error:facts['failure_types'].append(error_type(error))
        actual_full=(facts['readback_completed'] is True and facts['readback_size_bytes']==len(raw)
                     and facts['readback_sha256']==hashlib.sha256(raw).hexdigest())
        complete=(all(facts[k] is True for k in ('open_completed','flush_completed','fsync_completed','close_completed'))
                  and facts['written_bytes']==len(raw) and facts['write_extent_unknown'] is False
                  and actual_full and facts['readback_close_completed'] is True and not facts['failure_types'])
        retention_complete=retention_complete and complete
        # Every later original is still attempted; existing partial files survive.
        descriptors[name]={'available':facts['readback_completed'],'path':str(target),
                           'size_bytes':facts['readback_size_bytes'],'sha256':facts['readback_sha256'],
                           'expected_size_bytes':len(raw),'expected_sha256':hashlib.sha256(raw).hexdigest(),
                           'retention':facts}
    result=canonical({'kind':'d27_actual_geometry_metadata_retention_v1','originals':descriptors,
        'geometry_risk_passed':parent['geometry_risk_passed'],'retention_complete':retention_complete,'descendant_quiescence':'UNKNOWN',
        'physical_persistence_attested':False})+b'\n'
    if len(result)>32768:raise RuntimeError('d27_root_metadata_record_bound')
    sys.stdout.buffer.write(result);sys.stdout.buffer.flush()
    return 0 if parent['geometry_risk_passed'] and retention_complete else 1


def d27_geometry_child_v1(pins):
    """The fixed admitted child: one held class, metadata-only bounded protocol."""
    import time
    if len(sys.argv)!=4 or sys.argv[3]!='--d27-sole-inert-geometry-child':
        raise RuntimeError('d27_geometry_child_entry')
    end=float(sys.argv[2]);last=None;written=0;prefix=[]
    def gate():
        nonlocal last
        now=time.monotonic()
        if not math.isfinite(now) or not math.isfinite(end) or now>=end or last is not None and now<last:
            raise RuntimeError('d27_geometry_child_deadline')
        last=now
    gate()
    main=_d27_main_module_v1(True)
    node_codec,role=d27_node_codec_v1(vars(main).get('D27_WIRE_CODEC'))
    program=main.d27_geometry_driver_v1()
    if type(program) is not str or not program.isascii() or not 0<len(program)<=24576:
        raise RuntimeError('d27_geometry_child_driver')
    driver={'source_kind':'d27_fixed_test_driver_v1','driver_role':'geometry',
            'driver_getter':'d27_geometry_driver_v1','program_bytes':len(program),
            'program_sha256':hashlib.sha256(program.encode('ascii')).hexdigest()}
    admitted={r:{'size_bytes':pins[r][0],'sha256':pins[r][1]} for r in ('main','caller')}
    admitted.update(driver={'size_bytes':driver['program_bytes'],'sha256':driver['program_sha256']},
                    codec={r:{'size_bytes':n,'sha256':h} for r,n,h in (
                        ('full',role['full_codec_bytes'],role['full_codec_sha256']),
                        ('decoder',role['node_codec_bytes'],role['node_codec_sha256']),
                        ('tail',role['excluded_encoder_bytes'],role['excluded_encoder_sha256']))})
    test_id='tests.test_accepted_policy_fixture_compiler_gate2_dictionary_caller_v1.D27CompleteGeometryTests.test_complete_form_bounds_preserve_hold'
    original_stdout,original_stderr=sys.stdout,sys.stderr
    def emit_raw(raw):
        nonlocal written
        gate()
        if type(raw) is not bytes or not raw.endswith(b'\n') or len(raw)>32768 or written+len(raw)>1048576:
            raise RuntimeError('d27_geometry_child_output_bound')
        # The finite parser checks every known record before it is forwarded.
        d27_original_protocol_v1(b''.join(prefix)+raw,b'',None,admitted)
        offset=0
        while offset<len(raw):
            gate();count=os.write(original_stdout.fileno(),raw[offset:])
            if type(count) is not int or not 0<count<=len(raw)-offset:
                raise RuntimeError('d27_geometry_child_write')
            offset+=count
        written+=len(raw);prefix.append(raw);gate()
    def emit(value):emit_raw(canonical(value)+b'\n')
    emit({'event':'source_bindings','sources':[{'path':path,**admitted[r]} for path,r in (
        ('tests/test_accepted_policy_fixture_compiler_gate2_dictionary_v1.py','main'),
        ('tests/test_accepted_policy_fixture_compiler_gate2_dictionary_caller_v1.py','caller'))],
        'both_buffers_verified_before_either_compile':True,'held_driver_loader_bound':True,
        'held_driver_module':'tests.test_accepted_policy_fixture_compiler_gate2_dictionary_v1',
        'execution_reopens_test_paths':False,'held_driver_aliases_bound':True,'held_caller_aliases_bound':True,
        'codec_role':role,'fixed_driver':driver})

    class Stream(io.TextIOBase):
        def __init__(self,allow):
            self.allow=allow;self.pending='';self.discard=False;self.bad=False
            self.count=self.forwarded=self.source_records=self.case_records=0
            self.source_kind=None;self.digest=hashlib.sha256()
        @property
        def encoding(self):return 'utf-8'
        def writable(self):return True
        def flush(self):pass
        def _line(self,line):
            source_tag='D27_GEOMETRY_SOURCE_METADATA ';case_tag='D27_CASE_METADATA '
            try:
                if not self.allow:raise ValueError('d27_stream_unexpected')
                if line.startswith(source_tag):
                    tag=source_tag
                    if self.source_records or self.case_records:raise ValueError('d27_stream_source_order')
                elif line.startswith(case_tag):
                    tag=case_tag
                    if self.source_records!=1 or self.case_records or self.source_kind!='d27_inert_source_construction_metadata_v1':
                        raise ValueError('d27_stream_case_order')
                else:raise ValueError('d27_stream_unexpected')
                payload=line[len(tag):].encode('ascii')
                def pairs(rows):
                    result={}
                    for key,item in rows:
                        if key in result:raise ValueError('d27_stream_duplicate')
                        result[key]=item
                    return result
                value=json.loads(payload,object_pairs_hook=pairs,
                    parse_constant=lambda unused: (_ for _ in ()).throw(ValueError('d27_stream_nonfinite')))
                raw=(line+'\n').encode('ascii')
                if canonical(value)!=payload or len(raw)>32768:raise ValueError('d27_stream_canonical')
                d27_original_protocol_v1(b''.join(prefix)+raw,b'',None,admitted)
            except (ValueError,TypeError,KeyError,AssertionError,UnicodeError):
                self.bad=True;return
            # Deadline/write failures propagate; no operational text is emitted.
            emit_raw(raw);self.forwarded+=1
            if tag==source_tag:self.source_records+=1;self.source_kind=value['kind']
            else:self.case_records+=1
        def write(self,text):
            if type(text) is not str:self.bad=True;raise TypeError('d27_stream_type')
            gate()
            for index,char in enumerate(text):
                if index%256==0:gate()
                raw=char.encode('utf-8','backslashreplace')
                if self.count+len(raw)>1048576:self.bad=True;raise ValueError('d27_stream_bound')
                self.count+=len(raw);self.digest.update(raw)
                if char=='\n':
                    if self.discard or not self.pending:self.bad=True
                    else:self._line(self.pending)
                    self.pending='';self.discard=False
                elif not self.discard:
                    if not self.allow or not 32<=ord(char)<=126 or len(self.pending)>=32767:
                        self.bad=True;self.pending='';self.discard=True
                    else:self.pending+=char
            gate();return len(text)
        def facts(self):
            return {'observed_bytes':self.count,'sha256':self.digest.hexdigest(),'metadata_records':self.forwarded,
                'geometry_source_records':self.source_records,'geometry_case_records':self.case_records,
                'unexpected_or_unterminated':self.bad or bool(self.pending) or self.discard,'raw_values_retained':False}

    selected=D27CompleteGeometryTests('test_complete_form_bounds_preserve_hold')
    class Result(unittest.TestResult):
        def __init__(self):
            super().__init__();self.started=self.finished=False;self.outcome=None
            self.successes=self.callbacks=self.issue_total=0
            self.counts={'subtest_issue':0,'parent_issue':0};self.parent_outcomes={}
        def active(self,test):
            gate()
            if test is not selected or not self.started or self.finished:raise ValueError('d27_result_lifecycle')
        def startTest(self,test):
            if test is not selected or self.started:raise ValueError('d27_result_start')
            gate();super().startTest(test);self.started=True
            emit({'event':'test_started','test_id':test_id})
        def simple(self,test,outcome):
            self.active(test)
            if self.outcome is not None:raise ValueError('d27_result_callback_contradiction')
            self.outcome={'outcome':outcome}
        def addSuccess(self,test):self.simple(test,'success');self.successes+=1
        def addSkip(self,test,reason):self.simple(test,'skip');self.skipped.append((test,None))
        def addUnexpectedSuccess(self,test):self.simple(test,'unexpected_success');self.unexpectedSuccesses.append(test)
        def issue(self,test,err,outcome,sink,event='parent_issue',ordinal=None):
            self.active(test)
            if self.outcome and self.outcome['outcome'] not in ('failure','error','expected_failure'):
                raise ValueError('d27_result_callback_contradiction')
            if type(err) is not tuple or len(err)!=3 or not isinstance(err[1],BaseException) or type(err[1]) is not err[0]:
                raise ValueError('d27_result_exception_shape')
            if self.issue_total>=512:raise ValueError('d27_result_issue_bound')
            facts=d27_error_facts_v1(err[1]);sink.append((test,facts));self.issue_total+=1;self.counts[event]+=1
            old=self.outcome
            if old is None or old['outcome'] not in ('failure','error') or old['outcome']=='failure' and outcome=='error':
                self.outcome={'outcome':outcome,**facts}
            emit({'event':event,'test_id':test_id,'issue_index':self.issue_total,'subtest_ordinal':ordinal,
                  'outcome':outcome,**facts})
        def addFailure(self,test,err):self.issue(test,err,'failure',self.failures)
        def addError(self,test,err):self.issue(test,err,'error',self.errors)
        def addExpectedFailure(self,test,err):self.issue(test,err,'expected_failure',self.expectedFailures)
        def addSubTest(self,test,subtest,err):
            self.active(test)
            if self.callbacks>=512:raise ValueError('d27_result_subtest_bound')
            self.callbacks+=1
            if err is not None:
                if type(err) is not tuple or len(err)!=3:raise ValueError('d27_result_exception_shape')
                failure=isinstance(err[1],AssertionError)
                self.issue(test,err,'failure' if failure else 'error',self.failures if failure else self.errors,
                           'subtest_issue',self.callbacks)
        def stopTest(self,test):
            self.active(test)
            if self.outcome is None:raise ValueError('d27_result_missing_outcome')
            self.finished=True;self.parent_outcomes={self.outcome['outcome']:1}
            emit({'event':'test_terminal','test_id':test_id,'subtest_callbacks':self.callbacks,
                  'issue_counts':dict(self.counts),**self.outcome})
            super().stopTest(test);gate()
    out,err=Stream(True),Stream(False);result=Result()
    try:
        sys.stdout,sys.stderr=out,err
        unittest.TestSuite([selected]).run(result)
    finally:sys.stdout,sys.stderr=original_stdout,original_stderr
    streams={'stdout':out.facts(),'stderr':err.facts()}
    good=(result.started and result.finished and result.testsRun==1 and result.wasSuccessful()
          and not result.skipped and not result.expectedFailures and out.forwarded==2
          and out.source_records==out.case_records==1 and out.source_kind=='d27_inert_source_construction_metadata_v1'
          and not any(row['unexpected_or_unterminated'] for row in streams.values()) and err.count==0)
    emit({'event':'test_summary','selected_class':'D27CompleteGeometryTests','tests_run':result.testsRun,
        'expected_metadata_records':2,'geometry_source_records':out.source_records,'geometry_case_records':out.case_records,
        'successes':result.successes,'failures':len(result.failures),'errors':len(result.errors),'skips':len(result.skipped),
        'expected_failures':len(result.expectedFailures),'unexpected_successes':len(result.unexpectedSuccesses),
        'issue_events':result.issue_total,'subtest_callbacks':result.callbacks,'parent_outcomes':result.parent_outcomes,
        'successful':good,'test_streams':streams,'generated_operational_program_execution':False,
        'descendant_quiescence':'UNKNOWN'})
    return 0 if good else 1


class D27CompleteGeometryTests(unittest.TestCase):
    def test_complete_form_bounds_preserve_hold(self):
        import time
        # Ordinary CI cannot consume the separate one-risk admission.
        if len(sys.argv)!=4 or sys.argv[3]!='--d27-sole-inert-geometry-child':
            self.skipTest('D27 sole geometry requires separately recorded Root admission')
        self.assertEqual(sys.version_info[:3],(3,14,7))
        self.assertTrue(sys.flags.isolated and sys.flags.no_site and sys.flags.dont_write_bytecode
                        and not sys.flags.optimize)
        deadline=float(sys.argv[2])
        self.assertTrue(math.isfinite(deadline) and 0<deadline-time.monotonic()<=27)
        try:
            data,source=d27_inert_bundle_v1(deadline)
        except Exception as error:
            facts=d27_error_facts_v1(error);capture=facts.pop('exception_capture')
            source={'kind':'d27_construction_failure_metadata_v1',**facts,**capture,
                    'generated_operational_program_execution':False,
                    'generated_full_subject_files_written':False,'physical_acceptance':False}
            # Fixed construction exceptions have an available finite message.
            if 'message_unavailable' in source:
                raise RuntimeError('d27_construction_message_unavailable') from None
            encoded=canonical(source)
            if len(encoded)+len('D27_GEOMETRY_SOURCE_METADATA ')+1>32768:raise RuntimeError('d27_source_metadata_bound') from None
            print('D27_GEOMETRY_SOURCE_METADATA '+encoded.decode('ascii'),flush=True)
            raise
        encoded=canonical(source)
        if len(encoded)+len('D27_GEOMETRY_SOURCE_METADATA ')+1>32768:raise RuntimeError('d27_source_metadata_bound')
        print('D27_GEOMETRY_SOURCE_METADATA '+encoded.decode('ascii'),flush=True)
        report,capture=d27_run_geometry_v1(data,deadline)
        case={'case':'geometry','report':report,'capture':capture};encoded=canonical(case)
        if len(encoded)+len('D27_CASE_METADATA ')+1>32768:raise RuntimeError('d27_case_metadata_bound')
        print('D27_CASE_METADATA '+encoded.decode('ascii'),flush=True)
        self.assertTrue(report['completed'] and report['cause'] is None
                        and report['checks'] and all(row['ok'] for row in report['checks']))


class D27ProtocolControlsTests(unittest.TestCase):
    def held_admission(self):
        import ast
        root=Path(__file__).absolute().parents[1]
        admitted={};raws={}
        for role,name in (('main','test_accepted_policy_fixture_compiler_gate2_dictionary_v1.py'),
                          ('caller','test_accepted_policy_fixture_compiler_gate2_dictionary_caller_v1.py')):
            raw=(root/'tests'/name).read_bytes();raws[role]=raw
            admitted[role]={'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
        keys=('ROOT_ENCODER','ROOT_SHA256','D27_WIRE_CODEC','D27_GEOMETRY_MODEL','D27_GEOMETRY_STDIO')
        literals={n.targets[0].id:ast.literal_eval(n.value) for n in ast.parse(raws['main']).body
                  if type(n) is ast.Assign and len(n.targets)==1 and type(n.targets[0]) is ast.Name and n.targets[0].id in keys}
        digest=hashlib.sha256();extent=0
        for i,key in enumerate(keys):
            if i:digest.update(b'\n');extent+=1
            data=literals[key].encode('ascii');digest.update(data);extent+=len(data)
        admitted['driver']={'size_bytes':extent,'sha256':digest.hexdigest()}
        codec=literals['D27_WIRE_CODEC'];at=codec.index('function gate2WireEncode(text,tag,sha,canon,guard){')
        admitted['codec']={role:{'size_bytes':len(part),'sha256':hashlib.sha256(part.encode('ascii')).hexdigest()}
                           for role,part in (('full',codec),('decoder',codec[:at]),('tail',codec[at:]))}
        return admitted

    def binding(self,admitted):
        codec=admitted['codec']
        return {'event':'source_bindings','sources':[{'path':path,**admitted[role]} for path,role in (
            ('tests/test_accepted_policy_fixture_compiler_gate2_dictionary_v1.py','main'),
            ('tests/test_accepted_policy_fixture_compiler_gate2_dictionary_caller_v1.py','caller'))],
            'both_buffers_verified_before_either_compile':True,'held_driver_loader_bound':True,
            'held_driver_module':'tests.test_accepted_policy_fixture_compiler_gate2_dictionary_v1',
            'execution_reopens_test_paths':False,'held_driver_aliases_bound':True,'held_caller_aliases_bound':True,
            'codec_role':{'kind':'d27_node_codec_role_v1','full_codec_bytes':codec['full']['size_bytes'],
                'full_codec_sha256':codec['full']['sha256'],'node_codec_bytes':codec['decoder']['size_bytes'],
                'node_codec_sha256':codec['decoder']['sha256'],'excluded_encoder_bytes':codec['tail']['size_bytes'],
                'excluded_encoder_sha256':codec['tail']['sha256'],'marker_occurrences':1,
                'role_is_exact_prefix':True,'encoder_excluded':True},
            'fixed_driver':{'source_kind':'d27_fixed_test_driver_v1','driver_role':'geometry',
                'driver_getter':'d27_geometry_driver_v1','program_bytes':admitted['driver']['size_bytes'],
                'program_sha256':admitted['driver']['sha256']}}

    def test_partial_protocol_never_invents_completion(self):
        admitted=self.held_admission();binding=self.binding(admitted)
        for raw in (b'',b'{',canonical(binding)+b'\n',canonical(binding)+b'\n{'):
            self.assertEqual(d27_original_protocol_v1(raw,b'',None,admitted),(None,None,None,False,False,False))

    def test_closed_binding_and_known_pin_contradictions_refuse(self):
        admitted=self.held_admission();binding=self.binding(admitted)
        for row in ({**binding,'extra':True},{**binding,'held_driver_aliases_bound':False},
                    {**binding,'sources':[]},{**binding,'codec_role':{**binding['codec_role'],'marker_occurrences':True}}):
            with self.assertRaises(AssertionError):d27_original_protocol_v1(canonical(row)+b'\n',b'',None,admitted)
        raw=canonical(binding)+b'\n'
        with self.assertRaises(AssertionError):d27_original_protocol_v1(raw+raw,b'',None,admitted)

    def test_untagged_metadata_and_parseable_wrong_fields_refuse(self):
        admitted=self.held_admission()
        rows=({'event':'source_metadata','data':{}},{'event':'case_metadata','data':{}},
              {'event':'test_started','test_id':'wrong'},
              {'event':'test_summary','selected_class':'wrong'},
              {'event':'entry_failure','error_type':'RuntimeError','message_size_bytes':None,
               'message_sha256':None,'message_unavailable':False,'secondary':[]})
        for row in rows:
            with self.subTest(event=row['event']):
                with self.assertRaises(AssertionError):d27_original_protocol_v1(canonical(row)+b'\n',b'',None,admitted)


class D27EntryTransportControlsTests(unittest.TestCase):
    def test_mocked_genuine_capture_preserves_valid_report_on_transport_failure(self):
        from unittest import mock
        import time
        main=_d27_main_module_v1();caller=sys.modules[__name__]
        helper=D27FixedDriverTransportTests()
        data=b'{}';construction={'input':{'size_bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}}
        for role,route in (('genuine_initial',main.d27_run_genuine_initial_v1),('genuine_finalizer',main.d27_run_genuine_finalizer_v1)):
            output=helper._output(case=role,completed=False,cause='d27_genuine_assertion')
            # Only fake pipe/process objects run; no builder or Node is called.
            process=helper._fake_process(stdout=output,status=1)
            with mock.patch.object(caller,'d27_require_positive_geometry_v1',return_value={}):
                with mock.patch.object(main,'_d27_genuine_material_v1',return_value=(data,{},construction)):
                    with mock.patch('shutil.which',return_value=sys.executable),mock.patch('subprocess.Popen',return_value=process):
                        with self.assertRaises(D27CaseError) as caught:route(time.monotonic()+40)
            error=caught.exception;self.assertIn('child_status',error.metadata['causes'])
            self.assertFalse(error.metadata['parent_observed_completion'])
            with mock.patch.object(caller,'d27_genuine_construction_metadata_v1',return_value=None):
                report,facts=d27_genuine_failure_metadata_v1(error,role)
            self.assertEqual(canonical(report)+b'\n',output)
            self.assertEqual(facts['capture'],error.metadata)
            self.assertTrue(facts['capture_available'] and facts['report_available'])
            self.assertEqual(facts['report_sha256'],hashlib.sha256(output).hexdigest())
            self.assertFalse(facts['physical_acceptance'])
            error.args=('\ud800',)
            with mock.patch.object(caller,'d27_genuine_construction_metadata_v1',return_value=None):
                report,surrogate=d27_genuine_failure_metadata_v1(error,role)
            self.assertTrue(surrogate['message_unavailable'])
            self.assertEqual(surrogate['capture'],error.metadata)
            self.assertEqual(canonical(report)+b'\n',output)

    def test_mocked_genuine_negative_report_is_not_behavioral_acceptance(self):
        from unittest import mock
        import time
        main=_d27_main_module_v1();caller=sys.modules[__name__];helper=D27FixedDriverTransportTests()
        data=b'{}';construction={'input':{'size_bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}}
        output=helper._output(case='genuine_initial',completed=False,cause='d27_genuine_assertion')
        process=helper._fake_process(stdout=output)
        with mock.patch.object(caller,'d27_require_positive_geometry_v1',return_value={}):
            with mock.patch.object(main,'_d27_genuine_material_v1',return_value=(data,{},construction)):
                with mock.patch('shutil.which',return_value=sys.executable),mock.patch('subprocess.Popen',return_value=process):
                    report,capture=main.d27_run_genuine_initial_v1(time.monotonic()+40)
        with mock.patch.object(caller,'d27_genuine_construction_metadata_v1',return_value=None):
            first,last=d27_genuine_success_records_v1(report,capture)
            import copy
            bad=copy.deepcopy(capture);bad['program_bytes']=None;bad['program_sha256']=None
            with self.assertRaisesRegex(ValueError,'d27_genuine_normal_descriptor'):d27_genuine_capture_metadata_v1(bad)
            bad=copy.deepcopy(capture);bad['stdout']['unknown_remainder']=True
            with self.assertRaisesRegex(ValueError,'d27_genuine_capture_channel_join'):d27_genuine_capture_metadata_v1(bad)
        self.assertEqual(first,output);self.assertFalse(report['completed'])
        self.assertTrue(capture['parent_observed_completion'])
        self.assertEqual(json.loads(last)['event'],'genuine_capture')
        self.assertEqual(json.loads(last)['capture'],capture)

    def test_genuine_metadata_rejects_raw_source_and_oversize_before_encoding(self):
        from unittest import mock
        with self.assertRaisesRegex(ValueError,'d27_genuine_construction_fields'):
            d27_genuine_construction_metadata_v1({'raw_source':'prohibited TEST sentinel'})
        with mock.patch.object(sys.modules[__name__],'canonical',side_effect=AssertionError('encoding_reached')):
            with self.assertRaisesRegex(ValueError,'d27_genuine_metadata_encoding_bound'):
                d27_genuine_plain_size_v1({'value':'x'*32767})
        for value in ({'value':'\u00e9'}, {'value':'\ud800'}, {'value':'"\\\n\t'}, [None,True,False,1,-1,1.25]):
            self.assertEqual(d27_genuine_plain_size_v1(value),len(canonical(value)))

    def test_genuine_complete_test_and_future_pure_source_headroom(self):
        import ast
        main_raw=Path(__file__).with_name('test_accepted_policy_fixture_compiler_gate2_dictionary_v1.py').read_bytes()
        values={node.targets[0].id:ast.literal_eval(node.value) for node in ast.parse(main_raw).body
                if type(node) is ast.Assign and len(node.targets)==1 and type(node.targets[0]) is ast.Name
                and node.targets[0].id in {'D27_GENUINE_VM_CORE','D27_GENUINE_INITIAL_TEST','D27_GENUINE_FINALIZER_TEST'}}
        # Independent delimiter-inclusive scalar bound, with no fabricated PIN.
        def obj(fields):return 2+sum(len(json.dumps(key))+1+size for key,size in fields)+max(0,len(fields)-1)
        def pin(digits):return obj([('size_bytes',digits),('sha256',66)])
        roles=obj([(key,pin(digits)) for key,digits in (('component',5),('finalizer',6),('initial',5),
                   ('resume',5),('root',6),('structured_failure',4),('success',4),('unicode_failure',4))])
        upper=obj([('roles',roles),('setup_python',pin(6)),('writer_python',pin(6)),('commit',42),
                   ('approval',len(json.dumps('https://github.com/lordcoudy/VAST/pull/9#issuecomment-1234567890'))),
                   ('packet_sha256',66),('factory_sha256',66),('executor',pin(6))])
        self.assertEqual(upper,1518)
        for role in ('initial','finalizer'):
            prefix=len('const E=')+upper+len(';\nconst D27_CASE=')+len(json.dumps('genuine_'+role))+len(';\n')
            complete=prefix+len(values['D27_GENUINE_VM_CORE'])+1+len(values['D27_GENUINE_'+role.upper()+'_TEST'])
            self.assertLessEqual(complete,24576,role+' complete fixed TEST bound')
        self.assertEqual(values['D27_GENUINE_VM_CORE'].count('codeGeneration:{strings:false,wasm:false}'),1)
        caller_raw=Path(__file__).read_bytes();tree=ast.parse(caller_raw)
        development=next(node for node in tree.body if type(node) is ast.ClassDef and node.name=='D27CompleteGeometryTests')
        author=next(node for node in tree.body if type(node) is ast.FunctionDef and node.name=='d27_pure_class_source_v1')
        body=next(ast.literal_eval(node.value) for node in author.body if type(node) is ast.Assign and len(node.targets)==1 and type(node.targets[0]) is ast.Name and node.targets[0].id=='body')
        def pyobj(fields):return 2+2*max(0,len(fields)-1)+sum(len(repr(key))+2+size for key,size in fields.items())
        py_pin=pyobj({'size_bytes':7,'sha256':66})
        py_admitted=pyobj({**{key:py_pin for key in ('entry','main','caller','driver')},'codec':pyobj({key:py_pin for key in ('full','decoder','tail')})})
        py_external=pyobj({'attribution':len(repr('root_observed_tool_result_not_child_self_receipt')),'reference':386,'completed':5,'exit_code':11,'wall_time_seconds':32})
        head=next(node.value for node in author.body if type(node) is ast.Assign and len(node.targets)==1 and type(node.targets[0]) is ast.Name and node.targets[0].id=='head')
        header_bound=sum(len(node.value.encode('ascii')) for node in ast.walk(head) if type(node) is ast.Constant and type(node.value) is str)+py_pin+66+py_admitted+py_external
        self.assertLessEqual(header_bound,4096)
        self.assertLessEqual(len(caller_raw)-len(ast.get_source_segment(caller_raw.decode('ascii'),development).encode('ascii'))+len(body.encode('ascii'))+header_bound+16,524288)
        self.assertLessEqual(len(main_raw),524288)

    def test_genuine_routes_are_fixed_and_require_positive_geometry(self):
        import ast
        main_path=Path(__file__).with_name('test_accepted_policy_fixture_compiler_gate2_dictionary_v1.py')
        tree=ast.parse(main_path.read_bytes())
        functions={node.name:node for node in tree.body if type(node) is ast.FunctionDef}
        for name in ('d27_run_genuine_initial_v1','d27_run_genuine_finalizer_v1'):
            self.assertTrue(name in functions,'D27 fixed genuine route absent: '+name)
            node=functions[name]
            self.assertEqual([arg.arg for arg in node.args.args],['deadline'])
            self.assertFalse(node.args.defaults or node.args.kw_defaults or node.args.vararg or node.args.kwarg)
            calls=[item.func.attr for item in ast.walk(node) if type(item) is ast.Call and type(item.func) is ast.Attribute]
            self.assertIn('d27_require_positive_geometry_v1',calls)
        self.assertIn('D27_GENUINE_INITIAL_ENTRY',globals())
        self.assertIn('D27_GENUINE_FINALIZER_ENTRY',globals())

    def test_genuine_routes_refuse_before_material_construction(self):
        from unittest import mock
        main=_d27_main_module_v1()
        for route in (main.d27_run_genuine_initial_v1,main.d27_run_genuine_finalizer_v1):
            with mock.patch.object(sys.modules[__name__],'d27_require_positive_geometry_v1',side_effect=RuntimeError('controlled_geometry_not_admitted')):
                with self.assertRaisesRegex(RuntimeError,'^controlled_geometry_not_admitted$'):
                    route(0)

    def test_fallback_output_failure_has_no_chained_traceback(self):
        import subprocess
        root=Path('C:/Users/s-a-balashov/.codex/worktrees/fix-accepted-policy-preprocessing/VAST')
        if os.name!='nt' or sys.version_info[:3]!=(3,14,7) or Path(__file__).absolute().parents[1]!=root:
            self.skipTest('D27 held-entry control requires fixed Windows Python3.14.7 worktree')
        control=('import sys,pathlib\n'
                 'class BrokenBuffer:\n'
                 ' def write(self,value):raise OSError("controlled_output_failure")\n'
                 ' def flush(self):raise OSError("controlled_flush_failure")\n'
                 'class ControlStdout:\n'
                 ' buffer=BrokenBuffer()\n'
                 ' def reconfigure(self,**kwargs):pass\n'
                 ' def flush(self):pass\n'
                 'sys.stdout=ControlStdout()\n'
                 'def denied():raise RuntimeError("controlled_original_error")\n'
                 'pathlib.Path.cwd=staticmethod(denied)\n')
        result=subprocess.run([sys.executable,'-I','-S','-B','-c',control+D27_GEOMETRY_TEST_ENTRY,'{}'],
                              cwd=root,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=10)
        self.assertEqual(result.returncode,1);self.assertEqual(result.stdout,b'');self.assertEqual(result.stderr,b'')

    def test_all_held_aliases_bind_before_intercepted_geometry_route(self):
        import subprocess
        root=Path('C:/Users/s-a-balashov/.codex/worktrees/fix-accepted-policy-preprocessing/VAST')
        if os.name!='nt' or sys.version_info[:3]!=(3,14,7) or Path(__file__).absolute().parents[1]!=root:
            self.skipTest('D27 held-entry control requires fixed Windows Python3.14.7 worktree')
        pins={}
        for role,name in (('main','test_accepted_policy_fixture_compiler_gate2_dictionary_v1.py'),
                          ('caller','test_accepted_policy_fixture_compiler_gate2_dictionary_caller_v1.py')):
            raw=(root/'tests'/name).read_bytes();pins[role]=[len(raw),hashlib.sha256(raw).hexdigest()]
        route='return modules[1].d27_geometry_child_v1(expected) if len(sys.argv)==4 else modules[1].d27_geometry_root_v1(expected)'
        self.assertEqual(D27_GEOMETRY_TEST_ENTRY.count(route),1)
        # Intercept only the final route after the unchanged holder/alias checks.
        control=D27_GEOMETRY_TEST_ENTRY.replace(route,'raise RuntimeError("aliases_verified_without_geometry")')
        result=subprocess.run([sys.executable,'-I','-S','-B','-c',control,json.dumps(pins,separators=(',',':'))],
                              cwd=root,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=10)
        self.assertEqual(result.returncode,1);self.assertEqual(result.stderr,b'')
        row=json.loads(result.stdout);self.assertEqual(row['event'],'entry_failure')
        self.assertEqual(row['error_type'],'RuntimeError')
        self.assertEqual(row['message_sha256'],hashlib.sha256(b'aliases_verified_without_geometry').hexdigest())
        self.assertEqual(canonical(row)+b'\n',result.stdout)

    def test_geometry_entry_refuses_bad_pin_before_any_held_compile(self):
        import subprocess
        root=Path('C:/Users/s-a-balashov/.codex/worktrees/fix-accepted-policy-preprocessing/VAST')
        if os.name!='nt' or sys.version_info[:3]!=(3,14,7) or Path(__file__).absolute().parents[1]!=root:
            self.skipTest('D27 held-entry control requires fixed Windows Python3.14.7 worktree')
        pins={}
        for role,name in (('main','test_accepted_policy_fixture_compiler_gate2_dictionary_v1.py'),
                          ('caller','test_accepted_policy_fixture_compiler_gate2_dictionary_caller_v1.py')):
            raw=(root/'tests'/name).read_bytes();pins[role]=[len(raw),hashlib.sha256(raw).hexdigest()]
        pins['main'][1]='0'*64
        watcher=('import builtins,sys\n_original_compile=builtins.compile\n'
                 'def watched(source,filename,*args,**kwargs):\n'
                 ' if filename.endswith("test_accepted_policy_fixture_compiler_gate2_dictionary_v1.py") or filename.endswith("test_accepted_policy_fixture_compiler_gate2_dictionary_caller_v1.py"):raise RuntimeError("held_compile_reached")\n'
                 ' return _original_compile(source,filename,*args,**kwargs)\n'
                 'builtins.compile=watched\n')
        child=subprocess.run([sys.executable,'-I','-S','-B','-c',watcher+D27_GEOMETRY_TEST_ENTRY,
                              json.dumps(pins,separators=(',',':'))],cwd=root,stdin=subprocess.DEVNULL,
                             stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=10)
        self.assertEqual(child.returncode,1);self.assertEqual(child.stderr,b'')
        self.assertLessEqual(len(child.stdout),32768)
        row=json.loads(child.stdout);self.assertEqual(row['event'],'entry_failure')
        self.assertEqual(row['error_type'],'AssertionError')
        self.assertNotEqual(row.get('message_sha256'),hashlib.sha256(b'held_compile_reached').hexdigest())
        self.assertEqual(canonical(row)+b'\n',child.stdout)

    def test_mocked_empty_parent_capture_stays_incomplete(self):
        import subprocess
        class Child:
            stdout=io.BytesIO(b'');stderr=io.BytesIO(b'')
            def poll(self):return 0
            def wait(self,timeout):return 0
            def kill(self):raise AssertionError('unexpected_kill')
        pins={}
        for role,name in (('main','test_accepted_policy_fixture_compiler_gate2_dictionary_v1.py'),
                          ('caller','test_accepted_policy_fixture_compiler_gate2_dictionary_caller_v1.py')):
            raw=Path(__file__).with_name(name).read_bytes();pins[role]=[len(raw),hashlib.sha256(raw).hexdigest()]
        with mock.patch.object(subprocess,'Popen',return_value=Child()) as launch:
            originals,parent=d27_geometry_parent_v1(pins)
        self.assertEqual(launch.call_count,1)
        self.assertEqual(originals['stdout'],b'');self.assertEqual(originals['stderr'],b'')
        self.assertIsNone(originals['canonical_report'])
        self.assertTrue(parent['threads_joined']);self.assertFalse(parent['io_failure'])
        self.assertEqual(parent['protocol_error_type'],'d27_protocol_incomplete')
        self.assertFalse(parent['parent_observed_test_transport_complete'])
        self.assertFalse(parent['geometry_risk_passed'])
        self.assertEqual(parent['descendant_quiescence'],'UNKNOWN')
        for row in parent['channels'].values():
            self.assertTrue(row['eof'] and row['closed'] and row['close_attempted'])
            self.assertEqual(row['observed_bytes'],row['size_bytes'])

    def test_unowned_error_never_calls_message_or_metadata_getter(self):
        class Unowned(RuntimeError):
            @property
            def metadata(self):raise AssertionError('metadata_getter_called')
            def __str__(self):raise AssertionError('message_getter_called')
        row=d27_error_facts_v1(Unowned('private-test-sentinel'))
        self.assertTrue(row['message_unavailable'])
        self.assertIsNone(row['message_size_bytes']);self.assertIsNone(row['message_sha256'])
        self.assertTrue(row['exception_capture']['capture_metadata_unavailable'])
        self.assertIsNone(row['exception_capture']['capture'])
        safe=d27_error_facts_v1(RuntimeError('bounded-error'))
        self.assertEqual(safe['message_size_bytes'],13)
        self.assertEqual(safe['message_sha256'],hashlib.sha256(b'bounded-error').hexdigest())

    def test_error_encoding_refuses_unbounded_data_before_serialization(self):
        main=_d27_main_module_v1()
        error=main.D27PhaseConstructionError('bounded',{'unreviewed':'x'*100000})
        with mock.patch.object(json,'JSONEncoder',side_effect=AssertionError('serialization_reached')) as encoder:
            row=d27_error_facts_v1(error)
        encoder.assert_not_called()
        self.assertTrue(row['exception_capture']['capture_metadata_unavailable'])
        self.assertIsNone(row['exception_capture']['capture_metadata_size_bytes'])
        self.assertIsNone(row['exception_capture']['capture_metadata_sha256'])
        oversized=d27_error_facts_v1(RuntimeError('x'*4097))
        self.assertTrue(oversized['message_unavailable'])
        self.assertIsNone(oversized['message_size_bytes'])
        class Meta(type):
            def __getattribute__(cls,name):
                if name=='__name__':raise AssertionError('metaclass_getter_called')
                return super().__getattribute__(name)
        class Foreign(RuntimeError,metaclass=Meta):pass
        self.assertEqual(d27_error_facts_v1(Foreign('unowned'))['error_type'],'Foreign')

    def test_retention_keeps_known_prefixes_and_attempts_every_original(self):
        # Metadata I/O fixtures only: parent and all filesystem calls are mocked.
        names=('stdout','stderr','parent','canonical_report')
        originals={name:('unit-'+name+'\n').encode('ascii') for name in names}
        filenames={'vast-d27-sole-inert-geometry-v1.'+name+'.original.txt':name for name in names}
        for fault in ('write','fsync'):
            data={};opened=[];reads={};fd_names={};output=io.BytesIO()
            class File:
                def __init__(self,name):
                    self.name=name;self.writes=0;self.fd=100+names.index(name)
                    data[name]=bytearray();fd_names[self.fd]=name
                def fileno(self):return self.fd
                def write(self,raw):
                    self.writes+=1
                    if fault=='write' and self.name=='stdout':
                        if self.writes==1:data[self.name].extend(raw[:4]);return 4
                        data[self.name].extend(raw[:1]);raise OSError('controlled-partial-write')
                    data[self.name].extend(raw);return len(raw)
                def flush(self):pass
                def close(self):pass
            def open_write(path,mode,*,buffering):
                self.assertEqual((mode,buffering),('xb',0));name=filenames[path.name]
                opened.append(name);return File(name)
            def stat_for(name):
                return types.SimpleNamespace(st_dev=1,st_ino=names.index(name)+1,st_mode=0o100600,
                    st_nlink=1,st_size=len(data[name]),st_mtime_ns=1)
            def open_read(path,flags):
                name=filenames[Path(path).name];fd=200+names.index(name);fd_names[fd]=name;reads[fd]=0;return fd
            def read(fd,size):
                name=fd_names[fd];at=reads[fd];raw=bytes(data[name][at:at+size]);reads[fd]+=len(raw);return raw
            def fsync(fd):
                if fault=='fsync' and fd_names[fd]=='stdout':raise OSError('controlled-fsync')
            with self.subTest(fault=fault),mock.patch.object(sys.modules[__name__],'d27_geometry_parent_v1',
                    return_value=(originals,{'geometry_risk_passed':True})),mock.patch.object(os.path,'lexists',return_value=False),\
                 mock.patch.object(Path,'open',autospec=True,side_effect=open_write),\
                 mock.patch.object(Path,'lstat',autospec=True,side_effect=lambda path:stat_for(filenames[path.name])),\
                 mock.patch.object(os,'open',side_effect=open_read),mock.patch.object(os,'fstat',side_effect=lambda fd:stat_for(fd_names[fd])),\
                 mock.patch.object(os,'read',side_effect=read),mock.patch.object(os,'close'),\
                 mock.patch.object(os,'fsync',side_effect=fsync),mock.patch.object(sys,'stdout',types.SimpleNamespace(buffer=output)):
                status=d27_geometry_root_v1({})
            self.assertEqual(status,1);self.assertEqual(opened,list(names))
            report=json.loads(output.getvalue());self.assertTrue(report['geometry_risk_passed'])
            self.assertFalse(report['retention_complete']);self.assertFalse(report['physical_persistence_attested'])
            for name in names:
                row=report['originals'][name];self.assertTrue(row['available'])
                self.assertEqual(row['size_bytes'],len(data[name]))
                self.assertEqual(row['sha256'],hashlib.sha256(data[name]).hexdigest())
                self.assertEqual(row['expected_size_bytes'],len(originals[name]))
            row=report['originals']['stdout']
            if fault=='write':
                self.assertEqual(row['size_bytes'],5);self.assertEqual(row['retention']['written_bytes'],4)
                self.assertTrue(row['retention']['write_extent_unknown'])
            else:
                self.assertEqual(row['size_bytes'],len(originals['stdout']))
                self.assertFalse(row['retention']['fsync_completed'])

    def test_existing_metadata_or_outcome_refuses_before_parent(self):
        names=('stdout','stderr','parent','canonical_report','fixture')
        for existing in names:
            def lexists(path):
                return (Path(path).name=='d27-geometry-retained-v1.json' if existing=='fixture'
                        else Path(path).name=='vast-d27-sole-inert-geometry-v1.'+existing+'.original.txt')
            with self.subTest(existing=existing),mock.patch.object(os.path,'lexists',side_effect=lexists),\
                 mock.patch.object(sys.modules[__name__],'d27_geometry_parent_v1') as parent,\
                 mock.patch.object(Path,'open') as opened:
                with self.assertRaises(RuntimeError):d27_geometry_root_v1({})
            parent.assert_not_called();opened.assert_not_called()


def d27_genuine_construction_metadata_v1(value):
    """Closed metadata schemas exclude operational strings at every level."""
    def keys(item,expected):
        if (type(item) is not dict or len(item)>128 or any(type(key) is not str or len(key)>128 for key in item)
                or set(item)!=set(expected.split())):
            raise ValueError('d27_genuine_construction_fields')
    def number(item,cap=262144):
        if type(item) is not int or not 0<=item<=cap:raise ValueError('d27_genuine_construction_count')
    def digest(item):
        if type(item) is not str or re.fullmatch('[0-9a-f]{64}',item) is None:raise ValueError('d27_genuine_construction_hash')
    def pin(item,cap):
        keys(item,'size_bytes sha256');number(item['size_bytes'],cap);digest(item['sha256'])
        if item['size_bytes']==0:raise ValueError('d27_genuine_construction_pin')
    keys(value,'kind initial finalizer codec roles executor input generated_operational_program_execution generated_full_subject_files_written physical_acceptance')
    if (value['kind']!='d27_genuine_construction_metadata_v1' or any(value[key] is not False for key in
            ('generated_operational_program_execution','generated_full_subject_files_written','physical_acceptance'))):
        raise ValueError('d27_genuine_construction_scope')
    initial=value['initial']
    keys(initial,'kind source_bytes source_sha256 escaped_source_bytes baseline_bytes baseline_sha256 original_builder_bytes original_builder_sha256 baseline_body_bytes baseline_body_sha256 prefix_bytes prefix_sha256 decoder_bytes decoder_sha256 canonical_data_bytes canonical_data_sha256 compressed_data_bytes compressed_data_sha256 base64_data_bytes base64_data_sha256 data_fields strings_field_absent deferred_definition_bytes deferred_definition_sha256 exact_decoder_inverse exact_phase_inverse exact_inverse_source source_contribution_fits source_only_over_cap_by complete_geometry_qualified behavior_conformance_complete finalizer_implemented generated_operational_program_executed generated_full_subject_files_written status task_2_10_complete compression')
    if initial['kind']!='d24_initial_source_only_v1' or initial['status'] not in ('UNQUALIFIED_SOURCE_ONLY','HOLD_SOURCE_CONTRIBUTION_OVER_CAP'):
        raise ValueError('d27_genuine_initial_identity')
    for key,item in initial.items():
        if key.endswith('_sha256'):digest(item)
        elif key.endswith('_bytes') or key in ('data_fields','source_only_over_cap_by'):number(item)
    for key in ('strings_field_absent','exact_decoder_inverse','exact_phase_inverse','exact_inverse_source'):
        if initial[key] is not True:raise ValueError('d27_genuine_initial_inverse')
    for key in ('complete_geometry_qualified','behavior_conformance_complete','finalizer_implemented','generated_operational_program_executed','generated_full_subject_files_written','task_2_10_complete'):
        if initial[key] is not False:raise ValueError('d27_genuine_initial_scope')
    if (type(initial['source_contribution_fits']) is not bool or initial['data_fields']!=9
            or initial['source_bytes']!=14162 or initial['source_sha256']!='4032a534147aada87931734f3b06cde67988d62c75851b959945399843a3770d'):
        raise ValueError('d27_genuine_unchanged_initial')
    compression=initial['compression'];d27_capture_metadata_v1(compression)
    if (compression['parent_observed_completion'] is not True or compression['data_only'] is not True
            or compression['input_bytes']!=initial['canonical_data_bytes'] or compression['input_sha256']!=initial['canonical_data_sha256']
            or compression['packed_bytes']!=initial['compressed_data_bytes'] or compression['packed_sha256']!=initial['compressed_data_sha256']):
        raise ValueError('d27_genuine_compression_join')
    final=value['finalizer']
    keys(final,'initial_size_bytes initial_sha256 finalizer_size_bytes finalizer_sha256 factory_size_bytes factory_sha256 wrapper_prefix_size_bytes wrapper_suffix_size_bytes python_head_size_bytes python_head_sha256 python_tail_size_bytes python_tail_sha256 python_common_size_bytes python_common_sha256 generated_operational_program_execution generated_full_subject_files_written')
    for key,item in final.items():
        if key.endswith('_sha256'):digest(item)
        elif key.endswith('_bytes'):number(item)
        elif item is not False:raise ValueError('d27_genuine_finalizer_scope')
    if (final['initial_size_bytes']!=initial['source_bytes'] or final['initial_sha256']!=initial['source_sha256']
            or final['factory_size_bytes']!=13073 or final['factory_sha256']!='997579f8ffcc50d6e05ae859dd9164b1dc08ce5a71e82a1d8070633c3cdf3677'):
        raise ValueError('d27_genuine_finalizer_join')
    codec=value['codec']
    keys(codec,'kind full_codec_bytes full_codec_sha256 node_codec_bytes node_codec_sha256 excluded_encoder_bytes excluded_encoder_sha256 marker_occurrences role_is_exact_prefix encoder_excluded')
    if (codec['kind']!='d27_node_codec_role_v1' or type(codec['marker_occurrences']) is not int or codec['marker_occurrences']!=1
            or codec['role_is_exact_prefix'] is not True or codec['encoder_excluded'] is not True):
        raise ValueError('d27_genuine_codec_role')
    for name,size,sha in (('full_codec',6779,'071da76e6b0c03ef7d01f82fb552f25807720787e1d863543934416165ddbeee'),
                          ('node_codec',4397,'6d59e7482bcf92b620ccf758152bdfb76dddf99738329d47250171b49712a657'),
                          ('excluded_encoder',2382,'479e56d80c86221b3630a014439c46073685689b0d435407aea87fd4071bcaae')):
        if type(codec[name+'_bytes']) is not int or codec[name+'_bytes']!=size or codec[name+'_sha256']!=sha:
            raise ValueError('d27_genuine_codec_pin')
    roles=value['roles'];keys(roles,'component finalizer initial resume root structured_failure success unicode_failure')
    for name,item in roles.items():pin(item,2048 if name in ('structured_failure','success','unicode_failure') else 262144)
    if (roles['initial']!={'size_bytes':initial['source_bytes'],'sha256':initial['source_sha256']}
            or roles['finalizer']!={'size_bytes':final['finalizer_size_bytes'],'sha256':final['finalizer_sha256']}
            or roles['component']!={'size_bytes':32732,'sha256':'329fb13f2c6dcee0872e5a29ec1fd769dc6e57ce92ee1076fef6737f1da86d88'}
            or roles['resume']!={'size_bytes':32739,'sha256':'5fd7d2d6ee62ff584d2a4662757ca804a3d3300d30bb966319901870c4c85670'}):
        raise ValueError('d27_genuine_role_join')
    pin(value['executor'],262144);pin(value['input'],262144)


def d27_genuine_plain_size_v1(value):
    """Count exact canonical ASCII bytes before allocating encoded metadata."""
    pending=[(value,0)];nodes=0;extent=0
    while pending:
        item,depth=pending.pop();nodes+=1
        if nodes>4096 or depth>32:raise ValueError('d27_genuine_capture_shape')
        if type(item) is dict:
            if len(item)>128 or any(type(key) is not str or re.fullmatch('[A-Za-z_][A-Za-z0-9_]{0,127}',key) is None for key in item):
                raise ValueError('d27_genuine_capture_keys')
            extent+=2+max(0,len(item)-1)+sum(len(key)+3 for key in item)
            pending.extend((child,depth+1) for child in item.values())
        elif type(item) is list:
            if len(item)>512:raise ValueError('d27_genuine_capture_array')
            extent+=2+max(0,len(item)-1);pending.extend((child,depth+1) for child in item)
        elif type(item) is str:
            if len(item)>32768:raise ValueError('d27_genuine_capture_string')
            extent+=2
            for char in item:
                point=ord(char)
                extent+=1 if 32<=point<=126 and point not in (34,92) else 2 if char in '\b\f\n\r\t"\\' else 6 if point<=65535 else 12
                if extent>32768:raise ValueError('d27_genuine_metadata_encoding_bound')
        elif item is None:extent+=4
        elif type(item) is bool:extent+=4 if item else 5
        elif type(item) is int:
            if not -9007199254740991<=item<=9007199254740991:raise ValueError('d27_genuine_capture_integer')
            extent+=len(str(item))
        elif type(item) is float:
            if not math.isfinite(item):raise ValueError('d27_genuine_capture_clock')
            extent+=len(json.dumps(item,allow_nan=False))
        else:raise ValueError('d27_genuine_capture_plain_DATA')
        if extent>32768 or len(pending)+nodes>4096:raise ValueError('d27_genuine_metadata_encoding_bound')
    return extent


def d27_genuine_capture_metadata_v1(value):
    """Validate finite plain owned genuine capture DATA without raw fallback."""
    if (type(value) is not dict or len(value)>128 or any(type(key) is not str for key in value)
            or type(value.get('source_kind')) is not str
            or value.get('source_kind')!='d27_fixed_genuine_test_v1' or value.get('data_only') is not False):
        raise ValueError('d27_genuine_capture_kind')
    base=set('schema_version data_only spawned pid returncode timed_out kill_requested stdin_bytes stdin_closed stdin_complete stdin_extent_unknown stdin_write_attempted stdin_write_in_flight threads_started reaped threads_joined causes node_version case case_completed case_cause parent_observed_completion descendant_quiescence input_bytes input_sha256 data_bytes data_sha256 report_bytes report_sha256 checks_count measurements_count environment_keys program_sha256 source_kind program_bytes driver_role driver_getter construction native_activity physical_acceptance stdout stderr elapsed_seconds finished_before_deadline child_completion_observed_before_deadline'.split())
    optional=set('started_monotonic caller_deadline work_deadline child_total_deadline cleanup_deadline child_total_limit_seconds child_work_limit_seconds cleanup_limit_seconds final_reserve_seconds node_executable command_options'.split())
    if not base<=set(value)<=base|optional:raise ValueError('d27_genuine_capture_fields')
    extent=d27_genuine_plain_size_v1(value)
    if extent>28000:raise ValueError('d27_genuine_capture_bound')
    d27_genuine_construction_metadata_v1(value['construction'])
    role=value['case']
    if (role not in ('genuine_initial','genuine_finalizer') or value['driver_role']!=role
            or value['driver_getter']!='d27_run_'+role+'_v1' or value['schema_version']!=1
            or type(value['schema_version']) is not int or value['native_activity']!='UNKNOWN'
            or value['descendant_quiescence']!='UNKNOWN' or value['physical_acceptance'] is not False):
        raise ValueError('d27_genuine_capture_identity')
    bools='spawned timed_out kill_requested stdin_closed stdin_complete stdin_extent_unknown stdin_write_attempted stdin_write_in_flight reaped threads_joined parent_observed_completion finished_before_deadline child_completion_observed_before_deadline'.split()
    if any(type(value[key]) is not bool for key in bools):raise ValueError('d27_genuine_capture_boolean')
    for key,cap,minimum in (('pid',9007199254740991,1),('stdin_bytes',262144,0),('threads_started',3,0),
             ('input_bytes',262144,1),('data_bytes',262144,1),('report_bytes',32768,1),
             ('checks_count',512,0),('measurements_count',128,0),('program_bytes',24576,1)):
        item=value[key]
        if item is not None and (type(item) is not int or not minimum<=item<=cap):raise ValueError('d27_genuine_capture_count')
    for key in ('input_sha256','data_sha256','report_sha256','program_sha256'):
        item=value[key]
        if item is not None and (type(item) is not str or re.fullmatch('[0-9a-f]{64}',item) is None):raise ValueError('d27_genuine_capture_hash')
    if (value['returncode'] is not None and (type(value['returncode']) is not int or not -2147483648<=value['returncode']<=4294967295)
            or value['case_completed'] is not None and type(value['case_completed']) is not bool
            or value['case_cause'] is not None and value['case_cause'] not in ('d27_genuine_assertion','d27_genuine_input','d27_genuine_version','d27_genuine_error')
            or value['node_version'] is not None and (type(value['node_version']) is not str or re.fullmatch(r'[0-9]{1,3}(?:\.[0-9]{1,3}){2}',value['node_version']) is None)
            or type(value['elapsed_seconds']) not in (int,float) or not math.isfinite(value['elapsed_seconds'])):
        raise ValueError('d27_genuine_capture_scalar')
    if value['environment_keys'] not in ([],['PATH'],['PATH','SystemRoot']):raise ValueError('d27_genuine_capture_environment')
    for key in ('started_monotonic','caller_deadline','work_deadline','child_total_deadline','cleanup_deadline'):
        if key in value and (type(value[key]) not in (int,float) or not math.isfinite(value[key])):raise ValueError('d27_genuine_capture_clock')
    for key,limit in (('child_total_limit_seconds',30),('child_work_limit_seconds',27),('cleanup_limit_seconds',3),('final_reserve_seconds',5)):
        if key in value and (type(value[key]) is not int or value[key]!=limit):raise ValueError('d27_genuine_capture_limit')
    if ('node_executable' in value and (type(value['node_executable']) is not str or not 0<len(value['node_executable'])<=32767)
            or 'command_options' in value and value['command_options']!=['--max-old-space-size=256','--experimental-vm-modules','--no-warnings','--input-type=commonjs','-e']):
        raise ValueError('d27_genuine_capture_command')
    for name,cap in (('stdout',1048576),('stderr',16384)):
        channel=value[name]
        if type(channel) is not dict or set(channel)!=set('observed_bytes retained_bytes eof overflow io_error closed unknown_remainder prefix_sha256'.split()):
            raise ValueError('d27_genuine_capture_channel')
        if channel['unknown_remainder'] is not (not channel['eof'] or channel['overflow'] or channel['io_error'] is not None):
            raise ValueError('d27_genuine_capture_channel_join')
        if (type(channel['observed_bytes']) is not int or type(channel['retained_bytes']) is not int
                or not 0<=channel['retained_bytes']<=cap or not channel['retained_bytes']<=channel['observed_bytes']<=9007199254740991
                or any(type(channel[key]) is not bool for key in ('eof','overflow','closed','unknown_remainder'))
                or type(channel['prefix_sha256']) is not str or re.fullmatch('[0-9a-f]{64}',channel['prefix_sha256']) is None
                or channel['io_error'] is not None and (type(channel['io_error']) is not str or re.fullmatch('[A-Za-z_][A-Za-z0-9_]{0,95}',channel['io_error']) is None)):
            raise ValueError('d27_genuine_capture_channel')
    if (type(value['causes']) is not list or len(value['causes'])>128
            or len(set(value['causes']))!=len(value['causes'])
            or any(type(cause) is not str or re.fullmatch('[A-Za-z_][A-Za-z0-9_]{0,95}',cause) is None for cause in value['causes'])):
        raise ValueError('d27_genuine_capture_causes')
    if value['parent_observed_completion']:
        if any(value[key] is None for key in ('program_bytes','program_sha256','input_bytes','input_sha256','data_bytes','data_sha256','report_bytes','report_sha256','case_completed','checks_count','measurements_count')):
            raise ValueError('d27_genuine_normal_descriptor')
        flags=('spawned','stdin_closed','stdin_complete','reaped','threads_joined','finished_before_deadline','child_completion_observed_before_deadline')
        if (not all(value[key] for key in flags) or value['timed_out'] or value['kill_requested']
                or value['stdin_extent_unknown'] or value['stdin_write_in_flight'] or value['causes']
                or type(value['returncode']) is not int or value['returncode']!=0
                or type(value['pid']) is not int or not 0<value['pid']<=9007199254740991
                or value['threads_started']!=3 or type(value['threads_started']) is not int
                or value['node_version']!='25.2.1'
                or value.get('command_options')!=['--max-old-space-size=256','--experimental-vm-modules','--no-warnings','--input-type=commonjs','-e']):
            raise ValueError('d27_genuine_normal_capture')
        for name in ('stdout','stderr'):
            channel=value[name]
            if (not channel['eof'] or not channel['closed'] or channel['overflow'] or channel['unknown_remainder']
                    or channel['io_error'] is not None or channel['observed_bytes']!=channel['retained_bytes']):
                raise ValueError('d27_genuine_normal_channel')
        if value['stderr']['retained_bytes']!=0 or value['stderr']['prefix_sha256']!=hashlib.sha256(b'').hexdigest():
            raise ValueError('d27_genuine_normal_stderr')
        for key in ('started_monotonic','caller_deadline','work_deadline','child_total_deadline','cleanup_deadline','elapsed_seconds'):
            if key not in value or type(value[key]) not in (int,float) or not math.isfinite(value[key]) or value[key]<0:
                raise ValueError('d27_genuine_normal_clock')
        start,end=value['started_monotonic'],value['caller_deadline'];observed=start+value['elapsed_seconds']
        if (value['work_deadline']!=min(start+27,end-8) or value['child_total_deadline']!=min(start+30,end-5)
                or value['cleanup_deadline']>min(value['child_total_deadline'],value['work_deadline']+3)
                or not observed<min(end,value['child_total_deadline'],value['cleanup_deadline'])
                or any(type(value.get(key)) is not int or value[key]!=limit for key,limit in
                       (('child_total_limit_seconds',30),('child_work_limit_seconds',27),('cleanup_limit_seconds',3),('final_reserve_seconds',5)))):
            raise ValueError('d27_genuine_normal_deadline')
        if (type(value['construction']) is not dict or type(value['construction'].get('input')) is not dict
                or value['construction']['input']!={'size_bytes':value['input_bytes'],'sha256':value['input_sha256']}
                or value['stdin_bytes']!=value['input_bytes'] or value['data_bytes']!=value['input_bytes']
                or value['data_sha256']!=value['input_sha256']):
            raise ValueError('d27_genuine_normal_input')
    encoded=canonical(value)
    if len(encoded)!=extent:raise ValueError('d27_genuine_metadata_extent_join')
    return encoded


def d27_genuine_report_metadata_v1(report,capture):
    if (type(report) is not dict or set(report)!={'schema_version','case','node_version','completed','cause','checks','measurements'}
            or type(report['schema_version']) is not int or report['schema_version']!=1
            or report['case']!=capture['case'] or report['node_version']!='25.2.1'
            or type(report['completed']) is not bool or report['cause'] is not None
                and report['cause'] not in ('d27_genuine_assertion','d27_genuine_input','d27_genuine_version','d27_genuine_error')
            or type(report['checks']) is not list or len(report['checks'])>512
            or type(report['measurements']) is not list or len(report['measurements'])>128):
        raise ValueError('d27_genuine_report_shape')
    for key,fields,cap in (('checks',{'id','ok'},512),('measurements',{'id','size_bytes','sha256'},128)):
        seen=set()
        for row in report[key]:
            if (type(row) is not dict or set(row)!=fields or type(row['id']) is not str
                    or re.fullmatch('[A-Za-z0-9_]{1,64}',row['id']) is None or row['id'] in seen):
                raise ValueError('d27_genuine_report_row')
            seen.add(row['id'])
            if key=='checks':
                if type(row['ok']) is not bool:raise ValueError('d27_genuine_report_boolean')
            elif (type(row['size_bytes']) is not int or not 0<=row['size_bytes']<=262144
                    or type(row['sha256']) is not str or re.fullmatch('[0-9a-f]{64}',row['sha256']) is None):
                raise ValueError('d27_genuine_report_measurement')
    if d27_genuine_plain_size_v1(report)+1>32768:raise ValueError('d27_genuine_report_bound')
    raw=canonical(report)+b'\n'
    if (len(raw)>32768 or capture['report_bytes']!=len(raw) or capture['report_sha256']!=hashlib.sha256(raw).hexdigest()
            or capture['checks_count']!=len(report['checks']) or capture['measurements_count']!=len(report['measurements'])
            or capture['case_completed'] is not report['completed'] or capture['case_cause']!=report['cause']
            or capture['stdout']['retained_bytes']!=len(raw) or capture['stdout']['prefix_sha256']!=hashlib.sha256(raw).hexdigest()):
        raise ValueError('d27_genuine_report_capture_join')
    return raw


def d27_genuine_failure_metadata_v1(error,route):
    """Preserve exact owned capture/report facts; pre-auth failures stay finite."""
    main=_d27_main_module_v1();phase=vars(main).get('D27PhaseConstructionError')
    if type(route) is not str or route not in ('genuine_initial','genuine_finalizer'):raise ValueError('d27_genuine_failure_route')
    owned=(D27CaseError,D27CompressionError,D27ConstructionError,phase)
    report=None;capture=None;capture_kind=None
    facts={'event':'genuine_failure','route':route,'error_type':type.__getattribute__(type(error),'__name__'),
           'message_size_bytes':None,'message_sha256':None,'message_unavailable':True,
           'capture':None,'capture_available':False,'capture_unavailable_reason':'NO_OWNED_CAPTURE',
           'report_available':False,'report_unavailable_reason':'NOT_VALIDATED',
           'report_size_bytes':None,'report_sha256':None,'physical_acceptance':False,
           'native_activity':'UNKNOWN','descendant_quiescence':'UNKNOWN'}
    if re.fullmatch('[A-Za-z_][A-Za-z0-9_]{0,95}',facts['error_type']) is None:facts['error_type']='Exception'
    if type(error) in owned+(RuntimeError,ValueError,AssertionError,TypeError,OverflowError,TimeoutError):
        args=BaseException.args.__get__(error)
        if type(args) is tuple and len(args)==1 and type(args[0]) is str and len(args[0])<=4096:
            try:
                message=args[0].encode('utf-8');facts.update(message_size_bytes=len(message),message_sha256=hashlib.sha256(message).hexdigest(),message_unavailable=False)
            except UnicodeError:pass
    if type(error) in owned:
        attrs=object.__getattribute__(error,'__dict__');candidate=attrs.get('metadata')
        if candidate is not None:
            extent=d27_genuine_plain_size_v1(candidate)
            if extent>28000:raise ValueError('d27_genuine_owned_capture_bound')
            if type(candidate) is dict and candidate.get('source_kind')=='d27_fixed_genuine_test_v1':
                encoded=d27_genuine_capture_metadata_v1(candidate);capture_kind='genuine'
                if candidate['case']!=route:raise ValueError('d27_genuine_failure_route_join')
            else:
                d27_capture_metadata_v1(candidate);encoded=canonical(candidate);capture_kind='phase'
            if len(encoded)!=extent:raise ValueError('d27_genuine_owned_capture_extent')
            capture=json.loads(encoded);facts.update(capture=capture,capture_available=True,capture_unavailable_reason=None)
        candidate_report=attrs.get('validated_report')
        if candidate_report is not None:
            if capture_kind!='genuine':raise ValueError('d27_genuine_report_capture_absent')
            raw=d27_genuine_report_metadata_v1(candidate_report,capture);report=json.loads(raw)
            facts.update(report_available=True,report_unavailable_reason=None,report_size_bytes=len(raw),report_sha256=hashlib.sha256(raw).hexdigest())
    if d27_genuine_plain_size_v1(facts)+1>30000:raise ValueError('d27_genuine_failure_envelope_bound')
    return report,facts


def d27_genuine_success_records_v1(report,capture):
    d27_genuine_capture_metadata_v1(capture)
    if capture['parent_observed_completion'] is not True:raise ValueError('d27_genuine_complete_transport_required')
    raw=d27_genuine_report_metadata_v1(report,capture)
    facts={'event':'genuine_capture','route':report['case'],'capture':capture,
           'report_available':True,'report_size_bytes':len(raw),'report_sha256':hashlib.sha256(raw).hexdigest(),
           'physical_acceptance':False,'native_activity':'UNKNOWN','descendant_quiescence':'UNKNOWN'}
    if d27_genuine_plain_size_v1(facts)+1>30000:raise ValueError('d27_genuine_capture_envelope_bound')
    encoded=canonical(facts)+b'\n'
    return raw,encoded


def d27_require_positive_geometry_v1():
    """Validate only the fixed actual pure outcome before genuine construction."""
    import ast
    held=globals().get('__d27_held_raw__')
    if type(held) is not bytes or not 0<len(held)<=524288:
        raise RuntimeError('d27_genuine_held_source_absent')
    tree=ast.parse(held)
    classes=[node for node in tree.body if type(node) is ast.ClassDef and node.name=='D27CompleteGeometryTests']
    if len(classes)!=1 or classes[0].decorator_list or len(classes[0].body)!=1:
        raise RuntimeError('d27_genuine_pure_outcome_required')
    method=classes[0].body[0]
    if (type(method) is not ast.FunctionDef or method.name!='test_complete_form_bounds_preserve_hold'
            or method.decorator_list or method.args.defaults or method.args.kw_defaults
            or method.args.vararg or method.args.kwarg or method.args.kwonlyargs
            or [arg.arg for arg in method.args.args]!=['self']):
        raise RuntimeError('d27_genuine_pure_outcome_required')
    literals={}
    for node in method.body:
        if type(node) is ast.Assign and len(node.targets)==1 and type(node.targets[0]) is ast.Name:
            name=node.targets[0].id
            if name in ('fixture_pin','template_sha','admitted','external'):
                if name in literals:raise RuntimeError('d27_genuine_duplicate_outcome_pin')
                try:literals[name]=ast.literal_eval(node.value)
                except (ValueError,TypeError):raise RuntimeError('d27_genuine_literal_outcome_required') from None
    if set(literals)!={'fixture_pin','template_sha','admitted','external'}:
        raise RuntimeError('d27_genuine_pure_outcome_required')
    pin=literals['fixture_pin']
    if (type(pin) is not dict or set(pin)!={'size_bytes','sha256'} or type(pin['size_bytes']) is not int
            or not 0<pin['size_bytes']<=8388608 or type(pin['sha256']) is not str
            or re.fullmatch('[0-9a-f]{64}',pin['sha256']) is None):
        raise RuntimeError('d27_genuine_outcome_pin')
    target=Path(__file__).absolute().parents[1]/'tests/fixtures/gate2/d27-geometry-retained-v1.json'
    with target.open('rb') as handle:raw=handle.read(8388609)
    if len(raw)!=pin['size_bytes'] or hashlib.sha256(raw).hexdigest()!=pin['sha256']:
        raise RuntimeError('d27_genuine_outcome_identity')
    def pairs(rows):
        value={}
        for key,item in rows:
            if key in value:raise ValueError('duplicate')
            value[key]=item
        return value
    value=json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda _:(_ for _ in ()).throw(ValueError('nonfinite')))
    if (type(value) is not dict or set(value)!={'schema_version','kind','originals','development','risk_inputs','source_rows','outcome'}
            or canonical(value)+b'\n'!=raw or value['kind']!='d27_retained_geometry_outcome_v1'
            or type(value['outcome']) is not dict or value['outcome'].get('status')!='ALL_GEOMETRY_TRUE_NOT_READY'):
        raise RuntimeError('d27_genuine_positive_geometry_required')
    expected_source=d27_pure_class_source_v1(literals['fixture_pin'],literals['template_sha'],
                                            literals['admitted'],literals['external'])
    if ast.get_source_segment(held.decode('ascii'),classes[0])!=expected_source.rstrip('\n'):
        raise RuntimeError('d27_genuine_frozen_pure_body')
    main=_d27_main_module_v1()
    main_held=vars(main).get('__d27_held_raw__')
    if type(main_held) is not bytes or not 0<len(main_held)<=524288:
        raise RuntimeError('d27_genuine_held_source_absent')
    for role,current_raw in (('main',main_held),('caller',held)):
        current,_=d27_source_rows_v1(current_raw,role)
        frozen=value['source_rows'][role]
        if (current['excluded_class']!=frozen['excluded_class']
                or [row[:4] for row in current['ordered_rows']]!=[row[:4] for row in frozen['ordered_rows']]):
            raise RuntimeError('d27_genuine_frozen_held_rows')
    selected=vars(D27CompleteGeometryTests).get('test_complete_form_bounds_preserve_hold')
    if (type(selected) is not types.FunctionType or selected.__globals__ is not globals()
            or selected.__module__!=__name__ or Path(selected.__code__.co_filename)!=Path(__file__)):
        raise RuntimeError('d27_genuine_pure_method_identity')
    # This executes the authenticated current ordinary pure validator, never
    # development source/fixture bytes or an outcome-selected program.
    selected(D27CompleteGeometryTests('test_complete_form_bounds_preserve_hold'))
    return {'fixture':pin,'template_sha256':literals['template_sha'],
            'status':'ALL_GEOMETRY_TRUE_NOT_READY','physical_acceptance':False}


def d27_pure_class_source_v1(fixture_pin,template_sha,admitted,external):
    """Author only the fixed pure class after the sole actual outcome is retained."""
    import re
    if (type(fixture_pin) is not dict or set(fixture_pin)!={'size_bytes','sha256'}
            or type(fixture_pin['size_bytes']) is not int or not 0<fixture_pin['size_bytes']<=8388608
            or type(fixture_pin['sha256']) is not str or re.fullmatch('[0-9a-f]{64}',fixture_pin['sha256']) is None
            or type(template_sha) is not str or re.fullmatch('[0-9a-f]{64}',template_sha) is None):
        raise ValueError('d27_pure_authoring_pin')
    if type(admitted) is not dict or set(admitted)!={'entry','main','caller','driver','codec'}:
        raise ValueError('d27_pure_authoring_admission')
    def pin(value,cap):
        if (type(value) is not dict or set(value)!={'size_bytes','sha256'}
                or type(value['size_bytes']) is not int or not 0<value['size_bytes']<=cap
                or type(value['sha256']) is not str or re.fullmatch('[0-9a-f]{64}',value['sha256']) is None):
            raise ValueError('d27_pure_authoring_admission')
    for role in ('entry','main','caller'):pin(admitted[role],524288)
    pin(admitted['driver'],24576)
    if type(admitted['codec']) is not dict or set(admitted['codec'])!={'full','decoder','tail'}:
        raise ValueError('d27_pure_authoring_admission')
    for role in ('full','decoder','tail'):pin(admitted['codec'][role],6907)
    if (type(external) is not dict or set(external)!={'attribution','reference','completed','exit_code','wall_time_seconds'}
            or external['attribution']!='root_observed_tool_result_not_child_self_receipt'
            or type(external['reference']) is not str or not 1<=len(external['reference'])<=192
            or any(ord(c)<32 or ord(c)>126 or ord(c) in (34,92) for c in external['reference'])
            or external['completed'] is not None and type(external['completed']) is not bool
            or external['exit_code'] is not None and (type(external['exit_code']) is not int or not -2147483648<=external['exit_code']<=2147483647)
            or external['wall_time_seconds'] is not None and (type(external['wall_time_seconds']) not in (int,float) or not math.isfinite(external['wall_time_seconds']) or not 0<=external['wall_time_seconds']<=2147483647 or len(canonical(external['wall_time_seconds']))>32)):
        raise ValueError('d27_pure_authoring_external')
    target=Path(__file__).absolute().parents[1]/'tests/fixtures/gate2/d27-geometry-retained-v1.json'
    if not target.is_file():raise RuntimeError('d27_pure_source_requires_actual_retained_outcome')
    with target.open('rb') as handle:raw=handle.read(8388609)
    if len(raw)>8388608 or len(raw)!=fixture_pin['size_bytes'] or hashlib.sha256(raw).hexdigest()!=fixture_pin['sha256']:
        raise RuntimeError('d27_pure_source_requires_actual_retained_outcome')
    head=('class D27CompleteGeometryTests(unittest.TestCase):\n'
          '    def test_complete_form_bounds_preserve_hold(self):\n'
          '        import ast,base64,hashlib,json,math,re\n'
          '        from pathlib import Path\n'
          '        fixture_pin='+repr(fixture_pin)+'\n'
          '        template_sha='+repr(template_sha)+'\n'
          '        admitted='+repr(admitted)+'\n'
          '        external='+repr(external)+'\n'
          '        INPUT_PINS={role:admitted[role] for role in ("main","caller","entry")}\n')
    body = "        FIXTURES = (\n         ('tests/fixtures/accepted_policy_fixture_compiler_component_v1.py',32732,'329fb13f2c6dcee0872e5a29ec1fd769dc6e57ce92ee1076fef6737f1da86d88'),\n         ('tests/fixtures/accepted_policy_fixture_compiler_gate2_resume_v1.py',32739,'5fd7d2d6ee62ff584d2a4662757ca804a3d3300d30bb966319901870c4c85670'),\n         ('tests/fixtures/accepted_policy_fixture_compiler_gate2_c_v1.py',130783,'5a6c4b08ce3d381c355cbf72f93057c991b4adcb9d6ca8c43a638acd64f2ecf9'),\n         ('tests/fixtures/accepted_policy_fixture_compiler_v1.py',103925,'1e40d4786fd03543ac43df7fe0e42a4349d55bad9288ead28f5d2a6ad87bcb03'))\n\n        CLASS_NAME='D27CompleteGeometryTests'\n\n        METHOD_NAME='test_complete_form_bounds_preserve_hold'\n\n        MODULE_PATHS=('tests/test_accepted_policy_fixture_compiler_gate2_dictionary_v1.py','tests/test_accepted_policy_fixture_compiler_gate2_dictionary_caller_v1.py')\n\n        SETUPS=('success','structured_failure','unicode_failure','partial_emission','unknown_closure','setup_refusal')\n\n        LATER=('C1_success','C1_failure','C6_success','C6_failure','D_success','D_failure')\n\n        GROUPS=('c1_success','c1_failure','c6_success','c6_failure','d_success','d_failure')\n\n        RAW_CAPS={'stdout':1048576,'stderr':16384,'parent':32768,'canonical_report':32768}\n\n        B64_CAPS={'stdout':1398104,'stderr':21848,'parent':43692,'canonical_report':43692}\n\n        REASONS=('NOT_EMITTED','CAPTURE_INCOMPLETE','RETENTION_FAILED','NOT_OBSERVED','NOT_CONSTRUCTED','UPSTREAM_UNAVAILABLE','REPORT_UNAVAILABLE','BOUND_REFUSAL','CAUSE_UNKNOWN')\n\n        PARENT_KEYS = frozenset('kind source_pins suite_mode selected_class source_binding_policy source_binding_record_validated held_driver_loader_binding_validated fixed_driver_binding codec_role_binding python deadline_seconds elapsed_before_report_write_s returncode forced_test_child timed_out channels threads_joined io_failure ordered_causes test_child_command_chars child_work_seconds child_total_seconds work_deadline cleanup_deadline child_total_deadline child_completion_observed_at child_completion_before_total_end child_completion_before_cleanup_end protocol_error_type parent_observed_test_transport_complete test_summary geometry_source_kind geometry_fully_measured geometry_risk_passed source_execution_reopens_paths generated_operational_program_execution descendant_quiescence self_report_persistence_or_whole_process_attested'.split())\n\n        def require(ok,cause):\n         if not ok: raise AssertionError(cause)\n\n        def canonical(value):\n         return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode('ascii')\n\n        def sha(raw): return hashlib.sha256(raw).hexdigest()\n\n        def samekeys(value,keys):\n         require(type(value) is dict and set(value)==set(keys),'closed_keys')\n\n        def integer(value,lo,hi):\n         require(type(value) is int and lo<=value<=hi,'integer')\n\n        def hex64(value):\n         require(type(value) is str and re.fullmatch('[0-9a-f]{64}',value) is not None,'hex64')\n\n        def identifier(value):\n         require(type(value) is str and re.fullmatch('[A-Za-z_][A-Za-z0-9_]{0,127}',value) is not None,'name')\n\n        def ids(values,cap):\n         require(type(values) is list and len(values)<=cap and len(set(values))==len(values),'ids')\n         require(all(type(v) is str and re.fullmatch('[A-Za-z0-9_]{1,64}',v) for v in values),'id')\n\n        def pin(value,cap,zero=False):\n         samekeys(value,('size_bytes','sha256'));integer(value['size_bytes'],0 if zero else 1,cap);hex64(value['sha256'])\n\n        def bytes_pin(raw):\n         require(type(raw) is bytes,'bytes');return {'size_bytes':len(raw),'sha256':sha(raw)}\n\n        def checked_b64(text,size,digest,cap,encoded_cap,zero=False):\n         integer(size,0 if zero else 1,cap);hex64(digest)\n         require(type(text) is str and len(text)<=encoded_cap and len(text)==4*((size+2)//3),'b64_size')\n         require(text.isascii() and re.fullmatch('[A-Za-z0-9+/]*={0,2}',text) is not None,'b64_alphabet')\n         try: raw=base64.b64decode(text,validate=True)\n         except Exception: raise AssertionError('b64_decode') from None\n         require(len(raw)==size and sha(raw)==digest and base64.b64encode(raw).decode('ascii')==text,'b64_binding')\n         return raw\n\n        def duplicate_pairs(items):\n         value={}\n         for key,item in items:\n          require(key not in value,'duplicate_key');value[key]=item\n         return value\n\n        def load_json(raw,lf=True):\n         require(type(raw) is bytes and raw.isascii() and not raw.startswith(b'\\xef\\xbb\\xbf'),'json_ascii')\n         if lf:require(raw.endswith(b'\\n') and not raw.endswith(b'\\n\\n'),'json_lf');body=raw[:-1]\n         else:body=raw\n         try:value=json.loads(body,object_pairs_hook=duplicate_pairs,parse_constant=lambda unused: (_ for _ in ()).throw(AssertionError('nonfinite')))\n         except Exception:raise AssertionError('json_parse') from None\n         require(canonical(value)==body,'json_canonical')\n         return value\n\n        def declared(node):\n         if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)):return [node.name]\n         if isinstance(node,ast.Import):return [item.asname or item.name.split('.')[0] for item in node.names]\n         if isinstance(node,ast.ImportFrom):return [item.asname or item.name for item in node.names]\n         if isinstance(node,(ast.Assign,ast.AnnAssign)):\n          targets=node.targets if isinstance(node,ast.Assign) else [node.target]\n          return sorted({item.id for target in targets for item in ast.walk(target) if isinstance(item,ast.Name) and isinstance(item.ctx,ast.Store)})\n         return []\n\n        def segment(text,node):\n         require(not getattr(node,'decorator_list',[]),'top_decorator')\n         value=ast.get_source_segment(text,node);require(type(value) is str,'source_segment')\n         return value.encode('utf-8')\n\n        def class_shape(node):\n         require(type(node) is ast.ClassDef and node.name==CLASS_NAME and not node.decorator_list and not node.keywords and not getattr(node,'type_params',[]) and len(node.bases)==1,'class_shape')\n         base=node.bases[0]\n         require(type(base) is ast.Attribute and type(base.value) is ast.Name and base.value.id=='unittest' and base.attr=='TestCase','class_base')\n         require(len(node.body)==1 and type(node.body[0]) is ast.FunctionDef and node.body[0].name==METHOD_NAME,'class_method')\n         method=node.body[0]\n         require(not method.decorator_list and not getattr(method,'type_params',[]) and not method.args.defaults and not method.args.kw_defaults,'method_modifiers')\n         require(len(method.args.args)==1 and method.args.args[0].arg=='self' and not method.args.posonlyargs and not method.args.kwonlyargs and method.args.vararg is None and method.args.kwarg is None and method.returns is None and method.args.args[0].annotation is None,'method_signature')\n         return method\n\n        def source_rows(raw,owner):\n         require(type(raw) is bytes and 0<len(raw)<=524288 and b'\\r' not in raw,'source_size')\n         text=raw.decode('utf-8');tree=ast.parse(text)\n         rows=[];found=[]\n         for node in tree.body:\n          if type(node) is ast.ClassDef and node.name==CLASS_NAME:\n           require(owner=='caller','only_caller_exclusion');class_shape(node);found.append(node);continue\n          kind=type(node).__name__;require(kind in ('Expr','Import','ImportFrom','Assign','AnnAssign','FunctionDef','AsyncFunctionDef','ClassDef','Assert','If'),'node_kind')\n          names=declared(node);require(len(names)<=16 and len(set(names))==len(names),'bindings')\n          for name in names:identifier(name)\n          data=segment(text,node);integer(len(data),1,524288)\n          rows.append([kind,names,len(data),sha(data),sha(ast.dump(node,include_attributes=False).encode('utf-8'))])\n         require(len(found)==(1 if owner=='caller' else 0) and 1<=len(rows)<=256,'source_exclusion_count')\n         return {'excluded_class':CLASS_NAME if owner=='caller' else None,'ordered_rows':rows,'ordered_rows_sha256':sha(canonical(rows))},(text,found)\n\n        def inventory():\n         checks=['source_bindings','initial_source_bound','finalizer_source_bound','executor_source_bound','six_setup_forms']\n         measures=['initial_source','finalizer_source','executor_source']\n         for form in SETUPS:\n          checks += [form+s for s in ('_setup','_provider_pipes','_pipe0_inverse','_pipe1_inverse','_pipe2_inverse','_selected_original_bound','_observed_original_bound','_selected_wire_bound','_observed_wire_bound','_full_roundtrip','_uint64','_writer_pipe0_inverse','_writer_pipe1_inverse','_ack_bound','_writer_stdout_bound','_writer_input_bound','_forms_bound','_chain_join','_root_bound','_chain_bound')]\n          measures += [form+s for s in ('_selected_original','_observed_original','_selected_wire','_observed_wire','_ack','_writer_stdout','_root','_chain')]\n         checks += ['approval_slots','six_later_forms','later_measured_upstream']\n         groups=[]\n         for group,form in zip(GROUPS,LATER):\n          groups.append({'id':group,'check_ids':[form+s for s in ('_later','_pipe_limits','_pipe0_inverse','_pipe1_inverse','_selected_bound','_native_input_bound','_uint64','_writer_pipe0_inverse','_writer_pipe1_inverse','_ack_bound','_writer_stdout_bound','_writer_forms_bound','_writer_input_bound')],\n           'measurement_ids':[form+s for s in ('_selected','_native_input','_ack','_writer_stdout')]})\n         value={'always':{'check_ids':checks,'measurement_ids':measures},'conditional':groups,\n         'diagnostic':{'check_ids':[f+'_wire_geometry' for f in SETUPS],'measurement_ids':[f+'_wire_refusal' for f in SETUPS]}}\n         validate_inventory(value)\n         return value\n\n        def validate_inventory(value):\n         samekeys(value,('always','conditional','diagnostic'))\n         require(type(value['conditional']) is list and len(value['conditional'])==6,'group_count')\n         all_c=[];all_m=[]\n         for key in ('always','diagnostic'):\n          row=value[key];samekeys(row,('check_ids','measurement_ids'));ids(row['check_ids'],512);ids(row['measurement_ids'],128)\n          all_c+=row['check_ids'];all_m+=row['measurement_ids']\n         for group,row in zip(GROUPS,value['conditional']):\n          samekeys(row,('id','check_ids','measurement_ids'));require(row['id']==group,'group_identity')\n          ids(row['check_ids'],512);ids(row['measurement_ids'],128);all_c+=row['check_ids'];all_m+=row['measurement_ids']\n         ids(all_c,512);ids(all_m,128)\n\n        def validate_development(value):\n         samekeys(value,('owner_role','class_name','method_name','class_source','method'))\n         require((value['owner_role'],value['class_name'],value['method_name'])==('caller',CLASS_NAME,METHOD_NAME),'development_identity')\n         row=value['class_source'];samekeys(row,('size_bytes','sha256','bytes_base64'))\n         raw=checked_b64(row['bytes_base64'],row['size_bytes'],row['sha256'],524288,699052)\n         text=raw.decode('utf-8');tree=ast.parse(text)\n         require(len(tree.body)==1,'development_ast');method=class_shape(tree.body[0])\n         selected=segment(text,method);span=value['method'];samekeys(span,('start_byte','end_byte','size_bytes','sha256'))\n         integer(span['start_byte'],0,len(raw)-1);integer(span['end_byte'],1,len(raw));pin({'size_bytes':span['size_bytes'],'sha256':span['sha256']},524288)\n         require(span['end_byte']-span['start_byte']==span['size_bytes'] and raw[span['start_byte']:span['end_byte']]==selected and sha(selected)==span['sha256'],'development_method_binding')\n\n        def validate_source_rows(value):\n         samekeys(value,('main','caller','fixtures'))\n         for role in ('main','caller'):\n          row=value[role];samekeys(row,('excluded_class','ordered_rows','ordered_rows_sha256'))\n          require(row['excluded_class']==(CLASS_NAME if role=='caller' else None),'excluded_class')\n          rows=row['ordered_rows'];require(type(rows) is list and 1<=len(rows)<=256,'row_count')\n          for item in rows:\n           require(type(item) is list and len(item)==5 and item[0] in ('Expr','Import','ImportFrom','Assign','AnnAssign','FunctionDef','AsyncFunctionDef','ClassDef','Assert','If'),'node_tuple')\n           require(type(item[1]) is list and len(item[1])<=16 and len(set(item[1]))==len(item[1]),'binding_count')\n           for name in item[1]:identifier(name)\n           integer(item[2],1,524288);hex64(item[3])\n           if item[4] is not None:hex64(item[4])\n          hex64(row['ordered_rows_sha256']);require(sha(canonical(rows))==row['ordered_rows_sha256'],'rows_hash')\n         require(type(value['fixtures']) is list and len(value['fixtures'])==4,'fixtures_count')\n         for actual,expected in zip(value['fixtures'],FIXTURES):\n          samekeys(actual,('path','size_bytes','sha256'));require(actual==dict(zip(('path','size_bytes','sha256'),expected)),'fixture_pin')\n\n        def compare_sources(expected,main,caller,fixtures):\n         validate_source_rows(expected)\n         for role,raw in (('main',main),('caller',caller)):\n          current,_=source_rows(raw,role)\n          require(current['excluded_class']==expected[role]['excluded_class'] and len(current['ordered_rows'])==len(expected[role]['ordered_rows']),'protected_row_count')\n          require([r[:4] for r in current['ordered_rows']]==[r[:4] for r in expected[role]['ordered_rows']],'protected_source_changed')\n         tree=ast.parse(main.decode('utf-8'))\n         literals={}\n         for node in tree.body:\n          if type(node) is ast.Assign and len(node.targets)==1 and type(node.targets[0]) is ast.Name and node.targets[0].id in ('D27_WIRE_CODEC','ROOT_ENCODER','ROOT_SHA256','D27_GEOMETRY_MODEL','D27_GEOMETRY_STDIO'):\n           require(node.targets[0].id not in literals,'duplicate_role_literal')\n           literals[node.targets[0].id]=ast.literal_eval(node.value)\n         require(len(literals)==5 and all(type(v) is str and v.isascii() for v in literals.values()),'role_literals')\n         codec=literals['D27_WIRE_CODEC'];marker='function gate2WireEncode(text,tag,sha,canon,guard){'\n         require(codec.count(marker)==1,'role_encoder_boundary');at=codec.index(marker)\n         for role,part in (('full',codec),('decoder',codec[:at]),('tail',codec[at:])):\n          require(bytes_pin(part.encode('ascii'))==admitted['codec'][role],'actual_codec_partition')\n         require(bytes_pin(codec[:949].encode('ascii'))=={'size_bytes':949,'sha256':'d15dca0b287943b37e43143397e8c753f6bca0170862d3d924ca15e01965cd7b'},'actual_primitives')\n         digest=hashlib.sha256();extent=0\n         for index,key in enumerate(('ROOT_ENCODER','ROOT_SHA256','D27_WIRE_CODEC','D27_GEOMETRY_MODEL','D27_GEOMETRY_STDIO')):\n          if index:digest.update(b'\\n');extent+=1\n          part=literals[key].encode('ascii');digest.update(part);extent+=len(part)\n         require({'size_bytes':extent,'sha256':digest.hexdigest()}==admitted['driver'],'actual_fixed_TEST_driver')\n         require(type(fixtures) in (tuple,list) and len(fixtures)==4,'fixture_buffers')\n         for raw,(_,size,digest) in zip(fixtures,FIXTURES):require(type(raw) is bytes and len(raw)==size and sha(raw)==digest,'formatter_source_changed')\n\n        def observed_pin(value):\n         samekeys(value,('available','size_bytes','sha256','unavailable_reason'));require(type(value['available']) is bool,'observed_available')\n         if value['available']:\n          pin({'size_bytes':value['size_bytes'],'sha256':value['sha256']},9007199254740991);require(value['unavailable_reason'] is None,'observed_reason')\n         else:require(value['size_bytes'] is None and value['sha256'] is None and value['unavailable_reason'] in ('NOT_CONSTRUCTED','CAPTURE_INCOMPLETE','NOT_OBSERVED','CAUSE_UNKNOWN'),'observed_absent')\n\n        def validate_risk(value,admitted):\n         samekeys(value,('entry','main','caller','driver','codec','initial','finalizer','executor','template_sha256'))\n         for role in ('entry','main','caller'):pin(value[role],524288);require(value[role]==admitted[role],'admitted_input')\n         pin(value['driver'],24576);require(value['driver']==admitted['driver'],'admitted_driver')\n         samekeys(value['codec'],('full','decoder','tail'))\n         for role in ('full','decoder','tail'):pin(value['codec'][role],6907);require(value['codec'][role]==admitted['codec'][role],'admitted_codec')\n         require(value['codec']['full']['size_bytes']==value['codec']['decoder']['size_bytes']+value['codec']['tail']['size_bytes'],'codec_extent')\n         for role in ('initial','finalizer','executor'):observed_pin(value[role])\n         hex64(value['template_sha256'])\n\n        def validate_external(value,expected):\n         samekeys(value,('attribution','reference','completed','exit_code','wall_time_seconds'))\n         require(value['attribution']=='root_observed_tool_result_not_child_self_receipt','external_attribution')\n         ref=value['reference'];require(type(ref) is str and 1<=len(ref)<=192 and all(32<=ord(c)<=126 and c not in '\\x22\\x5c' for c in ref),'external_reference')\n         require(value['completed'] is None or type(value['completed']) is bool,'external_completed')\n         if value['exit_code'] is not None:integer(value['exit_code'],-2147483648,2147483647)\n         wall=value['wall_time_seconds']\n         require(wall is None or type(wall) in (int,float) and math.isfinite(wall) and 0<=wall<=2147483647 and len(canonical(wall))<=32,'external_wall')\n         require(value==expected,'external_observation_changed')\n\n        def validate_report(value):\n         samekeys(value,('schema_version','case','node_version','completed','cause','checks','measurements'))\n         require(type(value['schema_version']) is int and value['schema_version']==1 and value['case']=='geometry' and value['node_version']=='25.2.1' and type(value['completed']) is bool,'report_identity')\n         require(value['cause'] in (None,'d27_codec_absent','d27_driver_assertion','d27_driver_input','d27_driver_error','d27_node_version','d27_geometry_hold'),'report_cause')\n         require(type(value['checks']) is list and len(value['checks'])<=512 and type(value['measurements']) is list and len(value['measurements'])<=128,'report_counts')\n         for row in value['checks']:samekeys(row,('id','ok'));require(type(row['ok']) is bool,'check_boolean')\n         for row in value['measurements']:samekeys(row,('id','size_bytes','sha256'));integer(row['size_bytes'],0,262144);hex64(row['sha256'])\n         ids([r['id'] for r in value['checks']],512);ids([r['id'] for r in value['measurements']],128)\n         require(len(canonical(value))+1<=32768,'report_bound')\n         return {r['id']:r['ok'] for r in value['checks']},{r['id']:r for r in value['measurements']}\n\n        def membership(report,inv):\n         validate_inventory(inv)\n         checks,measures=validate_report(report) if report is not None else ({},{})\n         allowed_c=set(inv['always']['check_ids']+inv['diagnostic']['check_ids']);allowed_m=set(inv['always']['measurement_ids']+inv['diagnostic']['measurement_ids'])\n         for row in inv['conditional']:allowed_c.update(row['check_ids']);allowed_m.update(row['measurement_ids'])\n         require(set(checks)<=allowed_c and set(measures)<=allowed_m,'undeclared_report_id')\n         missing_c=[x for x in inv['always']['check_ids'] if x not in checks];missing_m=[x for x in inv['always']['measurement_ids'] if x not in measures]\n         groups=[]\n         for group,form in zip(inv['conditional'],LATER):\n          selected=measures.get(form+'_selected')\n          known=report is not None and checks.get('later_measured_upstream') is True and selected is not None\n          if not known:\n           expected_c=group['check_ids'];expected_m=group['measurement_ids'];coverage='UNAVAILABLE';reason='REPORT_UNAVAILABLE' if report is None else 'UPSTREAM_UNAVAILABLE' if checks.get('later_measured_upstream') is not True else 'CAUSE_UNKNOWN'\n          else:\n           use_writer=selected['size_bytes']<=4096\n           expected_c=group['check_ids'] if use_writer else group['check_ids'][:6]\n           expected_m=group['measurement_ids'] if use_writer else group['measurement_ids'][:2]\n           omitted_c=set(group['check_ids'])-set(expected_c);omitted_m=set(group['measurement_ids'])-set(expected_m)\n           require(not omitted_c.intersection(checks) and not omitted_m.intersection(measures),'inapplicable_writer_present')\n           complete=all(x in checks for x in expected_c) and all(x in measures for x in expected_m)\n           coverage='COMPLETE_APPLICABLE' if complete else 'PARTIAL';reason=None if complete else 'CAPTURE_INCOMPLETE'\n          groups.append({'id':group['id'],'coverage':coverage,'missing_check_ids':[x for x in expected_c if x not in checks],'missing_measurement_ids':[x for x in expected_m if x not in measures],'unavailable_reason':reason})\n         return missing_c,missing_m,groups\n\n        def original_protocol(stdout,stderr,parent,admitted):\n         import base64,math\n         def canon(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode('ascii')\n         CAPTURE_KEYS=set('caller_deadline case case_cause case_completed causes checks_count child_completion_observed_before_deadline child_total_deadline child_total_limit_seconds child_work_limit_seconds cleanup_deadline cleanup_limit_seconds command_options data_bytes data_only data_sha256 descendant_quiescence elapsed_seconds environment_keys final_reserve_seconds finished_before_deadline input_bytes input_sha256 kill_requested measurements_count node_executable node_version parent_observed_completion pid program_sha256 reaped report_bytes report_sha256 returncode schema_version spawned started_monotonic stderr stdin_bytes stdin_closed stdin_complete stdin_extent_unknown stdin_write_attempted stdin_write_in_flight stdout threads_joined threads_started timed_out work_deadline'.split())\n         PIPE_KEYS=set('observed_bytes retained_bytes eof overflow io_error closed unknown_remainder prefix_sha256'.split())\n         COMP_KEYS=(CAPTURE_KEYS-set('case case_cause case_completed data_bytes data_sha256 report_bytes report_sha256 checks_count measurements_count'.split()))|set('quality roundtrip packed_bytes packed_sha256 stderr_prefix_b64'.split())\n         CAPTURE_KEYS|={'source_kind','driver_role','driver_getter','program_bytes'}\n         INITIAL_KEYS=set('kind source_bytes source_sha256 escaped_source_bytes baseline_bytes baseline_sha256 original_builder_bytes original_builder_sha256 baseline_body_bytes baseline_body_sha256 prefix_bytes prefix_sha256 decoder_bytes decoder_sha256 canonical_data_bytes canonical_data_sha256 compressed_data_bytes compressed_data_sha256 base64_data_bytes base64_data_sha256 data_fields strings_field_absent deferred_definition_bytes deferred_definition_sha256 exact_decoder_inverse exact_phase_inverse exact_inverse_source source_contribution_fits source_only_over_cap_by complete_geometry_qualified behavior_conformance_complete finalizer_implemented generated_operational_program_executed generated_full_subject_files_written status task_2_10_complete compression'.split())\n         FINAL_KEYS=set('initial_size_bytes initial_sha256 finalizer_size_bytes finalizer_sha256 factory_size_bytes factory_sha256 wrapper_prefix_size_bytes wrapper_suffix_size_bytes python_head_size_bytes python_head_sha256 python_tail_size_bytes python_tail_sha256 python_common_size_bytes python_common_sha256 generated_operational_program_execution generated_full_subject_files_written'.split())\n         ROLE_KEYS=set('kind full_codec_bytes full_codec_sha256 node_codec_bytes node_codec_sha256 excluded_encoder_bytes excluded_encoder_sha256 marker_occurrences role_is_exact_prefix encoder_excluded'.split())\n         SOURCE_KEYS=set('kind driver initial node_codec finalizer executor input_data_size_bytes input_data_sha256 modeled_setup_form_count modeled_later_form_count controlled_synthetic_geometry_only independent_actual_acquisition_proven generated_operational_program_execution generated_full_subject_files_written behavior_conformance_complete physical_acceptance'.split())\n         FAIL_KEYS=set('kind error_type message_size_bytes message_sha256 capture capture_metadata_unavailable capture_metadata_size_bytes capture_metadata_sha256 generated_operational_program_execution generated_full_subject_files_written physical_acceptance'.split())\n         SAFE_KEYS=CAPTURE_KEYS|COMP_KEYS|PIPE_KEYS|INITIAL_KEYS|FINAL_KEYS|ROLE_KEYS|SOURCE_KEYS|FAIL_KEYS|{'size_bytes','sha256'}\n         require(stdout is None or type(stdout) is bytes and len(stdout)<=1048576,'original_stdout_bound')\n         require(stderr is None or type(stderr) is bytes and len(stderr)<=16384,'original_stderr_bound')\n         ROLE_EXPECTED=None;FIXED_DRIVER=None\n         def pairs(rows):\n          value={}\n          for key,item in rows:\n           if key in value:raise AssertionError('d27_test_metadata_duplicate')\n           value[key]=item\n          return value\n\n         def sha_text(value):return type(value) is str and re.fullmatch('[0-9a-f]{64}',value) is not None\n         def bounded(value):\n          todo=[('',value)];nodes=0\n          while todo:\n           key,item=todo.pop();nodes+=1\n           if nodes>4096:raise ValueError('d27_metadata_nodes')\n           if type(item) is dict:\n            if any(type(k) is not str or k not in SAFE_KEYS for k in item):raise ValueError('d27_metadata_key')\n            todo.extend(item.items())\n           elif type(item) is list:\n            if len(item)>128:raise ValueError('d27_metadata_list')\n            todo.extend((key,v) for v in item)\n           elif type(item) is str:\n            if key=='stderr_prefix_b64':\n             if len(item)>21848 or re.fullmatch('[A-Za-z0-9+/]*={0,2}',item) is None:raise ValueError('d27_metadata_stderr')\n             b=base64.b64decode(item,validate=True)\n             if len(b)>16384 or base64.b64encode(b).decode('ascii')!=item:raise ValueError('d27_metadata_stderr')\n            elif len(item)>256 or not item.isascii() or any(ord(c)<32 or ord(c)>126 for c in item):raise ValueError('d27_metadata_string')\n            if key.endswith('sha256') and not sha_text(item):raise ValueError('d27_metadata_sha256')\n           elif type(item) is float:\n            if not math.isfinite(item):raise ValueError('d27_metadata_number')\n           elif type(item) is int:\n            if not -(2**64)<=item<=2**64:raise ValueError('d27_metadata_integer')\n           elif item is not None and type(item) is not bool:raise ValueError('d27_metadata_type')\n          return value\n         def capture_metadata(value):\n             if type(value) is not dict:raise ValueError('d27_capture_shape')\n             compression='quality' in value\n             allowed=COMP_KEYS if compression else CAPTURE_KEYS\n             if not set(value)<=allowed:raise ValueError('d27_capture_keys')\n             bounded(value)\n             def want(ok):\n                 if not ok:raise ValueError('d27_capture_correspondence')\n             def number(item):return type(item) in (int,float) and math.isfinite(item) and item>=0\n             def integer(item,lo=0,hi=9007199254740991):return type(item) is int and lo<=item<=hi\n             want(type(value.get('schema_version')) is int and value['schema_version']==1)\n             bools=('data_only','spawned','timed_out','kill_requested','stdin_closed','stdin_complete',\n                    'stdin_extent_unknown','stdin_write_attempted','stdin_write_in_flight','reaped',\n                    'threads_joined','parent_observed_completion','finished_before_deadline',\n                    'child_completion_observed_before_deadline')\n             for key in bools:\n                 if key in value:want(type(value[key]) is bool)\n             want(value.get('data_only') is True and value.get('descendant_quiescence')=='UNKNOWN')\n             for key in ('pid','returncode'):\n                 if key in value and value[key] is not None:\n                     want(integer(value[key],1,2147483647) if key=='pid' else integer(value[key],-2147483648,2147483647))\n             for key in ('stdin_bytes','input_bytes','data_bytes','report_bytes','checks_count','measurements_count','packed_bytes','program_bytes'):\n                 if key in value and value[key] is not None:want(integer(value[key]))\n             if 'threads_started' in value:want(integer(value['threads_started'],0,3))\n             for key in ('program_sha256','input_sha256','data_sha256','report_sha256','packed_sha256'):\n                 if key in value and value[key] is not None:want(sha_text(value[key]))\n             for key in ('started_monotonic','elapsed_seconds','caller_deadline','work_deadline','child_total_deadline','cleanup_deadline'):\n                 if key in value and value[key] is not None:want(number(value[key]))\n             for key,expected in (('child_total_limit_seconds',30),('child_work_limit_seconds',27),('cleanup_limit_seconds',3),('final_reserve_seconds',5)):\n                 if key in value:want(type(value[key]) is int and value[key]==expected)\n             if 'node_version' in value and value['node_version'] is not None:\n                 want(type(value['node_version']) is str and re.fullmatch('[0-9]{1,8}\\\\.[0-9]{1,8}\\\\.[0-9]{1,8}',value['node_version']) is not None)\n             want(type(value.get('causes')) is list and len(value['causes'])<=128\n                  and all(type(v) is str and v.isascii() and 1<=len(v)<=128 and all(32<=ord(c)<=126 for c in v) for v in value['causes'])\n                  and len(set(value['causes']))==len(value['causes']))\n             for key in ('environment_keys','command_options'):\n                 if key in value:want(type(value[key]) is list and len(value[key])<=16 and all(type(v) is str and v.isascii() and len(v)<=256 for v in value[key]))\n             if 'node_executable' in value:want(type(value['node_executable']) is str and 0<len(value['node_executable'])<=256)\n             if compression:\n                 want(type(value['quality']) is int and value['quality']==11 and type(value.get('roundtrip')) is bool)\n             else:\n                 want(value.get('source_kind')=='d27_fixed_test_driver_v1')\n                 if value.get('case') is not None:want(value['case']=='geometry')\n                 if value.get('driver_role') is not None:want(value['driver_role']=='geometry')\n                 if value.get('driver_getter') is not None:want(value['driver_getter']=='d27_geometry_driver_v1')\n                 if value.get('case_completed') is not None:want(type(value['case_completed']) is bool)\n                 if value.get('case_cause') is not None:want(value['case_cause'] in ('d27_codec_absent','d27_driver_assertion','d27_driver_input','d27_driver_error','d27_node_version','d27_geometry_hold'))\n                 if value.get('program_bytes') is not None:want(0<value['program_bytes']<=24576)\n             for name,cap in (('stdout',1048576),('stderr',16384)):\n                 channel=value.get(name);want(type(channel) is dict and set(channel)==PIPE_KEYS)\n                 for key in ('eof','overflow','closed','unknown_remainder'):want(type(channel[key]) is bool)\n                 want(integer(channel['observed_bytes']) and integer(channel['retained_bytes'],0,cap)\n                      and channel['observed_bytes']>=channel['retained_bytes'] and sha_text(channel['prefix_sha256']))\n                 want(channel['io_error'] is None or type(channel['io_error']) is str and re.fullmatch('[A-Za-z_][A-Za-z0-9_]{0,127}',channel['io_error']) is not None)\n                 want(channel['unknown_remainder'] is (not channel['eof'] or channel['overflow'] or channel['io_error'] is not None))\n             if value.get('parent_observed_completion') is True:\n                 want(integer(value.get('pid'),1) and integer(value.get('input_bytes'),1,262144)\n                      and sha_text(value.get('input_sha256')) and sha_text(value.get('program_sha256')))\n                 want(set(value)==allowed and value.get('node_version')=='25.2.1'\n                      and type(value.get('returncode')) is int and value['returncode']==0 and value['causes']==[])\n                 for key in ('spawned','reaped','threads_joined','stdin_complete','stdin_closed','stdin_write_attempted',\n                             'finished_before_deadline','child_completion_observed_before_deadline'):want(value[key] is True)\n                 for key in ('timed_out','kill_requested','stdin_extent_unknown','stdin_write_in_flight'):want(value[key] is False)\n                 want(value['threads_started']==3 and value['command_options']==['--max-old-space-size=256','--input-type=commonjs','-e'])\n                 want(value['environment_keys'] in (['PATH'],['PATH','SystemRoot']))\n                 for key in ('started_monotonic','elapsed_seconds','caller_deadline','work_deadline','child_total_deadline','cleanup_deadline'):want(number(value[key]))\n                 start=value['started_monotonic'];end=value['caller_deadline'];work=min(start+27,end-8);total=min(start+30,end-5);observed=start+value['elapsed_seconds']\n                 want(value['work_deadline']==work and value['child_total_deadline']==total\n                      and value['cleanup_deadline']<=min(total,work+3)\n                      and observed<end and observed<total and observed<value['cleanup_deadline'])\n                 want(value['stdin_bytes']==value['input_bytes'])\n                 for channel in (value['stdout'],value['stderr']):\n                     want(channel['eof'] is True and channel['closed'] is True and channel['overflow'] is False\n                          and channel['io_error'] is None and channel['unknown_remainder'] is False\n                          and channel['observed_bytes']==channel['retained_bytes'])\n                 want(value['stderr']['retained_bytes']==0 and value['stderr']['prefix_sha256']=='e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855')\n                 if compression:\n                     want(value['roundtrip'] is True and value['stderr_prefix_b64']==''\n                          and integer(value.get('packed_bytes'),1,32768) and sha_text(value.get('packed_sha256')))\n                 else:\n                     want(type(value['case_completed']) is bool and value['case']=='geometry' and value['node_version']=='25.2.1'\n                          and integer(value.get('program_bytes'),1,24576) and integer(value.get('data_bytes'),0,262144)\n                          and sha_text(value.get('data_sha256')) and integer(value.get('report_bytes'),1,32768)\n                          and sha_text(value.get('report_sha256')) and integer(value.get('checks_count'),0,512)\n                          and integer(value.get('measurements_count'),0,128))\n             return value\n         def driver_metadata(value):\n          if type(value) is not dict or set(value)!={'source_kind','driver_role','driver_getter','program_bytes','program_sha256'} or value['source_kind']!='d27_fixed_test_driver_v1' or value['driver_role']!='geometry' or value['driver_getter']!='d27_geometry_driver_v1' or type(value['program_bytes']) is not int or not 0<value['program_bytes']<=24576 or not sha_text(value['program_sha256']):raise ValueError('d27_driver_binding')\n          return value\n         def role_metadata(value):\n          if type(value) is not dict or set(value)!=ROLE_KEYS or value['kind']!='d27_node_codec_role_v1' or value['marker_occurrences']!=1 or type(value['marker_occurrences']) is not int or value['role_is_exact_prefix'] is not True or value['encoder_excluded'] is not True:raise ValueError('d27_role_shape')\n          for name in ('full_codec_bytes','node_codec_bytes','excluded_encoder_bytes'):\n           if type(value[name]) is not int or not 0<value[name]<=6907 or not sha_text(value[name.replace('_bytes','_sha256')]):raise ValueError('d27_role_pin')\n          if value['node_codec_bytes']+value['excluded_encoder_bytes']!=value['full_codec_bytes'] or value['full_codec_sha256'] in ('56708c18c942acfb6e8153971a0013ca79c955e4182efff590ad7ae3a2ba2432','c65b73fe0e7d274040dda413b7871ee83c4c952f9bb2c1e74962b0e3e5f34767'):raise ValueError('d27_role_extent_or_legacy')\n          return value\n         def source_metadata(value):\n          if type(value) is not dict:raise ValueError('d27_source_shape')\n          if value.get('kind')=='d27_construction_failure_metadata_v1':\n           if set(value)!=FAIL_KEYS or type(value['error_type']) is not str or not re.fullmatch('[A-Za-z_][A-Za-z0-9_]{0,95}',value['error_type']) or type(value['message_size_bytes']) is not int or value['message_size_bytes']<0 or not sha_text(value['message_sha256']):raise ValueError('d27_construction_shape')\n           if type(value['capture_metadata_unavailable']) is not bool or not (value['capture_metadata_size_bytes'] is None and value['capture_metadata_sha256'] is None) and (type(value['capture_metadata_size_bytes']) is not int or value['capture_metadata_size_bytes']<0 or not sha_text(value['capture_metadata_sha256'])):raise ValueError('d27_construction_capture')\n           if value['capture'] is not None:\n            capture_metadata(value['capture']);encoded=canon(value['capture'])\n            if value['capture_metadata_unavailable'] or len(encoded)>30000 or len(encoded)!=value['capture_metadata_size_bytes'] or hashlib.sha256(encoded).hexdigest()!=value['capture_metadata_sha256']:raise ValueError('d27_construction_capture')\n           elif value['capture_metadata_unavailable'] is not True:raise ValueError('d27_construction_unavailable')\n           for name in ('generated_operational_program_execution','generated_full_subject_files_written','physical_acceptance'):\n            if value[name] is not False:raise ValueError('d27_construction_authority')\n           return bounded(value)\n          if set(value)!=SOURCE_KEYS or value.get('kind')!='d27_inert_source_construction_metadata_v1':raise ValueError('d27_source_shape')\n          initial=value['initial'];final=value['finalizer'];executor=value['executor']\n          if type(initial) is not dict or set(initial)!=INITIAL_KEYS or initial['kind']!='d24_initial_source_only_v1' or type(final) is not dict or set(final)!=FINAL_KEYS or type(executor) is not dict or set(executor)!={'size_bytes','sha256'}:raise ValueError('d27_source_nested')\n          if (initial['source_bytes'],initial['source_sha256'],initial['canonical_data_bytes'],initial['canonical_data_sha256'],initial['compressed_data_bytes'],initial['compressed_data_sha256'])!=(14162,'4032a534147aada87931734f3b06cde67988d62c75851b959945399843a3770d',6566,'8ca48e37f97d03af660960f75afab79db162e8f8997f39f6c1c5c55dd896c97e',2365,'a7caf17aa8d2d5d6beb60880d415e7328947d188623bf5fa0d1ad566e1fd2f2f'):raise ValueError('d27_initial_expected_recipe')\n          driver_metadata(value['driver'])\n          if FIXED_DRIVER is None or value['driver']!=FIXED_DRIVER:raise ValueError('d27_source_driver_join')\n          if initial['prefix_bytes']!=295 or initial['prefix_sha256']!='ea63175835e2149d61c71d52696c62033d17b908f76ca0a20cf25e32b18f142b' or type(initial['data_fields']) is not int or initial['data_fields']!=9 or initial['strings_field_absent'] is not True:raise ValueError('d27_source_initial')\n          if any(initial[name] is not True for name in ('exact_decoder_inverse','exact_phase_inverse','exact_inverse_source')):raise ValueError('d27_source_initial_inverse')\n          escaped=initial['escaped_source_bytes'];fits=initial['source_contribution_fits'];over=initial['source_only_over_cap_by']\n          if type(escaped) is not int or escaped<=0 or type(fits) is not bool or fits is not (escaped<=12288) or type(over) is not int or over!=max(0,escaped-12288) or initial['status']!=('UNQUALIFIED_SOURCE_ONLY' if fits else 'HOLD_SOURCE_CONTRIBUTION_OVER_CAP'):raise ValueError('d27_source_initial_state')\n          if initial['baseline_bytes']!=initial['prefix_bytes']+initial['decoder_bytes']+initial['baseline_body_bytes'] or not 0<initial['canonical_data_bytes']<=16384 or initial['base64_data_bytes']!=4*((initial['compressed_data_bytes']+2)//3):raise ValueError('d27_source_data_extent')\n          role=value['node_codec']\n          if type(role) is not dict or set(role)!=ROLE_KEYS or role['kind']!='d27_node_codec_role_v1' or type(role['marker_occurrences']) is not int or role['marker_occurrences']!=1 or role['role_is_exact_prefix'] is not True or role['encoder_excluded'] is not True:raise ValueError('d27_node_role_shape')\n          role_metadata(role)\n          if ROLE_EXPECTED is None or role!=ROLE_EXPECTED:raise ValueError('d27_node_role_binding')\n          for name in ('complete_geometry_qualified','behavior_conformance_complete','finalizer_implemented','generated_operational_program_executed','generated_full_subject_files_written','task_2_10_complete'):\n           if initial[name] is not False:raise ValueError('d27_source_initial_authority')\n          compression=capture_metadata(initial['compression'])\n          if compression.get('parent_observed_completion') is not True or compression.get('returncode')!=0 or compression.get('causes') or compression.get('quality')!=11 or compression.get('roundtrip') is not True:raise ValueError('d27_source_compression')\n          for name in ('data_only','finished_before_deadline','child_completion_observed_before_deadline','reaped','threads_joined','stdin_complete','stdin_closed'):\n           if compression.get(name) is not True:raise ValueError('d27_source_compression_completion')\n          for name in ('timed_out','kill_requested','stdin_extent_unknown'):\n           if compression.get(name) is not False:raise ValueError('d27_source_compression_unknown')\n          if compression['started_monotonic']+compression['elapsed_seconds']>=compression['cleanup_deadline']:raise ValueError('d27_source_compression_cleanup')\n          for channel in (compression['stdout'],compression['stderr']):\n           if channel['eof'] is not True or channel['closed'] is not True or channel['overflow'] is not False or channel['io_error'] is not None or channel['unknown_remainder'] is not False:raise ValueError('d27_source_compression_pipe')\n          if compression.get('input_bytes')!=initial['canonical_data_bytes'] or compression.get('input_sha256')!=initial['canonical_data_sha256'] or compression.get('stdin_bytes')!=initial['canonical_data_bytes'] or compression.get('packed_bytes')!=initial['compressed_data_bytes'] or compression.get('packed_sha256')!=initial['compressed_data_sha256']:raise ValueError('d27_source_compression_data_join')\n          for name in ('generated_operational_program_execution','generated_full_subject_files_written'):\n           if final[name] is not False:raise ValueError('d27_finalizer_authority')\n          if final['initial_size_bytes']!=initial['source_bytes'] or final['initial_sha256']!=initial['source_sha256'] or final['factory_size_bytes']!=13073 or final['factory_sha256']!='997579f8ffcc50d6e05ae859dd9164b1dc08ce5a71e82a1d8070633c3cdf3677':raise ValueError('d27_finalizer_binding')\n          for record in (initial,final,role):\n           for name,item in record.items():\n            if name.endswith('_sha256') and not sha_text(item):raise ValueError('d27_source_hash_kind')\n            if name.endswith('_bytes') and (type(item) is not int or item<=0):raise ValueError('d27_source_size_kind')\n          if value['modeled_setup_form_count']!=6 or value['modeled_later_form_count']!=6 or value['controlled_synthetic_geometry_only'] is not True:raise ValueError('d27_source_counts')\n          for name in ('independent_actual_acquisition_proven','generated_operational_program_execution','generated_full_subject_files_written','behavior_conformance_complete','physical_acceptance'):\n           if value[name] is not False:raise ValueError('d27_source_authority')\n          for item in (executor,{'size_bytes':value['input_data_size_bytes'],'sha256':value['input_data_sha256']},{'size_bytes':final['finalizer_size_bytes'],'sha256':final['finalizer_sha256']}):\n           if type(item['size_bytes']) is not int or not 0<item['size_bytes']<=9007199254740991 or not sha_text(item['sha256']):raise ValueError('d27_source_pin')\n          return bounded(value)\n         def metadata(value):\n          if type(value) is not dict or set(value)!={'case','report','capture'} or value['case']!='geometry':raise ValueError('d27_case_shape')\n          report=value['report'];capture=value['capture']\n          if type(report) is not dict or set(report)!={'schema_version','case','node_version','completed','cause','checks','measurements'} or type(report['schema_version']) is not int or report['schema_version']!=1 or report['case']!='geometry' or report['node_version']!='25.2.1' or type(report['completed']) is not bool:raise ValueError('d27_case_identity')\n          if report['cause'] not in (None,'d27_geometry_hold','d27_codec_absent','d27_driver_assertion','d27_driver_input','d27_node_version','d27_driver_error'):raise ValueError('d27_case_cause')\n          if type(report['checks']) is not list or len(report['checks'])>512 or type(report['measurements']) is not list or len(report['measurements'])>128:raise ValueError('d27_case_rows')\n          for row in report['checks']:\n           if type(row) is not dict or set(row)!={'id','ok'} or type(row['id']) is not str or not re.fullmatch('[A-Za-z0-9_]{1,64}',row['id']) or type(row['ok']) is not bool:raise ValueError('d27_case_check')\n          for row in report['measurements']:\n           if type(row) is not dict or set(row)!={'id','size_bytes','sha256'} or type(row['id']) is not str or not re.fullmatch('[A-Za-z0-9_]{1,64}',row['id']) or type(row['size_bytes']) is not int or not 0<=row['size_bytes']<=262144 or not sha_text(row['sha256']):raise ValueError('d27_case_measurement')\n          capture_metadata(capture)\n          if capture.get('case')!='geometry':raise ValueError('d27_case_capture')\n          if set(capture)!=CAPTURE_KEYS or capture.get('source_kind')!='d27_fixed_test_driver_v1' or FIXED_DRIVER is None or {key:capture.get(key) for key in FIXED_DRIVER}!=FIXED_DRIVER:raise ValueError('d27_case_driver_join')\n          for key in ('checks_count','measurements_count','report_bytes','input_bytes','data_bytes','stdin_bytes','program_bytes'):\n           if type(capture.get(key)) is not int or capture[key]<0:raise ValueError('d27_case_counter')\n          return value\n         def exception_capture(error):\n          value=getattr(error,'metadata',None);encoded=None;result={'capture':None,'capture_metadata_unavailable':True,'capture_metadata_size_bytes':None,'capture_metadata_sha256':None}\n          try:\n           encoded=canon(value);result.update(capture_metadata_size_bytes=len(encoded),capture_metadata_sha256=hashlib.sha256(encoded).hexdigest())\n           if value is not None and len(encoded)<=30000:capture_metadata(value);result.update(capture=value,capture_metadata_unavailable=False)\n          except BaseException:pass\n          return result\n         def validate_exception_capture(value):\n          if type(value) is not dict or set(value)!={'capture','capture_metadata_unavailable','capture_metadata_size_bytes','capture_metadata_sha256'} or type(value['capture_metadata_unavailable']) is not bool:raise ValueError('d27_exception_capture')\n          n=value['capture_metadata_size_bytes'];h=value['capture_metadata_sha256']\n          if not (n is None and h is None) and (type(n) is not int or n<0 or not sha_text(h)):raise ValueError('d27_exception_capture_pin')\n          if value['capture'] is not None:\n           capture_metadata(value['capture']);raw=canon(value['capture'])\n           if value['capture_metadata_unavailable'] or len(raw)>30000 or n!=len(raw) or h!=hashlib.sha256(raw).hexdigest():raise ValueError('d27_exception_capture_binding')\n          elif value['capture_metadata_unavailable'] is not True:raise ValueError('d27_exception_capture_unavailable')\n          return value\n         def geometry_evidence(source,case,collection_only=False):\n          if source.get('kind')!='d27_inert_source_construction_metadata_v1' or case is None:return False,False\n          report=case['report'];capture=case['capture'];checks={r['id']:r['ok'] for r in report['checks']};measurements={r['id']:r for r in report['measurements']}\n          if not checks or len(checks)!=len(report['checks']) or len(measurements)!=len(report['measurements']) or capture.get('parent_observed_completion') is not True:return False,False\n          if capture.get('data_bytes')!=source['input_data_size_bytes'] or capture.get('data_sha256')!=source['input_data_sha256'] or capture.get('input_bytes')!=source['input_data_size_bytes']+27:return False,False\n          report_bytes=canon(report)+b'\\n'\n          if capture.get('report_bytes')!=len(report_bytes) or capture.get('report_sha256')!=hashlib.sha256(report_bytes).hexdigest() or capture.get('checks_count')!=len(report['checks']) or capture.get('measurements_count')!=len(report['measurements']) or capture.get('case_completed') is not report['completed'] or capture.get('case_cause')!=report['cause']:return False,False\n          for name in ('data_only','spawned','finished_before_deadline','child_completion_observed_before_deadline','reaped','threads_joined','stdin_complete','stdin_closed'):\n           if capture.get(name) is not True:return False,False\n          for name in ('timed_out','kill_requested','stdin_extent_unknown','stdin_write_in_flight'):\n           if capture.get(name) is not False:return False,False\n          if capture.get('causes') or type(capture.get('returncode')) is not int or capture['returncode']!=0 or capture.get('descendant_quiescence')!='UNKNOWN' or capture.get('stdin_bytes')!=capture.get('input_bytes'):return False,False\n          for name in ('stdout','stderr'):\n           channel=capture[name]\n           if channel['eof'] is not True or channel['closed'] is not True or channel['overflow'] is not False or channel['io_error'] is not None or channel['unknown_remainder'] is not False:return False,False\n          if capture['stdout']['retained_bytes']!=len(report_bytes) or capture['stdout']['prefix_sha256']!=hashlib.sha256(report_bytes).hexdigest() or capture['stderr']['retained_bytes']!=0:return False,False\n          caps={};required={'source_bindings','six_setup_forms','six_later_forms','approval_slots','later_measured_upstream'}\n          for name in ('initial_source','finalizer_source','executor_source'):caps[name]=262144\n          for prefix in ('success','structured_failure','unicode_failure','partial_emission','unknown_closure','setup_refusal'):\n           for suffix,cap in (('selected_original',32768),('observed_original',32768),('selected_wire',12288),('observed_wire',12288),('ack',24576),('writer_stdout',2112),('root',65536),('chain',262144)):caps[prefix+'_'+suffix]=cap\n           required.update(prefix+suffix for suffix in ('_setup','_provider_pipes','_pipe0_inverse','_pipe1_inverse','_pipe2_inverse','_full_roundtrip','_uint64','_writer_pipe0_inverse','_writer_pipe1_inverse','_chain_join'))\n          for stage in ('C1_success','C1_failure','C6_success','C6_failure','D_success','D_failure'):\n           selected=stage+'_selected';caps[selected]=4096;caps[stage+'_native_input']=32768\n           required.update(stage+suffix for suffix in ('_later','_pipe_limits','_pipe0_inverse','_pipe1_inverse'))\n           if selected not in measurements:return False,False\n           if measurements[selected]['size_bytes']<=4096:\n            caps[stage+'_ack']=16384;caps[stage+'_writer_stdout']=2112\n            required.update(stage+suffix for suffix in ('_uint64','_writer_pipe0_inverse','_writer_pipe1_inverse'))\n          if set(measurements)!=set(caps):return False,False\n          for name,cap in caps.items():\n           require(measurements[name]['size_bytes']>0,'geometry_positive_measurement')\n           if name+'_bound' not in checks:return False,False\n           require(checks[name+'_bound'] is (measurements[name]['size_bytes']<=cap),'geometry_bound_correspondence')\n          required.update(name+'_bound' for name in caps)\n          for prefix in ('success','structured_failure','unicode_failure','partial_emission','unknown_closure','setup_refusal'):\n           wire=measurements[prefix+'_selected_wire']['size_bytes'];q=((wire+4095)//4096)*4096\n           expected={prefix+'_writer_input_bound':measurements[prefix+'_ack']['size_bytes']+65471<=90112,prefix+'_forms_bound':max(12288,q)+q+8192<=32768}\n           for name,ok in expected.items():\n            if name not in checks:return False,False\n            require(checks[name] is ok,'geometry_allocation_correspondence')\n           required.update(expected)\n          for stage in ('C1_success','C1_failure','C6_success','C6_failure','D_success','D_failure'):\n           if measurements[stage+'_selected']['size_bytes']<=4096:\n            wire=measurements[stage+'_selected']['size_bytes'];q=((wire+4095)//4096)*4096\n            expected={stage+'_writer_input_bound':measurements[stage+'_ack']['size_bytes']+65471<=81920,stage+'_writer_forms_bound':max(4096,q)+q+8192<=16384}\n            for name,ok in expected.items():\n             if name not in checks:return False,False\n             require(checks[name] is ok,'geometry_allocation_correspondence')\n            required.update(expected)\n          if set(checks)!=required:return False,False\n          for name,n,h in (('initial_source',source['initial']['source_bytes'],source['initial']['source_sha256']),('finalizer_source',source['finalizer']['finalizer_size_bytes'],source['finalizer']['finalizer_sha256']),('executor_source',source['executor']['size_bytes'],source['executor']['sha256'])):\n           if measurements[name]['size_bytes']!=n or measurements[name]['sha256']!=h:return False,False\n          require(all(ok or name.endswith('_bound') for name,ok in checks.items()),'geometry_complete_nonbound_failure')\n          require(report['completed'] is all(checks.values()) and report['cause']==(None if all(checks.values()) else 'd27_geometry_hold'),'geometry_complete_report_status')\n          if collection_only:return True,False\n          return True,report['completed']\n         ROLE_EXPECTED={'kind':'d27_node_codec_role_v1','full_codec_bytes':admitted['codec']['full']['size_bytes'],'full_codec_sha256':admitted['codec']['full']['sha256'],'node_codec_bytes':admitted['codec']['decoder']['size_bytes'],'node_codec_sha256':admitted['codec']['decoder']['sha256'],'excluded_encoder_bytes':admitted['codec']['tail']['size_bytes'],'excluded_encoder_sha256':admitted['codec']['tail']['sha256'],'marker_occurrences':1,'role_is_exact_prefix':True,'encoder_excluded':True}\n         FIXED_DRIVER={'source_kind':'d27_fixed_test_driver_v1','driver_role':'geometry','driver_getter':'d27_geometry_driver_v1','program_bytes':admitted['driver']['size_bytes'],'program_sha256':admitted['driver']['sha256']}\n         pins=[{'path':path,**admitted[role]} for path,role in zip(MODULE_PATHS,('main','caller'))]\n         expected_id='tests.test_accepted_policy_fixture_compiler_gate2_dictionary_caller_v1.D27CompleteGeometryTests.test_complete_form_bounds_preserve_hold'\n         wire_events=('source_bindings','test_started','test_terminal','subtest_issue','parent_issue','test_summary','entry_failure')\n         error_fields={'error_type','message_size_bytes','message_sha256','exception_capture'}\n         binding_fields=set('event sources both_buffers_verified_before_either_compile held_driver_loader_bound held_driver_module execution_reopens_test_paths held_driver_aliases_bound held_caller_aliases_bound codec_role fixed_driver'.split())\n         summary_fields=set('event selected_class tests_run expected_metadata_records geometry_source_records geometry_case_records successes failures errors skips expected_failures unexpected_successes issue_events subtest_callbacks parent_outcomes successful test_streams generated_operational_program_execution descendant_quiescence'.split())\n         stream_fields=set('observed_bytes sha256 metadata_records geometry_source_records geometry_case_records unexpected_or_unterminated raw_values_retained'.split())\n         def count(value):require(type(value) is int and 0<=value<=1048576,'protocol_counter')\n         def error_facts(row):\n             require(type(row['error_type']) is str and re.fullmatch('[A-Za-z_][A-Za-z0-9_]{0,95}',row['error_type']) is not None,'protocol_error_type')\n             if 'message_unavailable' in row:\n                 require(row['message_unavailable'] is True and row['message_size_bytes'] is None and row['message_sha256'] is None,'protocol_unavailable_message')\n             else:integer(row['message_size_bytes'],0,9007199254740991);hex64(row['message_sha256'])\n             if 'exception_capture' in row:validate_exception_capture(row['exception_capture'])\n         def event_shape(row):\n             require(type(row) is dict and row.get('event') in wire_events,'protocol_event')\n             event=row['event'];optional={'message_unavailable'} if 'message_unavailable' in row else set()\n             if event=='source_bindings':\n                 samekeys(row,binding_fields)\n                 require(row['sources']==pins and row['both_buffers_verified_before_either_compile'] is True and row['held_driver_loader_bound'] is True and row['held_driver_module']=='tests.test_accepted_policy_fixture_compiler_gate2_dictionary_v1' and row['execution_reopens_test_paths'] is False and row['held_driver_aliases_bound'] is True and row['held_caller_aliases_bound'] is True,'protocol_binding')\n                 require(role_metadata(row['codec_role'])==ROLE_EXPECTED and driver_metadata(row['fixed_driver'])==FIXED_DRIVER,'protocol_role_binding')\n             elif event=='test_started':samekeys(row,('event','test_id'));require(row['test_id']==expected_id,'protocol_test_id')\n             elif event in ('subtest_issue','parent_issue'):\n                 samekeys(row,{'event','test_id','issue_index','subtest_ordinal','outcome'}|error_fields|optional)\n                 require(row['test_id']==expected_id and row['outcome'] in ('failure','error','expected_failure'),'protocol_issue_identity')\n                 integer(row['issue_index'],1,512);error_facts(row)\n                 if event=='subtest_issue':integer(row['subtest_ordinal'],1,512);require(row['outcome'] in ('failure','error'),'protocol_subtest_outcome')\n                 else:require(row['subtest_ordinal'] is None,'protocol_parent_ordinal')\n             elif event=='test_terminal':\n                 base={'event','test_id','subtest_callbacks','issue_counts','outcome'}\n                 require(row['outcome'] in ('success','failure','error','skip','expected_failure','unexpected_success'),'protocol_terminal_outcome')\n                 samekeys(row,base|error_fields|optional if row['outcome'] in ('failure','error','expected_failure') else base)\n                 require(row['test_id']==expected_id,'protocol_terminal_identity');integer(row['subtest_callbacks'],0,512)\n                 samekeys(row['issue_counts'],('subtest_issue','parent_issue'))\n                 for value in row['issue_counts'].values():integer(value,0,512)\n                 if row['outcome'] in ('failure','error','expected_failure'):error_facts(row)\n             elif event=='entry_failure':\n                 samekeys(row,{'event','error_type','message_size_bytes','message_sha256','secondary'}|optional);error_facts(row)\n                 require(type(row['secondary']) is list and len(row['secondary'])<=128 and all(type(v) is str and re.fullmatch('[A-Za-z_][A-Za-z0-9_]{0,95}',v) for v in row['secondary']),'protocol_entry_secondary')\n             else:\n                 samekeys(row,summary_fields)\n                 require(row['selected_class']==CLASS_NAME and type(row['successful']) is bool and row['generated_operational_program_execution'] is False and row['descendant_quiescence']=='UNKNOWN','protocol_summary_identity')\n                 for key in ('tests_run','expected_metadata_records','geometry_source_records','geometry_case_records','successes','failures','errors','skips','expected_failures','unexpected_successes','issue_events','subtest_callbacks'):count(row[key])\n                 outcomes=row['parent_outcomes']\n                 require(type(outcomes) is dict and set(outcomes)<=set(('success','failure','error','skip','expected_failure','unexpected_success')),'protocol_parent_outcomes')\n                 for value in outcomes.values():integer(value,1,512)\n                 samekeys(row['test_streams'],('stdout','stderr'))\n                 for stream in row['test_streams'].values():\n                     samekeys(stream,stream_fields);integer(stream['observed_bytes'],0,9007199254740991);hex64(stream['sha256'])\n                     for key in ('metadata_records','geometry_source_records','geometry_case_records'):count(stream[key])\n                     require(type(stream['unexpected_or_unterminated']) is bool and stream['raw_values_retained'] is False,'protocol_stream_flags')\n         rows=[];incomplete=type(stdout) is not bytes or type(stderr) is not bytes or bool(stderr)\n         if type(stdout) is bytes:\n             for line in stdout.splitlines(keepends=True):\n                 if len(line)>32768 or not line.endswith(b'\\n') or not line.isascii():incomplete=True;continue\n                 tagged=None;payload=line[:-1]\n                 for prefix,event in ((b'D27_GEOMETRY_SOURCE_METADATA ','source_metadata'),(b'D27_CASE_METADATA ','case_metadata')):\n                     if payload.startswith(prefix):tagged=event;payload=payload[len(prefix):];break\n                 try:value=json.loads(payload,object_pairs_hook=pairs,parse_constant=lambda unused: (_ for _ in ()).throw(AssertionError('protocol_nonfinite')))\n                 except (json.JSONDecodeError,UnicodeError):incomplete=True;continue\n                 require(canon(value)==payload,'protocol_canonical_record')\n                 if tagged is not None:\n                     try:value={'event':tagged,'data':source_metadata(value) if tagged=='source_metadata' else metadata(value)}\n                     except (ValueError,TypeError,KeyError):raise AssertionError('contradictory_tagged_metadata') from None\n                 elif type(value) is dict and value.get('event') in ('source_metadata','case_metadata'):\n                     raise AssertionError('untagged_metadata_impersonation')\n                 elif type(value) is not dict or value.get('event') not in wire_events:incomplete=True;continue\n                 else:\n                     try:event_shape(value)\n                     except (ValueError,TypeError,KeyError):raise AssertionError('contradictory_protocol_record') from None\n                 rows.append(value)\n         sources=[row['data'] for row in rows if row['event']=='source_metadata']\n         cases=[row['data'] for row in rows if row['event']=='case_metadata']\n         summaries=[row for row in rows if row['event']=='test_summary']\n         bindings=[row for row in rows if row['event']=='source_bindings']\n         starts=[row for row in rows if row['event']=='test_started'];terminals=[row for row in rows if row['event']=='test_terminal']\n         require(len(sources)<=1 and len(cases)<=1 and len(summaries)<=1 and len(bindings)<=1 and len(starts)<=1 and len(terminals)<=1,'duplicate_protocol_record')\n         if bindings:require(rows[0] is bindings[0],'protocol_binding_order')\n         active=False;issues=[];last_subtest=0\n         for index,row in enumerate(rows):\n             event=row['event']\n             if event=='test_started':require(not active,'protocol_start_order');active=True\n             elif event in ('source_metadata','case_metadata'):\n                 require(active,'protocol_metadata_parent')\n                 if event=='case_metadata':require(sources and any(v['event']=='source_metadata' for v in rows[:index]),'protocol_metadata_order')\n             elif event in ('subtest_issue','parent_issue'):\n                 require(active and row['issue_index']==len(issues)+1,'protocol_issue_order')\n                 if event=='subtest_issue':require(last_subtest<row['subtest_ordinal'],'protocol_subtest_order');last_subtest=row['subtest_ordinal']\n                 issues.append(row)\n             elif event=='test_terminal':\n                 require(active,'protocol_terminal_order');active=False\n                 require(row['subtest_callbacks']>=last_subtest and row['issue_counts']=={name:sum(v['event']==name for v in issues) for name in ('subtest_issue','parent_issue')},'protocol_terminal_counts')\n                 selected=next((v for kind in ('error','failure','expected_failure') for v in issues if v['outcome']==kind),None)\n                 if selected is not None:\n                     require(row['outcome']==selected['outcome'],'protocol_issue_precedence')\n                     for key in error_fields|{'message_unavailable'}:require(row.get(key)==selected.get(key),'protocol_terminal_error_join')\n                 else:require(row['outcome'] in ('success','skip','unexpected_success'),'protocol_terminal_issue_absent')\n             elif event=='test_summary':require(index==len(rows)-1,'protocol_summary_order')\n         if sources and sources[0]['kind']=='d27_construction_failure_metadata_v1':require(not cases,'protocol_failed_construction_case')\n         if cases:\n             report=cases[0]['report'];capture=cases[0]['capture'];validate_report(report)\n             known=canon(report)+b'\\n'\n             require(capture['report_bytes']==len(known) and capture['report_sha256']==sha(known) and capture['stdout']['retained_bytes']==len(known) and capture['stdout']['prefix_sha256']==sha(known) and capture['checks_count']==len(report['checks']) and capture['measurements_count']==len(report['measurements']) and capture['case_completed'] is report['completed'] and capture['case_cause']==report['cause'],'protocol_report_capture_join')\n             if sources and sources[0]['kind']=='d27_inert_source_construction_metadata_v1':\n                 source=sources[0]\n                 require(capture['data_bytes']==source['input_data_size_bytes'] and capture['data_sha256']==source['input_data_sha256'] and capture['input_bytes']==source['input_data_size_bytes']+27,'protocol_input_join')\n                 measurements={v['id']:v for v in report['measurements']}\n                 for name,n,h in (('initial_source',source['initial']['source_bytes'],source['initial']['source_sha256']),('finalizer_source',source['finalizer']['finalizer_size_bytes'],source['finalizer']['finalizer_sha256']),('executor_source',source['executor']['size_bytes'],source['executor']['sha256'])):\n                     if name in measurements:require(measurements[name]['size_bytes']==n and measurements[name]['sha256']==h,'protocol_observed_source_join')\n         if summaries:\n             summary=summaries[0];counts={name:sum(row['outcome']==name for row in terminals) for name in ('success','failure','error','skip','expected_failure','unexpected_success')}\n             require(summary['tests_run']==len(starts)==len(terminals) and not active and summary['parent_outcomes']=={name:n for name,n in counts.items() if n},'protocol_summary_terminals')\n             expected={'successes':counts['success'],'failures':sum(v['outcome']=='failure' for v in issues),'errors':sum(v['outcome']=='error' for v in issues),'skips':counts['skip'],'expected_failures':sum(v['outcome']=='expected_failure' for v in issues),'unexpected_successes':counts['unexpected_success'],'issue_events':len(issues),'subtest_callbacks':sum(v['subtest_callbacks'] for v in terminals),'expected_metadata_records':2,'geometry_source_records':len(sources),'geometry_case_records':len(cases)}\n             require(all(summary[key]==value for key,value in expected.items()),'protocol_summary_counts')\n             out=summary['test_streams']['stdout'];err=summary['test_streams']['stderr']\n             require(out['metadata_records']==len(sources)+len(cases) and out['geometry_source_records']==len(sources) and out['geometry_case_records']==len(cases) and all(err[k]==0 for k in ('metadata_records','geometry_source_records','geometry_case_records')),'protocol_stream_counts')\n             # The D27 producer rejects every nonmetadata write, including blank LFs.\n             forwarded=b''.join((b'D27_GEOMETRY_SOURCE_METADATA ' if row['event']=='source_metadata' else b'D27_CASE_METADATA ')+canon(row['data'])+b'\\n' for row in rows if row['event'] in ('source_metadata','case_metadata'))\n             if out['unexpected_or_unterminated'] is False:require(out['observed_bytes']==len(forwarded) and out['sha256']==sha(forwarded),'protocol_forwarded_stream_join')\n             if err['observed_bytes']==0:require(err['sha256']==sha(b''),'protocol_empty_stderr_sha')\n             green=(counts['success']==1 and not issues and not any(counts[name] for name in ('failure','error','skip','expected_failure','unexpected_success')) and len(sources)==len(cases)==1 and sources[0]['kind']=='d27_inert_source_construction_metadata_v1' and out['metadata_records']==2 and out['unexpected_or_unterminated'] is False and err['unexpected_or_unterminated'] is False and err['observed_bytes']==0)\n             require(summary['successful'] is green,'protocol_summary_success')\n         else:summary=None;green=False\n         complete=(not incomplete and len(bindings)==len(starts)==len(terminals)==len(summaries)==1 and len(sources)==1 and not any(row['event'] in ('entry_failure','fixture_terminal') for row in rows))\n         source=sources[0] if sources else None;case=cases[0] if cases else None\n         if parent is not None:\n             for helper in ([source['initial']['compression']] if source and source['kind']=='d27_inert_source_construction_metadata_v1' else [])+([case['capture']] if case else []):\n                 if helper.get('parent_observed_completion') is True:require(helper['caller_deadline']==parent['work_deadline'],'protocol_parent_helper_clock')\n             require(parent['protocol_error_type']==(None if complete else 'd27_protocol_incomplete'),'original_protocol_contradiction')\n             if complete:\n                 require(type(parent['returncode']) is int and parent['returncode']==(0 if green else 1),'protocol_child_status')\n                 require(parent['fixed_driver_binding']==FIXED_DRIVER and parent['codec_role_binding']==ROLE_EXPECTED,'protocol_parent_roles')\n         if not complete:return source,case,None,False,False,False\n         full,passed=geometry_evidence(source,case) if source else (False,False)\n         collected=geometry_evidence(source,case,True)[0] if source else False\n         return source,case,summary,full,passed,collected\n\n        def validate_fixture(value,template_sha,admitted,external,main,caller,fixtures):\n         def normal_capture(capture,parent,compression=False):\n          if capture.get('parent_observed_completion') is not True:return\n          require(capture['caller_deadline']==parent['work_deadline'],'capture_parent_clock')\n          for key,expected in (('child_total_limit_seconds',30),('child_work_limit_seconds',27),('cleanup_limit_seconds',3),('final_reserve_seconds',5),('threads_started',3)):\n           require(type(capture[key]) is int and capture[key]==expected,'capture_fixed_limits')\n          require(capture['stdin_write_in_flight'] is False,'capture_pending_stdin')\n          for key in ('started_monotonic','elapsed_seconds','caller_deadline','work_deadline','child_total_deadline','cleanup_deadline'):\n           require(type(capture[key]) in (int,float) and math.isfinite(capture[key]) and capture[key]>=0,'capture_clock_scalar')\n          start=capture['started_monotonic'];end=capture['caller_deadline'];work=min(start+27,end-8);total=min(start+30,end-5);cleanup=capture['cleanup_deadline'];observed=start+capture['elapsed_seconds']\n          require(capture['work_deadline']==work and capture['child_total_deadline']==total and cleanup<=min(total,work+3) and observed<end and observed<total and observed<cleanup,'capture_deadline_join')\n          for name in ('stdout','stderr'):require(capture[name]['observed_bytes']==capture[name]['retained_bytes'],'capture_channel_extent')\n          require(capture['stderr']['retained_bytes']==0 and capture['stderr']['observed_bytes']==0 and capture['stderr']['prefix_sha256']=='e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855','capture_stderr_empty')\n          if compression:require(capture['node_version']=='25.2.1','compression_node_version')\n         samekeys(value,('schema_version','kind','originals','development','risk_inputs','source_rows','outcome'))\n         require(type(value['schema_version']) is int and value['schema_version']==1 and value['kind']=='d27_retained_geometry_outcome_v1','fixture_identity')\n         validate_development(value['development']);validate_source_rows(value['source_rows']);validate_risk(value['risk_inputs'],admitted)\n         outcome=value['outcome'];samekeys(outcome,('status','parent_transport_complete','inventory','missing_check_ids','missing_measurement_ids','conditional_groups','unknowns','external_observation'))\n         require(outcome['status'] in ('INCOMPLETE_HOLD','COMPLETE_HOLD','ALL_GEOMETRY_TRUE_NOT_READY') and (outcome['parent_transport_complete'] is None or type(outcome['parent_transport_complete']) is bool),'outcome_status')\n         validate_inventory(outcome['inventory']);require(outcome['inventory']==inventory(),'inventory_changed')\n         template={'schema_version':1,'kind':'d27_retention_template_v1','development':value['development'],'source_rows':value['source_rows'],'inventory':outcome['inventory']}\n         hex64(template_sha);require(sha(canonical(template))==template_sha==value['risk_inputs']['template_sha256'],'external_template_binding')\n         compare_sources(value['source_rows'],main,caller,fixtures)\n         validate_external(outcome['external_observation'],external)\n         samekeys(outcome['unknowns'],('descendant_quiescence','native_activity','native_closure','namespace'));require(all(v=='UNKNOWN' for v in outcome['unknowns'].values()),'unknowns')\n         samekeys(value['originals'],RAW_CAPS);originals={}\n         for name,cap in RAW_CAPS.items():\n          row=value['originals'][name];samekeys(row,('name','available','size_bytes','sha256','bytes_base64','unavailable_reason'))\n          require(row['name']==name and type(row['available']) is bool,'original_identity')\n          if row['available']:\n           require(row['unavailable_reason'] is None,'available_original_reason')\n           originals[name]=checked_b64(row['bytes_base64'],row['size_bytes'],row['sha256'],cap,B64_CAPS[name],True)\n          else:\n           require(all(row[k] is None for k in ('size_bytes','sha256','bytes_base64')) and row['unavailable_reason'] in ('NOT_EMITTED','CAPTURE_INCOMPLETE','RETENTION_FAILED','NOT_OBSERVED','CAUSE_UNKNOWN'),'unavailable_original')\n           originals[name]=None\n         report=None\n         if originals['canonical_report'] is not None:report=load_json(originals['canonical_report']);validate_report(report)\n         parent=None;source=None;case=None;summary=None;measured=passed=collected=False\n         source,case,_,_,_,_=original_protocol(originals['stdout'],originals['stderr'],None,admitted)\n         if originals['parent'] is not None:\n          try:parent_candidate=load_json(originals['parent'])\n          except AssertionError:parent_candidate=None\n          if parent_candidate is not None:\n           require(type(parent_candidate) is dict and parent_candidate.get('kind')=='d27_local_inert_geometry_test_parent_observation_v1','parent_protocol_identity')\n           parent=parent_candidate;samekeys(parent,PARENT_KEYS)\n           require(parent['source_pins']==[{'path':p,**admitted[r]} for p,r in zip(MODULE_PATHS,('main','caller'))] and parent['suite_mode']=='geometry' and parent['selected_class']==CLASS_NAME,'parent_source_binding')\n           require(type(parent['parent_observed_test_transport_complete']) is bool,'parent_transport_type')\n           for key in ('source_binding_record_validated','held_driver_loader_binding_validated','forced_test_child','timed_out','threads_joined','io_failure','child_completion_before_total_end','child_completion_before_cleanup_end','parent_observed_test_transport_complete','geometry_fully_measured','geometry_risk_passed','source_execution_reopens_paths','generated_operational_program_execution','self_report_persistence_or_whole_process_attested'):\n            require(type(parent[key]) is bool,'parent_boolean')\n           require(parent['python']=='3.14.7','parent_python')\n           require(parent['source_binding_policy']=='both_held_test_buffers_before_either_compile' and parent['source_execution_reopens_paths'] is False and parent['generated_operational_program_execution'] is False and parent['self_report_persistence_or_whole_process_attested'] is False and parent['descendant_quiescence']=='UNKNOWN','parent_scope')\n           require(parent['source_binding_record_validated'] is (parent['protocol_error_type'] is None) and parent['held_driver_loader_binding_validated'] is (parent['protocol_error_type'] is None),'parent_binding_flags')\n           require(parent['deadline_seconds']==300 and type(parent['deadline_seconds']) is int and parent['child_work_seconds']==27 and type(parent['child_work_seconds']) is int and parent['child_total_seconds']==30 and type(parent['child_total_seconds']) is int,'parent_limits')\n           integer(parent['test_child_command_chars'],1,32767)\n           for key in ('work_deadline','cleanup_deadline','child_total_deadline','elapsed_before_report_write_s'):\n            require(type(parent[key]) in (int,float) and math.isfinite(parent[key]) and parent[key]>=0,'parent_clock')\n           observed=parent['child_completion_observed_at']\n           require(observed is None or type(observed) in (int,float) and math.isfinite(observed) and observed>=0,'parent_observation_clock')\n           require(parent['child_completion_before_total_end'] is (observed is not None and observed<parent['child_total_deadline']) and parent['child_completion_before_cleanup_end'] is (observed is not None and observed<parent['cleanup_deadline']),'parent_observation_cutoff')\n           require(type(parent['ordered_causes']) is list and len(parent['ordered_causes'])<=128 and len(set(parent['ordered_causes']))==len(parent['ordered_causes']) and all(type(c) is str and c.isascii() and len(c)<=128 for c in parent['ordered_causes']),'parent_causes')\n           require(parent['io_failure'] is bool(parent['ordered_causes']),'parent_cause_failure_join')\n           require(parent['work_deadline']==parent['child_total_deadline']-3 and parent['cleanup_deadline']<=parent['child_total_deadline'],'parent_deadline_extent')\n           samekeys(parent['channels'],('stdout','stderr'))\n           for name in ('stdout','stderr'):\n            channel=parent['channels'][name]\n            samekeys(channel,('eof','overflow','error','secondary','closed','close_attempted','observed_bytes','size_bytes','sha256','remainder_unknown','closure_unknown'))\n            for key in ('eof','overflow','closed','close_attempted','remainder_unknown','closure_unknown'):require(type(channel[key]) is bool,'parent_channel_boolean')\n            integer(channel['observed_bytes'],0,9007199254740991);integer(channel['size_bytes'],0,RAW_CAPS[name]);hex64(channel['sha256'])\n            require(channel['observed_bytes']>=channel['size_bytes'] and channel['closure_unknown'] is (not channel['closed']),'parent_channel_extent')\n            require(channel['error'] is None or type(channel['error']) is str and channel['error'].isascii() and len(channel['error'])<=128,'parent_channel_error')\n            require(type(channel['secondary']) is list and len(channel['secondary'])<=128 and all(type(c) is str and c.isascii() and len(c)<=128 for c in channel['secondary']),'parent_channel_secondary')\n            require(channel['remainder_unknown'] is (not channel['eof'] or channel['overflow'] or channel['error'] is not None or not parent['threads_joined']),'parent_channel_unknown')\n            if channel['eof'] is True and channel['overflow'] is False and channel['error'] is None and parent['threads_joined'] is True:\n             require(channel['closed'] is True and channel['close_attempted'] is True and channel['observed_bytes']==channel['size_bytes'] and channel['secondary']==[],'normal_parent_channel_join')\n            if originals[name] is not None:require(channel['size_bytes']==len(originals[name]) and channel['sha256']==sha(originals[name]),'parent_channel_join')\n           if originals['stdout'] is not None and originals['stderr'] is not None:\n            source,case,summary,measured,passed,collected=original_protocol(originals['stdout'],originals['stderr'],parent,admitted)\n           if report is not None and case is not None:require(report==case['report'],'canonical_report_stdout_join')\n           if parent['protocol_error_type'] is None and originals['stdout'] is not None and originals['stderr'] is not None:\n            require(source is not None and summary is not None,'parent_protocol_availability')\n            require(parent['geometry_source_kind']==source['kind'],'parent_geometry_source_kind_join')\n            require(parent['test_summary']==summary,'parent_summary_join')\n           if source and source['kind']=='d27_inert_source_construction_metadata_v1':normal_capture(source['initial']['compression'],parent,True)\n           if case is not None:normal_capture(case['capture'],parent)\n           normal=parent['returncode'] in (0,1) and type(parent['returncode']) is int and all(parent[k] is False for k in ('forced_test_child','timed_out','io_failure')) and parent['threads_joined'] is True and parent['child_completion_before_total_end'] is True and parent['child_completion_before_cleanup_end'] is True and parent['protocol_error_type'] is None and all(channel['remainder_unknown'] is False for channel in parent['channels'].values())\n           require(parent['parent_observed_test_transport_complete'] is normal,'parent_transport_contradiction')\n           if originals['stdout'] is not None and originals['stderr'] is not None:\n            require(parent['geometry_fully_measured'] is (normal and measured) and parent['geometry_risk_passed'] is (normal and passed and bool(summary and summary['successful'])),'parent_geometry_contradiction')\n         require(outcome['parent_transport_complete']==(parent['parent_observed_test_transport_complete'] if parent is not None else None),'outcome_parent_join')\n         for role in ('initial','finalizer','executor'):\n          known=None\n          if source and source['kind']=='d27_inert_source_construction_metadata_v1':\n           row=source[role]\n           known={'size_bytes':row['source_bytes'] if role=='initial' else row['finalizer_size_bytes'] if role=='finalizer' else row['size_bytes'],'sha256':row['source_sha256'] if role=='initial' else row['finalizer_sha256'] if role=='finalizer' else row['sha256']}\n          actual=value['risk_inputs'][role]\n          require(actual['available'] is (known is not None),'observed_source_availability')\n          if known is not None:require({k:actual[k] for k in ('size_bytes','sha256')}==known,'observed_source_join')\n         if case is not None:\n          validate_report(case['report']);known=canonical(case['report'])+b'\\n';capture=case['capture']\n          require(capture['report_bytes']==len(known) and capture['report_sha256']==sha(known) and capture['stdout']['retained_bytes']==len(known) and capture['stdout']['prefix_sha256']==sha(known) and capture['checks_count']==len(case['report']['checks']) and capture['measurements_count']==len(case['report']['measurements']) and capture['case_completed'] is case['report']['completed'] and capture['case_cause']==case['report']['cause'],'known_stdout_report_capture_join')\n          require(report is not None,'recoverable_canonical_original_dropped')\n          require(report==case['report'],'known_report_representation_join')\n         missing_c,missing_m,groups=membership(report,outcome['inventory'])\n         ids(outcome['missing_check_ids'],512);ids(outcome['missing_measurement_ids'],128)\n         require(outcome['missing_check_ids']==missing_c and outcome['missing_measurement_ids']==missing_m and outcome['conditional_groups']==groups,'missing_inventory_join')\n         collection=report is not None and parent is not None and parent['parent_observed_test_transport_complete'] is True and source is not None and source['kind']=='d27_inert_source_construction_metadata_v1' and case is not None and collected and all(raw is not None for raw in originals.values()) and not missing_c and not missing_m and all(g['coverage']=='COMPLETE_APPLICABLE' for g in groups)\n         outer_known=external['completed'] is True and external['exit_code'] is not None\n         all_true=collection and passed and parent['geometry_risk_passed'] is True and bool(summary and summary['successful'] is True) and external['completed'] is True and external['exit_code']==0\n         expected_status='ALL_GEOMETRY_TRUE_NOT_READY' if all_true else 'COMPLETE_HOLD' if collection and outer_known else 'INCOMPLETE_HOLD'\n         require(outcome['status']==expected_status,'outcome_status_join')\n         return {'retained_metadata_valid':True,'status':expected_status,'geometry_risk_replayed':False,'geometry_readiness_granted':False}\n        root=Path(__file__).resolve().parents[1]\n        # The old roles are separate fixed DATA checks, never fixture-selected roles.\n        for rel,size,digest in (\n          ('tests/test_accepted_policy_fixture_compiler_gate2_resume_v1.py',521029,'bdfaca98fbd3825cf383a4d3f22ae60ffaced76cee27f42cf462ba6dba7bd704'),\n          ('tests/test_accepted_policy_fixture_compiler_gate2_resume_caller_v1.py',520323,'3742a391657a85932a3ba776b36fbef87c7a097b7be067cf79ea27cfb3e5b24f'),\n          ('tests/fixtures/gate2/d26-geometry-retained-v1.json',102199,'408379cb8ee0d7ce2fd233d963a0939889485156e7c42a07481d3726b419578f')):\n            with (root/rel).open('rb') as handle:old_raw=handle.read(size+1)\n            require(len(old_raw)==size and sha(old_raw)==digest,'protected_old_DATA_identity')\n        try:\n            with (root/'tests/fixtures/gate2/d27-geometry-retained-v1.json').open('rb') as handle:raw=handle.read(8388609)\n            require(len(raw)<=8388608,'fixture_oversize')\n            require(bytes_pin(raw)==fixture_pin,'fixture_literal_pin')\n            value=load_json(raw)\n            sources=[]\n            for rel in MODULE_PATHS:\n                with (root/rel).open('rb') as handle:held=handle.read(524289)\n                require(len(held)<=524288,'held_source_oversize');sources.append(held)\n            fixtures=[]\n            for rel,size,digest in FIXTURES:\n                with (root/rel).open('rb') as handle:held=handle.read(262145)\n                require(len(held)<=262144,'formatter_oversize');fixtures.append(held)\n            validate_fixture(value,template_sha,admitted,external,sources[0],sources[1],fixtures)\n        except Exception:\n            raise AssertionError('d27_retained_metadata_invalid') from None\n"
    return head+body



D27_CODEC_TEST_ENTRY = 'import sys\nsys.stdout.reconfigure(encoding=\'utf-8\')\nimport hashlib,json,os,pathlib,stat,types,unittest\nif not (sys.flags.isolated and sys.flags.no_site and sys.flags.dont_write_bytecode and sys.flags.optimize==0):raise RuntimeError(\'d27_entry_python_flags\')\nif sys.version_info[:3]!=(3,14,7):raise RuntimeError(\'d27_entry_python_version\')\nroot=pathlib.Path(\'C:/Users/s-a-balashov/.codex/worktrees/fix-accepted-policy-preprocessing/VAST\')\nexpected=json.loads(sys.argv[1]);assert type(expected) is dict and set(expected)=={\'main\',\'caller\'}\nfixed=((\'main\',\'tests.test_accepted_policy_fixture_compiler_gate2_dictionary_v1\',\'test_accepted_policy_fixture_compiler_gate2_dictionary_v1.py\'),(\'caller\',\'tests.test_accepted_policy_fixture_compiler_gate2_dictionary_caller_v1\',\'test_accepted_policy_fixture_compiler_gate2_dictionary_caller_v1.py\'))\ndef epoch(s,cross=False):return(s.st_dev,s.st_ino,s.st_mode,s.st_nlink,s.st_size,s.st_mtime_ns,getattr(s,"st_birthtime_ns",None),None if cross and os.name=="nt" else s.st_ctime_ns)\nheld=[]\nfor role,name,filename in fixed:\n path=root/\'tests\'/filename;pin=expected[role];assert type(pin) is list and len(pin)==2 and type(pin[0]) is int and 0<pin[0]<=524288 and type(pin[1]) is str and len(pin[1])==64\n before=path.lstat();assert path.resolve(strict=True)==path and stat.S_ISREG(before.st_mode) and before.st_nlink==1 and before.st_size==pin[0]\n fd=os.open(path,os.O_RDONLY|getattr(os,\'O_BINARY\',0))\n try:\n  opened=os.fstat(fd);assert epoch(opened,True)==epoch(before,True)\n  raw=b\'\'\n  while len(raw)<pin[0]:\n   part=os.read(fd,min(65536,pin[0]-len(raw)));assert part;raw+=part\n  assert os.read(fd,1)==b\'\' and epoch(os.fstat(fd))==epoch(opened) and epoch(path.lstat())==epoch(before)\n finally:os.close(fd)\n assert len(raw)==pin[0] and hashlib.sha256(raw).hexdigest()==pin[1];held.append((name,path,raw))\n# Both immutable buffers have been authenticated and held before either compile.\nmodules=[]\nfor name,path,raw in held:\n module=types.ModuleType(name);module.__file__=str(path);module.__package__=\'tests\';sys.modules[name]=module;modules.append(module)\nfor module,(_,path,raw) in zip(modules,held):exec(compile(raw,str(path),\'exec\'),vars(module))\nsuite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(getattr(modules[1],name)) for name in (\'D27WireCodecTests\',\'D27CaptureControlTests\',\'D27FixedDriverTransportTests\',\'D27SourceCustodyTests\',\'D27RetentionSourceTests\',\'D27ProtocolControlsTests\',\'D27EntryTransportControlsTests\'))\nresult=unittest.TextTestRunner(verbosity=1,failfast=True).run(suite)\nraise SystemExit(0 if result.wasSuccessful() else 1)\n'

D27_GENUINE_INITIAL_ENTRY = 'import sys,hashlib,json,re\nsys.stdout.reconfigure(encoding=\'utf-8\')\ndef _d27_entry():\n import sys\n sys.stdout.reconfigure(encoding=\'utf-8\')\n import hashlib,json,os,pathlib,stat,types,unittest,re,math,time\n if not (sys.flags.isolated and sys.flags.no_site and sys.flags.dont_write_bytecode and sys.flags.optimize==0):raise RuntimeError(\'d27_entry_python_flags\')\n if sys.version_info[:3]!=(3,14,7):raise RuntimeError(\'d27_entry_python_version\')\n root=pathlib.Path(\'C:/Users/s-a-balashov/.codex/worktrees/fix-accepted-policy-preprocessing/VAST\')\n assert len(sys.argv)==2\n assert pathlib.Path.cwd().resolve()==root.resolve(strict=True)\n assert len(sys.argv[1])<=1024\n def pairs(rows):\n  value={}\n  for key,item in rows:\n   assert key not in value;value[key]=item\n  return value\n expected=json.loads(sys.argv[1],object_pairs_hook=pairs);assert type(expected) is dict and set(expected)=={\'main\',\'caller\'}\n fixed=((\'main\',\'tests.test_accepted_policy_fixture_compiler_gate2_dictionary_v1\',\'test_accepted_policy_fixture_compiler_gate2_dictionary_v1.py\'),(\'caller\',\'tests.test_accepted_policy_fixture_compiler_gate2_dictionary_caller_v1\',\'test_accepted_policy_fixture_compiler_gate2_dictionary_caller_v1.py\'))\n def epoch(s,cross=False):return(s.st_dev,s.st_ino,s.st_mode,s.st_nlink,s.st_size,s.st_mtime_ns,getattr(s,"st_birthtime_ns",None),None if cross and os.name=="nt" else s.st_ctime_ns)\n held=[]\n for role,name,filename in fixed:\n  path=root/\'tests\'/filename;pin=expected[role];assert type(pin) is list and len(pin)==2 and type(pin[0]) is int and 0<pin[0]<=524288 and type(pin[1]) is str and re.fullmatch(\'[0-9a-f]{64}\',pin[1]) is not None\n  before=path.lstat();assert path.resolve(strict=True)==path and stat.S_ISREG(before.st_mode) and before.st_nlink==1 and before.st_size==pin[0]\n  fd=os.open(path,os.O_RDONLY|getattr(os,\'O_BINARY\',0))\n  try:\n   opened=os.fstat(fd);assert epoch(opened,True)==epoch(before,True)\n   raw=b\'\'\n   while len(raw)<pin[0]:\n    part=os.read(fd,min(65536,pin[0]-len(raw)));assert part;raw+=part\n   assert os.read(fd,1)==b\'\' and epoch(os.fstat(fd))==epoch(opened) and epoch(path.lstat())==epoch(before)\n  finally:os.close(fd)\n  assert len(raw)==pin[0] and hashlib.sha256(raw).hexdigest()==pin[1];held.append((name,path,raw))\n # Both immutable buffers have been authenticated and held before either compile.\n modules=[]\n for name,path,raw in held:\n  module=types.ModuleType(name);module.__file__=str(path);module.__package__=\'tests\';module.__d27_held_raw__=raw;sys.modules[name]=module;sys.modules[name.rsplit(\'.\',1)[-1]]=module;modules.append(module)\n for module,(_,path,raw) in zip(modules,held):exec(compile(raw,str(path),\'exec\'),vars(module))\n for module,(name,path,raw) in zip(modules,held):\n  assert sys.modules[name] is module and sys.modules[name.rsplit(\'.\',1)[-1]] is module and vars(module)[\'__name__\']==name\n for module,(_,path,_),getter_name in zip(modules,held,(\'d27_run_genuine_initial_v1\',\'d27_require_positive_geometry_v1\')):\n  getter=vars(module).get(getter_name)\n  assert type(getter) is types.FunctionType and getter.__name__==getter_name and getter.__module__==module.__name__ and getter.__globals__ is vars(module) and pathlib.Path(getter.__code__.co_filename)==path\n try:\n  report,capture=modules[0].d27_run_genuine_initial_v1(time.monotonic()+300)\n except BaseException as error:\n  report,facts=modules[1].d27_genuine_failure_metadata_v1(error,\'genuine_initial\')\n  records=[]\n  if report is not None:records.append(json.dumps(report,sort_keys=True,separators=(\',\',\':\'),ensure_ascii=True,allow_nan=False).encode(\'ascii\')+b\'\\n\')\n  records.append(json.dumps(facts,sort_keys=True,separators=(\',\',\':\'),ensure_ascii=True,allow_nan=False).encode(\'ascii\')+b\'\\n\');status=1\n else:\n  records=modules[1].d27_genuine_success_records_v1(report,capture)\n  status=0 if report[\'completed\'] is True and report[\'cause\'] is None and report[\'checks\'] and all(row[\'ok\'] is True for row in report[\'checks\']) else 1\n for raw in records:\n  if len(raw)>32768:raise RuntimeError(\'d27_genuine_entry_metadata_bound\')\n  sys.stdout.buffer.write(raw);sys.stdout.buffer.flush()\n return status\n\ntry:status=_d27_entry()\nexcept BaseException as error:\n status=1\n try:\n  kind=type.__getattribute__(type(error),\'__name__\')\n  if type(kind) is not str or re.fullmatch(\'[A-Za-z_][A-Za-z0-9_]{0,95}\',kind) is None:kind=\'Exception\'\n  facts={\'event\':\'entry_failure\',\'error_type\':kind,\'message_size_bytes\':None,\'message_sha256\':None,\'message_unavailable\':True,\'secondary\':[]}\n  try:\n   args=BaseException.args.__get__(error)\n   if type(error) in (RuntimeError,ValueError,AssertionError,TypeError,OverflowError,TimeoutError) and type(args) is tuple and len(args)==1 and type(args[0]) is str and len(args[0])<=4096:\n    raw=args[0].encode(\'utf-8\');facts.update(message_size_bytes=len(raw),message_sha256=hashlib.sha256(raw).hexdigest());del facts[\'message_unavailable\']\n  except BaseException:pass\n  encoded=json.dumps(facts,sort_keys=True,separators=(\',\',\':\'),ensure_ascii=True,allow_nan=False).encode(\'ascii\')+b\'\\n\'\n  if len(encoded)>32768:raise RuntimeError(\'d27_entry_failure_record_bound\')\n  sys.stdout.buffer.write(encoded);sys.stdout.buffer.flush();status=1\n except BaseException:pass\nraise SystemExit(status) from None\n'

D27_GENUINE_FINALIZER_ENTRY = 'import sys,hashlib,json,re\nsys.stdout.reconfigure(encoding=\'utf-8\')\ndef _d27_entry():\n import sys\n sys.stdout.reconfigure(encoding=\'utf-8\')\n import hashlib,json,os,pathlib,stat,types,unittest,re,math,time\n if not (sys.flags.isolated and sys.flags.no_site and sys.flags.dont_write_bytecode and sys.flags.optimize==0):raise RuntimeError(\'d27_entry_python_flags\')\n if sys.version_info[:3]!=(3,14,7):raise RuntimeError(\'d27_entry_python_version\')\n root=pathlib.Path(\'C:/Users/s-a-balashov/.codex/worktrees/fix-accepted-policy-preprocessing/VAST\')\n assert len(sys.argv)==2\n assert pathlib.Path.cwd().resolve()==root.resolve(strict=True)\n assert len(sys.argv[1])<=1024\n def pairs(rows):\n  value={}\n  for key,item in rows:\n   assert key not in value;value[key]=item\n  return value\n expected=json.loads(sys.argv[1],object_pairs_hook=pairs);assert type(expected) is dict and set(expected)=={\'main\',\'caller\'}\n fixed=((\'main\',\'tests.test_accepted_policy_fixture_compiler_gate2_dictionary_v1\',\'test_accepted_policy_fixture_compiler_gate2_dictionary_v1.py\'),(\'caller\',\'tests.test_accepted_policy_fixture_compiler_gate2_dictionary_caller_v1\',\'test_accepted_policy_fixture_compiler_gate2_dictionary_caller_v1.py\'))\n def epoch(s,cross=False):return(s.st_dev,s.st_ino,s.st_mode,s.st_nlink,s.st_size,s.st_mtime_ns,getattr(s,"st_birthtime_ns",None),None if cross and os.name=="nt" else s.st_ctime_ns)\n held=[]\n for role,name,filename in fixed:\n  path=root/\'tests\'/filename;pin=expected[role];assert type(pin) is list and len(pin)==2 and type(pin[0]) is int and 0<pin[0]<=524288 and type(pin[1]) is str and re.fullmatch(\'[0-9a-f]{64}\',pin[1]) is not None\n  before=path.lstat();assert path.resolve(strict=True)==path and stat.S_ISREG(before.st_mode) and before.st_nlink==1 and before.st_size==pin[0]\n  fd=os.open(path,os.O_RDONLY|getattr(os,\'O_BINARY\',0))\n  try:\n   opened=os.fstat(fd);assert epoch(opened,True)==epoch(before,True)\n   raw=b\'\'\n   while len(raw)<pin[0]:\n    part=os.read(fd,min(65536,pin[0]-len(raw)));assert part;raw+=part\n   assert os.read(fd,1)==b\'\' and epoch(os.fstat(fd))==epoch(opened) and epoch(path.lstat())==epoch(before)\n  finally:os.close(fd)\n  assert len(raw)==pin[0] and hashlib.sha256(raw).hexdigest()==pin[1];held.append((name,path,raw))\n # Both immutable buffers have been authenticated and held before either compile.\n modules=[]\n for name,path,raw in held:\n  module=types.ModuleType(name);module.__file__=str(path);module.__package__=\'tests\';module.__d27_held_raw__=raw;sys.modules[name]=module;sys.modules[name.rsplit(\'.\',1)[-1]]=module;modules.append(module)\n for module,(_,path,raw) in zip(modules,held):exec(compile(raw,str(path),\'exec\'),vars(module))\n for module,(name,path,raw) in zip(modules,held):\n  assert sys.modules[name] is module and sys.modules[name.rsplit(\'.\',1)[-1]] is module and vars(module)[\'__name__\']==name\n for module,(_,path,_),getter_name in zip(modules,held,(\'d27_run_genuine_finalizer_v1\',\'d27_require_positive_geometry_v1\')):\n  getter=vars(module).get(getter_name)\n  assert type(getter) is types.FunctionType and getter.__name__==getter_name and getter.__module__==module.__name__ and getter.__globals__ is vars(module) and pathlib.Path(getter.__code__.co_filename)==path\n try:\n  report,capture=modules[0].d27_run_genuine_finalizer_v1(time.monotonic()+300)\n except BaseException as error:\n  report,facts=modules[1].d27_genuine_failure_metadata_v1(error,\'genuine_finalizer\')\n  records=[]\n  if report is not None:records.append(json.dumps(report,sort_keys=True,separators=(\',\',\':\'),ensure_ascii=True,allow_nan=False).encode(\'ascii\')+b\'\\n\')\n  records.append(json.dumps(facts,sort_keys=True,separators=(\',\',\':\'),ensure_ascii=True,allow_nan=False).encode(\'ascii\')+b\'\\n\');status=1\n else:\n  records=modules[1].d27_genuine_success_records_v1(report,capture)\n  status=0 if report[\'completed\'] is True and report[\'cause\'] is None and report[\'checks\'] and all(row[\'ok\'] is True for row in report[\'checks\']) else 1\n for raw in records:\n  if len(raw)>32768:raise RuntimeError(\'d27_genuine_entry_metadata_bound\')\n  sys.stdout.buffer.write(raw);sys.stdout.buffer.flush()\n return status\n\ntry:status=_d27_entry()\nexcept BaseException as error:\n status=1\n try:\n  kind=type.__getattribute__(type(error),\'__name__\')\n  if type(kind) is not str or re.fullmatch(\'[A-Za-z_][A-Za-z0-9_]{0,95}\',kind) is None:kind=\'Exception\'\n  facts={\'event\':\'entry_failure\',\'error_type\':kind,\'message_size_bytes\':None,\'message_sha256\':None,\'message_unavailable\':True,\'secondary\':[]}\n  try:\n   args=BaseException.args.__get__(error)\n   if type(error) in (RuntimeError,ValueError,AssertionError,TypeError,OverflowError,TimeoutError) and type(args) is tuple and len(args)==1 and type(args[0]) is str and len(args[0])<=4096:\n    raw=args[0].encode(\'utf-8\');facts.update(message_size_bytes=len(raw),message_sha256=hashlib.sha256(raw).hexdigest());del facts[\'message_unavailable\']\n  except BaseException:pass\n  encoded=json.dumps(facts,sort_keys=True,separators=(\',\',\':\'),ensure_ascii=True,allow_nan=False).encode(\'ascii\')+b\'\\n\'\n  if len(encoded)>32768:raise RuntimeError(\'d27_entry_failure_record_bound\')\n  sys.stdout.buffer.write(encoded);sys.stdout.buffer.flush();status=1\n except BaseException:pass\nraise SystemExit(status) from None\n'
