"""Real policy consumers for the explicit physical fixture, without authority claims."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import sys
import types
from typing import Any, Mapping

def _descriptor(root: Path, path: Path) -> dict[str, Any]:
    payload = path.read_bytes()
    return {"path": path.relative_to(root).as_posix(), "size_bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest()}


def validate_fixture_identity_policy_component_v1(*, project_root: Path, accepted_dir: Path) -> dict[str, Any]:
    """Use the same physical registry and actual assessor as the whole identity reader."""
    import full_publication_identity_artifacts as identity
    from publication_physical_io_v1 import PhysicalRootCustodyV1
    from publication_policy_qualification import CALIBRATION_MAPPING_FILENAME, CAPABILITY_MANIFEST_FILENAME, QUALIFICATION_RECEIPT_FILENAME

    binding = {"receipt": _descriptor(project_root, accepted_dir / QUALIFICATION_RECEIPT_FILENAME),
               "outputs": {"capability_manifest": _descriptor(project_root, accepted_dir / CAPABILITY_MANIFEST_FILENAME),
                           "calibration_mapping": _descriptor(project_root, accepted_dir / CALIBRATION_MAPPING_FILENAME)}}
    with PhysicalRootCustodyV1.open(project_root, label="fixture real identity policy component") as custody:
        registry = identity._Registry(project_root, custody)
        normalized, receipt = identity._validate_policy(binding, registry=registry, assessor=identity._default_policy_assessor)
        custody.verify()
    if normalized != binding:
        raise ValueError("identity policy component normalized different physical descriptors")
    return {"passed": True, "scope": "policy_component_only_not_complete_campaign_identity",
            "bindings": normalized, "accepted_sample_count": receipt["coverage"]["accepted_sample_count"],
            "campaign_authority": False}


def check_fixture_measured_coverage_refusals_v1(*, accepted_dir: Path) -> list[dict[str, Any]]:
    """Call the actual guardian predicate on fresh deep copies of genuine F1 outputs."""
    import publication_guardian_accepted_policy_preprocessing_contract_v1 as guardian
    from publication_policy_qualification import CALIBRATION_MAPPING_FILENAME, QUALIFICATION_RECEIPT_FILENAME

    receipt = json.loads((accepted_dir / QUALIFICATION_RECEIPT_FILENAME).read_bytes())
    original_coverage = receipt["coverage"]
    original_calibration = json.loads((accepted_dir / CALIBRATION_MAPPING_FILENAME).read_bytes())
    mutations = []
    for field, count in original_coverage.items():
        for label, bad in (("boolean", True), ("numeric_string", str(count)), ("fraction", count + 0.5)):
            mutations.append((field + ":" + label, lambda coverage, calibration, field=field, bad=bad: coverage.__setitem__(field, bad)))
    mutations.extend([
        ("missing_coverage_key", lambda coverage, calibration: coverage.pop("accepted_sample_count")),
        ("extra_coverage_key", lambda coverage, calibration: coverage.__setitem__("unapproved_count", 1)),
        ("bad_binding_count", lambda coverage, calibration: coverage.__setitem__("binding_count", 31)),
        ("bad_cell_count", lambda coverage, calibration: coverage.__setitem__("pilot_cell_count", 31)),
        ("bad_minimum", lambda coverage, calibration: coverage.__setitem__("minimum_samples_per_branch_cell", 31)),
        ("below_measured_minimum", lambda coverage, calibration: coverage.__setitem__("accepted_sample_count", 3839)),
        ("aggregate_total_disagrees", lambda coverage, calibration: coverage.__setitem__("accepted_sample_count", coverage["accepted_sample_count"] + 1)),
    ])
    systems = sorted(original_calibration["calibrations"])
    branches = sorted(original_calibration["calibrations"][systems[0]]["costs"])
    mutations.extend([
        ("missing_calibration_coordinate", lambda coverage, calibration: calibration["calibrations"][systems[0]]["costs"].pop(branches[0])),
        ("aggregate_binding_below_120", lambda coverage, calibration: calibration["calibrations"][systems[0]]["costs"][branches[0]]["cpu"].__setitem__("samples", 119)),
    ])
    results = []
    for label, mutate in mutations:
        coverage, calibration = copy.deepcopy(original_coverage), copy.deepcopy(original_calibration)
        mutate(coverage, calibration)
        try:
            guardian._validate_measured_coverage(coverage, calibration)
        except guardian.AcceptedPolicyGuardianPreprocessingContractV1Error as error:
            results.append({"case": label, "refused": True, "error": str(error),
                            "scope": "real_measured_coverage_predicate_not_complete_upstream_replay"})
        else:
            raise ValueError("real guardian measured coverage accepted invalid fixture case: " + label)
    return results


def run_approved_guardian_snapshot_red_v1(*, approved_source: bytes, approved_commit: str,
                                        materializer_kwargs: Mapping[str, Any]) -> dict[str, Any]:
    """Execute exact pre-repair default code against complete genuine new predecessors."""
    name = "fixture_approved_guardian_snapshot_v1"
    if name in sys.modules:
        raise ValueError("approved guardian snapshot module name is occupied")
    module = types.ModuleType(name)
    sys.modules[name] = module
    try:
        exec(compile(approved_source, approved_commit + ":publication_guardian_accepted_policy_preprocessing_contract_v1.py", "exec"), module.__dict__)
        try:
            module.materialize_accepted_policy_guardian_preprocessing_contract_v1(**dict(materializer_kwargs))
        except module.AcceptedPolicyGuardianPreprocessingContractV1Error as error:
            message = str(error)
            assessor_failure = "official candidate to accepted policy promotion validation drifted" in message
            if "coverage" not in message and "qualification assessor" not in message and not assessor_failure:
                raise ValueError("old default RED stopped outside the repaired behavior: " + message) from error
            old_assessment = None
            if assessor_failure:
                old_assessment = module._default_assess_policy_qualification(
                    project_root=materializer_kwargs["project_root"],
                    index_path=materializer_kwargs["completed_qualification_index_path"],
                )
                if old_assessment.get("passed") is not False:
                    raise ValueError("old guardian RED did not reproduce its default assessor refusal")
            return {"passed": True, "old_default_refused": True, "approved_commit": approved_commit,
                    "approved_source_sha256": hashlib.sha256(approved_source).hexdigest(), "error": message,
                    "old_default_assessment": old_assessment,
                    "default_dependencies": True, "campaign_authority": False}
        raise ValueError("approved old guardian unexpectedly accepted the complete repaired fixture")
    finally:
        sys.modules.pop(name, None)
