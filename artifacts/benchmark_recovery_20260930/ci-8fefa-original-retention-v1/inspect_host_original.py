"""Read fixed original host archive and committed diagnostic source; no project imports."""
import hashlib, json, os, pathlib, stat, subprocess, zipfile

ROOT = pathlib.Path('/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
OUT = pathlib.Path(__file__).parent
COMMIT = '8fefa4ba0c5b135c66f85a6eb7f4fd1aaebfdc21'
ARCHIVE = OUT / '36751014399-host/original-artifact.zip'

def epoch(s):
    return [s.st_dev, s.st_ino, s.st_mode, s.st_nlink, s.st_size, s.st_mtime_ns, s.st_ctime_ns]

def descriptor(p):
    raw = p.read_bytes()
    return {'path': p.relative_to(ROOT).as_posix(), 'size_bytes':len(raw), 'sha256':hashlib.sha256(raw).hexdigest()}

def save(p, value):
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open('xb') as f:
        f.write((json.dumps(value, sort_keys=True, indent=2)+'\n').encode()); f.flush(); os.fsync(f.fileno())

fd = os.open(ARCHIVE, os.O_RDONLY|os.O_CLOEXEC|os.O_NOFOLLOW)
before = epoch(os.fstat(fd))
assert stat.S_ISREG(before[2]) and before[3] == 1 and before == epoch(ARCHIVE.lstat())
stream = os.fdopen(fd, 'rb', closefd=False)
try:
    assert descriptor(ARCHIVE)['sha256'] == '299348c4cabd58df8c57c8bde105080ca88418eb5f520ae558084229a54e9fc2'
    with zipfile.ZipFile(stream) as z:
        def read(name, maximum=1024*1024):
            info = z.getinfo(name); assert info.file_size <= maximum
            raw = z.read(info); assert len(raw)==info.file_size
            return raw
        report = json.loads(read('report.json'))
        tracked = json.loads(read('tracked-source.before.json'))
        assert tracked == json.loads(read('tracked-source.after.json'))
        prerequisites = json.loads(read('host-prerequisites.json'))
        paths = ('scripts/ci_namespace_diagnostic_v1.py', 'scripts/run_ci_checks.py',
                 'scripts/ci_test_selection_v1.py', '.ci/integration-test-selection.v1.json')
        result = subprocess.run(['/usr/bin/git', '--git-dir=/mnt/e/STUDY/VAST/.git/worktrees/fix-benchmark-preparations-spec',
            '--work-tree='+str(ROOT), 'cat-file', '--batch'], input=('\n'.join(COMMIT+':'+p for p in paths)+'\n').encode(),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30, check=True)
        assert not result.stderr and len(result.stdout)<=1024*1024
        offset=0; sources=[]
        for p in paths:
            end=result.stdout.index(b'\n',offset); header=result.stdout[offset:end].split()
            assert len(header)==3 and header[1]==b'blob'
            size=int(header[2]); raw=result.stdout[end+1:end+1+size]
            assert result.stdout[end+1+size:end+2+size]==b'\n'
            offset=end+2+size
            facts={'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
            assert tracked[p]==facts
            target=OUT/'committed-source'/p; target.parent.mkdir(parents=True,exist_ok=True)
            with target.open('xb') as f: f.write(raw); f.flush(); os.fsync(f.fileno())
            sources.append({'original_commit':COMMIT,'path':p,**facts,'snapshot':descriptor(target)})
        assert offset==len(result.stdout)
    assert before == epoch(os.fstat(fd)) == epoch(ARCHIVE.lstat())
    save(OUT/'host-original-readonly-review.v1.json', {
        'run_id':36751014399,'source_commit':COMMIT,'read_only':True,'accepted':False,
        'archive':descriptor(ARCHIVE),'archive_original_epoch_before_after':before,
        'original_report':report,'original_prerequisites':prerequisites,
        'original_tracked_source_count':len(tracked),'source_before_after_equal':True,
        'committed_source_snapshots_match_original_hosted_bytes':sources,
        'source_index_head_modified':False,'tests_engine_namespace_or_models_executed':False,
        'cpu_job_terminal_or_denial_not_yet_observed':True})
    print(json.dumps({'host_review':descriptor(OUT/'host-original-readonly-review.v1.json')}))
finally:
    stream.close(); os.close(fd)
