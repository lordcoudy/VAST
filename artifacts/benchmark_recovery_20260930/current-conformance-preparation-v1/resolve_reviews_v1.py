"""Read-only AST resolution; never imports project code or runs tests."""
import ast, importlib.util, json
from pathlib import Path
ROOT=Path('/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('author_reviews', HERE/'scenario_reviews_v1.py')
mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
methods={}; parsed={}
paths=list((ROOT/'tests').glob('test*.py'))+list((ROOT/'artifacts/benchmark_recovery_20260930/decoder-research-implementation-v5').glob('test*.py'))+list((ROOT/'artifacts/benchmark_recovery_20260930/component-ext4-relocation-preparation-v1').glob('test*.py'))
for path in sorted(paths):
    raw=path.read_bytes(); tree=ast.parse(raw,filename=str(path)); parsed[str(path.relative_to(ROOT))]=(raw,tree)
    module=path.stem
    for cls in tree.body:
        if isinstance(cls,ast.ClassDef):
            for node in cls.body:
                if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and node.name.startswith('test_'):
                    item={'id':f'{module}.{cls.name}.{node.name}','path':str(path.relative_to(ROOT)),'line':node.lineno}
                    methods.setdefault(node.name,[]).append(item); methods[item['id']]=[item]
fail=[]
for key,row in mod.REVIEWS.items():
    for name in row['tests']:
        hits=methods.get(name,[])
        if len(hits)!=1: fail.append({'scenario':key,'test':name,'hits':hits})
    for path,anchor in row['anchors']:
        p=ROOT/path
        if not p.is_file(): fail.append({'scenario':key,'source_missing':path})
        elif anchor not in p.read_text(encoding='utf-8-sig'): fail.append({'scenario':key,'anchor_missing':[path,anchor]})
print(json.dumps({'unresolved':fail,'evidence_keys':sorted(set(x for r in mod.REVIEWS.values() for x in r['evidence']))},indent=2))
