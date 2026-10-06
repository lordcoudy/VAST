"""Retain attempt K originals: control/log files copied (large JSON gzip'd, mtime=0); all raw by size+SHA256 (kept in the K root)."""
import gzip,hashlib,json,shutil,sys
from pathlib import Path
src=Path('/home/s-a-balashov/vffefab7aK');logs=Path('/mnt/e/STUDY/VAST/tmp/finite-component-study-20261005/launch-K-v1-logs')
ci=Path('/mnt/e/STUDY/VAST/tmp/finite-component-study-20261005/ci-A11-fefab7a-v1')
dst=Path(sys.argv[1]);dst.mkdir(parents=True)
GZ=4*1024**2
rows=[];raw=[]
def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for c in iter(lambda:f.read(1<<20),b''):h.update(c)
    return h.hexdigest()
def keep(p,rel):
    out=dst/rel;out.parent.mkdir(parents=True,exist_ok=True);row={'source':str(p),'size_bytes':p.stat().st_size,'sha256':sha(p)}
    if p.stat().st_size>GZ:
        out=out.with_name(out.name+'.gz')
        with p.open('rb') as i,open(out,'wb') as o,gzip.GzipFile(filename='',mode='wb',fileobj=o,mtime=0,compresslevel=9) as g:shutil.copyfileobj(i,g)
        row['gzip_sha256']=sha(out)
    else:shutil.copyfile(p,out)
    row['path']=str(out.relative_to(dst));rows.append(row)
for base in ('b','s/run','s/prepare','s/prepare/pool-global-client/evidence','s/prepare/pool-branch-channel/evidence'):
    for p in sorted((src/base).iterdir()):
        if p.is_file() and p.suffix in ('.mp4','.avi'):raw.append({'source':str(p),'size_bytes':p.stat().st_size,'sha256':sha(p)})
        elif p.is_file():keep(p,base.replace('/','__')+'/'+p.name)
for p in sorted(logs.iterdir()):
    if p.is_file():keep(p,'launch-K-v1-logs/'+p.name)
for p in sorted(ci.iterdir()):
    if p.is_file():keep(p,'ci-A11-fefab7a-v1/'+p.name)
for d in sorted((src/'s/run').iterdir()):
    if d.is_dir():
        for p in sorted(d.rglob('*')):
            if p.is_file():raw.append({'source':str(p),'size_bytes':p.stat().st_size,'sha256':sha(p)})
for pool in ('pool-global-client','pool-branch-channel'):
    for p in sorted((src/'s/prepare'/pool/'journal').rglob('*')):
        if p.is_file():raw.append({'source':str(p),'size_bytes':p.stat().st_size,'sha256':sha(p)})
res=json.loads((src/'s/run/study-results.original.json').read_text())
rr=json.loads((logs/'independent-rereduce.K.v1.json').read_text())
doc={'kind':'real-K-complete-24-arm-campaign-preserved','source_commit':'fefab7a93ab5e850ddcb90ac4c9d8eb351811fa0',
 'ci_run':37463682987,'canonical_study_complete':res['canonical_study_complete'],'final_variant':res['final_variant'],
 'elapsed_s':res['elapsed_s'],'started_monotonic_ns':res['started_monotonic_ns'],
 'raw_effect_matrix_complete':rr['raw_effect_matrix_complete'],'actual_effect_arms':rr['actual_effect_arms'],
 'independent_rereduction_equals_original':rr==res['reduction'],
 'first_observation':False,'prior_attempt_J_pilot_sealed_not_mixed':True,
 'legacy_full_run_eligible':res['legacy_full_run_eligible'],'qualification_eligible':res['qualification_eligible'],
 'q4_eligible':res['q4_eligible'],'publication_eligible':res['publication_eligible'],
 'copied':rows,'retained_in_root_not_committed':raw}
(dst/'retention.original.json').write_text(json.dumps(doc,indent=1,sort_keys=True)+'\n')
print(len(rows),len(raw),sum(r['size_bytes'] for r in raw),doc['independent_rereduction_equals_original'])
