"""Record a scoped original unit preflight; no workflow/build/hardware acceptance."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path('/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
OUT = ROOT / 'artifacts/benchmark_recovery_20260930/cpu-ci-preflight-v1'
FILES = ('.github/workflows/ci.yml', '.ci/requirements.txt',
         'scripts/run_ci_checks.py', 'tests/test_run_ci_checks.py')


def descriptor(path):
    raw = path.read_bytes()
    return {'path': str(path), 'size_bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def owner(pid):
    stat = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
    return {'pid': pid, 'ppid': int(stat[1]), 'starttime_ticks': int(stat[19]),
            'uid': os.getuid(), 'gid': os.getgid(),
            'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip()}


OUT.mkdir(mode=0o700)
before = [descriptor(ROOT / name) for name in FILES]
argv = [sys.executable, '-I', '-B', str(ROOT / 'tests/test_run_ci_checks.py'), '-v']
began = time.monotonic()
with (OUT / 'original.stdout').open('xb') as stdout, (OUT / 'original.stderr').open('xb') as stderr:
    process = subprocess.Popen(argv, cwd=ROOT, stdin=subprocess.DEVNULL,
                               stdout=stdout, stderr=stderr, start_new_session=True)
    child = owner(process.pid)
    process.wait(timeout=30)
after = [descriptor(ROOT / name) for name in FILES]
successful = process.returncode == 0 and before == after
report = {'artifact_kind': 'vast_cpu_ci_scoped_unit_preflight_v1',
          'controller': owner(os.getpid()), 'original_child': child,
          'argv': argv, 'original_returncode': process.returncode,
          'elapsed_s': time.monotonic() - began, 'python': sys.version,
          'before': before, 'after': after, 'source_unchanged': before == after,
          'original_stdout': descriptor(OUT / 'original.stdout'),
          'original_stderr': descriptor(OUT / 'original.stderr'),
          'scoped_successful': successful, 'accepted': False, 'publication_ready': False,
          'hosted_workflow_executed': False, 'native_build_executed': False,
          'full_suite_executed': False, 'hardware_acceptance': False}
raw = json.dumps(report, sort_keys=True, separators=(',', ':')).encode()
report['sha256'] = hashlib.sha256(raw).hexdigest()
(OUT / 'original-terminal.v1.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
print(json.dumps({'successful': successful, 'receipt': descriptor(OUT / 'original-terminal.v1.json')}))
sys.exit(0 if successful else 1)
