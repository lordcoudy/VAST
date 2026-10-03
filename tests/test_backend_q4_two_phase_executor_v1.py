from __future__ import annotations

import copy
import hashlib
import io
import json
import os
import socket
import stat
import sys
import tempfile
import threading
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import backend_q4_two_phase_executor_v1 as target  # noqa: E402
import publication_physical_io_v1 as physical_io  # noqa: E402


class InjectedCrash(BaseException):
    pass


def canonical(value: object) -> bytes:
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("ascii")


def write_json(path: Path, value: dict[str, object]) -> dict[str, object]:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical(value)
    path.write_bytes(payload)
    return {
        "path": path.relative_to(path.parents[len(path.parts) - 1]).as_posix(),
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def descriptor(root: Path, path: Path) -> dict[str, object]:
    payload = path.read_bytes()
    return {
        "path": path.relative_to(root).as_posix(),
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def identity(label: str) -> str:
    return hashlib.sha256(label.encode("ascii")).hexdigest()


def accepted_guardian_pins(
    contract: dict[str, object], receipt: dict[str, object],
) -> dict[str, object]:
    authority = {
        "schema_version": 1,
        "artifact_kind": (
            "vast_guardian_accepted_policy_preprocessing_contract_authority_v1"
        ),
        "preprocessing_contract_content_sha256": identity("preprocessing"),
        "preprocessing_contract_file_sha256": contract["sha256"],
        "materialization_receipt_identity_sha256": identity("receipt"),
        "materialization_receipt_file_sha256": receipt["sha256"],
        "predecessor_qualification_preprocessing_receipt_identity_sha256": identity(
            "predecessor-receipt"
        ),
        "predecessor_qualification_preprocessing_receipt_file_sha256": identity(
            "predecessor-receipt-file"
        ),
        "accepted_policy_qualification_receipt_identity_sha256": identity(
            "policy-receipt"
        ),
        "accepted_policy_qualification_receipt_file_sha256": identity(
            "policy-receipt-file"
        ),
        "accepted_policy_capability_manifest_file_sha256": identity(
            "policy-capability-file"
        ),
        "accepted_policy_capability_manifest_content_sha256": identity(
            "policy-capability"
        ),
        "accepted_policy_calibration_mapping_file_sha256": identity(
            "policy-calibration-file"
        ),
        "accepted_policy_calibration_mapping_content_sha256": identity(
            "policy-calibration"
        ),
        "qualification_execution_closure_receipt_identity_sha256": identity(
            "execution-closure"
        ),
        "qualification_execution_closure_receipt_file_sha256": identity(
            "execution-closure-file"
        ),
        "execution_config_identity_sha256": identity("execution-config"),
        "execution_config_file_sha256": identity("execution-config-file"),
        "binding_set_identity_sha256": identity("binding-set"),
        "bindings_identity_sha256": identity("bindings"),
        "binding_set_index_file_sha256": identity("binding-index-file"),
        "binding_preprocessing_consensus_sha256": identity(
            "binding-preprocessing-consensus"
        ),
        "worker_image_ids": {
            "cpu": "sha256:" + "1" * 64,
            "gpu": "sha256:" + "2" * 64,
        },
        "policy_contract_sha256": identity("policy-contract"),
    }
    return {
        "preprocessing_contract": contract,
        "preprocessing_receipt": receipt,
        "preprocessing_authority": authority,
        "preprocessing_authority_sha256": hashlib.sha256(
            canonical(authority)[:-1]
        ).hexdigest(),
        "service_identity_sha256": identity("analytics-service"),
        "policy_contract_sha256": authority["policy_contract_sha256"],
    }


class FakePipeline:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.events: list[tuple[str, int | None]] = []
        self.qualification_calls: list[int] = []
        self.production_calls: list[int] = []
        self.pin_calls = 0
        self.fail_production_with_fence = False
        self.identity: dict[str, object] | None = None
        self.grant: dict[str, object] | None = None
        self.q4: dict[str, object] | None = None

    def recheck_pins(self, **kwargs: object) -> dict[str, object]:
        self.pin_calls += 1
        registry = kwargs["source_registry"]
        return {
            "status": "verified",
            "source_registry_sha256": registry["registry_sha256"],
            "file_set_sha256": hashlib.sha256(
                canonical(registry["files"])[:-1]
            ).hexdigest(),
            "socket_set_sha256": hashlib.sha256(
                canonical(registry["sockets"])[:-1]
            ).hexdigest(),
            "image_set_sha256": hashlib.sha256(
                canonical(registry["images"])[:-1]
            ).hexdigest(),
        }

    def materialize_qualification_input(self, **kwargs: object) -> dict[str, object]:
        cell = kwargs["cell"]
        self.events.append(("materialize", cell.cell_index))
        return {
            "runtime_inputs": {
                "system": cell.system,
                "codec": cell.codec,
                "topology_kind": cell.topology_kind,
                "policy": cell.policy,
                "deadline_ms": cell.deadline_ms,
                "warmup_s": 30,
                "measurement_s": 180,
                "streams": 6,
                "seed": 20260323,
            }
        }

    def run_native_qualification(self, **kwargs: object) -> dict[str, object]:
        cell = kwargs["cell"]
        output = kwargs["output_dir"]
        self.qualification_calls.append(cell.cell_index)
        self.events.append(("qualify", cell.cell_index))
        evidence = output / "raw-evidence.json"
        evidence.write_bytes(canonical({
            "cell_index": cell.cell_index,
            "scope": "native_qualification_only",
        }))
        return {
            "exit_code": 0,
            "raw_evidence_path": evidence,
            "qualification_request": {"cell_index": cell.cell_index},
            "validation_record_candidate": {"cell_index": cell.cell_index},
        }

    def finalize_qualification_graph(self, **kwargs: object) -> dict[str, object]:
        records = kwargs["phase_a_records"]
        self.events.append(("graph", None))
        self.assert_exact_records(records)
        catalog = kwargs["graph_dir"] / "q4-catalog.json"
        catalog.parent.mkdir(parents=True, exist_ok=True)
        catalog.write_bytes(canonical({
            "schema_version": 1,
            "artifact_kind": "fake_q4_catalog",
            "record_count": 560,
        }))
        return {"catalog_path": catalog}

    @staticmethod
    def assert_exact_records(records: object) -> None:
        assert isinstance(records, list)
        assert len(records) == 560
        assert [item["coordinate"]["cell_index"] for item in records] == list(range(560))

    def promote_qualification(self, **kwargs: object) -> dict[str, object]:
        self.events.append(("promote", None))
        output = Path(kwargs["output_dir"])
        output.mkdir(parents=True, exist_ok=True)
        receipts: dict[str, dict[str, object]] = {}
        for system in target.SYSTEMS:
            path = output / f"checkpoint_{system}_backend_runtime_qualification_v4_receipt.json"
            path.write_bytes(canonical({"system": system, "accepted": True}))
            receipts[system] = descriptor(self.root, path)
        index = output / target.Q4_BINDING_INDEX_FILENAME
        index.write_bytes(canonical({"schema_version": 4, "accepted": True}))
        return {
            "binding_index_descriptor": descriptor(self.root, index),
            "receipt_descriptors": receipts,
        }

    def load_qualification(self, **kwargs: object) -> dict[str, object]:
        self.events.append(("load-q4", None))
        path = self.root / str(kwargs["binding_index_path"])
        value = {
            "schema_version": 3,
            "artifact_kind": "vast_full_publication_backend_runtime_qualification_binding_v3",
            "authorization_eligible": True,
            "validation_trust_status": "authenticated_persisted_physical_q4_v4",
            "semantic_crossbinding_complete": True,
            "authorization_blockers": [],
            "binding_index": descriptor(self.root, path),
        }
        self.q4 = value
        return value

    def build_identity_manifest(self, **kwargs: object) -> dict[str, object]:
        self.events.append(("identity", None))
        self.assert_event_order()
        output = Path(kwargs["output_path"])
        output.write_bytes(canonical({"identity": "accepted-q4"}))
        identity = {
            "schema_version": 2,
            "artifact_kind": "vast_full_publication_identity_artifact_binding",
            "bindings": {"backend_runtime_qualification": self.q4},
            "binding_sha256": hashlib.sha256(b"identity").hexdigest(),
        }
        self.identity = identity
        return {"manifest_path": str(output), "binding": identity}

    def load_identity(self, **kwargs: object) -> dict[str, object]:
        assert self.identity is not None
        return dict(self.identity)

    def build_grant(self, identity: dict[str, object]) -> dict[str, object]:
        self.events.append(("grant", None))
        assert identity == self.identity
        grant = {
            "schema_version": 3,
            "artifact_kind": target.GRANT_V3_KIND,
            "identity_artifact_binding_sha256": identity["binding_sha256"],
            "grant_sha256": hashlib.sha256(b"grant").hexdigest(),
        }
        self.grant = grant
        return grant

    def validate_grant(self, grant: dict[str, object]) -> dict[str, object]:
        assert grant == self.grant
        return dict(grant)

    def execute_production_arm(self, **kwargs: object) -> dict[str, object]:
        cell = kwargs["cell"]
        transaction = kwargs["transaction_dir"]
        self.events.append(("production", cell.cell_index))
        assert kwargs["backend_runtime_grant"] == self.grant
        transaction.mkdir(parents=True, exist_ok=True)
        arm = transaction / target.ARM_CONTRACT_FILENAME
        arm.write_bytes(canonical({"cell_index": cell.cell_index}))
        fence = transaction / target.LAUNCH_FENCE_FILENAME
        fence.write_bytes(canonical({"cell_index": cell.cell_index}))
        self.production_calls.append(cell.cell_index)
        if self.fail_production_with_fence and cell.cell_index == 0:
            return {"exit_code": 75, "blockers": ["injected-transient"]}
        receipt = transaction / target.OUTPUT_RECEIPT_FILENAME
        receipt.write_bytes(canonical({"cell_index": cell.cell_index}))
        return {
            "exit_code": 0,
            "authority": {
                "schema_version": 3,
                "artifact_kind": "fake_production_authority_v3",
                "coordinate": cell.coordinate,
                "authority_sha256": hashlib.sha256(
                    f"authority:{cell.cell_index}".encode("ascii")
                ).hexdigest(),
            },
        }

    def persist_authority(self, **kwargs: object) -> dict[str, object]:
        output = Path(kwargs["output_path"])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(canonical(dict(kwargs["authority"])))
        return descriptor(self.root, output)

    def build_sizing_input(self, **kwargs: object) -> dict[str, object]:
        pairs = kwargs["pairs"]
        assert len(pairs) == 280
        assert all(set(item["arms"]) == set(target.TOPOLOGIES) for item in pairs)
        return {
            "schema_version": 1,
            "artifact_kind": "fake_pair_sizing_input",
            "pairs": pairs,
            "coverage": {"pair_count": 280, "topology_arm_count": 560},
        }

    def materialize_sizing(self, **kwargs: object) -> dict[str, object]:
        self.events.append(("sizing", None))
        output = Path(kwargs["output_dir"])
        output.mkdir(parents=True, exist_ok=True)
        index = output / "checkpoint_backend_pair_archive_sizing_index_v1.json"
        index.write_bytes(canonical({"pair_count": 280}))
        return {
            "index": descriptor(self.root, index),
            "sizing_rows": [{"row": position} for position in range(280)],
        }

    def load_sizing(self, **_: object) -> list[dict[str, object]]:
        return [{"row": position} for position in range(280)]

    def assert_event_order(self) -> None:
        labels = [event[0] for event in self.events]
        assert labels.count("qualify") == 560
        assert labels.index("graph") > max(
            position for position, label in enumerate(labels) if label == "qualify"
        )
        assert labels.index("promote") > labels.index("graph")
        assert labels.index("load-q4") > labels.index("promote")

    def dependencies(self) -> target.BackendQ4TwoPhaseDependenciesV1:
        return target.BackendQ4TwoPhaseDependenciesV1(
            recheck_pins=self.recheck_pins,
            materialize_qualification_input=self.materialize_qualification_input,
            run_native_qualification=self.run_native_qualification,
            finalize_qualification_graph=self.finalize_qualification_graph,
            promote_qualification=self.promote_qualification,
            load_qualification=self.load_qualification,
            build_identity_manifest=self.build_identity_manifest,
            load_identity=self.load_identity,
            build_backend_grant=self.build_grant,
            validate_backend_grant=self.validate_grant,
            execute_production_arm=self.execute_production_arm,
            persist_production_authority=self.persist_authority,
            build_pair_sizing_input=self.build_sizing_input,
            materialize_pair_sizing=self.materialize_sizing,
            load_pair_sizing=self.load_sizing,
        )


def source_registry(root: Path) -> Path:
    sources = root / "accepted-sources"
    sources.mkdir()
    files_by_name: dict[str, dict[str, object]] = {}
    for name in ("model.json", "policy.json", "resource.json", "runtime.json"):
        path = sources / name
        path.write_bytes(canonical({"accepted": name}))
        files_by_name[name] = descriptor(root, path)
    contract_path = sources / "accepted-preprocessing.json"
    contract_path.write_bytes(canonical({"accepted": "preprocessing"}))
    receipt_path = sources / "accepted-preprocessing-receipt.json"
    receipt_path.write_bytes(canonical({"accepted": "preprocessing-receipt"}))
    contract = descriptor(root, contract_path)
    receipt = descriptor(root, receipt_path)
    files = sorted(
        [*files_by_name.values(), contract, receipt],
        key=lambda item: str(item["path"]),
    )
    unsigned = {
        "schema_version": 1,
        "artifact_kind": "vast_backend_q4_two_phase_source_registry_v1",
        "status": "accepted_reachable_runtime_candidates",
        "accepted": True,
        "model_parity": files_by_name["model.json"],
        "policy_qualification": files_by_name["policy.json"],
        "resource_qualification": files_by_name["resource.json"],
        "runtime_candidate_registry": files_by_name["runtime.json"],
        "analytics_guardian": accepted_guardian_pins(contract, receipt),
        "files": files,
        "sockets": [],
        "images": [],
    }
    value = {
        **unsigned,
        "registry_sha256": hashlib.sha256(canonical(unsigned)[:-1]).hexdigest(),
    }
    path = root / "q4-source-registry.json"
    path.write_bytes(canonical(value))
    return path


def identity_inputs(root: Path) -> dict[str, object]:
    return {
        "analytics_model_parity": {"fixture": "parity"},
        "analytics_execution_layer": {"fixture": "execution"},
        "policy_qualification": {"fixture": "policy"},
        "resource_qualification": {"fixture": "resource"},
    }


class BackendQ4TwoPhaseExecutorV1Tests(unittest.TestCase):
    def execute(
        self,
        root: Path,
        fake: FakePipeline,
        **overrides: object,
    ) -> dict[str, object]:
        kwargs: dict[str, object] = {
            "project_root": root,
            "source_registry_path": source_registry(root),
            "work_dir": root / "q4-work",
            "identity_manifest_output": root / "q4-work/accepted-identity.json",
            "identity_inputs": identity_inputs(root),
            "production_context": {"fixture": "production"},
            "dependencies": fake.dependencies(),
        }
        kwargs.update(overrides)
        return target.execute_backend_q4_two_phase_v1(**kwargs)

    def test_matrix_is_exact_frozen_560_and_pairable_280(self) -> None:
        cells = target.backend_q4_cells_v1()
        self.assertEqual(len(cells), 560)
        self.assertEqual([cell.cell_index for cell in cells], list(range(560)))
        self.assertEqual(len({cell.arm_id for cell in cells}), 560)
        self.assertEqual(
            {
                (cell.system, cell.codec, cell.topology_kind, cell.policy, cell.deadline_ms)
                for cell in cells
            },
            {
                (system, codec, topology, policy, deadline)
                for system in target.SYSTEMS
                for codec in target.CODECS
                for topology in target.TOPOLOGIES
                for policy in target.POLICIES
                for deadline in target.DEADLINES_MS
            },
        )
        self.assertTrue(all(cell.warmup_s == 30 for cell in cells))
        self.assertTrue(all(cell.measurement_s == 180 for cell in cells))
        self.assertTrue(all(cell.streams == 6 for cell in cells))
        self.assertTrue(all(cell.seed == 20260323 for cell in cells))

    def test_phase_b_pair_run_seed_uses_the_frozen_shared_seed_group(self) -> None:
        baseline = target.backend_q4_cells_v1()[0]
        shared = target.backend_q4_cells_v1()[35]
        expected = int(
            hashlib.sha256(
                b"20260323:kpp_iss_publication_v3_codecs_v1::6:0"
            ).hexdigest()[:12],
            16,
        ) % (2**31 - 1)
        self.assertEqual(
            target._backend_q4_run_seed_v1(baseline),  # noqa: SLF001
            expected,
        )
        self.assertEqual(
            target._backend_q4_run_seed_v1(shared),  # noqa: SLF001
            expected,
        )

    def test_default_identity_inputs_are_reloaded_from_same_source_registry(self) -> None:
        import backend_q4_two_phase_source_registry_v1 as source_registry_module

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            registry = {"registry_sha256": "a" * 64}
            path = root / "source-registry.json"
            path.write_bytes(canonical(registry))
            record = descriptor(root, path)
            identity = {
                "analytics_model_parity": {"fixture": "parity"},
                "analytics_execution_layer": {"fixture": "execution"},
                "policy_qualification": {"fixture": "policy"},
                "resource_qualification": {"fixture": "resource"},
            }
            with mock.patch.object(
                source_registry_module,
                "load_backend_q4_two_phase_source_registry_v1",
                return_value={
                    "registry": registry,
                    "identity_inputs": identity,
                    "source_registry": record,
                },
            ) as loader:
                observed = target._default_identity_inputs_from_source_registry_v1(  # noqa: SLF001
                    root=root,
                    source_path=path,
                    expected_registry=registry,
                )
            self.assertEqual(observed, identity)
            loader.assert_called_once_with(
                project_root=root,
                registry_path=path,
            )

    @unittest.skipUnless(os.name == "posix", "dirfd read race requires POSIX")
    def test_held_read_parent_swap_never_accepts_attacker_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            trusted = root / "trusted"
            displaced = root / "trusted-displaced"
            attacker = root / "attacker"
            trusted.mkdir()
            attacker.mkdir()
            source = trusted / "source.json"
            source.write_bytes(canonical({"owner": "trusted"}))
            canary = attacker / "source.json"
            canary.write_bytes(canonical({"owner": "attacker"}))
            original_open = physical_io.os.open
            swapped = False

            def race_open(
                path: object,
                flags: int,
                mode: int = 0o777,
                *,
                dir_fd: int | None = None,
            ) -> int:
                nonlocal swapped
                if (
                    not swapped
                    and path == "source.json"
                    and bool(flags & os.O_RDONLY) is False
                    and dir_fd is not None
                ):
                    swapped = True
                    trusted.rename(displaced)
                    attacker.rename(trusted)
                return original_open(path, flags, mode, dir_fd=dir_fd)

            with target._held_physical_root_v1(root):  # noqa: SLF001
                with (
                    mock.patch.object(
                        physical_io.os, "open", side_effect=race_open
                    ),
                    self.assertRaisesRegex(
                        target.BackendQ4TwoPhaseExecutorV1Error,
                        "parent|directory|changed|custody",
                    ),
                ):
                    target._load_canonical_json(  # noqa: SLF001
                        source, label="held source"
                    )
            self.assertTrue(swapped)
            self.assertEqual(
                (trusted / "source.json").read_bytes(),
                canonical({"owner": "attacker"}),
            )

    @unittest.skipUnless(os.name == "posix", "dirfd write race requires POSIX")
    def test_held_immutable_write_parent_swap_never_overwrites_canary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            trusted = root / "trusted"
            displaced = root / "trusted-displaced"
            attacker = root / "attacker"
            trusted.mkdir()
            attacker.mkdir()
            canary = attacker / "record.json"
            canary.write_bytes(b"attacker-canary\n")
            original_link = physical_io.os.link
            swapped = False

            def race_link(
                source: object,
                destination: object,
                *,
                src_dir_fd: int | None = None,
                dst_dir_fd: int | None = None,
                follow_symlinks: bool = True,
            ) -> None:
                nonlocal swapped
                if not swapped and destination == "record.json":
                    swapped = True
                    trusted.rename(displaced)
                    attacker.rename(trusted)
                original_link(
                    source,
                    destination,
                    src_dir_fd=src_dir_fd,
                    dst_dir_fd=dst_dir_fd,
                    follow_symlinks=follow_symlinks,
                )

            with target._held_physical_root_v1(root):  # noqa: SLF001
                with (
                    mock.patch.object(
                        physical_io, "_rename_noreplace_posix", return_value=False
                    ),
                    mock.patch.object(
                        physical_io.os, "link", side_effect=race_link
                    ),
                    self.assertRaisesRegex(
                        target.BackendQ4TwoPhaseExecutorV1Error,
                        "parent|directory|changed|custody",
                    ),
                ):
                    target._write_immutable_json(  # noqa: SLF001
                        root,
                        trusted / "record.json",
                        {"owner": "executor"},
                        label="held record",
                    )
            self.assertTrue(swapped)
            self.assertEqual(
                (trusted / "record.json").read_bytes(), b"attacker-canary\n"
            )

    @unittest.skipUnless(os.name == "posix", "dirfd replace race requires POSIX")
    def test_held_checkpoint_parent_swap_never_overwrites_canary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            trusted = root / "trusted"
            displaced = root / "trusted-displaced"
            attacker = root / "attacker"
            trusted.mkdir()
            attacker.mkdir()
            checkpoint = trusted / "checkpoint.json"
            checkpoint.write_bytes(canonical({"generation": 1}))
            canary = attacker / "checkpoint.json"
            canary.write_bytes(b"attacker-canary\n")
            original_replace = physical_io.os.replace
            swapped = False

            def race_replace(
                source: object,
                destination: object,
                *,
                src_dir_fd: int | None = None,
                dst_dir_fd: int | None = None,
            ) -> None:
                nonlocal swapped
                if not swapped and dst_dir_fd is not None:
                    swapped = True
                    trusted.rename(displaced)
                    attacker.rename(trusted)
                original_replace(
                    source,
                    destination,
                    src_dir_fd=src_dir_fd,
                    dst_dir_fd=dst_dir_fd,
                )

            with target._held_physical_root_v1(root):  # noqa: SLF001
                with (
                    mock.patch.object(
                        physical_io.os, "replace", side_effect=race_replace
                    ),
                    self.assertRaisesRegex(
                        target.BackendQ4TwoPhaseExecutorV1Error,
                        "parent|directory|changed|custody",
                    ),
                ):
                    target._atomic_checkpoint(  # noqa: SLF001
                        root, checkpoint, {"generation": 2}
                    )
            self.assertTrue(swapped)
            self.assertEqual(
                (trusted / "checkpoint.json").read_bytes(), b"attacker-canary\n"
            )

    @unittest.skipUnless(os.name == "posix", "cold-load race requires POSIX")
    def test_held_immutable_cold_load_rejects_exact_copy_parent_rebind(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            trusted = root / "trusted"
            displaced = root / "trusted-displaced"
            attacker = root / "attacker"
            trusted.mkdir()
            attacker.mkdir()
            payload = canonical({"owner": "executor"})
            (attacker / "record.json").write_bytes(payload)
            original_read = (
                physical_io.PhysicalRootCustodyV1.adopt_exact_durable_identity
            )
            swapped = False

            def race_cold_read(
                custody: object,
                value: object,
                payload: object,
                **kwargs: object,
            ) -> object:
                nonlocal swapped
                if not swapped and Path(value).name == "record.json":
                    swapped = True
                    trusted.rename(displaced)
                    attacker.rename(trusted)
                    try:
                        return original_read(custody, value, payload, **kwargs)
                    finally:
                        trusted.rename(attacker)
                        displaced.rename(trusted)
                return original_read(custody, value, payload, **kwargs)

            with target._held_physical_root_v1(root):  # noqa: SLF001
                with (
                    mock.patch.object(
                        physical_io.PhysicalRootCustodyV1,
                        "adopt_exact_durable_identity",
                        new=race_cold_read,
                    ),
                    self.assertRaisesRegex(
                        target.BackendQ4TwoPhaseExecutorV1Error,
                        "rebound|parent|directory|custody",
                    ),
                ):
                    target._write_immutable_json(  # noqa: SLF001
                        root,
                        trusted / "record.json",
                        {"owner": "executor"},
                        label="cold-load record",
                    )
            self.assertTrue(swapped)
            self.assertEqual((attacker / "record.json").read_bytes(), payload)
            self.assertEqual((trusted / "record.json").read_bytes(), payload)

    @unittest.skipUnless(os.name == "posix", "symlink race requires POSIX")
    def test_held_cold_load_rejects_parent_symlink_rebind(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            trusted = root / "trusted"
            displaced = root / "trusted-displaced"
            attacker = root / "attacker"
            trusted.mkdir()
            attacker.mkdir()
            payload = canonical({"owner": "executor"})
            (attacker / "record.json").write_bytes(payload)
            original_read = (
                physical_io.PhysicalRootCustodyV1.adopt_exact_durable_identity
            )
            swapped = False

            def race_cold_read(
                custody: object,
                value: object,
                payload: object,
                **kwargs: object,
            ) -> object:
                nonlocal swapped
                if not swapped and Path(value).name == "record.json":
                    swapped = True
                    trusted.rename(displaced)
                    trusted.symlink_to(attacker, target_is_directory=True)
                    try:
                        return original_read(custody, value, payload, **kwargs)
                    finally:
                        trusted.unlink()
                        displaced.rename(trusted)
                return original_read(custody, value, payload, **kwargs)

            with target._held_physical_root_v1(root):  # noqa: SLF001
                with (
                    mock.patch.object(
                        physical_io.PhysicalRootCustodyV1,
                        "adopt_exact_durable_identity",
                        new=race_cold_read,
                    ),
                    self.assertRaisesRegex(
                        target.BackendQ4TwoPhaseExecutorV1Error,
                        "physical|parent|directory|custody",
                    ),
                ):
                    target._write_immutable_json(  # noqa: SLF001
                        root,
                        trusted / "record.json",
                        {"owner": "executor"},
                        label="symlink cold-load record",
                    )
            self.assertTrue(swapped)
            self.assertEqual((attacker / "record.json").read_bytes(), payload)
            self.assertEqual((trusted / "record.json").read_bytes(), payload)

    @unittest.skipUnless(os.name == "posix", "atomic crash recovery is POSIX-only")
    def test_immutable_json_recovers_every_physical_publish_window(self) -> None:
        steps = (
            "mid_write",
            "post_fsync_pre_publish",
            "post_publish_pre_parent_fsync",
        )
        for position, step in enumerate(steps):
            with self.subTest(step=step), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                output = root / "authority/record.json"
                value = {"position": position, "step": step}

                def crash(observed: str) -> None:
                    if observed == step:
                        raise InjectedCrash(observed)

                with self.assertRaises(InjectedCrash):
                    target._write_immutable_json(  # noqa: SLF001
                        root,
                        output,
                        value,
                        label=f"faulted authority record {step}",
                        after_publish_step=crash,
                    )
                published_identity = (
                    (output.stat().st_dev, output.stat().st_ino)
                    if output.exists()
                    else None
                )
                observed = target._write_immutable_json(  # noqa: SLF001
                    root,
                    output,
                    value,
                    label=f"resumed authority record {step}",
                )
                self.assertEqual(output.read_bytes(), canonical(value))
                self.assertEqual(observed, descriptor(root, output))
                self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o444)
                self.assertEqual(output.stat().st_nlink, 1)
                if published_identity is not None:
                    self.assertEqual(
                        (output.stat().st_dev, output.stat().st_ino),
                        published_identity,
                    )

    @unittest.skipUnless(os.name == "posix", "atomic crash recovery is POSIX-only")
    def test_host_evidence_copy_recovers_every_physical_publish_window(self) -> None:
        steps = (
            "mid_write",
            "post_fsync_pre_publish",
            "post_publish_pre_parent_fsync",
        )
        for step in steps:
            with self.subTest(step=step), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                source = root / "host-evidence.json"
                output = root / "authority/host-evidence.json"
                payload = canonical({"evidence": step})
                source.write_bytes(payload)

                def crash(observed: str) -> None:
                    if observed == step:
                        raise InjectedCrash(observed)

                with self.assertRaises(InjectedCrash):
                    target._copy_host_evidence_noreplace(  # noqa: SLF001
                        root=root,
                        source=source,
                        destination=output,
                        label=f"faulted host evidence {step}",
                        after_publish_step=crash,
                    )
                published_identity = (
                    (output.stat().st_dev, output.stat().st_ino)
                    if output.exists()
                    else None
                )
                observed = target._copy_host_evidence_noreplace(  # noqa: SLF001
                    root=root,
                    source=source,
                    destination=output,
                    label=f"resumed host evidence {step}",
                )
                self.assertEqual(output.read_bytes(), payload)
                self.assertEqual(observed, descriptor(root, output))
                self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o444)
                self.assertEqual(output.stat().st_nlink, 1)
                if published_identity is not None:
                    self.assertEqual(
                        (output.stat().st_dev, output.stat().st_ino),
                        published_identity,
                    )

    @unittest.skipUnless(os.name == "posix", "owned inode cleanup requires POSIX")
    def test_owned_cleanup_never_unlinks_replacement_leaf(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            directory = root / "owned"
            directory.mkdir()
            path = directory / "private.tmp"
            displaced = directory / "private-owned-displaced.tmp"
            competitor = b"operator-owned-replacement\n"
            with physical_io.PhysicalRootCustodyV1.open(root) as custody:
                _descriptor, identity = custody.write_exclusive_identity(
                    path,
                    b"executor-owned\n",
                    label="owned cleanup fixture",
                    mode=0o600,
                )
                path.rename(displaced)
                path.write_bytes(competitor)
                with self.assertRaisesRegex(
                    physical_io.PublicationPhysicalIoV1Error,
                    "no longer names the owned file",
                ):
                    custody.unlink_owned_identity(
                        path,
                        identity,
                        label="owned cleanup fixture",
                    )
            self.assertEqual(path.read_bytes(), competitor)
            self.assertEqual(displaced.read_bytes(), b"executor-owned\n")

    @unittest.skipUnless(os.name == "posix", "cold-loader race requires POSIX")
    def test_guarded_path_loader_rejects_parent_swap_restored_after_read(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            trusted = root / "trusted"
            displaced = root / "trusted-displaced"
            attacker = root / "attacker"
            trusted.mkdir()
            attacker.mkdir()
            path = trusted / "source.json"
            payload = canonical({"owner": "same-bytes"})
            path.write_bytes(payload)
            (attacker / path.name).write_bytes(payload)

            def swapped_loader() -> dict[str, object]:
                trusted.rename(displaced)
                attacker.rename(trusted)
                try:
                    return json.loads(path.read_bytes())
                finally:
                    trusted.rename(attacker)
                    displaced.rename(trusted)

            with target._held_physical_root_v1(root):  # noqa: SLF001
                with self.assertRaisesRegex(
                    target.BackendQ4TwoPhaseExecutorV1Error,
                    "namespace changed|directory.*cold load|mutated",
                ):
                    target._guarded_cold_load_v1(  # noqa: SLF001
                        root=root,
                        paths=[path],
                        label="path loader race",
                        callback=swapped_loader,
                    )
            self.assertEqual(path.read_bytes(), payload)

    @unittest.skipUnless(os.name == "posix", "physical AF_UNIX pins require Linux")
    def test_default_pin_recheck_physically_validates_live_sockets_and_images(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            service = root / "sidecar-service-authority.json"
            service.write_bytes(canonical({"service": "owned"}))
            service_descriptor = descriptor(root, service)
            contract = root / "accepted-preprocessing.json"
            contract.write_bytes(canonical({"accepted": "preprocessing"}))
            contract_descriptor = descriptor(root, contract)
            receipt = root / "accepted-preprocessing-receipt.json"
            receipt.write_bytes(canonical({"accepted": "receipt"}))
            receipt_descriptor = descriptor(root, receipt)
            guardian = accepted_guardian_pins(
                contract_descriptor, receipt_descriptor,
            )
            engine_path = root / "engine.sock"
            analytics_path = root / "analytics.sock"
            engine = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            analytics = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
            try:
                engine.bind(str(engine_path))
                analytics.bind(str(analytics_path))

                def pin(
                    role: str,
                    transport: str,
                    ownership: str,
                    path: Path,
                    authority: dict[str, object] | None,
                ) -> dict[str, object]:
                    observed = path.lstat()
                    return {
                        "role": role,
                        "transport": transport,
                        "ownership": ownership,
                        "path": str(path),
                        "device": int(observed.st_dev),
                        "inode": int(observed.st_ino),
                        "owner_uid": int(observed.st_uid),
                        "owner_gid": int(observed.st_gid),
                        "service_authority": authority,
                    }

                sockets = [
                    pin(
                        "container_engine",
                        "AF_UNIX/SOCK_STREAM",
                        "external_container_engine",
                        engine_path,
                        None,
                    ),
                    pin(
                        "analytics_execution",
                        "AF_UNIX/SOCK_SEQPACKET",
                        "executor_managed_sidecar_v1",
                        analytics_path,
                        service_descriptor,
                    ),
                ]
                images = [
                    {
                        "role": "cpu_worker",
                        "reference": "vast/cpu:publication-v4",
                        "image_id": "sha256:" + "1" * 64,
                        "os": "linux",
                        "architecture": "amd64",
                        "engine_socket_role": "container_engine",
                    }
                ]
                unsigned = {
                    "analytics_guardian": guardian,
                    "files": sorted(
                        [
                            contract_descriptor,
                            receipt_descriptor,
                            service_descriptor,
                        ],
                        key=lambda item: str(item["path"]),
                    ),
                    "sockets": sockets,
                    "images": images,
                }
                registry = {
                    **unsigned,
                    "registry_sha256": hashlib.sha256(
                        canonical(unsigned)[:-1]
                    ).hexdigest(),
                }
                with (
                    mock.patch.object(
                        target,
                        "_inspect_container_image_v1",
                        return_value={
                            "reference": images[0]["reference"],
                            "image_id": images[0]["image_id"],
                            "os": "linux",
                            "architecture": "amd64",
                        },
                    ) as inspect_image,
                    mock.patch.object(
                        target, "_assert_live_analytics_guardian_v1"
                    ) as assert_guardian,
                ):
                    checked = target._default_recheck_pins(  # noqa: SLF001
                        project_root=root,
                        source_registry=registry,
                    )
                self.assertEqual(checked["status"], "verified")
                inspect_image.assert_called_once_with(
                    engine_socket_path=engine_path,
                    reference="vast/cpu:publication-v4",
                )
                assert_guardian.assert_called_once_with(
                    root=root,
                    analytics_pin=sockets[1],
                    images=images,
                    guardian_pins=guardian,
                )

                drifted = copy.deepcopy(registry)
                drifted["sockets"][1]["inode"] += 1
                with self.assertRaisesRegex(
                    target.BackendQ4TwoPhaseExecutorV1Error,
                    "live identity drifted",
                ):
                    target._default_recheck_pins(  # noqa: SLF001
                        project_root=root,
                        source_registry=drifted,
                    )
            finally:
                engine.close()
                analytics.close()

    @unittest.skipUnless(os.name == "posix", "physical authority paths require Linux")
    def test_default_guardian_assert_uses_accepted_policy_pins_not_service_artifact(
        self,
    ) -> None:
        import checkpoint_gstreamer_analytics_sidecar as sidecar

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            service_value = {
                "service_identity_sha256": identity("self-anchored-service"),
            }
            service = root / "sidecar-service-authority.json"
            service.write_bytes(canonical(service_value))
            service_descriptor = descriptor(root, service)
            contract = root / "accepted-preprocessing.json"
            contract.write_bytes(canonical({"accepted": "preprocessing"}))
            receipt = root / "accepted-preprocessing-receipt.json"
            receipt.write_bytes(canonical({"accepted": "receipt"}))
            guardian = accepted_guardian_pins(
                descriptor(root, contract), descriptor(root, receipt),
            )
            analytics_pin = {
                "role": "analytics_execution",
                "transport": "AF_UNIX/SOCK_SEQPACKET",
                "ownership": "executor_managed_sidecar_v1",
                "path": str(root / "analytics.sock"),
                "device": 1,
                "inode": 2,
                "owner_uid": 3,
                "owner_gid": 4,
                "service_authority": service_descriptor,
            }
            images = [
                {
                    "role": f"{resource}_worker",
                    "image_id": image_id,
                }
                for resource, image_id in guardian[
                    "preprocessing_authority"
                ]["worker_image_ids"].items()
            ]
            checked = {
                "front_socket": {
                    key: analytics_pin[key]
                    for key in ("path", "device", "inode", "owner_uid", "owner_gid")
                },
                "readiness_artifact_path": str(service),
            }
            with mock.patch.object(
                sidecar,
                "assert_publication_sidecar_service_authority_v1",
                return_value=checked,
            ) as assert_authority:
                target._assert_live_analytics_guardian_v1(  # noqa: SLF001
                    root=root,
                    analytics_pin=analytics_pin,
                    images=images,
                    guardian_pins=guardian,
                )
            assert_authority.assert_called_once_with(
                service_value,
                expected_front_socket=analytics_pin["path"],
                expected_execution_config_identity_sha256=guardian[
                    "preprocessing_authority"
                ]["execution_config_identity_sha256"],
                expected_binding_set_identity_sha256=guardian[
                    "preprocessing_authority"
                ]["binding_set_identity_sha256"],
                expected_worker_image_ids=guardian[
                    "preprocessing_authority"
                ]["worker_image_ids"],
                expected_preprocessing_contract_authority=guardian[
                    "preprocessing_authority"
                ],
                expected_service_identity_sha256=guardian[
                    "service_identity_sha256"
                ],
                expected_policy_contract_sha256=guardian[
                    "policy_contract_sha256"
                ],
            )
            self.assertNotEqual(
                service_value["service_identity_sha256"],
                guardian["service_identity_sha256"],
            )

            drifted = copy.deepcopy(guardian)
            drifted["policy_contract_sha256"] = identity("cross-run-policy")
            with self.assertRaisesRegex(
                target.BackendQ4TwoPhaseExecutorV1Error,
                "guardian.*drifted|policy.*drifted",
            ):
                target._assert_live_analytics_guardian_v1(  # noqa: SLF001
                    root=root,
                    analytics_pin=analytics_pin,
                    images=images,
                    guardian_pins=drifted,
                )

    @unittest.skipUnless(os.name == "posix", "Docker AF_UNIX API requires Linux")
    def test_image_recheck_uses_read_only_bounded_docker_engine_api(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            socket_path = Path(temporary).resolve() / "engine.sock"
            listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            listener.bind(str(socket_path))
            listener.listen(1)
            requests: list[bytes] = []
            failure: list[BaseException] = []
            body = json.dumps(
                {
                    "Id": "sha256:" + "a" * 64,
                    "Os": "linux",
                    "Architecture": "amd64",
                },
                separators=(",", ":"),
            ).encode("ascii")

            def serve() -> None:
                try:
                    endpoint, _ = listener.accept()
                    with endpoint:
                        request = bytearray()
                        while b"\r\n\r\n" not in request:
                            request.extend(endpoint.recv(4096))
                        requests.append(bytes(request))
                        endpoint.sendall(
                            b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                            + f"Content-Length: {len(body)}\r\n".encode("ascii")
                            + b"Connection: close\r\n\r\n"
                            + body
                        )
                except BaseException as error:
                    failure.append(error)

            thread = threading.Thread(target=serve)
            thread.start()
            try:
                observed = target._inspect_container_image_v1(  # noqa: SLF001
                    engine_socket_path=socket_path,
                    reference="vast/runtime:publication-v4",
                )
            finally:
                thread.join(timeout=3)
                listener.close()
            self.assertFalse(thread.is_alive())
            self.assertEqual(failure, [])
            self.assertEqual(
                observed,
                {
                    "reference": "vast/runtime:publication-v4",
                    "image_id": "sha256:" + "a" * 64,
                    "os": "linux",
                    "architecture": "amd64",
                },
            )
            self.assertTrue(
                requests[0].startswith(
                    b"GET /images/vast%2Fruntime%3Apublication-v4/json HTTP/1.1\r\n"
                )
            )

    def test_standard_phase_b_adapter_routes_through_production_v3_api(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            cell = target.backend_q4_cells_v1()[0]

            def materializer(**_: object) -> dict[str, object]:
                return {
                    "arm_contract": {
                        "fixture": "arm",
                        "runtime_inputs": {
                            "streams": 6,
                            "duration_s": 180,
                            "base_seed": 20260323,
                            "warmup_s": 30,
                        },
                    },
                    "run_arguments": {"fixture_argument": "accepted"},
                }

            authority = {"fixture": "authority"}
            def prepare_transaction(**kwargs: object) -> dict[str, object]:
                output = Path(kwargs["output_dir"])
                output.mkdir(parents=True, exist_ok=True)
                (output / target.ARM_CONTRACT_FILENAME).write_bytes(
                    b"arm-contract\n"
                )
                return {"status": "prepared_production_arm_not_executed"}

            with (
                mock.patch.object(
                    target,
                    "canonical_backend_publication_arm_contract_bytes_v3",
                    return_value=b"arm-contract\n",
                ),
                mock.patch.object(
                    target,
                    "prepare_backend_publication_production_transaction_v3",
                    side_effect=prepare_transaction,
                ) as prepare,
                mock.patch.object(
                    target,
                    "run_or_resume_backend_publication_production_transaction_v3",
                    return_value=authority,
                ) as run,
            ):
                result = target.run_backend_q4_production_v3_adapter_v1(
                    project_root=root,
                    source_registry={},
                    cell=cell,
                    transaction_dir=root / "phase-b" / "transaction",
                    q4_binding={},
                    identity_binding={"binding_sha256": "1" * 64},
                    backend_runtime_grant={"grant_sha256": "2" * 64},
                    production_context={
                        "production_v3_materializer": materializer,
                    },
                )
            self.assertEqual(result, {"exit_code": 0, "authority": authority})
            prepare.assert_called_once()
            arguments = run.call_args.kwargs
            self.assertEqual(arguments["project_root"], root)
            self.assertEqual(
                arguments["output_dir"], root / "phase-b" / "transaction"
            )
            self.assertEqual(arguments["execution_scope"], "full_publication_measurement_v3")
            self.assertEqual(
                arguments["expected_backend_runtime_grant_sha256"], "2" * 64
            )
            self.assertEqual(
                arguments["expected_identity_artifact_binding_sha256"], "1" * 64
            )
            self.assertNotIn("cell_index", arguments["expected_coordinate"])

    def test_standard_adapter_resumes_each_parent_pin_wal_state_without_second_spawn(
        self,
    ) -> None:
        for terminal_state in ("result", "receipt_intent", "committed"):
            with self.subTest(terminal_state=terminal_state), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                cell = target.backend_q4_cells_v1()[0]
                transaction = root / "phase-b" / "transaction"
                spawn_count = 0
                run_count = 0

                def materializer(**_: object) -> dict[str, object]:
                    return {
                        "arm_contract": {
                            "fixture": "arm",
                            "runtime_inputs": {
                                "streams": 6,
                                "duration_s": 180,
                                "base_seed": 20260323,
                                "warmup_s": 30,
                            },
                        },
                        "run_arguments": {"fixture_argument": "accepted"},
                    }

                def prepare_transaction(**kwargs: object) -> dict[str, object]:
                    output = Path(kwargs["output_dir"])
                    output.mkdir(parents=True, exist_ok=True)
                    (output / target.ARM_CONTRACT_FILENAME).write_bytes(
                        b"arm-contract\n"
                    )
                    return {"status": "prepared_production_arm_not_executed"}

                def wal_transaction(**kwargs: object) -> dict[str, object]:
                    nonlocal spawn_count, run_count
                    run_count += 1
                    expected = kwargs["expected_durable_parent_artifact_pin"]
                    sink = kwargs["durable_parent_artifact_pin_sink"]
                    if expected is None:
                        spawn_count += 1
                        sink({
                            "state": "result",
                            "path": "backend_publication_launcher_result_v3.json",
                            "size_bytes": 11,
                            "sha256": "a" * 64,
                        })
                        if terminal_state in {"receipt_intent", "committed"}:
                            sink({
                                "state": "receipt_intent",
                                "path": target.OUTPUT_RECEIPT_FILENAME,
                                "size_bytes": 13,
                                "sha256": "b" * 64,
                            })
                        if terminal_state == "committed":
                            sink({
                                "state": "committed",
                                "path": target.OUTPUT_RECEIPT_FILENAME,
                                "size_bytes": 13,
                                "sha256": "b" * 64,
                            })
                        raise RuntimeError(f"fault after {terminal_state}")
                    self.assertEqual(expected["state"], terminal_state)
                    self.assertIs(kwargs["_allow_spawn"], False)
                    if terminal_state == "result":
                        sink({
                            "state": "receipt_intent",
                            "path": target.OUTPUT_RECEIPT_FILENAME,
                            "size_bytes": 13,
                            "sha256": "b" * 64,
                        })
                    if terminal_state in {"result", "receipt_intent"}:
                        sink({
                            "state": "committed",
                            "path": target.OUTPUT_RECEIPT_FILENAME,
                            "size_bytes": 13,
                            "sha256": "b" * 64,
                        })
                    return {"fixture": "authority"}

                common = {
                    "project_root": root,
                    "source_registry": {},
                    "cell": cell,
                    "transaction_dir": transaction,
                    "q4_binding": {},
                    "identity_binding": {"binding_sha256": "1" * 64},
                    "backend_runtime_grant": {"grant_sha256": "2" * 64},
                    "production_context": {
                        "production_v3_materializer": materializer,
                    },
                }
                with (
                    mock.patch.object(
                        target,
                        "canonical_backend_publication_arm_contract_bytes_v3",
                        return_value=b"arm-contract\n",
                    ),
                    mock.patch.object(
                        target,
                        "prepare_backend_publication_production_transaction_v3",
                        side_effect=prepare_transaction,
                    ) as prepare,
                    mock.patch.object(
                        target,
                        "run_or_resume_backend_publication_production_transaction_v3",
                        side_effect=wal_transaction,
                    ),
                ):
                    with self.assertRaises(
                        target.BackendQ4TwoPhaseExecutorV1Error
                    ) as caught:
                        target.run_backend_q4_production_v3_adapter_v1(**common)
                    self.assertEqual(caught.exception.exit_code, target.EXIT_TRANSIENT)
                    result = target.run_backend_q4_production_v3_adapter_v1(
                        **common,
                        _allow_spawn=False,
                        _require_committed_parent_pin=True,
                    )
                self.assertEqual(
                    result,
                    {"exit_code": target.EXIT_OK, "authority": {"fixture": "authority"}},
                )
                self.assertEqual(spawn_count, 1)
                self.assertEqual(run_count, 2)
                self.assertEqual(prepare.call_count, 2)

    def test_default_phase_b_adapter_materializes_without_injected_factory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            transaction = root / "phase-b" / "transaction"
            cell = target.backend_q4_cells_v1()[0]
            observed: list[dict[str, object]] = []

            def receipt_loader(**kwargs: object) -> dict[str, object]:
                observed.append(dict(kwargs))
                return {
                    "phase1_receipt_sha256": "3" * 64,
                    "phase2_receipt_sha256": "4" * 64,
                    "source_materialization_result_sha256": "5" * 64,
                }

            def repository_materializer(**kwargs: object) -> dict[str, object]:
                loaded = kwargs["production_context"]["production_receipt_loader"](
                    project_root=kwargs["project_root"],
                    source_registry=kwargs["source_registry"],
                )
                self.assertEqual(
                    loaded["source_materialization_result_sha256"], "5" * 64
                )
                self.assertEqual(kwargs["transaction_dir"], transaction)
                return {
                    "arm_contract": {
                        "fixture": "repository-arm",
                        "runtime_inputs": {
                            "streams": 6,
                            "duration_s": 180,
                            "base_seed": 20260323,
                            "warmup_s": 30,
                        },
                    },
                    "run_arguments": {"fixture_argument": "accepted"},
                }

            authority = {"fixture": "authority"}
            def prepare_transaction(**kwargs: object) -> dict[str, object]:
                output = Path(kwargs["output_dir"])
                output.mkdir(parents=True, exist_ok=True)
                (output / target.ARM_CONTRACT_FILENAME).write_bytes(
                    b"repository-arm-contract\n"
                )
                return {"status": "prepared_production_arm_not_executed"}

            with (
                mock.patch.object(
                    target,
                    "materialize_backend_q4_production_v3_arm_v1",
                    side_effect=repository_materializer,
                    create=True,
                ) as materialize,
                mock.patch.object(
                    target,
                    "canonical_backend_publication_arm_contract_bytes_v3",
                    return_value=b"repository-arm-contract\n",
                ),
                mock.patch.object(
                    target,
                    "prepare_backend_publication_production_transaction_v3",
                    side_effect=prepare_transaction,
                ),
                mock.patch.object(
                    target,
                    "run_or_resume_backend_publication_production_transaction_v3",
                    return_value=authority,
                ),
            ):
                result = target.run_backend_q4_production_v3_adapter_v1(
                    project_root=root,
                    source_registry={"registry_sha256": "6" * 64},
                    source_registry_path=root / "q4-source-registry.json",
                    cell=cell,
                    transaction_dir=transaction,
                    q4_binding={"fixture": "q4"},
                    identity_binding={"binding_sha256": "1" * 64},
                    backend_runtime_grant={"grant_sha256": "2" * 64},
                    production_context={
                        "production_receipt_loader": receipt_loader,
                        "phase1_receipt_path": "phase1.json",
                        "phase1_receipt_file_sha256": "7" * 64,
                        "phase1_receipt_sha256": "8" * 64,
                    },
                )

            self.assertEqual(result, {"exit_code": 0, "authority": authority})
            materialize.assert_called_once()
            self.assertEqual(len(observed), 1)

    def test_repository_materializer_builds_exact_real_v3_arm_and_pair_binding(
        self,
    ) -> None:
        import full_publication_entrypoint as production_entrypoint  # noqa: PLC0415

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            q4 = {"fixture": "accepted-q4"}
            identity_sha = "1" * 64
            backend_grant_sha = "2" * 64
            resource_grant_sha = "3" * 64
            model_grant_sha = "4" * 64
            parity_sha = "5" * 64
            runtime_binding_sha = "6" * 64
            source_sha = "7" * 64
            cell = target.backend_q4_cells_v1()[0]
            transaction = root / "phase-b" / cell.arm_id
            invocation = target.publication_launcher_invocation_v3_contract()
            runtime_template = {
                "evidence_mapping": {
                    "checkpoint_publication_acceptance.json": (
                        "checkpoint_publication_acceptance.json"
                    ),
                    "run_metadata.json": "run_metadata.json",
                }
            }
            selected = {
                "launcher": {
                    "path": "scripts/checkpoint_deepstream_publication_launcher_v3.py",
                    "size_bytes": 101,
                    "sha256": "8" * 64,
                },
                "launcher_invocation": invocation,
                "cell_identity_sha256": "9" * 64,
                "validation_record_sha256": "a" * 64,
                "runtime_authority_sha256": "b" * 64,
                "model_parity_acceptance_binding_sha256": parity_sha,
                "dataset_runtime_input_key": "deepstream_publication_runtime_v3",
                "dataset_runtime_input": runtime_template,
                "launcher_evidence_files": [
                    "checkpoint_publication_acceptance.json",
                    "run_metadata.json",
                ],
                "qualification_dataset_runtime_input": runtime_template,
                "qualification_launcher_evidence_files": list(
                    target.qualification_launcher_evidence_files_v4(cell.policy)
                ),
                "launcher_input_wrapper_sha256": "d" * 64,
                "launcher_input_projection_crossbinding_sha256": "e" * 64,
            }
            runtime_binding = {
                "schema_version": 3,
                "artifact_kind": (
                    "vast_backend_publication_production_runtime_bind_mount_v3"
                ),
                "source_runtime_root": "/runtime",
                "source_python_relative_path": "bin/python3.12",
                "source_python_size_bytes": 202,
                "source_python_sha256": "c" * 64,
                "project_runtime_mount": ".publication-runtime/runtime-v1",
                "project_python_path": (
                    ".publication-runtime/runtime-v1/bin/python3.12"
                ),
                "runtime_filesystem": "ext4",
                "source_runtime_mount_read_only": True,
                "runtime_mount_read_only": True,
                "binding_sha256": runtime_binding_sha,
            }
            for name in (
                "phase1.json",
                "phase2.json",
                "source-result.json",
                "source-registry.json",
            ):
                (root / name).write_bytes(canonical({"physical": name}))
            receipt_unsigned = {
                "schema_version": 1,
                "artifact_kind": target.PRODUCTION_RECEIPT_CHAIN_KIND,
                "phase1_receipt": descriptor(root, root / "phase1.json"),
                "phase1_receipt_sha256": "e" * 64,
                "phase2_receipt": descriptor(root, root / "phase2.json"),
                "phase2_receipt_sha256": "0" * 64,
                "source_materialization_result": descriptor(
                    root, root / "source-result.json"
                ),
                "source_materialization_result_sha256": "2" * 64,
                "source_registry": descriptor(root, root / "source-registry.json"),
                "source_registry_sha256": source_sha,
                "source_registry_path_plan_sha256": "4" * 64,
                "runtime_candidate_registry_sha256": "5" * 64,
            }
            receipt_chain = {
                **receipt_unsigned,
                "receipt_chain_sha256": target._canonical_sha(  # noqa: SLF001
                    receipt_unsigned
                ),
            }
            context = {
                "phase1_receipt_path": "phase1.json",
                "phase1_receipt_file_sha256": "d" * 64,
                "phase1_receipt_sha256": "e" * 64,
                "phase2_receipt_path": "phase2.json",
                "phase2_receipt_file_sha256": "f" * 64,
                "phase2_receipt_sha256": "0" * 64,
                "source_materialization_result_path": "source-result.json",
                "source_materialization_result_file_sha256": "1" * 64,
                "source_materialization_result_sha256": "2" * 64,
                "production_receipt_loader": lambda **_: receipt_chain,
                "production_runtime_bind_mount_loader": lambda **_: runtime_binding,
            }
            identity = {
                "binding_sha256": identity_sha,
                "bindings": {"backend_runtime_qualification": q4},
            }
            backend_grant = {
                "identity_artifact_binding_sha256": identity_sha,
                "grant_sha256": backend_grant_sha,
            }
            resource_grant = {
                "identity_artifact_binding_sha256": identity_sha,
                "grant_sha256": resource_grant_sha,
            }
            model_grant = {
                "identity_artifact_binding_sha256": identity_sha,
                "grant_sha256": model_grant_sha,
                "parity_acceptance_binding_sha256": parity_sha,
            }
            dataset_binding = {
                "dataset": {
                    "name": "kpp_iss_publication_v3_h264",
                    "codec_variant": "h264",
                    "logical_stream_instances": 6,
                    "streams": [],
                }
            }
            runtime_authority = {
                "runtime_authority_sha256": selected["runtime_authority_sha256"],
                "runtime_input_template": runtime_template,
            }

            with (
                mock.patch.object(
                    target,
                    "resource_capability_grant_from_identity_artifacts",
                    return_value=resource_grant,
                ),
                mock.patch.object(
                    target,
                    "validate_pre_run_resource_capability_grant",
                    side_effect=lambda value: value,
                ),
                mock.patch.object(
                    target,
                    "model_parity_grant_from_identity_artifacts",
                    return_value=model_grant,
                ),
                mock.patch.object(
                    target,
                    "validate_pre_run_model_parity_grant",
                    side_effect=lambda value: value,
                ),
                mock.patch.object(
                    production_entrypoint,
                    "_select_production_v3_authority",
                    return_value=selected,
                ) as select_authority,
                mock.patch.object(
                    target,
                    "_runtime_material_for_cell_v4",
                    return_value=({}, runtime_authority, dataset_binding),
                ),
            ):
                material = target.materialize_backend_q4_production_v3_arm_v1(
                    project_root=root,
                    source_registry={"registry_sha256": source_sha},
                    source_registry_path=root / "source-registry.json",
                    cell=cell,
                    transaction_dir=transaction,
                    q4_binding=q4,
                    identity_binding=identity,
                    backend_runtime_grant=backend_grant,
                    production_context=context,
                )

                drifted_selected = copy.deepcopy(selected)
                drifted_selected[
                    "model_parity_acceptance_binding_sha256"
                ] = "d" * 64
                select_authority.return_value = drifted_selected
                with self.assertRaisesRegex(
                    target.BackendQ4TwoPhaseExecutorV1Error,
                    "runtime authority parity binding drifted",
                ):
                    target.materialize_backend_q4_production_v3_arm_v1(
                        project_root=root,
                        source_registry={"registry_sha256": source_sha},
                        source_registry_path=root / "source-registry.json",
                        cell=cell,
                        transaction_dir=root / "transactions" / "parity-drift",
                        q4_binding=q4,
                        identity_binding=identity,
                        backend_runtime_grant=backend_grant,
                        production_context=context,
                    )

            arm = material["arm_contract"]
            arguments = material["run_arguments"]
            runtime = arm["runtime_inputs"]
            execution = arm["full_publication_execution_binding"]
            self.assertEqual(runtime["output_dir"], str(transaction))
            self.assertEqual(runtime["duration_s"], 180)
            self.assertEqual(runtime["repeat_index"], 0)
            self.assertEqual(
                runtime["dataset"]["deepstream_publication_runtime_v3"],
                runtime_template,
            )
            self.assertEqual(execution["sequence"], 0)
            self.assertEqual(execution["attempt"], 1)
            self.assertEqual(execution["arm_id"], cell.arm_id)
            self.assertEqual(arguments["expected_runtime_inputs"], runtime)
            self.assertEqual(
                arguments["expected_runtime_binding_identity_sha256"],
                runtime_binding_sha,
            )
            self.assertEqual(
                arguments["expected_production_runtime_bind_mount"], runtime_binding
            )
            self.assertEqual(
                arm["resource_capability_grant_sha256"], resource_grant_sha
            )
            self.assertEqual(arm["model_parity_grant_sha256"], model_grant_sha)
            self.assertEqual(arm["backend_runtime_grant_sha256"], backend_grant_sha)
            self.assertEqual(
                select_authority.call_args_list[0].kwargs[
                    "runtime_authority_snapshot"
                ],
                runtime_authority,
            )

            paired = target.backend_q4_cells_v1()[35]
            self.assertEqual(
                target._backend_q4_pair_execution_v1(cell)[0],  # noqa: SLF001
                target._backend_q4_pair_execution_v1(paired)[0],  # noqa: SLF001
            )

    def test_b3_receipt_loader_crossbinds_phase_chain_and_source_result(self) -> None:
        import publication_q4_authority_plan_pipeline_v1 as plan_pipeline  # noqa: PLC0415

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            phase1_path = root / "phase1.json"
            phase2_path = root / "phase2.json"
            runtime_path = root / "runtime-registry.json"
            source_path = root / "source-registry.json"
            result_path = root / "source-result.json"
            phase1_path.write_bytes(canonical({"physical": "phase1"}))
            phase2_path.write_bytes(canonical({"physical": "phase2"}))
            runtime_path.write_bytes(canonical({"physical": "runtime"}))
            runtime_descriptor = descriptor(root, runtime_path)
            source_semantic = "1" * 64
            runtime_semantic = "2" * 64
            plan_semantic = "3" * 64
            source_registry = {
                "registry_sha256": source_semantic,
                "runtime_candidate_registry": runtime_descriptor,
            }
            source_path.write_bytes(canonical(source_registry))
            source_descriptor = descriptor(root, source_path)
            result_unsigned = {
                "schema_version": 1,
                "artifact_kind": target.SOURCE_MATERIALIZATION_RESULT_KIND,
                "status": "materialized_accepted_physical_q4_sources",
                "plan_sha256": plan_semantic,
                "source_registry": source_descriptor,
                "source_registry_sha256": source_semantic,
                "identity_inputs": {
                    "analytics_model_parity": {},
                    "analytics_execution_layer": {},
                    "policy_qualification": {},
                    "resource_qualification": {},
                },
            }
            result_value = {
                **result_unsigned,
                "result_sha256": target._canonical_sha(result_unsigned),  # noqa: SLF001
            }
            result_path.write_bytes(canonical(result_value))
            phase1_semantic = "4" * 64
            phase2_semantic = "5" * 64
            phase1 = {
                "schema_version": 1,
                "artifact_kind": target.PHASE1_PLAN_RECEIPT_KIND,
                "receipt_sha256": phase1_semantic,
            }
            phase2 = {
                "schema_version": 1,
                "artifact_kind": target.PHASE2_PLAN_RECEIPT_KIND,
                "phase1_receipt": {
                    "artifact_schema_version": 1,
                    "artifact_kind": target.PHASE1_PLAN_RECEIPT_KIND,
                    "descriptor": descriptor(root, phase1_path),
                    "content_identity_sha256": phase1_semantic,
                },
                "phase1_receipt_sha256": phase1_semantic,
                "source_registry_path_plan": {
                    "artifact_schema_version": 1,
                    "artifact_kind": "vast_backend_q4_two_phase_source_registry_path_plan_v1",
                    "descriptor": {
                        "path": "source-plan.json",
                        "size_bytes": 1,
                        "sha256": "6" * 64,
                    },
                    "content_identity_sha256": plan_semantic,
                },
                "runtime_candidate_registry": {
                    "artifact_schema_version": 4,
                    "artifact_kind": "vast_publication_q4_runtime_candidate_registry_v4",
                    "descriptor": runtime_descriptor,
                    "content_identity_sha256": runtime_semantic,
                },
                "planned_outputs": {
                    "source_registry_path": source_descriptor["path"],
                    "source_materialization_result_path": descriptor(
                        root, result_path
                    )["path"],
                },
                "receipt_sha256": phase2_semantic,
            }
            loader_kwargs = {
                "project_root": root,
                "source_registry_path": source_path,
                "source_registry": source_registry,
                "phase1_receipt_path": phase1_path,
                "phase1_receipt_file_sha256": descriptor(
                    root, phase1_path
                )["sha256"],
                "phase1_receipt_sha256": phase1_semantic,
                "phase2_receipt_path": phase2_path,
                "phase2_receipt_file_sha256": descriptor(
                    root, phase2_path
                )["sha256"],
                "phase2_receipt_sha256": phase2_semantic,
                "source_materialization_result_path": result_path,
                "source_materialization_result_file_sha256": descriptor(
                    root, result_path
                )["sha256"],
                "source_materialization_result_sha256": result_value[
                    "result_sha256"
                ],
            }
            with (
                mock.patch.object(
                    plan_pipeline,
                    "load_publication_q4_authority_plan_phase1_receipt_v1",
                    return_value=phase1,
                ),
                mock.patch.object(
                    plan_pipeline,
                    "load_publication_q4_source_plan_phase2_receipt_v1",
                    return_value=phase2,
                ),
                mock.patch.object(
                    target,
                    "_load_publication_q4_runtime_candidate_registry_v4",
                    return_value={"registry_sha256": runtime_semantic},
                ),
            ):
                loaded = target.load_backend_q4_production_receipt_chain_v1(
                    **loader_kwargs,
                )
                phase2["planned_outputs"][
                    "source_materialization_result_path"
                ] = "wrong/source-result.json"
                with self.assertRaisesRegex(
                    target.BackendQ4TwoPhaseExecutorV1Error,
                    "causality drifted",
                ):
                    target.load_backend_q4_production_receipt_chain_v1(
                        **loader_kwargs,
                    )
            self.assertEqual(loaded["source_registry"], source_descriptor)
            self.assertEqual(
                loaded["source_materialization_result_sha256"],
                result_value["result_sha256"],
            )
            self.assertEqual(
                loaded["receipt_chain_sha256"],
                target._canonical_sha(  # noqa: SLF001
                    {
                        key: value
                        for key, value in loaded.items()
                        if key != "receipt_chain_sha256"
                    }
                ),
            )

    def test_cli_requires_all_external_receipt_pins_and_routes_no_callable(self) -> None:
        argv = [
            "--project-root", "project",
            "--source-registry", "source-registry.json",
            "--work-dir", "work",
            "--identity-manifest-output", "work/identity.json",
            "--phase1-receipt", "phase1.json",
            "--phase1-receipt-file-sha256", "1" * 64,
            "--phase1-receipt-sha256", "2" * 64,
            "--phase2-receipt", "phase2.json",
            "--phase2-receipt-file-sha256", "3" * 64,
            "--phase2-receipt-sha256", "4" * 64,
            "--source-materialization-result", "source-result.json",
            "--source-materialization-result-file-sha256", "5" * 64,
            "--source-materialization-result-sha256", "6" * 64,
            "--through-phase", "phase_b",
        ]
        result = {
            "status": "completed",
            "phase_a_completed_cells": 560,
            "phase_b_completed_cells": 560,
            "pair_count": 280,
        }
        stdout = io.StringIO()
        with (
            mock.patch.object(
                target, "execute_backend_q4_two_phase_v1", return_value=result
            ) as execute,
            mock.patch.object(target.sys, "stdout", stdout),
        ):
            code = target.run_cli(argv)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout.getvalue()), result)
        context = execute.call_args.kwargs["production_context"]
        self.assertEqual(set(context), target._PRODUCTION_CONTEXT_FIELDS)  # noqa: SLF001
        self.assertNotIn("production_v3_materializer", context)
        with mock.patch.object(
            target,
            "execute_backend_q4_two_phase_v1",
            side_effect=AssertionError("invalid CLI reached execution"),
        ):
            self.assertEqual(target.run_cli(argv[:-2]), 78)

    def test_identity_boundary_rejects_q4_or_grant_crossbinding_drift(self) -> None:
        q4 = {"identity_binding_sha256": "a" * 64}
        identity = {
            "binding_sha256": "b" * 64,
            "bindings": {"backend_runtime_qualification": q4},
        }
        target._identity_q4_crossbind(identity, q4)  # noqa: SLF001
        with self.assertRaises(target.BackendQ4TwoPhaseExecutorV1Error):
            target._identity_q4_crossbind(  # noqa: SLF001
                identity, {"identity_binding_sha256": "c" * 64}
            )
        with self.assertRaises(target.BackendQ4TwoPhaseExecutorV1Error):
            target._validate_grant(  # noqa: SLF001
                {
                    "schema_version": 3,
                    "artifact_kind": "vast_backend_runtime_grant_v3",
                    "identity_artifact_binding_sha256": "d" * 64,
                    "grant_sha256": "e" * 64,
                },
                identity_binding_sha256=identity["binding_sha256"],
            )

    def test_identity_boundary_accepts_real_cross_module_v3_grant(self) -> None:
        from tests.test_backend_runtime_grant import v3_identity  # noqa: PLC0415

        identity = v3_identity()
        grant = target.backend_runtime_grant_from_identity_artifacts(identity)
        checked = target._validate_grant(  # noqa: SLF001
            grant,
            identity_binding_sha256=identity["binding_sha256"],
        )
        self.assertEqual(checked, grant)
        self.assertEqual(checked["artifact_kind"], target.GRANT_V3_KIND)

    def test_default_arbitrary_q4_adapters_are_public_and_no_di_is_required(self) -> None:
        dependencies = target.default_backend_q4_two_phase_dependencies_v1()
        self.assertTrue(
            {
                "materialize_backend_q4_runtime_input_v4_adapter",
                "run_backend_q4_native_runtime_v4_adapter",
                "finalize_backend_q4_qualification_graph_v4_adapter",
            }.issubset(target.__all__)
        )
        self.assertIs(
            dependencies.materialize_qualification_input,
            target.materialize_backend_q4_runtime_input_v4_adapter,
        )
        self.assertIs(
            dependencies.run_native_qualification,
            target.run_backend_q4_native_runtime_v4_adapter,
        )
        self.assertIs(
            dependencies.finalize_qualification_graph,
            target.finalize_backend_q4_qualification_graph_v4_adapter,
        )

    def test_standard_graph_tail_builds_v2_index_and_catalog(self) -> None:
        tests_dir = ROOT / "tests"
        sys.path.insert(0, str(tests_dir))
        from test_backend_runtime_qualification_v4_catalog import (  # noqa: PLC0415
            Fixture as CatalogFixture,
        )

        fixture = CatalogFixture()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            graph_dir = root / "graph"
            graph_dir.mkdir()
            record_fixture = fixture.records
            trust = {
                "snapshot": {
                    "runner_invocation_identity_sha256": (
                        record_fixture.invocation_sha
                    )
                },
                "validator": {"authority_sha256": record_fixture.validator_sha},
                "runner": {
                    "runner_authority_sha256": record_fixture.runner_sha
                },
                "invocation": {"invocation_sha256": record_fixture.abi_sha},
                "validator_ref": record_fixture.validator_ref,
                "runner_ref": record_fixture.runner_ref,
                "invocation_ref": record_fixture.abi_ref,
            }
            index, result = target._build_q4_validation_index_and_catalog_v4(  # noqa: SLF001
                root=root,
                graph_dir=graph_dir,
                q4_input={"input_index_sha256": record_fixture.q4_sha},
                q4_input_ref=record_fixture.q4_ref,
                trust=trust,
                context_refs=fixture.context_refs,
                request_refs=fixture.request_refs,
                record_refs=fixture.record_refs,
                records=record_fixture.records,
                binding_pins=record_fixture.bindings,
                set_pins=record_fixture.sets,
                launcher_refs=record_fixture.launcher_refs,
                launcher_pins=record_fixture.launcher_shas,
            )
            self.assertEqual(len(index["validation_records"]), 560)
            self.assertEqual(result["catalog"]["coverage"], {
                "system_count": 4,
                "contexts_per_system": 1,
                "shards_per_system": 1,
                "cells_per_system": 140,
                "validation_request_count": 560,
                "validation_record_count": 560,
            })
            self.assertEqual(result["catalog_path"].parent, graph_dir)

            rejected_graph_dir = root / "rejected-graph"
            rejected_graph_dir.mkdir()
            unqualified_records = copy.deepcopy(record_fixture.records)
            unqualified_records[0]["replay_result"]["accepted"] = False
            with self.assertRaises(
                target.BackendQ4TwoPhaseExecutorV1Error
            ) as caught:
                target._build_q4_validation_index_and_catalog_v4(  # noqa: SLF001
                    root=root,
                    graph_dir=rejected_graph_dir,
                    q4_input={"input_index_sha256": record_fixture.q4_sha},
                    q4_input_ref=record_fixture.q4_ref,
                    trust=trust,
                    context_refs=fixture.context_refs,
                    request_refs=fixture.request_refs,
                    record_refs=fixture.record_refs,
                    records=unqualified_records,
                    binding_pins=record_fixture.bindings,
                    set_pins=record_fixture.sets,
                    launcher_refs=record_fixture.launcher_refs,
                    launcher_pins=record_fixture.launcher_shas,
                )
            self.assertIn("qualified physical replay", caught.exception.blocker)

    def test_standard_native_adapter_seals_only_physical_pending_evidence(self) -> None:
        class Collector:
            def __init__(self, path: Path) -> None:
                self.path = path

            def start(self) -> None:
                self.path.write_text("run_id,cpu_percent\nfixture,1\n", encoding="ascii")

            def wait_until_ready(self, *, timeout_s: float) -> None:
                self.timeout_s = timeout_s

            def stop(self) -> None:
                return None

            def join(self, *, timeout: float) -> None:
                self.timeout = timeout

            def is_alive(self) -> bool:
                return False

            def raise_if_failed(self) -> None:
                return None

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            output = root / "cell"
            output.mkdir()
            input_path = output / target.PHASE_A_INPUT_FILENAME
            input_path.write_bytes(canonical({"fixture": "input"}))
            cell = target.backend_q4_cells_v1()[0]
            evidence_names = target.qualification_launcher_evidence_files_v4(
                cell.policy
            )
            sys.path.insert(0, str(ROOT / "tests"))
            from test_publication_q4_runtime_contract_v4 import (  # noqa: PLC0415
                dataset as runtime_dataset,
                snapshot as runtime_snapshot,
            )

            data = runtime_dataset(cell.codec)
            authority = runtime_snapshot(
                {
                    key: cell.coordinate[key]
                    for key in ("system", "codec", "topology_kind", "policy")
                },
                data,
            )
            contract = target.build_publication_runtime_contract_v4(
                coordinate=cell.coordinate,
                authority_snapshot=authority,
                dataset_binding=data,
                run_id=f"qualification-q4-v4-{cell.arm_id}",
                duration_s=180,
            )

            def runtime(request: object) -> object:
                for name in evidence_names:
                    (request.output_dir / name).write_text(
                        f"physical:{name}\n", encoding="ascii"
                    )
                return target.NativePublicationOutcomeV3(exit_code=0)

            with (
                mock.patch.object(
                    target,
                    "_validated_materialized_runtime_contract_v4",
                    return_value=contract,
                ),
                mock.patch.object(
                    target,
                    "_default_q4_hardware_collector",
                    side_effect=lambda path, **_: Collector(path),
                ),
                mock.patch.dict(
                    target._NATIVE_RUNTIME_REGISTRY,  # noqa: SLF001
                    {cell.system: runtime},
                ),
            ):
                result = target.run_backend_q4_native_runtime_v4_adapter(
                    project_root=root,
                    source_registry={},
                    cell=cell,
                    qualification_input={},
                    qualification_input_path=input_path,
                    output_dir=output,
                )
            self.assertEqual(result["exit_code"], 0)
            self.assertIsNone(
                result["validation_record_candidate"]["replay_result"]
            )
            manifest = json.loads(Path(result["raw_evidence_path"]).read_text("ascii"))
            self.assertEqual(manifest["artifact_kind"], target.RAW_EVIDENCE_MANIFEST_KIND)
            self.assertFalse(manifest["authorization_eligible"])
            self.assertFalse(manifest["execution_authorized"])
            self.assertEqual(
                [Path(item["path"]).name for item in manifest["evidence_files"]],
                [*evidence_names, target.HARDWARE_EVIDENCE_FILENAME],
            )
            self.assertNotIn("replay_result", manifest)

    def test_invalid_runtime_registry_fails_closed_before_fence_without_di(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            registry = source_registry(root)
            with self.assertRaises(target.BackendQ4TwoPhaseExecutorV1Error) as caught:
                target.execute_backend_q4_two_phase_v1(
                    project_root=root,
                    source_registry_path=registry,
                    work_dir=root / "q4-work",
                    identity_manifest_output=root / "q4-work/identity.json",
                    identity_inputs=identity_inputs(root),
                    production_context={"fixture": "production"},
                )
            self.assertEqual(caught.exception.exit_code, 78)
            self.assertIn("runtime candidate registry", caught.exception.blocker)
            first = target.backend_q4_cells_v1()[0]
            fence = (
                root
                / "q4-work"
                / "phase-a"
                / "cells"
                / first.arm_id
                / "qualification-launch-fence.json"
            )
            self.assertFalse(fence.exists())

    def test_fake_end_to_end_runs_phase_a_boundary_phase_b_and_280_pairs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            fake = FakePipeline(root)
            result = self.execute(root, fake)
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["phase_a_completed_cells"], 560)
            self.assertEqual(result["phase_b_completed_cells"], 560)
            self.assertEqual(result["pair_count"], 280)
            self.assertEqual(fake.qualification_calls, list(range(560)))
            self.assertEqual(fake.production_calls, list(range(560)))
            self.assertGreaterEqual(fake.pin_calls, 2242)
            labels = [event[0] for event in fake.events]
            self.assertLess(labels.index("grant"), labels.index("production"))
            self.assertEqual(labels[-1], "sizing")

    def test_checkpoint_resume_does_not_repeat_committed_phase_a_cell(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            fake = FakePipeline(root)
            registry = source_registry(root)
            fired = False

            def fault(event: str, cell: target.BackendQ4CellV1 | None) -> None:
                nonlocal fired
                if (
                    event == "phase_a_after_record"
                    and cell is not None
                    and cell.cell_index == 9
                    and not fired
                ):
                    fired = True
                    raise RuntimeError("injected interruption")

            common = {
                "project_root": root,
                "source_registry_path": registry,
                "work_dir": root / "q4-work",
                "identity_manifest_output": root / "q4-work/accepted-identity.json",
                "identity_inputs": identity_inputs(root),
                "production_context": {"fixture": "production"},
                "dependencies": fake.dependencies(),
            }
            with self.assertRaisesRegex(RuntimeError, "injected interruption"):
                target.execute_backend_q4_two_phase_v1(**common, _fault_hook=fault)
            self.assertEqual(fake.qualification_calls, list(range(10)))
            result = target.execute_backend_q4_two_phase_v1(**common)
            self.assertEqual(result["status"], "completed")
            self.assertEqual(fake.qualification_calls.count(9), 1)
            self.assertEqual(fake.qualification_calls, list(range(560)))

    def test_uncheckpointed_phase_a_record_cannot_skip_native_execution(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            fake = FakePipeline(root)
            registry_path = source_registry(root)
            registry = json.loads(registry_path.read_bytes())
            work = root / "q4-work"
            work.mkdir()
            cell = target.backend_q4_cells_v1()[0]
            target._run_phase_a_cell(  # noqa: SLF001
                root=root,
                work_dir=work,
                cell=cell,
                source_path=registry_path,
                source_registry=registry,
                source_descriptor=descriptor(root, registry_path),
                dependencies=fake.dependencies(),
            )
            self.assertEqual(fake.qualification_calls, [0])
            with self.assertRaisesRegex(
                target.BackendQ4TwoPhaseExecutorV1Error,
                "uncheckpointed record|not parent-authorized",
            ) as caught:
                target.execute_backend_q4_two_phase_v1(
                    project_root=root,
                    source_registry_path=registry_path,
                    work_dir=work,
                    identity_manifest_output=work / "accepted-identity.json",
                    identity_inputs=identity_inputs(root),
                    production_context={"fixture": "production"},
                    dependencies=fake.dependencies(),
                )
            self.assertEqual(caught.exception.exit_code, target.EXIT_PERMANENT)
            self.assertEqual(fake.qualification_calls, [0])

    def test_uncheckpointed_phase_b_record_cannot_skip_parent_wal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            fake = FakePipeline(root)
            self.execute(root, fake, through_phase="boundary")
            registry_path = root / "q4-source-registry.json"
            registry = json.loads(registry_path.read_bytes())
            work = root / "q4-work"
            boundary = json.loads(
                (work / "boundary" / target.BOUNDARY_RECORD_FILENAME).read_bytes()
            )
            cell = target.backend_q4_cells_v1()[0]
            target._run_phase_b_cell(  # noqa: SLF001
                root=root,
                work_dir=work,
                cell=cell,
                source_path=registry_path,
                source_registry=registry,
                source_descriptor=descriptor(root, registry_path),
                q4_binding=fake.q4,
                identity_binding=fake.identity,
                backend_runtime_grant=fake.grant,
                boundary_record=boundary,
                production_context={"fixture": "production"},
                dependencies=fake.dependencies(),
            )
            self.assertEqual(fake.production_calls, [0])
            with self.assertRaisesRegex(
                target.BackendQ4TwoPhaseExecutorV1Error,
                "uncheckpointed record.*parent WAL",
            ) as caught:
                target.execute_backend_q4_two_phase_v1(
                    project_root=root,
                    source_registry_path=registry_path,
                    work_dir=work,
                    identity_manifest_output=work / "accepted-identity.json",
                    identity_inputs=identity_inputs(root),
                    production_context={"fixture": "production"},
                    dependencies=fake.dependencies(),
                )
            self.assertEqual(caught.exception.exit_code, target.EXIT_PERMANENT)
            self.assertEqual(fake.production_calls, [0])

    def test_checkpoint_rejects_phase_b_context_drift_before_new_arm(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            fake = FakePipeline(root)
            registry = source_registry(root)
            fired = False

            def fault(event: str, cell: target.BackendQ4CellV1 | None) -> None:
                nonlocal fired
                if (
                    event == "phase_b_after_record"
                    and cell is not None
                    and cell.cell_index == 0
                    and not fired
                ):
                    fired = True
                    raise RuntimeError("injected Phase-B interruption")

            common = {
                "project_root": root,
                "source_registry_path": registry,
                "work_dir": root / "q4-work",
                "identity_manifest_output": root / "q4-work/accepted-identity.json",
                "identity_inputs": identity_inputs(root),
                "dependencies": fake.dependencies(),
            }
            with self.assertRaisesRegex(
                RuntimeError, "injected Phase-B interruption"
            ):
                target.execute_backend_q4_two_phase_v1(
                    **common,
                    production_context={"fixture": "production"},
                    _fault_hook=fault,
                )
            self.assertEqual(fake.production_calls, [0])

            with self.assertRaisesRegex(
                target.BackendQ4TwoPhaseExecutorV1Error,
                "Phase-B production context/pins drifted",
            ):
                target.execute_backend_q4_two_phase_v1(
                    **common,
                    production_context={"fixture": "drifted"},
                )
            self.assertEqual(fake.production_calls, [0])

    def test_receipt_committed_phase_b_arm_resumes_without_second_launch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            fake = FakePipeline(root)
            registry = source_registry(root)
            committed_result: dict[str, object] | None = None
            persistence_calls = 0

            def resumable_execute(**kwargs: object) -> dict[str, object]:
                nonlocal committed_result
                if committed_result is None:
                    committed_result = fake.execute_production_arm(**kwargs)
                return copy.deepcopy(committed_result)

            def interrupted_persist(**kwargs: object) -> dict[str, object]:
                nonlocal persistence_calls
                persistence_calls += 1
                if persistence_calls == 1:
                    raise RuntimeError("injected post-receipt interruption")
                return fake.persist_authority(**kwargs)

            dependencies = replace(
                fake.dependencies(),
                execute_production_arm=resumable_execute,
                persist_production_authority=interrupted_persist,
            )
            common = {
                "project_root": root,
                "source_registry_path": registry,
                "work_dir": root / "q4-work",
                "identity_manifest_output": root / "q4-work/accepted-identity.json",
                "identity_inputs": identity_inputs(root),
                "production_context": {"fixture": "production"},
                "dependencies": dependencies,
            }
            with self.assertRaisesRegex(
                target.BackendQ4TwoPhaseExecutorV1Error,
                "authority persistence failed after durable fence",
            ):
                target.execute_backend_q4_two_phase_v1(**common)
            self.assertEqual(fake.production_calls, [0])

            def stop_after_recovered_record(
                event: str, cell: target.BackendQ4CellV1 | None
            ) -> None:
                if (
                    event == "phase_b_after_record"
                    and cell is not None
                    and cell.cell_index == 0
                ):
                    raise RuntimeError("recovered committed receipt")

            with self.assertRaisesRegex(RuntimeError, "recovered committed receipt"):
                target.execute_backend_q4_two_phase_v1(
                    **common, _fault_hook=stop_after_recovered_record
                )
            self.assertEqual(fake.production_calls, [0])
            self.assertEqual(persistence_calls, 2)
            first = target.backend_q4_cells_v1()[0]
            self.assertTrue(
                (
                    root
                    / "q4-work"
                    / "phase-b"
                    / "records"
                    / f"{first.arm_id}.json"
                ).is_file()
            )

    def test_authority_before_record_resume_is_idempotent_without_second_launch(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            fake = FakePipeline(root)
            registry = source_registry(root)
            committed_result: dict[str, object] | None = None
            persistence_calls = 0

            def resumable_execute(**kwargs: object) -> dict[str, object]:
                nonlocal committed_result
                if committed_result is None:
                    committed_result = fake.execute_production_arm(**kwargs)
                return copy.deepcopy(committed_result)

            def persist_then_interrupt(**kwargs: object) -> dict[str, object]:
                nonlocal persistence_calls
                persistence_calls += 1
                persisted = fake.persist_authority(**kwargs)
                if persistence_calls == 1:
                    raise RuntimeError("injected authority-before-record fault")
                return persisted

            dependencies = replace(
                fake.dependencies(),
                execute_production_arm=resumable_execute,
                persist_production_authority=persist_then_interrupt,
            )
            common = {
                "project_root": root,
                "source_registry_path": registry,
                "work_dir": root / "q4-work",
                "identity_manifest_output": root / "q4-work/accepted-identity.json",
                "identity_inputs": identity_inputs(root),
                "production_context": {"fixture": "production"},
                "dependencies": dependencies,
            }
            with self.assertRaisesRegex(
                target.BackendQ4TwoPhaseExecutorV1Error,
                "authority persistence failed",
            ) as caught:
                target.execute_backend_q4_two_phase_v1(**common)
            self.assertEqual(caught.exception.exit_code, target.EXIT_TRANSIENT)
            self.assertEqual(fake.production_calls, [0])

            def stop_after_record(
                event: str, cell: target.BackendQ4CellV1 | None
            ) -> None:
                if (
                    event == "phase_b_after_record"
                    and cell is not None
                    and cell.cell_index == 0
                ):
                    raise RuntimeError("recovered authority-before-record")

            with self.assertRaisesRegex(
                RuntimeError, "recovered authority-before-record"
            ):
                target.execute_backend_q4_two_phase_v1(
                    **common,
                    _fault_hook=stop_after_record,
                )
            self.assertEqual(fake.production_calls, [0])
            self.assertEqual(persistence_calls, 2)

    def test_pre_fence_input_collision_is_permanent_and_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            fake = FakePipeline(root)
            registry = source_registry(root)
            first = target.backend_q4_cells_v1()[0]
            collision = (
                root
                / "q4-work"
                / "phase-a"
                / "cells"
                / first.arm_id
                / "qualification-input.json"
            )
            collision.parent.mkdir(parents=True)
            original = b"operator-owned-collision\n"
            collision.write_bytes(original)

            with self.assertRaises(target.BackendQ4TwoPhaseExecutorV1Error) as caught:
                target.execute_backend_q4_two_phase_v1(
                    project_root=root,
                    source_registry_path=registry,
                    work_dir=root / "q4-work",
                    identity_manifest_output=root / "q4-work/accepted-identity.json",
                    identity_inputs=identity_inputs(root),
                    production_context={"fixture": "production"},
                    dependencies=fake.dependencies(),
                )
            self.assertEqual(caught.exception.exit_code, 78)
            self.assertEqual(collision.read_bytes(), original)
            self.assertEqual(fake.qualification_calls, [])

    def test_checkpoint_rejects_phase_b_progress_before_identity_grant(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            fake = FakePipeline(root)
            registry_path = source_registry(root)
            registry = json.loads(registry_path.read_text(encoding="ascii"))
            work = root / "q4-work"
            work.mkdir()
            state = target._initial_checkpoint(  # noqa: SLF001
                source_registry=registry,
                source_descriptor=descriptor(root, registry_path),
            )
            state["phase_b_records"] = [descriptor(root, registry_path)]
            checkpoint = target._checkpoint_value(state)  # noqa: SLF001
            (work / target.CHECKPOINT_FILENAME).write_bytes(canonical(checkpoint))

            with self.assertRaises(target.BackendQ4TwoPhaseExecutorV1Error) as caught:
                target.execute_backend_q4_two_phase_v1(
                    project_root=root,
                    source_registry_path=registry_path,
                    work_dir=work,
                    identity_manifest_output=work / "accepted-identity.json",
                    identity_inputs=identity_inputs(root),
                    production_context={"fixture": "production"},
                    dependencies=fake.dependencies(),
                )
            self.assertEqual(caught.exception.exit_code, 78)
            self.assertEqual(fake.events, [])
            self.assertEqual(fake.pin_calls, 0)

    def test_tampered_committed_evidence_blocks_resume(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            fake = FakePipeline(root)
            self.execute(root, fake, through_phase="phase_a")
            evidence = root / (
                "q4-work/phase-a/cells/0000-deepstream-h264-"
                "independent-processes-cpu-only-16p7/raw-evidence.json"
            )
            evidence.write_bytes(b"tampered\n")
            with self.assertRaises(target.BackendQ4TwoPhaseExecutorV1Error) as caught:
                target.execute_backend_q4_two_phase_v1(
                    project_root=root,
                    source_registry_path=root / "q4-source-registry.json",
                    work_dir=root / "q4-work",
                    identity_manifest_output=root / "q4-work/accepted-identity.json",
                    identity_inputs=identity_inputs(root),
                    production_context={"fixture": "production"},
                    dependencies=fake.dependencies(),
                )
            self.assertEqual(caught.exception.exit_code, 78)

    def test_fence_without_parent_wal_is_permanent_after_adapter_resume_probe(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            fake = FakePipeline(root)
            fake.fail_production_with_fence = True
            with self.assertRaises(target.BackendQ4TwoPhaseExecutorV1Error) as caught:
                self.execute(root, fake)
            self.assertEqual(caught.exception.exit_code, 78)
            self.assertEqual(fake.production_calls, [0])
            with self.assertRaises(target.BackendQ4TwoPhaseExecutorV1Error) as resumed:
                target.execute_backend_q4_two_phase_v1(
                    project_root=root,
                    source_registry_path=root / "q4-source-registry.json",
                    work_dir=root / "q4-work",
                    identity_manifest_output=root / "q4-work/accepted-identity.json",
                    identity_inputs=identity_inputs(root),
                    production_context={"fixture": "production"},
                    dependencies=fake.dependencies(),
            )
            self.assertEqual(resumed.exception.exit_code, 78)
            # A durable fence is no longer rejected before the production adapter:
            # the real adapter must be allowed to inspect its parent-pin WAL.  This
            # seam has no WAL, so its resume probe remains permanently rejected.
            self.assertEqual(fake.production_calls, [0, 0])


if __name__ == "__main__":
    unittest.main()
