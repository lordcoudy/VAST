"""Capture one original stock host-closure CLI after the reviewed host renewal."""
from pathlib import Path
import hashlib, json, os, signal, subprocess, sys, time

ROOT = Path(__file__).resolve().parents[2]
base = ROOT / 'artifacts/gstreamer_component_release_20260930_a3e976d0/host'
previous = json.loads((base / 'execution-code-closure.v1.json').read_bytes())
names = [r['path'] for r in previous['project_sources']]
assert len(names) == 87
output = ROOT / 'artifacts/benchmark_recovery_20260930/component-selected-host-closure-v2-original'
output.mkdir()
def facts(path):
    raw = path.read_bytes()
    return {'size_bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
def snapshot():
    return {p: facts(ROOT / p) for p in names}
before = snapshot()
receipt = base / 'execution-code-closure.v2.json'
assert not receipt.exists()
code = 'import runpy,sys;sys.path.insert(0,' + repr(str(ROOT/'scripts')) + ');runpy.run_path(' + repr(str(ROOT/'scripts/publication_policy_qualification_execution_code_closure_v1.py')) + ',run_name="__main__")'
argv = [sys.executable, '-I', '-B', '-c', code, '--project-root', str(ROOT), '--receipt', str(receipt)]
began = time.monotonic()
with (output/'stdout.bin').open('xb') as stdout, (output/'stderr.bin').open('xb') as stderr:
    child = subprocess.Popen(argv, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, start_new_session=True)
    owner = {'pid': child.pid, 'pgid': os.getpgid(child.pid), 'proc_stat': Path('/proc',str(child.pid),'stat').read_text(), 'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip()}
    with (output/'dispatch.v1.json').open('x') as stream:
        json.dump({'argv':argv,'owner':owner,'before':before,'helper':facts(Path(__file__)),'timeout_s':120,'cleanup_s':10,'historical_receipt_used_only_as_path_inventory':True},stream,sort_keys=True);stream.write('\n')
    timed_out = False
    try:
        child.wait(timeout=120)
    except subprocess.TimeoutExpired:
        timed_out = True
        os.killpg(child.pid, signal.SIGKILL); child.wait(timeout=10)
try:
    os.killpg(child.pid,0); absent=False
except ProcessLookupError:
    absent=True
after=snapshot()
result={'returncode':child.returncode,'timed_out':timed_out,'elapsed_s':time.monotonic()-began,
        'before':before,'after':after,'source_before_after_equal':before==after,
        'original_pid_absent':not Path('/proc',str(child.pid)).exists(),'original_group_absent':absent,
        'outputs':{p:facts(output/p) for p in ('stdout.bin','stderr.bin')},
        'receipt':facts(receipt) if receipt.is_file() else None,'hardware_acceptance':False}
with (output/'execution.v1.json').open('x') as stream:
    json.dump(result,stream,sort_keys=True);stream.write('\n')
print(json.dumps({k:result[k] for k in ('returncode','elapsed_s','source_before_after_equal','original_pid_absent','original_group_absent','receipt')}))
sys.exit(0 if child.returncode==0 and not timed_out and before==after and absent else 78)
