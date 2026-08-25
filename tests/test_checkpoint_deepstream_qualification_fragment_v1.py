from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from checkpoint_deepstream_qualification_fragment_v1 import (  # noqa: E402
    materialize_deepstream_qualification_fragment,
    validate_deepstream_qualification_fragment,
)
import checkpoint_deepstream_qualification_fragment_v1 as target  # noqa: E402


BRANCHES = ("plate_number", "vehicle_type", "damage", "foreign_object")
IMAGE_ID = "sha256:" + "1" * 64
SOURCE_SHA = "2" * 64
CPU_WORKER_IMAGE_ID = "sha256:" + "3" * 64
GPU_WORKER_IMAGE_ID = "sha256:" + "4" * 64
CPU_WORKER_IMPLEMENTATION = "5" * 64
GPU_WORKER_IMPLEMENTATION = "6" * 64
BASE_DIGEST = (
    "nvcr.io/nvidia/deepstream@sha256:"
    "c11befa808af8270e8ea0d0d7cc7cabbda08a2f496ee30b95f7acba5dce81759"
)


def _inspect() -> dict:
    return {
        "Id": IMAGE_ID,
        "RepoDigests": ["vast/deepstream-publication-runtime-v3@" + IMAGE_ID],
        "Os": "linux",
        "Architecture": "amd64",
        "Config": {
            "Entrypoint": ["/usr/local/bin/vast_deepstream_publication_runtime_v3"],
            "Env": ["DS_VERSION=7.0.0"],
            "Labels": {
                "org.vast.component": "deepstream-checkpoint-native-sdk-runtime",
                "org.vast.publication-runtime-abi": "3",
                "org.vast.publication-ready": "false",
                "org.vast.runtime-source-sha256": SOURCE_SHA,
                "org.vast.base-image-digest": BASE_DIGEST,
            },
        },
    }


class DeepStreamQualificationFragmentV1Tests(unittest.TestCase):
    def test_repository_refrozen_endpoint_materials_are_exactly_accepted(self) -> None:
        terminals, material = target._terminal_identities(
            ROOT, "GPU-00bb784b-60f3-8bf6-bbd3-5a0c09805266"
        )
        self.assertEqual(len(terminals), 8)
        self.assertEqual(
            {value["worker_image_id"] for value in terminals.values()},
            set(target.WORKER_IMAGE_IDS.values()),
        )
        self.assertEqual(
            material["accepted_model_parity_manifest"]["sha256"],
            "a570b8cc4bcc66119930f01239ed0fb2de7accd449b769d5a4b0511d70fb72b6",
        )
        self.assertEqual(
            material["analytics_binding_index"]["identity_sha256"],
            "6fb0a64f19d61ef7021a50ae35f04f55b344f0fe67911d29d43e03a00ebb635b",
        )

    @contextmanager
    def _accepted_pins(self):
        terminals = {}
        for branch in BRANCHES:
            for resource, suffix in (
                ("cpu", "openvino_cpu"),
                ("gpu", "tensorrt_cuda"),
            ):
                terminals[(branch, resource)] = {
                    "terminal_detector": f"detector-{branch}",
                    "terminal_backend": (
                        "analytics-execution:openvino_cpu;runtime=OpenVINO;"
                        "native_api=openvino.CompiledModel.__call__;"
                        "device=CPU:fixture-host-cpu"
                        if resource == "cpu"
                        else "analytics-execution:tensorrt_cuda;runtime=TensorRT;"
                        "native_api=nvinfer1::IExecutionContext::enqueueV3;"
                        "device=NVIDIA_CUDA:GPU-00bb784b-60f3-8bf6-bbd3-5a0c09805266"
                    ),
                    "worker_image_id": (
                        CPU_WORKER_IMAGE_ID
                        if resource == "cpu"
                        else GPU_WORKER_IMAGE_ID
                    ),
                    "worker_implementation_sha256": (
                        CPU_WORKER_IMPLEMENTATION
                        if resource == "cpu"
                        else GPU_WORKER_IMPLEMENTATION
                    ),
                    "binding_path": (
                        "artifacts/analytics_execution_bindings/publication_v3/"
                        f"{branch}.{suffix}.json"
                    ),
                    "probe_path": (
                        "artifacts/analytics_runtime_probes/publication_v3/"
                        f"{resource}_runtime_probe.json"
                    ),
                }
        with mock.patch(
            "checkpoint_deepstream_qualification_fragment_v1._terminal_identities",
            return_value=(terminals, {"fixture_accepted_material": True}),
        ):
            yield

    def _root(self, base: Path) -> Path:
        root = base / "project"
        for relative in (
            "scripts/checkpoint_native_policy_runtime.py",
            "scripts/checkpoint_deepstream_protocol_adapter.py",
            "scripts/checkpoint_deepstream_protocol_bridge.py",
            "scripts/checkpoint_deepstream_sdk_runtime.py",
            "scripts/checkpoint_deepstream_resource_runtime_v3.py",
            "scripts/checkpoint_gstreamer_runtime.py",
            "scripts/collect_metrics.py",
            "scripts/full_resource_contract.py",
            "scripts/resource_interval_contract.py",
        ):
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"physical source {relative}\n", encoding="utf-8")
        bindings = root / "artifacts/analytics_execution_bindings/publication_v3"
        probes = root / "artifacts/analytics_runtime_probes/publication_v3"
        bindings.mkdir(parents=True)
        probes.mkdir(parents=True)
        for branch in BRANCHES:
            for resource, suffix, kind in (
                ("cpu", "openvino_cpu", "vast_openvino_execution_worker_binding"),
                ("gpu", "tensorrt_cuda", "vast_tensorrt_execution_worker_binding"),
            ):
                (bindings / f"{branch}.{suffix}.json").write_text(
                    json.dumps(
                        {
                            "artifact_kind": kind,
                            "branch": branch,
                            "model_id": f"detector-{branch}",
                            "worker_image_id": (
                                CPU_WORKER_IMAGE_ID
                                if resource == "cpu"
                                else GPU_WORKER_IMAGE_ID
                            ),
                        },
                        sort_keys=True,
                    )
                    + "\n",
                    encoding="utf-8",
                )
        (probes / "cpu_runtime_probe.json").write_text(
            json.dumps(
                {
                    "engine": "openvino_cpu",
                    "runtime_name": "OpenVINO",
                    "native_inference_api": "openvino.CompiledModel.__call__",
                    "device_api": "CPU",
                    "device_id": "fixture-host-cpu",
                    "worker_implementation_sha256": CPU_WORKER_IMPLEMENTATION,
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        (probes / "gpu_runtime_probe.json").write_text(
            json.dumps(
                {
                    "engine": "tensorrt_cuda",
                    "runtime_name": "TensorRT",
                    "native_inference_api": "nvinfer1::IExecutionContext::enqueueV3",
                    "device_api": "NVIDIA_CUDA",
                    "device_id": "GPU-00bb784b-60f3-8bf6-bbd3-5a0c09805266",
                    "worker_implementation_sha256": GPU_WORKER_IMPLEMENTATION,
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        return root

    def test_materializes_exact_ten_unique_physical_bindings_and_no_pilots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(Path(tmp))
            output = root / "artifacts/deepstream_publication_v3/qualification"
            with self._accepted_pins():
                fragment_path = materialize_deepstream_qualification_fragment(
                    project_root=root,
                    output_dir=output,
                    image_inspect=_inspect(),
                    gpu_uuid="GPU-00bb784b-60f3-8bf6-bbd3-5a0c09805266",
                )
                fragment = validate_deepstream_qualification_fragment(
                    project_root=root,
                    fragment_path=fragment_path,
                )
            self.assertEqual(fragment["artifact_kind"], "vast_publication_qualification_system_fragment_v1")
            self.assertEqual(fragment["system"], "deepstream")
            self.assertEqual(
                set(fragment),
                {
                    "schema_version",
                    "artifact_kind",
                    "system",
                    "policy_bindings",
                    "resource_bindings",
                    "pilots",
                },
            )
            self.assertEqual(fragment["pilots"], [])
            self.assertEqual(len(fragment["policy_bindings"]), 8)
            self.assertEqual(len(fragment["resource_bindings"]), 2)

            policy_keys = {
                (row["branch"], row["resource"])
                for row in fragment["policy_bindings"]
            }
            self.assertEqual(
                policy_keys,
                {(branch, resource) for branch in BRANCHES for resource in ("cpu", "gpu")},
            )
            paths = [
                root / row["path"]
                for row in [*fragment["policy_bindings"], *fragment["resource_bindings"]]
            ]
            self.assertEqual(len(paths), len(set(paths)))
            self.assertEqual(len({path.stat().st_ino for path in paths}), 10)
            self.assertTrue(all(path.is_file() and not path.is_symlink() for path in paths))
            self.assertEqual(
                len({row["implementation_id"] for row in [*fragment["policy_bindings"], *fragment["resource_bindings"]]}),
                10,
            )
            self.assertEqual(
                len({row["emitter_id"] for row in [*fragment["policy_bindings"], *fragment["resource_bindings"]]}),
                10,
            )
            for row in [*fragment["policy_bindings"], *fragment["resource_bindings"]]:
                path = root / row["path"]
                self.assertEqual(row["size"], path.stat().st_size)
                self.assertEqual(row["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
                self.assertEqual(
                    set(row),
                    {
                        "role",
                        "branch",
                        "resource",
                        "path",
                        "sha256",
                        "size",
                        "implementation_id",
                        "emitter_id",
                        "runtime_identity",
                    },
                )
                expected_image = (
                    IMAGE_ID
                    if row["role"] == "resource"
                    else (
                        CPU_WORKER_IMAGE_ID
                        if row["resource"] == "cpu"
                        else GPU_WORKER_IMAGE_ID
                    )
                )
                self.assertEqual(
                    row["runtime_identity"]["worker_image_digest"], expected_image
                )
                if row["role"] == "policy":
                    self.assertEqual(
                        row["runtime_identity"]["device_api"],
                        "CPU" if row["resource"] == "cpu" else "NVIDIA_CUDA",
                    )
                    self.assertEqual(
                        row["runtime_identity"]["gpu_id"],
                        None if row["resource"] == "cpu" else 0,
                    )
                else:
                    self.assertEqual(
                        row["runtime_identity"]["analytics_device_api"],
                        "HOST_CPU"
                        if row["resource"] == "cpu"
                        else "NVIDIA_CUDA",
                    )
                artifact = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(
                    set(artifact["native_evidence_contract"]["roles"]),
                    {
                        "checkpoint_acceptance",
                        "frames",
                        "frame_events",
                        "ingress_ledger",
                        "topology_events",
                        "resource_intervals",
                        *(
                            {
                                "publication_policy_decisions.jsonl",
                                "branch_terminals",
                            }
                            if row["role"] == "policy"
                            else {
                                "hardware_resource_samples",
                                "fanout_work_counters",
                            }
                        ),
                    },
                )
                self.assertEqual(artifact["blockers"], [])

    def test_materialization_is_idempotent_but_refuses_physical_binding_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(Path(tmp))
            output = root / "artifacts/deepstream_publication_v3/qualification"
            with self._accepted_pins():
                first = materialize_deepstream_qualification_fragment(
                    project_root=root,
                    output_dir=output,
                    image_inspect=_inspect(),
                    gpu_uuid="GPU-00bb784b-60f3-8bf6-bbd3-5a0c09805266",
                )
                payload = first.read_bytes()
                second = materialize_deepstream_qualification_fragment(
                    project_root=root,
                    output_dir=output,
                    image_inspect=_inspect(),
                    gpu_uuid="GPU-00bb784b-60f3-8bf6-bbd3-5a0c09805266",
                )
            self.assertEqual(first, second)
            self.assertEqual(second.read_bytes(), payload)

            fragment = json.loads(first.read_text(encoding="utf-8"))
            binding = root / fragment["policy_bindings"][0]["path"]
            binding.write_bytes(b"drifted\n")
            with self._accepted_pins():
                with self.assertRaisesRegex(RuntimeError, "collision|drift"):
                    materialize_deepstream_qualification_fragment(
                        project_root=root,
                        output_dir=output,
                        image_inspect=_inspect(),
                        gpu_uuid="GPU-00bb784b-60f3-8bf6-bbd3-5a0c09805266",
                    )

    def test_validator_rejects_hardlink_alias_and_image_identity_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(Path(tmp))
            output = root / "artifacts/deepstream_publication_v3/qualification"
            with self._accepted_pins():
                fragment_path = materialize_deepstream_qualification_fragment(
                    project_root=root,
                    output_dir=output,
                    image_inspect=_inspect(),
                    gpu_uuid="GPU-00bb784b-60f3-8bf6-bbd3-5a0c09805266",
                )
            fragment = json.loads(fragment_path.read_text(encoding="utf-8"))
            first = root / fragment["policy_bindings"][0]["path"]
            alias = output / "alias.json"
            os.link(first, alias)
            with self._accepted_pins():
                with self.assertRaisesRegex(RuntimeError, "hardlink"):
                    validate_deepstream_qualification_fragment(
                        project_root=root,
                        fragment_path=fragment_path,
                    )

        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(Path(tmp))
            output = root / "artifacts/deepstream_publication_v3/qualification"
            inspect = _inspect()
            inspect["Config"]["Labels"]["org.vast.publication-ready"] = "true"
            with self._accepted_pins():
                with self.assertRaisesRegex(RuntimeError, "publication-ready"):
                    materialize_deepstream_qualification_fragment(
                        project_root=root,
                        output_dir=output,
                        image_inspect=inspect,
                        gpu_uuid="GPU-00bb784b-60f3-8bf6-bbd3-5a0c09805266",
                    )


if __name__ == "__main__":
    unittest.main()
