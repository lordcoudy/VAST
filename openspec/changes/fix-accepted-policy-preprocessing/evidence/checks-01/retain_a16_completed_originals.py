#!/usr/bin/env python3
"""Finite byte-exact retention of closed A16 originals; no check re-execution."""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess


COMMIT = "a16f243e7e80f093342ccdddf717d59d6d46f0a8"
HERE = Path("/mnt/c/Users/s-a-balashov/.codex/worktrees/fix-accepted-policy-preprocessing/VAST/openspec/changes/fix-accepted-policy-preprocessing/evidence/checks-01")
ROOT = Path("/home/s-a-balashov/work/vast-accepted-policy-repair-20261011a-source-a16f243e7e80f093342ccdddf717d59d6d46f0a8")
BASE = ROOT / "artifacts/accepted_policy_repair_20261011a/checks-01"
PREPARE = Path("/var/tmp/vast-repair-precheck-inputs-a16f243e-01")
RECONSTRUCTION = Path("/var/tmp/vast-repair-reconstruction-a16f243e-01")
EXISTING_INTEGRATION = HERE / "integration-a16-original-control-01"
OUTPUT = HERE / "a16-completed-originals"
CATALOGUE = HERE / "a16-completed-originals.v1.json"
FILE_LIMIT = 16 * 1024 * 1024
TOTAL_LIMIT = 32 * 1024 * 1024
INTEGRATION_IDS = (
    "test_checkpoint_deepstream_runtime_image_evidence_v1.DeepStreamRuntimeImageEvidenceV1Tests.test_exact_materialized_image_evidence_and_qualification_fragment",
    "test_checkpoint_gstreamer_custom_qualification_fragment_v3.GstreamerCustomQualificationFragmentV3Tests.test_exact_accepted_parity_preprocessing_and_runtime_images_are_bound",
    "test_checkpoint_gstreamer_custom_qualification_fragment_v3.GstreamerCustomQualificationFragmentV3Tests.test_phase_one_materializes_exact_physical_binding_fragment",
    "test_checkpoint_openvino_gva_publication_runtime_v3.OpenVINOGVAPublicationRuntimeV3Tests.test_live_daemon_reads_private_held_fd_copy",
    "test_kpp_frozen_reconstruction_v1_dataset_integration.KppFrozenReconstructionV1DatasetIntegrationTests.test_full_on_disk_corpus_and_receipt_graph_validate",
    "test_kpp_iss_publication_v3_dataset_integration.KppIssPublicationV3DatasetIntegrationTests.test_require_files_rehashes_the_complete_exact_corpus",
    "test_publication_runtime_frozen_identity_constants_v1.PublicationRuntimeFrozenIdentityConstantsV1Tests.test_current_qualification_fragments_match_physical_receipts",
    "test_publication_runtime_frozen_identity_constants_v1.PublicationRuntimeFrozenIdentityConstantsV1Tests.test_fix_benchmark_patch_matches_exact_runtime_constants",
    "test_publication_runtime_frozen_identity_constants_v1.PublicationRuntimeFrozenIdentityConstantsV1Tests.test_live_fix_benchmark_preflight_matches_runtime_materializer",
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def canonical(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("ascii")


def strict_json(payload):
    def pairs(rows):
        result = {}
        for key, value in rows:
            require(key not in result, "duplicate JSON key")
            result[key] = value
        return result

    def reject(value):
        raise ValueError("nonfinite JSON constant: " + value)

    require(len(payload) <= TOTAL_LIMIT, "JSON exceeds bound")
    return json.loads(payload.decode("ascii"), object_pairs_hook=pairs, parse_constant=reject)


def epoch(info):
    return {name: int(getattr(info, name)) for name in (
        "st_dev", "st_ino", "st_mode", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns",
    )}


def snapshot(path):
    require(path.is_absolute() and path.resolve(strict=True) == path, "aliased result path")
    current = path
    while current != Path("/"):
        require(not stat.S_ISLNK(current.lstat().st_mode), "linked result ancestor")
        current = current.parent
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_size <= FILE_LIMIT, "nonplain or oversized result")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        require(epoch(os.fstat(stream.fileno())) == epoch(info), "result changed before read")
        payload = stream.read(FILE_LIMIT + 1)
        require(epoch(os.fstat(stream.fileno())) == epoch(info), "result changed during read")
    require(path.resolve(strict=True) == path and len(payload) == info.st_size and epoch(path.lstat()) == epoch(info),
            "result changed after read")
    return payload, epoch(info)


def document(path):
    return strict_json(snapshot(path)[0])


def git(*args):
    # Prevent optional index refresh writes while another actor owns source custody.
    return subprocess.run(["git", "--no-optional-locks", "-C", str(ROOT), *args],
                          check=True, capture_output=True).stdout


def assert_source():
    require(Path(__file__).resolve().parent == HERE and HERE.resolve(strict=True) == HERE, "helper is outside exact managed directory")
    require(ROOT.resolve(strict=True) == ROOT, "noncanonical source root")
    require(git("rev-parse", "HEAD").decode("ascii").strip() == COMMIT, "source commit differs")
    require(git("status", "--porcelain=v1", "--untracked-files=no") == b"", "tracked source differs")


def literal_groups():
    return {
        "prepare-original-controls": (PREPARE, (
            "command.v1.json", "original.stdout.raw", "original.stderr.raw", "original.result.v1.json",
            "independent.stdout.raw", "independent.stderr.raw", "independent.result.v1.json",
            "independent-02.stdout.raw", "independent-02.stderr.raw", "independent-02.result.v1.json",
            "independent-02.input-hashes.v1.json", "reconstruction-plan.original.stdout.json",
            "reconstruction-plan.original.stderr.raw", "reconstruction-plan.original.result.v1.json",
        )),
        "source-input-copy-" + COMMIT: (BASE / ("source-input-copy-" + COMMIT), (
            "regression-copy.report.json", "regression-copy.stdout.log", "regression-copy.stderr.log",
            "asset-copy.report.json", "asset-copy.stdout.log", "asset-copy.stderr.log",
            "fresh-copy.report.json", "fresh-copy.stdout.log", "fresh-copy.stderr.log",
        )),
        "focused-" + COMMIT + "-01": (BASE / ("focused-" + COMMIT + "-01"), (
            "commit.txt", "started.txt", "finished.txt", "original.rc.txt", "original.stdout.log",
            "original.stderr.log", "test-modules.txt",
        )),
        "final-source-inputs-" + COMMIT: (BASE / ("final-source-inputs-" + COMMIT), (
            "source-commit.txt", "started.txt", "finished.txt", "original.rc.txt", "original.stdout.log",
            "original.stderr.log", "external-helpers.sha256.txt", "fresh-packaged-closure.inventory.v1.json",
            "native-worker.plan.json", "source-comparison.v1.json", "execution-code-closure.v1.json",
            "code-closure-materialize.stdout.json", "code-closure-cold.stdout.json",
        )),
        "reconstruction-original-controls": (RECONSTRUCTION, (
            "command.v1.json", "original.stdout.raw", "original.stderr.raw", "original.result.v1.json",
            "independent.stdout.raw", "independent.stderr.raw", "independent.result.v1.json",
            "independent-02/command.v1.json", "independent-02/original.stdout.raw",
            "independent-02/original.stderr.raw", "independent-02/original.result.v1.json",
            "independent-03/command.v1.json", "independent-03/original.stdout.raw",
            "independent-03/original.stderr.raw", "independent-03/original.result.v1.json",
        )),
        "reconstruction-inputs-copy-v2-" + COMMIT: (BASE / ("reconstruction-inputs-copy-v2-" + COMMIT), (
            "source-commit.txt", "started.txt", "finished.txt", "original.rc.txt", "original.stdout.json",
            "original.stderr.log", "external-helper-plan-wrapper.sha256",
        )),
        "integration-" + COMMIT + "-01": (BASE / ("integration-" + COMMIT + "-01"), (
            "commit.txt", "started.txt", "finished.txt", "integration-test-ids.txt", "results.txt",
            "containers.before.txt", "containers.after.txt", "gpu-compute.before.txt", "gpu-compute.after.txt",
            "docker-engine-id.txt", "disk.before.txt",
            *(item + suffix for item in INTEGRATION_IDS for suffix in (".outcome.json", ".stdout.log", ".stderr.log")),
        )),
    }


def original_capture(path, expected_rc, expected_stream_names=None):
    result = document(path)
    require(result["original_exit_code"] == expected_rc, "original capture return code differs")
    commit_present = "source_commit" in result
    if commit_present:
        require(result["source_commit"] == COMMIT, "original capture commit differs")
    else:
        require(path == RECONSTRUCTION / "independent.result.v1.json" and expected_rc == 1,
                "unexpected absent original source-commit metadata")
    start = datetime.fromisoformat(result["started_utc"].replace("Z", "+00:00"))
    finish = datetime.fromisoformat(result["finished_utc"].replace("Z", "+00:00"))
    require(start <= finish, "original UTC order differs")
    streams = result["streams"]
    require(len(streams) == 2, "original capture stream count differs")
    if expected_stream_names is not None:
        require(set(streams) == set(expected_stream_names), "original special stream keyset differs")
    for name, facts in streams.items():
        require(PurePosixPath(name).name == name and (name.endswith((".stdout.raw", ".stderr.raw"))
                or expected_stream_names is not None), "unexpected original stream name")
        payload = snapshot(path.parent / name)[0]
        require(len(payload) == facts["bytes"] and hashlib.sha256(payload).hexdigest() == facts["sha256"], "original raw capture differs")
    return {"result_source": str(path), "original_exit_code": expected_rc,
            "original_source_commit_metadata_present": commit_present,
            "source_binding_boundary": "Actual metadata field" if commit_present else
                "Literal A16 control-directory context only; absent original metadata field is not invented.",
            "started_utc": result["started_utc"], "finished_utc": result["finished_utc"]}


def recipe_result(directory, commit_file):
    require(snapshot(directory / commit_file)[0].decode("ascii").strip() == COMMIT, "recipe commit differs")
    require(snapshot(directory / "original.rc.txt")[0].decode("ascii").strip() == "0", "recipe original RC differs")
    start = snapshot(directory / "started.txt")[0].decode("ascii").strip()
    finish = snapshot(directory / "finished.txt")[0].decode("ascii").strip()
    require(datetime.fromisoformat(start.replace("Z", "+00:00")) <= datetime.fromisoformat(finish.replace("Z", "+00:00")), "recipe UTC order differs")
    return {"directory": str(directory), "original_recipe_rc_file": 0, "started_utc": start, "finished_utc": finish}


def completed_states():
    captures = {
        "preparation": original_capture(PREPARE / "original.result.v1.json", 0),
        "preparation-independent-01": original_capture(PREPARE / "independent.result.v1.json", 1),
        "preparation-independent-02": original_capture(PREPARE / "independent-02.result.v1.json", 0),
        "reconstruction-plan": original_capture(PREPARE / "reconstruction-plan.original.result.v1.json", 0,
            ("reconstruction-plan.original.stdout.json", "reconstruction-plan.original.stderr.raw")),
        "reconstruction-copy": original_capture(RECONSTRUCTION / "original.result.v1.json", 0),
        "reconstruction-independent-01": original_capture(RECONSTRUCTION / "independent.result.v1.json", 1),
        "reconstruction-independent-02": original_capture(RECONSTRUCTION / "independent-02/original.result.v1.json", 1),
        "reconstruction-independent-03": original_capture(RECONSTRUCTION / "independent-03/original.result.v1.json", 0),
    }
    captures["preparation-independent-01"]["preserved_failure"] = "Transferred shell variables vanished before the independent source gate."
    captures["reconstruction-independent-01"]["preserved_failure"] = "Transferred nested Python quoting failed at parsing, before independent predicates."
    captures["reconstruction-independent-02"]["preserved_failure"] = "Verifier refused legitimate unittest docstring-split OK formatting; original suite was not rerun."
    source_copy = BASE / ("source-input-copy-" + COMMIT)
    for name, count in (("regression-copy.report.json", 31), ("asset-copy.report.json", 34), ("fresh-copy.report.json", 2473)):
        result = document(source_copy / name)
        require(result["commit"] == COMMIT and result["target_root"] == str(ROOT) and len(result["copied_files"]) == count,
                "preparation original report scope differs")
    require(len(document(source_copy / "fresh-copy.report.json")["fixture_observation_files"]) == 2, "fresh map count differs")
    focused = BASE / ("focused-" + COMMIT + "-01")
    focused_state = recipe_result(focused, "commit.txt")
    lines = snapshot(focused / "original.stderr.log")[0].decode("utf-8").splitlines()
    require(lines[-3:] == ["Ran 212 tests in 131.755s", "", "OK (skipped=1)"], "actual focused terminal result differs")
    focused_state.update({"original_tests_run": 212, "original_skip_count": 1,
                          "retained_outer_result_file": False,
                          "record_boundary": "Finished recipe RC/UTC controls and original unittest streams; no separate captured outer result file is inventoried."})
    comparison = BASE / ("final-source-inputs-" + COMMIT)
    comparison_state = recipe_result(comparison, "source-commit.txt")
    report = document(comparison / "source-comparison.v1.json")
    require(report["source_commit"] == COMMIT and report["passed"] is True, "comparison original report differs")
    comparison_state.update({"outer_tool_exit_emission_available": False,
                             "missing_outer_record": "Recipe RC/UTC/reports exist; outer completed tool result was not emitted after an orchestration store error."})
    reconstruction_state = recipe_result(BASE / ("reconstruction-inputs-copy-v2-" + COMMIT), "source-commit.txt")
    copied = document(BASE / ("reconstruction-inputs-copy-v2-" + COMMIT) / "original.stdout.json")
    require(copied["passed"] is True and copied["source_commit"] == COMMIT and copied["file_count"] == 12,
            "copy original result differs")
    integration = BASE / ("integration-" + COMMIT + "-01")
    require(snapshot(integration / "commit.txt")[0].decode("ascii").strip() == COMMIT, "integration original commit differs")
    ids_path = ROOT / "openspec/changes/fix-accepted-policy-preprocessing/evidence/checks-01/integration-test-ids.txt"
    ids_raw = snapshot(ids_path)[0]
    require(ids_raw == git("show", COMMIT + ":" + ids_path.relative_to(ROOT).as_posix()), "frozen integration ID source differs")
    require(tuple(ids_raw.decode("ascii").splitlines()) == INTEGRATION_IDS
            and snapshot(integration / "integration-test-ids.txt")[0] == ids_raw, "executed exact9 manifest differs")
    require(snapshot(integration / "results.txt")[0].decode("ascii").splitlines() == ["0 " + item for item in INTEGRATION_IDS], "nine original RC rows differ")
    for item in INTEGRATION_IDS:
        result = document(integration / (item + ".outcome.json"))
        require(result["test_id"] == item and result["tests_run"] == 1 and result["successful"] is True
                and result["successful_test_ids"] == [item] and result["skips"] == [] and result["failures"] == []
                and result["errors"] == [] and result["new_repair_runtime_authority"] is False, "actual integration outcome differs")
    for name in ("containers.before.txt", "containers.after.txt", "gpu-compute.before.txt", "gpu-compute.after.txt"):
        require(snapshot(integration / name)[0] == b"", "original idle observation differs")
    integration_state = original_capture(EXISTING_INTEGRATION / "original.result.v1.json", 0)
    integration_state.update({"existing_managed_outer_controls_not_copied": True, "original_cases": 9, "original_skips": 0})
    return {"captures": captures, "focused": focused_state, "source_comparison": comparison_state,
            "reconstruction": reconstruction_state, "integration": integration_state}


def file_row(source, retained=None):
    payload, physical_epoch = snapshot(source)
    result = {"source": str(source), "size_bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest(),
              "physical_epoch": physical_epoch}
    if retained is not None:
        relative = PurePosixPath(retained)
        require(not relative.is_absolute() and all(part not in ("", ".", "..") for part in relative.parts), "unsafe retention target")
        target = OUTPUT.joinpath(*relative.parts)
        require(target.is_relative_to(OUTPUT), "target escapes finite output")
        result.update({"retained": relative.as_posix(), "target": str(target)})
    return result


def plan():
    assert_source()
    require(not os.path.lexists(OUTPUT) and not os.path.lexists(CATALOGUE), "retention destination already exists")
    states = completed_states()
    rows = [file_row(source / name, (PurePosixPath(group) / name).as_posix())
            for group, (source, names) in sorted(literal_groups().items()) for name in sorted(names)]
    references = [file_row(EXISTING_INTEGRATION / name) for name in (
        "command.v1.json", "original.result.v1.json", "original.stdout.raw", "original.stderr.raw")]
    require(len(rows) == 103 and len({row["source"] for row in rows}) == len(rows)
            and len({row["target"] for row in rows}) == len(rows), "finite103 inventory differs")
    require(sum(row["size_bytes"] for row in rows) <= TOTAL_LIMIT, "retention total exceeds bound")
    assert_source()
    return {"artifact_kind": "vast_a16_completed_original_retention_plan_v1", "schema_version": 1,
            "source_commit": COMMIT, "retention_output": str(OUTPUT), "catalogue": str(CATALOGUE),
            "helper_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), "completed_states": states,
            "file_count": len(rows), "total_bytes": sum(row["size_bytes"] for row in rows), "files": rows,
            "existing_managed_outer_controls_untouched": references, "source_read_only": True, "campaign_authority": False,
            "exclusions": ["All current/later full-suite and consumer outputs", "Native/model/corpus/tensor/fixture input trees",
                           "Existing managed integration outer controls (referenced, not recopied)", "Absent outer source-comparison tool emission"],
            "limits": ["Failed originals stay failed; each passing original is retained separately.",
                       "No missing command, UTC, raw stream or return-code record is reconstructed or invented.",
                       "Retention is mechanical provenance, not consumer acceptance, full-suite completion, archive or Q1."]}


def apply(plan_path, reviewed_sha):
    require(len(reviewed_sha) == 64 and all(char in "0123456789abcdef" for char in reviewed_sha), "invalid reviewed plan SHA")
    payload = snapshot(plan_path)[0]
    require(hashlib.sha256(payload).hexdigest() == reviewed_sha, "reviewed plan bytes differ")
    reviewed = strict_json(payload)
    require(plan() == reviewed, "finite plan, original bytes, epochs or helper changed")
    OUTPUT.mkdir(mode=0o700)
    report = []
    for row in reviewed["files"]:
        old = Path(row["source"])
        data, old_epoch = snapshot(old)
        require(old_epoch == row["physical_epoch"] and hashlib.sha256(data).hexdigest() == row["sha256"], "original changed before retention")
        new = Path(row["target"])
        require(new.is_relative_to(OUTPUT) and not os.path.lexists(new), "destination is not fresh/bounded")
        new.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        require(new.parent.resolve(strict=True) == new.parent, "retention parent is aliased")
        with new.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        require(snapshot(old) == (data, old_epoch) and snapshot(new)[0] == data, "original or retained bytes changed")
        report.append({**row, "retained": new.relative_to(HERE).as_posix()})
    for row in [*reviewed["files"], *reviewed["existing_managed_outer_controls_untouched"]]:
        data, physical_epoch = snapshot(Path(row["source"]))
        require(physical_epoch == row["physical_epoch"] and hashlib.sha256(data).hexdigest() == row["sha256"], "original/reference changed during retention")
    assert_source()
    catalogue = {**reviewed, "artifact_kind": "vast_a16_completed_original_retention_v1", "status": "retained_exactly",
                 "reviewed_plan_sha256": reviewed_sha, "files": report}
    with CATALOGUE.open("xb") as stream:
        stream.write(canonical(catalogue))
        stream.flush()
        os.fsync(stream.fileno())
    return {"status": "retained_exactly", "file_count": len(report), "total_bytes": reviewed["total_bytes"],
            "reviewed_plan_sha256": reviewed_sha, "catalogue_sha256": hashlib.sha256(CATALOGUE.read_bytes()).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("plan", "apply"))
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--reviewed-plan-sha256")
    args = parser.parse_args()
    require(args.mode == "plan" or (args.plan and args.reviewed_plan_sha256), "apply requires reviewed plan and SHA")
    result = plan() if args.mode == "plan" else apply(args.plan, args.reviewed_plan_sha256)
    print(canonical(result).decode("ascii"), end="")


if __name__ == "__main__":
    main()
