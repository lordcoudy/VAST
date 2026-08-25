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

from checkpoint_deepstream_container_runtime_v3 import (  # noqa: E402
    DeepStreamContainerRuntimeV3Error,
    parse_sha_path_bindings,
    seed_deepstream_gstreamer_registries,
    terminal_status,
    validate_deepstream_native_stdio,
)


class DeepStreamContainerRuntimeV3Tests(unittest.TestCase):
    def test_gpu_registry_seed_is_hashed_and_copied_to_every_process(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            specs = [
                SimpleNamespace(
                    environment={
                        "GST_REGISTRY": str(root / f"worker-{index}.bin"),
                        "GST_REGISTRY_UPDATE": "no",
                        "GST_REGISTRY_FORK": "no",
                    }
                )
                for index in range(3)
            ]

            def runner(_command, **kwargs):
                registry = Path(kwargs["env"]["GST_REGISTRY"])
                registry.write_bytes(b"exact-gpu-aware-registry")
                return SimpleNamespace(returncode=0, stdout=b"", stderr=b"scanner warning")

            audit = seed_deepstream_gstreamer_registries(
                specs[:2],
                specs[2:],
                codec="h265",
                registry_root=root,
                runner=runner,
            )
            expected = hashlib.sha256(b"exact-gpu-aware-registry").hexdigest()
            self.assertEqual(audit["seed_sha256"], expected)
            self.assertEqual(audit["copy_sha256"], expected)
            self.assertEqual(audit["copy_count"], 3)
            self.assertIn("h265parse", audit["required_factories"])
            self.assertIn("nvv4l2decoder", audit["required_factories"])
            self.assertTrue(all(
                Path(spec.environment["GST_REGISTRY"]).read_bytes()
                == b"exact-gpu-aware-registry"
                for spec in specs
            ))

    def test_native_stdio_is_bounded_exact_and_stderr_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            stdout = root / "stdout.log"
            stderr = root / "stderr.log"
            stdout.write_text(
                "nvstreammux: Successfully handled EOS for source_id=0\n"
                "nvstreammux: Successfully handled EOS for source_id=0\n",
                encoding="utf-8",
            )
            stderr.write_bytes(b"")
            audit = validate_deepstream_native_stdio(
                stdout,
                stderr,
                expected_worker_count=2,
            )
            self.assertEqual(audit["nvstreammux_eos_line_count"], 2)
            self.assertEqual(audit["stderr_bytes"], 0)

            stdout.write_text("unexpected child output\n", encoding="utf-8")
            with self.assertRaisesRegex(
                DeepStreamContainerRuntimeV3Error,
                "stdout contract",
            ):
                validate_deepstream_native_stdio(
                    stdout,
                    stderr,
                    expected_worker_count=1,
                )
            stdout.write_text(
                "nvstreammux: Successfully handled EOS for source_id=0\n",
                encoding="utf-8",
            )
            stderr.write_text("plugin warning\n", encoding="utf-8")
            with self.assertRaisesRegex(
                DeepStreamContainerRuntimeV3Error,
                "stderr contract",
            ):
                validate_deepstream_native_stdio(
                    stdout,
                    stderr,
                    expected_worker_count=1,
                )

    def test_materialized_sha_path_bindings_are_rehashed_and_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            source = root / "kpp-stream-0.mp4"
            source.write_bytes(b"exact-kpp-v3-source")
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            self.assertEqual(
                parse_sha_path_bindings(
                    [f"{digest}={source}"],
                    label="source",
                    root=root,
                ),
                {digest: source},
            )
            with self.assertRaisesRegex(DeepStreamContainerRuntimeV3Error, "SHA-256 drifted"):
                parse_sha_path_bindings(
                    [f"{'0' * 64}={source}"],
                    label="source",
                    root=root,
                )
            with self.assertRaisesRegex(DeepStreamContainerRuntimeV3Error, "duplicated"):
                parse_sha_path_bindings(
                    [f"{digest}={source}", f"{digest}={source}"],
                    label="source",
                    root=root,
                )

    def test_terminal_status_is_exact_success_only_abi_v3(self) -> None:
        args = argparse.Namespace(
            run_id="run-deepstream-v3",
            arm_id="arm-deepstream-v3",
            scenario="checkpoint_video_dag_shared",
            topology_kind="shared_video_dag",
            codec="h265",
            policy="deadline_aware_heft",
            deadline_ms=50.0,
            defer_full_resource_acceptance=False,
        )
        acceptance = {
            "status": "accepted_native_checkpoint_arm",
            "run_id": "run-deepstream-v3",
            "system": "deepstream",
            "scenario": "checkpoint_video_dag_shared",
            "topology_kind": "shared_video_dag",
            "codec": "h265",
            "policy": "deadline_aware_heft",
            "deadline_ms": 50.0,
        }
        self.assertEqual(
            terminal_status(args, publication_acceptance=acceptance),
            {
                "schema_version": 3,
                "artifact_kind": "vast_deepstream_publication_terminal_status_v3",
                "run_id": "run-deepstream-v3",
                "arm_id": "arm-deepstream-v3",
                "system": "deepstream",
                "scenario": "checkpoint_video_dag_shared",
                "topology_kind": "shared_video_dag",
                "codec": "h265",
                "policy": "deadline_aware_heft",
                "deadline_ms": 50.0,
                "accepted_benchmark_sidecars_written": True,
                "publication_blockers": [],
                "publication_acceptance": acceptance,
            },
        )
        with self.assertRaisesRegex(DeepStreamContainerRuntimeV3Error, "incomplete"):
            terminal_status(
                args,
                publication_acceptance={**acceptance, "status": "pending_full_resource_validation"},
            )
        args.defer_full_resource_acceptance = True
        candidate = {**acceptance, "status": "pending_full_resource_validation"}
        deferred = terminal_status(args, publication_acceptance=candidate)
        self.assertEqual(deferred["publication_acceptance"], candidate)

    def test_coordinator_source_uses_real_sdk_graph_and_common_finalizer(self) -> None:
        source = (ROOT / "scripts" / "checkpoint_deepstream_container_runtime_v3.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("build_deepstream_runtime_plan", source)
        self.assertIn("build_deepstream_worker_specs", source)
        self.assertIn("run_worker_processes", source)
        self.assertIn("NativePolicyRuntimeCoordinator", source)
        self.assertIn("publish_checkpoint_runtime", source)
        self.assertIn("merge_runtime_resource_intervals", source)
        self.assertIn("merge_runtime_fanout_work_counters", source)
        self.assertIn("promote_runtime_interval_and_fanout_evidence", source)
        self.assertNotIn("synthetic", source.lower())

    def test_runtime_image_recipe_is_pinned_to_abi3_coordinator(self) -> None:
        dockerfile = (
            ROOT / "deploy" / "deepstream" / "checkpoint" / "Dockerfile.runtime"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "nvcr.io/nvidia/deepstream@sha256:c11befa808af8270e8ea0d0d7cc7cabbda08a2f496ee30b95f7acba5dce81759",
            dockerfile,
        )
        self.assertIn('org.vast.publication-runtime-abi="3"', dockerfile)
        self.assertIn("vast_checkpoint_source", dockerfile)
        self.assertIn("libvast_deepstream_meta_bridge.so", dockerfile)
        self.assertIn(
            "COPY deploy/deepstream/checkpoint/requirements.lock",
            dockerfile,
        )
        self.assertNotIn(
            "COPY deploy/deepstream/checkpoint/wheels/",
            dockerfile,
        )
        self.assertIn(
            "deploy/deepstream/checkpoint/wheels/"
            "numpy-1.26.4-cp310-cp310-manylinux_2_17_x86_64."
            "manylinux2014_x86_64.whl",
            dockerfile,
        )
        self.assertIn("--no-index --no-deps --no-compile --require-hashes", dockerfile)
        requirements = (
            ROOT / "deploy" / "deepstream" / "checkpoint" / "requirements.lock"
        ).read_text(encoding="utf-8")
        for exact_requirement in (
            "numpy==1.26.4 --hash=sha256:ffa75af20b44f8dba823498024771d5ac50620e6915abac414251bd971b4529f",
            "pandas==2.2.3 --hash=sha256:86976a1c5b25ae3f8ccae3a5306e443569ee3c3faf444dfd0f41cda24667ad57",
            "python-dateutil==2.9.0.post0 --hash=sha256:a8b2bc7bffae282281c8140a97d3aa9c14da0b136dfe83f850eea9a5f7470427",
            "pytz==2026.3.post1 --hash=sha256:dd95840dd199baea12d9cc096a1d452caa6596a1c1e4b5f3dbd1541855d5e815",
            "tzdata==2026.3 --hash=sha256:dc096730c87af6cab1b171c9d532be840741ff5d459015e7f6947bd7d7e54931",
            "PyYAML==6.0.2 --hash=sha256:ec031d5d2feb36d1d1a24380e4db6d43695f3748343d99434e6f5f9156aaa2ed",
            "six==1.17.0 --hash=sha256:4721f391ed90541fddacab5acf947aa0d3dc7d27b2e1e8eda2be8970586c3274",
        ):
            self.assertIn(exact_requirement, requirements)
        self.assertIn(
            'ENTRYPOINT ["/usr/local/bin/vast_deepstream_publication_runtime_v3"]',
            dockerfile,
        )
        self.assertIn("ARG SOURCE_DATE_EPOCH", dockerfile)
        build_script = (
            ROOT / "scripts" / "build_deepstream_publication_runtime_v3.sh"
        ).read_text(encoding="utf-8")
        self.assertIn('source_date_epoch="1722470400"', build_script)
        self.assertIn("docker buildx build", build_script)
        self.assertIn("--network=none", build_script)
        self.assertIn('--provenance=false', build_script)
        self.assertIn('type=docker,rewrite-timestamp=true', build_script)
        self.assertIn('SOURCE_DATE_EPOCH=$source_date_epoch', build_script)
        self.assertNotIn("find scripts", build_script)
        self.assertNotIn("find deploy/native_gst_probe", build_script)
        self.assertIn("runtime-source-allowlist.txt", build_script)
        self.assertIn("runtime-dependency-allowlist.txt", build_script)
        self.assertIn('post_build_source_sha256=', build_script)
        self.assertIn('DeepStream runtime source changed during build', build_script)


if __name__ == "__main__":
    unittest.main()
