from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from analytics_execution_bindings import (  # noqa: E402
    BINDING_SET_KIND,
    build_worker_bindings,
    materialize_worker_bindings,
)
from analytics_execution_protocol import (  # noqa: E402
    BRANCHES,
    ENGINE_OPENVINO_CPU,
    ENGINE_TENSORRT_CUDA,
    PROTOCOL_IDENTITY_SHA256,
    ProtocolError,
    canonical_sha256,
)


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _artifact(root: Path, name: str, payload: bytes) -> dict[str, object]:
    path = root / "models" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": _sha(payload),
        "size_bytes": len(payload),
    }


def _fixture(root: Path) -> tuple[dict[str, object], dict[str, object]]:
    sources: dict[str, object] = {}
    slots: dict[str, object] = {}
    for index, branch in enumerate(BRANCHES, start=1):
        source_ref = f"resnet{index}"
        source = _artifact(root, f"sources/{source_ref}.onnx", f"source-{branch}".encode())
        xml = _artifact(root, f"derived/{source_ref}.xml", f"xml-{branch}".encode())
        weights = _artifact(root, f"derived/{source_ref}.bin", f"weights-{branch}".encode())
        engine = _artifact(root, f"derived/{source_ref}.engine", f"engine-{branch}".encode())
        sources[source_ref] = {
            **source,
            "input": {
                "name": "data", "dtype": "float32", "layout": "NCHW",
                "execution_shape": [1, 3, 224, 224],
            },
            "output": {
                "name": f"logits_{index}", "dtype": "float32",
                "execution_shape": [1, 1000], "contract_ref": "raw_logits",
            },
        }
        slots[branch] = {
            "slot_id": f"opaque_rn{index}",
            "source_ref": source_ref,
            "openvino_ir": {"model": xml, "weights": weights},
            "tensorrt_engine": {"artifact": engine},
        }
    manifest = {
        "required_branches": list(BRANCHES),
        "preprocessing_contract": {
            "contract_id": "pre-v2", "output_dtype": "float32",
            "output_layout": "NCHW", "execution_shape": [1, 3, 224, 224],
        },
        "classification_contract": {
            "contract_id": "raw_logits", "dtype": "float32", "class_count": 1000,
        },
        "source_registry": sources,
        "workload_slots": slots,
        "toolchain_registry": {
            "tensorrt_cuda": {"gpu_uuid": "GPU-00000000-0000-0000-0000-000000000001"},
        },
        "identity": {"algorithm": "sha256", "sha256": "a" * 64},
    }
    config = {
        "protocol_identity_sha256": PROTOCOL_IDENTITY_SHA256,
        "workers": {
            "cpu": {
                "engine": ENGINE_OPENVINO_CPU,
                "image_id": "sha256:" + "b" * 64,
                "worker_implementation_sha256": "e" * 64,
            },
            "gpu": {
                "engine": ENGINE_TENSORRT_CUDA,
                "image_id": "sha256:" + "c" * 64,
                "worker_implementation_sha256": "f" * 64,
            },
        },
        "identity": {"algorithm": "sha256", "sha256": "d" * 64},
    }
    return manifest, config


class AnalyticsExecutionBindingsTests(unittest.TestCase):
    def test_builds_all_exact_hash_bound_worker_bindings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest, config = _fixture(root)
            bindings = build_worker_bindings(
                manifest,
                config,
                project_root=root,
                worker_project_root="/workspace",
            )

            self.assertEqual(set(bindings), set(BRANCHES))
            expected_preprocessing = canonical_sha256(manifest["preprocessing_contract"])
            for branch in BRANCHES:
                pair = bindings[branch]
                self.assertEqual(set(pair), {ENGINE_OPENVINO_CPU, ENGINE_TENSORRT_CUDA})
                source = manifest["source_registry"][manifest["workload_slots"][branch]["source_ref"]]
                expected_output = canonical_sha256({
                    "classification_contract": manifest["classification_contract"],
                    "source_output": source["output"],
                })
                cpu = pair[ENGINE_OPENVINO_CPU]
                gpu = pair[ENGINE_TENSORRT_CUDA]
                self.assertEqual(cpu["preprocessing_contract_sha256"], expected_preprocessing)
                self.assertEqual(gpu["output_contract_sha256"], expected_output)
                self.assertEqual(cpu["source_model_sha256"], gpu["source_model_sha256"])
                self.assertTrue(cpu["source_path"].startswith("/workspace/models/"))
                self.assertEqual(cpu["worker_image_id"], "sha256:" + "b" * 64)
                self.assertEqual(gpu["worker_image_id"], "sha256:" + "c" * 64)
                self.assertEqual(gpu["gpu_uuid"], "GPU-00000000-0000-0000-0000-000000000001")

    def test_rejects_mutated_authoritative_engine(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest, config = _fixture(root)
            slot = manifest["workload_slots"][BRANCHES[0]]
            engine = root / slot["tensorrt_engine"]["artifact"]["path"]
            engine.write_bytes(b"x" * engine.stat().st_size)

            with self.assertRaisesRegex(ProtocolError, "authoritative TensorRT engine SHA-256 mismatch"):
                build_worker_bindings(manifest, config, project_root=root)

    def test_materializes_canonical_index_and_individual_bindings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest, config = _fixture(root)
            output = root / "bindings"
            with mock.patch("analytics_execution_bindings.shutil.rmtree") as remove_tree:
                index = materialize_worker_bindings(
                    output,
                    manifest=manifest,
                    execution_config=config,
                    project_root=root,
                    worker_project_root="/workspace",
                )
            remove_tree.assert_not_called()

            self.assertEqual(index["artifact_kind"], BINDING_SET_KIND)
            self.assertEqual(len(index["files"]), len(BRANCHES) * 2)
            self.assertEqual(
                index["worker_implementation_sha256"],
                {ENGINE_OPENVINO_CPU: "e" * 64, ENGINE_TENSORRT_CUDA: "f" * 64},
            )
            raw = (output / "index.json").read_bytes()
            self.assertEqual(raw, json.dumps(index, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode() + b"\n")
            for record in index["files"]:
                payload = (output / record["path"]).read_bytes()
                self.assertEqual(hashlib.sha256(payload).hexdigest(), record["sha256"])
            with self.assertRaisesRegex(ProtocolError, "already exists"):
                materialize_worker_bindings(
                    output,
                    manifest=manifest,
                    execution_config=config,
                    project_root=root,
                )

    def test_rejects_invalid_worker_implementation_sha256(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest, config = _fixture(root)
            config["workers"]["cpu"]["worker_implementation_sha256"] = "not-a-sha256"
            with self.assertRaisesRegex(ProtocolError, "implementation SHA-256"):
                build_worker_bindings(manifest, config, project_root=root)

    def test_failed_replace_only_targets_the_exact_staging_child(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest, config = _fixture(root)
            output = root / "bindings"
            with (
                mock.patch(
                    "analytics_execution_bindings.os.replace",
                    side_effect=OSError("injected replace failure"),
                ),
                mock.patch("analytics_execution_bindings.shutil.rmtree") as remove_tree,
                self.assertRaisesRegex(OSError, "injected replace failure"),
            ):
                materialize_worker_bindings(
                    output,
                    manifest=manifest,
                    execution_config=config,
                    project_root=root,
                )

            remove_tree.assert_called_once()
            staging = Path(remove_tree.call_args.args[0])
            self.assertEqual(staging.parent, root.resolve())
            self.assertTrue(staging.name.startswith(".bindings."))
            self.assertNotEqual(staging, root.resolve())
            self.assertNotEqual(staging, Path.cwd().resolve())


if __name__ == "__main__":
    unittest.main()
