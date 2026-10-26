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
    "reports-red-01": ["tests.test_accepted_policy_fixture_report_v1"],
    "reports-green-01": ["tests.test_accepted_policy_fixture_report_v1"],
    "quantity-red-01": ["tests.test_accepted_policy_fixture_quantity_v1"],
    "quantity-green-01": ["tests.test_accepted_policy_fixture_quantity_v1",
        "tests.test_accepted_policy_fixture_sample_counts_v2.AcceptedPolicyFixtureSampleCountsV2Tests.test_mixed_counts_change_one_qualification_cell_and_leave_others_at31",
        "tests.test_accepted_policy_fixture_sample_counts_v2.AcceptedPolicyFixtureSampleCountsV2Tests.test_negative_entrypoint_compiles_and_uses_actual_call_signatures_without_changing_positive_gate",
        "tests.test_accepted_policy_fixture_sample_counts_v2.AcceptedPolicyFixtureSampleCountsV2Tests.test_invalid_global_or_mixed_counts_refuse_before_native_writes"],
    "bindings-red-01": ["tests.test_accepted_policy_fixture_binding_bounds_v1"],
    "bindings-green-01": ["tests.test_accepted_policy_fixture_binding_bounds_v1",
        "tests.test_accepted_policy_fixture_quantity_v1"],
    "sidecars-red-01": ["tests.test_accepted_policy_fixture_sidecar_bounds_v1"],
    "sidecars-edges-red-01": ["tests.test_accepted_policy_fixture_sidecar_edges_v1"],
    "sidecars-green-01": ["tests.test_accepted_policy_fixture_sidecar_bounds_v1",
        "tests.test_accepted_policy_fixture_sidecar_edges_v1",
        "tests.test_accepted_policy_fixture_binding_bounds_v1",
        "tests.test_accepted_policy_fixture_quantity_v1"],
    "readers-red-01": ["tests.test_accepted_policy_fixture_reader_bounds_v1"],
    "readers-green-01": ["tests.test_accepted_policy_fixture_reader_bounds_v1"],
    "writefacts-red-01": ["tests.test_accepted_policy_fixture_sidecar_write_facts_v1"],
    "writefacts-green-01": ["tests.test_accepted_policy_fixture_sidecar_write_facts_v1",
        "tests.test_accepted_policy_fixture_sidecar_bounds_v1",
        "tests.test_accepted_policy_fixture_sidecar_edges_v1",
        "tests.test_accepted_policy_fixture_binding_bounds_v1",
        "tests.test_accepted_policy_fixture_quantity_v1"],
    "headers-red-01": ["tests.test_accepted_policy_fixture_journal_header_v1"],
    "headers-owner-red-01": [
        "tests.test_accepted_policy_fixture_journal_header_v1.JournalHeaderBoundsTests.test_failed_buffer_construction_cannot_release_then_reclose_raw_fd",
        "tests.test_accepted_policy_fixture_journal_header_v1.JournalHeaderBoundsTests.test_successful_buffer_keeps_raw_descriptor_under_one_explicit_owner"],
    "headers-green-01": ["tests.test_accepted_policy_fixture_journal_header_v1",
        "tests.test_accepted_policy_fixture_reader_bounds_v1"],
    "artreads-red-01": ["tests.test_accepted_policy_fixture_artifact_reads_v1"],
    "artreads-green-01": ["tests.test_accepted_policy_fixture_artifact_reads_v1", *PROBES],
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
    if phase.startswith(("reports-", "quantity-", "bindings-", "sidecars-", "readers-", "writefacts-", "headers-", "artreads-")):
        # Pure report tests need no native socket or executable filesystem.
        # Their deliberately oversized RED originals stay directly on C:.
        temporary = Path(__file__).resolve().parent / ("temporary-" + phase)
    if ROOT.resolve(strict=True) != ROOT or output.exists() or temporary.exists():
        raise ValueError("preparatory paths must be canonical and fresh; no retry")
    units, free, runtime = {}, {}, None
    paths = [("c", Path("/mnt/c")), ("temporary", temporary.parent)]
    if phase.startswith(("compat-", "reports-", "quantity-", "bindings-", "sidecars-", "readers-", "writefacts-", "headers-", "artreads-")):
        paths.append(("e", Path("/mnt/e")))
    for label, path in paths:
        info = os.statvfs(path)
        units[label], free[label] = info.f_frsize, info.f_bavail * info.f_frsize
    if any(not 0 < value <= 4096 for value in units.values()):
        raise ValueError("preparatory allocation-unit bound differs")
    allowance = 536870912 + (134217728 if phase == "edges" or phase.startswith("metadata-") else 0)
    if phase.startswith("metadata-"):
        allowance += 134217728
    if phase.startswith("compat-"):
        allowance = 1073741824  # prior768MiB plus the complete reviewed256MiB tranche
    if phase.startswith("reports-"):
        allowance = 1207959552  # prior1GiB plus the prospective128MiB report tranche
    if phase.startswith("quantity-"):
        allowance = 1275068416  # prior1152MiB plus the prospective64MiB quantity tranche
    if phase.startswith("bindings-"):
        allowance = 1342177280  # prior1216MiB plus the prospective64MiB binding tranche
    if phase.startswith("sidecars-"):
        allowance = 1409286144  # prior1280MiB plus the prospective64MiB sidecar tranche
    if phase in ("sidecars-edges-red-01", "sidecars-green-01"):
        allowance = 1426063360  # review-found failure cases add their own16MiB tranche
    if phase.startswith("readers-"):
        allowance = 1493172224  # prior1360MiB plus the prospective64MiB adapter tranche
    if phase.startswith("writefacts-"):
        allowance = 1526726656  # prior1424MiB plus the prospective32MiB fact-correction tranche
    if phase.startswith("headers-"):
        allowance = 1560281088  # prior1456MiB plus the prospective32MiB header/cleanup tranche
    if phase in ("headers-owner-red-01", "headers-green-01"):
        allowance = 1577058304  # review-found ownership cases have a separate16MiB tranche
    if phase.startswith("artreads-"):
        allowance = 1610612736  # prior1504MiB plus the prospective32MiB fixed-role reads tranche
    if free["c"] < 42949672960 + allowance or free["temporary"] < 1073741824 + allowance:
        raise ValueError("preparatory physical floor is insufficient")
    if phase.startswith(("compat-", "reports-", "quantity-", "bindings-", "sidecars-", "readers-", "writefacts-", "headers-", "artreads-")):
        # Payload scattering and all previously unbacked fixed ext4 metadata,
        # full guest swap and host bookkeeping have their own physical quote.
        # E also pays its entire64GiB pagefile maximum plus1GiB source forms.
        if free["c"] < 128849018880 or free["e"] < 70866960384:
            raise ValueError("compatibility physical backing reservation is insufficient")
        with Path("/proc/meminfo").open("rb") as stream:
            memory = stream.read(16385)
        if len(memory) > 16384:
            raise ValueError("compatibility memory observation exceeds bound")
        rows = dict(line.split(b":", 1) for line in memory.splitlines())
        runtime = {name.decode("ascii"): int(rows[name].split()[0]) * 1024
                   for name in (b"MemTotal", b"SwapTotal")}
        if (not 0 < runtime["MemTotal"] <= 24 * 1024**3
                or runtime["SwapTotal"] != 6 * 1024**3):
            raise ValueError("compatibility VM memory/swap geometry differs")
    if time.monotonic_ns() >= deadline["absolute_monotonic_ns"] - 15_000_000_000:
        raise ValueError("preparatory deadline expired before namespace allocation")
    output.mkdir(mode=0o700)
    temporary.mkdir(mode=0o700)
    os.environ["TMPDIR"] = str(temporary)
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    command = [sys.executable, "-B", "-m", "unittest", "-v", *ROSTER[phase]]
    facts, _, _ = _capture_owned_reader_v2(command=command, cwd=ROOT,
        outputs={key: output / (key + ".original") for key in ("stdout", "stderr")}, deadline=deadline)
    expected = 1 if phase in ("red", "metadata-red", "reports-red-01", "quantity-red-01", "bindings-red-01", "sidecars-red-01", "sidecars-edges-red-01", "readers-red-01", "writefacts-red-01", "headers-red-01", "headers-owner-red-01", "artreads-red-01") else 0
    closed = (not facts["causes"] and facts["closure"]["closed"] and not facts["forced"]
              and facts["signal"] is None and facts["returncode"] == expected)
    for channel in ("stdout", "stderr"):
        row = facts[channel]
        closed = closed and row is not None and row["eof"] and not row["overflow"] and not row["remainder_unknown"]
        closed = closed and row["file"]["fsync_completed"] and row["file"]["close_completed"]
    raw = _bounded_json_v2({"phase": phase, "command": command, "fresh_free_bytes": free,
        "allocation_units": units, "vm_memory_bytes": runtime,
        "expected_child_returncode": expected, "capture": facts,
        "closed_as_expected": bool(closed), "physical_acceptance": False}, 32767)
    if raw is None:
        raise ValueError("preparatory result exceeds its reviewed bound")
    path = output / "result.original.json"
    persistence = _write_result_v2(path, raw + b"\n", deadline["absolute_monotonic_ns"])
    late = time.monotonic_ns() >= deadline["absolute_monotonic_ns"]
    complete = closed and not persistence["causes"] and persistence["written_bytes"] == len(raw) + 1 and not late
    status = _bounded_json_v2({"phase": phase, "capture_closed_with_expected_child_status": bool(closed),
        "child_returncode": facts["returncode"], "result": str(path), "result_persistence": persistence,
        "deadline_exceeded": late, "red_output_review_required": phase in ("red", "metadata-red", "reports-red-01", "quantity-red-01", "bindings-red-01", "sidecars-red-01", "sidecars-edges-red-01", "readers-red-01", "writefacts-red-01", "headers-red-01", "headers-owner-red-01", "artreads-red-01")}, 2048)
    if status is None:
        raise ValueError("fixed preparatory status exceeded its reviewed bound")
    print(status.decode("ascii"), flush=True)
    return 0 if complete else 1


if __name__ == "__main__":
    raise SystemExit(main())
