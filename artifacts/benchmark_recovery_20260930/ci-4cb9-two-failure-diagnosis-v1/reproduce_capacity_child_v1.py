"""Observe one unchanged original unit; wrappers always forward real functions."""
import hashlib
import json
import os
from pathlib import Path
import sys
import traceback
import unittest

ROOT = Path('/home/s-a-balashov/work/vast-current-source-ci-20261001-4cb9d831')
OUT = Path(sys.argv[1])
sys.path.insert(0, str(ROOT / 'tests'))
import test_publication_operational_process_custody_v1 as original_test
observer = original_test.observer
events = []
receipts = []
real_require = observer._require
real_started = original_test.engine_process_started_v1
real_finish = observer._Capture.finish

def write(name, raw):
    with (OUT / name).open('xb') as file:
        file.write(raw)
        file.flush()
        os.fsync(file.fileno())

def current():
    capture = observer.current_original_engine_capture_v1()
    return None if capture is None else {'output_dir': str(capture.output_dir),
        'call_count': len(capture.calls), 'failure': capture.failure, 'phase': observer._phase.get()}

def observe_require(condition, message):
    if not condition:
        events.append({'event': 'original_require_refused', 'message': message,
                       'capture': current(), 'original_stack': traceback.format_stack(limit=12)})
    return real_require(condition, message)

def observe_started(*args, **kwargs):
    process = args[0]
    before = current()
    try:
        token = real_started(*args, **kwargs)
    except BaseException as error:
        events.append({'event': 'original_start_raised', 'pid': process.pid, 'before': before,
                       'after': current(), 'error_type': type(error).__name__, 'error': str(error),
                       'original_traceback': traceback.format_exc()})
        raise
    else:
        events.append({'event': 'original_start_returned', 'pid': process.pid, 'before': before,
                       'after': current()})
        return token

def observe_finish(capture, body_error):
    try:
        return real_finish(capture, body_error)
    finally:
        descriptor = capture.receipt_descriptor
        if descriptor is not None:
            raw = Path(descriptor['path']).read_bytes()
            assert len(raw) == descriptor['size_bytes'] and hashlib.sha256(raw).hexdigest() == descriptor['sha256']
            name = 'original-fixture-receipt-%02d.json' % (len(receipts) + 1)
            write(name, raw)
            receipts.append({'original_descriptor': descriptor, 'retained_name': name,
                             'body_error_type': None if body_error is None else type(body_error).__name__,
                             'body_error': None if body_error is None else str(body_error),
                             'call_count': len(capture.calls), 'failure': capture.failure})

observer._require = observe_require
original_test.engine_process_started_v1 = observe_started
observer._Capture.finish = observe_finish
test_id = 'test_publication_operational_process_custody_v1.ProcessCustodyTests.test_caught_invalid_phase_remains_sticky_and_call_capacity_is_bounded'
try:
    suite = unittest.defaultTestLoader.loadTestsFromName(test_id)
    assert suite.countTestCases() == 1
    result = unittest.TextTestRunner(verbosity=2).run(suite)
finally:
    observer._require = real_require
    original_test.engine_process_started_v1 = real_started
    observer._Capture.finish = real_finish
    loaded = []
    for module in list(sys.modules.values()):
        value = getattr(module, '__file__', None)
        if value:
            path = Path(value).resolve()
            if path.is_relative_to(ROOT) and path.is_file():
                raw = path.read_bytes()
                loaded.append({'path': str(path), 'size_bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()})
    write('original-observations.v1.json', (json.dumps({'test_id': test_id, 'events': events,
        'receipts': receipts, 'loaded_sources': sorted(loaded, key=lambda row: row['path']),
        'limitation': 'Observation wrappers forward unchanged real validators; their cost can change race timing. Local behavior is not the hosted cause.'},
        sort_keys=True, indent=2) + '\n').encode())
raise SystemExit(0 if result.wasSuccessful() else 1)
