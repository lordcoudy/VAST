from __future__ import annotations

import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from backend_runtime_grant import (  # noqa: E402
    BackendRuntimeGrantError,
    SYSTEMS,
    assess_pre_run_backend_runtime_grant,
    backend_launcher_output_receipt_protocol_ready,
    backend_runtime_grant_from_identity_artifacts,
    validate_pre_run_backend_runtime_grant,
)
from backend_publication_launcher_invocation_v3 import (  # noqa: E402
    publication_launcher_invocation_v3_contract,
)
from backend_publication_dispatch import (  # noqa: E402
    launcher_invocation_contract,
    runtime_binding_identity,
)


def canonical_sha(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def descriptor(path: str, marker: str) -> dict[str, object]:
    return {
        "path": path,
        "size_bytes": 100 + len(marker),
        "sha256": hashlib.sha256(marker.encode("utf-8")).hexdigest(),
    }


def cell(system: str, ordinal: int) -> dict[str, object]:
    codec = ("h264", "h265")[(ordinal // 70) % 2]
    topology = ("independent_processes", "shared_video_dag")[(ordinal // 35) % 2]
    policies = (
        "cpu_only",
        "gpu_only",
        "static_hybrid",
        "heft",
        "deadline_aware_heft",
        "queue_aware_edf",
        "adaptive_weights",
    )
    policy = policies[(ordinal // 5) % len(policies)]
    deadline = (16.7, 33.3, 50, 100, 500)[ordinal % 5]
    coordinate = {
        "system": system,
        "codec": codec,
        "topology_kind": topology,
        "policy": policy,
        "deadline_ms": deadline,
    }
    return {
        **coordinate,
        "cell_identity_sha256": canonical_sha(coordinate),
        "raw_evidence": descriptor(
            f"accepted/backend/{system}/cells/{ordinal:03d}.json",
            f"raw:{system}:{ordinal}",
        ),
        "launcher_invocation_sha256": launcher_invocation_contract()[
            "invocation_sha256"
        ],
        "validator_identity_sha256": hashlib.sha256(
            b"backend-cell-raw-validator-v2"
        ).hexdigest(),
        "validation_record_sha256": hashlib.sha256(
            f"validation:{system}:{ordinal}".encode("utf-8")
        ).hexdigest(),
    }


def system_binding(
    system: str, upstream_identities: dict[str, object]
) -> dict[str, object]:
    cells = [cell(system, ordinal) for ordinal in range(140)]
    launcher = descriptor(
        f"scripts/checkpoint_{system}_publication_launcher.py",
        f"launcher:{system}",
    )
    invocation = launcher_invocation_contract()
    return {
        "system": system,
        "runtime_binding_identity_sha256": runtime_binding_identity(
            system=system,
            launcher=launcher,
            launcher_invocation=invocation,
            upstream_identities=upstream_identities,
        ),
        "launcher": launcher,
        "launcher_invocation": invocation,
        "launcher_kind": "dedicated_publication_runtime",
        "publication_capable": True,
        "qualified_cells": cells,
        "qualified_cells_sha256": canonical_sha(cells),
        "raw_evidence_set_sha256": canonical_sha(
            [item["raw_evidence"] for item in cells]
        ),
    }


def v2_identity() -> dict[str, object]:
    index = descriptor(
        "accepted/checkpoint_backend_runtime_qualification_binding_index.json",
        "binding-index-v2",
    )
    receipts = {
        system: descriptor(
            f"accepted/checkpoint_{system}_backend_runtime_qualification_receipt.json",
            f"receipt:{system}:v2",
        )
        for system in SYSTEMS
    }
    upstream_identities = {
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
    systems = {
        system: system_binding(system, upstream_identities)
        for system in SYSTEMS
    }
    backend = {
        "schema_version": 2,
        "qualification_index_sha256": hashlib.sha256(b"qualification-index-v2").hexdigest(),
        "binding_index": index,
        "receipts": receipts,
        "upstream_identities": upstream_identities,
        "systems": systems,
        "coverage": {
            "system_count": 4,
            "runtime_cell_count": 560,
            "cells_per_system": 140,
        },
        "post_run_per_arm_evidence_required": True,
        "configuration_evidence_accepted_mutated": False,
    }
    files = [index, *receipts.values()]
    files.extend(systems[system]["launcher"] for system in SYSTEMS)
    files.extend(
        item["raw_evidence"]
        for system in SYSTEMS
        for item in systems[system]["qualified_cells"]
    )
    identity = {
        "schema_version": 2,
        "artifact_kind": "vast_full_publication_identity_artifact_binding",
        "manifest": descriptor("configs/full_publication_identity_artifacts.yaml", "manifest"),
        "bindings": {
            "analytics_model_parity": {
                "binding_sha256": upstream_identities[
                    "model_parity_acceptance_binding_sha256"
                ]
            },
            "analytics_execution_layer": {},
            "policy_qualification": {},
            "resource_qualification": {},
            "backend_runtime_qualification": backend,
        },
        "files": files,
        "files_sha256": canonical_sha(files),
    }
    identity["binding_sha256"] = canonical_sha(identity)
    return identity


def v3_identity() -> dict[str, object]:
    upstream = v2_identity()["bindings"]["backend_runtime_qualification"][
        "upstream_identities"
    ]
    invocation = publication_launcher_invocation_v3_contract()
    validator_sha = hashlib.sha256(b"authenticated-q4-validator").hexdigest()
    index = descriptor(
        "accepted/checkpoint_backend_runtime_qualification_v4_binding_index.json",
        "q4-binding-index",
    )
    receipts = {
        system: descriptor(
            f"accepted/checkpoint_{system}_backend_runtime_qualification_v4_receipt.json",
            f"q4-receipt:{system}",
        )
        for system in SYSTEMS
    }
    protocol_paths = {
        "full_publication_entrypoint": "scripts/full_publication_entrypoint.py",
        "production_output_transaction": (
            "scripts/backend_publication_output_transaction_production_v3.py"
        ),
        "engineering_output_transaction": (
            "scripts/backend_publication_output_transaction_v3.py"
        ),
        "dispatch_abi": "scripts/backend_publication_dispatch_v3.py",
        "process_supervisor": (
            "scripts/backend_publication_process_supervisor_v3.py"
        ),
    }
    protocol_files = {
        role: descriptor(path, f"protocol:{role}")
        for role, path in protocol_paths.items()
    }
    systems: dict[str, object] = {}
    files: list[dict[str, object]] = [
        index, *receipts.values(), *protocol_files.values(),
    ]
    for system in SYSTEMS:
        launcher = descriptor(
            f"scripts/checkpoint_{system}_publication_launcher_v3.py",
            f"launcher-v3:{system}",
        )
        launcher_authority_descriptor = descriptor(
            f"accepted/{system}-launcher-authority.json",
            f"launcher-authority:{system}",
        )
        launcher_authority_sha = hashlib.sha256(
            f"launcher-authority-semantic:{system}".encode()
        ).hexdigest()
        authorities: list[dict[str, object]] = []
        authority_files: list[dict[str, object]] = []
        authority_shas: dict[tuple[str, str, str], str] = {}
        for codec in ("h264", "h265"):
            for topology in ("independent_processes", "shared_video_dag"):
                for policy in (
                    "cpu_only", "gpu_only", "static_hybrid", "heft",
                    "deadline_aware_heft", "queue_aware_edf",
                    "adaptive_weights",
                ):
                    marker = f"{system}:{codec}:{topology}:{policy}"
                    authority_sha = hashlib.sha256(
                        f"authority-semantic:{marker}".encode()
                    ).hexdigest()
                    authority_descriptor = descriptor(
                        f"accepted/backend/{system}/authorities/"
                        f"{codec}-{topology}-{policy}.json",
                        f"authority-file:{marker}",
                    )
                    authorities.append({
                        "system": system,
                        "codec": codec,
                        "topology_kind": topology,
                        "policy": policy,
                        "runtime_authority_sha256": authority_sha,
                        "artifact": {"authority_sha256": authority_sha},
                        "artifact_descriptor": authority_descriptor,
                    })
                    authority_files.append(authority_descriptor)
                    authority_shas[(codec, topology, policy)] = authority_sha
        cells: list[dict[str, object]] = []
        for ordinal in range(140):
            source = cell(system, ordinal)
            source["launcher_invocation_sha256"] = invocation[
                "invocation_sha256"
            ]
            source["validator_identity_sha256"] = validator_sha
            source["runtime_authority_sha256"] = authority_shas[(
                str(source["codec"]), str(source["topology_kind"]),
                str(source["policy"]),
            )]
            cells.append(source)
        systems[system] = {
            "system": system,
            "runtime_binding_identity_sha256": hashlib.sha256(
                f"runtime-binding-v4:{system}".encode()
            ).hexdigest(),
            "runtime_authority_set_sha256": hashlib.sha256(
                f"authority-set:{system}".encode()
            ).hexdigest(),
            "runtime_authorities": authorities,
            "launcher_runtime_authority": {
                "launcher_runtime_authority_sha256": launcher_authority_sha,
            },
            "launcher_runtime_authority_descriptor": (
                launcher_authority_descriptor
            ),
            "launcher_runtime_authority_sha256": launcher_authority_sha,
            "launcher": launcher,
            "launcher_invocation": invocation,
            "launcher_kind": "dedicated_publication_runtime_v3",
            "publication_capable": True,
            "qualified_cells": cells,
            "qualified_cells_sha256": canonical_sha(cells),
            "raw_evidence_set_sha256": canonical_sha([
                item["raw_evidence"] for item in cells
            ]),
        }
        files.extend([
            launcher, launcher_authority_descriptor, *authority_files,
            *(item["raw_evidence"] for item in cells),
        ])
    protocol = {
        "schema_version": 4,
        "artifact_kind": (
            "vast_backend_publication_production_output_receipt_protocol_binding_v4"
        ),
        "execution_scope": "full_publication_measurement_v3",
        "receipt_kind": "vast_backend_publication_production_output_receipt_v4",
        "receipt_authority_kind": (
            "vast_backend_publication_production_output_receipt_authority_v4"
        ),
        "atomicity": "durable_journal_then_launcher_result_then_output_receipt_last_v4",
        "parent_owned_transaction_required": True,
        "semantic_evidence_validation_required": True,
        "protocol_files": protocol_files,
        "systems": {
            system: {
                "launcher": systems[system]["launcher"],
                "launcher_runtime_authority_descriptor": systems[system][
                    "launcher_runtime_authority_descriptor"
                ],
                "launcher_runtime_authority_sha256": systems[system][
                    "launcher_runtime_authority_sha256"
                ],
                "launcher_invocation_sha256": invocation["invocation_sha256"],
            }
            for system in SYSTEMS
        },
    }
    protocol["protocol_binding_sha256"] = canonical_sha(protocol)
    backend = {
        "schema_version": 3,
        "artifact_kind": (
            "vast_full_publication_backend_runtime_qualification_binding_v3"
        ),
        "source_status": "accepted_persisted_physical_q4_qualification",
        "source_qualification_scope": (
            "backend_native_runtime_q4_physical_qualification"
        ),
        "authorization_eligible": True,
        "validation_trust_status": "authenticated_persisted_physical_q4_v4",
        "semantic_crossbinding_complete": True,
        "authorization_blockers": [],
        "observed_validator_identity_sha256": validator_sha,
        "qualification_index_sha256": hashlib.sha256(b"q4-index").hexdigest(),
        "catalog_sha256": hashlib.sha256(b"q4-catalog").hexdigest(),
        "binding_index": index,
        "receipts": receipts,
        "upstream_identities": upstream,
        "systems": systems,
        "coverage": {
            "system_count": 4, "runtime_authority_count": 112,
            "runtime_authorities_per_system": 28, "runtime_cell_count": 560,
            "cells_per_system": 140, "validation_request_count": 560,
            "validation_record_count": 560,
        },
        "runtime_authority_leaves": [],
        "runtime_authority_leaf_set_sha256": canonical_sha([]),
        "physical_files": files,
        "physical_files_sha256": canonical_sha(files),
        "production_output_receipt_protocol": protocol,
        "post_run_per_arm_evidence_required": True,
        "configuration_evidence_accepted_mutated": False,
    }
    backend["identity_binding_sha256"] = canonical_sha(backend)
    identity = {
        "schema_version": 2,
        "artifact_kind": "vast_full_publication_identity_artifact_binding",
        "manifest": descriptor(
            "configs/full_publication_identity_artifacts.yaml", "manifest-v3"
        ),
        "bindings": {
            "analytics_model_parity": {
                "binding_sha256": upstream[
                    "model_parity_acceptance_binding_sha256"
                ],
            },
            "analytics_execution_layer": {}, "policy_qualification": {},
            "resource_qualification": {},
            "backend_runtime_qualification": backend,
        },
        "files": files,
        "files_sha256": canonical_sha(files),
    }
    identity["binding_sha256"] = canonical_sha(identity)
    return identity


class BackendRuntimeGrantTests(unittest.TestCase):
    def test_authenticated_persisted_q4_identity_derives_protocol_bound_v3_grant(self) -> None:
        identity = v3_identity()
        grant = backend_runtime_grant_from_identity_artifacts(identity)

        self.assertEqual(grant["schema_version"], 3)
        self.assertEqual(
            grant["artifact_kind"],
            "vast_verified_pre_run_backend_runtime_grant_v3",
        )
        self.assertTrue(assess_pre_run_backend_runtime_grant(grant)["passed"])
        self.assertTrue(backend_launcher_output_receipt_protocol_ready(grant))
        self.assertEqual(len(grant["systems"]), 4)
        self.assertEqual(
            sum(len(item["qualified_cells"]) for item in grant["systems"].values()),
            560,
        )

    def test_v3_protocol_file_and_launcher_crossbinding_tamper_fail_closed(self) -> None:
        for mutation in ("protocol_file", "launcher_authority"):
            identity = v3_identity()
            backend = identity["bindings"]["backend_runtime_qualification"]
            if mutation == "protocol_file":
                backend["production_output_receipt_protocol"]["protocol_files"][
                    "production_output_transaction"
                ]["sha256"] = "f" * 64
                backend["production_output_receipt_protocol"].pop(
                    "protocol_binding_sha256"
                )
                backend["production_output_receipt_protocol"][
                    "protocol_binding_sha256"
                ] = canonical_sha(
                    backend["production_output_receipt_protocol"]
                )
            else:
                backend["production_output_receipt_protocol"]["systems"][
                    SYSTEMS[0]
                ]["launcher_runtime_authority_sha256"] = "f" * 64
                backend["production_output_receipt_protocol"].pop(
                    "protocol_binding_sha256"
                )
                backend["production_output_receipt_protocol"][
                    "protocol_binding_sha256"
                ] = canonical_sha(
                    backend["production_output_receipt_protocol"]
                )
            backend.pop("identity_binding_sha256")
            backend["identity_binding_sha256"] = canonical_sha(backend)
            identity.pop("binding_sha256")
            identity["binding_sha256"] = canonical_sha(identity)
            with self.subTest(mutation=mutation):
                with self.assertRaises(BackendRuntimeGrantError):
                    backend_runtime_grant_from_identity_artifacts(identity)

    def test_derives_exact_self_hashed_v2_grant_from_validated_identity(self) -> None:
        identity = v2_identity()
        grant = backend_runtime_grant_from_identity_artifacts(identity)

        self.assertEqual(grant["schema_version"], 2)
        self.assertEqual(
            grant["artifact_kind"],
            "vast_verified_pre_run_backend_runtime_grant",
        )
        self.assertEqual(
            grant["identity_artifact_binding_sha256"], identity["binding_sha256"]
        )
        self.assertEqual(grant["coverage"]["runtime_cell_count"], 560)
        self.assertEqual(set(grant["systems"]), set(SYSTEMS))
        self.assertEqual(
            grant["upstream_identities"][
                "model_parity_acceptance_binding_sha256"
            ],
            identity["bindings"]["analytics_model_parity"]["binding_sha256"],
        )
        self.assertTrue(validate_pre_run_backend_runtime_grant(grant))
        self.assertTrue(assess_pre_run_backend_runtime_grant(grant)["passed"])

    def test_legacy_schema1_identity_is_rejected_before_backend_promotion(self) -> None:
        identity = v2_identity()
        identity["schema_version"] = 1
        identity.pop("binding_sha256")
        identity["binding_sha256"] = canonical_sha(identity)

        with self.assertRaisesRegex(BackendRuntimeGrantError, "schema-2"):
            backend_runtime_grant_from_identity_artifacts(identity)

    def test_backend_upstream_must_bind_nested_physical_parity_acceptance(self) -> None:
        identity = v2_identity()
        backend = identity["bindings"]["backend_runtime_qualification"]
        backend["upstream_identities"][
            "model_parity_acceptance_binding_sha256"
        ] = "0" * 64
        for system in SYSTEMS:
            system_value = backend["systems"][system]
            system_value["runtime_binding_identity_sha256"] = runtime_binding_identity(
                system=system,
                launcher=system_value["launcher"],
                launcher_invocation=system_value["launcher_invocation"],
                upstream_identities=backend["upstream_identities"],
            )
        identity.pop("binding_sha256")
        identity["binding_sha256"] = canonical_sha(identity)

        with self.assertRaisesRegex(BackendRuntimeGrantError, "model parity acceptance"):
            backend_runtime_grant_from_identity_artifacts(identity)

    def test_current_v1_backend_binding_cannot_be_promoted(self) -> None:
        identity = v2_identity()
        backend = identity["bindings"]["backend_runtime_qualification"]
        backend.clear()
        backend.update(
            {
                "binding_index": descriptor("accepted/index.json", "v1-index"),
                "receipts": {
                    system: descriptor(f"accepted/{system}.json", f"v1:{system}")
                    for system in SYSTEMS
                },
            }
        )
        identity["files"] = [backend["binding_index"], *backend["receipts"].values()]
        identity["files_sha256"] = canonical_sha(identity["files"])
        identity.pop("binding_sha256")
        identity["binding_sha256"] = canonical_sha(identity)

        with self.assertRaisesRegex(BackendRuntimeGrantError, "backend qualification v2"):
            backend_runtime_grant_from_identity_artifacts(identity)

    def test_identity_self_hash_and_descriptor_membership_are_required(self) -> None:
        identity = v2_identity()
        identity["binding_sha256"] = "0" * 64
        with self.assertRaisesRegex(BackendRuntimeGrantError, "self-hash"):
            backend_runtime_grant_from_identity_artifacts(identity)

        identity = v2_identity()
        identity["files"].pop()
        identity["files_sha256"] = canonical_sha(identity["files"])
        identity.pop("binding_sha256")
        identity["binding_sha256"] = canonical_sha(identity)
        with self.assertRaisesRegex(BackendRuntimeGrantError, "unbound"):
            backend_runtime_grant_from_identity_artifacts(identity)

    def test_missing_duplicate_relabelled_and_raw_evidence_drift_fail_closed(self) -> None:
        mutations = []
        missing = v2_identity()
        missing["bindings"]["backend_runtime_qualification"]["systems"][SYSTEMS[0]]["qualified_cells"].pop()
        mutations.append(missing)
        duplicate = v2_identity()
        cells = duplicate["bindings"]["backend_runtime_qualification"]["systems"][SYSTEMS[0]]["qualified_cells"]
        cells[-1] = copy.deepcopy(cells[0])
        mutations.append(duplicate)
        relabelled = v2_identity()
        relabelled["bindings"]["backend_runtime_qualification"]["systems"][SYSTEMS[0]]["qualified_cells"][0]["system"] = SYSTEMS[1]
        mutations.append(relabelled)
        evidence_drift = v2_identity()
        evidence_drift["bindings"]["backend_runtime_qualification"]["systems"][SYSTEMS[0]]["qualified_cells"][0]["raw_evidence"]["sha256"] = "f" * 64
        mutations.append(evidence_drift)

        for position, identity in enumerate(mutations):
            with self.subTest(position=position):
                identity.pop("binding_sha256")
                identity["binding_sha256"] = canonical_sha(identity)
                with self.assertRaises(BackendRuntimeGrantError):
                    backend_runtime_grant_from_identity_artifacts(identity)

    def test_launcher_must_be_dedicated_publication_capable_and_exact(self) -> None:
        for field, value in (
            ("launcher_kind", "engineering_probe"),
            ("publication_capable", False),
        ):
            identity = v2_identity()
            identity["bindings"]["backend_runtime_qualification"]["systems"][SYSTEMS[0]][field] = value
            identity.pop("binding_sha256")
            identity["binding_sha256"] = canonical_sha(identity)
            with self.subTest(field=field):
                with self.assertRaisesRegex(BackendRuntimeGrantError, "launcher"):
                    backend_runtime_grant_from_identity_artifacts(identity)

    def test_launcher_and_raw_evidence_must_be_members_of_identity_file_set(self) -> None:
        for target_path in (
            "scripts/checkpoint_deepstream_publication_launcher.py",
            "accepted/backend/deepstream/cells/000.json",
        ):
            identity = v2_identity()
            identity["files"] = [
                item for item in identity["files"] if item["path"] != target_path
            ]
            identity["files_sha256"] = canonical_sha(identity["files"])
            identity.pop("binding_sha256")
            identity["binding_sha256"] = canonical_sha(identity)
            with self.subTest(target_path=target_path):
                with self.assertRaisesRegex(BackendRuntimeGrantError, "unbound"):
                    backend_runtime_grant_from_identity_artifacts(identity)

    def test_grant_validator_rejects_every_authorization_boundary_drift(self) -> None:
        grant = backend_runtime_grant_from_identity_artifacts(v2_identity())
        mutations = []
        extra = copy.deepcopy(grant)
        extra["extra"] = True
        mutations.append(extra)
        self_hash = copy.deepcopy(grant)
        self_hash["grant_sha256"] = "0" * 64
        mutations.append(self_hash)
        cell = copy.deepcopy(grant)
        cell["systems"][SYSTEMS[0]]["qualified_cells"][0]["deadline_ms"] = 75
        cell.pop("grant_sha256")
        cell["grant_sha256"] = canonical_sha(cell)
        mutations.append(cell)
        launcher = copy.deepcopy(grant)
        launcher["systems"][SYSTEMS[0]]["launcher"]["sha256"] = "1" * 64
        mutations.append(launcher)

        for position, value in enumerate(mutations):
            with self.subTest(position=position):
                assessment = assess_pre_run_backend_runtime_grant(value)
                self.assertFalse(assessment["passed"])
                with self.assertRaises(BackendRuntimeGrantError):
                    validate_pre_run_backend_runtime_grant(value)


if __name__ == "__main__":
    unittest.main()
