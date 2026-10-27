#!/usr/bin/env python3
"""Explicit complete real-consumer fixture; artificial observations are not Q1."""
from __future__ import annotations

import argparse
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import traceback


APPROVED_COMMIT = "299c9c0eefb83fe3031096b0e96527236678a4d2"
GUARDIAN_SOURCE = "scripts/publication_guardian_accepted_policy_preprocessing_contract_v1.py"


def _fixture_source_root_v2(entrypoint: Path) -> Path:
    path = Path(entrypoint)
    if (not path.is_absolute() or not path.is_file() or path.resolve(strict=True) != path
            or path.name not in {"build_production_fixture_v2.py", "build_per_cell_minimum_refusal_v1.py"}):
        raise ValueError("fixture entrypoint origin is missing or noncanonical")
    evidence = path.parent.parent
    change = evidence.parent
    if path.parent.name != "consumer-01" or evidence.name != "evidence":
        raise ValueError("fixture entrypoint evidence layout is unsupported")
    name = "fix-accepted-policy-preprocessing"
    if change.name == name:
        changes = change.parent
    else:
        match = re.fullmatch(r"(\d{4}-\d{2}-\d{2})-" + re.escape(name), change.name)
        if match is None or change.parent.name != "archive":
            raise ValueError("fixture entrypoint change layout is unsupported")
        date.fromisoformat(match[1])
        changes = change.parent.parent
    if changes.name != "changes" or changes.parent.name != "openspec":
        raise ValueError("fixture entrypoint repository layout is unsupported")
    return changes.parent.parent


def _lexical_path_argument(value: str | Path, *, root: Path | None = None) -> Path:
    raw = os.fspath(value)
    path = Path(raw)
    if not raw or ".." in path.parts or raw != os.path.normpath(raw):
        raise ValueError("fixture path argument has noncanonical components")
    if not path.is_absolute():
        if root is None:
            raise ValueError("fixture project root must be an exact absolute path")
        path = root / path
    if root is not None and (path == root or not path.is_relative_to(root)):
        raise ValueError("fixture directory escaped the selected project root")
    return path


def _canonical_fixture_root_v2(value: str | Path, *, source_root: Path) -> Path:
    root = _lexical_path_argument(value)
    if root.resolve(strict=True) != root or not root.is_dir() or root != source_root:
        raise ValueError("fixture project root must be the exact unaliased frozen source root")
    return root


def _canonical_fixture_directory_v2(value: str | Path, *, root: Path, fresh: bool) -> Path:
    path = _lexical_path_argument(value, root=root)
    if fresh:
        if os.path.lexists(path) or path.parent.resolve(strict=True) != path.parent or not path.parent.is_dir():
            raise ValueError("fixture output must be fresh with a canonical physical parent")
    elif path.resolve(strict=True) != path or not path.is_dir():
        raise ValueError("fixture input directory must be canonical and physical")
    return path


def _git(root: Path, *args: str, source_capture=None, slot=None) -> bytes:
    if source_capture is None or slot is None:
        raise ValueError("literal Git requires its explicit fixed source capture")
    return source_capture.git(root, *args, slot=slot)


def _fixture_source_capture_v2(*, project_root, output_dir, capture_dir, deadline,
                               expected_commit, negative=False):
    from tests.fixtures.accepted_policy_literal_source_capture_v2 import LiteralSourceCaptureV2

    return LiteralSourceCaptureV2(project_root=project_root, output_dir=output_dir,
        capture_dir=capture_dir, deadline=deadline, expected_commit=expected_commit, negative=negative)


def _add_fixture_execution_arguments_v2(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--compiler-qualification-json", required=True)
    parser.add_argument("--compiler-admission-json", required=True)
    parser.add_argument("--compiler-deadline-ns", type=int, required=True)
    parser.add_argument("--reader-deadline-json", required=True)
    parser.add_argument("--source-capture-dir", required=True)
    parser.add_argument("--qualification-samples-json")


def _fixture_execution_inputs_v2(args):
    """Read bounded data arguments; existing gates still authenticate authority."""
    from publication_operational_request_domain_v1 import strict_json_object_v1
    from tests.fixtures.accepted_policy_native_fixture_v2 import MAX_FIXTURE_COMPLETED_SAMPLES_PER_BRANCH_V2
    from tests.fixtures.accepted_policy_fixture_compiler_admission_v1 import _compiler_preparation_clock_v1
    from tests.fixtures.accepted_policy_standalone_reader_fixture_v2 import _sealed_deadline_v2

    values = []
    raw_values = [args.compiler_qualification_json, args.compiler_admission_json, args.reader_deadline_json]
    if args.qualification_samples_json is not None:
        raw_values.append(args.qualification_samples_json)
    for raw in raw_values:
        if type(raw) is not str or len(raw) > 4096:
            raise ValueError("fixture execution JSON argument exceeds its bound")
        values.append(strict_json_object_v1(raw.encode("utf-8"), max_bytes=4096))
    qualification, admission, reader_deadline = values[:3]
    overrides = values[3] if len(values) == 4 else None
    if overrides is not None and (len(overrides) > 32 or any(
            type(value) is not int or not 1 <= value <= MAX_FIXTURE_COMPLETED_SAMPLES_PER_BRANCH_V2
            for value in overrides.values())):
        raise ValueError("fixture qualification overrides exceed their count/value bounds")
    _sealed_deadline_v2(reader_deadline)
    _compiler_preparation_clock_v1(args.compiler_deadline_ns)
    return qualification, admission, reader_deadline, overrides


def _fixture_observation_maps_v2(observations: Path):
    from publication_physical_io_v1 import PhysicalRootCustodyV1
    from tests.fixtures.accepted_policy_fixture_compiler_v1 import _json_bound

    values = []
    with PhysicalRootCustodyV1.open(observations, label="fixture producer observations") as custody:
        for name in ("image-inspect-map.json", "device-probe-map.json"):
            _, payload = custody.read_descriptor(observations / name, label=name,
                maximum=16 * 1024**2, capture=True)
            custody.verify()
            value = json.loads(payload)
            del payload
            if type(value) is not dict:
                raise ValueError("fixture observation map requires a JSON object")
            _json_bound(value)
            values.append(value)
    return values[0], values[1]


def _fixture_entrypoint_sha256_v2(root: Path, entrypoint: Path) -> str:
    from publication_physical_io_v1 import PhysicalRootCustodyV1

    with PhysicalRootCustodyV1.open(root, label="fixture producer entrypoint") as custody:
        descriptor, _ = custody.read_descriptor(entrypoint, label="fixture producer entrypoint",
            maximum=2 * 1024**2, capture=False)
        custody.verify()
    return descriptor["sha256"]


class FixtureReportPersistenceRefusedV2(ValueError):
    def __init__(self, facts, *, late=False, clock_error=None):
        self.facts = facts
        self.primary, self.secondary = clock_error, ()
        self.causes = facts["causes"].copy()
        if late and "fixture_report_deadline_exceeded" not in self.causes:
            self.causes.append("fixture_report_deadline_exceeded")
        if clock_error is not None and "fixture_report_clock_unavailable" not in self.causes:
            self.causes.append("fixture_report_clock_unavailable")
        super().__init__("fixture producer report persistence is incomplete")


class _FixtureProducerFailureV2(ValueError):
    def __init__(self, primary, secondary):
        self.primary, self.secondary = primary, tuple(secondary)
        super().__init__("fixture producer failed; distinct finalization causes retained")


def _raise_fixture_producer_failure_v2(primary, secondary):
    distinct = []
    for error in secondary:
        if error is not primary and not any(error is previous for previous in distinct):
            distinct.append(error)
    if distinct:
        raise _FixtureProducerFailureV2(primary, distinct) from primary
    raise primary


def _fresh_json(path: Path, value: object, *, absolute_deadline_ns=None):
    from tests.fixtures.accepted_policy_fixture_report_v1 import REPORT_LIMIT, fixture_report_bytes_v1
    from tests.fixtures.accepted_policy_standalone_reader_fixture_v2 import _monotonic_ns, _write_result_v2

    if (type(absolute_deadline_ns) is not int or absolute_deadline_ns <= 0
            or _monotonic_ns() >= absolute_deadline_ns):
        raise ValueError("fixture report requires an unexpired inherited absolute deadline")

    # Preserve the original text writer's native final newline, including its
    # extra byte on Windows, within the complete physical report ceiling.
    raw = fixture_report_bytes_v1(value, limit=REPORT_LIMIT - (len(os.linesep) - 1))
    raw = raw[:-1] + os.linesep.encode("ascii")
    if _monotonic_ns() >= absolute_deadline_ns:
        raise ValueError("fixture report deadline expired during encoding")
    facts = _write_result_v2(path, raw, absolute_deadline_ns)
    try:
        late = _monotonic_ns() >= absolute_deadline_ns
    except BaseException as clock_error:
        raise FixtureReportPersistenceRefusedV2(facts, clock_error=clock_error) from clock_error
    if (facts["attempted"] is not True or type(facts["written_bytes"]) is not int
            or facts["written_bytes"] != len(raw) or facts["write_extent_unknown"] is not False
            or facts["fsync_completed"] is not True or facts["close_completed"] is not True
            or facts["causes"] or late):
        raise FixtureReportPersistenceRefusedV2(facts, late=late)
    return facts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--expected-source-commit", required=True)
    parser.add_argument("--artifact-base", required=True)
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--socket-prefix", default=".apfv2")
    parser.add_argument("--samples-per-branch", type=int, default=30)
    parser.add_argument("--stage", choices=("inputs", "original-observations", "complete"), default="complete")
    _add_fixture_execution_arguments_v2(parser)
    args = parser.parse_args()
    source_root = _fixture_source_root_v2(Path(__file__))
    root = _canonical_fixture_root_v2(args.project_root, source_root=source_root)
    if re.fullmatch(r"[0-9a-f]{40}", args.expected_source_commit) is None:
        raise ValueError("expected source commit must be an exact commit SHA")
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(root / "scripts"))
    from tests.fixtures.accepted_policy_native_fixture_v2 import MAX_FIXTURE_COMPLETED_SAMPLES_PER_BRANCH_V2

    qualification, admission, reader_deadline, overrides = _fixture_execution_inputs_v2(args)
    if (type(args.samples_per_branch) is not int or args.samples_per_branch < 30
            or args.samples_per_branch > MAX_FIXTURE_COMPLETED_SAMPLES_PER_BRANCH_V2):
        raise ValueError("complete fixture requires 30..985 samples in every branch cell")
    if re.fullmatch(r"[a-z0-9][a-z0-9-]{0,100}", args.namespace) is None:
        raise ValueError("fixture upstream namespace is invalid")
    base = _canonical_fixture_directory_v2(args.artifact_base, root=root, fresh=False)
    output = _canonical_fixture_directory_v2(args.output_dir, root=root, fresh=True)
    with _fixture_source_capture_v2(project_root=root, output_dir=output, capture_dir=args.source_capture_dir,
            deadline=reader_deadline, expected_commit=args.expected_source_commit) as source_capture:
        _run_fixture_v2(args, root, qualification, admission, reader_deadline, overrides, base, output, source_capture)


def _run_fixture_v2(args, root, qualification, admission, reader_deadline, overrides, base, output, source_capture):
    if _git(root, "rev-parse", "HEAD", source_capture=source_capture, slot="head").decode().strip() != args.expected_source_commit:
        raise ValueError("fixture source HEAD differs from the explicitly pinned commit")
    if _git(root, "status", "--porcelain", "--untracked-files=no", source_capture=source_capture, slot="status"):
        raise ValueError("fixture tracked source is not clean")
    from tests.fixtures.accepted_policy_fixture_provenance_v1 import loaded_fixture_production_sources_v1
    from tests.fixtures.accepted_policy_physical_fixture_v2 import (
        _fixture_operation_sample_counts_v2, build_original_native_fixture_observations_v2,
        prepared_complete_fixture_inputs_v2,
    )
    from tests.fixtures.accepted_policy_consumer_fixture_v2 import complete_fixture_production_consumers_v2

    original_sources = loaded_fixture_production_sources_v1(project_root=root)
    approved_source = _git(root, "show", APPROVED_COMMIT + ":" + GUARDIAN_SOURCE,
        source_capture=source_capture, slot="guardian")
    report = {"schema_version": 2, "fixture_stage": args.stage,
              "campaign_authority": False, "physical_inference_observed": False,
              "complete_consumer_positive_asserted": False,
              "upstream_root": str(root), "source_commit": args.expected_source_commit,
              "entrypoint_sha256": _fixture_entrypoint_sha256_v2(root, Path(__file__)),
              "samples_per_branch": args.samples_per_branch,
              "expected_measured_sample_count": 32 * 4 * args.samples_per_branch if overrides is None else None,
              "approved_old_guardian_commit": APPROVED_COMMIT,
              "approved_old_guardian_source_sha256": hashlib.sha256(approved_source).hexdigest(),
              "initial_loaded_production_sources": original_sources}

    def phase(name: str) -> None:
        current = loaded_fixture_production_sources_v1(project_root=root)
        by_name = {row["module"]: row for row in current}
        if any(by_name.get(row["module"]) != row for row in original_sources):
            raise ValueError("previously loaded production source changed during the fixture")
        print(json.dumps({"fixture_phase": name, "output_dir": str(output),
                          "production_module_count": len(current)}, sort_keys=True), flush=True)
        if output.is_dir():
            _fresh_json(output / ("producer-phase-" + name + ".v2.json"),
                        {"phase": name, "source_commit": args.expected_source_commit,
                         "loaded_production_sources": current, "campaign_authority": False},
                        absolute_deadline_ns=reader_deadline["absolute_monotonic_ns"])

    phase("00-imported")
    config_base = root / "configs" / f"checkpoint_analytics_model_parity.refreshed.v4.{args.namespace}.accepted"
    observations = base / "consumer-runtime-observations-02"
    try:
        image_inspections, device_probes = _fixture_observation_maps_v2(observations)
        with prepared_complete_fixture_inputs_v2(
            project_root=root, output_dir=output,
            identity_patch_path=base / "qualification_image_identity_patch.json",
            accepted_model_parity_manifest_path=config_base.with_suffix(".accepted.yaml"),
            accepted_model_parity_assessment_path=Path(str(config_base) + ".assessment.json"),
            accepted_model_parity_receipt_path=Path(str(config_base) + ".acceptance_receipt.json"),
            image_inspections=image_inspections, device_probes=device_probes,
            socket_prefix=args.socket_prefix,
            compiler_qualification=qualification, compiler_admission=admission,
            compiler_absolute_deadline_ns=args.compiler_deadline_ns,
        ) as prepared:
            sample_counts = _fixture_operation_sample_counts_v2(prepared["capture_plan"],
                samples_per_branch=args.samples_per_branch, qualification_samples_by_operation_id=overrides)
            report["expected_measured_sample_count"] = 4 * sum(
                sample_counts[row["operation_id"]] for row in prepared["capture_plan"]["operation_manifest"]["operations"]
                if row["phase"] == "qualification_cell")
            phase("01-prepared")
            report.update(transaction_receipt=str(prepared["transaction"]["transaction_receipt_path"]),
                          preprocessing_receipt=str(prepared["preprocessing"]["receipt_path"]),
                          capture_plan=prepared["capture_plan_descriptor"],
                          runtime_input_receipt=str(prepared["runtime"]["receipt_path"]))
            if args.stage != "inputs":
                native = build_original_native_fixture_observations_v2(prepared=prepared,
                    samples_per_branch=args.samples_per_branch, qualification_samples_by_operation_id=overrides)
                phase("02-originals")
                report.update(original_operation_count=len(native["operations"]),
                              qualification_count=native["qualification_count"], native_domains=native["native_domains"])
                if args.stage == "complete":
                    consumers = complete_fixture_production_consumers_v2(
                        prepared=prepared, native=native, approved_guardian_source=approved_source,
                        approved_guardian_commit=APPROVED_COMMIT,
                        standalone_reader_deadline=reader_deadline,
                    )
                    if consumers["assessment"]["coverage"]["accepted_sample_count"] != report["expected_measured_sample_count"]:
                        raise ValueError("real F1 measured sample count includes a drop or loses a branch cell")
                    phase("03-complete-consumers")
                    report.update(consumers=consumers, complete_consumer_positive_asserted=True)
            report["final_loaded_production_sources"] = loaded_fixture_production_sources_v1(project_root=root)
            _fresh_json(output / "producer-stage-report.v2.json", report,
                        absolute_deadline_ns=reader_deadline["absolute_monotonic_ns"])
            print(json.dumps({"fixture_completed": args.stage,
                              "complete_consumer_positive_asserted": report["complete_consumer_positive_asserted"],
                              "report_path": str(output / "producer-stage-report.v2.json")}, sort_keys=True), flush=True)
    except Exception as error:
        try:
            if output.is_dir() and not (output / "producer-failure.v2.json").exists():
                _fresh_json(output / "producer-failure.v2.json",
                            {**report, "complete_consumer_positive_asserted": False,
                             "error_type": type(error).__name__, "error": str(error), "traceback": traceback.format_exc()},
                            absolute_deadline_ns=reader_deadline["absolute_monotonic_ns"])
        except BaseException as secondary:
            _raise_fixture_producer_failure_v2(error, [secondary])
        raise


if __name__ == "__main__":
    main()
