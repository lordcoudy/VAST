from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_PATH = (
    ROOT / "deploy" / "savant" / "publication" / "savant_publication_runtime_v3.py"
)
DOCKERFILE = ROOT / "deploy" / "savant" / "publication" / "Dockerfile"
ENTRYPOINT = (
    ROOT / "deploy" / "savant" / "publication" / "vast_savant_checkpoint_runtime"
)
BUILDER = ROOT / "scripts" / "build_savant_publication_runtime_v3.sh"


def load_runtime():
    spec = importlib.util.spec_from_file_location(
        "vast_savant_publication_image_runtime_v3", RUNTIME_PATH
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load Savant image runtime")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SavantPublicationImageV3Tests(unittest.TestCase):
    def test_exact_base_labels_and_entrypoint_are_frozen(self) -> None:
        dockerfile = DOCKERFILE.read_text(encoding="utf-8")
        self.assertIn(
            "ARG SAVANT_BASE_IMAGE=ghcr.io/insight-platform/"
            "savant-deepstream:0.5.17-7.0",
            dockerfile,
        )
        self.assertIn("FROM ${SAVANT_BASE_IMAGE}", dockerfile)
        self.assertIn(
            "FROM ${NATIVE_BUILDER_IMAGE} AS native-builder", dockerfile
        )
        for value in (
            'org.vast.component="savant-checkpoint-publication-runtime"',
            'org.vast.publication-runtime-abi="3"',
            'org.vast.savant.version="0.5.17"',
            'org.vast.deepstream.version="7.0"',
            'ARG VAST_BASE_IMAGE_ID',
            'org.vast.base-image-id="${VAST_BASE_IMAGE_ID}"',
        ):
            self.assertIn(value, dockerfile)
        builder = BUILDER.read_text(encoding="utf-8")
        self.assertIn(
            "expected_base_id=\"${VAST_SAVANT_BASE_IMAGE_ID:-"
            "sha256:3c0ef6f4bb57e385644da526789626f0c943dcb90ff32b72a7883e05798ce9e6}\"",
            builder,
        )
        self.assertIn('--build-arg "VAST_BASE_IMAGE_ID=$expected_base_id"', builder)
        self.assertIn(
            'ENTRYPOINT ["/usr/local/bin/vast_savant_checkpoint_runtime"]',
            dockerfile,
        )
        entrypoint = ENTRYPOINT.read_text(encoding="utf-8")
        self.assertIn('"$1" != "arm"', entrypoint)
        self.assertIn(
            "/opt/vast/checkpoint/checkpoint_savant_container_runtime_v3.py",
            entrypoint,
        )
        self.assertNotIn("savant_publication_runtime_v3.py", entrypoint)

    def test_runtime_contract_covers_exact_datasets_codecs_and_topologies(self) -> None:
        runtime = load_runtime()
        self.assertEqual(runtime.SAVANT_VERSION, "0.5.17")
        self.assertEqual(runtime.DEEPSTREAM_VERSION, "7.0")
        self.assertEqual(
            runtime.DATASET_BY_CODEC,
            {
                "h264": "kpp_iss_publication_v3_h264",
                "h265": "kpp_iss_publication_v3_h265",
            },
        )
        expected = {"independent_processes": 24, "shared_video_dag": 6}
        for topology, count in expected.items():
            rows = runtime.materialize_topology_descriptors(
                topology_kind=topology,
                dataset_id="kpp_iss_publication_v3_h264",
                codec="h264",
                policy="cpu_only",
                deadline_ms=50.0,
            )
            self.assertEqual(len(rows), count)
            self.assertEqual({row["stream_id"] for row in rows}, set(range(6)))
            self.assertEqual(
                {branch for row in rows for branch in row["branches"]},
                set(runtime.BRANCHES),
            )
            self.assertEqual(
                len({row["module_id"] for row in rows}), count
            )

    def test_worker_receipt_requires_real_savant_observations(self) -> None:
        runtime = load_runtime()
        base = {
            "schema_version": 3,
            "artifact_kind": runtime.WORKER_RECEIPT_KIND,
            "status": "completed_native_savant_worker",
            "run_id": "run-1",
            "arm_id": "arm-1",
            "module_id": "savant-stream-0-shared-video-dag",
            "topology_kind": "shared_video_dag",
            "stream_id": 0,
            "branches": list(runtime.BRANCHES),
            "dataset_id": "kpp_iss_publication_v3_h264",
            "codec": "h264",
            "source_sha256": "a" * 64,
            "module_config_sha256": "b" * 64,
            "savant_version": "0.5.17",
            "deepstream_version": "7.0",
            "decoder_factory": "nvv4l2decoder",
            "decoder_gpu_id": 0,
            "admitted_frames": 2,
            "decoded_frames": 2,
            "branch_terminals": 8,
            "branch_drops": 0,
            "runtime_event_count": 16,
            "worker_started_monotonic_ns": 1,
            "worker_completed_monotonic_ns": 2,
            "receipt_payload_sha256": "",
        }
        base["receipt_payload_sha256"] = runtime.receipt_payload_sha256(base)
        self.assertEqual(runtime.validate_worker_receipt(base), base)
        for field, value in (
            ("decoder_factory", "avdec_h264"),
            ("decoded_frames", 0),
            ("branch_terminals", 7),
        ):
            drifted = dict(base)
            drifted[field] = value
            drifted["receipt_payload_sha256"] = runtime.receipt_payload_sha256(drifted)
            with self.assertRaises(runtime.SavantPublicationImageRuntimeError):
                runtime.validate_worker_receipt(drifted)

    @unittest.skipIf(os.name == "nt", "image finalizer requires Linux fsync/fchmod")
    def test_finalizer_derives_evidence_only_from_complete_worker_receipts(self) -> None:
        runtime = load_runtime()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            modules = root / "modules"
            modules.mkdir()
            mapping = {"savant-pilot-evidence.json": "evidence/savant-pilot-evidence.json"}
            descriptors = runtime.materialize_topology_descriptors(
                topology_kind="shared_video_dag",
                dataset_id="kpp_iss_publication_v3_h264",
                codec="h264",
                policy="cpu_only",
                deadline_ms=50.0,
            )
            for descriptor in descriptors:
                receipt = {
                    "schema_version": 3,
                    "artifact_kind": runtime.WORKER_RECEIPT_KIND,
                    "status": "completed_native_savant_worker",
                    "run_id": "run-1",
                    "arm_id": "arm-1",
                    "module_id": descriptor["module_id"],
                    "topology_kind": "shared_video_dag",
                    "stream_id": descriptor["stream_id"],
                    "branches": descriptor["branches"],
                    "dataset_id": "kpp_iss_publication_v3_h264",
                    "codec": "h264",
                    "source_sha256": "a" * 64,
                    "module_config_sha256": "b" * 64,
                    "savant_version": "0.5.17",
                    "deepstream_version": "7.0",
                    "decoder_factory": "nvv4l2decoder",
                    "decoder_gpu_id": 0,
                    "admitted_frames": 1,
                    "decoded_frames": 1,
                    "branch_terminals": 4,
                    "branch_drops": 0,
                    "runtime_event_count": 8,
                    "worker_started_monotonic_ns": 1,
                    "worker_completed_monotonic_ns": 2,
                    "receipt_payload_sha256": "",
                }
                receipt["receipt_payload_sha256"] = runtime.receipt_payload_sha256(receipt)
                path = modules / descriptor["module_id"] / "worker-receipt.json"
                path.parent.mkdir()
                path.write_text(
                    json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n",
                    encoding="ascii",
                )
            terminal = runtime.finalize_runtime_output(
                runtime_output=root,
                run_id="run-1",
                arm_id="arm-1",
                scenario="checkpoint_video_dag_shared",
                topology_kind="shared_video_dag",
                dataset_id="kpp_iss_publication_v3_h264",
                codec="h264",
                policy="cpu_only",
                deadline_ms=50.0,
                module_count=6,
                evidence_mapping=mapping,
            )
            self.assertEqual(terminal["status"], "accepted_native_checkpoint_arm")
            evidence = root / mapping["savant-pilot-evidence.json"]
            payload = evidence.read_bytes()
            document = json.loads(payload)
            self.assertEqual(document["worker_receipt_count"], 6)
            self.assertEqual(document["decoded_frame_count"], 6)
            self.assertEqual(
                document["evidence_payload_sha256"],
                runtime.evidence_payload_sha256(document),
            )
            self.assertEqual(len(hashlib.sha256(payload).hexdigest()), 64)
            self.assertNotIn("evidence_sha256", terminal)


if __name__ == "__main__":
    unittest.main()
