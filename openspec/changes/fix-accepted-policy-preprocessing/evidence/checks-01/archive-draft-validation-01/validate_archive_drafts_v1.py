#!/usr/bin/env python3
"""Syntax and explicit AST equivalence only; never import or run draft modes."""
from __future__ import annotations

import ast
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys


BASE = Path("/mnt/c/Users/s-a-balashov/.codex/worktrees/fix-accepted-policy-preprocessing/VAST/openspec/changes/fix-accepted-policy-preprocessing/evidence/checks-01")
PYTHON = Path("/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python")
HASHES = {
    "copy_fresh_check_inputs.py": "dfe4456b27f2bbadcc1866d5a08f2be4e5cf5d73da03bf53705e13f57fbe5243",
    "copy_fresh_check_inputs_v2.py": "1360c08500c0006dcc06f4908c73c782a39a6fe67fcf7dcfff43acfd6eabe3d0",
    "compare_final_source_inputs_v2.py": "3c55fb6d43aa7873622f936de3d573969f161a691684f05c79f124a8ddb7bb57",
    "compare_final_source_inputs_v3.py": "246ffcfb9e9b3a8841435166d0a8e65c548aeacbb56b48d66f1607c4d5f70ea2",
    "run_archive_checks_v1.sh": "5058f38055b534f356ce68d4d1cc75ebf96a08059cb86d7038dab7b323af1fed",
    "run_focused_suite.sh": "237ae90c628d187b9d6e66847b3176f24f399d7ed700350df9257d983477ca42",
    "run_ext4_suite.sh": "045cdded701dfb59100ce600344079f615a7be5991778befa4123eb209cb106d",
    "private_runtime_namespace.sh": "19197711989ce2693ddeae547b65dd30579a7a33e7e5d751ea6656296494c36e",
}


def require(value: bool, message: str) -> None:
    if not value:
        raise ValueError(message)


def dump(node: ast.AST) -> str:
    return ast.dump(node, annotate_fields=True, include_attributes=False)


def node(source: str) -> ast.stmt:
    body = ast.parse(source).body
    require(len(body) == 1, "expected exactly one declared adapter statement")
    return body[0]


def remove_exact(body: list[ast.stmt], source: str) -> None:
    expected = dump(node(source))
    positions = [index for index, item in enumerate(body) if dump(item) == expected]
    require(len(positions) == 1, "declared adapter statement is absent or duplicated: " + source)
    del body[positions[0]]


def main_function(tree: ast.Module) -> ast.FunctionDef:
    matches = [item for item in tree.body if isinstance(item, ast.FunctionDef) and item.name == "main"]
    require(len(matches) == 1, "main function is absent or duplicated")
    return matches[0]


def strip_module_docstring(tree: ast.Module) -> None:
    require(isinstance(tree.body[0], ast.Expr) and isinstance(tree.body[0].value, ast.Constant)
            and type(tree.body[0].value.value) is str, "module docstring differs")
    del tree.body[0]


def normalize_metadata(tree: ast.Module, old_kind: str, new_kind: str, additions: dict[str, str]) -> None:
    matches = []
    for item in ast.walk(tree):
        if isinstance(item, ast.Dict):
            for index, key in enumerate(item.keys):
                if isinstance(key, ast.Constant) and key.value == "artifact_kind":
                    if dump(item.values[index]) == dump(ast.Constant(value=new_kind)):
                        matches.append((item, index))
    require(len(matches) == 1, "declared new report dictionary differs")
    item, index = matches[0]
    item.values[index] = ast.Constant(value=old_kind)
    for key_value, value_source in additions.items():
        positions = [i for i, key in enumerate(item.keys)
                     if isinstance(key, ast.Constant) and key.value == key_value]
        require(len(positions) == 1, "declared new metadata key differs")
        i = positions[0]
        require(dump(item.values[i]) == dump(ast.parse(value_source, mode="eval").body),
                "declared new metadata value differs")
        del item.keys[i]
        del item.values[i]


def compare_fresh(payloads: dict[str, bytes]) -> dict:
    old = ast.parse(payloads["copy_fresh_check_inputs.py"].decode("ascii"))
    new = ast.parse(payloads["copy_fresh_check_inputs_v2.py"].decode("ascii"))
    for tree in (old, new):
        strip_module_docstring(tree)
    remove_exact(new.body, "from datetime import date")
    origins = [item for item in new.body if isinstance(item, ast.FunctionDef) and item.name == "recipe_origin"]
    require(len(origins) == 1, "new origin adapter differs")
    origin_sha = hashlib.sha256(dump(origins[0]).encode("ascii")).hexdigest()
    new.body.remove(origins[0])
    old_main, new_main = main_function(old), main_function(new)
    remove_exact(old_main.body, 'recipe_relative = Path("openspec/changes/fix-accepted-policy-preprocessing/evidence/checks-01/copy_fresh_check_inputs.py")')
    remove_exact(old_main.body, 'require(any(Path(__file__).resolve() == root / recipe_relative for root in copier_roots), "copier must come from the selected frozen check source or destination root")')
    for source in (
        "self_path = Path(__file__)",
        "origins = [recipe_origin(root, commit, self_path) for root in copier_roots if self_path.is_relative_to(root)]",
        'require(len(origins) == 1 and self_path.name == "copy_fresh_check_inputs_v2.py", "copier must have one exact committed source or destination recipe origin")',
        "selected_origin = origins[0]",
    ):
        remove_exact(new_main.body, source)
    normalize_metadata(new, "vast_fresh_check_input_copy_v1", "vast_fresh_check_input_copy_v2",
                       {"copier_origin": "selected_origin", "sealed_v1_copy_predicates_preserved": "True"})
    require(dump(old) == dump(new), "fresh-copy operational module AST changed beyond declared adapters")
    return {"normalized_entire_operational_module_ast_equal": True,
            "normalized_ast_sha256": hashlib.sha256(dump(old).encode("ascii")).hexdigest(),
            "disclosed_recipe_origin_ast_sha256": origin_sha}


class EvidenceAlias(ast.NodeTransformer):
    def visit_Name(self, item: ast.Name) -> ast.AST:
        if item.id == "evidence":
            item.id = "EVIDENCE"
        return item


def compare_source(payloads: dict[str, bytes]) -> dict:
    old = ast.parse(payloads["compare_final_source_inputs_v2.py"].decode("ascii"))
    new = ast.parse(payloads["compare_final_source_inputs_v3.py"].decode("ascii"))
    for tree in (old, new):
        strip_module_docstring(tree)
    remove_exact(old.body, 'EVIDENCE = Path("openspec/changes/fix-accepted-policy-preprocessing/evidence/physical-01")')
    remove_exact(new.body, "from copy_fresh_check_inputs_v2 import recipe_origin")
    body = main_function(new).body
    for source in (
        "self_path = Path(__file__)",
        'require(self_path.name == "compare_final_source_inputs_v3.py", "comparison helper identity differs")',
        "origin = recipe_origin(root, source_commit, self_path)",
        'evidence = Path(origin["change_relative"]) / "evidence/physical-01"',
    ):
        remove_exact(body, source)
    aliases = [item for item in ast.walk(new) if isinstance(item, ast.Name) and item.id == "evidence"]
    require(len(aliases) == 2 and all(isinstance(item.ctx, ast.Load) for item in aliases), "evidence adapter uses differ")
    EvidenceAlias().visit(new)
    normalize_metadata(new, "vast_final_repair_source_input_comparison_v1",
                       "vast_final_repair_source_input_comparison_v3",
                       {"helper_origin": "origin", "sealed_v2_byte_and_graph_predicates_preserved": "True"})
    require(dump(old) == dump(new), "source comparison module AST changed beyond declared adapters")
    return {"normalized_entire_predicate_module_ast_equal": True,
            "normalized_ast_sha256": hashlib.sha256(dump(old).encode("ascii")).hexdigest()}


def snapshot() -> dict[str, bytes]:
    require(BASE.resolve(strict=True) == BASE, "managed validation base is aliased")
    result = {}
    for name, expected in HASHES.items():
        path = BASE / name
        require(path.resolve(strict=True) == path and path.is_file(), "validation input is aliased or absent")
        payload = path.read_bytes()
        require(hashlib.sha256(payload).hexdigest() == expected, "reviewed validation input hash changed: " + name)
        result[name] = payload
    return result


def validate() -> int:
    before = snapshot()
    result = {"artifact_kind": "vast_archive_check_draft_static_validation_v1",
              "fresh_copy": compare_fresh(before), "source_comparison": compare_source(before),
              "reviewed_input_sha256": HASHES}
    shell = before["run_archive_checks_v1.sh"].decode("ascii")
    heredocs = re.findall(r"(?m)^[^\n]*<<'PY'\n([\s\S]*?)^PY\n", shell)
    require(len(heredocs) == 7, "new shell Python block count differs")
    for index, body in enumerate(heredocs):
        ast.parse(body, filename="run_archive_checks_v1.sh:Python-block-" + str(index + 1))
    original_full = before["run_ext4_suite.sh"].decode("ascii")
    original_docs = re.findall(r"(?m)^[^\n]*<<'PY'\n([\s\S]*?)^PY\n", original_full)
    require(len(original_docs) == 2, "sealed full Python block count differs")
    require(dump(ast.parse(original_docs[-1])) == dump(ast.parse(heredocs[-1])), "strict portable report predicates changed")
    require(dump(ast.parse(original_docs[0])) == dump(ast.parse(heredocs[-2])), "ordinary observed-limit predicates changed")
    pattern = r"(?m)^\s*MODULES=\(\n((?:\s+tests\.[a-zA-Z0-9_]+\n)+)\s*\)$"
    old_modules = re.findall(pattern, before["run_focused_suite.sh"].decode("ascii"))
    new_modules = re.findall(pattern, shell)
    require(len(old_modules) == len(new_modules) == 1, "focused module declaration differs")
    require(old_modules[0].split() == new_modules[0].split() and len(new_modules[0].split()) == 33,
            "focused ordered33 modules changed")
    bash_command = ["/bin/bash", "-n", str(BASE / "run_archive_checks_v1.sh")]
    checked = subprocess.run(bash_command, capture_output=True, check=False)
    sys.stderr.buffer.write(checked.stderr)
    require(checked.returncode == 0 and not checked.stdout, "Bash syntax check failed or produced stdout")
    require(snapshot() == before, "reviewed originals or drafts changed during validation")
    result.update({"passed": True, "reviewed_bytes_before_after_unchanged": True,
                   "python_module_parse_count": 4, "embedded_python_parse_count": len(heredocs),
                   "focused_ordered_module_count": 33, "strict_portable_report_ast_equal": True,
                   "ordinary_observed_limit_ast_equal": True,
                   "bash_syntax_command": bash_command, "bash_syntax_original_rc": checked.returncode,
                   "launcher_modes_executed": False, "reviewed_module_imports": False,
                   "source_clone_copy_mount_archive_actions": False, "qualification_authority": False})
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0


def capture() -> int:
    require(Path(__file__).resolve(strict=True) == BASE / "archive-draft-validation-01/validate_archive_drafts_v1.py",
            "capture helper physical origin differs")
    out = Path(__file__).parent / "controls"
    require(not out.exists() and not out.is_symlink(), "static validation controls already exist")
    before = snapshot()
    out.mkdir(mode=0o700)
    command = [str(PYTHON), "-B", str(Path(__file__)), "--validate"]
    (out / "command.json").write_text(json.dumps(command, indent=2) + "\n", encoding="ascii")
    (out / "started.txt").write_text(datetime.now(timezone.utc).isoformat() + "\n", encoding="ascii")
    with (out / "original.stdout.log").open("xb") as stdout, (out / "original.stderr.log").open("xb") as stderr:
        child = subprocess.run(command, stdout=stdout, stderr=stderr, check=False)
    (out / "original.rc.txt").write_text(str(child.returncode) + "\n", encoding="ascii")
    (out / "finished.txt").write_text(datetime.now(timezone.utc).isoformat() + "\n", encoding="ascii")
    after = snapshot()
    require(before == after, "reviewed files changed across captured validation")
    (out / "reviewed-bytes.before-after.json").write_text(
        json.dumps({"passed": True, "sha256": HASHES, "unchanged": True}, sort_keys=True, indent=2) + "\n", encoding="ascii")
    print(json.dumps({"original_rc": child.returncode, "controls": str(out), "reviewed_bytes_unchanged": True}))
    return child.returncode


if __name__ == "__main__":
    require(sys.flags.optimize == 0 and Path(sys.executable) == PYTHON, "canonical unoptimized Python required")
    require(sys.argv[1:] in (["--capture"], ["--validate"]), "one explicit static-only mode required")
    raise SystemExit(capture() if sys.argv[1:] == ["--capture"] else validate())
