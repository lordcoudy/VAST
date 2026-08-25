from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "publication_image_build_v1.py"
REGISTRY = ROOT / "configs" / "publication_image_build_v1.json"


def _module():
    spec = importlib.util.spec_from_file_location("publication_image_build_v1", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load publication image build module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PublicationImageBuildV1Tests(unittest.TestCase):
    def test_production_registry_is_exact_and_fail_closed(self) -> None:
        module = _module()
        registry = module.load_publication_image_registry(
            project_root=ROOT,
            registry_path=REGISTRY,
        )
        self.assertEqual(
            tuple(image["name"] for image in registry["images"]),
            (
                "native_probe_deepstream",
                "native_probe_openvino",
                "native_probe_savant",
                "analytics_worker_openvino",
                "analytics_worker_tensorrt",
            ),
        )
        self.assertEqual(
            tuple(image["group"] for image in registry["images"]),
            ("native_probe", "native_probe", "native_probe", "analytics_worker", "analytics_worker"),
        )
        by_name = {image["name"]: image for image in registry["images"]}
        self.assertEqual(
            by_name["native_probe_openvino"]["base"]["reference"],
            "intel/dlstreamer@sha256:355435d2bdb986fe1d51f443d366da3ac1eb0c7175aa03ce2b31e4485f36b3bd",
        )
        self.assertEqual(
            by_name["native_probe_deepstream"]["base"]["reference"],
            "nvcr.io/nvidia/deepstream@sha256:c11befa808af8270e8ea0d0d7cc7cabbda08a2f496ee30b95f7acba5dce81759",
        )
        self.assertEqual(
            by_name["native_probe_savant"]["base"]["reference"],
            "ghcr.io/insight-platform/savant-deepstream@sha256:3c0ef6f4bb57e385644da526789626f0c943dcb90ff32b72a7883e05798ce9e6",
        )
        self.assertEqual(
            by_name["analytics_worker_openvino"]["base"]["producer"],
            "native_probe_openvino",
        )
        self.assertEqual(
            by_name["analytics_worker_tensorrt"]["base"]["producer"],
            "native_probe_deepstream",
        )

    def test_production_contexts_are_exact_copy_closures(self) -> None:
        module = _module()
        registry = module.load_publication_image_registry(
            project_root=ROOT,
            registry_path=REGISTRY,
        )
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            for image in registry["images"]:
                output = parent / image["name"]
                output.mkdir()
                plan = module.materialize_image_context(
                    project_root=ROOT,
                    image=image,
                    output_dir=output,
                )
                observed = tuple(sorted(
                    path.relative_to(output).as_posix()
                    for path in output.rglob("*")
                    if path.is_file()
                ))
                self.assertEqual(observed, tuple(plan["relative_paths"]))
                self.assertEqual(
                    set(observed),
                    module.dockerfile_context_sources(
                        project_root=ROOT,
                        dockerfile_relative=image["dockerfile"],
                    ),
                )
                self.assertRegex(plan["source_set_sha256"], r"^[0-9a-f]{64}$")
                self.assertRegex(plan["dependency_set_sha256"], r"^[0-9a-f]{64}$")
                self.assertRegex(plan["build_context_sha256"], r"^[0-9a-f]{64}$")

    def test_production_dockerfiles_are_offline_and_identity_labelled(self) -> None:
        module = _module()
        registry = module.load_publication_image_registry(
            project_root=ROOT,
            registry_path=REGISTRY,
        )
        for image in registry["images"]:
            source = (ROOT / image["dockerfile"]).read_text(encoding="utf-8")
            lowered = source.lower()
            for forbidden in (
                "apt-get", "apk add", "dnf install", "yum install",
                "curl ", "wget ", "git clone", "add ",
            ):
                self.assertNotIn(forbidden, lowered, image["name"])
            self.assertIn("ARG VAST_SOURCE_SET_SHA256", source)
            self.assertIn("ARG VAST_DEPENDENCY_SET_SHA256", source)
            self.assertIn("ARG VAST_BUILD_CONTEXT_SHA256", source)
            self.assertIn("ARG VAST_BASE_IMAGE_ID", source)
            self.assertIn('org.vast.publication-image.source-set-sha256', source)
            self.assertIn('org.vast.publication-image.dependency-set-sha256', source)
            self.assertIn('org.vast.publication-image.build-context-sha256', source)
            self.assertIn('org.vast.publication-image.base-image-id', source)
            self.assertIn(
                "ENTRYPOINT " + json.dumps(image["entrypoint"], separators=(",", ":")),
                source,
            )

    def test_build_command_is_double_no_cache_and_network_none(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn('"buildx", "build"', source)
        self.assertIn('"--no-cache"', source)
        self.assertIn('"--pull=false"', source)
        self.assertIn('"--network=none"', source)
        self.assertIn('"--provenance=false"', source)
        self.assertIn('"--sbom=false"', source)
        self.assertIn('"type=docker,rewrite-timestamp=true,unpack=false"', source)
        self.assertIn("deterministic image IDs differ", source)

    def test_wrappers_pin_wsl_runtime_and_do_not_change_boot_configuration(self) -> None:
        for relative in (
            "scripts/build_native_probe_images_publication_v1.sh",
            "scripts/build_analytics_worker_images_publication_v1.sh",
        ):
            source = (ROOT / relative).read_text(encoding="utf-8")
            self.assertIn(
                ".publication-runtime/full-publication-cp312-v1/bin/python3.12",
                source,
            )
            self.assertIn("publication_image_build_v1.py", source)
            self.assertNotIn(".wslconfig", source)
            self.assertNotIn("wsl --shutdown", source.lower())
            self.assertNotIn("boot", source.lower())

    def test_registry_rejects_unpinned_remote_base(self) -> None:
        module = _module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "configs").mkdir()
            data = json.loads(REGISTRY.read_text(encoding="utf-8"))
            data["images"][0]["base"]["reference"] = "vendor/runtime:latest"
            path = root / "configs" / "publication_image_build_v1.json"
            path.write_text(json.dumps(data) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "remote base is not digest-pinned"):
                module.load_publication_image_registry(
                    project_root=root,
                    registry_path=path,
                    validate_files=False,
                )


if __name__ == "__main__":
    unittest.main()
