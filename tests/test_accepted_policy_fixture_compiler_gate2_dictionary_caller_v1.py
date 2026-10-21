"""Ordinary authored fixed D27 TEST caller; geometry remains unadmitted."""
import hashlib
import io
import json
import os
import sys
from pathlib import Path
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

D27_CODEC_TEST_ENTRY = 'import sys\nsys.stdout.reconfigure(encoding=\'utf-8\')\nimport hashlib,json,os,pathlib,stat,types,unittest\nif not (sys.flags.isolated and sys.flags.no_site and sys.flags.dont_write_bytecode and sys.flags.optimize==0):raise RuntimeError(\'d27_entry_python_flags\')\nif sys.version_info[:3]!=(3,14,7):raise RuntimeError(\'d27_entry_python_version\')\nroot=pathlib.Path(\'C:/Users/s-a-balashov/.codex/worktrees/fix-accepted-policy-preprocessing/VAST\')\nexpected=json.loads(sys.argv[1]);assert type(expected) is dict and set(expected)=={\'main\',\'caller\'}\nfixed=((\'main\',\'tests.test_accepted_policy_fixture_compiler_gate2_dictionary_v1\',\'test_accepted_policy_fixture_compiler_gate2_dictionary_v1.py\'),(\'caller\',\'tests.test_accepted_policy_fixture_compiler_gate2_dictionary_caller_v1\',\'test_accepted_policy_fixture_compiler_gate2_dictionary_caller_v1.py\'))\ndef epoch(s,cross=False):return(s.st_dev,s.st_ino,s.st_mode,s.st_nlink,s.st_size,s.st_mtime_ns,getattr(s,"st_birthtime_ns",None),None if cross and os.name=="nt" else s.st_ctime_ns)\nheld=[]\nfor role,name,filename in fixed:\n path=root/\'tests\'/filename;pin=expected[role];assert type(pin) is list and len(pin)==2 and type(pin[0]) is int and 0<pin[0]<=524288 and type(pin[1]) is str and len(pin[1])==64\n before=path.lstat();assert path.resolve(strict=True)==path and stat.S_ISREG(before.st_mode) and before.st_nlink==1 and before.st_size==pin[0]\n fd=os.open(path,os.O_RDONLY|getattr(os,\'O_BINARY\',0))\n try:\n  opened=os.fstat(fd);assert epoch(opened,True)==epoch(before,True)\n  raw=b\'\'\n  while len(raw)<pin[0]:\n   part=os.read(fd,min(65536,pin[0]-len(raw)));assert part;raw+=part\n  assert os.read(fd,1)==b\'\' and epoch(os.fstat(fd))==epoch(opened) and epoch(path.lstat())==epoch(before)\n finally:os.close(fd)\n assert len(raw)==pin[0] and hashlib.sha256(raw).hexdigest()==pin[1];held.append((name,path,raw))\n# Both immutable buffers have been authenticated and held before either compile.\nmodules=[]\nfor name,path,raw in held:\n module=types.ModuleType(name);module.__file__=str(path);module.__package__=\'tests\';sys.modules[name]=module;modules.append(module)\nfor module,(_,path,raw) in zip(modules,held):exec(compile(raw,str(path),\'exec\'),vars(module))\nsuite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(getattr(modules[1],name)) for name in (\'D27WireCodecTests\',\'D27CaptureControlTests\',\'D27FixedDriverTransportTests\'))\nresult=unittest.TextTestRunner(verbosity=1,failfast=True).run(suite)\nraise SystemExit(0 if result.wasSuccessful() else 1)\n'
