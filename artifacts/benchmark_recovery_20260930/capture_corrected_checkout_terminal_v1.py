"""Close actual checkout/tool observations; no clone/source/model operation."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
sys.dont_write_bytecode = True
ROOT = Path("/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec")
DIRECTORY = "artifacts/benchmark_recovery_20260930/"
SCRIPT = ROOT / DIRECTORY / "verify_checkout_byte_freeze_v9.py"
spec = importlib.util.spec_from_file_location("closed_checkout_observer_v9", SCRIPT)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
pins = {
    "controller-lf-attributes-preparation.v1.json": "0ee823284c2aca4c22bcf9033b487e64e8a43b2a2700c7529c173085d471e49e",
    "byte-freeze-tiny-git-controller-regression.v3.json": "74182dabf30cf46c7672e7874786c51f70f73fdf301c495d89b30a5ad2c14b5f",
    "byte-freeze-fresh-checkouts.v7.json": "3c27a97f3132e84707f9849e4bf6939fd8a6de64173f2f5549251299bbdc7bf3",
    "byte-freeze-fresh-checkouts.v7.source.json": "7def15c706a49ed03ff6b87d4900873c129eb4d9ba4b29b9ce5aa409d1f76104",
    "byte-freeze-fresh-checkouts.v7.autocrlf-false.json": "0ce5450ecfd0829b548ca765b337164ce3268d87317dcd5b618025a33388f432",
    "byte-freeze-fresh-checkouts.v7.autocrlf-true.json": "35750b37b1a14f9abc10ea445b576ce4583d46c4dcde2c114a7751a8cd9ad2e9",
    "verify_checkout_byte_freeze_v9.py": "0ef86e6fbd54d297d23ea1d4a0cf2ff7794ab2da15501f9ef2e2e77e6473aa2c",
    "byte_freeze_tiny_git_controller_regression_v3.py": "9ed0dadfdfa30e2a7146723b19ad33946c73784c6cbf9d4380ba235e2085a5fc",
}
with m.Held(ROOT) as held:
    documents, descriptors = {}, []
    for name, expected in pins.items():
        descriptor = held.pin(DIRECTORY + name)
        m.require(descriptor["sha256"] == expected, "closed source/proof drift")
        descriptors.append(descriptor)
        if name.endswith(".json"):
            documents[name] = m.sealed_document(held.raw(DIRECTORY + name))
    originals = {}
    groups = set()
    for document in documents.values():
        original = document["controller"]
        originals[(original["pid"], original["start_ticks"], original["boot_id"])] = original
        groups.add(original["pgid"])
        for command in document.get("commands", ()):
            child = command.get("child", {})
            if "start_ticks" in child:
                originals[(child["pid"], child["start_ticks"], child["boot_id"])] = child
            if "exclusive_original_process_group" in command:
                groups.add(command["exclusive_original_process_group"])
    original_observations = []
    for (pid, start, boot), expected in sorted(originals.items()):
        current = m.process_observation(pid)
        present = current.get("start_ticks") == start and current.get("boot_id") == boot
        m.require(not present, "original closed controller/child still present")
        original_observations.append({"original": expected, "current": current, "original_identity_absent": True})
    members = []
    for entry in Path("/proc").iterdir():
        if entry.name.isdigit():
            current = m.process_observation(int(entry.name))
            if current.get("pgid") in groups:
                members.append(current)
    m.require(not any(row.get("state") != "Z" for row in members), "owned clone/fixture group still has live work")
    master = documents["byte-freeze-fresh-checkouts.v7.json"]
    roots = []
    for row in master["checkouts"]:
        root = Path(row["checkout_root"])
        current = m.epoch(root.lstat())
        m.require(root.resolve(strict=True) == root and current[:3] == row["before_first_checkout_epoch"][:3],
            "original new checkout root replaced")
        roots.append({"path": str(root), "current_epoch": current, "original_dev_ino_mode_unchanged": True})
    captures = []
    for stem in ("controller-lf-attributes-preparation.v1",
        "byte-freeze-tiny-git-controller-regression.v3", "byte-freeze-fresh-checkouts.v7"):
        for channel in ("stdout", "stderr"):
            captures.append(held.pin(DIRECTORY + stem + "." + channel + ".log"))
    for name in ("byte-freeze-fresh-checkouts.v7.reservation.json",
        "byte-freeze-fresh-checkouts.v7.source.reservation.json",
        "byte-freeze-fresh-checkouts.v7.autocrlf-false.reservation.json",
        "byte-freeze-fresh-checkouts.v7.autocrlf-true.reservation.json",
        "apply_controller_lf_attributes_v1.py"):
        descriptors.append(held.pin(DIRECTORY + name))
    held.pin(Path(__file__).resolve().relative_to(ROOT).as_posix())
    result = {"schema_version": 1, "artifact_kind": "vast_corrected_checkout_closed_execution_v1",
        "controller": m.process_observation(os.getpid()), "source_commit": master["source_commit"],
        "reviewed_planning_commit": master["reviewed_planning_commit"], "review_reference": master["review_reference"],
        "closed_proof_and_controller_descriptors": descriptors, "raw_original_captures": captures,
        "actual_tool_terminal_observations": [
            {"task": "attributes_preparation", "session_id": 88782, "exit_code": 0},
            {"task": "tiny_fixture3", "original_tool_chunk": "dcbcba", "exit_code": 0},
            {"task": "actual_corrected_checkouts", "session_id": 1814, "exit_code": 0}],
        "tool_observation_origin": "actual completed functions exec_command/write_stdin results",
        "post_terminal_original_process_observations": original_observations,
        "original_group_ids": sorted(groups), "current_original_group_members": members,
        "no_owned_clone_pack_fixture_descendants_live": True, "retained_original_new_roots": roots,
        "verifier_and_fixture_bytes_before_after_equal": True, "held_closed_inputs": held.witnesses(),
        "source_index_config_docs_tasks_or_old_namespace_mutated": False,
        "images_models_or_containers_observed_or_launched": False,
        "accepted": False, "publication_ready": False, "launch_or_publication_grant": False,
        "scope": "closed_actual165_plus10_checkout_custody_and_original_process_quiescence_not_benchmark_acceptance"}
    held.verify()
    descriptor = m.write_new(ROOT / DIRECTORY / "byte-freeze-corrected-closed-execution.v1.json", result)
    held.verify()
print(json.dumps(descriptor))
