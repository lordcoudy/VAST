#!/usr/bin/env python3
"""Re-derive the saved qfb pin plan, verify it, and render the planned unified diff.

Checks: saved plan bytes are reproduced exactly; per file the AST is unchanged after
normalizing string constants and the integer constants at planned size sites; every
edited line is a planned line. Writes host-pin-rebind.planned.patch (exclusive create).
"""
import ast
import difflib
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("qfb_pins", HERE / "rebind_host_identity_pins_qfb_v4.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

saved_raw = (HERE / "host-pin-rebind.plan.v1.json").read_bytes()
plans, mapping, _, _, _, configs = module.plan_all()
derived = (json.dumps(module.report(plans, mapping, configs, "planned"), sort_keys=True, indent=1) + "\n").encode()
assert derived == saved_raw, "saved plan is not reproduced"


class Normalize(ast.NodeTransformer):
    def __init__(self, size_lines):
        self.size_lines = size_lines

    def visit_Constant(self, node):
        if isinstance(node.value, str):
            node.value = ""
        elif type(node.value) is int and node.lineno in self.size_lines:
            node.value = 0
        return node


patch = []
summary = []
for row in plans:
    size_lines = {edit["line"] for edit in row["edits"] if "size" in edit["kind"]}
    before = ast.dump(Normalize(size_lines).visit(ast.parse(row["before"])), include_attributes=False)
    after = ast.dump(Normalize(size_lines).visit(ast.parse(row["after"])), include_attributes=False)
    assert before == after, "non-pin AST changed: " + row["file"]
    old_lines = row["before"].decode().splitlines(keepends=True)
    new_lines = row["after"].decode().splitlines(keepends=True)
    assert len(old_lines) == len(new_lines)
    changed = {index + 1 for index, (a, b) in enumerate(zip(old_lines, new_lines)) if a != b}
    planned = {edit["line"] for edit in row["edits"]}
    assert changed == planned, f"changed lines differ from planned lines: {row['file']}"
    patch.extend(difflib.unified_diff(old_lines, new_lines, fromfile="a/" + row["file"],
                                      tofile="b/" + row["file"]))
    summary.append({"file": row["file"], "changed_lines": sorted(changed), "edits": len(row["edits"])})
payload = "".join(patch).encode()
with (HERE / "host-pin-rebind.planned.patch").open("xb") as stream:
    stream.write(payload)
print(json.dumps({"status": "verified_plan_rendered", "plan_sha256": hashlib.sha256(saved_raw).hexdigest(),
                  "mapping_size": len(mapping), "non_pin_ast_unchanged": True,
                  "changed_lines_equal_planned_lines": True, "files": summary,
                  "patch_bytes": len(payload), "patch_sha256": hashlib.sha256(payload).hexdigest()},
                 sort_keys=True, indent=1))
