"""Read-only finite preservation/count audit of six Decision27 planning documents."""
import hashlib,json,re
from pathlib import Path
ROOT=Path('/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
OUT=Path(__file__).parent
SNAPSHOT=ROOT/'artifacts/benchmark_recovery_20260930/decision27-planning-originals-v1'
def descriptor(p):
 raw=p.read_bytes();return {'path':str(p.relative_to(ROOT)),'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
rows=json.loads((SNAPSHOT/'inventory.json').read_bytes());audit=[]
for row in rows:
 before=SNAPSHOT/row['original_file'];after=ROOT/row['path'];old=before.read_bytes();new=after.read_bytes()
 assert len(old)==row['size_bytes'] and hashlib.sha256(old).hexdigest()==row['sha256']
 assert new.startswith(old),row['path']+' original bytes not preserved prefix'
 audit.append({'before':descriptor(before),'after':descriptor(after),'original_bytes_preserved_as_prefix':True})
spec=next(row for row in rows if row['path'].endswith('/spec.md'));tasks=next(row for row in rows if row['path'].endswith('/tasks.md'))
def count_spec(raw):return {'requirements':len(re.findall(rb'^### Requirement:',raw,re.M)),'scenarios':len(re.findall(rb'^#### Scenario:',raw,re.M))}
def task_lines(raw):return re.findall(rb'^- \[([x ])\] (.+)$',raw,re.M)
oldspec=(SNAPSHOT/spec['original_file']).read_bytes();newspec=(ROOT/spec['path']).read_bytes();oldtasks=task_lines((SNAPSHOT/tasks['original_file']).read_bytes());newtasks=task_lines((ROOT/tasks['path']).read_bytes())
assert count_spec(oldspec)=={'requirements':19,'scenarios':109}
assert count_spec(newspec)=={'requirements':20,'scenarios':112}
assert len(oldtasks)==62 and len(newtasks)==65 and newtasks[:62]==oldtasks
assert sum(state==b'x' for state,text in oldtasks)==sum(state==b'x' for state,text in newtasks)==37
assert all(state==b' ' and text.startswith(b'22.') for state,text in newtasks[62:])
result={'schema_version':1,'artifact_kind':'vast_decision27_planning_preservation_audit_v1','six_documents':audit,'original_counts':{**count_spec(oldspec),'tasks':62,'checked':37},'current_counts':{**count_spec(newspec),'tasks':65,'checked':37},'all_original_task_ID_text_state_lines_preserved':True,'three_new_22_tasks_unchecked':True,'original82_scenario72_task_register_byte_exact':True,'scope':'Pure original/current bytes and Markdown counts; no OpenSpec/producer/model/engine/copy/setup/test execution or acceptance.'}
with (OUT/'static-prefix-audit.v1.json').open('x') as out:json.dump(result,out,sort_keys=True,indent=2);out.write('\n')
print(json.dumps(descriptor(OUT/'static-prefix-audit.v1.json')))