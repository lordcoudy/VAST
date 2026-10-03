from __future__ import annotations

import copy
import hashlib
import inspect
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import checkpoint_model_parity_materializer as materializer  # noqa: E402
import checkpoint_model_parity as parity  # noqa: E402
from checkpoint_model_parity_materializer import (  # noqa: E402
    FROZEN_KPP_FILES,
    MaterializerError,
    NonPublicationCollection,
    ProductionCollection,
    build_deterministic_sample_plan,
    build_promoted_manifest,
    collect_nonpublication_test_evidence,
    decode_validated_fp32_output,
    build_execution_probe_document,
    materialize_and_promote_model_parity,
    native_service_time_ms,
    promote_model_parity_evidence,
    verify_physical_file,
)


def sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


class ModelParityMaterializerTests(unittest.TestCase):
    def test_active_publication_dataset_ids_are_kpp_iss_v3(self) -> None:
        self.assertEqual(
            materializer.KPP_DATASET_BY_CODEC,
            {
                "h264": "kpp_iss_publication_v3_h264",
                "h265": "kpp_iss_publication_v3_h265",
            },
        )

    def test_frozen_kpp_inventory_is_exact(self) -> None:
        self.assertEqual(
            {item.relative_path for item in FROZEN_KPP_FILES},
            {
                "data/videos/kpp/kpp_iss_publication_v3/h264/iss_v2_underbody.mp4",
                "data/videos/kpp/kpp_iss_publication_v3/h264/iss_v2_front_gate.mp4",
                "data/videos/kpp/kpp_iss_publication_v3/h265/iss_v2_underbody.mp4",
                "data/videos/kpp/kpp_iss_publication_v3/h265/iss_v2_front_gate.mp4",
                "data/videos/kpp/kpp_iss_publication_v3/receipts/iss_v2_underbody_metadata.json",
            },
        )
        self.assertEqual(
            {item.sha256 for item in FROZEN_KPP_FILES},
            {
                "b7e5165549172266a5617ff7bbca6e5b888775b0a2490e27b7cbe17640e3b102",
                "08991b572d2d990a07536c9a4a7eed7780b27127c0e38abe7b607ba97dd59273",
                "5368c94a26659c529106724427fc6c3e60fe6788d56699da14c93bc4222e7839",
                "fa400ecc8b84afc8144fac1da522ef3e9e321c7feb89a5086ac1a1e3ccbe7728",
                "d23872d4b4706ef7d804f917a72407f82326eb3cdd5d39d347913f20cc65b0d4",
            },
        )

    def test_frozen_dataset_config_rejects_publication_v3_claim_drift(self) -> None:
        config = yaml.safe_load(
            (ROOT / "configs" / "datasets.yaml").read_text(encoding="utf-8")
        )
        config["datasets"]["kpp_iss_publication_v3_h264"]["provenance"]["claims"][
            "accuracy_ground_truth_validated"
        ] = True

        with self.assertRaisesRegex(MaterializerError, "claims|publication-v3"):
            materializer._validate_frozen_dataset_config(config)

    def test_default_real_path_fails_before_outputs_decoder_or_workers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            (root / "configs").mkdir()
            shutil.copyfile(ROOT / "configs" / "datasets.yaml", root / "configs" / "datasets.yaml")
            shutil.copyfile(
                ROOT / "configs" / "checkpoint_analytics_model_parity.yaml",
                root / "configs" / "checkpoint_analytics_model_parity.yaml",
            )
            output = root / "evidence" / "model_parity" / "materializations" / "run-1"
            accepted = root / "configs" / "checkpoint_analytics_model_parity.accepted.yaml"

            with mock.patch.object(materializer, "ProductionFfmpegDecoder") as decoder:
                with mock.patch.object(materializer, "NativeEndpointRunner") as endpoints:
                    with self.assertRaisesRegex(MaterializerError, "missing"):
                        materialize_and_promote_model_parity(
                            project_root=root,
                            dataset_manifest_path=root / "configs" / "datasets.yaml",
                            base_manifest_path=root / "configs" / "checkpoint_analytics_model_parity.yaml",
                            materialization_dir=output,
                            accepted_manifest_path=accepted,
                            ffmpeg_executable=root / "ffmpeg",
                            execution_config_path=root / "configs" / "analytics_execution_layer.yaml",
                            binding_set_dir=root / "bindings",
                            runtime_probe_paths={"cpu": root / "cpu.json", "gpu": root / "gpu.json"},
                            socket_dir=root / "sockets",
                        )
                    decoder.assert_not_called()
                    endpoints.assert_not_called()
            self.assertFalse(output.exists())
            self.assertFalse(output.parent.exists())
            self.assertFalse(accepted.exists())

    def test_sample_plan_is_stable_balanced_and_disjoint(self) -> None:
        first = build_deterministic_sample_plan()
        second = build_deterministic_sample_plan()
        self.assertEqual(first, second)
        self.assertEqual(len(first), 4 * 2 * 30)
        for branch in ("plate_number", "vehicle_type", "damage", "foreign_object"):
            branch_rows = [row for row in first if row.branch == branch]
            self.assertEqual(len(branch_rows), 60)
            for role in ("calibration", "evaluation"):
                role_rows = [row for row in branch_rows if row.role == role]
                self.assertEqual(len(role_rows), 30)
                self.assertEqual(
                    {codec: sum(row.codec == codec for row in role_rows) for codec in ("h264", "h265")},
                    {"h264": 15, "h265": 15},
                )
            calibration = {
                (row.relative_path, row.stream_index, row.frame_index)
                for row in branch_rows
                if row.role == "calibration"
            }
            evaluation = {
                (row.relative_path, row.stream_index, row.frame_index)
                for row in branch_rows
                if row.role == "evaluation"
            }
            self.assertTrue(calibration.isdisjoint(evaluation))
            self.assertEqual(len({row.sample_id for row in branch_rows}), 60)

    def test_production_runner_owns_attested_worker_lifecycle(self) -> None:
        plan = build_deterministic_sample_plan()
        bounds = materializer._worker_request_bounds(plan)
        self.assertEqual(set(bounds), set(parity.BRANCHES))
        for branch, request_count in bounds.items():
            self.assertEqual(
                request_count,
                sum(row.branch == branch for row in plan),
            )
            self.assertGreater(request_count, 0)

        source = (ROOT / "scripts" / "checkpoint_model_parity_materializer.py").read_text(
            encoding="utf-8"
        )
        runner_source = source[
            source.index("class NativeEndpointRunner:") : source.index(
                "class _UniqueKeyLoader"
            )
        ]
        self.assertIn("DockerWorkerProcessFactory", runner_source)
        self.assertIn("_open_owned_listener", runner_source)
        self.assertIn("expected_peer_pid", runner_source)
        self.assertIn("_attest_worker_peer_identity", runner_source)
        self.assertIn("_complete_peer_identity_after_handshake", runner_source)
        self.assertIn("DirectoryFdCustodyV1", runner_source)
        self.assertIn("mkdir_child_exclusive", runner_source)
        self.assertIn("self._retire_listener(owned)", runner_source)
        self.assertIn("_validate_retired_socket_record_v1", runner_source)
        self.assertIn("peer_identities", runner_source)
        self.assertNotIn("observed_peer_pid = _peer_pid", runner_source)
        self.assertNotIn("connection.connect(", runner_source)
        self.assertIn("worker_peer_identity_attestation.json", source)

    @unittest.skipUnless(os.name == "posix", "dirfd retirement is POSIX-only")
    def test_native_endpoint_listener_retirement_uses_physical_custody(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runtime_dir = Path(temporary) / "vast-runtime"
            runtime_dir.mkdir(mode=0o700)
            runner = object.__new__(materializer.NativeEndpointRunner)
            runner._socket_dir = runtime_dir
            runner._lifecycle_id = "a" * 32
            runner._socket_retirement_directory = runtime_dir.parent / (
                f".vast-model-parity-retired-{runner._lifecycle_id}"
            )
            runner._runtime_directory_custody = None
            runner._socket_retirement_directory_custody = None
            runner._opened_socket_names = set()
            runner._retired_socket_nodes = []
            runner._establish_socket_retirement_custody()
            owned = materializer._open_owned_listener(
                runtime_dir / "worker-plate_number-cpu.sock",
                backlog=1,
            )
            runner._opened_socket_names.add(owned.path.name)
            try:
                runner._retire_listener(owned)
                runner._verify_socket_retirement_namespace(require_all=True)
                self.assertEqual(list(runtime_dir.iterdir()), [])
                self.assertEqual(len(runner._retired_socket_nodes), 1)
                record = runner._retired_socket_nodes[0]
                self.assertEqual(
                    record["active_name"],
                    "worker-plate_number-cpu.sock",
                )
                self.assertEqual(
                    {item.name for item in runner._socket_retirement_directory.iterdir()},
                    {record["retired_name"]},
                )
            finally:
                runner._close_socket_retirement_custody()

    def test_verify_physical_file_rejects_links_and_hash_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            payload = b"physical fixture\n"
            real = root / "real.bin"
            real.write_bytes(payload)
            record = verify_physical_file(
                root,
                "real.bin",
                expected_sha256=sha(payload),
                label="fixture",
            )
            self.assertEqual(record.sha256, sha(payload))
            self.assertEqual(record.size_bytes, len(payload))

            alias = root / "alias.bin"
            try:
                os.link(real, alias)
            except OSError:
                self.skipTest("hard links are unavailable")
            with self.assertRaisesRegex(MaterializerError, "hardlink"):
                verify_physical_file(
                    root,
                    "real.bin",
                    expected_sha256=sha(payload),
                    label="fixture",
                )
            with self.assertRaisesRegex(MaterializerError, "hardlink"):
                verify_physical_file(
                    root,
                    "alias.bin",
                    expected_sha256=sha(payload),
                    label="fixture",
                )

    def test_project_relative_inputs_are_resolved_against_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            target = root / "artifacts" / "runtime" / "cpu.json"
            target.parent.mkdir(parents=True)
            target.write_text("{}\n", encoding="utf-8")

            self.assertNotEqual(Path.cwd().resolve(), root)
            self.assertEqual(
                materializer._project_relative(
                    root,
                    Path("artifacts/runtime/cpu.json"),
                    label="cpu runtime probe",
                ),
                Path("artifacts/runtime/cpu.json"),
            )

    def test_nonpublication_injection_is_structurally_unpromotable(self) -> None:
        signature = inspect.signature(collect_nonpublication_test_evidence)
        self.assertNotIn("accepted_manifest_path", signature.parameters)
        self.assertNotIn("materialization_dir", signature.parameters)
        collection = collect_nonpublication_test_evidence(
            decoder=lambda *_args, **_kwargs: (),
            runner=lambda *_args, **_kwargs: (),
        )
        self.assertIs(type(collection), NonPublicationCollection)
        with tempfile.TemporaryDirectory() as temporary:
            accepted = Path(temporary) / "accepted.yaml"
            with self.assertRaisesRegex(TypeError, "ProductionCollection"):
                promote_model_parity_evidence(
                    collection,
                    accepted_manifest_path=accepted,
                )
            self.assertFalse(accepted.exists())

    def test_promoted_manifest_copy_sets_only_final_evidence_refs(self) -> None:
        base = yaml.safe_load(
            (ROOT / "configs" / "checkpoint_analytics_model_parity.yaml").read_text(
                encoding="utf-8"
            )
        )
        frozen = copy.deepcopy(base)
        refs = {}
        for branch, slot in base["workload_slots"].items():
            for name in slot["evidence"]:
                refs[(branch, name)] = {
                    "path": f"evidence/model_parity/materializations/run-7/documents/{branch}/{name}.json",
                    "sha256": sha(f"{branch}:{name}".encode("ascii")),
                }
        promoted = build_promoted_manifest(base, evidence_refs=refs)
        self.assertEqual(len(refs), 32)
        self.assertEqual(base, frozen)
        self.assertEqual(
            promoted["workload_slots"]["damage"]["evidence"]["cpu_execution_probe"],
            refs[("damage", "cpu_execution_probe")],
        )
        serialized = yaml.safe_dump(promoted, sort_keys=False)
        self.assertNotIn(".staging", serialized)
        self.assertNotIn("sha256: null", serialized)

    def test_native_service_time_requires_protocol_validated_response(self) -> None:
        with self.assertRaisesRegex(TypeError, "ValidatedNativeResponse"):
            native_service_time_ms(
                {
                    "timing": {
                        "inference_started_monotonic_ns": 10,
                        "inference_finished_monotonic_ns": 1_000_010,
                        "inference_latency_ns": 1_000_000,
                    }
                }
            )

    def test_execution_bundle_ledger_persists_every_physical_sample(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            staging = root / ".candidate.staging"
            final = root / "candidate"
            staging.mkdir()
            expected = {
                ("damage", "calibration", "h264", "sample-00", "openvino_cpu"),
                ("damage", "calibration", "h264", "sample-00", "tensorrt_cuda"),
            }
            ledger = materializer._ExecutionBundleLedger(
                project_root=root,
                staging_root=staging,
                final_root=final,
                expected_coordinates=expected,
            )

            def response(resource: str, request_id: str):
                return materializer.ValidatedNativeResponse(
                    materializer._VALIDATED_RESPONSE_TOKEN,
                    request={"request_id": request_id},
                    response={},
                    capability={},
                    output=b"output",
                )

            def persisted(*_args, **kwargs):
                request_id = kwargs["request"]["request_id"]
                manifest = {
                    "request_id": request_id,
                    "files": {
                        "request": {"sha256": "1" * 64},
                        "response": {"sha256": "2" * 64},
                        "input_tensor": {"sha256": "3" * 64},
                        "output_tensor": {"sha256": "4" * 64},
                    },
                    "identity": {"sha256": "5" * 64},
                }
                bundle = staging / "execution_bundles" / request_id
                bundle.mkdir(parents=True)
                (bundle / "manifest.json").write_bytes(
                    materializer._canonical_json(manifest) + b"\n"
                )
                return manifest

            with mock.patch.object(
                materializer, "persist_execution_bundle", side_effect=persisted
            ) as persist:
                with mock.patch.object(
                    materializer,
                    "verify_execution_bundle",
                    side_effect=lambda path, *, capability: materializer._load_canonical_json_payload(
                        (Path(path) / "manifest.json").read_bytes(), label="fixture"
                    ),
                ) as verify:
                    for resource, request_id in (
                        ("openvino_cpu", "request-cpu"),
                        ("tensorrt_cuda", "request-gpu"),
                    ):
                        ledger.persist(
                            branch="damage",
                            role="calibration",
                            codec="h264",
                            sample_id="sample-00",
                            resource=resource,
                            response=response(resource, request_id),
                            input_tensor=b"input",
                        )
                    rows = ledger.finalize()

            self.assertEqual(persist.call_count, 2)
            self.assertEqual(verify.call_count, 2)
            self.assertEqual(len(rows), 2)
            self.assertEqual(
                {row["request_id"] for row in rows}, {"request-cpu", "request-gpu"}
            )
            self.assertEqual(
                {row["resource"] for row in rows}, {"openvino_cpu", "tensorrt_cuda"}
            )
            self.assertTrue(
                all(row["manifest"]["path"].startswith("candidate/execution_bundles/") for row in rows)
            )

            with self.assertRaisesRegex(MaterializerError, "duplicate"):
                ledger.persist(
                    branch="damage",
                    role="calibration",
                    codec="h264",
                    sample_id="sample-00",
                    resource="openvino_cpu",
                    response=response("openvino_cpu", "request-cpu-repeat"),
                    input_tensor=b"input",
                )

    def test_transaction_index_v2_binds_all_execution_bundles_and_self_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            staging = root / ".run.staging"
            final = root / "run"
            staging.mkdir()
            (staging / "physical.bin").write_bytes(b"physical\n")
            output_segments = [{"sample_id": "sample-00", "resource": "openvino_cpu"}]
            execution_bundles = [
                {
                    "request_id": "request-00",
                    "sample_id": "sample-00",
                    "resource": "openvino_cpu",
                }
            ]

            record = materializer._write_transaction_index(
                root=root,
                staging_root=staging,
                final_root=final,
                run_id="run",
                source_inventory={},
                output_segments=output_segments,
                execution_bundles=execution_bundles,
            )
            index = materializer._load_canonical_json_payload(
                record.path.read_bytes(), label="transaction fixture"
            )

            self.assertEqual(index["schema_version"], 2)
            self.assertEqual(index["execution_bundle_count"], 1)
            self.assertEqual(index["execution_bundles"], execution_bundles)
            self.assertEqual(
                index["execution_bundles_sha256"],
                sha(materializer._canonical_json(execution_bundles)),
            )
            identity = index.pop("transaction_sha256")
            self.assertEqual(identity, sha(materializer._canonical_json(index)))

            with self.assertRaisesRegex(MaterializerError, "cardinality"):
                materializer._write_transaction_index(
                    root=root,
                    staging_root=staging,
                    final_root=final,
                    run_id="run",
                    source_inventory={},
                    output_segments=output_segments,
                    execution_bundles=[],
                )

    def test_fp32_decode_rejects_partial_and_nonfinite_outputs(self) -> None:
        import struct

        good = struct.pack("<4f", 0.0, 1.0, -1.0, 2.0)
        self.assertEqual(
            decode_validated_fp32_output(good, expected_values=4),
            [0.0, 1.0, -1.0, 2.0],
        )
        with self.assertRaisesRegex(MaterializerError, "byte length"):
            decode_validated_fp32_output(good[:-1], expected_values=4)
        with self.assertRaisesRegex(MaterializerError, "non-finite"):
            decode_validated_fp32_output(
                struct.pack("<4f", 0.0, float("nan"), 1.0, 2.0),
                expected_values=4,
            )

    def test_production_collection_constructor_is_not_publicly_forgeable(self) -> None:
        with self.assertRaisesRegex(TypeError, "internal"):
            ProductionCollection()

    def test_execution_probe_records_actual_derived_worker_image_id(self) -> None:
        base = yaml.safe_load(
            (ROOT / "configs" / "checkpoint_analytics_model_parity.yaml").read_text(
                encoding="utf-8"
            )
        )
        execution = yaml.safe_load(
            (ROOT / "configs" / "analytics_execution_layer.yaml").read_text(
                encoding="utf-8"
            )
        )
        branch = "plate_number"
        slot = base["workload_slots"][branch]
        source = base["source_registry"][slot["source_ref"]]
        capability = {
            "worker_image_id": execution["workers"]["cpu"]["image_id"],
            "worker_implementation_sha256": execution["workers"]["cpu"]["worker_implementation_sha256"],
            "runtime_name": "OpenVINO",
            "device_api": "CPU",
            "device_id": "Intel(R) Core(TM) i7-14700K",
            "source_model_sha256": source["sha256"],
            "model_artifact_sha256": slot["openvino_ir"]["model"]["sha256"],
            "runtime_weights_sha256": slot["openvino_ir"]["weights"]["sha256"],
            "preprocessing_contract_sha256": sha(
                materializer._canonical_json(base["preprocessing_contract"])
            ),
            "output_contract_sha256": sha(
                materializer._canonical_json(
                    {
                        "classification_contract": base["classification_contract"],
                        "source_output": source["output"],
                    }
                )
            ),
        }
        probe = build_execution_probe_document(
            branch=branch,
            slot=slot,
            source=source,
            resource="openvino_cpu",
            capability=capability,
            sample_count=60,
        )
        self.assertEqual(probe["runtime_image_id"], execution["workers"]["cpu"]["image_id"])
        self.assertEqual(
            probe["worker_implementation_sha256"],
            execution["workers"]["cpu"]["worker_implementation_sha256"],
        )
        self.assertEqual(probe["device_id"], "CPU")
        self.assertNotEqual(probe["runtime_image_id"], base["toolchain_registry"]["openvino_cpu"]["image_id"])
        self.assertEqual(
            parity._execution_probe_blockers_v3(
                branch,
                slot,
                source,
                probe,
                resource="openvino_cpu",
                preprocessing_sha=capability["preprocessing_contract_sha256"],
                output_sha=capability["output_contract_sha256"],
                toolchains=base["toolchain_registry"],
                worker_runtimes=base["worker_runtime_registry"],
            ),
            [],
        )
        relabelled_probe = dict(probe)
        relabelled_probe["runtime_image_id"] = base["toolchain_registry"]["openvino_cpu"]["image_id"]
        self.assertIn(
            "branch:plate_number:cpu_execution_probe_image_mismatch",
            parity._execution_probe_blockers_v3(
                branch,
                slot,
                source,
                relabelled_probe,
                resource="openvino_cpu",
                preprocessing_sha=capability["preprocessing_contract_sha256"],
                output_sha=capability["output_contract_sha256"],
                toolchains=base["toolchain_registry"],
                worker_runtimes=base["worker_runtime_registry"],
            ),
        )
        drifted_probe = dict(probe)
        drifted_probe["worker_implementation_sha256"] = "0" * 64
        self.assertIn(
            "branch:plate_number:cpu_execution_probe_implementation_mismatch",
            parity._execution_probe_blockers_v3(
                branch,
                slot,
                source,
                drifted_probe,
                resource="openvino_cpu",
                preprocessing_sha=capability["preprocessing_contract_sha256"],
                output_sha=capability["output_contract_sha256"],
                toolchains=base["toolchain_registry"],
                worker_runtimes=base["worker_runtime_registry"],
            ),
        )

        gpu_capability = {
            **capability,
            "worker_image_id": execution["workers"]["gpu"]["image_id"],
            "worker_implementation_sha256": execution["workers"]["gpu"]["worker_implementation_sha256"],
            "runtime_name": "TensorRT",
            "device_api": "NVIDIA_CUDA",
            "device_id": base["toolchain_registry"]["tensorrt_cuda"]["gpu_uuid"],
            "model_artifact_sha256": slot["tensorrt_engine"]["artifact"]["sha256"],
            "runtime_weights_sha256": None,
        }
        gpu_probe = build_execution_probe_document(
            branch=branch,
            slot=slot,
            source=source,
            resource="tensorrt_cuda",
            capability=gpu_capability,
            sample_count=60,
        )
        self.assertEqual(
            gpu_probe["runtime_image_id"], execution["workers"]["gpu"]["image_id"]
        )
        self.assertNotEqual(
            gpu_probe["runtime_image_id"],
            base["toolchain_registry"]["tensorrt_cuda"]["image_id"],
        )
        self.assertEqual(
            parity._execution_probe_blockers_v3(
                branch,
                slot,
                source,
                gpu_probe,
                resource="tensorrt_cuda",
                preprocessing_sha=gpu_capability["preprocessing_contract_sha256"],
                output_sha=gpu_capability["output_contract_sha256"],
                toolchains=base["toolchain_registry"],
                worker_runtimes=base["worker_runtime_registry"],
            ),
            [],
        )

    def test_nonpublication_assessment_never_creates_accepted_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            (root / "configs").mkdir()
            materialization = root / "evidence" / "model_parity" / "materializations" / "run"
            materialization.mkdir(parents=True)
            base_path = root / "configs" / "base.yaml"
            base_bytes = b"base\n"
            base_path.write_bytes(base_bytes)
            base_record = materializer.verify_physical_file(
                root, "configs/base.yaml", expected_sha256=sha(base_bytes), label="base"
            )
            refs = {
                (branch, name): {
                    "path": f"evidence/model_parity/materializations/run/{branch}-{name}.json",
                    "sha256": "0" * 64,
                }
                for branch in ("plate_number", "vehicle_type", "damage", "foreign_object")
                for name in base_evidence_names()
            }
            promoted = {"schema_version": 3, "artifact_kind": "fixture"}
            collection = ProductionCollection(
                materializer._PRODUCTION_TOKEN,
                project_root=root,
                materialization_dir=materialization,
                base_manifest_record=base_record,
                base_manifest={},
                evidence_refs=refs,
                promoted_manifest=promoted,
            )
            accepted = root / "configs" / "accepted.yaml"
            assessment = {
                "publication_ready": False,
                "blockers": [
                    "branch:plate_number:cpu_execution_probe_image_mismatch",
                    "branch:plate_number:cuda_execution_probe_image_mismatch",
                ],
            }
            with mock.patch.object(materializer, "_verify_collection_final_paths"):
                with mock.patch.object(
                    materializer,
                    "load_parity_manifest",
                    return_value={**promoted, "identity": {"sha256": "0" * 64}},
                ):
                    with mock.patch.object(materializer, "assess_model_parity", return_value=assessment) as assessor:
                        with self.assertRaisesRegex(MaterializerError, "not publication-ready"):
                            promote_model_parity_evidence(collection, accepted_manifest_path=accepted)
            assessor.assert_called_once()
            self.assertFalse(accepted.exists())
            self.assertEqual(list(accepted.parent.glob(".*candidate*")), [])

    def test_accepted_manifest_is_written_only_after_publication_ready_assessment(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            (root / "configs").mkdir()
            materialization = root / "evidence" / "model_parity" / "materializations" / "run"
            materialization.mkdir(parents=True)
            base_path = root / "configs" / "base.yaml"
            base_bytes = b"base\n"
            base_path.write_bytes(base_bytes)
            base_record = materializer.verify_physical_file(
                root, "configs/base.yaml", expected_sha256=sha(base_bytes), label="base"
            )
            promoted = {"schema_version": 3, "artifact_kind": "fixture"}
            collection = ProductionCollection(
                materializer._PRODUCTION_TOKEN,
                project_root=root,
                materialization_dir=materialization,
                base_manifest_record=base_record,
                base_manifest={},
                evidence_refs={},
                promoted_manifest=promoted,
            )
            accepted = root / "configs" / "accepted.yaml"

            def assess(candidate: Path, *, project_root: Path):
                self.assertEqual(project_root, root)
                self.assertTrue(candidate.is_file())
                self.assertFalse(accepted.exists())
                self.assertNotIn(".staging", candidate.read_text(encoding="utf-8"))
                return {"publication_ready": True, "blockers": []}

            with mock.patch.object(materializer, "_verify_collection_final_paths"):
                with mock.patch.object(
                    materializer,
                    "load_parity_manifest",
                    return_value={**promoted, "identity": {"sha256": "0" * 64}},
                ):
                    with mock.patch.object(materializer, "assess_model_parity", side_effect=assess):
                        result = promote_model_parity_evidence(
                            collection, accepted_manifest_path=accepted
                        )
            self.assertTrue(accepted.is_file())
            self.assertEqual(result.accepted_manifest.sha256, sha(accepted.read_bytes()))
            self.assertEqual(list(accepted.parent.glob(".*candidate*")), [])

    def test_candidate_rebind_before_cleanup_preserves_final_and_foreign_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            (root / "configs").mkdir()
            materialization = root / "evidence" / "model_parity" / "materializations" / "run"
            materialization.mkdir(parents=True)
            base_path = root / "configs" / "base.yaml"
            base_path.write_bytes(b"base\n")
            base_record = materializer.verify_physical_file(
                root,
                "configs/base.yaml",
                expected_sha256=sha(b"base\n"),
                label="base",
            )
            promoted = {"schema_version": 3, "artifact_kind": "fixture"}
            collection = ProductionCollection(
                materializer._PRODUCTION_TOKEN,
                project_root=root,
                materialization_dir=materialization,
                base_manifest_record=base_record,
                base_manifest={},
                evidence_refs={},
                promoted_manifest=promoted,
            )
            accepted = root / "configs" / "accepted.yaml"
            candidate = accepted.parent / f".{accepted.name}.candidate.{os.getpid()}"
            stolen = candidate.with_name(candidate.name + ".stolen")

            def rebind_candidate(step: str) -> None:
                if step != "post_publish_pre_parent_fsync":
                    return
                os.replace(candidate, stolen)
                candidate.write_bytes(b"foreign\n")

            with (
                mock.patch.object(materializer, "_verify_collection_final_paths"),
                mock.patch.object(
                    materializer,
                    "load_parity_manifest",
                    return_value={**promoted, "identity": {"sha256": "0" * 64}},
                ),
                mock.patch.object(
                    materializer,
                    "assess_model_parity",
                    return_value={"publication_ready": True, "blockers": []},
                ),
                self.assertRaisesRegex(MaterializerError, "mutated|rebound|changed"),
            ):
                promote_model_parity_evidence(
                    collection,
                    accepted_manifest_path=accepted,
                    after_manifest_publish_step=rebind_candidate,
                )

            self.assertTrue(accepted.is_file())
            final_identity = accepted.stat().st_dev, accepted.stat().st_ino
            self.assertEqual(candidate.read_bytes(), b"foreign\n")
            self.assertTrue(stolen.is_file())
            self.assertNotEqual(
                (candidate.stat().st_dev, candidate.stat().st_ino), final_identity
            )
            self.assertNotEqual(
                (stolen.stat().st_dev, stolen.stat().st_ino), final_identity
            )

    def test_accepted_manifest_collision_is_immutable_and_unassessed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            (root / "configs").mkdir()
            materialization = root / "evidence" / "model_parity" / "materializations" / "run"
            materialization.mkdir(parents=True)
            base = root / "configs" / "base.yaml"
            base.write_bytes(b"base\n")
            base_record = materializer.verify_physical_file(
                root, "configs/base.yaml", expected_sha256=sha(b"base\n"), label="base"
            )
            collection = ProductionCollection(
                materializer._PRODUCTION_TOKEN,
                project_root=root,
                materialization_dir=materialization,
                base_manifest_record=base_record,
                base_manifest={},
                evidence_refs={},
                promoted_manifest={"schema_version": 3, "artifact_kind": "new"},
            )
            accepted = root / "configs" / "accepted.yaml"
            original = b"schema_version: 3\nartifact_kind: existing\n"
            accepted.write_bytes(original)
            with mock.patch.object(materializer, "assess_model_parity") as assessor:
                with self.assertRaisesRegex(MaterializerError, "immutable collision"):
                    promote_model_parity_evidence(
                        collection, accepted_manifest_path=accepted
                    )
            assessor.assert_not_called()
            self.assertEqual(accepted.read_bytes(), original)


def base_evidence_names() -> tuple[str, ...]:
    return (
        "cpu_execution_probe",
        "cuda_execution_probe",
        "calibration_corpus",
        "evaluation_corpus",
        "cpu_policy_calibration",
        "cuda_policy_calibration",
        "cpu_raw_output_bundle",
        "cuda_raw_output_bundle",
    )


if __name__ == "__main__":
    unittest.main()
