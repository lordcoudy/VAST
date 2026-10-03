"""Pure predicate regression; never import or execute the full engine probe."""
import ast,hashlib,json,sys
from pathlib import Path
root=Path(__file__).resolve().parents[3];out=Path(__file__).parent
source=out/'probe_original_ext4_bind_v1.py';old=out/'probe_original_ext4_bind_v1.pre-format-fix.raw'
before=old.read_bytes();after=source.read_bytes()
needle=b"stdout in (b'',b'\\n')"
assert before.count(needle)==1 and after==before.replace(needle,b"stdout in (b'',b'\\n',b'[]\\n')")
functions={}
for label,raw in [('original',before),('current',after)]:
    f=next(n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='not_found')
    namespace={};exec(compile(ast.Module(body=[f],type_ignores=[]),str(source),'exec'),namespace)
    functions[label]=namespace['not_found']
identifier='a'*64;prefixes=('Error response from daemon: No such container: ','Error: No such object: ','Error: No such container: ')
assert not functions['original']({'returncode':1},b'[]\n',(prefixes[0]+identifier+'\n').encode(),identifier)
checks=0
for prefix in prefixes:
    stderr=(prefix+identifier+'\n').encode()
    for stdout in (b'',b'\n',b'[]\n'):
        assert functions['current']({'returncode':1},stdout,stderr,identifier);checks+=1
    for stdout in (b'{}\n',b'[{"Id":"foreign"}]\n',b'[]\nextra',b'[]'):
        assert not functions['current']({'returncode':1},stdout,stderr,identifier);checks+=1
    for rc in (0,2,True):
        assert not functions['current']({'returncode':rc},b'[]\n',stderr,identifier);checks+=1
    assert not functions['current']({'returncode':1},b'[]\n',(prefix+'foreign\n').encode(),identifier);checks+=1
def desc(p):
    b=p.read_bytes();return {'path':p.relative_to(root).as_posix(),'size_bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()}
value={'artifact_kind':'vast_ext4_bind_default_inspect_format_review_v2','source':desc(source),'original':desc(old),
 'prior_author_review':desc(out/'author-review.v1.json'),'only_one_tuple_literal_changed':True,
 'actual_pure_predicate_cases':checks,'original_predicate_rejects_documented_default_empty_array':True,
 'python':sys.version,'scope':'AST-extracted actual predicate only; full probe not imported/executed',
 'primary_source':'https://raw.githubusercontent.com/docker/cli/v29.0.2/cli/command/inspect/inspector.go',
 'primary_source_lines':'191-194 default JSON inspector returns []newline on no elements;137-140 template inspector returns newline',
 'meaning':'probe uses unformatted container inspect; exact empty JSON array with rc1 and exact identifier-bound stderr is the genuine API absence form',
 'actual_engine_execution':False,'model_native_gpu_acceptance':False,'publication_ready':False}
(out/'author-review.v2.json').open('xb').write((json.dumps(value,sort_keys=True,indent=2)+'\n').encode())
print(json.dumps(value))
