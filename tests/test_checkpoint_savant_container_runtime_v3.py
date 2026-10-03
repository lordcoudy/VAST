from __future__ import annotations

import argparse
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from checkpoint_savant_container_runtime_v3 import (  # noqa: E402
    SavantContainerRuntimeV3Error,
    _verify_binding_artifacts,
    parse_sha_path_bindings,
    seed_savant_gstreamer_registries,
    terminal_status,
    validate_savant_native_stdio,
)
from checkpoint_savant_runtime_image_materialization_v3 import (  # noqa: E402
    NATIVE_BUILDER_IMAGE_ID,
    NATIVE_BUILDER_SOURCE_SHA256,
    build_runtime_image_materialization,
)


class SavantContainerRuntimeV3Tests(unittest.TestCase):
    def test_registry_seed_is_hashed_and_copied_to_every_internal_process(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            specs = [
                SimpleNamespace(environment={
                    "GST_REGISTRY": str(root / f"process-{index}.bin"),
                    "GST_REGISTRY_UPDATE": "no",
                    "GST_REGISTRY_FORK": "no",
                })
                for index in range(3)
            ]

            def runner(_command, **kwargs):
                Path(kwargs["env"]["GST_REGISTRY"]).write_bytes(
                    b"exact-savant-gpu-aware-registry"
                )
                return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

            audit = seed_savant_gstreamer_registries(
                specs[:2], specs[2:], codec="h264",
                registry_root=root, runner=runner,
            )
            expected = hashlib.sha256(
                b"exact-savant-gpu-aware-registry"
            ).hexdigest()
            self.assertEqual(audit["seed_sha256"], expected)
            self.assertEqual(audit["copy_count"], 3)
            self.assertIn("h264parse", audit["required_factories"])
            self.assertIn("nvv4l2decoder", audit["required_factories"])

    def test_materialized_bindings_are_rehashed_and_native_stdio_is_exact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            source = root / "kpp-stream-0.mp4"
            source.write_bytes(b"exact-kpp-v3-source")
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            self.assertEqual(
                parse_sha_path_bindings(
                    [f"{digest}={source}"], label="source", root=root,
                ),
                {digest: source},
            )
            with self.assertRaisesRegex(
                SavantContainerRuntimeV3Error, "SHA-256 drifted",
            ):
                parse_sha_path_bindings(
                    [f"{'0' * 64}={source}"], label="source", root=root,
                )
            stdout = root / "stdout.log"
            stderr = root / "stderr.log"
            stdout.write_text(
                "max_fps_dur 8.33333e+06 min_fps_dur 2e+08\n"
                "max_fps_dur 1.66667e+06 min_fps_dur 1.66667e+06\n",
                encoding="utf-8",
            )
            stderr.write_bytes(b"")
            audit = validate_savant_native_stdio(
                stdout, stderr, expected_worker_count=1,
            )
            self.assertEqual(audit["nvstreammux_default_timing_line_count"], 1)
            self.assertEqual(audit["nvstreammux_configured_timing_line_count"], 1)

    def test_frozen_gpu_model_paths_are_sha_bound_after_namespace_translation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            input_root = root / "input"
            frozen_root = root / "workspace"
            binding = {}
            model_bindings = {}
            expected_paths = set()
            for field, digest_field, relative, payload in (
                ("source_path", "source_model_sha256", Path("models/parity/source.onnx"), b"source"),
                ("engine_path", "model_artifact_sha256", Path("models/parity/runtime.engine"), b"engine"),
            ):
                materialized = input_root / "models" / relative
                materialized.parent.mkdir(parents=True, exist_ok=True)
                materialized.write_bytes(payload)
                digest = hashlib.sha256(payload).hexdigest()
                binding[field] = str(frozen_root / relative)
                binding[digest_field] = digest
                model_bindings[digest] = materialized
                expected_paths.add(materialized)

            self.assertEqual(
                _verify_binding_artifacts(
                    binding,
                    resource="gpu",
                    model_bindings=model_bindings,
                    input_root=input_root,
                    frozen_project_root=frozen_root,
                ),
                expected_paths,
            )
            model_bindings[binding["model_artifact_sha256"]] = next(
                path for path in expected_paths if path.name == "source.onnx"
            )
            with self.assertRaisesRegex(
                SavantContainerRuntimeV3Error,
                "undeclared model artifact",
            ):
                _verify_binding_artifacts(
                    binding,
                    resource="gpu",
                    model_bindings=model_bindings,
                    input_root=input_root,
                    frozen_project_root=frozen_root,
                )

    def test_terminal_status_is_exact_savant_abi_v3(self) -> None:
        args = argparse.Namespace(
            run_id="run-savant-v3", arm_id="arm-savant-v3",
            scenario="checkpoint_video_dag_shared",
            topology_kind="shared_video_dag", codec="h265",
            policy="gpu_only", deadline_ms=50.0,
            defer_full_resource_acceptance=False,
        )
        acceptance = {
            "status": "accepted_native_checkpoint_arm",
            "run_id": args.run_id, "system": "savant",
            "scenario": args.scenario,
            "topology_kind": args.topology_kind,
            "codec": args.codec, "policy": args.policy,
            "deadline_ms": args.deadline_ms,
        }
        result = terminal_status(args, publication_acceptance=acceptance)
        self.assertEqual(
            result["artifact_kind"],
            "vast_savant_publication_terminal_status_v3",
        )
        self.assertEqual(result["system"], "savant")
        self.assertTrue(result["accepted_benchmark_sidecars_written"])
        with self.assertRaisesRegex(
            SavantContainerRuntimeV3Error, "incomplete",
        ):
            terminal_status(
                args,
                publication_acceptance={
                    **acceptance,
                    "status": "pending_full_resource_validation",
                },
            )

    def test_source_is_one_arm_with_exact_24_or_6_workers_and_six_sources(self) -> None:
        source = (
            ROOT / "scripts" / "checkpoint_savant_container_runtime_v3.py"
        ).read_text(encoding="utf-8")
        for required in (
            "build_savant_runtime_plan",
            "build_savant_publication_worker_specs",
            "build_savant_publication_source_specs",
            "run_worker_processes",
            "NativePolicyRuntimeCoordinator",
            "publish_checkpoint_runtime",
            "merge_runtime_resource_intervals",
            "merge_runtime_fanout_work_counters",
            "promote_runtime_interval_and_fanout_evidence",
        ):
            self.assertIn(required, source)
        self.assertIn("expected_workers = 24", source)
        self.assertIn("len(source_specs) == 6", source)
        self.assertNotIn("synthetic", source.lower())
        entrypoint = (
            ROOT / "deploy" / "savant" / "publication"
            / "vast_savant_checkpoint_runtime"
        ).read_text(encoding="utf-8")
        self.assertIn("checkpoint_savant_container_runtime_v3.py", entrypoint)

        build = (
            ROOT / "scripts" / "build_savant_publication_runtime_v3.sh"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "ghcr.io/insight-platform/savant-deepstream@sha256:"
            "3c0ef6f4bb57e385644da526789626f0c943dcb90ff32b72a7883e05798ce9e6",
            build,
        )
        self.assertIn(
            "vast/savant-native-probe@sha256:"
            "314d4a4d71130e9b86caacb802e92fe97a89ee92b0240f9947dccebca3adc3dc",
            build,
        )
        self.assertIn("compute_runtime_source_sha256", build)
        self.assertIn("compute_runtime_bundle_sha256", build)
        self.assertIn("docker buildx build", build)
        self.assertIn("--provenance=false", build)
        self.assertIn("type=docker,rewrite-timestamp=true", build)
        self.assertIn("org.vast.savant.runtime-source-sha256", build)
        self.assertIn("org.vast.savant.runtime-bundle-sha256", build)


    def test_runtime_image_manifest_is_derived_from_exact_inspect_projection(self) -> None:
        source_sha = "1" * 64
        bundle_sha = "2" * 64
        labels = {
            "org.vast.savant.version": "0.5.17",
            "org.vast.deepstream.version": "7.0",
            "org.vast.base-image-id":
                "sha256:3c0ef6f4bb57e385644da526789626f0c943dcb90ff32b72a7883e05798ce9e6",
            "org.vast.native-builder-image-id":
                NATIVE_BUILDER_IMAGE_ID,
            "org.vast.native-builder-source-sha256":
                NATIVE_BUILDER_SOURCE_SHA256,
            "org.vast.savant.runtime-source-sha256": source_sha,
            "org.vast.savant.runtime-bundle-sha256": bundle_sha,
            "org.vast.publication-ready": "false",
        }
        inspect = {
            "Id": "sha256:" + "c" * 64,
            "Architecture": "amd64", "Os": "linux", "RepoDigests": [],
            "Config": {
                "Entrypoint": ["/usr/local/bin/vast_savant_checkpoint_runtime"],
                "Labels": labels,
            },
        }
        result = build_runtime_image_materialization(
            inspect=inspect,
            runtime_source_sha256=source_sha,
            runtime_bundle_sha256=bundle_sha,
        )
        self.assertEqual(
            result["artifact_kind"],
            "vast_savant_runtime_image_materialization_v3",
        )
        self.assertEqual(result["image_id"], inspect["Id"])
        self.assertRegex(result["inspect_projection_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(result["runtime_source_sha256"], source_sha)
        self.assertEqual(result["runtime_bundle_sha256"], bundle_sha)


if __name__ == "__main__":
    unittest.main()
