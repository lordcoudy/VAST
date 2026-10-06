"""Static-ish check: names loaded as globals in any function that the module does not define (NameError class)."""
import builtins, dis, importlib, sys, types
sys.path.insert(0, sys.argv[1] + "/scripts")
mods = sys.argv[2:]
for name in mods:
    m = importlib.import_module(name)
    known = set(vars(m)) | set(dir(builtins))
    seen = {}
    def walk(code, owner):
        for ins in dis.get_instructions(code):
            if ins.opname in ("LOAD_GLOBAL", "LOAD_NAME") and ins.argval not in known:
                seen.setdefault(ins.argval, set()).add(owner + ":" + str(code.co_firstlineno))
        for const in code.co_consts:
            if isinstance(const, types.CodeType):
                walk(const, owner + "." + const.co_name)
    src = open(m.__file__, encoding="utf-8").read()
    walk(compile(src, m.__file__, "exec"), name)
    for missing, where in sorted(seen.items()):
        print(name, "UNDEFINED", missing, sorted(where)[:4])
print("checked", len(mods))
import ast
for name in mods:
    m = importlib.import_module(name)
    tree = ast.parse(open(m.__file__, encoding="utf-8").read())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            try:
                target = importlib.import_module(node.module)
            except Exception as error:
                print(name, "IMPORT-MODULE", node.module, node.lineno, type(error).__name__, str(error)[:120]); continue
            for alias in node.names:
                if alias.name != "*" and not hasattr(target, alias.name):
                    try: importlib.import_module(node.module + "." + alias.name)
                    except Exception: print(name, "IMPORT-NAME", node.module + "." + alias.name, "line", node.lineno)
print("imports checked")
