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

import backend_runtime_validation_records as protocol  # noqa: E402


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def sha(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def artifact_ref(label: str, semantic_sha: str | None = None) -> dict[str, object]:
    payload = (label + "\n").encode("utf-8")
    return {
        "descriptor": {
            "path": f"qualification/replay/{label}.json",
            "size_bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        },
        "content_identity_sha256": semantic_sha or sha(f"semantic:{label}"),
    }


def persisted_ref(label: str, value: dict[str, object], semantic_field: str) -> dict[str, object]:
    payload = canonical_bytes(value) + b"\n"
    return {
        "descriptor": {
            "path": f"qualification/replay/{label}.json",
            "size_bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        },
        "content_identity_sha256": value[semantic_field],
    }


class ValidationReplayFixture:
    def __init__(self) -> None:
        self.upstream = {
            name: sha(name)
            for name in protocol.UPSTREAM_IDENTITY_FIELDS
        }
        self.qualification_index_sha256 = sha("qualification-index")
        self.qualification_index_ref = artifact_ref(
            "qualification-index", self.qualification_index_sha256,
        )
        self.validator_authority_sha256 = sha("validator-authority")
        self.validator_authority_ref = artifact_ref(
            "validator-authority", self.validator_authority_sha256,
        )
        self.runner_authority_sha256 = sha("runner-authority")
        self.runner_authority_ref = artifact_ref(
            "runner-authority", self.runner_authority_sha256,
        )
        self.runner_invocation_identity_sha256 = sha("runner-invocation")
        self.validation_protocol_identity_sha256 = sha("validation-protocol")
        self.input_schema_identity_sha256 = sha("input-schema")
        self.output_schema_identity_sha256 = sha("output-schema")

    def context_kwargs(self, system: str) -> dict[str, object]:
        return {
            "system": system,
            "qualification_index_ref": self.qualification_index_ref,
            "qualification_index_sha256": self.qualification_index_sha256,
            "upstream_identities": self.upstream,
            "runtime_binding_identity_sha256": sha(f"binding:{system}"),
            "runtime_authority_set_sha256": sha(f"authority-set:{system}"),
            "validator_authority_ref": self.validator_authority_ref,
            "validator_authority_sha256": self.validator_authority_sha256,
            "runner_authority_ref": self.runner_authority_ref,
            "runner_authority_sha256": self.runner_authority_sha256,
            "runner_invocation_identity_sha256": self.runner_invocation_identity_sha256,
            "validation_protocol_identity_sha256": self.validation_protocol_identity_sha256,
            "input_schema_identity_sha256": self.input_schema_identity_sha256,
            "output_schema_identity_sha256": self.output_schema_identity_sha256,
        }

    def context_expected(self, context: dict[str, object]) -> dict[str, object]:
        return {
            "expected_semantic_sha256": context["context_sha256"],
            "expected_system": context["system"],
            "expected_qualification_index_ref": self.qualification_index_ref,
            "expected_qualification_index_sha256": self.qualification_index_sha256,
            "expected_upstream_identities": self.upstream,
            "expected_runtime_binding_identity_sha256": context["runtime_binding_identity_sha256"],
            "expected_runtime_authority_set_sha256": context["runtime_authority_set_sha256"],
            "expected_validator_authority_ref": self.validator_authority_ref,
            "expected_validator_authority_sha256": self.validator_authority_sha256,
            "expected_runner_authority_ref": self.runner_authority_ref,
            "expected_runner_authority_sha256": self.runner_authority_sha256,
            "expected_runner_invocation_identity_sha256": self.runner_invocation_identity_sha256,
            "expected_validation_protocol_identity_sha256": self.validation_protocol_identity_sha256,
            "expected_input_schema_identity_sha256": self.input_schema_identity_sha256,
            "expected_output_schema_identity_sha256": self.output_schema_identity_sha256,
        }

    def coordinate(self, cell_index: int) -> dict[str, object]:
        per_system = (
            len(protocol.CODECS) * len(protocol.TOPOLOGIES)
            * len(protocol.POLICIES) * len(protocol.DEADLINES_MS)
        )
        system_index, local = divmod(cell_index, per_system)
        codec_index, local = divmod(
            local,
            len(protocol.TOPOLOGIES) * len(protocol.POLICIES)
            * len(protocol.DEADLINES_MS),
        )
        topology_index, local = divmod(
            local, len(protocol.POLICIES) * len(protocol.DEADLINES_MS),
        )
        policy_index, deadline_index = divmod(local, len(protocol.DEADLINES_MS))
        return {
            "system": protocol.SYSTEMS[system_index],
            "codec": protocol.CODECS[codec_index],
            "topology_kind": protocol.TOPOLOGIES[topology_index],
            "policy": protocol.POLICIES[policy_index],
            "deadline_ms": protocol.DEADLINES_MS[deadline_index],
            "cell_index": cell_index,
        }

    def request_kwargs(
        self, context_ref: dict[str, object], context: dict[str, object],
        coordinate: dict[str, object],
    ) -> dict[str, object]:
        authority_key = "-".join(str(coordinate[name]) for name in (
            "system", "codec", "topology_kind", "policy",
        ))
        runtime_authority_sha256 = sha(f"runtime-authority:{authority_key}")
        return {
            **coordinate,
            "context_ref": context_ref,
            "context_sha256": context["context_sha256"],
            "qualification_index_sha256": self.qualification_index_sha256,
            "upstream_identities": self.upstream,
            "runtime_binding_identity_sha256": context["runtime_binding_identity_sha256"],
            "runtime_authority_set_sha256": context["runtime_authority_set_sha256"],
            "runtime_authority_ref": artifact_ref(
                f"authority-{authority_key}", runtime_authority_sha256,
            ),
            "runtime_authority_sha256": runtime_authority_sha256,
            "raw_evidence_ref": artifact_ref(f"raw-{coordinate['cell_index']}"),
            "validator_authority_sha256": self.validator_authority_sha256,
            "runner_authority_sha256": self.runner_authority_sha256,
            "runner_invocation_identity_sha256": self.runner_invocation_identity_sha256,
            "validation_protocol_identity_sha256": self.validation_protocol_identity_sha256,
            "input_schema_identity_sha256": self.input_schema_identity_sha256,
            "output_schema_identity_sha256": self.output_schema_identity_sha256,
        }

    def request_expected(self, request: dict[str, object]) -> dict[str, object]:
        return {
            "expected_semantic_sha256": request["request_sha256"],
            "expected_context_ref": request["context_ref"],
            "expected_context_sha256": request["context_sha256"],
            "expected_coordinate": {
                name: request[name] for name in protocol.COORDINATE_FIELDS
            },
            "expected_qualification_index_sha256": self.qualification_index_sha256,
            "expected_upstream_identities": self.upstream,
            "expected_runtime_binding_identity_sha256": request["runtime_binding_identity_sha256"],
            "expected_runtime_authority_set_sha256": request["runtime_authority_set_sha256"],
            "expected_runtime_authority_ref": request["runtime_authority_ref"],
            "expected_runtime_authority_sha256": request["runtime_authority_sha256"],
            "expected_raw_evidence_ref": request["raw_evidence_ref"],
            "expected_validator_authority_sha256": self.validator_authority_sha256,
            "expected_runner_authority_sha256": self.runner_authority_sha256,
            "expected_runner_invocation_identity_sha256": self.runner_invocation_identity_sha256,
            "expected_validation_protocol_identity_sha256": self.validation_protocol_identity_sha256,
            "expected_input_schema_identity_sha256": self.input_schema_identity_sha256,
            "expected_output_schema_identity_sha256": self.output_schema_identity_sha256,
        }

    def record_kwargs(
        self, request_ref: dict[str, object], request: dict[str, object],
    ) -> dict[str, object]:
        return {
            **{name: request[name] for name in protocol.COORDINATE_FIELDS},
            "request_ref": request_ref,
            "request_sha256": request["request_sha256"],
            "qualification_index_sha256": self.qualification_index_sha256,
            "upstream_identities": self.upstream,
            "raw_evidence_ref": request["raw_evidence_ref"],
            "runtime_authority_ref": request["runtime_authority_ref"],
            "runtime_authority_sha256": request["runtime_authority_sha256"],
            "validator_authority_ref": self.validator_authority_ref,
            "validator_authority_sha256": self.validator_authority_sha256,
            "runner_authority_ref": self.runner_authority_ref,
            "runner_authority_sha256": self.runner_authority_sha256,
            "runner_invocation_identity_sha256": self.runner_invocation_identity_sha256,
            "validation_protocol_identity_sha256": self.validation_protocol_identity_sha256,
            "input_schema_identity_sha256": self.input_schema_identity_sha256,
            "output_schema_identity_sha256": self.output_schema_identity_sha256,
            "replay_result": {
                "record_status": "qualified",
                "accepted": True,
                "synthetic": False,
                "nonpublication": False,
                "publication_capable": True,
                "deterministic_replay_completed": True,
                "blocker_codes": [],
            },
        }

    def record_expected(self, record: dict[str, object]) -> dict[str, object]:
        return {
            "expected_semantic_sha256": record["validation_record_sha256"],
            "expected_request_ref": record["request_ref"],
            "expected_request_sha256": record["request_sha256"],
            "expected_coordinate": {
                name: record[name] for name in protocol.COORDINATE_FIELDS
            },
            "expected_qualification_index_sha256": self.qualification_index_sha256,
            "expected_upstream_identities": self.upstream,
            "expected_raw_evidence_ref": record["raw_evidence_ref"],
            "expected_runtime_authority_ref": record["runtime_authority_ref"],
            "expected_runtime_authority_sha256": record["runtime_authority_sha256"],
            "expected_validator_authority_ref": self.validator_authority_ref,
            "expected_validator_authority_sha256": self.validator_authority_sha256,
            "expected_runner_authority_ref": self.runner_authority_ref,
            "expected_runner_authority_sha256": self.runner_authority_sha256,
            "expected_runner_invocation_identity_sha256": self.runner_invocation_identity_sha256,
            "expected_validation_protocol_identity_sha256": self.validation_protocol_identity_sha256,
            "expected_input_schema_identity_sha256": self.input_schema_identity_sha256,
            "expected_output_schema_identity_sha256": self.output_schema_identity_sha256,
        }


class BackendRuntimeValidationRecordProtocolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = ValidationReplayFixture()

    def _full_graph(self) -> tuple[dict[str, object], list[dict[str, object]]]:
        shard_entries: list[dict[str, object]] = []
        records: list[dict[str, object]] = []
        for system_index, system in enumerate(protocol.SYSTEMS):
            context = protocol.build_backend_runtime_validation_system_context(
                **self.fixture.context_kwargs(system),
            )
            self.assertEqual(
                protocol.validate_backend_runtime_validation_system_context(
                    context, **self.fixture.context_expected(context),
                ),
                context,
            )
            context_ref = persisted_ref(
                f"context-{system}", context, "context_sha256",
            )
            record_entries: list[dict[str, object]] = []
            for cell_index in range(system_index * 140, (system_index + 1) * 140):
                coordinate = self.fixture.coordinate(cell_index)
                request = protocol.build_backend_runtime_validation_request(
                    **self.fixture.request_kwargs(context_ref, context, coordinate),
                )
                protocol.validate_backend_runtime_validation_request(
                    request, **self.fixture.request_expected(request),
                )
                request_ref = persisted_ref(
                    f"request-{cell_index}", request, "request_sha256",
                )
                record = protocol.build_backend_runtime_validation_record(
                    **self.fixture.record_kwargs(request_ref, request),
                )
                protocol.validate_backend_runtime_validation_record(
                    record, **self.fixture.record_expected(record),
                )
                record_ref = persisted_ref(
                    f"record-{cell_index}", record, "validation_record_sha256",
                )
                record_entries.append({
                    **coordinate,
                    "validation_record_ref": record_ref,
                })
                records.append(record)
            shard = protocol.build_backend_runtime_validation_system_shard(
                system=system,
                context_ref=context_ref,
                context_sha256=context["context_sha256"],
                validation_record_refs=record_entries,
            )
            protocol.validate_backend_runtime_validation_system_shard(
                shard,
                expected_semantic_sha256=shard["system_shard_sha256"],
                expected_system=system,
                expected_context_ref=context_ref,
                expected_context_sha256=context["context_sha256"],
                expected_validation_record_refs=record_entries,
                expected_validation_record_set_sha256=shard[
                    "validation_record_set_sha256"
                ],
            )
            shard_entries.append({
                "system": system,
                "system_shard_ref": persisted_ref(
                    f"shard-{system}", shard, "system_shard_sha256",
                ),
                "validation_record_set_sha256": shard[
                    "validation_record_set_sha256"
                ],
            })
        index = protocol.build_backend_runtime_validation_index(
            qualification_index_ref=self.fixture.qualification_index_ref,
            qualification_index_sha256=self.fixture.qualification_index_sha256,
            upstream_identities=self.fixture.upstream,
            validator_authority_ref=self.fixture.validator_authority_ref,
            validator_authority_sha256=self.fixture.validator_authority_sha256,
            runner_authority_ref=self.fixture.runner_authority_ref,
            runner_authority_sha256=self.fixture.runner_authority_sha256,
            runner_invocation_identity_sha256=self.fixture.runner_invocation_identity_sha256,
            validation_protocol_identity_sha256=self.fixture.validation_protocol_identity_sha256,
            input_schema_identity_sha256=self.fixture.input_schema_identity_sha256,
            output_schema_identity_sha256=self.fixture.output_schema_identity_sha256,
            system_shard_refs=shard_entries,
        )
        protocol.validate_backend_runtime_validation_index(
            index,
            expected_semantic_sha256=index["index_sha256"],
            expected_qualification_index_ref=self.fixture.qualification_index_ref,
            expected_qualification_index_sha256=self.fixture.qualification_index_sha256,
            expected_upstream_identities=self.fixture.upstream,
            expected_validator_authority_ref=self.fixture.validator_authority_ref,
            expected_validator_authority_sha256=self.fixture.validator_authority_sha256,
            expected_runner_authority_ref=self.fixture.runner_authority_ref,
            expected_runner_authority_sha256=self.fixture.runner_authority_sha256,
            expected_runner_invocation_identity_sha256=self.fixture.runner_invocation_identity_sha256,
            expected_validation_protocol_identity_sha256=self.fixture.validation_protocol_identity_sha256,
            expected_input_schema_identity_sha256=self.fixture.input_schema_identity_sha256,
            expected_output_schema_identity_sha256=self.fixture.output_schema_identity_sha256,
            expected_system_shard_refs=shard_entries,
            expected_system_shard_set_sha256=index["system_shard_set_sha256"],
            expected_validation_record_global_set_sha256=index[
                "validation_record_global_set_sha256"
            ],
        )
        return index, records

    def test_exact_full_560_record_replay_graph_is_closed_and_nonauthorizing(self) -> None:
        index, records = self._full_graph()
        self.assertEqual(len(records), 560)
        self.assertEqual([record["cell_index"] for record in records], list(range(560)))
        self.assertEqual(index["coverage"], {
            "system_count": 4,
            "cells_per_system": 140,
            "validation_record_count": 560,
        })
        self.assertEqual(index["status"], "persisted_for_deterministic_replay")
        for field in (
            "authorization_eligible", "execution_authorized",
            "validation_records_authenticated",
        ):
            self.assertIs(index[field], False)

    def test_context_rejects_self_consistent_attacker_authority_without_external_pin(self) -> None:
        context = protocol.build_backend_runtime_validation_system_context(
            **self.fixture.context_kwargs("deepstream"),
        )
        changed = copy.deepcopy(context)
        changed["validator_authority_sha256"] = sha("attacker-validator")
        changed["validator_authority_ref"] = artifact_ref(
            "attacker-validator", changed["validator_authority_sha256"],
        )
        changed["context_sha256"] = protocol.canonical_identity(
            {key: value for key, value in changed.items() if key != "context_sha256"}
        )
        expected = self.fixture.context_expected(context)
        expected["expected_semantic_sha256"] = changed["context_sha256"]
        with self.assertRaises(protocol.BackendRuntimeValidationRecordError):
            protocol.validate_backend_runtime_validation_system_context(
                changed, **expected,
            )

    def test_request_rejects_wrong_global_ordinal_and_deadline_numeric_type_drift(self) -> None:
        context = protocol.build_backend_runtime_validation_system_context(
            **self.fixture.context_kwargs("deepstream"),
        )
        context_ref = persisted_ref("context", context, "context_sha256")
        coordinate = self.fixture.coordinate(2)
        request = protocol.build_backend_runtime_validation_request(
            **self.fixture.request_kwargs(context_ref, context, coordinate),
        )
        for mutation in ("cell_index", "deadline_ms"):
            changed = copy.deepcopy(request)
            if mutation == "cell_index":
                changed[mutation] = 3
            else:
                changed[mutation] = 50.0
            changed["request_sha256"] = protocol.canonical_identity({
                key: value for key, value in changed.items() if key != "request_sha256"
            })
            expected = self.fixture.request_expected(changed)
            with self.assertRaises(protocol.BackendRuntimeValidationRecordError):
                protocol.validate_backend_runtime_validation_request(changed, **expected)

    def test_qualified_record_rejects_failure_flags_unknown_and_downstream_fields(self) -> None:
        context = protocol.build_backend_runtime_validation_system_context(
            **self.fixture.context_kwargs("deepstream"),
        )
        context_ref = persisted_ref("context", context, "context_sha256")
        request = protocol.build_backend_runtime_validation_request(
            **self.fixture.request_kwargs(
                context_ref, context, self.fixture.coordinate(0),
            ),
        )
        record = protocol.build_backend_runtime_validation_record(
            **self.fixture.record_kwargs(
                persisted_ref("request", request, "request_sha256"), request,
            ),
        )
        for mutation in ("accepted", "unknown", "downstream"):
            changed = copy.deepcopy(record)
            if mutation == "accepted":
                changed["replay_result"]["accepted"] = False
            elif mutation == "unknown":
                changed["replay_result"]["diagnostic"] = "untrusted"
            else:
                changed["backend_grant_sha256"] = sha("forbidden-cycle")
            changed["validation_record_sha256"] = protocol.canonical_identity({
                key: value for key, value in changed.items()
                if key != "validation_record_sha256"
            })
            expected = self.fixture.record_expected(changed)
            with self.assertRaises(protocol.BackendRuntimeValidationRecordError):
                protocol.validate_backend_runtime_validation_record(changed, **expected)

    def test_shard_rejects_swapped_or_incomplete_order(self) -> None:
        entries = []
        for index in range(140):
            entries.append({
                **self.fixture.coordinate(index),
                "validation_record_ref": artifact_ref(f"record-{index}"),
            })
        context_ref = artifact_ref("context", sha("context"))
        for changed in (list(reversed(entries)), entries[:-1]):
            with self.assertRaises(protocol.BackendRuntimeValidationRecordError):
                protocol.build_backend_runtime_validation_system_shard(
                    system="deepstream",
                    context_ref=context_ref,
                    context_sha256=sha("context"),
                    validation_record_refs=changed,
                )

    def test_shard_rejects_duplicate_record_reference_identity(self) -> None:
        original_entries = [{
            **self.fixture.coordinate(index),
            "validation_record_ref": artifact_ref(f"record-{index}"),
        } for index in range(140)]
        for identity_field in ("path", "file_sha256", "content_identity_sha256"):
            entries = copy.deepcopy(original_entries)
            source = entries[0]["validation_record_ref"]
            target = entries[1]["validation_record_ref"]
            if identity_field == "path":
                target["descriptor"]["path"] = source["descriptor"]["path"]
            elif identity_field == "file_sha256":
                target["descriptor"]["sha256"] = source["descriptor"]["sha256"]
            else:
                target["content_identity_sha256"] = source[
                    "content_identity_sha256"
                ]
            with self.subTest(identity_field=identity_field):
                with self.assertRaises(protocol.BackendRuntimeValidationRecordError):
                    protocol.build_backend_runtime_validation_system_shard(
                        system="deepstream",
                        context_ref=artifact_ref("context", sha("context")),
                        context_sha256=sha("context"),
                        validation_record_refs=entries,
                    )

    def test_shard_and_index_reject_resealed_semantic_reference_rebinding(self) -> None:
        entries = [{
            **self.fixture.coordinate(index),
            "validation_record_ref": artifact_ref(f"record-{index}"),
        } for index in range(140)]
        context_ref = artifact_ref("context", sha("context"))
        shard = protocol.build_backend_runtime_validation_system_shard(
            system="deepstream", context_ref=context_ref,
            context_sha256=sha("context"), validation_record_refs=entries,
        )
        changed = copy.deepcopy(shard)
        changed["context_ref"]["content_identity_sha256"] = sha("attacker-context")
        changed["system_shard_sha256"] = protocol.canonical_identity({
            key: value for key, value in changed.items()
            if key != "system_shard_sha256"
        })
        with self.assertRaises(protocol.BackendRuntimeValidationRecordError):
            protocol.validate_backend_runtime_validation_system_shard(
                changed, expected_semantic_sha256=changed["system_shard_sha256"],
                expected_system="deepstream", expected_context_ref=changed["context_ref"],
                expected_context_sha256=sha("context"),
                expected_validation_record_refs=entries,
                expected_validation_record_set_sha256=shard[
                    "validation_record_set_sha256"
                ],
            )

        shard_entries = [{
            "system": system,
            "system_shard_ref": artifact_ref(f"shard-{system}"),
            "validation_record_set_sha256": sha(f"records-{system}"),
        } for system in protocol.SYSTEMS]
        index = protocol.build_backend_runtime_validation_index(
            qualification_index_ref=self.fixture.qualification_index_ref,
            qualification_index_sha256=self.fixture.qualification_index_sha256,
            upstream_identities=self.fixture.upstream,
            validator_authority_ref=self.fixture.validator_authority_ref,
            validator_authority_sha256=self.fixture.validator_authority_sha256,
            runner_authority_ref=self.fixture.runner_authority_ref,
            runner_authority_sha256=self.fixture.runner_authority_sha256,
            runner_invocation_identity_sha256=self.fixture.runner_invocation_identity_sha256,
            validation_protocol_identity_sha256=self.fixture.validation_protocol_identity_sha256,
            input_schema_identity_sha256=self.fixture.input_schema_identity_sha256,
            output_schema_identity_sha256=self.fixture.output_schema_identity_sha256,
            system_shard_refs=shard_entries,
        )
        changed = copy.deepcopy(index)
        changed["runner_authority_ref"]["content_identity_sha256"] = sha("attacker-runner")
        changed["index_sha256"] = protocol.canonical_identity({
            key: value for key, value in changed.items() if key != "index_sha256"
        })
        with self.assertRaises(protocol.BackendRuntimeValidationRecordError):
            protocol.validate_backend_runtime_validation_index(
                changed, expected_semantic_sha256=changed["index_sha256"],
                expected_qualification_index_ref=self.fixture.qualification_index_ref,
                expected_qualification_index_sha256=self.fixture.qualification_index_sha256,
                expected_upstream_identities=self.fixture.upstream,
                expected_validator_authority_ref=self.fixture.validator_authority_ref,
                expected_validator_authority_sha256=self.fixture.validator_authority_sha256,
                expected_runner_authority_ref=changed["runner_authority_ref"],
                expected_runner_authority_sha256=self.fixture.runner_authority_sha256,
                expected_runner_invocation_identity_sha256=self.fixture.runner_invocation_identity_sha256,
                expected_validation_protocol_identity_sha256=self.fixture.validation_protocol_identity_sha256,
                expected_input_schema_identity_sha256=self.fixture.input_schema_identity_sha256,
                expected_output_schema_identity_sha256=self.fixture.output_schema_identity_sha256,
                expected_system_shard_refs=shard_entries,
                expected_system_shard_set_sha256=index["system_shard_set_sha256"],
                expected_validation_record_global_set_sha256=index[
                    "validation_record_global_set_sha256"
                ],
            )

    def test_index_rejects_wrong_system_order_set_hash_and_authorizing_claim(self) -> None:
        shard_entries = [
            {
                "system": system,
                "system_shard_ref": artifact_ref(f"shard-{system}"),
                "validation_record_set_sha256": sha(f"records-{system}"),
            }
            for system in protocol.SYSTEMS
        ]
        index = protocol.build_backend_runtime_validation_index(
            qualification_index_ref=self.fixture.qualification_index_ref,
            qualification_index_sha256=self.fixture.qualification_index_sha256,
            upstream_identities=self.fixture.upstream,
            validator_authority_ref=self.fixture.validator_authority_ref,
            validator_authority_sha256=self.fixture.validator_authority_sha256,
            runner_authority_ref=self.fixture.runner_authority_ref,
            runner_authority_sha256=self.fixture.runner_authority_sha256,
            runner_invocation_identity_sha256=self.fixture.runner_invocation_identity_sha256,
            validation_protocol_identity_sha256=self.fixture.validation_protocol_identity_sha256,
            input_schema_identity_sha256=self.fixture.input_schema_identity_sha256,
            output_schema_identity_sha256=self.fixture.output_schema_identity_sha256,
            system_shard_refs=shard_entries,
        )
        for mutation in ("order", "set_hash", "authorization"):
            changed = copy.deepcopy(index)
            if mutation == "order":
                changed["system_shards"] = list(reversed(changed["system_shards"]))
            elif mutation == "set_hash":
                changed["system_shard_set_sha256"] = sha("attacker-set")
            else:
                changed["execution_authorized"] = True
            changed["index_sha256"] = protocol.canonical_identity({
                key: value for key, value in changed.items() if key != "index_sha256"
            })
            with self.assertRaises(protocol.BackendRuntimeValidationRecordError):
                protocol.validate_backend_runtime_validation_index(
                    changed,
                    expected_semantic_sha256=changed["index_sha256"],
                    expected_qualification_index_ref=self.fixture.qualification_index_ref,
                    expected_qualification_index_sha256=self.fixture.qualification_index_sha256,
                    expected_upstream_identities=self.fixture.upstream,
                    expected_validator_authority_ref=self.fixture.validator_authority_ref,
                    expected_validator_authority_sha256=self.fixture.validator_authority_sha256,
                    expected_runner_authority_ref=self.fixture.runner_authority_ref,
                    expected_runner_authority_sha256=self.fixture.runner_authority_sha256,
                    expected_runner_invocation_identity_sha256=self.fixture.runner_invocation_identity_sha256,
                    expected_validation_protocol_identity_sha256=self.fixture.validation_protocol_identity_sha256,
                    expected_input_schema_identity_sha256=self.fixture.input_schema_identity_sha256,
                    expected_output_schema_identity_sha256=self.fixture.output_schema_identity_sha256,
                    expected_system_shard_refs=shard_entries,
                    expected_system_shard_set_sha256=index["system_shard_set_sha256"],
                    expected_validation_record_global_set_sha256=index[
                        "validation_record_global_set_sha256"
                    ],
                )

    def test_index_rejects_duplicate_system_shard_reference_identity(self) -> None:
        original_shards = [{
            "system": system,
            "system_shard_ref": artifact_ref(f"shard-{system}"),
            "validation_record_set_sha256": sha(f"records-{system}"),
        } for system in protocol.SYSTEMS]
        for identity_field in ("path", "file_sha256", "content_identity_sha256"):
            shard_entries = copy.deepcopy(original_shards)
            source = shard_entries[0]["system_shard_ref"]
            target = shard_entries[1]["system_shard_ref"]
            if identity_field == "path":
                target["descriptor"]["path"] = source["descriptor"]["path"]
            elif identity_field == "file_sha256":
                target["descriptor"]["sha256"] = source["descriptor"]["sha256"]
            else:
                target["content_identity_sha256"] = source[
                    "content_identity_sha256"
                ]
            with self.subTest(identity_field=identity_field):
                with self.assertRaises(protocol.BackendRuntimeValidationRecordError):
                    protocol.build_backend_runtime_validation_index(
                        qualification_index_ref=self.fixture.qualification_index_ref,
                        qualification_index_sha256=self.fixture.qualification_index_sha256,
                        upstream_identities=self.fixture.upstream,
                        validator_authority_ref=self.fixture.validator_authority_ref,
                        validator_authority_sha256=self.fixture.validator_authority_sha256,
                        runner_authority_ref=self.fixture.runner_authority_ref,
                        runner_authority_sha256=self.fixture.runner_authority_sha256,
                        runner_invocation_identity_sha256=self.fixture.runner_invocation_identity_sha256,
                        validation_protocol_identity_sha256=self.fixture.validation_protocol_identity_sha256,
                        input_schema_identity_sha256=self.fixture.input_schema_identity_sha256,
                        output_schema_identity_sha256=self.fixture.output_schema_identity_sha256,
                        system_shard_refs=shard_entries,
                    )

    def test_source_is_pure_and_has_no_authorization_or_io_capabilities(self) -> None:
        source_path = ROOT / "scripts" / "backend_runtime_validation_records.py"
        source = source_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = {
            alias.name.split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        } | {
            (node.module or "").split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        }
        self.assertTrue(imported.isdisjoint({
            "os", "pathlib", "subprocess", "socket", "docker", "requests",
            "backend_runtime_grant", "publication_matrix",
        }))
        calls = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertTrue(calls.isdisjoint({"open", "exec", "eval", "compile"}))
        self.assertNotIn("readiness", source.lower())
        self.assertNotIn("grant", source.lower())

    def test_validator_signatures_expose_external_trust_pins(self) -> None:
        context_parameters = inspect.signature(
            protocol.validate_backend_runtime_validation_system_context
        ).parameters
        for required in (
            "expected_semantic_sha256", "expected_qualification_index_ref",
            "expected_qualification_index_sha256", "expected_upstream_identities",
            "expected_validator_authority_ref", "expected_validator_authority_sha256",
            "expected_runner_authority_ref", "expected_runner_authority_sha256",
            "expected_runner_invocation_identity_sha256",
            "expected_validation_protocol_identity_sha256",
            "expected_input_schema_identity_sha256",
            "expected_output_schema_identity_sha256",
        ):
            self.assertIn(required, context_parameters)
            self.assertEqual(
                context_parameters[required].kind, inspect.Parameter.KEYWORD_ONLY,
            )


if __name__ == "__main__":
    unittest.main()
