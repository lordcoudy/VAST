from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
ORCHESTRATOR = ROOT / "scripts" / "build_publication_runtime_images_after_refreeze_v1.py"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "build_publication_runtime_images_after_refreeze_v1", ORCHESTRATOR,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("runtime refreeze handoff cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PublicationRuntimeRefreezeHandoffV1Tests(unittest.TestCase):
    @staticmethod
    def _native_rows(module):
        return module._override_rows(
            {
                "native_probe_deepstream": {
                    "image_id": "sha256:" + "5" * 64,
                    "source_set_sha256": "6" * 64,
                    "base_image_id": "sha256:" + "7" * 64,
                    "base_reference": (
                        "nvcr.io/nvidia/deepstream@sha256:"
                        "c11befa808af8270e8ea0d0d7cc7cabbda08a2f496ee30b95f7acba5dce81759"
                    ),
                    "target_reference": "vast/deepstream-native-probe:7.0",
                },
                "native_probe_openvino": {
                    "image_id": "sha256:" + "1" * 64,
                    "source_set_sha256": "2" * 64,
                    "base_image_id": "sha256:" + "8" * 64,
                    "base_reference": (
                        "intel/dlstreamer@sha256:"
                        "355435d2bdb986fe1d51f443d366da3ac1eb0c7175aa03ce2b31e4485f36b3bd"
                    ),
                    "target_reference": "vast/openvino-native-probe:dlstreamer-2026.1",
                },
                "native_probe_savant": {
                    "image_id": "sha256:" + "3" * 64,
                    "source_set_sha256": "4" * 64,
                    "base_image_id": "sha256:" + "9" * 64,
                    "base_reference": (
                        "ghcr.io/insight-platform/savant-deepstream@sha256:"
                        "3c0ef6f4bb57e385644da526789626f0c943dcb90ff32b72a7883e05798ce9e6"
                    ),
                    "target_reference": "vast/savant-native-probe:0.5.17-7.0",
                },
            }
        )

    def test_openvino_derived_runtimes_bind_physical_refrozen_base_id(self) -> None:
        for name in ("openvino_gva", "gstreamer_custom"):
            dockerfile = (
                ROOT / "deploy" / name / "publication" / "Dockerfile"
            ).read_text(encoding="utf-8")
            build = (
                ROOT / "scripts" / f"build_{name}_publication_runtime_v3.sh"
            ).read_text(encoding="utf-8")
            self.assertIn("ARG VAST_BASE_IMAGE_ID", dockerfile)
            self.assertIn(
                'LABEL org.vast.base-image-id="${VAST_BASE_IMAGE_ID}"',
                dockerfile,
            )
            self.assertIn("VAST_OPENVINO_NATIVE_PROBE_IMAGE", build)
            self.assertIn("VAST_OPENVINO_NATIVE_PROBE_IMAGE_ID", build)
            self.assertIn(
                '--build-arg "VAST_BASE_IMAGE_ID=$expected_base_id"', build,
            )

    def test_savant_runtime_binds_refrozen_native_builder_id_and_source(self) -> None:
        dockerfile = (
            ROOT / "deploy/savant/publication/Dockerfile"
        ).read_text(encoding="utf-8")
        build = (
            ROOT / "scripts/build_savant_publication_runtime_v3.sh"
        ).read_text(encoding="utf-8")
        for argument in (
            "ARG VAST_BASE_IMAGE_ID",
            "ARG VAST_NATIVE_BUILDER_IMAGE_ID",
            "ARG VAST_NATIVE_BUILDER_SOURCE_SHA256",
        ):
            self.assertIn(argument, dockerfile)
        self.assertIn(
            'org.vast.base-image-id="${VAST_BASE_IMAGE_ID}"',
            dockerfile,
        )
        self.assertIn(
            'org.vast.native-builder-image-id="${VAST_NATIVE_BUILDER_IMAGE_ID}"',
            dockerfile,
        )
        self.assertIn(
            'org.vast.native-builder-source-sha256="${VAST_NATIVE_BUILDER_SOURCE_SHA256}"',
            dockerfile,
        )
        for variable in (
            "VAST_SAVANT_NATIVE_PROBE_IMAGE",
            "VAST_SAVANT_NATIVE_PROBE_IMAGE_ID",
            "VAST_SAVANT_NATIVE_PROBE_SOURCE_SHA256",
            "VAST_SAVANT_BASE_IMAGE_ID",
        ):
            self.assertIn(variable, build)

        materializer_path = (
            ROOT / "scripts/checkpoint_savant_runtime_image_materialization_v3.py"
        )
        spec = importlib.util.spec_from_file_location(
            "dynamic_savant_runtime_image_materialization_v3", materializer_path,
        )
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader if spec else None)
        materializer = importlib.util.module_from_spec(spec)
        assert spec is not None and spec.loader is not None
        spec.loader.exec_module(materializer)
        base_id = "sha256:" + "a" * 64
        builder_id = "sha256:" + "b" * 64
        builder_source = "c" * 64
        source_sha = "d" * 64
        bundle_sha = "e" * 64
        labels = {
            "org.vast.savant.version": "0.5.17",
            "org.vast.deepstream.version": "7.0",
            "org.vast.base-image-id": base_id,
            "org.vast.native-builder-image-id": builder_id,
            "org.vast.native-builder-source-sha256": builder_source,
            "org.vast.savant.runtime-source-sha256": source_sha,
            "org.vast.savant.runtime-bundle-sha256": bundle_sha,
            "org.vast.publication-ready": "false",
        }
        result = materializer.build_runtime_image_materialization(
            inspect={
                "Id": "sha256:" + "f" * 64,
                "Architecture": "amd64", "Os": "linux", "RepoDigests": [],
                "Config": {
                    "Entrypoint": ["/usr/local/bin/vast_savant_checkpoint_runtime"],
                    "Labels": labels,
                },
            },
            runtime_source_sha256=source_sha,
            runtime_bundle_sha256=bundle_sha,
            base_image_id=base_id,
            native_builder_image_id=builder_id,
            native_builder_source_sha256=builder_source,
        )
        self.assertEqual(result["base_image_id"], base_id)
        self.assertEqual(result["native_builder_image_id"], builder_id)
        self.assertEqual(result["native_builder_source_sha256"], builder_source)

    def test_handoff_plan_derives_all_runtime_environment_from_freeze_receipt(self) -> None:
        module = _load_module()
        plan = module.runtime_image_handoff_plan(
            project_root=ROOT,
            native_receipt=None,
            producer_image_overrides={
                "native_probe_deepstream": {
                    "image_id": "sha256:" + "5" * 64,
                    "source_set_sha256": "6" * 64,
                    "base_image_id": "sha256:" + "7" * 64,
                    "base_reference": (
                        "nvcr.io/nvidia/deepstream@sha256:"
                        "c11befa808af8270e8ea0d0d7cc7cabbda08a2f496ee30b95f7acba5dce81759"
                    ),
                    "target_reference": "vast/deepstream-native-probe:7.0",
                },
                "native_probe_openvino": {
                    "image_id": "sha256:" + "1" * 64,
                    "source_set_sha256": "2" * 64,
                    "base_image_id": "sha256:" + "8" * 64,
                    "base_reference": (
                        "intel/dlstreamer@sha256:"
                        "355435d2bdb986fe1d51f443d366da3ac1eb0c7175aa03ce2b31e4485f36b3bd"
                    ),
                    "target_reference": "vast/openvino-native-probe:dlstreamer-2026.1",
                },
                "native_probe_savant": {
                    "image_id": "sha256:" + "3" * 64,
                    "source_set_sha256": "4" * 64,
                    "base_image_id": "sha256:" + "9" * 64,
                    "base_reference": (
                        "ghcr.io/insight-platform/savant-deepstream@sha256:"
                        "3c0ef6f4bb57e385644da526789626f0c943dcb90ff32b72a7883e05798ce9e6"
                    ),
                    "target_reference": "vast/savant-native-probe:0.5.17-7.0",
                },
            },
        )
        self.assertEqual(
            [row["system"] for row in plan["runtime_builds"]],
            ["deepstream", "savant", "openvino_gva", "gstreamer_custom"],
        )
        for row in plan["runtime_builds"]:
            self.assertEqual(row["command"][0], "/usr/bin/bash")
        savant = plan["runtime_builds"][1]["environment"]
        self.assertEqual(
            plan["runtime_builds"][0]["environment"]["VAST_DEEPSTREAM_BASE_IMAGE_ID"],
            "sha256:" + "7" * 64,
        )
        self.assertEqual(
            savant["VAST_SAVANT_NATIVE_PROBE_IMAGE_ID"],
            "sha256:" + "3" * 64,
        )
        self.assertEqual(
            savant["VAST_SAVANT_NATIVE_PROBE_SOURCE_SHA256"], "4" * 64,
        )
        self.assertEqual(
            savant["VAST_SAVANT_BASE_IMAGE_ID"], "sha256:" + "9" * 64,
        )
        openvino = plan["runtime_builds"][2]["environment"]
        self.assertEqual(
            openvino["VAST_OPENVINO_NATIVE_PROBE_IMAGE_ID"],
            "sha256:" + "1" * 64,
        )

    def test_physical_receipt_requires_distinct_explicit_artifact_directory(self) -> None:
        module = _load_module()
        rows = self._native_rows(module)
        with mock.patch.object(
            module, "_receipt_rows", return_value=(rows, "a" * 64),
        ):
            with self.assertRaisesRegex(
                module.RuntimeImageRefreezeHandoffV1Error,
                "explicit artifact_dir is required",
            ):
                module.runtime_image_handoff_plan(
                    project_root=ROOT,
                    native_receipt=ORCHESTRATOR,
                )

            plan = module.runtime_image_handoff_plan(
                project_root=ROOT,
                native_receipt=ORCHESTRATOR,
                artifact_dir=ROOT / "artifacts",
            )
        self.assertEqual(plan["artifact_dir"], "artifacts")
        self.assertEqual(
            plan["runtime_builds"][1]["environment"][
                "VAST_SAVANT_RUNTIME_IMAGE_MANIFEST"
            ],
            str(ROOT / "artifacts" / "savant.runtime_image.materialized.v3.json"),
        )


if __name__ == "__main__":
    unittest.main()
