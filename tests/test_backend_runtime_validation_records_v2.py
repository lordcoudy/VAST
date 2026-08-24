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

import backend_runtime_validation_records as legacy  # noqa: E402
import backend_runtime_validation_records_v2 as protocol  # noqa: E402


def sha(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def ref(label: str, semantic: str | None = None) -> dict[str, object]:
    payload = (label + "\n").encode("utf-8")
    return {
        "descriptor": {
            "path": f"qualification/replay-v2/{label}.json",
            "size_bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        },
        "content_identity_sha256": semantic or sha(f"semantic:{label}"),
    }


def typed(
    label: str, schema_version: int, kind: str, semantic: str | None = None,
) -> dict[str, object]:
    return {
        "artifact_schema_version": schema_version,
        "artifact_kind": kind,
        **ref(label, semantic),
    }


def persisted(
    label: str, value: dict[str, object], identity_field: str,
    *, schema_version: int, kind: str,
) -> dict[str, object]:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8") + b"\n"
    return {
        "artifact_schema_version": schema_version,
        "artifact_kind": kind,
        "descriptor": {
            "path": f"qualification/replay-v2/{label}.json",
            "size_bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        },
        "content_identity_sha256": value[identity_field],
    }


class Fixture:
    def __init__(self) -> None:
        self.q4_sha = sha("q4-input")
        self.validator_sha = sha("q4-validator")
        self.runner_sha = sha("runner")
        self.abi_sha = sha("abi-v3")
        self.invocation_sha = sha("runner-invocation")
        self.q4_ref = typed(
            "q4-input", 4, protocol.Q4_INPUT_KIND, self.q4_sha,
        )
        self.validator_ref = typed(
            "q4-validator", 1, protocol.Q4_VALIDATOR_KIND,
            self.validator_sha,
        )
        self.runner_ref = typed(
            "runner", 1, protocol.RUNNER_AUTHORITY_KIND, self.runner_sha,
        )
        self.abi_ref = typed("abi-v3", 3, protocol.ABI_V3_KIND, self.abi_sha)
        self.bindings = {system: sha(f"binding:{system}")
                         for system in protocol.SYSTEMS}
        self.sets = {system: sha(f"set:{system}")
                     for system in protocol.SYSTEMS}
        self.launcher_shas = {system: sha(f"launcher:{system}")
                              for system in protocol.SYSTEMS}
        self.launcher_refs = {
            system: typed(
                f"launcher-{system}", 1,
                protocol.LAUNCHER_RUNTIME_AUTHORITY_KIND,
                self.launcher_shas[system],
            )
            for system in protocol.SYSTEMS
        }

    def global_kwargs(self) -> dict[str, object]:
        return {
            "q4_input_ref": self.q4_ref,
            "q4_input_sha256": self.q4_sha,
            "q4_validator_authority_ref": self.validator_ref,
            "q4_validator_authority_sha256": self.validator_sha,
            "runner_authority_ref": self.runner_ref,
            "runner_authority_sha256": self.runner_sha,
            "publication_launcher_invocation_v3_ref": self.abi_ref,
            "publication_launcher_invocation_v3_sha256": self.abi_sha,
            "runner_invocation_identity_sha256": self.invocation_sha,
        }

    def system_kwargs(self, system: str) -> dict[str, object]:
        return {
            "runtime_binding_identity_v4_sha256": self.bindings[system],
            "runtime_authority_set_sha256": self.sets[system],
            "launcher_runtime_authority_ref": self.launcher_refs[system],
            "launcher_runtime_authority_sha256": self.launcher_shas[system],
        }

    def expected_global(self) -> dict[str, object]:
        return {f"expected_{key}": value
                for key, value in self.global_kwargs().items()}

    def expected_system(self, system: str) -> dict[str, object]:
        return {f"expected_{key}": value
                for key, value in self.system_kwargs(system).items()}

    def build_graph(self) -> tuple[list[dict[str, object]], dict[str, object]]:
        self.contexts: list[dict[str, object]] = []
        self.requests: list[dict[str, object]] = []
        self.records: list[dict[str, object]] = []
        shards: list[dict[str, object]] = []
        for system in protocol.SYSTEMS:
            context = protocol.build_backend_runtime_validation_system_context_v2(
                system=system, **self.global_kwargs(), **self.system_kwargs(system),
            )
            context_ref = persisted(
                f"context-{system}", context, "context_sha256",
                schema_version=2, kind=protocol.CONTEXT_KIND,
            )
            self.contexts.append(context)
            entries = []
            first = protocol.SYSTEMS.index(system) * 140
            for cell_index in range(first, first + 140):
                coordinate = protocol.coordinate_for_cell_index_v2(cell_index)
                authority_sha = sha(f"authority:{cell_index // 5}")
                authority_ref = typed(
                    f"authority-{cell_index // 5}", 2,
                    protocol.RUNTIME_AUTHORITY_KIND, authority_sha,
                )
                evidence_ref = ref(f"evidence-{cell_index}")
                request = protocol.build_backend_runtime_validation_request_v2(
                    **coordinate, context_ref=context_ref,
                    runtime_authority_ref=authority_ref,
                    runtime_authority_sha256=authority_sha,
                    raw_evidence_ref=evidence_ref,
                    **self.global_kwargs(), **self.system_kwargs(system),
                )
                request_ref = persisted(
                    f"request-{cell_index}", request, "request_sha256",
                    schema_version=2, kind=protocol.REQUEST_KIND,
                )
                self.requests.append(request)
                record = protocol.build_backend_runtime_validation_record_v2(
                    **coordinate, request_ref=request_ref,
                    runtime_authority_ref=authority_ref,
                    runtime_authority_sha256=authority_sha,
                    raw_evidence_ref=evidence_ref,
                    replay_result=protocol.QUALIFIED_REPLAY_RESULT,
                    **self.global_kwargs(), **self.system_kwargs(system),
                )
                entries.append({
                    **coordinate,
                    "validation_record_ref": persisted(
                        f"record-{cell_index}", record,
                        "validation_record_sha256", schema_version=2,
                        kind=protocol.RECORD_KIND,
                    ),
                })
                self.records.append(record)
            shard = protocol.build_backend_runtime_validation_system_shard_v2(
                system=system, context_ref=context_ref,
                validation_record_refs=entries,
                **self.global_kwargs(), **self.system_kwargs(system),
            )
            shards.append(shard)
        shard_refs = [
            persisted(
                f"shard-{shard['system']}", shard, "system_shard_sha256",
                schema_version=2, kind=protocol.SHARD_KIND,
            )
            for shard in shards
        ]
        index = protocol.build_backend_runtime_validation_index_v2(
            system_shards=shards, system_shard_refs=shard_refs,
            **self.global_kwargs(),
            expected_runtime_binding_identity_v4_sha256_by_system=self.bindings,
            expected_runtime_authority_set_sha256_by_system=self.sets,
            expected_launcher_runtime_authority_ref_by_system=self.launcher_refs,
            expected_launcher_runtime_authority_sha256_by_system=(
                self.launcher_shas
            ),
        )
        return shards, index


def resign_shard(
    shard: dict[str, object], shard_ref: dict[str, object],
) -> None:
    shard["validation_record_set_sha256"] = protocol.canonical_identity(
        shard["validation_record_refs"]
    )
    shard["system_shard_sha256"] = protocol.canonical_identity({
        key: value for key, value in shard.items()
        if key != "system_shard_sha256"
    })
    shard_ref["content_identity_sha256"] = shard["system_shard_sha256"]


class ValidationRecordProtocolV2Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.f = Fixture()
        cls.shards, cls.index = cls.f.build_graph()

    def test_exact_graph_and_flattened_commitment(self) -> None:
        self.assertEqual(protocol.SCHEMA_VERSION, 2)
        self.assertEqual(len(self.shards), 4)
        self.assertEqual(len(self.index["validation_records"]), 560)
        self.assertEqual(
            [item["coordinate"]["cell_index"]
             for item in self.index["validation_records"]], list(range(560)),
        )
        self.assertEqual(self.index["coverage"], {
            "system_count": 4, "cells_per_system": 140,
            "validation_record_count": 560,
        })
        self.assertIs(self.index["authorization_eligible"], False)
        self.assertIs(self.index["execution_authorized"], False)
        self.assertIs(self.index["validation_records_authenticated"], False)
        flattened = [item["validation_record_ref"]
                     for item in self.index["validation_records"]]
        self.assertEqual(len({item["descriptor"]["path"].casefold()
                              for item in flattened}), 560)
        self.assertEqual(len({item["descriptor"]["sha256"]
                              for item in flattened}), 560)
        self.assertEqual(len({item["content_identity_sha256"]
                              for item in flattened}), 560)

    def test_every_constructed_node_round_trips_its_closed_validator(self) -> None:
        for position, system in enumerate(protocol.SYSTEMS):
            context = self.f.contexts[position]
            protocol.validate_backend_runtime_validation_system_context_v2(
                context, expected_semantic_sha256=context["context_sha256"],
                expected_system=system, **self.f.expected_global(),
                **self.f.expected_system(system),
            )
            shard = self.shards[position]
            protocol.validate_backend_runtime_validation_system_shard_v2(
                shard,
                expected_semantic_sha256=shard["system_shard_sha256"],
                expected_system=system,
                expected_context_ref=shard["context_ref"],
                expected_validation_record_refs=shard["validation_record_refs"],
                **self.f.expected_global(), **self.f.expected_system(system),
            )
        for request in self.f.requests:
            coordinate = {
                field: request[field] for field in protocol.COORDINATE_FIELDS
            }
            system = coordinate["system"]
            protocol.validate_backend_runtime_validation_request_v2(
                request,
                expected_semantic_sha256=request["request_sha256"],
                expected_coordinate=coordinate,
                expected_context_ref=request["context_ref"],
                expected_runtime_authority_ref=request["runtime_authority_ref"],
                expected_runtime_authority_sha256=(
                    request["runtime_authority_sha256"]
                ),
                expected_raw_evidence_ref=request["raw_evidence_ref"],
                **self.f.expected_global(), **self.f.expected_system(system),
            )
        for record in self.f.records:
            coordinate = {
                field: record[field] for field in protocol.COORDINATE_FIELDS
            }
            system = coordinate["system"]
            protocol.validate_backend_runtime_validation_record_v2(
                record,
                expected_semantic_sha256=record["validation_record_sha256"],
                expected_coordinate=coordinate,
                expected_request_ref=record["request_ref"],
                expected_runtime_authority_ref=record["runtime_authority_ref"],
                expected_runtime_authority_sha256=(
                    record["runtime_authority_sha256"]
                ),
                expected_raw_evidence_ref=record["raw_evidence_ref"],
                **self.f.expected_global(), **self.f.expected_system(system),
            )
        protocol.validate_backend_runtime_validation_index_v2(
            self.index, expected_semantic_sha256=self.index["index_sha256"],
            expected_system_shards=self.shards,
            **self.f.expected_global(),
            expected_runtime_binding_identity_v4_sha256_by_system=(
                self.f.bindings
            ),
            expected_runtime_authority_set_sha256_by_system=self.f.sets,
            expected_launcher_runtime_authority_ref_by_system=(
                self.f.launcher_refs
            ),
            expected_launcher_runtime_authority_sha256_by_system=(
                self.f.launcher_shas
            ),
        )

    def test_typed_roots_and_abi_cross_binding_are_required(self) -> None:
        changed = copy.deepcopy(self.index)
        changed["publication_launcher_invocation_v3_ref"][
            "artifact_schema_version"
        ] = 2
        with self.assertRaises(protocol.BackendRuntimeValidationRecordV2Error):
            protocol.validate_backend_runtime_validation_index_v2(
                changed, expected_semantic_sha256=changed["index_sha256"],
                expected_system_shards=self.shards,
                **self.f.expected_global(),
                expected_runtime_binding_identity_v4_sha256_by_system=(
                    self.f.bindings
                ),
                expected_runtime_authority_set_sha256_by_system=self.f.sets,
                expected_launcher_runtime_authority_ref_by_system=(
                    self.f.launcher_refs
                ),
                expected_launcher_runtime_authority_sha256_by_system=(
                    self.f.launcher_shas
                ),
            )

    def test_external_system_pin_drift_is_rejected(self) -> None:
        bindings = copy.deepcopy(self.f.bindings)
        bindings["savant"] = sha("wrong-savant-binding")
        with self.assertRaises(protocol.BackendRuntimeValidationRecordV2Error):
            protocol.validate_backend_runtime_validation_index_v2(
                self.index, expected_semantic_sha256=self.index["index_sha256"],
                expected_system_shards=self.shards,
                **self.f.expected_global(),
                expected_runtime_binding_identity_v4_sha256_by_system=bindings,
                expected_runtime_authority_set_sha256_by_system=self.f.sets,
                expected_launcher_runtime_authority_ref_by_system=(
                    self.f.launcher_refs
                ),
                expected_launcher_runtime_authority_sha256_by_system=(
                    self.f.launcher_shas
                ),
            )

    def test_replay_result_rejects_integer_boolean_smuggling(self) -> None:
        base = self.f.records[0]
        coordinate = {
            field: base[field] for field in protocol.COORDINATE_FIELDS
        }
        system = coordinate["system"]
        for field in (
            "accepted", "synthetic", "nonpublication", "publication_capable",
            "deterministic_replay_completed",
        ):
            with self.subTest(field=field):
                result = copy.deepcopy(protocol.QUALIFIED_REPLAY_RESULT)
                result[field] = int(result[field])
                with self.assertRaises(
                    protocol.BackendRuntimeValidationRecordV2Error
                ):
                    protocol.build_backend_runtime_validation_record_v2(
                        **coordinate, request_ref=base["request_ref"],
                        runtime_authority_ref=base["runtime_authority_ref"],
                        runtime_authority_sha256=(
                            base["runtime_authority_sha256"]
                        ),
                        raw_evidence_ref=base["raw_evidence_ref"],
                        replay_result=result, **self.f.global_kwargs(),
                        **self.f.system_kwargs(system),
                    )

    def test_record_is_explicitly_nonauthorizing_and_bool_typed(self) -> None:
        for record in self.f.records:
            self.assertIs(record["authorization_eligible"], False)
            self.assertIs(record["execution_authorized"], False)
            self.assertIs(record["validation_records_authenticated"], False)
        changed = copy.deepcopy(self.f.records[0])
        changed["execution_authorized"] = 0
        coordinate = {
            field: changed[field] for field in protocol.COORDINATE_FIELDS
        }
        with self.assertRaises(protocol.BackendRuntimeValidationRecordV2Error):
            protocol.validate_backend_runtime_validation_record_v2(
                changed,
                expected_semantic_sha256=changed["validation_record_sha256"],
                expected_coordinate=coordinate,
                expected_request_ref=changed["request_ref"],
                expected_runtime_authority_ref=changed["runtime_authority_ref"],
                expected_runtime_authority_sha256=(
                    changed["runtime_authority_sha256"]
                ),
                expected_raw_evidence_ref=changed["raw_evidence_ref"],
                **self.f.expected_global(),
                **self.f.expected_system(coordinate["system"]),
            )

    def test_four_system_launcher_and_identity_maps_are_distinct(self) -> None:
        for pin_map_name in ("bindings", "sets", "launchers"):
            with self.subTest(pin_map=pin_map_name):
                shards = copy.deepcopy(self.shards)
                refs = [copy.deepcopy(item["system_shard_ref"])
                        for item in self.index["system_shards"]]
                pin_map = copy.deepcopy(
                    self.f.launcher_shas if pin_map_name == "launchers"
                    else getattr(self.f, pin_map_name)
                )
                pin_map["savant"] = pin_map["deepstream"]
                launcher_refs = copy.deepcopy(self.f.launcher_refs)
                launcher_shas = copy.deepcopy(self.f.launcher_shas)
                bindings = copy.deepcopy(self.f.bindings)
                sets = copy.deepcopy(self.f.sets)
                if pin_map_name == "bindings":
                    bindings = pin_map
                    shards[1]["runtime_binding_identity_v4_sha256"] = (
                        bindings["savant"]
                    )
                elif pin_map_name == "sets":
                    sets = pin_map
                    shards[1]["runtime_authority_set_sha256"] = sets["savant"]
                else:
                    launcher_refs["savant"] = copy.deepcopy(
                        launcher_refs["deepstream"]
                    )
                    launcher_shas["savant"] = launcher_shas["deepstream"]
                    shards[1]["launcher_runtime_authority_ref"] = (
                        copy.deepcopy(launcher_refs["savant"])
                    )
                    shards[1]["launcher_runtime_authority_sha256"] = (
                        launcher_shas["savant"]
                    )
                resign_shard(shards[1], refs[1])
                kwargs = {
                    "expected_runtime_binding_identity_v4_sha256_by_system": (
                        bindings
                    ),
                    "expected_runtime_authority_set_sha256_by_system": (
                        sets
                    ),
                    "expected_launcher_runtime_authority_ref_by_system": (
                        launcher_refs
                    ),
                    "expected_launcher_runtime_authority_sha256_by_system": (
                        launcher_shas
                    ),
                }
                with self.assertRaises(
                    protocol.BackendRuntimeValidationRecordV2Error
                ):
                    protocol.build_backend_runtime_validation_index_v2(
                        system_shards=shards, system_shard_refs=refs,
                        **self.f.global_kwargs(), **kwargs,
                    )

    def test_flattened_commitment_cannot_be_independently_resigned(self) -> None:
        changed = copy.deepcopy(self.index)
        changed["validation_records"][0], changed["validation_records"][1] = (
            changed["validation_records"][1], changed["validation_records"][0]
        )
        changed["validation_record_global_set_sha256"] = (
            protocol.canonical_identity(changed["validation_records"])
        )
        changed["index_sha256"] = protocol.canonical_identity({
            key: value for key, value in changed.items() if key != "index_sha256"
        })
        with self.assertRaises(protocol.BackendRuntimeValidationRecordV2Error):
            protocol.validate_backend_runtime_validation_index_v2(
                changed, expected_semantic_sha256=changed["index_sha256"],
                expected_system_shards=self.shards,
                **self.f.expected_global(),
                expected_runtime_binding_identity_v4_sha256_by_system=(
                    self.f.bindings
                ),
                expected_runtime_authority_set_sha256_by_system=self.f.sets,
                expected_launcher_runtime_authority_ref_by_system=(
                    self.f.launcher_refs
                ),
                expected_launcher_runtime_authority_sha256_by_system=(
                    self.f.launcher_shas
                ),
            )

    def test_validators_have_no_optional_trust_pins(self) -> None:
        validators = (
            protocol.validate_backend_runtime_validation_system_context_v2,
            protocol.validate_backend_runtime_validation_request_v2,
            protocol.validate_backend_runtime_validation_record_v2,
            protocol.validate_backend_runtime_validation_system_shard_v2,
            protocol.validate_backend_runtime_validation_index_v2,
        )
        for validator in validators:
            with self.subTest(validator=validator.__name__):
                parameters = inspect.signature(validator).parameters.values()
                self.assertTrue(all(
                    parameter.default is inspect.Parameter.empty
                    for parameter in parameters
                ))

    def test_index_validates_supplied_shard_documents(self) -> None:
        changed = copy.deepcopy(self.shards)
        changed[0]["validation_record_refs"][0]["cell_index"] = 1
        with self.assertRaises(protocol.BackendRuntimeValidationRecordV2Error):
            protocol.build_backend_runtime_validation_index_v2(
                system_shards=changed,
                system_shard_refs=[item["system_shard_ref"]
                                   for item in self.index["system_shards"]],
                **self.f.global_kwargs(),
                expected_runtime_binding_identity_v4_sha256_by_system=(
                    self.f.bindings
                ),
                expected_runtime_authority_set_sha256_by_system=self.f.sets,
                expected_launcher_runtime_authority_ref_by_system=(
                    self.f.launcher_refs
                ),
                expected_launcher_runtime_authority_sha256_by_system=(
                    self.f.launcher_shas
                ),
            )

    def test_shard_ref_semantic_must_equal_shard_sha(self) -> None:
        refs = [copy.deepcopy(item["system_shard_ref"])
                for item in self.index["system_shards"]]
        refs[0]["content_identity_sha256"] = sha("wrong-shard")
        with self.assertRaises(protocol.BackendRuntimeValidationRecordV2Error):
            protocol.build_backend_runtime_validation_index_v2(
                system_shards=self.shards, system_shard_refs=refs,
                **self.f.global_kwargs(),
                expected_runtime_binding_identity_v4_sha256_by_system=(
                    self.f.bindings
                ),
                expected_runtime_authority_set_sha256_by_system=self.f.sets,
                expected_launcher_runtime_authority_ref_by_system=(
                    self.f.launcher_refs
                ),
                expected_launcher_runtime_authority_sha256_by_system=(
                    self.f.launcher_shas
                ),
            )

    def test_flattened_record_refs_must_be_distinct(self) -> None:
        changed = copy.deepcopy(self.shards)
        changed[0]["validation_record_refs"][1]["validation_record_ref"] = (
            copy.deepcopy(changed[0]["validation_record_refs"][0][
                "validation_record_ref"
            ])
        )
        with self.assertRaises(protocol.BackendRuntimeValidationRecordV2Error):
            protocol.build_backend_runtime_validation_index_v2(
                system_shards=changed,
                system_shard_refs=[item["system_shard_ref"]
                                   for item in self.index["system_shards"]],
                **self.f.global_kwargs(),
                expected_runtime_binding_identity_v4_sha256_by_system=(
                    self.f.bindings
                ),
                expected_runtime_authority_set_sha256_by_system=self.f.sets,
                expected_launcher_runtime_authority_ref_by_system=(
                    self.f.launcher_refs
                ),
                expected_launcher_runtime_authority_sha256_by_system=(
                    self.f.launcher_shas
                ),
            )

    def test_casefold_path_collision_is_rejected_globally(self) -> None:
        changed = copy.deepcopy(self.shards)
        refs = [copy.deepcopy(item["system_shard_ref"])
                for item in self.index["system_shards"]]
        first = changed[0]["validation_record_refs"][0]["validation_record_ref"]
        second = changed[1]["validation_record_refs"][0]["validation_record_ref"]
        second["descriptor"]["path"] = first["descriptor"]["path"].upper()
        resign_shard(changed[1], refs[1])
        with self.assertRaises(protocol.BackendRuntimeValidationRecordV2Error):
            protocol.build_backend_runtime_validation_index_v2(
                system_shards=changed,
                system_shard_refs=refs,
                **self.f.global_kwargs(),
                expected_runtime_binding_identity_v4_sha256_by_system=(
                    self.f.bindings
                ),
                expected_runtime_authority_set_sha256_by_system=self.f.sets,
                expected_launcher_runtime_authority_ref_by_system=(
                    self.f.launcher_refs
                ),
                expected_launcher_runtime_authority_sha256_by_system=(
                    self.f.launcher_shas
                ),
            )

    def test_global_file_content_and_cycle_collisions_are_rejected(self) -> None:
        for mutation in ("file", "content", "cycle"):
            with self.subTest(mutation=mutation):
                changed = copy.deepcopy(self.shards)
                refs = [copy.deepcopy(item["system_shard_ref"])
                        for item in self.index["system_shards"]]
                first = changed[0]["validation_record_refs"][0][
                    "validation_record_ref"
                ]
                second = changed[1]["validation_record_refs"][0][
                    "validation_record_ref"
                ]
                if mutation == "file":
                    second["descriptor"]["sha256"] = (
                        first["descriptor"]["sha256"]
                    )
                elif mutation == "content":
                    second["content_identity_sha256"] = (
                        first["content_identity_sha256"]
                    )
                else:
                    second["content_identity_sha256"] = changed[1][
                        "context_sha256"
                    ]
                resign_shard(changed[1], refs[1])
                with self.assertRaises(
                    protocol.BackendRuntimeValidationRecordV2Error
                ):
                    protocol.build_backend_runtime_validation_index_v2(
                        system_shards=changed, system_shard_refs=refs,
                        **self.f.global_kwargs(),
                        expected_runtime_binding_identity_v4_sha256_by_system=(
                            self.f.bindings
                        ),
                        expected_runtime_authority_set_sha256_by_system=(
                            self.f.sets
                        ),
                        expected_launcher_runtime_authority_ref_by_system=(
                            self.f.launcher_refs
                        ),
                        expected_launcher_runtime_authority_sha256_by_system=(
                            self.f.launcher_shas
                        ),
                    )

    def test_four_context_refs_must_be_distinct(self) -> None:
        changed = copy.deepcopy(self.shards)
        refs = [copy.deepcopy(item["system_shard_ref"])
                for item in self.index["system_shards"]]
        changed[1]["context_ref"] = copy.deepcopy(changed[0]["context_ref"])
        changed[1]["context_sha256"] = changed[0]["context_sha256"]
        resign_shard(changed[1], refs[1])
        with self.assertRaises(protocol.BackendRuntimeValidationRecordV2Error):
            protocol.build_backend_runtime_validation_index_v2(
                system_shards=changed, system_shard_refs=refs,
                **self.f.global_kwargs(),
                expected_runtime_binding_identity_v4_sha256_by_system=(
                    self.f.bindings
                ),
                expected_runtime_authority_set_sha256_by_system=self.f.sets,
                expected_launcher_runtime_authority_ref_by_system=(
                    self.f.launcher_refs
                ),
                expected_launcher_runtime_authority_sha256_by_system=(
                    self.f.launcher_shas
                ),
            )

    def test_parent_binding_and_deadline_type_drift_are_rejected(self) -> None:
        context = protocol.build_backend_runtime_validation_system_context_v2(
            system="deepstream", **self.f.global_kwargs(),
            **self.f.system_kwargs("deepstream"),
        )
        context_ref = persisted(
            "isolated-context", context, "context_sha256",
            schema_version=2, kind=protocol.CONTEXT_KIND,
        )
        coordinate = protocol.coordinate_for_cell_index_v2(2)
        coordinate["deadline_ms"] = 50.0
        with self.assertRaises(protocol.BackendRuntimeValidationRecordV2Error):
            protocol.build_backend_runtime_validation_request_v2(
                **coordinate, context_ref=context_ref,
                runtime_authority_ref=typed(
                    "isolated-authority", 2, protocol.RUNTIME_AUTHORITY_KIND,
                    sha("isolated-authority"),
                ),
                runtime_authority_sha256=sha("isolated-authority"),
                raw_evidence_ref=ref("isolated-evidence"),
                **self.f.global_kwargs(), **self.f.system_kwargs("deepstream"),
            )
        wrong = copy.deepcopy(context)
        wrong["q4_input_sha256"] = sha("wrong-parent")
        with self.assertRaises(protocol.BackendRuntimeValidationRecordV2Error):
            protocol.validate_backend_runtime_validation_system_context_v2(
                wrong, expected_semantic_sha256=context["context_sha256"],
                expected_system="deepstream", **self.f.expected_global(),
                **self.f.expected_system("deepstream"),
            )

    def test_v1_rejects_v2_and_module_has_no_side_effect_surfaces(self) -> None:
        with self.assertRaises(legacy.BackendRuntimeValidationRecordError):
            legacy.validate_backend_runtime_validation_index(
                self.index,
                expected_semantic_sha256=self.index["index_sha256"],
                expected_qualification_index_ref=ref("legacy"),
                expected_qualification_index_sha256=sha("legacy"),
                expected_upstream_identities={
                    key: sha(key) for key in legacy.UPSTREAM_IDENTITY_FIELDS
                },
                expected_validator_authority_ref=ref("legacy-validator"),
                expected_validator_authority_sha256=sha("legacy-validator"),
                expected_runner_authority_ref=ref("legacy-runner"),
                expected_runner_authority_sha256=sha("legacy-runner"),
                expected_runner_invocation_identity_sha256=sha("legacy-i"),
                expected_validation_protocol_identity_sha256=sha("legacy-p"),
                expected_input_schema_identity_sha256=sha("legacy-in"),
                expected_output_schema_identity_sha256=sha("legacy-out"),
                expected_system_shard_refs=[],
                expected_system_shard_set_sha256=sha("legacy-ss"),
                expected_validation_record_global_set_sha256=sha("legacy-rs"),
            )
        source = inspect.getsource(protocol)
        tree = ast.parse(source)
        imports = {
            alias.name.split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import) for alias in node.names
        } | {
            node.module.split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        self.assertTrue(imports <= {
            "__future__", "copy", "hashlib", "json", "math", "re", "typing",
        })
        for forbidden in (
            "subprocess", "socket", "requests", "pathlib", "callback",
            "grant", "readiness", "open(", "exec(", "eval(", "compile(",
        ):
            self.assertNotIn(forbidden, source.lower())


if __name__ == "__main__":
    unittest.main()
