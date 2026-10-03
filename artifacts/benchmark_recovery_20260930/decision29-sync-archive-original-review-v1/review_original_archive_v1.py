"""Read only the actual closed archive and finite current-source witnesses."""
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import time

ROOT = Path('/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
HERE = ROOT/'artifacts/benchmark_recovery_20260930/decision29-sync-archive-original-review-v1'
CHANGE = ROOT/'openspec/changes/fix-benchmark-preparations-spec'
ARCHIVE = ROOT/'openspec/changes/archive/2026-10-03-fix-benchmark-preparations-spec'
MAIN = ROOT/'openspec/specs/benchmark-launch-preparation/spec.md'
SOURCE = Path('/home/s-a-balashov/work/vast-current-source-ci-20261003-decision29-D')
EXPECTED = {
 'prearchive-moves.sealed.v1.json':(7061,'828a90b70d6fe2641c58d7010034e0e2e8be83eff1f2cbf2c257df2cb1ae8c5d'),
 'supported-archive.original-tool.v1.json':(639,'39b8dcdb9836ea78e91d4d103954b0482531449d214e91c10e2f002e211027c8'),
}

def epoch(s):
    return [s.st_dev,s.st_ino,s.st_mode,s.st_nlink,s.st_size,s.st_mtime_ns,s.st_ctime_ns]

def require(test,message):
    if not test:
        raise ValueError(message)

def owner(pid):
    text=Path(f'/proc/{pid}/stat').read_text()
    tail=text[text.rfind(')')+2:].split()
    st=Path(f'/proc/{pid}').stat()
    return {'pid':pid,'ppid':int(tail[1]),'pgid':int(tail[2]),'session':int(tail[3]),'startticks':int(tail[19]),
            'uid':st.st_uid,'gid':st.st_gid,'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip()}

def norm(text):
    rows,current=[],None
    lines=text.splitlines()
    for i,line in enumerate(lines):
        if not line.startswith(('### Requirement:','#### Scenario:')):
            continue
        end=i+1
        while end<len(lines) and not lines[end].startswith(('### Requirement:','#### Scenario:')):
            end+=1
        if line.startswith('### Requirement:'):
            current={'id':f'R{len(rows)+1}','name':line[17:],'exact_requirement_clause':'\n'.join(lines[i:end]).strip(),'scenarios':[]}
            rows.append(current)
        else:
            current['scenarios'].append({'id':current['id']+f'/S{len(current["scenarios"])+1}',
                'name':line[15:],'exact_clause':'\n'.join(lines[i:end]).strip()})
    return rows

def task_rows(text):
    return [{'id':m[1],'text':m[2],'checked':line[3].lower()=='x'}
            for line in text.splitlines() if (m:=re.match(r'- \[[ xX]\] ([0-9]+(?:\.[0-9]+)*) (.+)',line))]

def save(name,value):
    raw=json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2).encode()+b'\n'
    with open(HERE/name,'xb') as f:
        f.write(raw);f.flush();os.fsync(f.fileno())
    return {'path':str(HERE/name),'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}

def main():
    start=time.monotonic_ns();fd_before=len(os.listdir('/proc/self/fd'))
    original=owner(os.getpid());original['observed_parent']=owner(original['ppid'])
    leaves,ancestors,witnesses={},{},[]
    first=None;close_errors=[]
    report={'schema_version':1,'reviewable':False,'blocking_findings':[],'reviewer_handles_released':False,
            'reader_original':original,'merge_performed':False,'latest_archived_commit_CI_accepted':False}

    def remaining():
        require(time.monotonic_ns()-start<=120_000_000_000,'original120s review deadline')

    def read(path,ref=None):
        path=Path(path);key=str(path)
        if key not in leaves:
            for parent in reversed(path.parents):
                p=str(parent)
                if p not in ancestors:
                    fd=os.open(parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
                    ancestors[p]=(fd,epoch(os.fstat(fd)))
            fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC)
            leaves[key]=(fd,epoch(os.fstat(fd)))
        fd,before=leaves[key]
        require(stat.S_ISREG(before[2]) and before[3]==1 and 0<before[4]<=8*1024*1024,'finite regular single-link leaf')
        require(epoch(os.lstat(path))==before,'named original identity')
        raw=bytearray();offset=0
        while offset<before[4]:
            remaining();chunk=os.pread(fd,min(65536,before[4]-offset),offset)
            require(bool(chunk),'short metadata read');raw.extend(chunk);offset+=len(chunk)
        require(os.pread(fd,1,before[4])==b'' and epoch(os.fstat(fd))==before,'metadata size/epoch')
        sha=hashlib.sha256(raw).hexdigest()
        if ref:
            require(len(raw)==ref['size_bytes'] and sha==ref['sha256'],'raw descriptor mismatch: '+key)
            if 'epoch' in ref:
                require(before==ref['epoch'],'current source seven epochs drifted: '+key)
        if not any(w['path']==key for w in witnesses):
            witnesses.append({'path':key,'size_bytes':len(raw),'sha256':sha,'epoch':before})
        return bytes(raw)

    try:
        save('reader-original.v1.json',original)
        read(Path(__file__))
        for name,(size,sha) in EXPECTED.items():
            read(HERE/name,{'size_bytes':size,'sha256':sha})
        inventory=json.loads(read(HERE/'prearchive-moves.sealed.v1.json'))
        tool=json.loads(read(HERE/'supported-archive.original-tool.v1.json'))
        inline=json.loads(read(HERE/'inline-sync.original.v1.json'))
        require(tool['exit_code']==0 and tool['chunk_id']=='feeec7','original supported archive did not succeed')
        result=json.loads(tool['output'])
        require(result['archive']['change']=='fix-benchmark-preparations-spec' and result['archive']['archivedAs']==ARCHIVE.name
                and result['archive']['specsUpdated'] is False,'supported archive identity/inline sync fate')
        require(result['root']['path'].replace('\\\\','/').replace('\\','/').rstrip('/')=='E:/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec','actual original CLI root')
        require(len(inventory['files'])==18 and len({r['new_path'] for r in inventory['files']})==18,'finite18 move set')
        require(not CHANGE.exists(),'old active change still exists')
        moved=[]
        for row in inventory['files']:
            require(row['old_path'].startswith('openspec/changes/fix-benchmark-preparations-spec/')
                    and row['new_path'].startswith('openspec/changes/archive/2026-10-03-fix-benchmark-preparations-spec/'),'move path escape')
            require(not (ROOT/row['old_path']).exists(),'old leaf not retired')
            read(ROOT/row['new_path'],row)
            require(row['git_mode']=='100644','declared Git mode changed')
            moved.append({'old_path':row['old_path'],'new_path':row['new_path'],'size_bytes':row['size_bytes'],'sha256':row['sha256'],
                          'sealed_git_mode':row['git_mode'],'actual_regular_file_mode':os.lstat(ROOT/row['new_path']).st_mode})
        actual_files={str(p.relative_to(ROOT)).replace(os.sep,'/') for p in ARCHIVE.rglob('*') if p.is_file()}
        require(actual_files=={r['new_path'] for r in inventory['files']},'archive exact namespace differs')
        require(not any(p.is_symlink() for p in ARCHIVE.rglob('*')),'archive alias')
        yaml=ARCHIVE/'.openspec.yaml';read(yaml)
        require(yaml.stat().st_size==40,'schema sidecar missing')
        delta=read(ARCHIVE/'specs/benchmark-launch-preparation/spec.md',inline['delta'])
        main=read(MAIN,inline['main'])
        expected=b'# Benchmark Launch Preparation\n\n'+delta.replace(b'## ADDED Requirements',b'## Requirements',1)
        require(main==expected,'new main differs beyond title/ADDED header')
        require(inline['all20_requirements118_scenarios_exact'] and inline['Purpose_and_Scope_verbatim'] and inline['no_additive_rules_returned'],'original inline declarations differ')
        delta_rows=norm(delta.decode());main_rows=norm(main.decode())
        require(main_rows==delta_rows and len(main_rows)==20 and sum(len(r['scenarios']) for r in main_rows)==118,'complete normative20/118 differ')
        cf_path=ROOT/'artifacts/benchmark_recovery_20260930/decision29-current-conformance-independent-review-v1/review.v1.json'
        cf=json.loads(read(cf_path,{'size_bytes':434057,'sha256':'af861006d56d00e466648cf2479f1536925f7b33f5a246916e924c067abec202'}))
        require(cf['reviewable'] and cf['blocking_findings']==[] and cf['reviewer_handles_released'],'accepted conformance not closed')
        for row,prior in zip(main_rows,cf['requirements']):
            require(row['id']==prior['id'] and hashlib.sha256(row['exact_requirement_clause'].encode()).hexdigest()==prior['complete_clause_sha256'],'accepted complete requirement changed')
        cf_rows={r['id']:r for r in cf['scenario_adjudications']}
        for row in [s for r in main_rows for s in r['scenarios']]:
            require(row['name']==cf_rows[row['id']]['name'] and hashlib.sha256(row['exact_clause'].encode()).hexdigest()==cf_rows[row['id']]['exact_clause_sha256'],'accepted complete scenario changed')
        tasks=task_rows(read(ARCHIVE/'tasks.md').decode())
        # Read only the mapper's task values; do not execute or import its code.
        mapper=json.loads(read(ROOT/'artifacts/benchmark_recovery_20260930/decision29-current-conformance-preparation-v1/attempt01/mapping.v1.json',
                        {'size_bytes':4907163,'sha256':'8d8b80bbc7a50c87e519f40f37a4bd2e3c965d3c8dca02af72fd04699770e583'}))
        old_tasks=mapper['current_task_states']
        require(len(tasks)==74 and len(old_tasks)==74 and sum(x['checked'] for x in tasks)==69,'actual69/74 snapshot')
        changed=[]
        for row,prior in zip(tasks,old_tasks):
            require(row['id']==prior['id'] and row['text']==prior['text'],'task text/ID changed during archive')
            if row['checked']!=prior['checked']:
                require(row['checked'] and not prior['checked'],'task state reverted')
                changed.append(row['id'])
        require(set(changed)=={'18.12','19.5','20.7','21.5'},'unexpected process task completion')
        pending=[r['id'] for r in tasks if not r['checked']]
        require(pending==inventory['pending_process_task_ids']==['18.13','18.14','22.3','23.5','24.4'],'future process obligations altered')
        closure=read(ARCHIVE/'implementation-closure.md').decode()
        require(all(i in closure for i in pending) and 'R13/S6' in closure and all(x in closure for x in cf['manual_coverage_rows']), 'dated closure omitted limits/process obligations')
        source_witnesses=[w for w in cf['physical_input_witnesses'] if w['physical_path'].startswith(str(SOURCE)+'/')]
        for witness in source_witnesses:
            read(witness['physical_path'],witness)
        require(read(SOURCE/'.git/HEAD').decode().strip()=='3c025b29b3c1d5275c2ec693410e4b83700583de','tested D HEAD changed')
        for lane,ci in cf['actual_CI'].items():
            for ref in ci['original_refs'].values():
                read(ROOT/ref['path'],ref)
        report.update({'reviewable':True,'blocking_findings':[],
          'change_name':'fix-benchmark-preparations-spec','actual_supported_archive':tool,
          'actual_inline_sync_ref':inline,'archive_location':str(ARCHIVE),'actual_move_count':18,'preserved_moves':moved,
          'all_old_leaves_and_active_root_absent':True,'exact_archive_namespace':True,'schema_sidecar_preserved':True,
          'Purpose_Scope_and_all20_complete_requirement_bodies118_scenarios_exact':True,
          'only_main_title_and_delta_header_changed':True,'accepted_112_prior_clauses_and_72_82_register_preserved_by_same_normative_and_conformance_refs':True,
          'actual_task_snapshot':{'checked':69,'total':74,'four_new_checked':changed,'pending_process_ids':pending},
          'dated_implementation_closure_preserved':True,'manual_limits_preserved':cf['manual_coverage_rows'],
          'all_consumer_direct_negative_gap_preserved':'R13/S6','source_D_witnesses_rechecked':len(source_witnesses),
          'source_D_raw_SHA_seven_epochs_unchanged':True,'both_accepted_CI_controls_unchanged':True,
          'validation':{'root_observed_originals':['93e855','22e9ca0'],'root_reported_valid_items':2,'root_reported_errors':0,
              'root_reported_INFO_long_requirement_messages':18,'limit':'Original validation raw bytes were not retained; this is explicitly root-observed, not an invented physical descriptor. Latest archived-commit CI must validate again.'},
          'limits':['Only the actual local inline sync/archive stage is approved; commit/push, latest archived-commit CI, exact final review and merge remain future gates.',
              'Sealed manifest records Git100644 class, not original per-file Linux physical mode/epoch; current regular leaf modes are observed separately. Staged/committed raw modes are a later root gate.',
              '18 archive leaves include17 originally tracked leaves and a new dated closure snapshot; no missing original is synthesized.',
              'All legacy campaign/integration/research obligations and scientific negative/manual limits remain; no full eligibility or execution grant.',
              'No OpenSpec/Git/source/test/CI/engine/model operation is executed by this reviewer.'],
          'accepted_conformance_ref':{'path':str(cf_path),'size_bytes':434057,'sha256':'af861006d56d00e466648cf2479f1536925f7b33f5a246916e924c067abec202'}})
        for path,(fd,before) in ancestors.items():
            require(epoch(os.fstat(fd))[:3]==epoch(os.lstat(path))[:3]==before[:3],'ancestor identity drift')
        for path,(fd,before) in leaves.items():
            require(epoch(os.fstat(fd))==epoch(os.lstat(path))==before,'held leaf seven epochs drift')
            raw=read(path)
            require(hashlib.sha256(raw).hexdigest()==next(w['sha256'] for w in witnesses if w['path']==path),'final full raw hash drift')
        report['finite_input_count']=len(witnesses)
        report['finite_input_witness_aggregate_sha256']=hashlib.sha256(json.dumps(witnesses,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        report['full_before_after_SHA_name_seven_epochs_verified']=True
    except BaseException as exc:
        first={'type':type(exc).__name__,'message':str(exc)}
        report.update(reviewable=False,blocking_findings=[first])
    finally:
        for path,(fd,_) in reversed(list(leaves.items())+list(ancestors.items())):
            try:os.close(fd)
            except BaseException as exc:close_errors.append({'path':path,'type':type(exc).__name__,'message':str(exc)})
        report['first_failure']=first;report['close_errors']=close_errors
        report['fd_before']=fd_before;report['fd_after']=len(os.listdir('/proc/self/fd'))
        report['reviewer_handles_released']=not close_errors and report['fd_after']==fd_before
        report['reviewable']=report['reviewable'] and report['reviewer_handles_released']
        report['elapsed_s']=(time.monotonic_ns()-start)/1e9
        result=save('review.v1.json',report)
        final_elapsed=(time.monotonic_ns()-start)/1e9
        if final_elapsed>120:
            save('late-failure.v1.json',{'original_limit_s':120,'actual_final_elapsed_s':final_elapsed,'first_failure':first,'reviewable':False})
            return 78
        print(json.dumps({'review':result,'reviewable':report['reviewable'],'first_failure':first,'final_elapsed_s':final_elapsed,'reader_pid':os.getpid()}))
        return 0 if report['reviewable'] else 78

if __name__=='__main__':
    raise SystemExit(main())
