"""Close the exact cold-provider repair without any workload or engine call."""
import ast
import hashlib
import json
from pathlib import Path

root = Path.cwd()
base = Path(__file__).parent
paths = ("scripts/publication_gstreamer_component_runtime_v1.py",
         "tests/test_publication_gstreamer_component_runtime_v1.py")
def descriptor(path):
    raw = path.read_bytes()
    return {"path": str(path.relative_to(root)), "size_bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest()}
before = [(base / "before" / Path(path).name).read_bytes() for path in paths]
after = [(root / path).read_bytes() for path in paths]
old = b"from publication_operational_request_domain_v1 import load_operational_jsonl_header_v1"
new = b"from publication_operational_request_reconciliation_v1 import load_operational_jsonl_header_v1"
assert before[0].count(old) == 1 and after[0] == before[0].replace(old, new)
def methods(raw):
    return {node.name + "." + method.name: ast.dump(method, include_attributes=False)
            for node in ast.parse(raw).body if isinstance(node, ast.ClassDef)
            for method in node.body if isinstance(method, ast.FunctionDef)}
old_methods, new_methods = methods(before[1]), methods(after[1])
assert all(new_methods[name] == value for name, value in old_methods.items())
added = sorted(set(new_methods) - set(old_methods))
assert len(added) == 2 and all(name.startswith("ColdProviderBoundaryTests.") for name in added)
red = json.loads((base / "red-01/terminal.v1.json").read_bytes())
green = json.loads((base / "green-01/terminal.v1.json").read_bytes())
for receipt in (red, green):
    assert receipt["sources_stable"] and not receipt["timed_out"] and not receipt["capture_exceeded"]
    assert receipt["original_child_current"] is None and receipt["original_group_members"] == []
assert red["original_child_returncode"] == 1 and green["original_child_returncode"] == 0
assert b"ImportError: cannot import name 'load_operational_jsonl_header_v1'" in (base / "red-01/stderr.raw").read_bytes()
assert b"Ran 14 tests" in (base / "green-01/stderr.raw").read_bytes()
for path in paths:
    row = green["source_after"][path]
    actual = descriptor(root / path)
    assert row["sha256"] == actual["sha256"] and row["size_bytes"] == actual["size_bytes"]
value = {"artifact_kind": "vast_component_cold_provider_repair_author_review_v1",
         "source": [descriptor(root / path) for path in paths],
         "exact_one_import_provider_change": True, "all_original_method_asts_retained": True,
         "added_tests": added, "red": descriptor(base / "red-01/terminal.v1.json"),
         "green": descriptor(base / "green-01/terminal.v1.json"),
         "green_actual_tests": 14, "no_workload_or_engine_call": True,
         "original_cpu04_cli_status": "failed_immutable", "complete_cold_pair_accepted": False,
         "next_gate": "Separately reviewed corrected reader against unchanged physical v5 sources before new native measurement; fresh production source closure required after source changes."}
destination = base / "author-review.v1.json"
with destination.open("xb") as stream:
    stream.write((json.dumps(value, sort_keys=True, indent=2) + "\n").encode())
print(json.dumps(descriptor(destination)))
