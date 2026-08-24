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
import backend_runtime_qualification_v4_input_index as q4  # noqa: E402


def canonical_sha(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False,
    ).encode()).hexdigest()


def sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def ref(label: str, semantic: str | None = None) -> dict[str, object]:
    payload = (label + "\n").encode()
    return {"descriptor": {"path": f"qualification/q4/{label}.json",
                            "size_bytes": len(payload),
                            "sha256": hashlib.sha256(payload).hexdigest()},
            "content_identity_sha256": semantic or sha("semantic:" + label)}


def typed(label: str, version: int, kind: str,
          semantic: str) -> dict[str, object]:
    return {"artifact_schema_version": version, "artifact_kind": kind,
            **ref(label, semantic)}


class Fixture:
    def __init__(self) -> None:
        self.upstream = {field: sha(field) for field in q4.UPSTREAM_IDENTITY_FIELDS}
        self.abi = sha("abi-v3")
        self.abi_ref = typed("abi-v3", 3,
                             q4.PUBLICATION_LAUNCHER_INVOCATION_V3_KIND, self.abi)
        self.bindings: dict[str, str] = {}
        self.sets: dict[str, str] = {}
        self.launchers: dict[str, str] = {}
        self.systems = []
        for si, system in enumerate(q4.SYSTEMS):
            authorities = []
            by_coordinate = {}
            for codec in q4.CODECS:
                for topology in q4.TOPOLOGIES:
                    for policy in q4.POLICIES:
                        key = (system, codec, topology, policy)
                        identity = sha("authority:" + ":".join(key))
                        by_coordinate[key[1:]] = identity
                        authorities.append({
                            "coordinate": dict(zip(
                                ("system", "codec", "topology_kind", "policy"), key
                            )),
                            "authority_ref": typed(
                                "authority-" + "-".join(key), 2,
                                q4.RUNTIME_AUTHORITY_KIND, identity,
                            ),
                            "authority_sha256": identity,
                        })
            authorities.sort(key=lambda item: (
                item["coordinate"]["system"],
                item["coordinate"]["codec"],
                item["coordinate"]["topology_kind"],
                item["coordinate"]["policy"],
            ))
            authority_set = canonical_sha(authorities)
            launcher = sha("launcher:" + system)
            binding = q4.runtime_binding_identity_v4(
                system=system, upstream_identities=self.upstream,
                runtime_authority_set_sha256=authority_set,
                launcher_runtime_authority_sha256=launcher,
                publication_launcher_invocation_v3_sha256=self.abi,
            )
            self.bindings[system] = binding
            self.sets[system] = authority_set
            self.launchers[system] = launcher
            cells = []
            for codec in q4.CODECS:
                for topology in q4.TOPOLOGIES:
                    for policy in q4.POLICIES:
                        for di, deadline in enumerate(q4.DEADLINES_MS):
                            cell_index = (((si * 2 + q4.CODECS.index(codec)) * 2
                                           + q4.TOPOLOGIES.index(topology)) * 7
                                          + q4.POLICIES.index(policy)) * 5 + di
                            cells.append({
                                "system": system, "codec": codec,
                                "topology_kind": topology, "policy": policy,
                                "deadline_ms": deadline, "cell_index": cell_index,
                                "runtime_authority_sha256": by_coordinate[
                                    (codec, topology, policy)
                                ],
                                "raw_evidence_ref": ref(f"evidence-{cell_index}"),
                            })
            self.systems.append({
                "system": system,
                "runtime_binding_identity_v4_sha256": binding,
                "runtime_authority_set_sha256": authority_set,
                "runtime_authorities": authorities,
                "launcher_runtime_authority_ref": typed(
                    "launcher-" + system, 1,
                    q4.LAUNCHER_RUNTIME_AUTHORITY_KIND, launcher,
                ),
                "launcher_runtime_authority_sha256": launcher,
                "cells": cells,
            })
        unsigned = {"schema_version": 4, "artifact_kind": q4.ARTIFACT_KIND,
                    "upstream_identities": self.upstream,
                    "publication_launcher_invocation_v3_ref": self.abi_ref,
                    "publication_launcher_invocation_v3_sha256": self.abi,
                    "systems": self.systems}
        self.semantic = canonical_sha(unsigned)

    def expected(self) -> dict[str, object]:
        return {
            "expected_semantic_sha256": self.semantic,
            "expected_upstream_identities": self.upstream,
            "expected_publication_launcher_invocation_v3_sha256": self.abi,
            "expected_runtime_binding_identity_v4_sha256_by_system": self.bindings,
            "expected_runtime_authority_set_sha256_by_system": self.sets,
            "expected_launcher_runtime_authority_sha256_by_system": self.launchers,
        }

    def build(self) -> dict[str, object]:
        return q4.build_backend_runtime_qualification_v4_input_index(
            upstream_identities=self.upstream,
            publication_launcher_invocation_v3_ref=self.abi_ref,
            systems=self.systems, **self.expected(),
        )


class Q4InputIndexTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.f = Fixture()
        cls.index = cls.f.build()

    def validate(self, value: object, **overrides: object) -> dict[str, object]:
        expected = self.f.expected()
        expected.update(overrides)
        return q4.validate_backend_runtime_qualification_v4_input_index(
            value, **expected,
        )

    @staticmethod
    def reseal(value: dict[str, object]) -> None:
        value["input_index_sha256"] = canonical_sha({
            key: item for key, item in value.items()
            if key != "input_index_sha256"
        })

    def test_full_graph_builds_and_validates(self) -> None:
        value = self.validate(self.index)
        self.assertEqual(len(value["systems"]), 4)
        self.assertEqual(sum(len(s["runtime_authorities"])
                             for s in value["systems"]), 112)
        self.assertEqual(sum(len(s["cells"]) for s in value["systems"]), 560)
        self.assertIsNot(value, self.index)

    def test_builder_uses_validation_and_all_pins_are_required(self) -> None:
        with self.assertRaises(q4.BackendRuntimeQualificationV4InputIndexError):
            q4.build_backend_runtime_qualification_v4_input_index(
                upstream_identities=self.f.upstream,
                publication_launcher_invocation_v3_ref=self.f.abi_ref,
                systems=self.f.systems,
                **{**self.f.expected(), "expected_semantic_sha256": sha("wrong")},
            )
        for function in (q4.build_backend_runtime_qualification_v4_input_index,
                         q4.validate_backend_runtime_qualification_v4_input_index):
            signature = inspect.signature(function)
            for name in self.f.expected():
                self.assertIs(signature.parameters[name].default,
                              inspect.Signature.empty)

    def test_closed_top_and_external_pins(self) -> None:
        for mutation in ("missing", "extra", "semantic", "upstream", "binding",
                         "set", "launcher"):
            changed = copy.deepcopy(self.index)
            overrides = {}
            if mutation == "missing":
                changed.pop("upstream_identities")
            elif mutation == "extra":
                changed["validation_records"] = []
            elif mutation == "semantic":
                overrides["expected_semantic_sha256"] = sha("other")
            else:
                key = {"upstream": "expected_upstream_identities",
                       "binding": "expected_runtime_binding_identity_v4_sha256_by_system",
                       "set": "expected_runtime_authority_set_sha256_by_system",
                       "launcher": "expected_launcher_runtime_authority_sha256_by_system"}[mutation]
                overrides[key] = copy.deepcopy(self.f.expected()[key])
                target = q4.UPSTREAM_IDENTITY_FIELDS[0] if mutation == "upstream" else "deepstream"
                overrides[key][target] = sha("attacker:" + mutation)
            self.reseal(changed)
            overrides.setdefault("expected_semantic_sha256",
                                 changed["input_index_sha256"])
            with self.subTest(mutation=mutation), self.assertRaises(
                q4.BackendRuntimeQualificationV4InputIndexError
            ):
                self.validate(changed, **overrides)

    def test_old_abi_and_runtime_v1_refs_rejected(self) -> None:
        for mutation in ("abi-schema", "abi-kind", "authority-schema",
                         "authority-kind", "launcher-kind"):
            changed = copy.deepcopy(self.index)
            if mutation == "abi-schema":
                changed["publication_launcher_invocation_v3_ref"][
                    "artifact_schema_version"] = 2
            elif mutation == "abi-kind":
                changed["publication_launcher_invocation_v3_ref"][
                    "artifact_kind"] = "vast_backend_publication_launcher_invocation"
            elif mutation == "authority-schema":
                changed["systems"][0]["runtime_authorities"][0][
                    "authority_ref"]["artifact_schema_version"] = 1
            elif mutation == "authority-kind":
                changed["systems"][0]["runtime_authorities"][0][
                    "authority_ref"]["artifact_kind"] = (
                        "vast_backend_publication_runtime_authority"
                    )
            else:
                changed["systems"][0]["launcher_runtime_authority_ref"][
                    "artifact_kind"] = "untrusted_launcher"
            self.reseal(changed)
            with self.subTest(mutation=mutation), self.assertRaises(
                q4.BackendRuntimeQualificationV4InputIndexError
            ):
                self.validate(changed,
                              expected_semantic_sha256=changed["input_index_sha256"])

    def test_authority_cardinality_order_relabel_set_and_global_uniqueness(self) -> None:
        for mutation in ("missing", "duplicate", "order", "relabel", "set",
                         "global-semantic"):
            changed = copy.deepcopy(self.index)
            authorities = changed["systems"][0]["runtime_authorities"]
            if mutation == "missing":
                authorities.pop()
            elif mutation == "duplicate":
                authorities[1] = copy.deepcopy(authorities[0])
            elif mutation == "order":
                authorities[0], authorities[1] = authorities[1], authorities[0]
            elif mutation == "relabel":
                authorities[0]["coordinate"]["policy"] = "gpu_only"
            elif mutation == "set":
                changed["systems"][0]["runtime_authority_set_sha256"] = sha("bad-set")
            else:
                source = changed["systems"][0]["runtime_authorities"][0]
                target = changed["systems"][1]["runtime_authorities"][0]
                target["authority_sha256"] = source["authority_sha256"]
                target["authority_ref"]["content_identity_sha256"] = source[
                    "authority_sha256"
                ]
            self.reseal(changed)
            with self.subTest(mutation=mutation), self.assertRaises(
                q4.BackendRuntimeQualificationV4InputIndexError
            ):
                self.validate(changed,
                              expected_semantic_sha256=changed["input_index_sha256"])

    def test_cell_cardinality_order_relabel_deadline_type_ordinal_and_reuse(self) -> None:
        for mutation in ("missing", "duplicate", "order", "relabel", "type",
                         "ordinal", "authority"):
            changed = copy.deepcopy(self.index)
            cells = changed["systems"][0]["cells"]
            if mutation == "missing": cells.pop()
            elif mutation == "duplicate": cells[1] = copy.deepcopy(cells[0])
            elif mutation == "order": cells[0], cells[1] = cells[1], cells[0]
            elif mutation == "relabel": cells[0]["policy"] = "gpu_only"
            elif mutation == "type": cells[2]["deadline_ms"] = 50.0
            elif mutation == "ordinal": cells[0]["cell_index"] = 1
            else: cells[0]["runtime_authority_sha256"] = sha("wrong-authority")
            self.reseal(changed)
            with self.subTest(mutation=mutation), self.assertRaises(
                q4.BackendRuntimeQualificationV4InputIndexError
            ):
                self.validate(changed,
                              expected_semantic_sha256=changed["input_index_sha256"])

    def test_duplicate_path_file_content_full_and_reserved_cycle_rejected(self) -> None:
        for identity in ("path", "file", "content", "full", "cycle"):
            changed = copy.deepcopy(self.index)
            source = changed["systems"][0]["cells"][0]["raw_evidence_ref"]
            target = changed["systems"][0]["cells"][1]["raw_evidence_ref"]
            if identity == "path": target["descriptor"]["path"] = source["descriptor"]["path"]
            elif identity == "file": target["descriptor"]["sha256"] = source["descriptor"]["sha256"]
            elif identity == "content": target["content_identity_sha256"] = source["content_identity_sha256"]
            elif identity == "full": changed["systems"][0]["cells"][1]["raw_evidence_ref"] = copy.deepcopy(source)
            else: target["content_identity_sha256"] = self.f.bindings["deepstream"]
            self.reseal(changed)
            with self.subTest(identity=identity), self.assertRaises(
                q4.BackendRuntimeQualificationV4InputIndexError
            ):
                self.validate(changed,
                              expected_semantic_sha256=changed["input_index_sha256"])

    def test_case_only_windows_path_alias_is_rejected_without_rewriting_paths(self) -> None:
        changed = copy.deepcopy(self.index)
        source = changed["systems"][0]["cells"][0]["raw_evidence_ref"]
        target = changed["systems"][0]["cells"][1]["raw_evidence_ref"]
        original_path = source["descriptor"]["path"]
        target["descriptor"]["path"] = original_path.upper()
        self.reseal(changed)
        with self.assertRaises(q4.BackendRuntimeQualificationV4InputIndexError):
            self.validate(
                changed,
                expected_semantic_sha256=changed["input_index_sha256"],
            )
        self.assertEqual(
            self.validate(self.index)["systems"][0]["cells"][0]
            ["raw_evidence_ref"]["descriptor"]["path"],
            original_path,
        )

    def test_binding_sensitive_and_source_pure_nonauthorizing(self) -> None:
        base = {"system": "deepstream", "upstream_identities": self.f.upstream,
                "runtime_authority_set_sha256": self.f.sets["deepstream"],
                "launcher_runtime_authority_sha256": self.f.launchers["deepstream"],
                "publication_launcher_invocation_v3_sha256": self.f.abi}
        identities = {q4.runtime_binding_identity_v4(**base)}
        for field in base:
            changed = copy.deepcopy(base)
            if field == "system": changed[field] = "savant"
            elif field == "upstream_identities": changed[field][q4.UPSTREAM_IDENTITY_FIELDS[0]] = sha("other-upstream")
            else: changed[field] = sha("other:" + field)
            identities.add(q4.runtime_binding_identity_v4(**changed))
        self.assertEqual(len(identities), 6)
        source = (ROOT / "scripts" / "backend_runtime_qualification_v4_input_index.py").read_text()
        tree = ast.parse(source)
        imported = {alias.name.split(".")[0] for node in ast.walk(tree)
                    if isinstance(node, ast.Import) for alias in node.names}
        imported |= {(node.module or "").split(".")[0] for node in ast.walk(tree)
                     if isinstance(node, ast.ImportFrom)}
        self.assertTrue(imported <= {"__future__", "copy", "hashlib", "json",
                                     "math", "re", "typing"})
        keys = set()
        def collect(value: object) -> None:
            if type(value) is dict:
                keys.update(value)
                for item in value.values(): collect(item)
            elif type(value) is list:
                for item in value: collect(item)
        collect(self.index)
        self.assertFalse(keys & {"status", "execution_authorized",
                                 "authorization_eligible",
                                 "validation_records_authenticated",
                                 "validation_record_sha256", "grant_sha256"})


if __name__ == "__main__":
    unittest.main()
