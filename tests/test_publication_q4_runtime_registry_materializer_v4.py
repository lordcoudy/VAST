from __future__ import annotations

import contextlib
import copy
import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from backend_publication_launcher_invocation_v3 import (  # noqa: E402
    publication_launcher_invocation_v3_contract,
)
import publication_q4_runtime_contract_v4 as contract  # noqa: E402
import publication_q4_runtime_registry_materializer_v4 as target  # noqa: E402
import publication_q4_authority_plan_pipeline_v1 as authority_pipeline  # noqa: E402
import full_publication_entrypoint as full_entrypoint  # noqa: E402
from test_publication_q4_runtime_contract_v4 import (  # noqa: E402
    runtime_template,
)
from test_publication_q4_authority_plan_pipeline_v1 import (  # noqa: E402
    Fixture as AuthorityPlanFixture,
)


def canonical(value: object, *, newline: bool = True) -> bytes:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")
    return payload + (b"\n" if newline else b"")


def sha(label: str) -> str:
    return hashlib.sha256(label.encode("ascii")).hexdigest()


class InjectedCrash(BaseException):
    pass


class Fixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.upstream = {
            field: sha(f"upstream:{field}")
            for field in contract.UPSTREAM_IDENTITY_FIELDS
        }
        self.protocol = sha("protocol")
        self.input_schema = sha("input-schema")
        self.output_schema = sha("output-schema")
        self.invocation = publication_launcher_invocation_v3_contract()
        invocation_descriptor = self._write_json(
            "authorities/invocation-v3.json", self.invocation
        )
        self.invocation_ref = self._ref(
            invocation_descriptor,
            schema_version=3,
            kind="vast_backend_publication_launcher_invocation_v3",
            identity=self.invocation["invocation_sha256"],
        )
        self.validator = {
            "authority_sha256": sha("validator"),
            "validation_protocol_identity_sha256": self.protocol,
            "validation_input_schema_identity_sha256": self.input_schema,
            "validation_output_schema_identity_sha256": self.output_schema,
        }
        validator_descriptor = self._write_json(
            "authorities/validator.json", self.validator
        )
        self.validator_ref = self._ref(
            validator_descriptor,
            schema_version=1,
            kind="vast_backend_runtime_validator_authority_q4",
            identity=self.validator["authority_sha256"],
        )
        self.runner = {
            "runner_authority_sha256": sha("runner"),
            "validation_protocol_identity_sha256": self.protocol,
            "input_schema_identity_sha256": self.input_schema,
            "output_schema_identity_sha256": self.output_schema,
            "invocation_contract": {"invocation_sha256": sha("runner-invocation")},
        }
        runner_descriptor = self._write_json(
            "authorities/runner.json", self.runner
        )
        self.runner_ref = self._ref(
            runner_descriptor,
            schema_version=1,
            kind="vast_backend_runtime_validation_runner_authority",
            identity=self.runner["runner_authority_sha256"],
        )
        self.launchers: list[dict[str, object]] = []
        for system in contract.SYSTEMS:
            value = {
                "launcher_runtime_authority_sha256": sha(f"launcher:{system}"),
                "runtime_closure_set_sha256": sha(f"closure-set:{system}"),
                "runtime_closure_manifest_content": {
                    "closure_manifest_sha256": sha(f"closure-manifest:{system}")
                },
            }
            path = f"authorities/launchers/{system}.json"
            descriptor = self._write_json(path, value)
            self.launchers.append(
                {
                    "system": system,
                    "artifact": self._ref(
                        descriptor,
                        schema_version=1,
                        kind=(
                            "vast_backend_publication_launcher_runtime_authority"
                        ),
                        identity=value["launcher_runtime_authority_sha256"],
                    ),
                    "closure_manifest_sha256": value[
                        "runtime_closure_manifest_content"
                    ]["closure_manifest_sha256"],
                    "runtime_closure_set_sha256": value[
                        "runtime_closure_set_sha256"
                    ],
                }
            )
        self.dataset_sources: list[dict[str, object]] = []
        self.source_descriptors: dict[str, tuple[dict[str, object], dict[str, object]]] = {}
        for codec in contract.CODECS:
            front_path = f"datasets/{codec}/iss_v2_front_gate.mp4"
            underbody_path = f"datasets/{codec}/iss_v2_underbody.mp4"
            front = self._write_bytes(front_path, f"front:{codec}".encode("ascii"))
            underbody = self._write_bytes(
                underbody_path, f"underbody:{codec}".encode("ascii")
            )
            self.dataset_sources.append(
                {
                    "codec_variant": codec,
                    "front_gate_source": self._ref(
                        front,
                        schema_version=1,
                        kind="vast_frozen_publication_dataset_source_v1",
                        identity=front["sha256"],
                    ),
                    "underbody_source": self._ref(
                        underbody,
                        schema_version=1,
                        kind="vast_frozen_publication_dataset_source_v1",
                        identity=underbody["sha256"],
                    ),
                }
            )
            self.source_descriptors[codec] = (front, underbody)
        self.authorities: list[dict[str, object]] = []
        for system in contract.SYSTEMS:
            for codec in contract.CODECS:
                for topology in contract.TOPOLOGIES:
                    for policy in contract.POLICIES:
                        coordinate = {
                            "system": system,
                            "codec": codec,
                            "topology_kind": topology,
                            "policy": policy,
                        }
                        template = runtime_template(system, policy, codec)
                        front, underbody = self.source_descriptors[codec]
                        template["source_files"] = [
                            {
                                **copy.deepcopy(front),
                                "container_path": (
                                    f"/opt/vast/input/sources/{codec}/front.mp4"
                                ),
                            },
                            {
                                **copy.deepcopy(underbody),
                                "container_path": (
                                    f"/opt/vast/input/sources/{codec}/underbody.mp4"
                                ),
                            },
                        ]
                        launcher_input = (
                            target.build_publication_q4_runtime_launcher_input_wrapper_v3(
                                system=system,
                                policy=policy,
                                qualification_runtime_input_template=template,
                                production_runtime_input_template=copy.deepcopy(
                                    template
                                ),
                            )
                        )
                        identity = sha(
                            f"runtime:{system}:{codec}:{topology}:{policy}"
                        )
                        authority = {
                            "coordinate": coordinate,
                            "authority_sha256": identity,
                            "upstream_identities": copy.deepcopy(self.upstream),
                            "policy_authority": {
                                "capability": None,
                                "calibration": None,
                                "static_map": None,
                            },
                            "dataset": {
                                "files": [
                                    copy.deepcopy(front),
                                    copy.deepcopy(underbody),
                                ]
                            },
                            "system_specific_launcher_input": {
                                "content": launcher_input,
                                "content_identity_sha256": target.canonical_sha256(
                                    launcher_input
                                ),
                            },
                        }
                        path = (
                            f"authorities/runtime/{system}/{codec}/{topology}/"
                            f"{policy}.json"
                        )
                        descriptor = self._write_json(path, authority)
                        self.authorities.append(
                            {
                                "coordinate": coordinate,
                                "artifact": self._ref(
                                    descriptor,
                                    schema_version=2,
                                    kind=(
                                        "vast_backend_publication_runtime_authority_v2"
                                    ),
                                    identity=identity,
                                ),
                                "upstream_identities": copy.deepcopy(
                                    self.upstream
                                ),
                                "policy_outputs": {
                                    "capability": None,
                                    "calibration": None,
                                    "static_map": None,
                                },
                                "launcher_input_expectations": (
                                    target.publication_q4_runtime_launcher_input_expectations_v5(
                                        launcher_input,
                                        expected_system=system,
                                        expected_policy=policy,
                                    )
                                ),
                            }
                        )
        self.plan = target.build_publication_q4_runtime_materialization_plan_v4(
            dataset_sources=self.dataset_sources,
            runtime_authorities=self.authorities,
            launcher_runtime_authorities=self.launchers,
            publication_launcher_invocation_v3=self.invocation_ref,
            q4_validator_authority=self.validator_ref,
            runner_authority=self.runner_ref,
            runner_invocation_identity_sha256=self.runner[
                "invocation_contract"
            ]["invocation_sha256"],
        )

    def _write_bytes(self, relative: str, payload: bytes) -> dict[str, object]:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        return {
            "path": relative,
            "size_bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }

    def _write_json(self, relative: str, value: object) -> dict[str, object]:
        return self._write_bytes(relative, canonical(value))

    @staticmethod
    def _ref(
        descriptor: dict[str, object],
        *,
        schema_version: int,
        kind: str,
        identity: object,
    ) -> dict[str, object]:
        return {
            "artifact_schema_version": schema_version,
            "artifact_kind": kind,
            "descriptor": copy.deepcopy(descriptor),
            "content_identity_sha256": identity,
        }

    def physical_api_patches(self) -> tuple[mock._patch, ...]:
        identity = lambda value, **_kwargs: copy.deepcopy(value)
        physical = lambda *_args, **_kwargs: {"status": "physically_valid"}
        return (
            mock.patch.object(
                target,
                "validate_backend_publication_runtime_authority_v2",
                side_effect=identity,
            ),
            mock.patch.object(
                target,
                "assess_backend_publication_runtime_authority_v2",
                side_effect=physical,
            ),
            mock.patch.object(
                target,
                "validate_backend_publication_launcher_runtime_authority",
                side_effect=identity,
            ),
            mock.patch.object(
                target,
                "assess_backend_publication_launcher_runtime_authority",
                side_effect=physical,
            ),
            mock.patch.object(
                target,
                "validate_backend_runtime_validator_authority_v4",
                side_effect=identity,
            ),
            mock.patch.object(
                target,
                "assess_backend_runtime_validator_authority_v4",
                side_effect=physical,
            ),
            mock.patch.object(
                target,
                "validate_backend_runtime_validation_runner_authority",
                side_effect=identity,
            ),
            mock.patch.object(
                target,
                "assess_backend_runtime_validation_runner_authority",
                side_effect=physical,
            ),
        )


class PublicationQ4RuntimeRegistryMaterializerV4Tests(unittest.TestCase):
    @staticmethod
    def _materialize(
        fixture: Fixture,
        *,
        output_path: str = "output/runtime-candidates.json",
        result_output_path: str = "output/runtime-materialization-result.json",
        after_artifact_commit: object = None,
    ) -> dict[str, object]:
        with contextlib.ExitStack() as stack:
            for patch in fixture.physical_api_patches():
                stack.enter_context(patch)
            return target.materialize_publication_q4_runtime_candidate_registry_v4(
                project_root=fixture.root,
                plan=fixture.plan,
                output_path=output_path,
                result_output_path=result_output_path,
                after_artifact_commit=after_artifact_commit,
            )

    def test_dual_projection_wrapper_rejects_legacy_crossbinding_and_evidence_drift(
        self,
    ) -> None:
        qualification = runtime_template(
            "gstreamer_custom", "static_hybrid", "h264"
        )
        production = copy.deepcopy(qualification)
        wrapper = target.build_publication_q4_runtime_launcher_input_wrapper_v3(
            system="gstreamer_custom",
            policy="static_hybrid",
            qualification_runtime_input_template=qualification,
            production_runtime_input_template=production,
        )
        self.assertEqual(
            target.validate_publication_q4_runtime_launcher_input_wrapper_v3(
                wrapper,
                expected_system="gstreamer_custom",
                expected_policy="static_hybrid",
            ),
            wrapper,
        )
        self.assertNotEqual(
            wrapper["qualification_projection"]["launcher_evidence_files"],
            wrapper["production_projection"]["launcher_evidence_files"],
        )

        substituted = copy.deepcopy(production)
        evidence_key = next(iter(substituted["evidence_mapping"]))
        substituted["evidence_mapping"][evidence_key] = (
            "alternate-child-evidence.bin"
        )
        with self.assertRaisesRegex(
            target.PublicationQ4RuntimeRegistryMaterializerV4Error,
            "shared runtime configuration drifted",
        ):
            target.build_publication_q4_runtime_launcher_input_wrapper_v3(
                system="gstreamer_custom",
                policy="static_hybrid",
                qualification_runtime_input_template=qualification,
                production_runtime_input_template=substituted,
            )

        permuted = copy.deepcopy(production)
        evidence_keys = list(permuted["evidence_mapping"])
        first, second = evidence_keys[:2]
        permuted["evidence_mapping"][first], permuted["evidence_mapping"][
            second
        ] = (
            permuted["evidence_mapping"][second],
            permuted["evidence_mapping"][first],
        )
        with self.assertRaisesRegex(
            target.PublicationQ4RuntimeRegistryMaterializerV4Error,
            "shared runtime configuration drifted",
        ):
            target.build_publication_q4_runtime_launcher_input_wrapper_v3(
                system="gstreamer_custom",
                policy="static_hybrid",
                qualification_runtime_input_template=qualification,
                production_runtime_input_template=permuted,
            )

        with self.assertRaises(
            target.PublicationQ4RuntimeRegistryMaterializerV4Error
        ):
            target.validate_publication_q4_runtime_launcher_input_wrapper_v3(
                qualification,
                expected_system="gstreamer_custom",
                expected_policy="static_hybrid",
            )

        crossbound = copy.deepcopy(wrapper)
        crossbound["projection_crossbinding_sha256"] = "0" * 64
        with self.assertRaises(
            target.PublicationQ4RuntimeRegistryMaterializerV4Error
        ):
            target.validate_publication_q4_runtime_launcher_input_wrapper_v3(
                crossbound,
                expected_system="gstreamer_custom",
                expected_policy="static_hybrid",
            )

        evidence_drift = copy.deepcopy(wrapper)
        evidence_drift["production_projection"]["launcher_evidence_files"] = [
            "checkpoint_publication_acceptance.json",
            "run_metadata.json",
        ]
        with self.assertRaises(
            target.PublicationQ4RuntimeRegistryMaterializerV4Error
        ):
            target.validate_publication_q4_runtime_launcher_input_wrapper_v3(
                evidence_drift,
                expected_system="gstreamer_custom",
                expected_policy="static_hybrid",
            )

    def test_plan_is_exact_deterministic_and_non_authorizing(self) -> None:
        coordinates = [
            {
                "system": system,
                "codec": codec,
                "topology_kind": topology,
                "policy": policy,
            }
            for system in contract.SYSTEMS
            for codec in contract.CODECS
            for topology in contract.TOPOLOGIES
            for policy in contract.POLICIES
        ]
        def reference(
            path: str, *, schema_version: int, kind: str, identity: str
        ) -> dict[str, object]:
            return {
                "artifact_schema_version": schema_version,
                "artifact_kind": kind,
                "descriptor": {
                    "path": path,
                    "size_bytes": 1,
                    "sha256": sha(f"raw:{path}"),
                },
                "content_identity_sha256": identity,
            }

        arguments = {
            "dataset_sources": [
                {
                    "codec_variant": codec,
                    "front_gate_source": reference(
                        f"datasets/{codec}/front.mp4",
                        schema_version=1,
                        kind="vast_frozen_publication_dataset_source_v1",
                        identity=sha(f"raw:datasets/{codec}/front.mp4"),
                    ),
                    "underbody_source": reference(
                        f"datasets/{codec}/underbody.mp4",
                        schema_version=1,
                        kind="vast_frozen_publication_dataset_source_v1",
                        identity=sha(f"raw:datasets/{codec}/underbody.mp4"),
                    ),
                }
                for codec in contract.CODECS
            ],
            "runtime_authorities": [
                {
                    "coordinate": coordinate,
                    "artifact": reference(
                        f"runtime/{position:03d}.json",
                        schema_version=2,
                        kind="vast_backend_publication_runtime_authority_v2",
                        identity=sha(f"runtime:{position}"),
                    ),
                    "upstream_identities": {
                        field: sha(f"upstream:{field}")
                        for field in contract.UPSTREAM_IDENTITY_FIELDS
                    },
                    "policy_outputs": {
                        "capability": None,
                        "calibration": None,
                        "static_map": None,
                    },
                    "launcher_input_expectations": {
                        field: sha(f"{position}:{field}")
                        for field in target._LAUNCHER_INPUT_EXPECTATION_FIELDS
                    },
                }
                for position, coordinate in enumerate(coordinates)
            ],
            "launcher_runtime_authorities": [
                {
                    "system": system,
                    "artifact": reference(
                        f"launcher/{system}.json",
                        schema_version=1,
                        kind=(
                            "vast_backend_publication_launcher_runtime_authority"
                        ),
                        identity=sha(f"launcher:{system}"),
                    ),
                    "closure_manifest_sha256": sha(f"manifest:{system}"),
                    "runtime_closure_set_sha256": sha(f"closure:{system}"),
                }
                for system in contract.SYSTEMS
            ],
            "publication_launcher_invocation_v3": reference(
                "trust/invocation.json",
                schema_version=3,
                kind="vast_backend_publication_launcher_invocation_v3",
                identity=sha("invocation"),
            ),
            "q4_validator_authority": reference(
                "trust/validator.json",
                schema_version=1,
                kind="vast_backend_runtime_validator_authority_q4",
                identity=sha("validator"),
            ),
            "runner_authority": reference(
                "trust/runner.json",
                schema_version=1,
                kind="vast_backend_runtime_validation_runner_authority",
                identity=sha("runner"),
            ),
            "runner_invocation_identity_sha256": sha("runner-invocation"),
        }
        plan = target.build_publication_q4_runtime_materialization_plan_v4(
            **arguments
        )
        self.assertEqual(
            target.validate_publication_q4_runtime_materialization_plan_v4(plan),
            plan,
        )
        self.assertFalse(plan["authorization_eligible"])
        self.assertFalse(plan["execution_authorized"])
        with self.assertRaises(
            target.PublicationQ4RuntimeRegistryMaterializerV4Error
        ):
            target.build_publication_q4_runtime_materialization_plan_v4(
                **{
                    **arguments,
                    "runtime_authorities": list(
                        reversed(arguments["runtime_authorities"])
                    ),
                }
            )

    def test_physical_materializer_commits_exact_registry_and_exactly_resumes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            fixture = Fixture(root)
            result = self._materialize(fixture)
            self.assertEqual(result["runtime_authority_count"], 112)
            self.assertEqual(result["dataset_binding_count"], 2)
            output = root / result["runtime_candidate_registry"]["path"]
            result_output = root / "output/runtime-materialization-result.json"
            registry = json.loads(output.read_bytes())
            checked = contract.validate_publication_q4_runtime_candidate_registry_v4(
                registry
            )
            self.assertEqual(
                checked["registry_sha256"],
                result["runtime_candidate_registry_sha256"],
            )
            identities = (output.stat().st_ino, result_output.stat().st_ino)
            self.assertEqual(self._materialize(fixture), result)
            self.assertEqual(
                (output.stat().st_ino, result_output.stat().st_ino),
                identities,
            )

    def test_two_leaf_materializer_recovers_every_commit_and_lost_response(
        self,
    ) -> None:
        cases = (
            ("runtime_candidate_registry:mid_write", False, False),
            ("runtime_candidate_registry:post_fsync_pre_publish", False, False),
            ("runtime_candidate_registry:post_publish_pre_parent_fsync", True, False),
            ("runtime_candidate_registry", True, False),
            ("runtime_materialization_result:mid_write", True, False),
            ("runtime_materialization_result:post_fsync_pre_publish", True, False),
            (
                "runtime_materialization_result:post_publish_pre_parent_fsync",
                True,
                True,
            ),
            ("runtime_materialization_result", True, True),
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            fixture = Fixture(root)
            for position, (boundary, registry_exists, result_exists) in enumerate(cases):
                with self.subTest(boundary=boundary):
                    output_path = f"output-{position}/runtime-candidates.json"
                    result_path = f"output-{position}/runtime-result.json"

                    def crash(observed: str) -> None:
                        if observed == boundary:
                            raise InjectedCrash(observed)

                    with self.assertRaises(InjectedCrash):
                        self._materialize(
                            fixture,
                            output_path=output_path,
                            result_output_path=result_path,
                            after_artifact_commit=crash,
                        )
                    registry = root / output_path
                    receipt = root / result_path
                    self.assertEqual(registry.exists(), registry_exists)
                    self.assertEqual(receipt.exists(), result_exists)
                    registry_identity = (
                        registry.stat().st_ino if registry.exists() else None
                    )
                    receipt_identity = (
                        receipt.stat().st_ino if receipt.exists() else None
                    )

                    result = self._materialize(
                        fixture,
                        output_path=output_path,
                        result_output_path=result_path,
                    )
                    if registry_identity is not None:
                        self.assertEqual(registry.stat().st_ino, registry_identity)
                    if receipt_identity is not None:
                        self.assertEqual(receipt.stat().st_ino, receipt_identity)
                    committed_identities = (
                        registry.stat().st_ino,
                        receipt.stat().st_ino,
                    )
                    self.assertEqual(
                        self._materialize(
                            fixture,
                            output_path=output_path,
                            result_output_path=result_path,
                        ),
                        result,
                    )
                    self.assertEqual(
                        (registry.stat().st_ino, receipt.stat().st_ino),
                        committed_identities,
                    )

    def test_two_leaf_resume_rejects_partial_tamper_foreign_result_and_redirect(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            fixture = Fixture(root)
            output_path = "partial/runtime-candidates.json"
            result_path = "partial/runtime-result.json"

            def crash(boundary: str) -> None:
                if boundary == "runtime_candidate_registry":
                    raise InjectedCrash(boundary)

            with self.assertRaises(InjectedCrash):
                self._materialize(
                    fixture,
                    output_path=output_path,
                    result_output_path=result_path,
                    after_artifact_commit=crash,
                )
            registry = root / output_path
            registry.chmod(0o644)
            registry.write_bytes(b'{"foreign":true}\n')
            registry.chmod(0o444)
            with self.assertRaisesRegex(
                target.PublicationQ4RuntimeRegistryMaterializerV4Error,
                "drifted|custody",
            ):
                self._materialize(
                    fixture,
                    output_path=output_path,
                    result_output_path=result_path,
                )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            fixture = Fixture(root)
            foreign_result = root / "result-only/runtime-result.json"
            foreign_result.parent.mkdir(parents=True)
            foreign_result.write_bytes(b'{"foreign":true}\n')
            with self.assertRaisesRegex(
                target.PublicationQ4RuntimeRegistryMaterializerV4Error,
                "without its causal registry",
            ):
                self._materialize(
                    fixture,
                    output_path="result-only/runtime-candidates.json",
                    result_output_path="result-only/runtime-result.json",
                )

        if os.name == "posix":
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                fixture = Fixture(root)
                foreign = root / "foreign"
                foreign.mkdir()
                (root / "redirect").symlink_to(foreign, target_is_directory=True)
                with self.assertRaisesRegex(
                    target.PublicationQ4RuntimeRegistryMaterializerV4Error,
                    "custody|physical|directory|unsafe",
                ):
                    self._materialize(
                        fixture,
                        output_path="redirect/runtime-candidates.json",
                        result_output_path="redirect/runtime-result.json",
                    )

    @unittest.skipUnless(
        os.name == "posix" and sys.platform.startswith("linux"),
        "transient ABA watch is Linux-only",
    )
    def test_two_leaf_materializer_rejects_same_invocation_aba(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            fixture = Fixture(root)
            output_path = "aba/runtime-candidates.json"

            def replace(boundary: str) -> None:
                if boundary != "runtime_candidate_registry":
                    return
                path = root / output_path
                payload = path.read_bytes()
                path.unlink()
                path.write_bytes(payload)
                path.chmod(0o444)

            with self.assertRaisesRegex(
                target.PublicationQ4RuntimeRegistryMaterializerV4Error,
                "mutated|changed|custody",
            ):
                self._materialize(
                    fixture,
                    output_path=output_path,
                    result_output_path="aba/runtime-result.json",
                    after_artifact_commit=replace,
                )

    def test_missing_physical_authority_fails_before_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            fixture = Fixture(root)
            (
                root
                / fixture.authorities[0]["artifact"]["descriptor"]["path"]
            ).unlink()
            patches = fixture.physical_api_patches()
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7]:
                with self.assertRaises(
                    target.PublicationQ4RuntimeRegistryMaterializerV4Error
                ):
                    target.materialize_publication_q4_runtime_candidate_registry_v4(
                        project_root=root,
                        plan=fixture.plan,
                        output_path="output/runtime-candidates.json",
                        result_output_path="output/runtime-materialization-result.json",
                    )
            self.assertFalse((root / "output/runtime-candidates.json").exists())

    def test_plan_pins_reject_runtime_authority_swap_then_accept_restore(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            fixture = Fixture(root)
            authority_path = (
                root
                / fixture.authorities[0]["artifact"]["descriptor"]["path"]
            )
            original = authority_path.read_bytes()
            foreign = json.loads(original)
            foreign["upstream_identities"][
                contract.UPSTREAM_IDENTITY_FIELDS[0]
            ] = sha("foreign-upstream")
            foreign["authority_sha256"] = target.canonical_sha256(
                {
                    key: item
                    for key, item in foreign.items()
                    if key != "authority_sha256"
                }
            )
            authority_path.write_bytes(canonical(foreign))
            patches = fixture.physical_api_patches()
            with (
                patches[0], patches[1], patches[2], patches[3],
                patches[4], patches[5], patches[6], patches[7],
            ):
                with self.assertRaisesRegex(
                    target.PublicationQ4RuntimeRegistryMaterializerV4Error,
                    "raw descriptor pin drifted",
                ):
                    target.materialize_publication_q4_runtime_candidate_registry_v4(
                        project_root=root,
                        plan=fixture.plan,
                        output_path="output/runtime-candidates.json",
                        result_output_path="output/runtime-materialization-result.json",
                    )
            self.assertFalse((root / "output/runtime-candidates.json").exists())
            authority_path.write_bytes(original)
            patches = fixture.physical_api_patches()
            with (
                patches[0], patches[1], patches[2], patches[3],
                patches[4], patches[5], patches[6], patches[7],
            ):
                result = target.materialize_publication_q4_runtime_candidate_registry_v4(
                    project_root=root,
                    plan=fixture.plan,
                    output_path="output/runtime-candidates.json",
                    result_output_path="output/runtime-materialization-result.json",
                )
            self.assertEqual(result["runtime_authority_count"], 112)

    def test_cli_requires_both_file_and_semantic_plan_pins(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            fixture = Fixture(root)
            plan_path = root / "plan.json"
            plan_payload = target.canonical_bytes(fixture.plan, newline=True)
            plan_path.write_bytes(plan_payload)

            class Stream:
                def __init__(self) -> None:
                    self.buffer = io.BytesIO()

            stdout = Stream()
            stderr = Stream()
            patches = fixture.physical_api_patches()
            with (
                patches[0],
                patches[1],
                patches[2],
                patches[3],
                patches[4],
                patches[5],
                patches[6],
                patches[7],
                mock.patch.object(target.sys, "stdout", stdout),
                mock.patch.object(target.sys, "stderr", stderr),
            ):
                exit_code = target.main(
                    [
                        "--project-root",
                        str(root),
                        "--plan",
                        "plan.json",
                        "--plan-file-sha256",
                        hashlib.sha256(plan_payload).hexdigest(),
                        "--plan-sha256",
                        fixture.plan["plan_sha256"],
                        "--output",
                        "output/from-cli.json",
                        "--result-output",
                        "output/from-cli.result.json",
                    ]
                )
            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr.buffer.getvalue(), b"")
            result = json.loads(stdout.buffer.getvalue())
            self.assertEqual(result["runtime_authority_count"], 112)
            self.assertTrue((root / "output/from-cli.json").is_file())
            self.assertTrue((root / "output/from-cli.result.json").is_file())


@unittest.skipUnless(
    os.name == "posix" and sys.platform.startswith("linux"),
    "no-mock Phase1 physical roundtrip requires WSL/Linux",
)
class PublicationQ4RuntimeRegistryNoMockRoundtripTests(unittest.TestCase):
    def test_source_spec_phase1_registry_roundtrips_into_real_production_selector(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            fixture = AuthorityPlanFixture(root)
            try:
                source_spec_path, source_spec = fixture.source_spec("A")
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
                        output_dir="transactions/A/phase1",
                    )
                )
                plan_path = root / phase1["runtime_materialization_plan"][
                    "descriptor"
                ]["path"]
                registry_result = (
                    target.materialize_publication_q4_runtime_candidate_registry_v4(
                        project_root=root,
                        plan=json.loads(plan_path.read_bytes()),
                        output_path=source_spec["planned_outputs"][
                            "runtime_candidate_registry_path"
                        ],
                        result_output_path=source_spec["planned_outputs"][
                            "runtime_materialization_result_path"
                        ],
                    )
                )
                registry = json.loads(
                    (
                        root
                        / registry_result["runtime_candidate_registry"]["path"]
                    ).read_bytes()
                )
                snapshot = registry["authority_snapshots"][0]
                coordinate = copy.deepcopy(snapshot["coordinate"])
                authority_record = phase1["runtime_authorities"][0]
                authority = json.loads(
                    (
                        root
                        / authority_record["artifact"]["descriptor"]["path"]
                    ).read_bytes()
                )
                launcher_record = phase1["launcher_runtime_authorities"][0]
                launcher_authority = json.loads(
                    (
                        root
                        / launcher_record["artifact"]["descriptor"]["path"]
                    ).read_bytes()
                )
                launcher = launcher_authority["publication_launcher"][
                    "descriptor"
                ]
                cell = {
                    **coordinate,
                    "deadline_ms": 100,
                    "cell_identity_sha256": sha("roundtrip-cell"),
                    "validation_record_sha256": sha("roundtrip-validation"),
                    "runtime_authority_sha256": authority["authority_sha256"],
                    "launcher_invocation_sha256": fixture.invocation_sha,
                }
                identity_binding = {
                    "bindings": {
                        "backend_runtime_qualification": {
                            "schema_version": 3,
                            "artifact_kind": (
                                "vast_full_publication_backend_runtime_qualification_binding_v3"
                            ),
                            "authorization_eligible": True,
                            "semantic_crossbinding_complete": True,
                            "authorization_blockers": [],
                            "systems": {
                                coordinate["system"]: {
                                    "launcher": copy.deepcopy(launcher),
                                    "runtime_authorities": [
                                        {
                                            **coordinate,
                                            "artifact": authority,
                                            "runtime_authority_sha256": authority[
                                                "authority_sha256"
                                            ],
                                        }
                                    ],
                                    "qualified_cells": [copy.deepcopy(cell)],
                                }
                            },
                        }
                    }
                }
                backend_grant = {
                    "systems": {
                        coordinate["system"]: {
                            "launcher": copy.deepcopy(launcher),
                            "qualified_cells": [copy.deepcopy(cell)],
                        }
                    }
                }
                selected = full_entrypoint._select_production_v3_authority(
                    identity_artifacts=identity_binding,
                    backend_runtime_grant=backend_grant,
                    coordinate=cell,
                    runtime_authority_snapshot=snapshot,
                )
                wrapper = target.validate_publication_q4_runtime_launcher_input_wrapper_v3(
                    authority["system_specific_launcher_input"]["content"],
                    expected_system=coordinate["system"],
                    expected_policy=coordinate["policy"],
                )
                self.assertEqual(
                    selected["qualification_dataset_runtime_input"],
                    snapshot["runtime_input_template"],
                )
                self.assertEqual(
                    selected["dataset_runtime_input"],
                    wrapper["production_projection"]["runtime_input_template"],
                )
                self.assertEqual(
                    selected["launcher_evidence_files"],
                    wrapper["production_projection"]["launcher_evidence_files"],
                )
            finally:
                fixture.close()


if __name__ == "__main__":
    unittest.main()
