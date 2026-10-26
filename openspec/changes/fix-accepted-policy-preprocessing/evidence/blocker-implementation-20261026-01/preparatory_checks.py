"""Fixed local checks only; portable results confer no physical authority."""
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from tests.fixtures.accepted_policy_standalone_reader_fixture_v2 import (
    _bounded_json_v2, _capture_owned_reader_v2, _write_result_v2,
)

NEGATIVES = (
    "missing_system_probe", "foreign_system_probe", "nonobject_probe", "missing_captured_image",
    "captured_image_id_mismatch", "fragment_image_id_mismatch", "malformed_patch_image_id",
    "missing_patch_identity", "shared_system_image_id", "conflicting_captured_alias",
    "malformed_captured_alias", "falsey_nonlist_captured_aliases",
)
PROBES = ["tests.test_accepted_policy_fixture_probe_binding_v2.AcceptedPolicyFixtureProbeBindingV2Tests.test_" +
          name + "_is_refused_before_writes" for name in NEGATIVES]
PROBES[-1] = PROBES[-1].replace("_is_refused_", "_are_refused_")
PROBES += ["tests.test_accepted_policy_fixture_probe_binding_v2.AcceptedPolicyFixtureProbeBindingV2Tests.test_" +
           name for name in ("empty_maps_remain_explicit_transport_only_boundary", "reply_maps_require_explicit_objects")]
LEGACY = [
    "tests.test_accepted_policy_fixture_compiler_gate2_dictionary_caller_v1.D27SourceCustodyTests.test_fixed_old_three_and_four_formatter_data_pins",
    "tests.test_accepted_policy_fixture_compiler_gate2_resume_retention_v1.ResumeSourceFormsTests.test_current_git_alias_requires_size_and_sha256_as_well_as_blob_identity",
    "tests.test_accepted_policy_fixture_compiler_gate2_resume_retention_v1.ResumeSourceFormsTests.test_extra_intermediate_plan_git_is_additive_even_when_current_bytes_unchanged",
    "tests.test_accepted_policy_fixture_compiler_gate2_resume_retention_v1.ResumeSourceFormsTests.test_reviewed_12k_plan_history_remains_inside_source_budget",
    "tests.test_accepted_policy_fixture_compiler_gate2_resume_retention_v1.ResumeSourceFormsTests.test_scoped_budget_keeps_legacy_and_counts_full_current_and_superseded_forms",
    "tests.test_accepted_policy_fixture_compiler_gate2_resume_retention_v1.ResumeSourceFormsTests.test_wrong_index_source_identity_or_unchanged_alias_refuses",
    "tests.test_accepted_policy_fixture_compiler_gate2_resume_v1.D25CompleteGeometryTests.test_complete_form_bounds_preserve_hold",
    "tests.test_accepted_policy_fixture_compiler_gate2_resume_caller_v1.D26CompleteGeometryTests.test_complete_form_bounds_preserve_hold",
    "tests.test_accepted_policy_fixture_compiler_gate2_resume_v1.ResumeBoundaries.test_actual_main_verified_closure_p0_api_write_order_and_single_terminal",
]
ROSTER = {
    "red": ["tests.test_accepted_policy_fixture_authority_v1"],
    "green": ["tests.test_accepted_policy_fixture_authority_v1"],
    "owner": ["tests.test_accepted_policy_fixture_compiler_v1", "tests.test_accepted_policy_fixture_compiler_owner_v1"],
    "transport": ["tests.test_accepted_policy_fixture_transport_v2", *PROBES],
    "edges": ["tests.test_accepted_policy_fixture_preflight_v1"],
    "metadata-red": ["tests.test_accepted_policy_fixture_metadata_v1"],
    "metadata-green": ["tests.test_accepted_policy_fixture_metadata_v1"],
    "compat-current-01": ["tests.test_accepted_policy_fixture_authority_v1",
        "tests.test_accepted_policy_fixture_preflight_v1",
        "tests.test_accepted_policy_fixture_compiler_admission_v1",
        "tests.test_accepted_policy_fixture_compiler_v1",
        "tests.test_accepted_policy_fixture_compiler_owner_v1",
        "tests.test_accepted_policy_fixture_transport_v2", *PROBES],
    "compat-legacy-01": LEGACY,
}


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ROSTER:
        raise ValueError("one reviewed literal phase is required")
    phase = sys.argv[1]
    deadline = {"absolute_monotonic_ns": time.monotonic_ns() + 300_000_000_000,
                "term_grace_ns": 5_000_000_000, "kill_grace_ns": 5_000_000_000,
                "final_ns": 5_000_000_000}
    output = Path(__file__).resolve().parent / ("prep-" + phase)
    temporary = Path("/var/tmp") / ("vast-pr9-b2-prep-" + phase)
    if ROOT.resolve(strict=True) != ROOT or output.exists() or temporary.exists():
        raise ValueError("preparatory paths must be canonical and fresh; no retry")
    units, free = {}, {}
    for label, path in (("c", Path("/mnt/c")), ("temporary", temporary.parent)):
        info = os.statvfs(path)
        units[label], free[label] = info.f_frsize, info.f_bavail * info.f_frsize
    if any(not 0 < value <= 4096 for value in units.values()):
        raise ValueError("preparatory allocation-unit bound differs")
    allowance = 536870912 + (134217728 if phase == "edges" or phase.startswith("metadata-") else 0)
    if phase.startswith("metadata-"):
        allowance += 134217728
    if phase.startswith("compat-"):
        allowance = 1073741824  # prior768MiB plus the complete reviewed256MiB tranche
    if free["c"] < 42949672960 + allowance or free["temporary"] < 1073741824 + allowance:
        raise ValueError("preparatory physical floor is insufficient")
    if time.monotonic_ns() >= deadline["absolute_monotonic_ns"] - 15_000_000_000:
        raise ValueError("preparatory deadline expired before namespace allocation")
    output.mkdir(mode=0o700)
    temporary.mkdir(mode=0o700)
    os.environ["TMPDIR"] = str(temporary)
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    command = [sys.executable, "-B", "-m", "unittest", "-v", *ROSTER[phase]]
    facts, _, _ = _capture_owned_reader_v2(command=command, cwd=ROOT,
        outputs={key: output / (key + ".original") for key in ("stdout", "stderr")}, deadline=deadline)
    expected = 1 if phase in ("red", "metadata-red") else 0
    closed = (not facts["causes"] and facts["closure"]["closed"] and not facts["forced"]
              and facts["signal"] is None and facts["returncode"] == expected)
    for channel in ("stdout", "stderr"):
        row = facts[channel]
        closed = closed and row is not None and row["eof"] and not row["overflow"] and not row["remainder_unknown"]
        closed = closed and row["file"]["fsync_completed"] and row["file"]["close_completed"]
    raw = _bounded_json_v2({"phase": phase, "command": command, "fresh_free_bytes": free,
        "allocation_units": units, "expected_child_returncode": expected, "capture": facts,
        "closed_as_expected": bool(closed), "physical_acceptance": False}, 32767)
    if raw is None:
        raise ValueError("preparatory result exceeds its reviewed bound")
    path = output / "result.original.json"
    persistence = _write_result_v2(path, raw + b"\n", deadline["absolute_monotonic_ns"])
    late = time.monotonic_ns() >= deadline["absolute_monotonic_ns"]
    complete = closed and not persistence["causes"] and persistence["written_bytes"] == len(raw) + 1 and not late
    status = _bounded_json_v2({"phase": phase, "capture_closed_with_expected_child_status": bool(closed),
        "child_returncode": facts["returncode"], "result": str(path), "result_persistence": persistence,
        "deadline_exceeded": late, "red_output_review_required": phase in ("red", "metadata-red")}, 2048)
    if status is None:
        raise ValueError("fixed preparatory status exceeded its reviewed bound")
    print(status.decode("ascii"), flush=True)
    return 0 if complete else 1


if __name__ == "__main__":
    raise SystemExit(main())
