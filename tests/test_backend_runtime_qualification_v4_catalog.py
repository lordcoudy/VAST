from __future__ import annotations

import ast
import copy
import hashlib
import inspect
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import backend_runtime_qualification_v4_catalog as catalog  # noqa: E402
import backend_runtime_validation_records_v2 as records  # noqa: E402
from test_backend_runtime_validation_records_v2 import (  # noqa: E402
    Fixture as RecordFixture,
    persisted,
    sha,
)


def canonical_sha(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")).hexdigest()


class Fixture:
    def __init__(self) -> None:
        self.records = RecordFixture()
        self.shards, self.index = self.records.build_graph()
        self.context_refs = [copy.deepcopy(item["context_ref"])
                             for item in self.index["system_shards"]]
        self.shard_refs = [copy.deepcopy(item["system_shard_ref"])
                           for item in self.index["system_shards"]]
        self.request_refs = [
            persisted(
                f"catalog-request-{position}", request, "request_sha256",
                schema_version=2, kind=records.REQUEST_KIND,
            )
            for position, request in enumerate(self.records.requests)
        ]
        self.record_refs = [copy.deepcopy(item["validation_record_ref"])
                            for item in self.index["validation_records"]]
        self.index_ref = persisted(
            "catalog-record-index", self.index, "index_sha256",
            schema_version=2, kind=records.INDEX_KIND,
        )
        self.context_root = canonical_sha([
            {"system": item["system"], "context_ref": item["context_ref"],
             "context_sha256": item["context_sha256"]}
            for item in self.index["system_shards"]
        ])
        self.shard_root = self.index["system_shard_set_sha256"]
        self.request_projection = [
            {"coordinate": records.coordinate_for_cell_index_v2(position),
             "validation_request_ref": self.request_refs[position]}
            for position in range(560)
        ]
        self.request_root = canonical_sha(self.request_projection)
        self.record_root = self.index["validation_record_global_set_sha256"]

    def kwargs(self) -> dict[str, object]:
        return {
            "q4_input_ref": self.records.q4_ref,
            "q4_validator_authority_ref": self.records.validator_ref,
            "runner_authority_ref": self.records.runner_ref,
            "publication_launcher_invocation_v3_ref": self.records.abi_ref,
            "records_v2_global_index": self.index,
            "records_v2_global_index_ref": self.index_ref,
            "system_context_refs": self.context_refs,
            "system_shard_refs": self.shard_refs,
            "validation_request_refs": self.request_refs,
            "validation_record_refs": self.record_refs,
            "expected_q4_input_sha256": self.records.q4_sha,
            "expected_q4_validator_authority_sha256": self.records.validator_sha,
            "expected_runner_authority_sha256": self.records.runner_sha,
            "expected_publication_launcher_invocation_v3_sha256": self.records.abi_sha,
            "expected_runner_invocation_identity_sha256": self.records.invocation_sha,
            "expected_records_v2_global_index_sha256": self.index["index_sha256"],
            "expected_system_context_set_sha256": self.context_root,
            "expected_system_shard_set_sha256": self.shard_root,
            "expected_validation_request_global_set_sha256": self.request_root,
            "expected_validation_record_global_set_sha256": self.record_root,
        }

    def unsigned_catalog(self) -> dict[str, object]:
        cells = [
            {"coordinate": records.coordinate_for_cell_index_v2(position),
             "validation_request_ref": copy.deepcopy(self.request_refs[position]),
             "validation_record_ref": copy.deepcopy(self.record_refs[position])}
            for position in range(560)
        ]
        return {
            "schema_version": 1,
            "artifact_kind": catalog.ARTIFACT_KIND,
            "status": "persisted_validation_graph_candidate",
            "qualification_accepted": False,
            "trusted_replay_completed": False,
            "deterministic_replay_assessed": False,
            "post_run_per_arm_evidence_required": True,
            "configuration_evidence_accepted_mutated": False,
            "authorization_eligible": False,
            "execution_authorized": False,
            "validation_records_authenticated": False,
            "q4_input_ref": copy.deepcopy(self.records.q4_ref),
            "q4_input_sha256": self.records.q4_sha,
            "q4_validator_authority_ref": copy.deepcopy(self.records.validator_ref),
            "q4_validator_authority_sha256": self.records.validator_sha,
            "runner_authority_ref": copy.deepcopy(self.records.runner_ref),
            "runner_authority_sha256": self.records.runner_sha,
            "publication_launcher_invocation_v3_ref": copy.deepcopy(self.records.abi_ref),
            "publication_launcher_invocation_v3_sha256": self.records.abi_sha,
            "runner_invocation_identity_sha256": self.records.invocation_sha,
            "records_v2_global_index_ref": copy.deepcopy(self.index_ref),
            "records_v2_global_index_sha256": self.index["index_sha256"],
            "system_graphs": copy.deepcopy(self.index["system_shards"]),
            "system_context_set_sha256": self.context_root,
            "system_shard_set_sha256": self.shard_root,
            "validation_cells": cells,
            "validation_request_global_set_sha256": self.request_root,
            "validation_record_global_set_sha256": self.record_root,
            "coverage": {"system_count": 4, "contexts_per_system": 1,
                         "shards_per_system": 1, "cells_per_system": 140,
                         "validation_request_count": 560,
                         "validation_record_count": 560},
        }

    def build(self) -> dict[str, object]:
        return catalog.build_backend_runtime_qualification_v4_catalog(
            **self.kwargs(),
            expected_catalog_semantic_sha256=canonical_sha(self.unsigned_catalog()),
        )


class BackendRuntimeQualificationV4CatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = Fixture()
        cls.value = cls.fixture.build()
        cls.expected_sha = cls.value["catalog_sha256"]

    def validate(self, value: object, **overrides: object) -> dict[str, object]:
        kwargs = self.fixture.kwargs()
        kwargs.update(overrides)
        return catalog.validate_backend_runtime_qualification_v4_catalog(
            value, **kwargs,
            expected_catalog_semantic_sha256=self.expected_sha,
        )

    @staticmethod
    def reseal(value: dict[str, object]) -> None:
        value["catalog_sha256"] = canonical_sha({
            key: item for key, item in value.items() if key != "catalog_sha256"
        })

    def test_exact_candidate_graph_builds_and_validates(self) -> None:
        checked = self.validate(self.value)
        self.assertEqual(checked["schema_version"], 1)
        self.assertEqual(checked["artifact_kind"], catalog.ARTIFACT_KIND)
        self.assertEqual(
            checked["status"], "persisted_validation_graph_candidate",
        )
        self.assertEqual(len(checked["system_graphs"]), 4)
        self.assertEqual(len(checked["validation_cells"]), 560)
        self.assertEqual(
            [item["coordinate"]["cell_index"]
             for item in checked["validation_cells"]], list(range(560)),
        )
        self.assertEqual(checked["coverage"], {
            "system_count": 4, "contexts_per_system": 1,
            "shards_per_system": 1, "cells_per_system": 140,
            "validation_request_count": 560,
            "validation_record_count": 560,
        })
        self.assertIsNot(checked, self.value)

    def test_all_claims_are_exact_fail_closed_booleans(self) -> None:
        expected = {
            "qualification_accepted": False,
            "trusted_replay_completed": False,
            "deterministic_replay_assessed": False,
            "post_run_per_arm_evidence_required": True,
            "configuration_evidence_accepted_mutated": False,
            "authorization_eligible": False,
            "execution_authorized": False,
            "validation_records_authenticated": False,
        }
        self.assertEqual({field: self.value[field] for field in expected}, expected)
        for field, canonical in expected.items():
            for smuggled in (not canonical, int(canonical)):
                changed = copy.deepcopy(self.value)
                changed[field] = smuggled
                self.reseal(changed)
                with self.subTest(field=field, value=smuggled), self.assertRaises(
                    catalog.BackendRuntimeQualificationV4CatalogError
                ):
                    self.validate(changed)

    def test_builder_requires_external_catalog_pin_and_all_root_pins(self) -> None:
        kwargs = self.fixture.kwargs()
        with self.assertRaises(catalog.BackendRuntimeQualificationV4CatalogError):
            catalog.build_backend_runtime_qualification_v4_catalog(
                **kwargs, expected_catalog_semantic_sha256=sha("wrong"),
            )
        required = {
            "expected_q4_input_sha256",
            "expected_q4_validator_authority_sha256",
            "expected_runner_authority_sha256",
            "expected_publication_launcher_invocation_v3_sha256",
            "expected_runner_invocation_identity_sha256",
            "expected_records_v2_global_index_sha256",
            "expected_system_context_set_sha256",
            "expected_system_shard_set_sha256",
            "expected_validation_request_global_set_sha256",
            "expected_validation_record_global_set_sha256",
            "expected_catalog_semantic_sha256",
        }
        for function in (
            catalog.build_backend_runtime_qualification_v4_catalog,
            catalog.validate_backend_runtime_qualification_v4_catalog,
        ):
            signature = inspect.signature(function)
            self.assertTrue(required.issubset(signature.parameters))
            for name in required:
                self.assertIs(signature.parameters[name].default,
                              inspect.Parameter.empty)
        for name in required - {"expected_catalog_semantic_sha256"}:
            changed_kwargs = self.fixture.kwargs()
            changed_kwargs[name] = sha("wrong:" + name)
            with self.subTest(name=name), self.assertRaises(
                catalog.BackendRuntimeQualificationV4CatalogError
            ):
                catalog.build_backend_runtime_qualification_v4_catalog(
                    **changed_kwargs,
                    expected_catalog_semantic_sha256=self.expected_sha,
                )

    def test_supplied_record_index_is_closed_bound_and_non_authorizing(self) -> None:
        mutations: list[dict[str, object]] = []
        changed = copy.deepcopy(self.fixture.index)
        changed["unknown"] = False
        mutations.append(changed)
        changed = copy.deepcopy(self.fixture.index)
        changed["index_sha256"] = sha("wrong-index")
        mutations.append(changed)
        changed = copy.deepcopy(self.fixture.index)
        changed["authorization_eligible"] = True
        changed["index_sha256"] = canonical_sha({
            key: item for key, item in changed.items() if key != "index_sha256"
        })
        mutations.append(changed)
        changed = copy.deepcopy(self.fixture.index)
        changed["validation_records"][0]["coordinate"]["cell_index"] = 1
        changed["validation_record_global_set_sha256"] = canonical_sha(
            changed["validation_records"]
        )
        changed["index_sha256"] = canonical_sha({
            key: item for key, item in changed.items() if key != "index_sha256"
        })
        mutations.append(changed)
        for position, changed in enumerate(mutations):
            kwargs = self.fixture.kwargs()
            kwargs["records_v2_global_index"] = changed
            with self.subTest(position=position), self.assertRaises(
                catalog.BackendRuntimeQualificationV4CatalogError
            ):
                catalog.build_backend_runtime_qualification_v4_catalog(
                    **kwargs, expected_catalog_semantic_sha256=self.expected_sha,
                )

    def test_each_system_record_set_root_is_recomputed_from_its_140_entries(
        self,
    ) -> None:
        changed_index = copy.deepcopy(self.fixture.index)
        changed_index["system_shards"][0]["validation_record_set_sha256"] = (
            changed_index["system_shards"][0]["system_shard_sha256"]
        )
        changed_index["system_shard_set_sha256"] = canonical_sha(
            changed_index["system_shards"]
        )
        changed_index["index_sha256"] = canonical_sha({
            key: item for key, item in changed_index.items()
            if key != "index_sha256"
        })
        changed_index_ref = persisted(
            "catalog-record-index-invalid-set-root", changed_index,
            "index_sha256", schema_version=2, kind=records.INDEX_KIND,
        )
        kwargs = self.fixture.kwargs()
        kwargs.update({
            "records_v2_global_index": changed_index,
            "records_v2_global_index_ref": changed_index_ref,
            "expected_records_v2_global_index_sha256": (
                changed_index["index_sha256"]
            ),
            "expected_system_shard_set_sha256": (
                changed_index["system_shard_set_sha256"]
            ),
        })
        unsigned = self.fixture.unsigned_catalog()
        unsigned.update({
            "records_v2_global_index_ref": changed_index_ref,
            "records_v2_global_index_sha256": changed_index["index_sha256"],
            "system_graphs": copy.deepcopy(changed_index["system_shards"]),
            "system_shard_set_sha256": (
                changed_index["system_shard_set_sha256"]
            ),
        })
        with self.assertRaises(
            catalog.BackendRuntimeQualificationV4CatalogError
        ):
            catalog.build_backend_runtime_qualification_v4_catalog(
                **kwargs,
                expected_catalog_semantic_sha256=canonical_sha(unsigned),
            )

    def test_ref_file_and_content_identities_cannot_alias_aggregate_roots(
        self,
    ) -> None:
        for component in ("file", "content"):
            with self.subTest(component=component):
                request_refs = copy.deepcopy(self.fixture.request_refs)
                if component == "file":
                    request_refs[0]["descriptor"]["sha256"] = (
                        self.fixture.context_root
                    )
                else:
                    request_refs[0]["content_identity_sha256"] = (
                        self.fixture.context_root
                    )
                request_projection = [
                    {
                        "coordinate": records.coordinate_for_cell_index_v2(
                            position
                        ),
                        "validation_request_ref": request_refs[position],
                    }
                    for position in range(560)
                ]
                request_root = canonical_sha(request_projection)
                kwargs = self.fixture.kwargs()
                kwargs.update({
                    "validation_request_refs": request_refs,
                    "expected_validation_request_global_set_sha256": (
                        request_root
                    ),
                })
                unsigned = self.fixture.unsigned_catalog()
                unsigned["validation_cells"][0][
                    "validation_request_ref"
                ] = copy.deepcopy(request_refs[0])
                unsigned["validation_request_global_set_sha256"] = request_root
                with self.assertRaises(
                    catalog.BackendRuntimeQualificationV4CatalogError
                ):
                    catalog.build_backend_runtime_qualification_v4_catalog(
                        **kwargs,
                        expected_catalog_semantic_sha256=canonical_sha(unsigned),
                    )

    def test_parent_membership_order_missing_and_duplicate_refs_fail(self) -> None:
        cases: list[tuple[str, list[dict[str, object]]]] = []
        contexts = copy.deepcopy(self.fixture.context_refs)
        contexts.reverse()
        cases.append(("system_context_refs", contexts))
        shards = copy.deepcopy(self.fixture.shard_refs)
        shards.pop()
        cases.append(("system_shard_refs", shards))
        records_changed = copy.deepcopy(self.fixture.record_refs)
        records_changed[9] = copy.deepcopy(records_changed[8])
        cases.append(("validation_record_refs", records_changed))
        requests_changed = copy.deepcopy(self.fixture.request_refs)
        requests_changed[3], requests_changed[4] = (
            requests_changed[4], requests_changed[3]
        )
        cases.append(("validation_request_refs", requests_changed))
        for field, sequence in cases:
            kwargs = self.fixture.kwargs()
            kwargs[field] = sequence
            with self.subTest(field=field), self.assertRaises(
                catalog.BackendRuntimeQualificationV4CatalogError
            ):
                catalog.build_backend_runtime_qualification_v4_catalog(
                    **kwargs, expected_catalog_semantic_sha256=self.expected_sha,
                )

    def test_typed_ref_type_kind_semantic_and_parent_mismatches_fail(self) -> None:
        cases: list[tuple[str, dict[str, object]]] = []
        q4_ref = copy.deepcopy(self.fixture.records.q4_ref)
        q4_ref["artifact_schema_version"] = 3
        cases.append(("q4_input_ref", q4_ref))
        validator_ref = copy.deepcopy(self.fixture.records.validator_ref)
        validator_ref["artifact_kind"] = "wrong"
        cases.append(("q4_validator_authority_ref", validator_ref))
        runner_ref = copy.deepcopy(self.fixture.records.runner_ref)
        runner_ref["content_identity_sha256"] = sha("wrong-runner")
        cases.append(("runner_authority_ref", runner_ref))
        index_ref = copy.deepcopy(self.fixture.index_ref)
        index_ref["content_identity_sha256"] = sha("wrong-index-ref")
        cases.append(("records_v2_global_index_ref", index_ref))
        for field, value in cases:
            kwargs = self.fixture.kwargs()
            kwargs[field] = value
            with self.subTest(field=field), self.assertRaises(
                catalog.BackendRuntimeQualificationV4CatalogError
            ):
                catalog.build_backend_runtime_qualification_v4_catalog(
                    **kwargs, expected_catalog_semantic_sha256=self.expected_sha,
                )

    def test_request_record_coordinate_swap_and_deadline_type_smuggle_fail(self) -> None:
        changed = copy.deepcopy(self.value)
        changed["validation_cells"][1]["validation_request_ref"], changed[
            "validation_cells"
        ][2]["validation_request_ref"] = (
            changed["validation_cells"][2]["validation_request_ref"],
            changed["validation_cells"][1]["validation_request_ref"],
        )
        self.reseal(changed)
        with self.assertRaises(catalog.BackendRuntimeQualificationV4CatalogError):
            self.validate(changed)
        changed = copy.deepcopy(self.value)
        changed["validation_cells"][2]["coordinate"]["deadline_ms"] = 50.0
        self.reseal(changed)
        with self.assertRaises(catalog.BackendRuntimeQualificationV4CatalogError):
            self.validate(changed)
        changed = copy.deepcopy(self.value)
        changed["validation_cells"][1], changed["validation_cells"][2] = (
            changed["validation_cells"][2],
            changed["validation_cells"][1],
        )
        self.reseal(changed)
        with self.assertRaises(catalog.BackendRuntimeQualificationV4CatalogError):
            self.validate(changed)

    def test_unique_node_refs_are_globally_distinct_by_path_file_and_content(self) -> None:
        root = self.fixture.context_refs[0]
        for component in ("path", "file", "content"):
            request_refs = copy.deepcopy(self.fixture.request_refs)
            if component == "path":
                request_refs[0]["descriptor"]["path"] = (
                    root["descriptor"]["path"].upper()
                )
            elif component == "file":
                request_refs[0]["descriptor"]["sha256"] = (
                    root["descriptor"]["sha256"]
                )
            else:
                request_refs[0]["content_identity_sha256"] = (
                    root["content_identity_sha256"]
                )
            kwargs = self.fixture.kwargs()
            kwargs["validation_request_refs"] = request_refs
            with self.subTest(component=component), self.assertRaises(
                catalog.BackendRuntimeQualificationV4CatalogError
            ):
                catalog.build_backend_runtime_qualification_v4_catalog(
                    **kwargs, expected_catalog_semantic_sha256=self.expected_sha,
                )

    def test_catalog_is_closed_and_rejects_downstream_claim_fields(self) -> None:
        for field in (
            "qualification_receipt_ref", "acceptance_binding_ref",
            "full_publication_identity_ref", "runtime_authorization_ref",
        ):
            changed = copy.deepcopy(self.value)
            changed[field] = copy.deepcopy(self.fixture.index_ref)
            self.reseal(changed)
            with self.subTest(field=field), self.assertRaises(
                catalog.BackendRuntimeQualificationV4CatalogError
            ):
                self.validate(changed)

    def test_builder_and_validator_are_copy_isolated(self) -> None:
        kwargs = copy.deepcopy(self.fixture.kwargs())
        built = self.fixture.build()
        kwargs["validation_request_refs"][0]["descriptor"]["path"] = (
            "qualification/replay-v2/mutated.json"
        )
        self.assertNotEqual(
            built["validation_cells"][0]["validation_request_ref"]
            ["descriptor"]["path"],
            "qualification/replay-v2/mutated.json",
        )
        checked = self.validate(self.value)
        checked["validation_cells"][0]["coordinate"]["cell_index"] = 99
        self.assertEqual(
            self.value["validation_cells"][0]["coordinate"]["cell_index"], 0,
        )

    def test_source_is_pure_and_has_no_downstream_or_execution_surface(self) -> None:
        source = inspect.getsource(catalog)
        tree = ast.parse(source)
        imported = {
            alias.name.split(".")[0]
            for node in ast.walk(tree) if isinstance(node, ast.Import)
            for alias in node.names
        }
        imported.update(
            (node.module or "").split(".")[0]
            for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
        )
        self.assertTrue(imported <= {
            "__future__", "copy", "hashlib", "json", "math", "re", "typing",
        })
        calls = {
            node.func.id for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertTrue({"open", "exec", "eval", "compile"}.isdisjoint(calls))
        lowered = source.lower()
        for forbidden in (
            "subprocess", "socket", "docker",
            "qualification_receipt", "acceptance_binding",
            "publication_matrix", "runtime_grant", "readiness",
        ):
            self.assertNotIn(forbidden, lowered)
        self.assertNotIn("replay_assessment_ref", lowered)


if __name__ == "__main__":
    unittest.main()
