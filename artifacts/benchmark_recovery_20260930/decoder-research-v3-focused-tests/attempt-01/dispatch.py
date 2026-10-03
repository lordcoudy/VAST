from pathlib import Path
import hashlib,json,os,signal,subprocess,sys,time
ROOT=Path('/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
BASE=ROOT/'artifacts/benchmark_recovery_20260930'
OUT=BASE/'decoder-research-v3-focused-tests/attempt-01'
CODE=BASE/'decoder-research-implementation-v3'
def canonical(doc):return json.dumps(doc,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode('ascii')
def descriptor(path):
 raw=path.read_bytes();return {'path':str(path),'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
def snapshots():return [descriptor(path) for path in sorted(CODE.iterdir()) if path.suffix in ('.py','.md')]
def owner(pid):
 suffix=Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()
 fields=dict((row.split(':',1)[0],row.split()[1:]) for row in Path(f'/proc/{pid}/status').read_text().splitlines() if ':' in row)
 return {'pid':pid,'ppid':int(suffix[1]),'starttime_ticks':int(suffix[19]),'uid':int(fields['Uid'][0]),'gid':int(fields['Gid'][0]),'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'pgid':os.getpgid(pid),'session_id':os.getsid(pid)}
program="import sys,unittest\nfrom pathlib import Path\nbase=Path('/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec/artifacts/benchmark_recovery_20260930')\nsys.path.insert(0,str(base/'decoder-research-implementation-v2'))\nimport research_protocol,guest_consumer\nsys.path.insert(0,str(base/'decoder-research-implementation-v3'))\nimport test_pin_diagnostics_v3\nnames=['test_hardlink_preserves_original_rejection_and_actual_predicate_facts','test_actual_directory_type_rejects_and_closes_fds','test_actual_oversize_retains_original_size_and_limit_before_hash']\nsuite=unittest.TestSuite(test_pin_diagnostics_v3.PinDiagnosticsTests(name) for name in names)\nresult=unittest.TextTestRunner(verbosity=2).run(suite)\nsys.exit(0 if result.wasSuccessful() else 1)\n"
argv=[sys.executable,'-I','-B','-c',program]
before=snapshots();begun=time.monotonic();started=time.time_ns();timed_out=False
process=subprocess.Popen(argv,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
child=owner(process.pid)
try:stdout,stderr=process.communicate(timeout=60)
except subprocess.TimeoutExpired:
 timed_out=True;os.killpg(process.pid,signal.SIGKILL);stdout,stderr=process.communicate(timeout=5)
for name,raw in (('original.stdout',stdout),('original.stderr',stderr)):
 if len(raw)>4*1024*1024:raise RuntimeError('focused fixture output cap exceeded')
 with (OUT/name).open('xb') as file:file.write(raw);file.flush();os.fsync(file.fileno())
after=snapshots()
terminal={'schema_version':1,'artifact_kind':'vast_decoder_research_v3_focused_fixture_execution_v1','argv':argv,'controller':owner(os.getpid()),'original_child':child,'started_at_ns':started,'finished_at_ns':time.time_ns(),'elapsed_s':time.monotonic()-begun,'returncode':process.returncode,'timed_out':timed_out,'source_before':before,'source_after':after,'source_stable':before==after,'stdout':descriptor(OUT/'original.stdout'),'stderr':descriptor(OUT/'original.stderr'),'dispatch_source':descriptor(Path(__file__)),'scope':'Meaningful RED: three actual-file strict Pin rejections on immutable v2 lack required original metadata; no GI/Docker/source/decoder/model','accepted':False,'publication_ready':False}
terminal['sha256']=hashlib.sha256(canonical(terminal)).hexdigest()
with (OUT/'terminal.v1.json').open('xb') as file:file.write(canonical(terminal)+b'\n');file.flush();os.fsync(file.fileno())
print(json.dumps({'returncode':process.returncode,'timed_out':timed_out,'source_stable':before==after,'receipt':descriptor(OUT/'terminal.v1.json'),'elapsed_s':terminal['elapsed_s']}))
print(stderr.decode('utf8','replace'))
sys.exit(process.returncode if before==after and not timed_out else 1)
