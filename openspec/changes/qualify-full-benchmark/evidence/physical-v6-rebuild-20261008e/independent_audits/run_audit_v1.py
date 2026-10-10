"""Exclusively preserve original audit-process output and source descriptors."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path('/mnt/e/STUDY/VAST/tmp/qfb-root-20261007a')
DIRECTORY = ROOT / 'artifacts/qualify_full_benchmark_20261008e/independent_audits'
name = sys.argv[1]
if sys.flags.optimize or os.getuid() != 1000 or name not in {'images', 'model-parity'}:
    raise RuntimeError('invalid audit invocation')
worker = DIRECTORY / ('audit_images_v1.py' if name == 'images' else 'audit_model_parity_v1.py')
argv = [sys.executable, '-B', str(worker)]


def describe(path):
    info = path.lstat()
    if not path.is_file() or path.is_symlink() or info.st_nlink != 1:
        raise RuntimeError(f'unsafe evidence file: {path}')
    raw = path.read_bytes()
    return {'path': path.relative_to(ROOT).as_posix(), 'sha256': hashlib.sha256(raw).hexdigest(), 'size_bytes': len(raw)}


def exclusive(path, raw):
    with path.open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    path.chmod(0o444)
    return describe(path)


stdout_path = DIRECTORY / f'{name}.original.stdout.log'
stderr_path = DIRECTORY / f'{name}.original.stderr.log'
receipt_path = DIRECTORY / f'{name}.original.execution.v1.json'
if any(path.exists() for path in (stdout_path, stderr_path, receipt_path)):
    raise RuntimeError('original audit output exists; refusing overwrite or repeat')
worker.chmod(0o444)
source = describe(worker)
start = datetime.now(timezone.utc).isoformat()
started = time.monotonic()
with stdout_path.open('xb') as stdout, stderr_path.open('xb') as stderr:
    result = subprocess.run(argv, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, check=False)
stdout_path.chmod(0o444)
stderr_path.chmod(0o444)
if source != describe(worker):
    raise RuntimeError('audit source changed while running')
receipt = {'schema_version': 1, 'artifact_kind': 'vast_g_independent_audit_original_execution_v1',
           'audit': name, 'command': argv, 'cwd': str(ROOT), 'uid': os.getuid(),
           'python': sys.executable, 'python_optimize': sys.flags.optimize,
           'started_at_utc': start, 'finished_at_utc': datetime.now(timezone.utc).isoformat(),
           'elapsed_seconds': time.monotonic() - started, 'original_exit_code': result.returncode,
           'audit_source': source, 'runner_source': describe(Path(__file__).absolute()),
           'stdout': describe(stdout_path), 'stderr': describe(stderr_path),
           'evidence_boundary': 'Original local read-only audit process; does not grant CI or workload acceptance.'}
receipt['payload_sha256'] = hashlib.sha256(json.dumps(receipt, sort_keys=True, separators=(',', ':')).encode('ascii')).hexdigest()
physical = exclusive(receipt_path, json.dumps(receipt, sort_keys=True, separators=(',', ':')).encode('ascii') + b'\n')
print(json.dumps({'audit': name, 'original_exit_code': result.returncode, 'execution_receipt': physical, 'stdout': receipt['stdout'], 'stderr': receipt['stderr']}, sort_keys=True))
raise SystemExit(result.returncode)
