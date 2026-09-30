"""Read-only AST/dependency review of the six already frozen owned files."""
import ast
import copy
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
manifest = json.loads((OUT / "originals.v1.json").read_bytes())
owned = manifest["owned_originals"]

def descriptor(path):
    path = Path(path)
    raw = path.read_bytes()
    return {"path": path.relative_to(ROOT).as_posix(), "size_bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest()}

def tree(path):
    return ast.parse(Path(path).read_bytes())

def dump(value):
    if isinstance(value, list):
        return [ast.dump(node, include_attributes=False) for node in value]
    return ast.dump(value, include_attributes=False)

def functions(value):
    return {node.name: node for node in value.body if isinstance(node, ast.FunctionDef)}

def nondoc(nodes):
    return [node for node in nodes if not (isinstance(node, ast.Expr)
             and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str))]

before = [descriptor(ROOT / row["path"]) for row in owned]
original_trees, current_trees = {}, {}
for row in owned:
    original = descriptor(ROOT / row["original_copy"])
    assert all(original[key] == row[key] for key in ("size_bytes", "sha256"))
    original_trees[row["path"]] = tree(ROOT / row["original_copy"])
    current_trees[row["path"]] = tree(ROOT / row["path"])
checks = {}

# Compare original implementation bodies after removing only acquisition.
runtime_path = "scripts/publication_gstreamer_component_runtime_v1.py"
old, new = functions(original_trees[runtime_path]), functions(current_trees[runtime_path])
for original_name, current_name in (
        ("materialize_component_runtime_v1", "_materialize_component_runtime_from_selected_v1"),
        ("held_component_runtime_v1", "_held_component_runtime_from_selected_v1")):
    original_body = []
    for node in nondoc(old[original_name].body):
        if isinstance(node, ast.ImportFrom) and node.module == "publication_gstreamer_component_inputs_v1":
            continue
        if isinstance(node, ast.With) and any(isinstance(item.context_expr, ast.Call)
                and isinstance(item.context_expr.func, ast.Name)
                and item.context_expr.func.id == "held_selected_component_inputs_v1" for item in node.items):
            original_body.extend(node.body)
        else:
            original_body.append(node)
    checks[original_name + "_body_identical_after_acquisition_extraction"] = (
        dump(original_body) == dump(nondoc(new[current_name].body)))
execute = nondoc(old["execute_component_operation_v1"].body)
checks["execute_original_native_custody_body_identical"] = (
    dump(execute[-1].body) == dump(nondoc(new["_execute_component_operation_from_held_v1"].body)))
class ColdHolder(ast.NodeTransformer):
    def visit_Name(self, node):
        if node.id == "held_component_runtime_v1":
            node.id = "_held_runtime"
        return node
original_cold = [ColdHolder().visit(copy.deepcopy(node)) for node in old["_cold_component_pair_from_held_v1"].body]
checks["cold_all_existing_predicates_identical_except_private_holder_name"] = (
    dump(original_cold) == dump(new["_cold_component_pair_from_held_v1"].body))
runtime_changed = {"materialize_component_runtime_v1", "held_component_runtime_v1",
                   "execute_component_operation_v1", "cold_component_pair_v1", "_cold_component_pair_from_held_v1"}
checks["all_other_runtime_functions_identical"] = all(
    dump(node) == dump(new[name]) for name, node in old.items() if name not in runtime_changed)

inputs_path = "scripts/publication_gstreamer_component_inputs_v1.py"
old, new = functions(original_trees[inputs_path]), functions(current_trees[inputs_path])
old_runner = next(node for node in old["_model_material"].body
                  if isinstance(node, ast.FunctionDef) and node.name == "runner")
new_runner = next(node for node in new["_model_image_runner_v1"].body
                  if isinstance(node, ast.FunctionDef) and node.name == "runner")
original_runner_body = old_runner.body[:-1]
original_runner_body += [ast.Assign(targets=[ast.Name(id="raw", ctx=ast.Store())], value=old_runner.body[-1].value),
                         ast.Return(value=ast.Name(id="raw", ctx=ast.Load()))]
current_runner_body = [node for node in new_runner.body if not isinstance(node, ast.If)]
checks["original_inspect_only_command_engine_socket_timeout_parser_body_identical"] = (
    dump(original_runner_body) == dump(current_runner_body))
old_call = next(node.value for node in old["_model_material"].body if isinstance(node, ast.Return))
new_call = next(node.value for node in new["_model_material"].body if isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == "material" for target in node.targets))
checks["original_complete_model_validator_arguments_identical"] = dump(old_call) == dump(new_call)
old_selected = old["held_selected_component_inputs_v1"].body[0].body
new_selected = new["_held_selected_component_inputs_v1"].body[0].body
checks["all_original_selected_fd_engine_socket_factory_barriers_identical"] = dump([
    node for node in old_selected if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
           and isinstance(node.value.func, ast.Name) and node.value.func.id == "_verify_host_material")]) == dump([
    node for node in new_selected if not isinstance(node, ast.If)])
checks["all_other_input_functions_identical"] = all(dump(node) == dump(new[name]) for name, node in old.items()
    if name not in {"_model_material", "_verify_host_material", "held_selected_component_inputs_v1"})
old_verify, new_verify = old["_verify_host_material"], copy.deepcopy(new["_verify_host_material"])
new_verify.body = [node for node in new_verify.body if not (isinstance(node, ast.Assign)
    and any(isinstance(target, ast.Name) and target.id == "arguments" for target in node.targets))]
for node in ast.walk(new_verify):
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_model_material":
        node.keywords = [kw for kw in node.keywords if kw.arg is not None]
checks["all_original_host_checks_identical_except_private_observation_forwarding"] = (
    dump(old_verify.body) == dump(new_verify.body))

cli_path = "scripts/publication_gstreamer_component_cli_v1.py"
old, new = functions(original_trees[cli_path]), functions(current_trees[cli_path])
checks["all_other_cli_functions_identical"] = all(dump(node) == dump(new[name]) for name, node in old.items()
                                                 if name != "run_component_pair_v1")
def constants(value):
    return {node.targets[0].id: dump(node.value) for node in value.body if isinstance(node, ast.Assign)
            and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)}
checks["cli_original_2100_60_120_channel_reservation_constants_identical"] = (
    constants(original_trees[cli_path]) == constants(current_trees[cli_path]))
methods, additions = [], []
for row in owned:
    if not row["path"].startswith("tests/"):
        continue
    def test_methods(value):
        return {node.name + "." + method.name: method for node in value.body if isinstance(node, ast.ClassDef)
                for method in node.body if isinstance(method, ast.FunctionDef) and method.name.startswith("test_")}
    original, current = test_methods(original_trees[row["path"]]), test_methods(current_trees[row["path"]])
    for name, node in original.items():
        assert name in current and dump(node) == dump(current[name]), (row["path"], name)
        methods.append(row["path"] + ":" + name)
    additions.extend(row["path"] + ":" + name for name in sorted(set(current) - set(original)))
checks["original_43_unit_methods_AST_identical"] = len(methods) == 43
checks["fifteen_new_fate_provider_routing_methods"] = len(additions) == 15

# This is source discovery only; it emits no renewed host receipt or live grant.
sys.path.insert(0, str(ROOT / "scripts"))
from publication_policy_qualification_execution_code_closure_v1 import _discover_sources
sources = [path.relative_to(ROOT).as_posix() for _module, path in _discover_sources(ROOT)]
historical_closure_path = ROOT / "artifacts/gstreamer_component_release_20260930_a4e145b7/host/execution-code-closure.v5.json"
historical_closure = json.loads(historical_closure_path.read_bytes())
original_sources = {row["path"] for row in historical_closure["project_sources"]}
checks["host_AST_source_set_still_exact_87"] = len(sources) == 87 and set(sources) == original_sources
image_path = ROOT / "artifacts/benchmark_recovery_20260930/selected-gstreamer-build-a4e145b7-v1/gstreamer_custom.runtime.freeze.json"
image = json.loads(image_path.read_bytes())
source_allowlist = ROOT / "deploy/gstreamer_custom/publication/runtime-source-allowlist.txt"
dependency_allowlist = ROOT / "deploy/gstreamer_custom/publication/runtime-dependency-allowlist.txt"
def allowlist(path):
    return [line for line in path.read_text().splitlines() if line and not line.startswith("#")]
selected_sources, selected_dependencies = allowlist(source_allowlist), allowlist(dependency_allowlist)
def aggregate(paths):
    return hashlib.sha256(b"".join((descriptor(ROOT / name)["sha256"] + "  " + name + "\n").encode("ascii")
                                  for name in sorted(paths))).hexdigest()
image_source = image["physical_identity"]["source_identity"]
checks["selected_image_73_original_physical_sources_equal"] = (
    len(selected_sources) == image_source["runtime_source_count"] == 73 and
    aggregate(selected_sources) == image_source["runtime_source_sha256"])
checks["selected_image_six_original_dependencies_equal"] = (
    len(selected_dependencies) == image_source["dependency_count"] == 6 and
    aggregate(selected_dependencies) == image_source["dependency_set_sha256"])
production_owned = {row["path"] for row in owned if row["path"].startswith("scripts/")}
checks["three_owned_host_scripts_outside_selected_image_sources_dependencies"] = not (
    production_owned & set(selected_sources + selected_dependencies))
execution_path = OUT / "attempt-04-focused/execution.json"
execution = json.loads(execution_path.read_bytes())
checks["original_focused_terminal_58_green_six_pins_stable_quiescent"] = (
    execution["returncode"] == 0 and not execution["timed_out"] and execution["source_stable"]
    and not execution["capture_errors"] and not execution["readers_alive"]
    and execution["original_pid_absent"] and not execution["process_group_members_after"]
    and b"Ran 58 tests" in (OUT / "attempt-04-focused/stderr.bin").read_bytes())
after = [descriptor(ROOT / row["path"]) for row in owned]
checks["frozen_six_before_after_equal"] = before == after

report = {"schema_version": 1, "kind": "vast_component_held_session_author_review_v1", "accepted": False,
    "planning_commit": manifest["planning_commit"], "pr_comment": manifest["pr_comment"],
    "independent_planning_review": manifest["independent_review"], "owned_source_pins": after,
    "originals_manifest": descriptor(OUT / "originals.v1.json"), "audit_script": descriptor(Path(__file__)),
    "checks": checks, "all_checks_pass": all(checks.values()), "original_test_methods": methods,
    "new_test_methods": additions, "focused_execution": descriptor(execution_path),
    "focused_original_channels": [descriptor(OUT / "attempt-04-focused" / (name + ".bin")) for name in ("stdout", "stderr")],
    "historical_host_v5_receipt": descriptor(historical_closure_path), "host_source_count": len(sources),
    "new_host_modules": sorted(set(sources) - original_sources), "selected_original_image_receipt": descriptor(image_path),
    "selected_source_count": len(selected_sources), "selected_source_sha256": aggregate(selected_sources),
    "selected_dependency_count": len(selected_dependencies), "selected_dependency_sha256": aggregate(selected_dependencies),
    "semantic_change": "Source materialization keeps its two original assessments; default CLI performs one complete held assessment, then five private borrow boundaries each freshly observe four original stock image projections. Public standalone entrypoints remain independent. Existing full raw hashes, FD/path/epoch barriers, original native wrappers and cold validators remain in use.",
    "limitations": ["Unit metadata and expensive model/transport acceptance are explicit fixtures, not physical model/image/benchmark acceptance.",
        "No new complete host receipt is issued: v5 is historical and stale for the three host edits; root must freeze a new closure before hardware dispatch.",
        "No measured speedup, cold CPU04 recovery, GPU run, full CI, OpenSpec completion or archive is claimed.",
        "Original model observer subprocess capture behavior is unchanged; only the nonauthorizing phase JSONL is bounded to twelve fixed phase pairs and 16KiB.",
        "Earlier original red/failed attempts and raw channels remain immutable; no attempt is relabeled."],
    "self_review": {"unnecessary_framework": "No production module, public cache, fake partial assessor, skip mode, new dependency, altered numerical threshold or deadline was added. Private helpers share existing bodies.",
        "practical_limit": "Full ComponentPins verification still rehashes the held source closure; actual preparation latency remains a hardware measurement question.",
        "fate": "Failures retire the private session and owned cleanup, preserve the original exception, and retain real timing starts without fabricated later terminals."}}
report["sha256"] = hashlib.sha256(json.dumps(report, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
target = OUT / "author-review.v1.json"
with target.open("xb") as stream:
    stream.write(json.dumps(report, sort_keys=True, indent=2).encode() + b"\n")
    stream.flush()
    os.fsync(stream.fileno())
print(json.dumps({"report": descriptor(target), "all_checks_pass": report["all_checks_pass"],
                  "failed": [name for name, value in checks.items() if not value]}))
if not report["all_checks_pass"]:
    raise SystemExit(1)
