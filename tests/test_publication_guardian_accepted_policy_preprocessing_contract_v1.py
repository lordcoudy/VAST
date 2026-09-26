from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import publication_guardian_accepted_policy_preprocessing_contract_v1 as target  # noqa: E402
from publication_guardian_runtime_expectations_v1 import (  # noqa: E402
    runtime_expectations_from_preprocessing_receipt_v1,
)


BRANCHES = ("plate_number", "vehicle_type", "damage", "foreign_object")
RESOURCES = ("cpu", "gpu")


def canonical(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")


def semantic(value: object) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical(value) + b"\n")


def descriptor(root: Path, path: Path) -> dict[str, object]:
    payload = path.read_bytes()
    return {
        "path": path.relative_to(root).as_posix(),
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


class Fixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.contract = {"resize": [640, 384], "layout": "nchw"}
        self.contract_sha = semantic(self.contract)
        self.policy_sha = semantic({"policy": "frozen"})
        self.candidate_dir = root / "qualification" / "candidate"
        self.accepted_dir = root / "qualification" / "accepted"
        self.predecessor_dir = root / "qualification" / "preprocessing"
        self.binding_dir = root / "parity" / "bindings"

        self.dataset_path = root / "configs" / "datasets.json"
        write_json(self.dataset_path, {"dataset": "frozen"})
        self.dataset_descriptor = descriptor(root, self.dataset_path)
        self.dataset_sha = semantic({"dataset": "frozen"})
        self.index_base = {
            "schema_version": 2,
            "artifact_kind": "vast_publication_policy_qualification_index",
            "policy_contract_sha256": self.policy_sha,
            "dataset_manifest": self.dataset_descriptor,
            "bindings": [{"system": system} for system in target.SYSTEMS],
        }
        self.bootstrap_index_path = (
            self.candidate_dir / "checkpoint_policy_qualification_index.v2.json"
        )
        write_json(
            self.bootstrap_index_path,
            {**self.index_base, "pilots": []},
        )
        self.bootstrap_index_descriptor = descriptor(
            root, self.bootstrap_index_path
        )

        self.candidate_manifest_path = (
            self.candidate_dir / "checkpoint_policy_capability_candidate_manifest.json"
        )
        self.capability = {
            "schema_version": 1,
            "artifact_kind": "vast_publication_policy_capability_manifest",
            "policy_scope": "analytics_only",
            "policy_contract_sha256": self.policy_sha,
            "systems": {},
        }
        write_json(self.candidate_manifest_path, self.capability)
        self.candidate_descriptor = descriptor(root, self.candidate_manifest_path)
        self.candidate_receipt_path = self.candidate_dir / "candidate-receipt.json"
        candidate_unsigned = {
            "artifact_kind": "vast_publication_policy_qualification_candidate_receipt",
            "candidate_manifest": self.candidate_descriptor,
        }
        self.candidate_receipt = {
            **candidate_unsigned,
            "sha256": semantic(candidate_unsigned),
        }
        write_json(self.candidate_receipt_path, self.candidate_receipt)
        self.candidate_receipt_descriptor = descriptor(root, self.candidate_receipt_path)

        self.config_path = root / "parity" / "execution-config.json"
        self.config_identity = semantic({"execution": "config"})
        self.worker_images = {
            "cpu": "sha256:" + "1" * 64,
            "gpu": "sha256:" + "2" * 64,
        }
        self.config = {
            "identity": {"algorithm": "sha256", "sha256": self.config_identity},
            "workers": {
                resource: {
                    "engine": (
                        "openvino_cpu" if resource == "cpu" else "tensorrt_cuda"
                    ),
                    "image_id": self.worker_images[resource],
                    "worker_implementation_sha256": semantic({"impl": resource}),
                }
                for resource in RESOURCES
            },
        }
        write_json(self.config_path, self.config)
        self.config_descriptor = descriptor(root, self.config_path)

        self.probes: dict[str, dict[str, object]] = {}
        self.probe_descriptors: dict[str, dict[str, object]] = {}
        for resource in RESOURCES:
            probe_path = root / "parity" / f"probe-{resource}.json"
            probe = {
                "engine": self.config["workers"][resource]["engine"],
                "worker_implementation_sha256": self.config["workers"][resource][
                    "worker_implementation_sha256"
                ],
            }
            write_json(probe_path, probe)
            self.probes[resource] = probe
            self.probe_descriptors[resource] = descriptor(root, probe_path)

        binding_descriptors: dict[str, dict[str, object]] = {}
        self.bindings: dict[tuple[str, str], dict[str, object]] = {}
        self.capabilities: dict[tuple[str, str], dict[str, object]] = {}
        for branch in BRANCHES:
            for resource in RESOURCES:
                path = self.binding_dir / f"{branch}-{resource}.json"
                value = {
                    "branch": branch,
                    "resource": resource,
                    "preprocessing_contract_sha256": self.contract_sha,
                }
                write_json(path, value)
                binding_descriptors[f"{branch}:{resource}"] = descriptor(root, path)
                self.bindings[(branch, resource)] = value
                self.capabilities[(branch, resource)] = dict(value)
        self.binding_index_path = self.binding_dir / "index.json"
        self.binding_identity = semantic({"binding": "set"})
        self.bindings_identity = semantic({"bindings": "exact-8"})
        write_json(
            self.binding_index_path,
            {
                "identity": {"algorithm": "sha256", "sha256": self.binding_identity},
                "bindings_identity_sha256": self.bindings_identity,
            },
        )
        self.binding_index_descriptor = descriptor(root, self.binding_index_path)

        refresh = {
            "image_identity_patch": {},
            "workers": {
                resource: {
                    "image": f"vast/{resource}:v1",
                    "image_id": self.worker_images[resource],
                    "worker_implementation_sha256": self.config["workers"][resource][
                        "worker_implementation_sha256"
                    ],
                    "source_set_sha256": semantic({"source": resource}),
                    "receipt_sha256": semantic({"worker-receipt": resource}),
                }
                for resource in RESOURCES
            },
            "execution_config": {
                **self.config_descriptor,
                "content_identity_sha256": self.config_identity,
                "worker_projection_sha256": semantic(self.config["workers"]),
            },
            "binding_set": {
                "index": self.binding_index_descriptor,
                "identity_sha256": self.binding_identity,
                "bindings_identity_sha256": self.bindings_identity,
                "bindings": binding_descriptors,
            },
            "runtime_probes": {
                resource: {
                    **self.probe_descriptors[resource],
                    "worker_implementation_sha256": self.config["workers"][resource][
                        "worker_implementation_sha256"
                    ],
                }
                for resource in RESOURCES
            },
        }

        self.predecessor_contract_path = self.predecessor_dir / "contract.json"
        write_json(self.predecessor_contract_path, self.contract)
        self.predecessor_contract_descriptor = descriptor(
            root, self.predecessor_contract_path
        )
        self.transaction_path = root / "qualification" / "inputs" / "transaction.json"
        transaction_unsigned = {
            "schema_version": 2,
            "artifact_kind": "vast_publication_policy_qualification_input_transaction_v2",
            "status": "qualification_inputs_materialized_nonaccepted",
        }
        self.transaction = {
            **transaction_unsigned,
            "receipt_sha256": semantic(transaction_unsigned),
        }
        write_json(self.transaction_path, self.transaction)
        self.transaction_descriptor = descriptor(root, self.transaction_path)
        self.predecessor_receipt_path = self.predecessor_dir / "receipt.json"
        predecessor_unsigned = {
            "artifact_kind": "vast_guardian_preprocessing_contract_materialization_v1",
            "preprocessing_contract_content_sha256": self.contract_sha,
            "policy_contract_sha256": self.policy_sha,
            "model_parity_refresh_authority": refresh,
            "qualification_index": self.bootstrap_index_descriptor,
            "qualification_transaction_receipt": self.transaction_descriptor,
            "qualification_transaction_receipt_sha256": self.transaction[
                "receipt_sha256"
            ],
            "candidate_manifest": self.candidate_descriptor,
            "candidate_receipt": self.candidate_receipt_descriptor,
            "candidate_receipt_identity_sha256": self.candidate_receipt["sha256"],
        }
        self.predecessor_receipt = {
            **predecessor_unsigned,
            "receipt_sha256": semantic(predecessor_unsigned),
        }
        write_json(self.predecessor_receipt_path, self.predecessor_receipt)
        self.predecessor_authority = {
            "artifact_kind": "vast_guardian_preprocessing_contract_authority_v1",
            "materialization_receipt_identity_sha256": self.predecessor_receipt[
                "receipt_sha256"
            ],
            "materialization_receipt_file_sha256": descriptor(
                root, self.predecessor_receipt_path
            )["sha256"],
        }

        self.closure_path = root / "qualification" / "closure" / "receipt.json"
        closure_unsigned = {
            "schema_version": 1,
            "artifact_kind": "vast_publication_policy_qualification_execution_closure_v1",
            "status": "qualification_execution_closed_nonpublication",
            "qualification_input_transaction": {
                "receipt": self.transaction_descriptor,
                "receipt_sha256": self.transaction["receipt_sha256"],
            },
            "guardian_preprocessing": {
                "contract": self.predecessor_contract_descriptor,
                "materialization_receipt": descriptor(
                    root, self.predecessor_receipt_path
                ),
                "materialization_receipt_identity_sha256": self.predecessor_receipt[
                    "receipt_sha256"
                ],
                "policy_contract_sha256": self.policy_sha,
            },
        }
        self.closure = {
            **closure_unsigned,
            "receipt_sha256": semantic(closure_unsigned),
        }
        write_json(self.closure_path, self.closure)
        self.closure_descriptor = descriptor(root, self.closure_path)

        self.index_path = (
            root
            / "qualification"
            / "completed"
            / "checkpoint_policy_qualification_index.v2.json"
        )
        self.index = {
            **self.index_base,
            "pilots": [{"cell_index": index} for index in range(32)],
            "qualification_execution_closure": self.closure_descriptor,
        }
        write_json(self.index_path, self.index)
        self.index_descriptor = descriptor(root, self.index_path)

        self.accepted_capability_path = (
            self.accepted_dir / "checkpoint_policy_capability_manifest.json"
        )
        write_json(self.accepted_capability_path, self.capability)
        self.calibration = {
            "schema_version": 1,
            "artifact_kind": "vast_publication_policy_calibration_mapping",
            "policy_contract_sha256": self.policy_sha,
            "aggregation_rule": "median_of_balanced_native_codec_topology_cells_v1",
            "minimum_samples_per_branch_cell": 30,
            "calibrations": {system: {} for system in target.SYSTEMS},
        }
        self.accepted_calibration_path = (
            self.accepted_dir / "checkpoint_policy_calibration_mapping.json"
        )
        write_json(self.accepted_calibration_path, self.calibration)
        self.coverage = {
            "binding_count": 32,
            "pilot_cell_count": 32,
            "accepted_sample_count": 3840,
            "minimum_samples_per_branch_cell": 30,
        }
        self.accepted_receipt_path = (
            self.accepted_dir / "checkpoint_policy_qualification_receipt.json"
        )
        accepted_unsigned = {
            "schema_version": 1,
            "artifact_kind": "vast_publication_policy_qualification_receipt",
            "status": "accepted_evidence_driven_policy_qualification",
            "policy_contract_sha256": self.policy_sha,
            "qualification_index_sha256": self.index_descriptor["sha256"],
            "dataset_manifest_sha256": self.dataset_sha,
            "coverage": self.coverage,
            "outputs": {
                "capability_manifest": {
                    **descriptor(root, self.accepted_capability_path),
                    "path": self.accepted_capability_path.name,
                },
                "calibration_mapping": {
                    **descriptor(root, self.accepted_calibration_path),
                    "path": self.accepted_calibration_path.name,
                },
            },
        }
        self.accepted_receipt = {
            **accepted_unsigned,
            "sha256": semantic(accepted_unsigned),
        }
        write_json(self.accepted_receipt_path, self.accepted_receipt)

    def dependencies(self) -> target.AcceptedPolicyGuardianDependenciesV1:
        def load_predecessor(**kwargs: object) -> dict[str, object]:
            if Path(kwargs["materialization_receipt_path"]) != self.predecessor_receipt_path:
                raise AssertionError(kwargs)
            if Path(kwargs["candidate_manifest_path"]) != self.candidate_manifest_path:
                raise AssertionError(kwargs)
            return {
                "preprocessing_contract": copy.deepcopy(self.contract),
                "receipt": copy.deepcopy(self.predecessor_receipt),
                "authority": copy.deepcopy(self.predecessor_authority),
            }

        def assess_policy(**kwargs: object) -> dict[str, object]:
            if Path(kwargs["index_path"]) != self.index_path:
                raise AssertionError(kwargs)
            return {
                "passed": True,
                "status": "ready_for_atomic_promotion",
                "blockers": [],
                "index_sha256": self.index_descriptor["sha256"],
                "dataset_manifest_sha256": self.dataset_sha,
                "qualification_execution_closure": self.closure_descriptor,
                "coverage": copy.deepcopy(self.coverage),
                "capability_manifest": copy.deepcopy(self.capability),
                "calibration_mapping": copy.deepcopy(self.calibration),
            }

        def load_closure(**kwargs: object) -> dict[str, object]:
            if Path(kwargs["receipt_path"]) != self.closure_path:
                raise AssertionError(kwargs)
            return {
                "receipt": copy.deepcopy(self.closure),
                "receipt_descriptor": copy.deepcopy(self.closure_descriptor),
                "receipt_sha256": self.closure["receipt_sha256"],
            }

        def load_config(path: Path) -> dict[str, object]:
            if path != self.config_path:
                raise AssertionError(path)
            return copy.deepcopy(self.config)

        def load_probe(path: Path, *, engine: str) -> dict[str, object]:
            value = json.loads(path.read_bytes())
            if value["engine"] != engine:
                raise AssertionError((value, engine))
            return value

        def load_bindings(
            path: Path,
            *,
            execution_config: dict[str, object],
            runtime_probes: dict[str, object],
        ) -> SimpleNamespace:
            if path != self.binding_dir or execution_config != self.config:
                raise AssertionError((path, execution_config))
            if runtime_probes != self.probes:
                raise AssertionError(runtime_probes)
            return SimpleNamespace(
                index={
                    "identity": {
                        "algorithm": "sha256",
                        "sha256": self.binding_identity,
                    },
                    "bindings_identity_sha256": self.bindings_identity,
                },
                bindings=copy.deepcopy(self.bindings),
                capabilities=copy.deepcopy(self.capabilities),
            )

        return target.AcceptedPolicyGuardianDependenciesV1(
            load_qualification_preprocessing=load_predecessor,
            assess_policy_qualification=assess_policy,
            load_execution_closure=load_closure,
            load_execution_config=load_config,
            load_runtime_probe=load_probe,
            load_binding_set=load_bindings,
        )

    def materialize(self, output: Path, **overrides: object) -> dict[str, object]:
        return target.materialize_accepted_policy_guardian_preprocessing_contract_v1(
            project_root=self.root,
            qualification_preprocessing_contract_path=self.predecessor_contract_path,
            qualification_preprocessing_receipt_path=self.predecessor_receipt_path,
            completed_qualification_index_path=self.index_path,
            accepted_policy_qualification_receipt_path=self.accepted_receipt_path,
            accepted_policy_capability_manifest_path=self.accepted_capability_path,
            accepted_policy_calibration_mapping_path=self.accepted_calibration_path,
            execution_config_path=self.config_path,
            binding_set_dir=self.binding_dir,
            output_dir=output,
            dependencies=self.dependencies(),
            **overrides,
        )


class SyntheticAtomicCrash(BaseException):
    pass


class AcceptedPolicyGuardianPreprocessingContractV1Tests(unittest.TestCase):
    def test_receipt_last_cold_load_proves_promotion_closure_and_consensus(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            fixture = Fixture(root)
            output = root / "q4" / "accepted-preprocessing"
            output.parent.mkdir()
            result = fixture.materialize(output)
            self.assertEqual(
                {path.name for path in output.iterdir()},
                {target.CONTRACT_FILENAME, target.RECEIPT_FILENAME},
            )
            loaded = target.load_accepted_policy_guardian_preprocessing_contract_v1(
                project_root=root,
                preprocessing_contract_path=result["contract_path"],
                materialization_receipt_path=result["receipt_path"],
                accepted_policy_capability_manifest_path=(
                    fixture.accepted_capability_path
                ),
                dependencies=fixture.dependencies(),
            )
            authority = loaded["authority"]
            self.assertEqual(
                authority["accepted_policy_qualification_receipt_identity_sha256"],
                fixture.accepted_receipt["sha256"],
            )
            self.assertEqual(
                authority["predecessor_qualification_preprocessing_receipt_identity_sha256"],
                fixture.predecessor_receipt["receipt_sha256"],
            )
            self.assertEqual(
                authority["qualification_execution_closure_receipt_identity_sha256"],
                fixture.closure["receipt_sha256"],
            )
            self.assertEqual(
                authority["binding_set_identity_sha256"], fixture.binding_identity
            )
            self.assertEqual(
                runtime_expectations_from_preprocessing_receipt_v1(
                    loaded["receipt"]
                ),
                loaded["runtime_expectations"],
            )

    def test_rejects_candidate_to_accepted_drift_and_cross_run_replay(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            fixture = Fixture(root)
            write_json(
                fixture.accepted_capability_path,
                {**fixture.capability, "systems": {"drift": {}}},
            )
            with self.assertRaisesRegex(
                target.AcceptedPolicyGuardianPreprocessingContractV1Error,
                "accepted.*descriptor|candidate.*accepted|promotion",
            ):
                fixture.materialize(root / "drift-output")

        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            first_root = Path(first).resolve()
            second_root = Path(second).resolve()
            first_fixture = Fixture(first_root)
            second_fixture = Fixture(second_root)
            output = first_root / "accepted-output"
            result = first_fixture.materialize(output)
            with self.assertRaises(
                target.AcceptedPolicyGuardianPreprocessingContractV1Error
            ):
                target.load_accepted_policy_guardian_preprocessing_contract_v1(
                    project_root=first_root,
                    preprocessing_contract_path=result["contract_path"],
                    materialization_receipt_path=result["receipt_path"],
                    accepted_policy_capability_manifest_path=(
                        second_fixture.accepted_capability_path
                    ),
                    dependencies=first_fixture.dependencies(),
                )

    def test_rejects_recomputed_complete_index_from_other_transaction(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            fixture = Fixture(root)

            foreign_transaction_path = (
                root / "foreign-run" / "inputs" / "transaction.json"
            )
            foreign_transaction_unsigned = {
                **{
                    key: value
                    for key, value in fixture.transaction.items()
                    if key != "receipt_sha256"
                },
                "run_nonce": "foreign-b",
            }
            foreign_transaction = {
                **foreign_transaction_unsigned,
                "receipt_sha256": semantic(foreign_transaction_unsigned),
            }
            write_json(foreign_transaction_path, foreign_transaction)
            foreign_transaction_descriptor = descriptor(
                root, foreign_transaction_path
            )

            foreign_predecessor_path = (
                root / "foreign-run" / "preprocessing" / "receipt.json"
            )
            foreign_predecessor_unsigned = {
                **{
                    key: value
                    for key, value in fixture.predecessor_receipt.items()
                    if key != "receipt_sha256"
                },
                "qualification_transaction_receipt": (
                    foreign_transaction_descriptor
                ),
                "qualification_transaction_receipt_sha256": (
                    foreign_transaction["receipt_sha256"]
                ),
            }
            foreign_predecessor = {
                **foreign_predecessor_unsigned,
                "receipt_sha256": semantic(foreign_predecessor_unsigned),
            }
            write_json(foreign_predecessor_path, foreign_predecessor)
            foreign_predecessor_descriptor = descriptor(
                root, foreign_predecessor_path
            )

            foreign_closure_path = root / "foreign-run" / "closure" / "receipt.json"
            foreign_closure_unsigned = {
                **{
                    key: value
                    for key, value in fixture.closure.items()
                    if key != "receipt_sha256"
                },
                "qualification_input_transaction": {
                    "receipt": foreign_transaction_descriptor,
                    "receipt_sha256": foreign_transaction["receipt_sha256"],
                },
                "guardian_preprocessing": {
                    "contract": fixture.predecessor_contract_descriptor,
                    "materialization_receipt": foreign_predecessor_descriptor,
                    "materialization_receipt_identity_sha256": (
                        foreign_predecessor["receipt_sha256"]
                    ),
                    "policy_contract_sha256": fixture.policy_sha,
                },
            }
            foreign_closure = {
                **foreign_closure_unsigned,
                "receipt_sha256": semantic(foreign_closure_unsigned),
            }
            write_json(foreign_closure_path, foreign_closure)
            foreign_closure_descriptor = descriptor(root, foreign_closure_path)

            foreign_index_path = (
                root
                / "foreign-run"
                / "completed"
                / "checkpoint_policy_qualification_index.v2.json"
            )
            foreign_index = {
                **fixture.index_base,
                "pilots": [{"cell_index": index} for index in range(32)],
                "qualification_execution_closure": foreign_closure_descriptor,
            }
            write_json(foreign_index_path, foreign_index)
            foreign_index_descriptor = descriptor(root, foreign_index_path)

            accepted_unsigned = {
                **{
                    key: value
                    for key, value in fixture.accepted_receipt.items()
                    if key != "sha256"
                },
                "qualification_index_sha256": foreign_index_descriptor["sha256"],
            }
            fixture.accepted_receipt = {
                **accepted_unsigned,
                "sha256": semantic(accepted_unsigned),
            }
            write_json(fixture.accepted_receipt_path, fixture.accepted_receipt)

            base = fixture.dependencies()

            def assess_foreign(**kwargs: object) -> dict[str, object]:
                self.assertEqual(Path(kwargs["index_path"]), foreign_index_path)
                return {
                    "passed": True,
                    "status": "ready_for_atomic_promotion",
                    "blockers": [],
                    "index_sha256": foreign_index_descriptor["sha256"],
                    "dataset_manifest_sha256": fixture.dataset_sha,
                    "qualification_execution_closure": foreign_closure_descriptor,
                    "coverage": copy.deepcopy(fixture.coverage),
                    "capability_manifest": copy.deepcopy(fixture.capability),
                    "calibration_mapping": copy.deepcopy(fixture.calibration),
                }

            def load_foreign_closure(**kwargs: object) -> dict[str, object]:
                self.assertEqual(Path(kwargs["receipt_path"]), foreign_closure_path)
                return {
                    "receipt": copy.deepcopy(foreign_closure),
                    "receipt_descriptor": copy.deepcopy(foreign_closure_descriptor),
                    "receipt_sha256": foreign_closure["receipt_sha256"],
                }

            dependencies = target.AcceptedPolicyGuardianDependenciesV1(
                load_qualification_preprocessing=(
                    base.load_qualification_preprocessing
                ),
                assess_policy_qualification=assess_foreign,
                load_execution_closure=load_foreign_closure,
                load_execution_config=base.load_execution_config,
                load_runtime_probe=base.load_runtime_probe,
                load_binding_set=base.load_binding_set,
            )
            with self.assertRaisesRegex(
                target.AcceptedPolicyGuardianPreprocessingContractV1Error,
                "completed qualification.*transaction|cross-run|lineage",
            ):
                target.materialize_accepted_policy_guardian_preprocessing_contract_v1(
                    project_root=root,
                    qualification_preprocessing_contract_path=(
                        fixture.predecessor_contract_path
                    ),
                    qualification_preprocessing_receipt_path=(
                        fixture.predecessor_receipt_path
                    ),
                    completed_qualification_index_path=foreign_index_path,
                    accepted_policy_qualification_receipt_path=(
                        fixture.accepted_receipt_path
                    ),
                    accepted_policy_capability_manifest_path=(
                        fixture.accepted_capability_path
                    ),
                    accepted_policy_calibration_mapping_path=(
                        fixture.accepted_calibration_path
                    ),
                    execution_config_path=fixture.config_path,
                    binding_set_dir=fixture.binding_dir,
                    output_dir=root / "mixed-run-output",
                    dependencies=dependencies,
                )

    def test_no_overwrite_and_fd_custody_surface_are_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            fixture = Fixture(root)
            output = root / "accepted-output"
            output.mkdir()
            canary = output / "KEEP"
            canary.write_text("keep\n", encoding="ascii")
            with self.assertRaisesRegex(
                target.AcceptedPolicyGuardianPreprocessingContractV1Error,
                "exists|overwrite",
            ):
                fixture.materialize(output)
            self.assertEqual(canary.read_text(encoding="ascii"), "keep\n")

            if os.name == "posix":
                alias = root.parent / f"{root.name}-alias"
                alias.symlink_to(root, target_is_directory=True)
                try:
                    with self.assertRaisesRegex(
                        target.AcceptedPolicyGuardianPreprocessingContractV1Error,
                        "project_root|physical",
                    ):
                        target.load_accepted_policy_guardian_preprocessing_contract_v1(
                            project_root=alias,
                            preprocessing_contract_path=fixture.predecessor_contract_path,
                            materialization_receipt_path=fixture.predecessor_receipt_path,
                            accepted_policy_capability_manifest_path=(
                                fixture.accepted_capability_path
                            ),
                            dependencies=fixture.dependencies(),
                        )
                finally:
                    alias.unlink()

    def test_receipt_recovers_every_atomic_physical_window_same_path(self) -> None:
        for step in (
            "mid_write",
            "post_fsync_pre_publish",
            "post_publish_pre_parent_fsync",
        ):
            with self.subTest(step=step), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                fixture = Fixture(root)
                output = root / "atomic-accepted-output"
                receipt = output / target.RECEIPT_FILENAME
                fired = False

                def crash(observed_step: str, path: Path) -> None:
                    nonlocal fired
                    if not fired and path == receipt and observed_step == step:
                        fired = True
                        raise SyntheticAtomicCrash(step)

                with self.assertRaises(SyntheticAtomicCrash):
                    fixture.materialize(
                        output, after_physical_commit_step=crash
                    )
                self.assertTrue(fired)
                published_identity = (
                    (receipt.stat().st_dev, receipt.stat().st_ino)
                    if step == "post_publish_pre_parent_fsync"
                    else None
                )
                result = fixture.materialize(output)
                self.assertEqual(Path(result["receipt_path"]), receipt)
                self.assertEqual(
                    {path.name for path in output.iterdir()},
                    {target.CONTRACT_FILENAME, target.RECEIPT_FILENAME},
                )
                if published_identity is not None:
                    self.assertEqual(
                        (receipt.stat().st_dev, receipt.stat().st_ino),
                        published_identity,
                    )


if __name__ == "__main__":
    unittest.main()
