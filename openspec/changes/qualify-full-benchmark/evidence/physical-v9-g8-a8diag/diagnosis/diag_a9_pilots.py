"""Amendment 9 diagnostic (non-qualifying, read-only): per-cell stock pilot validators of the policy
and resource assessments on the G8 `_a8diag` indices of attempt 4. Nothing is written under the root.
The execution closure was already cold-validated by G8 steps 1-3, so it is not reloaded here.
usage: python -B -E -s diag_a9_pilots.py <policy|resource> <inject_expected_streams:0|1>"""
import functools
import json
import sys
import traceback
from pathlib import Path

ROOT = Path("/mnt/e/STUDY/VAST/tmp/qfb-root-20261007a")
sys.path.insert(0, str(ROOT / "scripts"))
import benchmark_contract  # noqa: E402
import full_resource_qualification as frq  # noqa: E402
import publication_policy_qualification as ppq  # noqa: E402
import publication_policy_qualification_fragments_from_authority_v2 as fv2  # noqa: E402

A = ROOT / "artifacts"
POLICY_INDEX = A / "publication_policy_qualification_index_v2_qfb_20261008e_a8diag/checkpoint_policy_qualification_index.v2.json"
RESOURCE_INDEX = A / "full_resource_qualification_index_v1_qfb_20261008e_a8diag.json"
mode, inject = sys.argv[1], sys.argv[2] == "1"

if inject:
    stock = benchmark_contract.validate_required_sidecars

    @functools.wraps(stock)
    def with_streams(*args, **kwargs):
        kwargs.setdefault("expected_streams", 6)
        return stock(*args, **kwargs)

    benchmark_contract.validate_required_sidecars = with_streams


def refusal(error: BaseException) -> dict:
    chain, cause = [], error
    while cause is not None:
        chain.append(f"{type(cause).__name__}: {cause}"[:600])
        cause = cause.__cause__
    return {"status": "refused", "chain": chain,
            "where": [f"{Path(f.filename).name}:{f.lineno}" for f in traceback.extract_tb(error.__traceback__)][-4:]}


result: dict = {"mode": mode, "inject_expected_streams_6": inject, "cells": {}}
if mode == "policy":
    index = json.loads(POLICY_INDEX.read_bytes())
    policy = ppq._load_policy_contract()
    dataset = ppq._verify_descriptor(ROOT, index["dataset_manifest"], "dataset manifest", forbid_hardlinks=True)
    manifest, bindings = ppq._derive_fragment_bound_manifest(
        index["bindings"], project_root=ROOT, policy=policy,
        fragment_validator=fv2.validate_publication_policy_qualification_fragment_from_authority_v2)
    decisions, traces = set(), set()
    for pilot in index["pilots"]:
        key = (pilot["system"], pilot["resource"], pilot["codec"], pilot["topology_kind"])
        try:
            rows = ppq._default_pilot_validator(pilot, {
                "project_root": ROOT, "policy": policy, "capability_manifest": manifest,
                "bindings": bindings, "dataset_manifest": dataset})
            samples = ppq._validate_samples(rows, pilot_key=key, branches=tuple(policy.ANALYTICS_BRANCHES),
                                             minimum_samples=int(policy.MIN_CALIBRATION_SAMPLES),
                                             global_decisions=decisions, global_traces=traces)
            result["cells"]["/".join(key)] = {"status": "accepted", "samples": len(samples)}
        except Exception as error:  # diagnostic: record every cell
            result["cells"]["/".join(key)] = refusal(error)
else:
    index = json.loads(RESOURCE_INDEX.read_bytes())
    registry = frq._ArtifactRegistry()
    contract = frq._verify_resource_contract(ROOT, index["resource_contract"], registry)
    dataset = frq._verify_descriptor(ROOT, index["dataset_manifest"], "dataset manifest", forbid_hardlinks=True)
    registry.add(dataset, "dataset manifest")
    datasets = frq._load_and_verify_kpp_datasets(ROOT, dataset)
    systems, bindings = frq._verify_bindings(ROOT, index["bindings"], registry)
    seen_runs, trace_cells, samples = set(), {}, set()
    for pilot in index["pilots"]:
        key = (pilot["system"], pilot["resource"], pilot["codec"], pilot["topology_kind"])
        try:
            evidence = frq._verify_pilot_evidence(ROOT, pilot, registry)
            value = frq._default_pilot_validator(pilot, {
                "project_root": ROOT, "resource_contract": contract, "dataset_manifest": dataset,
                "datasets": datasets, "systems": systems, "bindings": bindings, "pilot_evidence": evidence})
            _row, count = frq._validate_pilot_result(value, key=key, evidence=evidence, datasets=datasets,
                                                     seen_run_ids=seen_runs, trace_cells=trace_cells,
                                                     global_samples=samples)
            result["cells"]["/".join(key)] = {"status": "accepted", "samples": count}
        except Exception as error:
            result["cells"]["/".join(key)] = refusal(error)
statuses = [cell["status"] for cell in result["cells"].values()]
result["accepted"] = statuses.count("accepted")
result["refused"] = statuses.count("refused")
print(json.dumps(result, indent=1))
