"""Static gate: finite-study runtime modules must not reference undefined globals.

Two never-executed study paths failed or would fail with NameError on real
hardware (attempt I: ``threading`` in ``run_finite_study_arm_v1``; latent:
``_require`` in ``persist_study_operational_v1``). This stdlib-only check
compiles each module without importing it, collects the module's top-level
bindings from its AST, and refuses any ``LOAD_GLOBAL`` inside a function that
is neither such a binding nor a builtin. Local ``from X import Y`` targets in
``scripts/`` must define ``Y`` at their top level.
"""
from __future__ import annotations

import ast
import builtins
import dis
from pathlib import Path
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
ALLOWLIST = ROOT / "deploy/gstreamer_custom/publication/runtime-source-allowlist.txt"
DRIVER_MODULES = ("run_canonical_systems_study_v1", "reduce_canonical_systems_study_v1",
                  "canonical_systems_study_plan_v1")


WORKER_FILES = ("deploy/analytics_execution/openvino_worker.py", "deploy/analytics_execution/tensorrt_worker.py")


def _local_imports(path):
    names = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        candidates = ([alias.name for alias in node.names] if isinstance(node, ast.Import) else
                      [node.module] if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module else [])
        names.update(name for name in candidates if (SCRIPTS / (name + ".py")).is_file())
    return names


def study_modules():
    """Runtime-image scripts, the driver/reducer/plan and their transitive local import closure."""
    pending = {line.strip()[len("scripts/"):-3] for line in ALLOWLIST.read_text().splitlines()
               if line.strip().startswith("scripts/") and line.strip().endswith(".py")} | set(DRIVER_MODULES)
    closure = set()
    while pending:
        name = pending.pop()
        if name not in closure:
            closure.add(name)
            pending |= _local_imports(SCRIPTS / (name + ".py")) - closure
    return sorted(closure)


def study_paths():
    return [SCRIPTS / (name + ".py") for name in study_modules()] + [ROOT / name for name in WORKER_FILES]


def _bound_names(target, names):
    for node in ast.walk(target):
        if isinstance(node, ast.Name):
            names.add(node.id)


def top_level_bindings(tree):
    """Names a module binds outside function/class bodies, plus explicit ``global`` declarations."""
    names, star = set(), False

    def visit(statements):
        nonlocal star
        for node in statements:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(node.name)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    if alias.name == "*":
                        star = True
                    else:
                        names.add(alias.asname or alias.name.split(".")[0])
            elif isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
                for target in node.targets if isinstance(node, ast.Assign) else [node.target]:
                    _bound_names(target, names)
            elif isinstance(node, (ast.For, ast.AsyncFor)):
                _bound_names(node.target, names)
            elif isinstance(node, (ast.With, ast.AsyncWith)):
                for item in node.items:
                    if item.optional_vars is not None:
                        _bound_names(item.optional_vars, names)
            elif isinstance(node, ast.Try):
                for handler in node.handlers:
                    if handler.name:
                        names.add(handler.name)
            for field in ("body", "orelse", "finalbody", "handlers"):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    children = getattr(node, field, None)
                    if isinstance(children, list):
                        visit([child for child in children if isinstance(child, ast.AST) and
                               not isinstance(child, ast.ExceptHandler)] if field != "handlers" else
                              [stmt for handler in children for stmt in handler.body])
    visit(tree.body)
    for node in ast.walk(tree):
        if isinstance(node, ast.Global):
            names.update(node.names)
        elif isinstance(node, ast.NamedExpr):
            _bound_names(node.target, names)
    return names, star


def undefined_globals(path):
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    names, star = top_level_bindings(tree)
    known = names | set(dir(builtins)) | {"__file__", "__name__", "__doc__", "__spec__", "__loader__",
                                          "__builtins__", "__package__", "__path__", "__annotations__"}
    missing = {}

    def walk(code):
        if code.co_flags & 0x1:  # CO_OPTIMIZED: a function body
            for instruction in dis.get_instructions(code):
                if instruction.opname == "LOAD_GLOBAL" and instruction.argval not in known:
                    missing.setdefault(instruction.argval, set()).add(code.co_firstlineno)
        for constant in code.co_consts:
            if isinstance(constant, types.CodeType):
                walk(constant)
    walk(compile(source, str(path), "exec"))
    return ({} if star else missing), tree


class FiniteStudyStaticNamesTests(unittest.TestCase):
    def test_study_modules_reference_only_defined_globals_and_local_imports(self):
        modules = study_modules()
        for required in ("checkpoint_gstreamer_runtime", "checkpoint_native_policy_runtime",
                         "publication_gstreamer_component_inputs_v1", "publication_image_build_v1"):
            self.assertIn(required, modules)
        failures, trees = [], {}
        for path in study_paths():
            name = path.stem
            missing, trees[name] = undefined_globals(path)
            failures.extend(f"{name}: undefined {symbol} (lines {sorted(lines)})" for symbol, lines in sorted(missing.items()))
        for name, tree in trees.items():
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module and \
                        (SCRIPTS / (node.module + ".py")).is_file():
                    exported, star = top_level_bindings(ast.parse((SCRIPTS / (node.module + ".py")).read_text(encoding="utf-8")))
                    failures.extend(f"{name}:{node.lineno}: {node.module} lacks {alias.name}" for alias in node.names
                                    if alias.name != "*" and not star and alias.name not in exported)
        self.assertEqual(failures, [])

    def test_study_operational_persistence_refuses_a_missing_context_with_its_own_error(self):
        import sys
        import threading
        sys.path.insert(0, str(SCRIPTS))
        import checkpoint_native_policy_runtime as runtime
        coordinator = object.__new__(runtime.NativePolicyRuntimeCoordinator)
        coordinator._lock = threading.RLock()
        coordinator._operational_context = None
        with self.assertRaisesRegex(runtime.NativePolicyRuntimeError, "separately typed context"):
            coordinator.persist_study_operational_v1(measurement_input_keys=())

    def test_checker_refuses_a_real_undefined_function_global(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "fixture.py"
            path.write_text("import os\nVALUE = 1\nclass C:\n    x = VALUE\n"
                            "def f():\n    return threading.Lock(), os.sep, VALUE, len\n")
            missing, _ = undefined_globals(path)
        self.assertEqual(sorted(missing), ["threading"])


if __name__ == "__main__":
    unittest.main()
