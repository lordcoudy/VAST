"""Saved local focused-test observer; never invokes component hardware paths."""
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path('/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
OUTPUT = Path(__file__).parent / sys.argv[1]
OUTPUT.mkdir(exist_ok=False)
PATHS = ['scripts/publication_gstreamer_component_cli_v1.py',
         'tests/test_publication_gstreamer_component_cli_v1.py']

def pins():
    return {p: ({'size_bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
                if (raw := (ROOT / p).read_bytes()) is not None else None)
            if (ROOT / p).exists() else None for p in PATHS}

before = pins()
argv = [sys.executable, '-I', '-B', '-c',
        "import sys,unittest;sys.path.insert(0," + repr(str(ROOT / 'tests')) + ");"
        "suite=unittest.defaultTestLoader.loadTestsFromName('test_publication_gstreamer_component_cli_v1');"
        "result=unittest.TextTestRunner(verbosity=2).run(suite);raise SystemExit(not result.wasSuccessful())"]
start = time.time_ns()
child = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, start_new_session=True)
timed_out = False
try:
    stdout, stderr = child.communicate(timeout=30)
except subprocess.TimeoutExpired:
    timed_out = True
    os.killpg(child.pid, 9)
    stdout, stderr = child.communicate(timeout=10)
terminal = time.time_ns()
outputs = {}
for name, raw in [('stdout.log', stdout), ('stderr.log', stderr)]:
    with (OUTPUT / name).open('xb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    outputs[name] = {'path': str(OUTPUT / name), 'size_bytes': len(raw),
                     'sha256': hashlib.sha256(raw).hexdigest()}
report = {'schema_version': 1, 'artifact_kind': 'vast_component_cli_focused_test_execution_v1',
          'argv': argv, 'original_child_pid': child.pid, 'original_child_returncode': child.returncode,
          'started_at_ns': start, 'terminal_at_ns': terminal, 'elapsed_s': (terminal-start)/1e9,
          'timed_out': timed_out, 'source_before': before, 'source_after': pins(), 'outputs': outputs,
          'scope': 'Local CLI delegation fixtures plus genuine bounded4KiB allocation/identity test only; no hardware/Docker/guardian/model/network acceptance.'}
with (OUTPUT / 'execution.v1.json').open('x') as stream:
    json.dump(report, stream, sort_keys=True, separators=(',', ':'));stream.write('\n');stream.flush();os.fsync(stream.fileno())
print(json.dumps(report,sort_keys=True))
raise SystemExit(child.returncode or timed_out)
