"""Saved local TDD dispatcher; no actual namespace, Docker or model workload."""
from pathlib import Path
import hashlib
import json
import os
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).parent / sys.argv[1]
OUT.mkdir()
PATHS = ['scripts/run_ci_checks.py', '.github/workflows/ci.yml', 'tests/test_run_ci_checks.py',
         'tests/test_ci_namespace_diagnostic_v1.py']
if (ROOT/'scripts/ci_namespace_diagnostic_v1.py').exists():
    PATHS.append('scripts/ci_namespace_diagnostic_v1.py')
PATHS += ['scripts/ci_test_selection_v1.py', '.ci/integration-test-selection.v1.json',
          'scripts/ci_external_test_observer_v1.py', 'scripts/backend_publication_process_supervisor_v3.py']
def pins():
    return {p: {'size_bytes': (ROOT/p).stat().st_size,
                'sha256': hashlib.sha256((ROOT/p).read_bytes()).hexdigest()} for p in PATHS}
before = pins()
argv = [sys.executable, '-I', '-B', '-c',
        "import sys,unittest;sys.path.insert(0,sys.argv[1]);s=unittest.defaultTestLoader.loadTestsFromNames(['test_run_ci_checks.RunCiChecksTests','test_ci_namespace_diagnostic_v1.NamespaceDiagnosticTests']);r=unittest.TextTestRunner(verbosity=2).run(s);raise SystemExit(not r.wasSuccessful())",
        str(ROOT/'tests')]
began = time.monotonic()
with (OUT/'stdout.raw').open('xb') as stdout, (OUT/'stderr.raw').open('xb') as stderr:
    child = subprocess.Popen(argv, stdout=stdout, stderr=stderr, start_new_session=True)
    (OUT/'launch.json').write_text(json.dumps({'argv':argv,'pid':child.pid,'source_before':before})+'\n')
    timeout = False
    try:
        child.wait(timeout=30)
    except subprocess.TimeoutExpired:
        timeout = True
        os.killpg(child.pid, signal.SIGKILL)
        child.wait(timeout=10)
terminal = {'argv':argv,'pid':child.pid,'returncode':child.returncode,'timed_out':timeout,
            'elapsed_s':time.monotonic()-began,'source_before':before,'source_after':pins(),
            'scope':'Local real alias/import/file/ordinary-child tests plus explicit tool metadata fixtures; no original namespace/model/Docker/hosted/full-suite invocation.'}
terminal['outputs'] = {n:{'size_bytes':(OUT/n).stat().st_size,'sha256':hashlib.sha256((OUT/n).read_bytes()).hexdigest()} for n in ['stdout.raw','stderr.raw']}
(OUT/'terminal.json').write_text(json.dumps(terminal,sort_keys=True)+'\n')
print(json.dumps(terminal))
raise SystemExit(child.returncode if not timeout else 1)
