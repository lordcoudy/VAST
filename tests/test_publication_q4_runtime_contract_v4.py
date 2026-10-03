from __future__ import annotations

import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from backend_publication_launcher_invocation_v3 import (  # noqa: E402
    publication_launcher_invocation_v3_contract,
)
import publication_q4_runtime_contract_v4 as target  # noqa: E402


def sha(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    ).hexdigest()


def descriptor(path: str, marker: str) -> dict[str, object]:
    payload = marker.encode("ascii")
    return {
        "path": path,
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def typed_ref(
    *, path: str, marker: str, schema_version: int, artifact_kind: str
) -> dict[str, object]:
    return {
        "artifact_schema_version": schema_version,
        "artifact_kind": artifact_kind,
        "descriptor": descriptor(path, marker),
        "content_identity_sha256": hashlib.sha256(
            f"semantic:{marker}".encode("ascii")
        ).hexdigest(),
    }


def dataset(codec: str) -> dict[str, object]:
    front = hashlib.sha256(f"front:{codec}".encode("ascii")).hexdigest()
    underbody = hashlib.sha256(f"underbody:{codec}".encode("ascii")).hexdigest()
    unsigned: dict[str, object] = {
        "schema_version": 4,
        "artifact_kind": target.DATASET_BINDING_KIND,
        "status": "frozen_publication_codec_corpus",
        "codec_variant": codec,
        "dataset": {
            "name": f"kpp_iss_publication_v3_{codec}",
            "codec_variant": codec,
            "logical_stream_instances": 6,
            "streams": [
                {
                    "stream_id": index,
                    "codec_name": codec,
                    "sha256": front if index < 5 else underbody,
                }
                for index in range(6)
            ],
        },
    }
    return {**unsigned, "dataset_binding_sha256": sha(unsigned)}


def runtime_template(system: str, policy: str, codec: str) -> dict[str, object]:
    front = hashlib.sha256(f"front:{codec}".encode("ascii")).hexdigest()
    underbody = hashlib.sha256(f"underbody:{codec}".encode("ascii")).hexdigest()
    evidence = target.qualification_launcher_evidence_files_v4(policy)
    common: dict[str, object] = {
        "schema_version": 3,
        "artifact_kind": target.RUNTIME_INPUT_KIND_BY_SYSTEM[system],
        "files": {},
        "source_files": [
            {
                **descriptor(f"datasets/{codec}/front.mp4", f"front:{codec}"),
                "sha256": front,
                "container_path": f"/opt/vast/input/sources/{codec}/front.mp4",
            },
            {
                **descriptor(
                    f"datasets/{codec}/underbody.mp4", f"underbody:{codec}"
                ),
                "sha256": underbody,
                "container_path": f"/opt/vast/input/sources/{codec}/underbody.mp4",
            },
        ],
        "model_files": [],
        "support_files": [],
        "static_hybrid_map": (
            {
                **descriptor("runtime/static-map.json", "static-map"),
                "container_path": "/opt/vast/input/runtime/static-map.json",
            }
            if policy == "static_hybrid"
            else None
        ),
        "container_image": {},
        "container_engine_socket": {},
        "endpoint_sockets": [] if system in {"deepstream", "savant"} else {},
        "scratch_root": "/var/tmp/vast-publication",
        "ready_timeout_s": 300.0,
        "drain_timeout_s": 10.0,
        "start_lead_ms": 100,
        "container_timeout_s": 900.0,
        "defer_full_resource_acceptance": True,
        "evidence_mapping": {name: name for name in evidence},
    }
    if system in {"openvino_gva", "gstreamer_custom"}:
        common.update(
            {
                "embedded_artifacts": {},
                "device_binding": {},
                "preprocessing_contract_sha256": "1" * 64,
                "detect_bin": "vastanalyticsqueue vastanalyticsterminal {branch} "
                "{factory} {model_path} {model_sha256} {weights_sha256} {device}",
                "analytics_queue_max_buffers": 1,
            }
        )
    if system == "openvino_gva":
        common["runtime_files"] = []
    return common


def snapshot(
    coordinate: dict[str, object], dataset_binding: dict[str, object]
) -> dict[str, object]:
    system = str(coordinate["system"])
    policy = str(coordinate["policy"])
    codec = str(coordinate["codec"])
    authority = typed_ref(
        path=(
            f"authorities/{system}/{codec}/{coordinate['topology_kind']}/"
            f"{policy}.json"
        ),
        marker=f"runtime:{system}:{codec}:{coordinate['topology_kind']}:{policy}",
        schema_version=2,
        artifact_kind="vast_backend_publication_runtime_authority_v2",
    )
    launcher = typed_ref(
        path=f"authorities/{system}/launcher.json",
        marker=f"launcher:{system}",
        schema_version=1,
        artifact_kind="vast_backend_publication_launcher_runtime_authority",
    )
    abi = typed_ref(
        path="authorities/publication-launcher-invocation-v3.json",
        marker="publication-launcher-invocation-v3",
        schema_version=3,
        artifact_kind="vast_backend_publication_launcher_invocation_v3",
    )
    invocation = publication_launcher_invocation_v3_contract()
    abi["content_identity_sha256"] = invocation["invocation_sha256"]
    validator = typed_ref(
        path="authorities/q4-validator.json",
        marker="q4-validator",
        schema_version=1,
        artifact_kind="vast_backend_runtime_validator_authority_q4",
    )
    runner = typed_ref(
        path="authorities/q4-runner.json",
        marker="q4-runner",
        schema_version=1,
        artifact_kind="vast_backend_runtime_validation_runner_authority",
    )
    unsigned: dict[str, object] = {
        "schema_version": 4,
        "artifact_kind": target.AUTHORITY_SNAPSHOT_KIND,
        "status": "physically_prepared_non_authorizing_runtime",
        "coordinate": copy.deepcopy(coordinate),
        "dataset_binding_sha256": dataset_binding["dataset_binding_sha256"],
        "upstream_identities": {
            field: hashlib.sha256(field.encode("ascii")).hexdigest()
            for field in target.UPSTREAM_IDENTITY_FIELDS
        },
        "runtime_authority_ref": authority,
        "runtime_authority_sha256": authority["content_identity_sha256"],
        "runtime_authority_set_sha256": hashlib.sha256(
            f"set:{system}".encode("ascii")
        ).hexdigest(),
        "runtime_binding_identity_v4_sha256": hashlib.sha256(
            f"binding:{system}".encode("ascii")
        ).hexdigest(),
        "launcher_runtime_authority_ref": launcher,
        "launcher_runtime_authority_sha256": launcher[
            "content_identity_sha256"
        ],
        "publication_launcher_invocation_v3_ref": abi,
        "publication_launcher_invocation_v3": invocation,
        "q4_validator_authority_ref": validator,
        "q4_validator_authority_sha256": validator["content_identity_sha256"],
        "runner_authority_ref": runner,
        "runner_authority_sha256": runner["content_identity_sha256"],
        "runner_invocation_identity_sha256": hashlib.sha256(
            b"runner-invocation"
        ).hexdigest(),
        "runtime_input_template": runtime_template(system, policy, codec),
    }
    return {**unsigned, "authority_snapshot_sha256": sha(unsigned)}


class PublicationQ4RuntimeContractV4Tests(unittest.TestCase):
    def coordinate(self, index: int = 0) -> dict[str, object]:
        return target.coordinate_for_q4_cell_index_v4(index)

    def build(self, index: int = 0) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
        coordinate = self.coordinate(index)
        data = dataset(str(coordinate["codec"]))
        authority_coordinate = {
            key: coordinate[key]
            for key in ("system", "codec", "topology_kind", "policy")
        }
        authority = snapshot(authority_coordinate, data)
        contract = target.build_publication_runtime_contract_v4(
            coordinate=coordinate,
            authority_snapshot=authority,
            dataset_binding=data,
            run_id=f"q4-runtime-v4-{index:04d}",
            duration_s=180,
        )
        return contract, authority, data

    def test_all_frozen_560_coordinates_build_deterministically(self) -> None:
        observed = []
        for index in range(560):
            contract, authority, data = self.build(index)
            rebuilt = target.build_publication_runtime_contract_v4(
                coordinate=self.coordinate(index),
                authority_snapshot=authority,
                dataset_binding=data,
                run_id=f"q4-runtime-v4-{index:04d}",
                duration_s=180,
            )
            self.assertEqual(contract, rebuilt)
            self.assertEqual(contract["coordinate"]["cell_index"], index)
            self.assertFalse(contract["authorization_eligible"])
            self.assertFalse(contract["execution_authorized"])
            observed.append(contract["contract_sha256"])
        self.assertEqual(len(set(observed)), 560)

    def test_round_trip_binds_runtime_dataset_authority_run_and_duration(self) -> None:
        contract, authority, data = self.build(559)
        checked = target.validate_publication_runtime_contract_v4(
            contract,
            coordinate=self.coordinate(559),
            authority_snapshot=authority,
            dataset_binding=data,
            run_id="q4-runtime-v4-0559",
            duration_s=180,
        )
        self.assertEqual(checked, contract)
        runtime = checked["runtime_inputs"]
        graph = checked["native_graph_contract"]
        self.assertEqual(runtime["run_id"], "q4-runtime-v4-0559")
        self.assertEqual(runtime["duration_s"], 180)
        self.assertEqual(runtime["dataset"]["codec_variant"], "h265")
        self.assertEqual(
            runtime["dataset"][target.RUNTIME_INPUT_KEY_BY_SYSTEM["gstreamer_custom"]][
                "artifact_kind"
            ],
            target.RUNTIME_INPUT_KIND_BY_SYSTEM["gstreamer_custom"],
        )
        self.assertEqual(
            graph["authority_snapshot_sha256"],
            authority["authority_snapshot_sha256"],
        )
        self.assertEqual(
            graph["dataset_binding_sha256"], data["dataset_binding_sha256"]
        )
        self.assertNotIn("replay_result", graph)

    def test_static_hybrid_and_adaptive_evidence_are_policy_exact(self) -> None:
        static_index = next(
            index
            for index in range(560)
            if self.coordinate(index)["policy"] == "static_hybrid"
        )
        adaptive_index = next(
            index
            for index in range(560)
            if self.coordinate(index)["policy"] == "adaptive_weights"
        )
        static, _, _ = self.build(static_index)
        adaptive, _, _ = self.build(adaptive_index)
        static_runtime = static["runtime_inputs"]["dataset"][
            target.RUNTIME_INPUT_KEY_BY_SYSTEM[str(static["coordinate"]["system"])]
        ]
        self.assertIsInstance(static_runtime["static_hybrid_map"], dict)
        self.assertIn(
            "publication_policy_feedback.jsonl",
            adaptive["native_graph_contract"]["launcher_evidence_files"],
        )

    def test_coherently_resealed_snapshot_cannot_bypass_physical_replay(self) -> None:
        coordinate = self.coordinate(0)
        data = dataset(str(coordinate["codec"]))
        authority = snapshot(
            {
                key: coordinate[key]
                for key in ("system", "codec", "topology_kind", "policy")
            },
            data,
        )
        authority["runtime_input_template"][
            "defer_full_resource_acceptance"
        ] = False
        unsigned = {
            key: item
            for key, item in authority.items()
            if key != "authority_snapshot_sha256"
        }
        authority["authority_snapshot_sha256"] = sha(unsigned)
        with self.assertRaises(target.PublicationQ4RuntimeContractV4Error):
            target.build_publication_runtime_contract_v4(
                coordinate=coordinate,
                authority_snapshot=authority,
                dataset_binding=data,
                run_id="q4-runtime-v4-defer-drift",
                duration_s=180,
            )

    def test_every_identity_or_coordinate_drift_fails_closed(self) -> None:
        contract, authority, data = self.build(0)
        mutations: list[tuple[str, object, object, object, str, int]] = []
        wrong_coordinate = copy.deepcopy(self.coordinate(0))
        wrong_coordinate["cell_index"] = 1
        mutations.append(
            ("coordinate", contract, authority, data, "q4-runtime-v4-0000", 180)
        )
        broken_authority = copy.deepcopy(authority)
        broken_authority["runtime_authority_sha256"] = "f" * 64
        mutations.append(
            ("authority", contract, broken_authority, data, "q4-runtime-v4-0000", 180)
        )
        broken_data = copy.deepcopy(data)
        broken_data["dataset"]["streams"][5]["sha256"] = "e" * 64
        mutations.append(
            ("dataset", contract, authority, broken_data, "q4-runtime-v4-0000", 180)
        )
        for label, value, candidate_authority, candidate_data, run_id, duration in mutations:
            with self.subTest(label=label):
                coordinate = (
                    wrong_coordinate if label == "coordinate" else self.coordinate(0)
                )
                with self.assertRaises(target.PublicationQ4RuntimeContractV4Error):
                    target.validate_publication_runtime_contract_v4(
                        value,
                        coordinate=coordinate,
                        authority_snapshot=candidate_authority,
                        dataset_binding=candidate_data,
                        run_id=run_id,
                        duration_s=duration,
                    )
        with self.assertRaises(target.PublicationQ4RuntimeContractV4Error):
            target.validate_publication_runtime_contract_v4(
                contract,
                coordinate=self.coordinate(0),
                authority_snapshot=authority,
                dataset_binding=data,
                run_id="different-run",
                duration_s=180,
            )
        with self.assertRaises(target.PublicationQ4RuntimeContractV4Error):
            target.build_publication_runtime_contract_v4(
                coordinate=self.coordinate(0),
                authority_snapshot=authority,
                dataset_binding=data,
                run_id="q4-runtime-v4-0000",
                duration_s=179,
            )

    def test_registry_rejects_mixed_global_trust_domains(self) -> None:
        datasets = [dataset(codec) for codec in target.CODECS]
        snapshots = []
        for system in target.SYSTEMS:
            for codec in target.CODECS:
                for topology in target.TOPOLOGIES:
                    for policy in target.POLICIES:
                        snapshots.append(
                            snapshot(
                                {
                                    "system": system,
                                    "codec": codec,
                                    "topology_kind": topology,
                                    "policy": policy,
                                },
                                datasets[target.CODECS.index(codec)],
                            )
                        )
        unsigned = {
            "schema_version": 4,
            "artifact_kind": target.RUNTIME_CANDIDATE_REGISTRY_KIND,
            "status": "physically_prepared_runtime_candidates",
            "accepted_as_input": True,
            "authorization_eligible": False,
            "execution_authorized": False,
            "dataset_bindings": datasets,
            "authority_snapshots": snapshots,
        }
        registry = {**unsigned, "registry_sha256": sha(unsigned)}
        target.validate_publication_q4_runtime_candidate_registry_v4(registry)

        mixed = copy.deepcopy(registry)
        mixed_snapshot = mixed["authority_snapshots"][1]
        mixed_snapshot["upstream_identities"][
            target.UPSTREAM_IDENTITY_FIELDS[0]
        ] = "f" * 64
        mixed_unsigned = {
            key: item
            for key, item in mixed_snapshot.items()
            if key != "authority_snapshot_sha256"
        }
        mixed_snapshot["authority_snapshot_sha256"] = sha(mixed_unsigned)
        registry_unsigned = {
            key: item for key, item in mixed.items() if key != "registry_sha256"
        }
        mixed["registry_sha256"] = sha(registry_unsigned)
        with self.assertRaises(target.PublicationQ4RuntimeContractV4Error):
            target.validate_publication_q4_runtime_candidate_registry_v4(mixed)

    def test_public_registry_builder_is_deterministic_and_closed(self) -> None:
        datasets = [dataset(codec) for codec in target.CODECS]
        snapshots = [
            snapshot(
                {
                    "system": system,
                    "codec": codec,
                    "topology_kind": topology,
                    "policy": policy,
                },
                datasets[target.CODECS.index(codec)],
            )
            for system in target.SYSTEMS
            for codec in target.CODECS
            for topology in target.TOPOLOGIES
            for policy in target.POLICIES
        ]
        registry = target.build_publication_q4_runtime_candidate_registry_v4(
            dataset_bindings=datasets,
            authority_snapshots=snapshots,
        )
        self.assertEqual(
            target.validate_publication_q4_runtime_candidate_registry_v4(registry),
            registry,
        )
        self.assertEqual(
            target.build_publication_q4_runtime_candidate_registry_v4(
                dataset_bindings=datasets,
                authority_snapshots=snapshots,
            ),
            registry,
        )
        with self.assertRaises(target.PublicationQ4RuntimeContractV4Error):
            target.build_publication_q4_runtime_candidate_registry_v4(
                dataset_bindings=datasets,
                authority_snapshots=list(reversed(snapshots)),
            )

    def test_public_dataset_binding_builder_fixes_six_stream_roles(self) -> None:
        front = hashlib.sha256(b"front").hexdigest()
        underbody = hashlib.sha256(b"underbody").hexdigest()
        binding = target.build_publication_q4_dataset_binding_v4(
            codec_variant="h265",
            front_gate_sha256=front,
            underbody_sha256=underbody,
        )
        self.assertEqual(
            [item["sha256"] for item in binding["dataset"]["streams"]],
            [front, front, front, front, front, underbody],
        )
        with self.assertRaises(target.PublicationQ4RuntimeContractV4Error):
            target.build_publication_q4_dataset_binding_v4(
                codec_variant="h265",
                front_gate_sha256=front,
                underbody_sha256=front,
            )


if __name__ == "__main__":
    unittest.main()
