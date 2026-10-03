from __future__ import annotations

import copy
import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import publication_q4_authority_source_material_v1 as source_material  # noqa: E402
import publication_q4_authority_source_request_v1 as target  # noqa: E402
import backend_q4_two_phase_source_registry_v1 as source_registry  # noqa: E402
import benchmark_contract  # noqa: E402
import checkpoint_gstreamer_analytics_sidecar as analytics_sidecar  # noqa: E402
import checkpoint_model_parity_acceptance_v4 as model_acceptance  # noqa: E402
import publication_guardian_accepted_policy_preprocessing_contract_v1 as accepted_guardian  # noqa: E402
import publication_q4_authority_plan_pipeline_v1 as authority_pipeline  # noqa: E402
import publication_q4_runtime_contract_v4 as runtime_contract  # noqa: E402
import publication_q4_runtime_registry_materializer_v4 as runtime_registry  # noqa: E402
from test_publication_q4_authority_plan_pipeline_v1 import (  # noqa: E402
    Fixture,
    named_sha,
    semantic,
)
from test_publication_policy_contract import (  # noqa: E402
    calibration as policy_calibration,
    valid_capability_manifest,
)


class SyntheticMaterializationCrash(BaseException):
    pass


@contextmanager
def patched_production_seams(seams: dict[str, object]):
    with (
        mock.patch.object(
            benchmark_contract,
            "load_dataset",
            side_effect=seams["load_dataset"],
        ),
        mock.patch.object(
            model_acceptance,
            "load_verified_model_parity_acceptance_v4",
            side_effect=seams["load_model_parity"],
        ),
        mock.patch.object(
            accepted_guardian,
            "load_accepted_policy_guardian_preprocessing_contract_v1",
            side_effect=seams["load_guardian"],
        ),
        mock.patch.object(
            analytics_sidecar,
            "validate_publication_sidecar_service_authority_v1",
            side_effect=seams["validate_service"],
        ),
    ):
        yield


def request_for(fixture: Fixture, run: str = "Q") -> dict[str, object]:
    _unused_path, source_spec = fixture.source_spec(run)
    accepted = {
        key: fixture.descriptor(fixture.root / str(path))
        for key, path in fixture.accepted_sources().items()
        if key.endswith("_path")
    }
    datasets = [
        {
            "codec_variant": row["codec_variant"],
            "front_gate": fixture.descriptor(
                fixture.root / str(row["front_gate_path"])
            ),
            "underbody": fixture.descriptor(
                fixture.root / str(row["underbody_path"])
            ),
        }
        for row in fixture.dataset_sources
    ]
    return source_material.build_publication_q4_authority_source_material_request_v1(
        accepted_upstream_identities=fixture.upstream,
        accepted_source_descriptors=accepted,
        expected_analytics_service_identity_sha256=fixture.service_identity,
        dataset_source_descriptors=datasets,
        runtime_authority_requests=[
            {
                "coordinate": copy.deepcopy(row["coordinate"]),
                "inputs": copy.deepcopy(row["inputs"]),
            }
            for row in fixture.runtime_builds
        ],
        launcher_runtime_authority_builds=fixture.launcher_builds,
        publication_launcher_invocation_v3_sha256=fixture.invocation_sha,
        q4_validator_authority_build=fixture.validator_build,
        runner_authority_build=fixture.runner_build,
        planned_outputs=source_spec["planned_outputs"],
    )


def prepared_for(
    fixture: Fixture, request: dict[str, object]
) -> target.PreparedPublicationQ4SourceRequestV1:
    launchers = {
        str(build["system"]): fixture.descriptor(
            fixture.root / str(build["runtime_closure_manifest_path"])
        )
        for build in fixture.launcher_builds
    }
    return target.PreparedPublicationQ4SourceRequestV1(
        request=copy.deepcopy(request),
        qualification_runtime_input_materialization_receipt=fixture.image_patch,
        support_artifacts={
            "policy_calibrations": {
                system: copy.deepcopy(fixture.policy_calibrations[system])
                for system in ("deepstream", "savant", "openvino_gva", "gstreamer_custom")
            },
            "policy_static_maps": {
                system: copy.deepcopy(fixture.policy_static_maps[system])
                for system in ("deepstream", "savant", "openvino_gva", "gstreamer_custom")
            },
            "python_executable": fixture.descriptor(
                fixture.root / "launcher/python"
            ),
            "launcher_runtime_closure_manifests": launchers,
            "runner_runtime_bundle_manifest": fixture.descriptor(
                fixture.root / str(
                    fixture.runner_build["runtime_bundle_manifest_path"]
                )
            ),
            "validator_implementation": copy.deepcopy(
                fixture.validator_build["implementation_descriptor"]
            ),
        },
    )


def prepare_callback(
    prepared: target.PreparedPublicationQ4SourceRequestV1,
):
    def prepare(_custody, _output_relative, _owned):
        return copy.deepcopy(prepared)

    return prepare


from test_checkpoint_external_execution_manifest import worker_manifest_fixture, producer as native_producer


def production_inputs_for(
    fixture: Fixture,
) -> tuple[
    target.ProductionPublicationQ4SourceRequestInputsV1,
    dict[str, object],
]:
    """Create production-shaped accepted inputs around the public plan fixture."""

    workers = worker_manifest_fixture(fixture.execution_config)
    capability_value = workers.policy
    policy_sha = str(capability_value["policy_contract_sha256"])
    calibration_values = {
        system: policy_calibration(system, capability_value)
        for system in runtime_contract.SYSTEMS
    }
    mapping_value = {
        "schema_version": 1,
        "artifact_kind": "vast_publication_policy_calibration_mapping",
        "policy_contract_sha256": policy_sha,
        "aggregation_rule": "median_of_balanced_native_codec_topology_cells_v1",
        "minimum_samples_per_branch_cell": 30,
        "calibrations": copy.deepcopy(calibration_values),
    }
    accepted_root = "production/accepted"
    capability = fixture.write_json(
        f"{accepted_root}/checkpoint_policy_capability_manifest.json",
        capability_value,
    )
    mapping = fixture.write_json(
        f"{accepted_root}/checkpoint_policy_calibration_mapping.json",
        mapping_value,
    )
    dataset_manifest = copy.deepcopy(fixture.dataset_manifest)

    def receipt_output(descriptor: dict[str, object]) -> dict[str, object]:
        return {
            **copy.deepcopy(descriptor),
            "path": Path(str(descriptor["path"])).name,
        }

    policy_unsigned = {
        "schema_version": 1,
        "artifact_kind": "vast_publication_policy_qualification_receipt",
        "status": "accepted_evidence_driven_policy_qualification",
        "policy_contract_sha256": policy_sha,
        "dataset_manifest_sha256": dataset_manifest["sha256"],
        "coverage": {
            "binding_count": 32,
            "pilot_cell_count": 32,
            "accepted_sample_count": 3840,
        },
        "outputs": {
            "capability_manifest": receipt_output(capability),
            "calibration_mapping": receipt_output(mapping),
        },
    }
    policy_receipt_value = {
        **policy_unsigned,
        "sha256": semantic(policy_unsigned),
    }
    policy_receipt = fixture.write_json(
        f"{accepted_root}/checkpoint_policy_qualification_receipt.json",
        policy_receipt_value,
    )

    resource_contract = {"contract_version": 2}
    resource_unsigned = {
        "schema_version": 1,
        "artifact_kind": "vast_pre_run_full_resource_capability_manifest",
        "resource_contract": resource_contract,
        "resource_contract_identity_sha256": semantic(resource_contract),
    }
    resource_value = {
        **resource_unsigned,
        "content_sha256": semantic(resource_unsigned),
    }
    resource_capability = fixture.write_json(
        f"{accepted_root}/checkpoint_full_resource_capability_manifest.json",
        resource_value,
    )
    resource_receipt_unsigned = {
        "schema_version": 1,
        "artifact_kind": (
            "vast_pre_run_full_resource_capability_qualification_receipt"
        ),
        "status": "accepted_pre_run_resource_capability_qualification",
        "dataset_manifest_sha256": dataset_manifest["sha256"],
        "resource_contract_identity_sha256": resource_value[
            "resource_contract_identity_sha256"
        ],
        "capability_manifest_content_sha256": resource_value["content_sha256"],
        "outputs": {
            "capability_manifest": receipt_output(resource_capability),
        },
    }
    resource_receipt_value = {
        **resource_receipt_unsigned,
        "sha256": semantic(resource_receipt_unsigned),
    }
    resource_receipt = fixture.write_json(
        f"{accepted_root}/checkpoint_full_resource_qualification_receipt.json",
        resource_receipt_value,
    )

    preprocessing_value = {"fixture": "accepted-policy-preprocessing"}
    preprocessing_contract = fixture.write_json(
        f"{accepted_root}/checkpoint_analytics_accepted_policy_preprocessing_contract.v1.json",
        preprocessing_value,
    )
    preprocessing_receipt_value = {
        "accepted_policy_qualification_receipt": copy.deepcopy(policy_receipt),
        "accepted_policy_capability_manifest": copy.deepcopy(capability),
        "accepted_policy_calibration_mapping": copy.deepcopy(mapping),
        "execution_config": copy.deepcopy(fixture.execution_config),
    }
    preprocessing_receipt = fixture.write_json(
        f"{accepted_root}/checkpoint_analytics_accepted_policy_preprocessing_contract.v1.receipt.json",
        preprocessing_receipt_value,
    )
    preprocessing_authority = copy.deepcopy(fixture.preprocessing_authority)
    preprocessing_authority.update(
        {
            "preprocessing_contract_content_sha256": workers.preprocessing,
            "preprocessing_contract_file_sha256": preprocessing_contract[
                "sha256"
            ],
            "materialization_receipt_identity_sha256": semantic(
                preprocessing_receipt_value
            ),
            "materialization_receipt_file_sha256": preprocessing_receipt[
                "sha256"
            ],
            "accepted_policy_qualification_receipt_identity_sha256": (
                policy_receipt_value["sha256"]
            ),
            "accepted_policy_qualification_receipt_file_sha256": (
                policy_receipt["sha256"]
            ),
            "accepted_policy_capability_manifest_file_sha256": capability[
                "sha256"
            ],
            "accepted_policy_capability_manifest_content_sha256": semantic(
                capability_value
            ),
            "accepted_policy_calibration_mapping_file_sha256": mapping[
                "sha256"
            ],
            "accepted_policy_calibration_mapping_content_sha256": semantic(
                mapping_value
            ),
            "policy_contract_sha256": policy_sha,
        }
    )
    service_identity = named_sha("production-source-request-service")
    service_unsigned = {
        "front_socket": fixture.socket_binding(
            fixture.analytics_path, endpoint=False
        ),
        "preprocessing_contract_authority": copy.deepcopy(
            preprocessing_authority
        ),
        "service_identity_sha256": service_identity,
    }
    service_value = {
        **service_unsigned,
        "service_authority_sha256": semantic(service_unsigned),
    }
    service_authority = fixture.write_json(
        f"{accepted_root}/service_authority.v1.json", service_value
    )

    parity_receipt = copy.deepcopy(fixture.parity_receipt)
    parity_binding = {
        "receipt": parity_receipt,
        "accepted_manifest_content_identity_sha256": fixture.upstream[
            "model_parity_manifest_identity_sha256"
        ],
        "binding_sha256": fixture.upstream[
            "model_parity_acceptance_binding_sha256"
        ],
    }

    helper_path = "scripts/producer_fixture_leaf.py"
    fixture.write_bytes(helper_path, b"VALUE = 'production-source-request'\n")
    for system, launcher_path in target._LAUNCHER_PATH_BY_SYSTEM.items():
        fixture.write_bytes(
            launcher_path,
            (
                "import producer_fixture_leaf\n"
                f"SYSTEM = {system!r}\n"
            ).encode("ascii"),
        )
    for system, runtime_path in target._RUNTIME_PATH_BY_SYSTEM.items():
        fixture.write_bytes(
            runtime_path, f"SYSTEM = {system!r}\n".encode("ascii")
        )
    fixture.write_bytes(
        "scripts/publication_q4_evidence_validator_v4.py",
        b"import producer_fixture_leaf\ndef validate(value):\n    return value\n",
    )
    fixture.write_bytes(
        "scripts/publication_q4_evidence_runner_v4.py",
        b"import publication_q4_evidence_validator_v4\ndef main():\n    return 0\n",
    )
    python_source = fixture.root / "production/python3"
    python_source.parent.mkdir(parents=True, exist_ok=True)
    python_source.write_bytes(b"production-python-executable\n")

    runtime_by_coordinate = {
        (
            row["coordinate"]["system"],
            row["coordinate"]["codec"],
            row["coordinate"]["topology_kind"],
            row["coordinate"]["policy"],
        ): row
        for row in fixture.runtime_builds
    }
    runtime_dir = "production/runtime-inputs"
    bundles: list[dict[str, object]] = []
    for system in runtime_contract.SYSTEMS:
        for resource in ("cpu", "gpu"):
            policy = "cpu_only" if resource == "cpu" else "gpu_only"
            for codec in runtime_contract.CODECS:
                for topology in runtime_contract.TOPOLOGIES:
                    row = runtime_by_coordinate[
                        (system, codec, topology, policy)
                    ]
                    wrapper = row["inputs"][
                        "system_specific_launcher_input"
                    ]["content"]
                    template = wrapper["qualification_projection"][
                        "runtime_input_template"
                    ]
                    template = copy.deepcopy(template)
                    if system in {"openvino_gva", "gstreamer_custom"}:
                        _, payload, _ = native_producer._adapter_asset(workers.inventory, system=system, final_root=ROOT / "artifacts/test-q4-manifest")
                        native_manifest = json.loads(payload)
                        native_descriptor = fixture.write_json(f"{runtime_dir}/{system}-execution.json", native_manifest)
                        template["files"]["analytics_execution_manifest"] = {**native_descriptor, "container_path": f"/opt/vast/{system}/execution.json"}
                    bundle_unsigned = {
                        "schema_version": 2,
                        "artifact_kind": (
                            "vast_qualification_native_runtime_input_bundle_v2"
                        ),
                        "status": "materialized_for_native_qualification_only",
                        "accepted": False,
                        "publication_ready": False,
                        "authorization_eligible": False,
                        "system": system,
                        "resource": resource,
                        "codec": codec,
                        "topology_kind": topology,
                        "runtime_inputs": {
                            "dataset": {
                                runtime_contract.RUNTIME_INPUT_KEY_BY_SYSTEM[
                                    system
                                ]: copy.deepcopy(template)
                            }
                        },
                    }
                    bundle_value = {
                        **bundle_unsigned,
                        "bundle_sha256": semantic(bundle_unsigned),
                    }
                    filename = (
                        f"{system}-{resource}-{codec}-{topology}.v2.json"
                    )
                    descriptor = fixture.write_json(
                        f"{runtime_dir}/{filename}", bundle_value
                    )
                    bundles.append(
                        {
                            "path": filename,
                            "size_bytes": descriptor["size_bytes"],
                            "sha256": descriptor["sha256"],
                            "bundle_sha256": bundle_value["bundle_sha256"],
                        }
                    )
    qualification_unsigned = {
        "schema_version": 2,
        "artifact_kind": (
            "vast_qualification_native_runtime_input_materialization_v2"
        ),
        "status": "materialized_for_native_qualification_only",
        "accepted": False,
        "publication_ready": False,
        "authorization_eligible": False,
        "scope": "pre_run_policy_and_full_resource_qualification_only",
        "blockers": [
            "qualification_runtime_inputs_are_not_production_authority"
        ],
        "bundles": bundles,
    }
    qualification_value = {
        **qualification_unsigned,
        "receipt_sha256": semantic(qualification_unsigned),
    }
    qualification_receipt = fixture.write_json(
        f"{runtime_dir}/qualification-runtime-inputs.materialization.v2.json",
        qualification_value,
    )

    fixture.policy_capability = capability
    fixture.policy_calibration = mapping
    fixture.policy_calibration_values = calibration_values
    fixture.policy_receipt = policy_receipt
    fixture.resource_capability = resource_capability
    fixture.resource_receipt = resource_receipt
    fixture.preprocessing_contract = preprocessing_contract
    fixture.preprocessing_receipt = preprocessing_receipt
    fixture.preprocessing_authority = preprocessing_authority
    fixture.service_authority = service_authority
    fixture.service_identity = service_identity
    fixture.upstream.update(
        {
            "policy_contract_sha256": policy_sha,
            "policy_qualification_receipt_sha256": policy_receipt_value[
                "sha256"
            ],
            "resource_contract_identity_sha256": resource_value[
                "resource_contract_identity_sha256"
            ],
            "resource_qualification_receipt_sha256": resource_receipt_value[
                "sha256"
            ],
        }
    )

    datasets_by_codec = {
        str(row["codec_variant"]): row for row in fixture.dataset_sources
    }

    def load_dataset(
        _manifest: Path,
        dataset_name: str,
        **_kwargs: object,
    ) -> dict[str, object]:
        codec = dataset_name.rsplit("_", 1)[-1]
        row = datasets_by_codec[codec]
        return {
            "codec_variant": codec,
            "logical_stream_instances": runtime_contract.STREAMS,
            "streams": [
                {
                    "path": row["front_gate_path"],
                    "camera_role": "front_gate",
                },
                {
                    "path": row["underbody_path"],
                    "camera_role": "foreign_object",
                },
            ],
        }

    accepted_paths = {
        "model_parity_acceptance_receipt_path": parity_receipt["path"],
        "policy_qualification_receipt_path": policy_receipt["path"],
        "policy_capability_manifest_path": capability["path"],
        "policy_calibration_mapping_path": mapping["path"],
        "resource_qualification_receipt_path": resource_receipt["path"],
        "resource_capability_manifest_path": resource_capability["path"],
        "analytics_service_authority_path": service_authority["path"],
        "guardian_preprocessing_contract_path": preprocessing_contract["path"],
        "guardian_preprocessing_receipt_path": preprocessing_receipt["path"],
    }
    production_inputs = target.ProductionPublicationQ4SourceRequestInputsV1(
        accepted_source_paths=accepted_paths,
        dataset_manifest_path=dataset_manifest["path"],
        qualification_runtime_input_materialization_receipt_path=(
            qualification_receipt["path"]
        ),
        planned_outputs={
            "runtime_candidate_registry_path": (
                "transactions/P/runtime-candidate-registry.v4.json"
            ),
            "runtime_materialization_result_path": (
                "transactions/P/runtime-materialization-result.v4.json"
            ),
            "source_registry_path": (
                "transactions/P/q4-source-registry.v1.json"
            ),
            "source_materialization_result_path": (
                "transactions/P/source-materialization-result.v1.json"
            ),
        },
        python_executable_source=python_source,
    )
    seams: dict[str, object] = {
        "load_dataset": load_dataset,
        "load_model_parity": lambda **_kwargs: copy.deepcopy(parity_binding),
        "load_guardian": lambda **_kwargs: {
            "receipt": copy.deepcopy(preprocessing_receipt_value),
            "authority": copy.deepcopy(preprocessing_authority),
        },
        "validate_service": lambda _value: copy.deepcopy(service_value),
        "mapping_value": mapping_value,
        "execution_config": copy.deepcopy(fixture.execution_config),
    }
    return production_inputs, seams


class PublicationQ4AuthoritySourceRequestV1Tests(unittest.TestCase):
    def test_receipt_last_roundtrip_uses_public_112_authority_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = Fixture(root)
            try:
                request = request_for(fixture)
                receipt = target.materialize_publication_q4_authority_source_request_v1(
                    project_root=root,
                    output_dir="transactions/request",
                    prepare_request=prepare_callback(prepared_for(fixture, request)),
                )
                output = root / "transactions/request"
                self.assertEqual(
                    sorted(item.name for item in output.iterdir()),
                    sorted((target.REQUEST_FILENAME, target.RECEIPT_FILENAME)),
                )
                self.assertFalse(receipt["authorization_eligible"])
                self.assertFalse(receipt["execution_authorized"])
                self.assertEqual(receipt["runtime_authority_request_count"], 112)
                self.assertEqual(receipt["launcher_runtime_authority_build_count"], 4)
                self.assertEqual(
                    receipt["projected_source_material_sha256"],
                    source_material.build_publication_q4_authority_source_material_v1(
                        project_root=root, request=request
                    )[1],
                )
            finally:
                fixture.close()

    def test_output_root_confinement_rejects_before_prepare(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            called = False

            def prepare(_custody, _output_relative, _owned):
                nonlocal called
                called = True
                raise AssertionError("prepare must not run")

            with self.assertRaisesRegex(Exception, "unsafe|escaped"):
                target.materialize_publication_q4_authority_source_request_v1(
                    project_root=root,
                    output_dir="../outside",
                    prepare_request=prepare,
                )
            self.assertFalse(called)
            self.assertFalse(root.parent.joinpath("outside", target.RECEIPT_FILENAME).exists())

    def test_post_preflight_tamper_rolls_back_request_without_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = Fixture(root)
            try:
                request = request_for(fixture)
                capability = request["accepted_source_descriptors"][
                    "policy_capability_manifest_path"
                ]

                def tamper() -> None:
                    (root / str(capability["path"])).write_bytes(b"tampered-after-preflight\n")

                with self.assertRaisesRegex(
                    target.PublicationQ4AuthoritySourceRequestV1Error,
                    "post-build input.*drifted",
                ):
                    target.materialize_publication_q4_authority_source_request_v1(
                        project_root=root,
                        output_dir="transactions/tamper",
                        prepare_request=prepare_callback(prepared_for(fixture, request)),
                        after_preflight=tamper,
                    )
                output = root / "transactions/tamper"
                self.assertFalse((output / target.REQUEST_FILENAME).exists())
                self.assertFalse((output / target.RECEIPT_FILENAME).exists())
            finally:
                fixture.close()

    def test_incomplete_111_authority_coverage_fails_before_commit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = Fixture(root)
            try:
                request = request_for(fixture)
                request["runtime_authority_requests"].pop()
                request["request_sha256"] = semantic(
                    {
                        key: value
                        for key, value in request.items()
                        if key != "request_sha256"
                    }
                )
                with self.assertRaisesRegex(Exception, "coverage"):
                    target.materialize_publication_q4_authority_source_request_v1(
                        project_root=root,
                        output_dir="transactions/incomplete",
                        prepare_request=prepare_callback(prepared_for(fixture, request)),
                )
                output = root / "transactions/incomplete"
                self.assertFalse(output.exists())
            finally:
                fixture.close()

    def test_same_prepared_inputs_produce_identical_canonical_request_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = Fixture(root)
            try:
                request = request_for(fixture)
                prepared = prepared_for(fixture, request)
                receipts = []
                for name in ("D1", "D2"):
                    receipts.append(
                        target.materialize_publication_q4_authority_source_request_v1(
                            project_root=root,
                            output_dir=f"transactions/{name}",
                            prepare_request=prepare_callback(prepared),
                        )
                    )
                first = root / str(receipts[0]["request"]["path"])
                second = root / str(receipts[1]["request"]["path"])
                self.assertEqual(first.read_bytes(), second.read_bytes())
                self.assertEqual(
                    hashlib.sha256(first.read_bytes()).hexdigest(),
                    hashlib.sha256(second.read_bytes()).hexdigest(),
                )
                self.assertEqual(
                    receipts[0]["request_sha256"], receipts[1]["request_sha256"]
                )
                self.assertEqual(
                    receipts[0]["projected_source_material_sha256"],
                    receipts[1]["projected_source_material_sha256"],
                )
            finally:
                fixture.close()

    def test_nonempty_namespace_is_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "transactions/existing"
            output.mkdir(parents=True)
            sentinel = output / "keep.txt"
            sentinel.write_bytes(b"keep\n")
            with self.assertRaisesRegex(Exception, "not empty"):
                target.materialize_publication_q4_authority_source_request_v1(
                    project_root=root,
                    output_dir="transactions/existing",
                    prepare_request=lambda *_args: (_ for _ in ()).throw(
                        AssertionError("prepare must not run")
                    ),
                )
            self.assertEqual(sentinel.read_bytes(), b"keep\n")
            self.assertFalse((output / target.RECEIPT_FILENAME).exists())

    def test_fault_after_every_owned_commit_rolls_back_and_same_path_retries(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            fixture = Fixture(root)
            try:
                (root / "transactions").mkdir(exist_ok=True)
                prepared = prepared_for(fixture, request_for(fixture))
                probe_token = "rollback-probe"
                probe_output = f"transactions/{probe_token}/request"
                baseline: list[tuple[str, str]] = []

                target.materialize_publication_q4_authority_source_request_v1(
                    project_root=root,
                    output_dir=probe_output,
                    prepare_request=prepare_callback(prepared),
                    after_owned_commit=lambda kind, path: baseline.append(
                        (kind, path.replace(probe_token, "<attempt>"))
                    ),
                )
                shutil.rmtree(root / "transactions" / probe_token)
                self.assertGreaterEqual(len(baseline), 4)
                self.assertIn(("file", "transactions/<attempt>/request/" + target.REQUEST_FILENAME), baseline)
                self.assertEqual(baseline[-1][0], "file")
                self.assertTrue(baseline[-1][1].endswith(target.RECEIPT_FILENAME))

                for fault_index, expected in enumerate(baseline):
                    token = f"rollback-{fault_index}"
                    output_relative = f"transactions/{token}/request"
                    observed: list[tuple[str, str]] = []

                    def fault(kind: str, path: str) -> None:
                        observed.append((kind, path.replace(token, "<attempt>")))
                        if len(observed) - 1 == fault_index:
                            raise RuntimeError("synthetic owned-commit fault")

                    with self.assertRaisesRegex(
                        RuntimeError, "synthetic owned-commit fault"
                    ):
                        target.materialize_publication_q4_authority_source_request_v1(
                            project_root=root,
                            output_dir=output_relative,
                            prepare_request=prepare_callback(prepared),
                            after_owned_commit=fault,
                        )
                    self.assertEqual(observed, baseline[: fault_index + 1])
                    self.assertFalse((root / "transactions" / token).exists())

                    receipt = target.materialize_publication_q4_authority_source_request_v1(
                        project_root=root,
                        output_dir=output_relative,
                        prepare_request=prepare_callback(prepared),
                    )
                    self.assertEqual(
                        receipt["status"],
                        "materialized_non_authorizing_q4_authority_source_request",
                    )
                self.assertEqual(expected, baseline[-1])
            finally:
                fixture.close()

    def test_default_production_crash_after_every_commit_resumes_exact_namespace(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            fixture = Fixture(root)
            try:
                (root / "transactions").mkdir(exist_ok=True)
                production_inputs, seams = production_inputs_for(fixture)
                probe_token = "resume-probe"
                probe_output = f"transactions/{probe_token}/request"
                baseline: list[tuple[str, str]] = []
                with patched_production_seams(seams):
                    target.materialize_publication_q4_authority_source_request_v1(
                        project_root=root,
                        output_dir=probe_output,
                        production_inputs=production_inputs,
                        after_owned_commit=lambda kind, path: baseline.append(
                            (kind, path.replace(probe_token, "<attempt>"))
                        ),
                    )
                shutil.rmtree(root / "transactions" / probe_token)
                self.assertGreaterEqual(len(baseline), 20)
                self.assertTrue(
                    any(
                        kind == "directory" and "/support/scratch/" in path
                        for kind, path in baseline
                    )
                )

                for fault_index in range(len(baseline)):
                    token = f"resume-{fault_index}"
                    output_relative = f"transactions/{token}/request"
                    observed: list[tuple[str, str]] = []
                    fault_path: list[str] = []

                    def crash(kind: str, path: str) -> None:
                        observed.append((kind, path.replace(token, "<attempt>")))
                        if len(observed) - 1 == fault_index:
                            fault_path.append(path)
                            raise SyntheticMaterializationCrash()

                    with (
                        patched_production_seams(seams),
                        mock.patch.object(target, "_rollback_owned", return_value=None),
                        self.assertRaises(SyntheticMaterializationCrash),
                    ):
                        target.materialize_publication_q4_authority_source_request_v1(
                            project_root=root,
                            output_dir=output_relative,
                            production_inputs=production_inputs,
                            after_owned_commit=crash,
                        )
                    self.assertEqual(observed, baseline[: fault_index + 1])
                    crashed_entry = root / fault_path[0]
                    before = crashed_entry.lstat()

                    with patched_production_seams(seams):
                        receipt = target.materialize_publication_q4_authority_source_request_v1(
                            project_root=root,
                            output_dir=output_relative,
                            production_inputs=production_inputs,
                        )
                    after = crashed_entry.lstat()
                    self.assertEqual(
                        (before.st_dev, before.st_ino),
                        (after.st_dev, after.st_ino),
                    )
                    self.assertEqual(receipt["runtime_authority_request_count"], 112)
                    self.assertTrue(
                        (root / output_relative / target.RECEIPT_FILENAME).is_file()
                    )
            finally:
                fixture.close()

    def test_default_production_recovers_every_atomic_physical_window(self) -> None:
        physical_steps = (
            "mid_write",
            "post_fsync_pre_publish",
            "post_publish_pre_parent_fsync",
        )
        for step in physical_steps:
            with self.subTest(step=step), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                fixture = Fixture(root)
                try:
                    (root / "transactions").mkdir(exist_ok=True)
                    production_inputs, seams = production_inputs_for(fixture)
                    output_relative = f"transactions/physical-{step}/request"
                    faulted_path: list[str] = []

                    def crash(observed_step: str, path: str) -> None:
                        if observed_step == step and not faulted_path:
                            faulted_path.append(path)
                            raise SyntheticMaterializationCrash()

                    with (
                        patched_production_seams(seams),
                        mock.patch.object(target, "_rollback_owned", return_value=None),
                        self.assertRaises(SyntheticMaterializationCrash),
                    ):
                        target.materialize_publication_q4_authority_source_request_v1(
                            project_root=root,
                            output_dir=output_relative,
                            production_inputs=production_inputs,
                            after_physical_commit_step=crash,
                        )
                    self.assertEqual(len(faulted_path), 1)
                    faulted_leaf = root / faulted_path[0]
                    published_identity = (
                        (faulted_leaf.stat().st_dev, faulted_leaf.stat().st_ino)
                        if faulted_leaf.exists()
                        else None
                    )

                    with patched_production_seams(seams):
                        receipt = (
                            target.materialize_publication_q4_authority_source_request_v1(
                                project_root=root,
                                output_dir=output_relative,
                                production_inputs=production_inputs,
                            )
                        )
                    self.assertEqual(receipt["runtime_authority_request_count"], 112)
                    self.assertEqual(
                        receipt["launcher_runtime_authority_build_count"], 4
                    )
                    self.assertTrue(
                        (root / output_relative / target.RECEIPT_FILENAME).is_file()
                    )
                    if published_identity is not None:
                        self.assertEqual(
                            (
                                faulted_leaf.stat().st_dev,
                                faulted_leaf.stat().st_ino,
                            ),
                            published_identity,
                        )
                finally:
                    fixture.close()

    def test_directory_rebind_during_owned_commit_is_rejected_without_cleanup(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            fixture = Fixture(root)
            try:
                (root / "transactions").mkdir(exist_ok=True)
                output_relative = "transactions/rebind/request"
                output = root / output_relative
                moved = root / "transactions/rebind/request-owned"
                sentinel = output / "attacker.txt"

                def rebind(kind: str, path: str) -> None:
                    if kind != "directory" or path != output_relative:
                        return
                    output.rename(moved)
                    output.mkdir()
                    sentinel.write_bytes(b"attacker\n")

                with self.assertRaisesRegex(
                    Exception, "rebound|identity changed|changed while"
                ):
                    target.materialize_publication_q4_authority_source_request_v1(
                        project_root=root,
                        output_dir=output_relative,
                        prepare_request=prepare_callback(
                            prepared_for(fixture, request_for(fixture))
                        ),
                        after_owned_commit=rebind,
                    )
                self.assertEqual(sentinel.read_bytes(), b"attacker\n")
                self.assertFalse((output / target.RECEIPT_FILENAME).exists())
                self.assertTrue(moved.is_dir())
            finally:
                fixture.close()

    def test_default_resume_rejects_tampered_partial_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            fixture = Fixture(root)
            try:
                production_inputs, seams = production_inputs_for(fixture)
                output_relative = "transactions/tampered-resume/request"
                partial_path: list[str] = []

                def crash(kind: str, path: str) -> None:
                    if (
                        kind == "file"
                        and path.endswith(
                            "/support/policy-calibration/deepstream.v1.json"
                        )
                    ):
                        partial_path.append(path)
                        raise SyntheticMaterializationCrash()

                with (
                    patched_production_seams(seams),
                    mock.patch.object(target, "_rollback_owned", return_value=None),
                    self.assertRaises(SyntheticMaterializationCrash),
                ):
                    target.materialize_publication_q4_authority_source_request_v1(
                        project_root=root,
                        output_dir=output_relative,
                        production_inputs=production_inputs,
                        after_owned_commit=crash,
                    )
                partial = root / partial_path[0]
                partial.unlink()
                partial.write_bytes(b"attacker-replacement\n")

                with (
                    patched_production_seams(seams),
                    self.assertRaisesRegex(Exception, "not byte-exact"),
                ):
                    target.materialize_publication_q4_authority_source_request_v1(
                        project_root=root,
                        output_dir=output_relative,
                        production_inputs=production_inputs,
                    )
                self.assertEqual(partial.read_bytes(), b"attacker-replacement\n")
                self.assertFalse(
                    (root / output_relative / target.RECEIPT_FILENAME).exists()
                )
            finally:
                fixture.close()

    def test_default_production_inputs_reach_cold_accepted_source_registry(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            fixture = Fixture(root)
            try:
                production_inputs, seams = production_inputs_for(fixture)
                with (
                    mock.patch.object(
                        benchmark_contract,
                        "load_dataset",
                        side_effect=seams["load_dataset"],
                    ),
                    mock.patch.object(
                        model_acceptance,
                        "load_verified_model_parity_acceptance_v4",
                        side_effect=seams["load_model_parity"],
                    ),
                    mock.patch.object(
                        accepted_guardian,
                        "load_accepted_policy_guardian_preprocessing_contract_v1",
                        side_effect=seams["load_guardian"],
                    ),
                    mock.patch.object(
                        analytics_sidecar,
                        "validate_publication_sidecar_service_authority_v1",
                        side_effect=seams["validate_service"],
                    ),
                ):
                    request_receipt = (
                        target.materialize_publication_q4_authority_source_request_v1(
                            project_root=root,
                            output_dir="transactions/P/request",
                            production_inputs=production_inputs,
                        )
                    )

                request_receipt_path = (
                    root / "transactions/P/request" / target.RECEIPT_FILENAME
                )
                cold_receipt = (
                    target.load_publication_q4_authority_source_request_receipt_v1(
                        project_root=root,
                        receipt_path=request_receipt_path,
                        expected_receipt_file_sha256=hashlib.sha256(
                            request_receipt_path.read_bytes()
                        ).hexdigest(),
                        expected_receipt_sha256=request_receipt[
                            "receipt_sha256"
                        ],
                    )
                )
                self.assertEqual(cold_receipt, request_receipt)
                self.assertEqual(request_receipt["dataset_source_count"], 2)
                self.assertEqual(
                    request_receipt["runtime_authority_request_count"], 112
                )
                self.assertEqual(
                    request_receipt["launcher_runtime_authority_build_count"], 4
                )

                request_path = root / str(request_receipt["request"]["path"])
                request = json.loads(request_path.read_bytes())
                support = request_receipt["support_artifacts"]
                calibrations = support["policy_calibrations"]
                static_maps = support["policy_static_maps"]
                self.assertEqual(
                    len({item["path"] for item in calibrations.values()}), 4
                )
                self.assertEqual(
                    len({item["path"] for item in static_maps.values()}), 4
                )
                for system in runtime_contract.SYSTEMS:
                    self.assertEqual(
                        json.loads(
                            (root / str(calibrations[system]["path"])).read_bytes()
                        ),
                        seams["mapping_value"]["calibrations"][system],
                    )

                execution_descriptor = seams["execution_config"]
                for row in request["runtime_authority_requests"]:
                    coordinate = row["coordinate"]
                    system = str(coordinate["system"])
                    policy = str(coordinate["policy"])
                    wrapper = runtime_registry.validate_publication_q4_runtime_launcher_input_wrapper_v3(
                        row["inputs"]["system_specific_launcher_input"][
                            "content"
                        ],
                        expected_system=system,
                        expected_policy=policy,
                    )
                    expected_roles = set(
                        runtime_contract.RUNTIME_MODULE_BY_SYSTEM[
                            system
                        ].FILE_ROLES
                    )
                    for projection in (
                        "qualification_projection",
                        "production_projection",
                    ):
                        files = wrapper[projection]["runtime_input_template"][
                            "files"
                        ]
                        self.assertEqual(set(files), expected_roles)
                        calibration_descriptor = {
                            key: files["policy_calibration"][key]
                            for key in ("path", "size_bytes", "sha256")
                        }
                        self.assertEqual(
                            calibration_descriptor, calibrations[system]
                        )
                        if system in {"openvino_gva", "gstreamer_custom"}:
                            observed_execution = {
                                key: files["analytics_execution_manifest"][key]
                                for key in ("path", "size_bytes", "sha256")
                            }
                            self.assertEqual(
                                json.loads((root / observed_execution["path"]).read_bytes())["execution_config"], execution_descriptor
                            )
                        else:
                            self.assertNotIn(
                                "analytics_execution_manifest", files
                            )

                material_receipt = (
                    source_material.materialize_publication_q4_authority_source_material_v1(
                        project_root=root,
                        request_path=request_path,
                        expected_request_file_sha256=request_receipt["request"][
                            "sha256"
                        ],
                        expected_request_sha256=request_receipt[
                            "request_sha256"
                        ],
                        output_dir="transactions/P/source-material",
                    )
                )
                material_path = root / str(
                    material_receipt["source_material"]["path"]
                )
                source_spec_path = root / "specs/P.production.json"
                source_spec = (
                    authority_pipeline.materialize_publication_q4_authority_source_spec_v1(
                        project_root=root,
                        source_material_path=material_path,
                        expected_source_material_file_sha256=material_receipt[
                            "source_material"
                        ]["sha256"],
                        expected_source_material_sha256=material_receipt[
                            "source_material_sha256"
                        ],
                        output_path=source_spec_path,
                    )
                )
                phase1 = (
                    authority_pipeline.materialize_publication_q4_authority_plan_phase1_v1(
                        project_root=root,
                        source_spec_path=source_spec_path,
                        expected_source_spec_file_sha256=hashlib.sha256(
                            source_spec_path.read_bytes()
                        ).hexdigest(),
                        expected_source_spec_sha256=source_spec[
                            "source_spec_sha256"
                        ],
                        output_dir="transactions/P/phase1",
                    )
                )
                phase1_path = (
                    root
                    / "transactions/P/phase1"
                    / authority_pipeline.PHASE1_RECEIPT_FILENAME
                )
                runtime_plan_path = root / str(
                    phase1["runtime_materialization_plan"]["descriptor"][
                        "path"
                    ]
                )
                runtime_result = (
                    runtime_registry.materialize_publication_q4_runtime_candidate_registry_v4(
                        project_root=root,
                        plan=json.loads(runtime_plan_path.read_bytes()),
                        output_path=source_spec["planned_outputs"][
                            "runtime_candidate_registry_path"
                        ],
                        result_output_path=source_spec["planned_outputs"][
                            "runtime_materialization_result_path"
                        ],
                    )
                )
                runtime_result_path = root / str(
                    source_spec["planned_outputs"][
                        "runtime_materialization_result_path"
                    ]
                )
                phase2 = authority_pipeline.finalize_publication_q4_source_plan_phase2_v1(
                    project_root=root,
                    phase1_receipt_path=phase1_path,
                    expected_phase1_receipt_file_sha256=hashlib.sha256(
                        phase1_path.read_bytes()
                    ).hexdigest(),
                    expected_phase1_receipt_sha256=phase1["receipt_sha256"],
                    runtime_materialization_result_path=runtime_result_path,
                    expected_runtime_materialization_result_file_sha256=(
                        hashlib.sha256(runtime_result_path.read_bytes()).hexdigest()
                    ),
                    expected_runtime_materialization_result_sha256=(
                        runtime_result["result_sha256"]
                    ),
                    output_dir="transactions/P/phase2",
                )
                source_plan_path = root / str(
                    phase2["source_registry_path_plan"]["descriptor"]["path"]
                )
                dependencies = fixture.dependencies(
                    runtime_result["runtime_candidate_registry"]
                )
                source_result = (
                    source_registry.materialize_backend_q4_two_phase_source_registry_v1(
                        project_root=root,
                        path_plan_path=source_plan_path,
                        expected_plan_file_sha256=hashlib.sha256(
                            source_plan_path.read_bytes()
                        ).hexdigest(),
                        expected_plan_sha256=phase2[
                            "source_registry_path_plan"
                        ]["content_identity_sha256"],
                        output_path=source_spec["planned_outputs"][
                            "source_registry_path"
                        ],
                        result_output_path=source_spec["planned_outputs"][
                            "source_materialization_result_path"
                        ],
                        dependencies=dependencies,
                    )
                )
                loaded = source_registry.load_backend_q4_two_phase_source_registry_v1(
                    project_root=root,
                    registry_path=source_result["source_registry"]["path"],
                    dependencies=dependencies,
                )
                self.assertEqual(
                    source_result["status"],
                    "materialized_accepted_physical_q4_sources",
                )
                runtime_calibrations = loaded["identity_inputs"][
                    "policy_qualification"
                ]["runtime_calibrations"]
                self.assertEqual(len(runtime_calibrations), 4)
                self.assertEqual(
                    len(
                        {
                            descriptor["path"]
                            for descriptor in runtime_calibrations.values()
                        }
                    ),
                    4,
                )
            finally:
                fixture.close()

    def test_public_request_reaches_accepted_source_registry_through_public_apis(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            fixture = Fixture(root)
            try:
                request = request_for(fixture, "I")
                request_receipt = (
                    target.materialize_publication_q4_authority_source_request_v1(
                        project_root=root,
                        output_dir="transactions/I/request",
                        prepare_request=prepare_callback(
                            prepared_for(fixture, request)
                        ),
                    )
                )
                request_path = root / str(request_receipt["request"]["path"])
                material_receipt = (
                    source_material.materialize_publication_q4_authority_source_material_v1(
                        project_root=root,
                        request_path=request_path,
                        expected_request_file_sha256=request_receipt["request"][
                            "sha256"
                        ],
                        expected_request_sha256=request_receipt["request_sha256"],
                        output_dir="transactions/I/source-material",
                    )
                )
                material_path = root / str(
                    material_receipt["source_material"]["path"]
                )
                source_spec_path = root / "specs/I.committed.json"
                source_spec = (
                    authority_pipeline.materialize_publication_q4_authority_source_spec_v1(
                        project_root=root,
                        source_material_path=material_path,
                        expected_source_material_file_sha256=material_receipt[
                            "source_material"
                        ]["sha256"],
                        expected_source_material_sha256=material_receipt[
                            "source_material_sha256"
                        ],
                        output_path=source_spec_path,
                    )
                )
                phase1 = (
                    authority_pipeline.materialize_publication_q4_authority_plan_phase1_v1(
                        project_root=root,
                        source_spec_path=source_spec_path,
                        expected_source_spec_file_sha256=hashlib.sha256(
                            source_spec_path.read_bytes()
                        ).hexdigest(),
                        expected_source_spec_sha256=source_spec[
                            "source_spec_sha256"
                        ],
                        output_dir="transactions/I/phase1",
                    )
                )
                phase1_path = (
                    root
                    / "transactions/I/phase1"
                    / authority_pipeline.PHASE1_RECEIPT_FILENAME
                )
                runtime_plan_path = root / str(
                    phase1["runtime_materialization_plan"]["descriptor"]["path"]
                )
                runtime_plan = json.loads(runtime_plan_path.read_bytes())
                runtime_result = (
                    runtime_registry.materialize_publication_q4_runtime_candidate_registry_v4(
                        project_root=root,
                        plan=runtime_plan,
                        output_path=source_spec["planned_outputs"][
                            "runtime_candidate_registry_path"
                        ],
                        result_output_path=source_spec["planned_outputs"][
                            "runtime_materialization_result_path"
                        ],
                    )
                )
                runtime_result_path = root / str(
                    source_spec["planned_outputs"][
                        "runtime_materialization_result_path"
                    ]
                )
                phase2 = authority_pipeline.finalize_publication_q4_source_plan_phase2_v1(
                    project_root=root,
                    phase1_receipt_path=phase1_path,
                    expected_phase1_receipt_file_sha256=hashlib.sha256(
                        phase1_path.read_bytes()
                    ).hexdigest(),
                    expected_phase1_receipt_sha256=phase1["receipt_sha256"],
                    runtime_materialization_result_path=runtime_result_path,
                    expected_runtime_materialization_result_file_sha256=hashlib.sha256(
                        runtime_result_path.read_bytes()
                    ).hexdigest(),
                    expected_runtime_materialization_result_sha256=runtime_result[
                        "result_sha256"
                    ],
                    output_dir="transactions/I/phase2",
                )
                source_plan_path = root / str(
                    phase2["source_registry_path_plan"]["descriptor"]["path"]
                )
                dependencies = fixture.dependencies(
                    runtime_result["runtime_candidate_registry"]
                )
                source_result = (
                    source_registry.materialize_backend_q4_two_phase_source_registry_v1(
                        project_root=root,
                        path_plan_path=source_plan_path,
                        expected_plan_file_sha256=hashlib.sha256(
                            source_plan_path.read_bytes()
                        ).hexdigest(),
                        expected_plan_sha256=phase2[
                            "source_registry_path_plan"
                        ]["content_identity_sha256"],
                        output_path=source_spec["planned_outputs"][
                            "source_registry_path"
                        ],
                        result_output_path=source_spec["planned_outputs"][
                            "source_materialization_result_path"
                        ],
                        dependencies=dependencies,
                    )
                )
                loaded = source_registry.load_backend_q4_two_phase_source_registry_v1(
                    project_root=root,
                    registry_path=source_result["source_registry"]["path"],
                    dependencies=dependencies,
                )
                runtime_calibrations = loaded["identity_inputs"][
                    "policy_qualification"
                ]["runtime_calibrations"]
                self.assertEqual(source_result["status"],
                                 "materialized_accepted_physical_q4_sources")
                self.assertEqual(len(runtime_calibrations), 4)
                self.assertEqual(
                    len({item["path"] for item in runtime_calibrations.values()}),
                    4,
                )
                for system, descriptor in runtime_calibrations.items():
                    self.assertEqual(
                        json.loads((root / descriptor["path"]).read_bytes()),
                        fixture.policy_calibration_values[system],
                    )
            finally:
                fixture.close()


if __name__ == "__main__":
    unittest.main()
