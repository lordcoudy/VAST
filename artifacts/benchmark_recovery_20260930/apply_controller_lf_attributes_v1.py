"""Apply only the reviewed ten LF rules, without source/index/config writes."""
import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
sys.dont_write_bytecode = True

ROOT = Path("/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec")
ARTIFACTS = ROOT / "artifacts/benchmark_recovery_20260930"
SCRIPT = ARTIFACTS / "verify_checkout_byte_freeze_v9.py"
OUTPUT = ARTIFACTS / "controller-lf-attributes-preparation.v1.json"
PLANNING = "47e432f2b5c09f750a55f7eb0164d84cc4d7e658"
ORIGINAL_ATTRIBUTES_SHA = "35b4d078b9f589f36cad52844fabb7e709829f5e18be377237b199b2bcf08adb"
VERIFIER_SHA = "0ef86e6fbd54d297d23ea1d4a0cf2ff7794ab2da15501f9ef2e2e77e6473aa2c"

raw = SCRIPT.read_bytes()
assert hashlib.sha256(raw).hexdigest() == VERIFIER_SHA
ast.parse(raw, filename=str(SCRIPT))
spec = importlib.util.spec_from_file_location("approved_controller_lf_verifier_v9", SCRIPT)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
assert not OUTPUT.exists() and not OUTPUT.with_name(OUTPUT.stem + ".failed.json").exists()
modified = False
attribute_observations = {}
try:
    with m.Held(ROOT) as held:
        bundle = m.inputs(ROOT, held)
        source_pins, controller_pins = bundle["source_pins"], bundle["controller_pins"]
        pins = source_pins + controller_pins
        names = [row["path"] for row in pins]
        source_names = [row["path"] for row in source_pins]
        controller_names = [row["path"] for row in controller_pins]
        prefix = m.git(ROOT)
        head = m.command(prefix + ["rev-parse", "HEAD"], ROOT).decode("ascii").strip()
        m.require(head == PLANNING, "exact reviewed planning HEAD changed")
        before_effective = m.attrs(prefix, ROOT, names)
        m.require({name: before_effective[name] for name in source_names}
            == m.desired_attrs(source_names, bundle["raw_paths"]), "165 original effective attributes changed")
        m.require(all(all(value == "unspecified" for value in before_effective[name].values())
            for name in controller_names), "ten original LF manifest attributes already changed")
        index_before = m.blobs(prefix, ROOT, held, pins, "")
        commit_before = m.blobs(prefix, ROOT, held, pins, head)
        m.require(all(row["category"] == "exact" for row in index_before + commit_before),
            "175 original physical/index/commit bytes differ")
        closure_before = m.closures(ROOT, held, bundle["audit"])
        attribute_path = ROOT / ".gitattributes"
        m.require(attribute_path.resolve(strict=True) == attribute_path, "attribute alias")
        fd = os.open(attribute_path, os.O_RDWR | os.O_APPEND | os.O_NOFOLLOW)
        try:
            before_epoch = m.epoch(os.fstat(fd))
            m.require(stat.S_ISREG(before_epoch[2]) and before_epoch[3] == 1
                and before_epoch == m.epoch(attribute_path.lstat()), "original attribute leaf identity")
            os.lseek(fd, 0, os.SEEK_SET)
            before = os.read(fd, 64 * 1024 + 1)
            m.require(len(before) <= 64 * 1024 and before.endswith(b"\n")
                and hashlib.sha256(before).hexdigest() == ORIGINAL_ATTRIBUTES_SHA,
                "original attributes are not the approved exact prefix")
            attribute_blob = m.command(prefix + ["show", head + ":.gitattributes"], ROOT)
            m.require(attribute_blob == before, "original attributes index/commit prefix differs")
            addition = ("\n" + "\n".join(bundle["controller_rules"]) + "\n").encode("ascii")
            m.require(all(line not in before.decode("ascii").splitlines()
                for line in bundle["controller_rules"]), "reviewed ten rules already present")
            m.require(m.epoch(os.fstat(fd)) == before_epoch
                and m.epoch(attribute_path.lstat()) == before_epoch, "attributes changed before append")
            modified = True
            m.require(os.write(fd, addition) == len(addition), "partial original attribute append")
            os.fsync(fd)
            os.lseek(fd, 0, os.SEEK_SET)
            after = os.read(fd, 64 * 1024 + 1)
            after_epoch = m.epoch(os.fstat(fd))
            m.require(after == before + addition and after_epoch == m.epoch(attribute_path.lstat())
                and after_epoch[:4] == before_epoch[:4], "attributes append or original inode changed")
            attribute_observations = {"path": ".gitattributes",
                "before": {"size_bytes": len(before), "sha256": hashlib.sha256(before).hexdigest(), "epoch": before_epoch},
                "after": {"size_bytes": len(after), "sha256": hashlib.sha256(after).hexdigest(), "epoch": after_epoch},
                "exact_appended_rules": bundle["controller_rules"], "unchanged_original_prefix": True}
        finally:
            os.close(fd)
        after_effective = m.attrs(prefix, ROOT, names)
        m.require(after_effective == m.desired_attrs(names, bundle["raw_paths"]),
            "156 raw+nine source LF+ten controller LF effective contract")
        index_after = m.blobs(prefix, ROOT, held, pins, "")
        m.require(index_after == index_before, "source or manifest index changed")
        closure_after = m.closures(ROOT, held, bundle["audit"])
        m.require(closure_after == closure_before, "stock9/78 identities changed")
        held.verify()
        status = m.command(prefix + ["status", "--porcelain=v1", "-z", "--untracked-files=no", "--",
            ".gitattributes", *names], ROOT)
        report = {"schema_version": 1, "artifact_kind": "vast_controller_LF_attributes_preparation_v1",
            "controller": m.process_observation(os.getpid()), "project_root": str(ROOT),
            "reviewed_planning_commit": PLANNING, "recorded_PR_comment": 5903081964,
            "source_commit_pending": True, "attributes": attribute_observations,
            "frozen165_source_audit": bundle["evidence"].pin(m.AUDIT[0]),
            "ten_controller_scope_audit": bundle["evidence"].pin(m.CONTROLLER_AUDIT[0]),
            "ten_LF_proposal": bundle["evidence"].pin(m.CONTROLLER_PROPOSAL[0]),
            "verifier": bundle["evidence"].pin(SCRIPT.relative_to(ROOT).as_posix()),
            "apply_script": bundle["evidence"].pin(Path(__file__).resolve().relative_to(ROOT).as_posix()),
            "source_group": {"count": 165, "aggregate_sha256": m.aggregate(source_pins), "pins": source_pins},
            "controller_metadata_group": {"count": 10, "aggregate_sha256": m.aggregate(controller_pins), "pins": controller_pins},
            "combined175_is_not_an_executable_source_inventory": True,
            "effective_attributes_before": before_effective, "effective_attributes_after": after_effective,
            "index_before": index_before, "index_after": index_after, "source_commit_blobs": commit_before,
            "stock_contexts_before": closure_before, "stock_contexts_after": closure_after,
            "source_and_manifest_bytes_epochs_index_unchanged": True,
            "source_witnesses": held.witnesses(), "evidence_witnesses": bundle["evidence"].witnesses(),
            "commands": m.COMMANDS,
            "active_status_porcelain_hex": status.hex(),
            "only_production_mutation": ".gitattributes exact ten canonical-LF rules",
            "manifest_rewrite_stage_or_source_config_mutation": False,
            "git_stage_commit_push_or_task_edits": False,
            "fresh_checkout_fixture_image_model_container_execution": False,
            "accepted": False, "publication_ready": False, "launch_or_publication_grant": False,
            "scope": "approved_attributes_preparation_only_actual_fresh_checkouts_pending"}
        result = m.write_new(OUTPUT, report)
        held.verify()
    print(json.dumps({"proof": result, "attributes_sha256": attribute_observations["after"]["sha256"],
        "source165_aggregate": m.AGGREGATE, "ready_for_parent_attributes_only_commit": True}))
except BaseException as error:
    failed = {"schema_version": 1, "artifact_kind": "vast_controller_LF_attributes_preparation_failure_v1",
        "controller": m.process_observation(os.getpid()), "reviewed_planning_commit": PLANNING,
        "recorded_PR_comment": 5903081964, "error_type": type(error).__name__, "error": str(error),
        "attribute_append_started": modified, "attribute_observations": attribute_observations,
        "commands": m.COMMANDS, "accepted": False, "publication_ready": False, "launch_or_publication_grant": False}
    m.write_new(OUTPUT.with_name(OUTPUT.stem + ".failed.json"), failed)
    raise
