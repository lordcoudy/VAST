from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from backend_publication_dispatch import launcher_invocation_contract  # noqa: E402
from backend_publication_runtime_authority import (  # noqa: E402
    build_backend_publication_runtime_authority,
)
from backend_runtime_grant import (  # noqa: E402
    BackendRuntimeGrantError,
    assess_pre_run_backend_runtime_grant,
    assess_pre_run_backend_runtime_grant_v3,
    backend_runtime_grant_v3_from_qualification_catalog,
    validate_pre_run_backend_runtime_grant,
    validate_pre_run_backend_runtime_grant_v3,
)
from backend_runtime_qualification_v3 import (  # noqa: E402
    CODECS,
    DEADLINES_MS,
    POLICIES,
    SYSTEMS,
    TOPOLOGIES,
    assess_backend_runtime_qualification_v3,
    promote_backend_runtime_qualification_v3,
    qualification_catalog_v3_from_assessment,
    runtime_binding_identity_v3,
    validate_backend_runtime_qualification_v3_catalog,
)


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def canonical_sha(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def descriptor(root: Path, relative: str, payload: bytes) -> dict[str, object]:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return {
        "path": relative,
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def artifact(role: str, value: dict[str, object]) -> dict[str, object]:
    return {
        "role": role,
        "descriptor": copy.deepcopy(value),
        "content_identity_sha256": value["sha256"],
    }


def content_record(content: dict[str, object]) -> dict[str, object]:
    return {"content": content, "content_identity_sha256": canonical_sha(content)}


class PhysicalV3Fixture:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.upstream = {
            "dataset_manifest_sha256": hashlib.sha256(b"dataset").hexdigest(),
            "policy_contract_sha256": hashlib.sha256(b"policy-contract").hexdigest(),
            "policy_qualification_receipt_sha256": hashlib.sha256(b"policy-receipt").hexdigest(),
            "resource_contract_identity_sha256": hashlib.sha256(b"resource-contract").hexdigest(),
            "resource_qualification_receipt_sha256": hashlib.sha256(b"resource-receipt").hexdigest(),
            "analytics_execution_config_identity_sha256": hashlib.sha256(b"execution").hexdigest(),
            "model_parity_manifest_identity_sha256": hashlib.sha256(b"parity").hexdigest(),
            "model_parity_acceptance_binding_sha256": hashlib.sha256(
                b"parity-acceptance-binding"
            ).hexdigest(),
        }
        self.index_path = self.root / "qualification/backend_v3_index.json"
        self.index = self._build_index()
        self.write_index(self.index)

    def _authority_fields(
        self, *, system: str, codec: str, topology: str, policy: str,
    ) -> dict[str, object]:
        shared = "runtime-authority-leaves"
        manifest = descriptor(
            self.root, f"{shared}/dataset-manifest.json", b"dataset-manifest"
        )
        dataset_file = descriptor(
            self.root, f"{shared}/kpp-source.bin", b"kpp-source"
        )
        source = artifact(
            "source_binary",
            descriptor(self.root, f"{shared}/source.bin", b"source"),
        )
        backend = artifact(
            "runtime_binary",
            descriptor(self.root, f"{shared}/backend.bin", b"backend"),
        )
        analytics_capability = artifact(
            "analytics_endpoint_capability",
            descriptor(
                self.root, f"{shared}/analytics-capability.json",
                b"analytics-capability",
            ),
        )
        analytics_binding = artifact(
            "analytics_worker_binding",
            descriptor(
                self.root, f"{shared}/analytics-binding.json", b"analytics-binding"
            ),
        )
        policy_capability = artifact(
            "policy_capability",
            descriptor(
                self.root, f"{shared}/policy-capability.json", b"policy-capability"
            ),
        )
        calibration = artifact(
            "policy_calibration",
            descriptor(
                self.root, f"{shared}/policy-calibration.json", b"calibration"
            ),
        )
        static_map = None
        if policy == "static_hybrid":
            static_map = artifact(
                "policy_static_map",
                descriptor(
                    self.root, f"{shared}/policy-static-map.json", b"static-map"
                ),
            )
        return {
            "system": system,
            "policy": policy,
            "topology_kind": topology,
            "codec": codec,
            "dataset_manifest": manifest,
            "dataset_files": [dataset_file],
            "source_runtime_artifacts": [source],
            "backend_runtime_artifacts": [backend],
            "analytics_authority": {
                "endpoint_authority": {
                    "transport": "AF_UNIX/SOCK_SEQPACKET",
                    "path_derivation_contract_sha256": "1" * 64,
                    "peer_capability_identity_sha256": "2" * 64,
                    "peer_binding_identity_sha256": "3" * 64,
                    "bind_before_backend_launch": True,
                    "peer_credentials_required": True,
                },
                "capability": analytics_capability,
                "bindings": [analytics_binding],
                "preprocessing_contract_sha256": "4" * 64,
            },
            "model_parity_acceptance_binding_sha256": self.upstream[
                "model_parity_acceptance_binding_sha256"
            ],
            "policy_authority": {
                "capability": policy_capability,
                "calibration": calibration,
                "static_map": static_map,
            },
            "cohort_topology_plan": content_record({
                "topology_kind": topology,
                "source_decode_count": 1 if topology == "shared_video_dag" else 4,
            }),
            "resource_contract": content_record({"contract_version": 2}),
            "system_specific_launcher_input": content_record({
                "system": system,
                "launcher_kind": "dedicated_publication_runtime",
            }),
        }

    def _authority_record(
        self, *, system: str, codec: str, topology: str, policy: str,
    ) -> dict[str, object]:
        authority = build_backend_publication_runtime_authority(
            project_root=self.root,
            **self._authority_fields(
                system=system, codec=codec, topology=topology, policy=policy,
            ),
        )
        relative = (
            f"qualification/authorities/{system}/{codec}/{topology}/{policy}.json"
        )
        payload = canonical_bytes(authority) + b"\n"
        authority_descriptor = descriptor(self.root, relative, payload)
        return {
            "system": system,
            "codec": codec,
            "topology_kind": topology,
            "policy": policy,
            "artifact": authority_descriptor,
            "runtime_authority_sha256": authority["authority_sha256"],
        }

    def _build_index(self) -> dict[str, object]:
        systems: dict[str, object] = {}
        invocation = launcher_invocation_contract()
        for system in SYSTEMS:
            launcher = descriptor(
                self.root,
                f"scripts/checkpoint_{system}_publication_launcher.py",
                f"launcher:{system}".encode("utf-8"),
            )
            authorities = [
                self._authority_record(
                    system=system, codec=codec, topology=topology, policy=policy,
                )
                for codec in CODECS
                for topology in TOPOLOGIES
                for policy in POLICIES
            ]
            authorities.sort(key=lambda item: (
                item["system"], item["codec"], item["topology_kind"],
                item["policy"],
            ))
            authority_set_sha = canonical_sha(authorities)
            binding_sha = runtime_binding_identity_v3(
                system=system,
                launcher=launcher,
                launcher_invocation=invocation,
                upstream_identities=self.upstream,
                runtime_authority_set_sha256=authority_set_sha,
            )
            authority_by_coordinate = {
                (
                    item["codec"], item["topology_kind"], item["policy"],
                ): item["runtime_authority_sha256"]
                for item in authorities
            }
            cells = []
            for codec in CODECS:
                for topology in TOPOLOGIES:
                    for policy in POLICIES:
                        for deadline in DEADLINES_MS:
                            ordinal = len(cells)
                            cells.append({
                                "system": system,
                                "codec": codec,
                                "topology_kind": topology,
                                "policy": policy,
                                "deadline_ms": deadline,
                                "runtime_authority_sha256": authority_by_coordinate[
                                    (codec, topology, policy)
                                ],
                                "raw_evidence": descriptor(
                                    self.root,
                                    f"qualification/evidence/{system}/{ordinal:03d}.json",
                                    f"evidence:{system}:{ordinal}".encode("utf-8"),
                                ),
                            })
            systems[system] = {
                "system": system,
                "runtime_binding_identity_sha256": binding_sha,
                "runtime_authority_set_sha256": authority_set_sha,
                "runtime_authorities": authorities,
                "launcher": launcher,
                "launcher_invocation": invocation,
                "launcher_kind": "dedicated_publication_runtime",
                "publication_capable": True,
                "cells": cells,
            }
        return {
            "schema_version": 3,
            "artifact_kind": "vast_backend_runtime_qualification_v3_index",
            "upstream_identities": self.upstream,
            "systems": systems,
        }

    def write_index(self, value: dict[str, object]) -> None:
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        self.index_path.write_bytes(canonical_bytes(value) + b"\n")


def raw_validator(
    cell: dict[str, object], context: dict[str, object],
) -> dict[str, object]:
    coordinate = {
        key: cell[key]
        for key in ("system", "codec", "topology_kind", "policy", "deadline_ms")
    }
    result = {
        "schema_version": 3,
        "artifact_kind": "vast_backend_runtime_cell_raw_evidence_validation_v3",
        **coordinate,
        "accepted": True,
        "synthetic": False,
        "nonpublication": False,
        "publication_capable": True,
        "runtime_binding_identity_sha256": context[
            "runtime_binding_identity_sha256"
        ],
        "runtime_authority_sha256": context["runtime_authority_sha256"],
        "runtime_authority_set_sha256": context[
            "runtime_authority_set_sha256"
        ],
        "launcher_sha256": context["launcher"]["sha256"],
        "launcher_invocation_sha256": context["launcher_invocation"][
            "invocation_sha256"
        ],
        "raw_evidence_sha256": context["raw_evidence"]["sha256"],
        "upstream_identities": context["upstream_identities"],
        "validator_identity_sha256": hashlib.sha256(
            b"backend-cell-raw-validator-v3"
        ).hexdigest(),
    }
    result["validation_record_sha256"] = canonical_sha(result)
    return result


class BackendRuntimeQualificationV3Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory()
        cls.fixture = PhysicalV3Fixture(Path(cls.temporary.name))

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    def tearDown(self) -> None:
        self.fixture.write_index(self.fixture.index)

    def assess(self, value: dict[str, object] | None = None) -> dict[str, object]:
        self.fixture.write_index(value or self.fixture.index)
        return assess_backend_runtime_qualification_v3(
            project_root=self.fixture.root,
            index_path=self.fixture.index_path,
            raw_evidence_validator=raw_validator,
        )

    def test_default_validator_fails_closed_without_creating_receipts(self) -> None:
        before = set(self.fixture.root.rglob("*"))
        assessment = assess_backend_runtime_qualification_v3(
            project_root=self.fixture.root,
            index_path=self.fixture.index_path,
        )
        self.assertFalse(assessment["passed"])
        self.assertEqual(assessment["status"], "blocked")
        self.assertTrue(any("validator is required" in item for item in assessment["blockers"]))
        self.assertEqual(before, set(self.fixture.root.rglob("*")))

    def test_exact_112_authorities_and_five_deadline_reuse_per_authority(self) -> None:
        assessment = self.assess()
        self.assertTrue(assessment["passed"], assessment["blockers"])
        self.assertEqual(assessment["coverage"], {
            "system_count": 4,
            "runtime_authority_count": 112,
            "runtime_authorities_per_system": 28,
            "runtime_cell_count": 560,
            "cells_per_system": 140,
            "deadlines_per_runtime_authority": 5,
        })
        observed: set[str] = set()
        for system in SYSTEMS:
            item = assessment["systems"][system]
            self.assertEqual(len(item["runtime_authorities"]), 28)
            self.assertEqual(
                item["runtime_authority_set_sha256"],
                canonical_sha(item["runtime_authorities"]),
            )
            uses: dict[str, int] = {}
            for cell in item["qualified_cells"]:
                uses[cell["runtime_authority_sha256"]] = (
                    uses.get(cell["runtime_authority_sha256"], 0) + 1
                )
            self.assertEqual(set(uses.values()), {5})
            self.assertEqual(len(uses), 28)
            observed.update(uses)
        self.assertEqual(len(observed), 112)

    def test_authority_catalog_and_cell_cross_binding_drift_fail_closed(self) -> None:
        duplicate = copy.deepcopy(self.fixture.index)
        authorities = duplicate["systems"][SYSTEMS[0]]["runtime_authorities"]
        authorities[-1] = copy.deepcopy(authorities[0])
        duplicate["systems"][SYSTEMS[0]]["runtime_authority_set_sha256"] = canonical_sha(authorities)
        duplicate["systems"][SYSTEMS[0]]["runtime_binding_identity_sha256"] = runtime_binding_identity_v3(
            system=SYSTEMS[0],
            launcher=duplicate["systems"][SYSTEMS[0]]["launcher"],
            launcher_invocation=duplicate["systems"][SYSTEMS[0]]["launcher_invocation"],
            upstream_identities=duplicate["upstream_identities"],
            runtime_authority_set_sha256=duplicate["systems"][SYSTEMS[0]]["runtime_authority_set_sha256"],
        )
        cross_bound = copy.deepcopy(self.fixture.index)
        cells = cross_bound["systems"][SYSTEMS[0]]["cells"]
        cells[0]["runtime_authority_sha256"] = cells[5]["runtime_authority_sha256"]

        for value in (duplicate, cross_bound):
            with self.subTest(case="catalog" if value is duplicate else "cell"):
                assessment = self.assess(value)
                self.assertFalse(assessment["passed"])
                self.assertEqual(assessment["status"], "blocked")

    def test_stale_cell_identity_rejects_coherent_authority_rebinding(self) -> None:
        catalog = qualification_catalog_v3_from_assessment(self.assess())
        system = SYSTEMS[0]
        system_value = catalog["systems"][system]
        first, second = system_value["runtime_authorities"][:2]
        first_key = (
            first["codec"], first["topology_kind"], first["policy"],
        )
        second_key = (
            second["codec"], second["topology_kind"], second["policy"],
        )
        first["artifact"], second["artifact"] = (
            second["artifact"], first["artifact"],
        )
        first["runtime_authority_sha256"], second["runtime_authority_sha256"] = (
            second["runtime_authority_sha256"],
            first["runtime_authority_sha256"],
        )
        selected = {
            first_key: first["runtime_authority_sha256"],
            second_key: second["runtime_authority_sha256"],
        }
        for cell in system_value["qualified_cells"]:
            key = (cell["codec"], cell["topology_kind"], cell["policy"])
            if key in selected:
                cell["runtime_authority_sha256"] = selected[key]
                # Deliberately leave cell_identity_sha256 stale.  Every outer
                # identity below is recomputed to isolate this exact boundary.
        system_value["runtime_authority_set_sha256"] = canonical_sha(
            system_value["runtime_authorities"]
        )
        system_value["runtime_binding_identity_sha256"] = runtime_binding_identity_v3(
            system=system,
            launcher=system_value["launcher"],
            launcher_invocation=system_value["launcher_invocation"],
            upstream_identities=catalog["upstream_identities"],
            runtime_authority_set_sha256=system_value[
                "runtime_authority_set_sha256"
            ],
        )
        system_value["qualified_cells_sha256"] = canonical_sha(
            system_value["qualified_cells"]
        )
        catalog.pop("catalog_sha256")
        catalog["catalog_sha256"] = canonical_sha(catalog)

        with self.assertRaisesRegex(Exception, "cell identity"):
            validate_backend_runtime_qualification_v3_catalog(catalog)

    def test_physical_authority_tamper_blocks_before_raw_validation(self) -> None:
        record = self.fixture.index["systems"][SYSTEMS[0]]["runtime_authorities"][0]
        path = self.fixture.root / record["artifact"]["path"]
        original = path.read_bytes()
        try:
            path.write_bytes(b"tampered-authority")
            assessment = self.assess()
            self.assertFalse(assessment["passed"])
            self.assertTrue(any("authority" in item for item in assessment["blockers"]))
        finally:
            path.write_bytes(original)

    def test_catalog_is_self_hashed_schema_isolated_and_not_a_grant(self) -> None:
        assessment = self.assess()
        catalog = qualification_catalog_v3_from_assessment(assessment)
        self.assertEqual(
            validate_backend_runtime_qualification_v3_catalog(catalog), catalog
        )
        self.assertEqual(
            catalog["status"],
            "qualified_runtime_authority_catalog_v3_pre_identity_candidate",
        )
        self.assertFalse(assess_pre_run_backend_runtime_grant_v3(catalog)["passed"])
        self.assertFalse(assess_pre_run_backend_runtime_grant(catalog)["passed"])
        with self.assertRaisesRegex(
            BackendRuntimeGrantError, "persisted.*identity",
        ):
            backend_runtime_grant_v3_from_qualification_catalog(
                catalog,
                identity_artifact_binding_sha256=hashlib.sha256(
                    b"future-full-identity-binding-v3"
                ).hexdigest(),
            )
        with self.assertRaises(BackendRuntimeGrantError):
            validate_pre_run_backend_runtime_grant_v3(catalog)

        drifted = copy.deepcopy(catalog)
        drifted["systems"][SYSTEMS[0]][
            "runtime_authority_set_sha256"
        ] = "0" * 64
        drifted.pop("catalog_sha256")
        drifted["catalog_sha256"] = canonical_sha(drifted)
        with self.assertRaises(Exception):
            validate_backend_runtime_qualification_v3_catalog(drifted)

    def test_promotion_writes_four_receipts_then_binding_index_as_candidate(self) -> None:
        with tempfile.TemporaryDirectory(dir=self.fixture.root) as tmp:
            output = Path(tmp)
            result = promote_backend_runtime_qualification_v3(
                project_root=self.fixture.root,
                index_path=self.fixture.index_path,
                output_dir=output,
                raw_evidence_validator=raw_validator,
            )
            self.assertEqual(result["status"], "promoted_pre_identity_candidate")
            self.assertEqual(len(result["receipt_descriptors"]), 4)
            binding_path = output / result["binding_index_descriptor"]["path"]
            self.assertTrue(binding_path.is_file())
            binding = json.loads(binding_path.read_text(encoding="utf-8"))
            self.assertEqual(binding["schema_version"], 3)
            self.assertEqual(
                binding["status"],
                "qualified_runtime_authority_catalog_v3_pre_identity_candidate",
            )
            self.assertEqual(binding["coverage"]["runtime_authority_count"], 112)
            for system in SYSTEMS:
                receipt = output / result["receipt_descriptors"][system]["path"]
                self.assertTrue(receipt.is_file())

            repeated = promote_backend_runtime_qualification_v3(
                project_root=self.fixture.root,
                index_path=self.fixture.index_path,
                output_dir=output,
                raw_evidence_validator=raw_validator,
            )
            self.assertEqual(result["binding_index"], repeated["binding_index"])


if __name__ == "__main__":
    unittest.main()
