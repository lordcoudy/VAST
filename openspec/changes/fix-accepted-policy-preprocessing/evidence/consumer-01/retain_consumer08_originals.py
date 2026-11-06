#!/usr/bin/env python3
"""Retain only closed A16 consumer08 originals after exact finite-plan review."""
import argparse
import hashlib
import importlib.util
import os
from pathlib import Path, PurePosixPath


HERE = Path(__file__).resolve().parent
COMMON_PATH = HERE.parent / "checks-01/retain_a16_completed_originals.py"
COMMON_SHA = "65fb7ef980246e1fd5b8054a4eaad6c04e6015928523532420c9f5e37bc68941"
if hashlib.sha256(COMMON_PATH.read_bytes()).hexdigest() != COMMON_SHA:
    raise ValueError("reviewed A16 retention primitives changed")
_spec = importlib.util.spec_from_file_location("a16_retention_primitives", COMMON_PATH)
common = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(common)
require = common.require
COMMIT = common.COMMIT
ROOT = common.ROOT
BASE = ROOT / "artifacts/accepted_policy_repair_20261011a"
CONTROLS = BASE / "consumer-complete-08-controls"
RUN_NAME = "consumer-fixture-08-minimum30"
RUN = CONTROLS / RUN_NAME
FAILURE = BASE / RUN_NAME / "producer-failure.v2.json"
POSTMORTEM = HERE / "probe-boundary-diagnosis-01"
OUTPUT = HERE / "consumer08-originals"
CATALOGUE = HERE / "consumer08-originals.v1.json"
FILE_LIMIT = 2 * 1024 * 1024
TOTAL_LIMIT = 4 * 1024 * 1024
STATE_FILES = ("source-head.before.txt", "source-head.after.txt",
               "source-tracked-status.before.txt", "source-tracked-status.after.txt")
RAW_SOURCE_FILES = tuple("raw-source-" + phase + suffix for phase in ("before", "after")
                         for suffix in (".stdout.raw", ".stderr.raw", ".result.v1.json"))
CONTROL_FILES = STATE_FILES + RAW_SOURCE_FILES + ("run-plan.v3.json", "run-result.v3.json")
RUN_FILES = STATE_FILES + RAW_SOURCE_FILES + (
    "stdout.raw", "stderr.raw", "original-exit-code.txt", "started.v3.json", "finished.v3.json")
POSTMORTEM_FILES = ("diagnostic-result.v1.json", *(phase + suffix
    for phase in ("openvino_gva", "gstreamer_custom", "raw-source-before", "raw-source-after")
    for suffix in (".started.v1.json", ".finished.v1.json", ".stdout.raw", ".stderr.raw")))


def snapshot(path):
    require(path.lstat().st_size <= FILE_LIMIT, "consumer original exceeds 2 MiB")
    return common.snapshot(path)


def document(path):
    return common.strict_json(snapshot(path)[0])


def assert_states(directory):
    for name in STATE_FILES:
        expected = (COMMIT + "\n").encode("ascii") if "source-head." in name else b""
        require(snapshot(directory / name)[0] == expected, "original HEAD/status control differs")
    proofs = {}
    for phase in ("before", "after"):
        result = document(directory / ("raw-source-" + phase + ".result.v1.json"))
        require(result["original_exit_code"] == 0 and result["proof_validated"] is True
                and result["cwd"] == str(ROOT), "original raw-source invocation differs")
        for stream in ("stdout", "stderr"):
            payload = snapshot(directory / ("raw-source-" + phase + "." + stream + ".raw"))[0]
            require(len(payload) == result[stream + "_bytes"]
                    and hashlib.sha256(payload).hexdigest() == result[stream + "_sha256"], "original raw-source stream differs")
        proof = document(directory / ("raw-source-" + phase + ".stdout.raw"))
        require(proof == result["proof"] and proof["raw_committed_bytes_verified"] is True
                and proof["tracked_path_count"] == 12115
                and proof["verifier_path"] == str(ROOT / "scripts/run_ci_checks.py"), "original stock raw12115 proof differs")
        proofs[phase] = {"original_exit_code": 0, "tracked_path_count": 12115, "raw_committed_bytes_verified": True,
                         "started_utc": result["started_utc"], "finished_utc": result["finished_utc"]}
    return proofs


def completed_state():
    outer_proofs = assert_states(CONTROLS)
    child_proofs = assert_states(RUN)
    result = document(CONTROLS / "run-result.v3.json")
    require(result["source_commit"] == COMMIT and result["exit_code"] == 1
            and result["source_state_unchanged"] is True and result["both_complete_consumers_passed"] is False
            and result["campaign_authority"] is False and result["finished_utc"] and len(result["runs"]) == 1,
            "original08 is not the closed failed run")
    finished = document(RUN / "finished.v3.json")
    require(result["runs"][0] == finished and finished["name"] == RUN_NAME
            and finished["original_exit_code"] == 1 and finished["samples_per_branch"] == 30
            and finished["expected_measured_sample_count"] == 3840
            and finished["complete_consumer_positive_asserted"] is False
            and finished["source_state_unchanged"] is True and finished["finished_utc"], "original child08 terminal state differs")
    require(snapshot(RUN / "original-exit-code.txt")[0].decode("ascii").strip() == "1", "original child RC differs")
    for name in ("stdout.raw", "stderr.raw"):
        payload = snapshot(RUN / name)[0]
        require(finished[name] == {"size_bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()},
                "original child raw stream differs")
    failure = document(FAILURE)
    require(failure["source_commit"] == COMMIT and failure["complete_consumer_positive_asserted"] is False
            and failure["campaign_authority"] is False and failure["physical_inference_observed"] is False
            and failure["samples_per_branch"] == 30 and failure["expected_measured_sample_count"] == 3840
            and failure["error"] == "openvino_gva OpenVINO device probe failed closed" and failure["traceback"],
            "original producer failure boundary differs")
    postmortem = document(POSTMORTEM / "diagnostic-result.v1.json")
    require(postmortem["source_commit"] == COMMIT and postmortem["source_root"] == str(ROOT)
            and postmortem["diagnostic_exit_code"] == 0 and postmortem["diagnostic_not_original_invocation"] is True
            and postmortem["campaign_authority"] is False and postmortem["qualification_executed"] is False
            and postmortem["finished_utc"] and len(postmortem["probes"]) == 2, "separate managed postmortem scope differs")
    return {"source_commit": COMMIT, "original_exit_code": 1, "original_error": failure["error"],
            "started_utc": finished["started_utc"], "finished_utc": finished["finished_utc"],
            "source_state_unchanged": True, "original_outer_raw_source_proofs": outer_proofs,
            "original_child_raw_source_proofs": child_proofs, "consumer09_unstarted": True,
            "complete_consumer_positive_asserted": False,
            "postmortem_boundary": "Existing separately captured retained-ELF diagnostic is referenced, not the original invocation or consumer success."}


def literal_paths():
    return [*((CONTROLS / name, PurePosixPath(CONTROLS.name) / name) for name in CONTROL_FILES),
            *((RUN / name, PurePosixPath(CONTROLS.name) / RUN_NAME / name) for name in RUN_FILES),
            (FAILURE, PurePosixPath(RUN_NAME) / "producer-failure.v2.json")]


def row(path, retained=None):
    payload, physical_epoch = snapshot(path)
    result = {"source": str(path), "size_bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest(),
              "physical_epoch": physical_epoch}
    if retained is not None:
        require(not retained.is_absolute() and all(part not in ("", ".", "..") for part in retained.parts), "unsafe finite target")
        target = OUTPUT.joinpath(*retained.parts)
        require(target.is_relative_to(OUTPUT), "target escapes fresh retention root")
        result.update({"retained": retained.as_posix(), "target": str(target)})
    return result


def plan():
    common.assert_source()
    require(HERE.resolve(strict=True) == HERE and HERE == COMMON_PATH.parent.parent / "consumer-01", "managed origin differs")
    require(not os.path.lexists(OUTPUT) and not os.path.lexists(CATALOGUE), "consumer08 retention destination already exists")
    require(not os.path.lexists(BASE / "consumer-fixture-09-larger31")
            and not os.path.lexists(CONTROLS / "consumer-fixture-09-larger31"), "unstarted09 unexpectedly exists")
    state = completed_state()
    files = [row(path, retained) for path, retained in sorted(literal_paths(), key=lambda item: item[1].as_posix())]
    references = [row(POSTMORTEM / name) for name in POSTMORTEM_FILES]
    total = sum(item["size_bytes"] for item in files)
    require(len(files) == len({item["target"] for item in files}) == 28 and len(references) == 17 and total <= TOTAL_LIMIT,
            "retention is not the finite28 plus17 references within4MiB")
    common.assert_source()
    return {"artifact_kind": "vast_consumer08_original_retention_plan_v1", "schema_version": 1,
            "source_commit": COMMIT, "source_base": str(BASE), "retention_output": str(OUTPUT), "catalogue": str(CATALOGUE),
            "helper_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), "snapshot_helper_sha256": COMMON_SHA,
            "completed_state": state, "files": files, "file_count": 28, "total_bytes": total,
            "existing_managed_postmortem_references_untouched": references, "source_read_only": True,
            "consumer_positive_asserted": False, "campaign_authority": False,
            "exclusions": ["Unstarted larger09", "All native/runtime/operational37/corpus/model/tensor/fixture input trees",
                           "Live full-suite outputs", "Existing managed postmortem records (referenced only)", "Any new consumer run"],
            "limits": ["Original08 remains failed before native observations or complete consumers.",
                       "Separate postmortem diagnostics do not replace the original exit or prove acceptance.",
                       "No original record is rewritten, normalized or invented; retention is not qualification or Q1."]}


def apply(plan_path, reviewed_sha):
    require(len(reviewed_sha) == 64 and all(char in "0123456789abcdef" for char in reviewed_sha), "invalid reviewed plan SHA")
    payload = snapshot(plan_path)[0]
    require(hashlib.sha256(payload).hexdigest() == reviewed_sha, "reviewed consumer08 plan bytes differ")
    reviewed = common.strict_json(payload)
    require(plan() == reviewed, "closed original/reference bytes, epochs or reviewed plan changed")
    OUTPUT.mkdir(mode=0o700)
    for item in reviewed["files"]:
        source, target = Path(item["source"]), Path(item["target"])
        data, physical_epoch = snapshot(source)
        require(physical_epoch == item["physical_epoch"] and hashlib.sha256(data).hexdigest() == item["sha256"], "original changed before copy")
        require(target.is_relative_to(OUTPUT) and not os.path.lexists(target), "retention target is not fresh/bounded")
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        require(target.parent.resolve(strict=True) == target.parent, "retention parent is aliased")
        with target.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        require(snapshot(source) == (data, physical_epoch) and snapshot(target)[0] == data, "source/retained bytes drifted")
    for item in [*reviewed["files"], *reviewed["existing_managed_postmortem_references_untouched"]]:
        data, physical_epoch = snapshot(Path(item["source"]))
        require(physical_epoch == item["physical_epoch"] and hashlib.sha256(data).hexdigest() == item["sha256"], "original/reference drifted during retention")
    common.assert_source()
    catalogue = {**reviewed, "artifact_kind": "vast_consumer08_original_retention_v1", "status": "retained_exactly",
                 "reviewed_plan_sha256": reviewed_sha}
    with CATALOGUE.open("xb") as stream:
        stream.write(common.canonical(catalogue))
        stream.flush()
        os.fsync(stream.fileno())
    return {"status": "retained_exactly", "file_count": 28, "total_bytes": reviewed["total_bytes"],
            "reviewed_plan_sha256": reviewed_sha, "catalogue_sha256": hashlib.sha256(CATALOGUE.read_bytes()).hexdigest(),
            "consumer_positive_asserted": False, "campaign_authority": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("plan", "apply"))
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--reviewed-plan-sha256")
    args = parser.parse_args()
    require(args.mode == "plan" or (args.plan and args.reviewed_plan_sha256), "apply requires reviewed plan and SHA")
    result = plan() if args.mode == "plan" else apply(args.plan, args.reviewed_plan_sha256)
    print(common.canonical(result).decode("ascii"), end="")


if __name__ == "__main__":
    main()
