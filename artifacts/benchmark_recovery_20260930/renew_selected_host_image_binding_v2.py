"""Renew six static host bindings from one closed actual selected image receipt."""
import ast
import hashlib
import json
from pathlib import Path
import pprint
import sys

ROOT = Path.cwd()
BASE = ROOT / "artifacts/benchmark_recovery_20260930"
SOURCE = ROOT / "scripts/checkpoint_gstreamer_publication_runtime_v3.py"
RECEIPT = BASE / "selected-gstreamer-build-a4e145b7-v1/gstreamer_custom.runtime.freeze.json"
OUTPUT = BASE / "component-host-image-binding-renewal-v3"
sys.path.insert(0, str(ROOT / "scripts"))
from publication_qualification_image_refreeze_v1 import load_runtime_image_receipt
import checkpoint_gstreamer_publication_runtime_v3 as original


def facts(path):
    data = path.read_bytes()
    return {"path": path.relative_to(ROOT).as_posix(), "size_bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest()}


assert facts(RECEIPT) == {
    "path": RECEIPT.relative_to(ROOT).as_posix(), "size_bytes": 7049,
    "sha256": "61874c718d6140d0d5cf745988bc301b916077af8f80e96742184f80a0805db7"}
receipt = load_runtime_image_receipt(RECEIPT)
assert receipt["candidate_binding_eligible"] is True and receipt["blockers"] == []
physical = receipt["physical_identity"]
assert physical["image_id"] == "sha256:e474867043f1a74387573140cb2bfd69825df2672edad0acda0d28954af84cb6"
assert physical["base"]["image_id"] == original.EXPECTED_BASE_IMAGE_ID
assert physical["entrypoint"] == [original.EXPECTED_IMAGE_ENTRYPOINT]
assert physical["user"] == original.EXPECTED_IMAGE_USER
assert physical["architecture"] == "amd64" and physical["os"] == "linux"
assert physical["created"] == "1970-01-01T00:00:00Z"
assert physical["observed_repository_digests"] == [physical["canonical_repository_digest"]]
assert set(physical["labels"]) == set(original.EXPECTED_IMAGE_LABELS)
assert set(physical["embedded_files"]) == set(original.EXPECTED_EMBEDDED_ARTIFACTS)
assert len(physical["embedded_files"]) == 11
assert "scripts/checkpoint_gstreamer_publication_runtime_v3.py" not in (
    ROOT / "deploy/gstreamer_custom/publication/runtime-source-allowlist.txt").read_text().splitlines()
changes = {
    "EXPECTED_IMAGE_REFERENCE": physical["final_reference"],
    "EXPECTED_IMAGE_ID": physical["image_id"],
    "EXPECTED_REPOSITORY_DIGEST": physical["canonical_repository_digest"],
    "EXPECTED_IMAGE_INSPECT_PROJECTION_SHA256": physical["inspect_projection_sha256"],
    "EXPECTED_IMAGE_LABELS": physical["labels"],
    "EXPECTED_EMBEDDED_ARTIFACTS": physical["embedded_files"],
}
before = SOURCE.read_bytes()
tree = ast.parse(before)
assignments = {node.targets[0].id: node for node in tree.body
               if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)}
old = {name: ast.literal_eval(assignments[name].value) for name in changes}
assert old["EXPECTED_IMAGE_ID"] == "sha256:88778ac8b7b91ca90b8d0f03c48823898fc8438ab9b0ad1df7548746792e2f4f"
image = {"image_id": physical["image_id"], "repository_digest": physical["canonical_repository_digest"],
         "inspect_projection_sha256": physical["inspect_projection_sha256"], "base_image_id": physical["base"]["image_id"]}
try:
    original._validate_image(image)
except original.NativePublicationPermanentErrorV3 as error:
    first_blocker = str(error)
else:
    raise AssertionError("Expected actual selected image to be rejected by stale original host binding")
assert "gstreamer_container_image_contract_invalid" in first_blocker
OUTPUT.mkdir(exist_ok=False)
snapshot_path = OUTPUT / "original-host-wrapper.raw"
snapshot_path.write_bytes(before)
pre = {"schema_version": 1, "artifact_kind": "vast_selected_host_image_binding_before_edit_v1",
       "source": facts(SOURCE), "snapshot": facts(snapshot_path), "receipt": facts(RECEIPT),
       "original_bindings": old, "proposed_actual_bindings": changes, "actual_pre_edit_gate_blocker": first_blocker,
       "model_transaction_or_runtime_execution": False,
       "scope": "Decision23 task18.6 static host identity renewal only; old aggregate association unchanged"}
with (OUTPUT / "before-edit.v1.json").open("x", encoding="utf-8", newline="\n") as stream:
    json.dump(pre, stream, sort_keys=True, separators=(",", ":")); stream.write("\n")
lines = before.splitlines(keepends=True)
newline = b"\r\n" if before.count(b"\r\n") == before.count(b"\n") else b"\n"
for name, node in sorted(((name, assignments[name]) for name in changes), key=lambda row: row[1].lineno, reverse=True):
    text = name + " = " + pprint.pformat(changes[name], sort_dicts=True, width=100)
    replacement = newline.join(text.encode().splitlines()) + newline
    lines[node.lineno - 1:node.end_lineno] = [replacement]
after = b"".join(lines)
updated_tree = ast.parse(after)
def nonbindings(value):
    return ast.dump(ast.Module(body=[node for node in value.body if not (
        isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id in changes)], type_ignores=[]), include_attributes=False)
assert nonbindings(tree) == nonbindings(updated_tree)
assert SOURCE.read_bytes() == before
SOURCE.write_bytes(after)
result = {"schema_version": 1, "artifact_kind": "vast_selected_host_image_binding_renewal_v1",
          "source_before": pre["source"], "source_after": facts(SOURCE), "receipt": facts(RECEIPT),
          "renewed_constants": changes, "nonbinding_ast_unchanged": True,
          "selected_runtime_image_invalidation": False, "native3_worker2_invalidation": False,
          "old_host_closure_invalidated": True, "new_host_closure_required": True,
          "old_aggregate_parity_rebound": False, "hardware_acceptance": False,
          "independent_source_review_pending": True}
with (OUTPUT / "renewal.v1.json").open("x", encoding="utf-8", newline="\n") as stream:
    json.dump(result, stream, sort_keys=True, separators=(",", ":")); stream.write("\n")
print(json.dumps({"source_after": result["source_after"], "receipt": facts(OUTPUT / "renewal.v1.json"),
                  "nonbinding_ast_unchanged": True}))
