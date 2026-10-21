import ast,sys,json,os
ROOT=sys.argv[1]; lists=sys.argv[2:]
NEW_ATTR={('sys','exception'):'3.11',('datetime','UTC'):'3.11',('hashlib','file_digest'):'3.11',('enum','StrEnum'):'3.11',('typing','Self'):'3.11',('typing','Never'):'3.11',('typing','assert_never'):'3.11',('typing','LiteralString'):'3.11',('typing','Required'):'3.11',('typing','NotRequired'):'3.11',('typing','reveal_type'):'3.11',('asyncio','TaskGroup'):'3.11',('asyncio','timeout'):'3.11',('contextlib','chdir'):'3.11',('operator','call'):'3.11',('itertools','batched'):'3.12',('typing','override'):'3.12',('os.path','isjunction'):'3.12',('math','cbrt'):'3.11',('math','exp2'):'3.11',('logging','getLevelNamesMapping'):'3.11'}
NEW_MOD={'tomllib':'3.11','wsgiref.types':'3.11'}
NEW_NAMES={'ExceptionGroup':'3.11','BaseExceptionGroup':'3.11'}
METHODS={'add_note':'3.11','walk_path?':''}
files=set()
for l in lists:
    for line in open(os.path.join(ROOT,l)):
        line=line.strip()
        if line.endswith('.py') and not line.startswith('#'): files.add(line)
hits=[]
for f in sorted(files):
    src=open(os.path.join(ROOT,f),encoding='utf-8').read(); t=ast.parse(src)
    for n in ast.walk(t):
        if isinstance(n,ast.Attribute):
            base=n.value
            name=base.id if isinstance(base,ast.Name) else (f"{base.value.id}.{base.attr}" if isinstance(base,ast.Attribute) and isinstance(base.value,ast.Name) else None)
            if name and (name,n.attr) in NEW_ATTR: hits.append((f,n.lineno,f"{name}.{n.attr}",NEW_ATTR[(name,n.attr)]))
            if n.attr=='add_note': hits.append((f,n.lineno,'.add_note','3.11'))
        elif isinstance(n,(ast.Import,ast.ImportFrom)):
            mods=[a.name for a in n.names] if isinstance(n,ast.Import) else [n.module or '']
            for m in mods:
                if m in NEW_MOD: hits.append((f,n.lineno,'import '+m,NEW_MOD[m]))
            if isinstance(n,ast.ImportFrom):
                for a in n.names:
                    if (n.module,a.name) in NEW_ATTR: hits.append((f,n.lineno,f"from {n.module} import {a.name}",NEW_ATTR[(n.module,a.name)]))
        elif isinstance(n,ast.Name) and n.id in NEW_NAMES: hits.append((f,n.lineno,n.id,NEW_NAMES[n.id]))
        elif type(n).__name__ in ('TryStar','TypeAlias','TypeVar'): hits.append((f,n.lineno,type(n).__name__,'3.11+'))
print(json.dumps({"files":len(files),"hits":hits},indent=1))
