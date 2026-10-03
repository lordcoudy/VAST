from __future__ import annotations

import importlib.util
import json
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock


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
    def test_savant_native_foundation_owns_exact_drop_queue_source(self) -> None:
        module = _module()
        registry = module.load_publication_image_registry(project_root=ROOT, registry_path=REGISTRY)
        queue_source = "deploy/savant/publication/gstvastcheckpointbranchqueue.cpp"
        for image in registry["images"]:
            sources = module.dockerfile_context_sources(
                project_root=ROOT, dockerfile_relative=image["dockerfile"])
            self.assertEqual(queue_source in sources, image["name"] == "native_probe_savant")
        dockerfile = (ROOT / "deploy/native_gst_probe/Dockerfile.savant").read_text(encoding="utf-8")
        self.assertIn("-fPIC -shared", dockerfile)
        self.assertIn("/usr/local/lib/gstreamer-1.0/libgstvastcheckpointbranchqueue.so", dockerfile)

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
        pinned_native_builder = (
            "nvcr.io/nvidia/deepstream@sha256:"
            "c11befa808af8270e8ea0d0d7cc7cabbda08a2f496ee30b95f7acba5dce81759"
        )
        for name in (
            "native_probe_deepstream",
            "native_probe_openvino",
            "native_probe_savant",
        ):
            self.assertEqual(
                by_name[name]["builder"],
                {"kind": "remote_digest", "reference": pinned_native_builder},
            )
        for name in ("analytics_worker_openvino", "analytics_worker_tensorrt"):
            self.assertEqual(by_name[name]["builder"], {"kind": "base"})
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
            self.assertIn("ARG VAST_BUILD_IMAGE_ID", source)
            self.assertIn('org.vast.publication-image.source-set-sha256', source)
            self.assertIn('org.vast.publication-image.dependency-set-sha256', source)
            self.assertIn('org.vast.publication-image.build-context-sha256', source)
            self.assertIn('org.vast.publication-image.base-image-id', source)
            self.assertIn('org.vast.publication-image.build-image-id', source)
            self.assertIn(
                "ENTRYPOINT " + json.dumps(image["entrypoint"], separators=(",", ":")),
                source,
            )
            if image["group"] == "native_probe":
                self.assertNotIn("command -v cmake", source)
                self.assertNotIn("cmake -S", source)
                self.assertIn("FROM ${BUILD_IMAGE}", source)
        savant_image = next(
            image for image in registry["images"]
            if image["name"] == "native_probe_savant"
        )
        savant = (ROOT / savant_image["dockerfile"]).read_text(
            encoding="utf-8",
        )
        self.assertIn(
            "/opt/vast/image-root/usr/local/bin/vast_checkpoint_source",
            savant,
        )
        self.assertIn(
            "checkpoint_source_coordinator.cpp",
            savant,
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

        legacy = (ROOT / "scripts" / "build_native_probe_images.sh").read_text(
            encoding="utf-8",
        )
        self.assertIn("build_native_probe_images_publication_v1.sh", legacy)
        self.assertNotIn("docker build", legacy)
        self.assertNotIn('"$PROJECT_DIR"', legacy)

    def test_registry_rejects_unpinned_remote_base(self) -> None:
        module = _module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "configs").mkdir()
            data = json.loads(REGISTRY.read_text(encoding="utf-8"))
            data["images"][0]["base"]["reference"] = "vendor/runtime:latest"
            path = root / "configs" / "publication_image_build_v1.json"
            path.write_bytes((json.dumps(data) + "\n").encode("utf-8"))
            with self.assertRaisesRegex(ValueError, "remote base is not digest-pinned"):
                module.load_publication_image_registry(
                    project_root=root,
                    registry_path=path,
                    validate_files=False,
                )

    def test_double_build_receipts_bind_native_producers_to_workers(self) -> None:
        module = _module()
        records: dict[str, dict[str, object]] = {}
        commands: list[tuple[str, ...]] = []
        entrypoints = {
            "vast/deepstream-native-probe:7.0": ["/usr/local/bin/vast_native_gst_probe"],
            "vast/openvino-native-probe:dlstreamer-2026.1": ["/usr/local/bin/vast_native_gst_probe"],
            "vast/savant-native-probe:0.5.17-7.0": ["/usr/local/bin/vast_native_gst_probe"],
            "vast/analytics-openvino-worker:publication-v3": ["/opt/vast/analytics/openvino_worker.py"],
            "vast/analytics-tensorrt-worker:publication-v3": ["/opt/vast/bin/vast_tensorrt_worker"],
        }
        users = {
            "vast/openvino-native-probe:dlstreamer-2026.1": "dlstreamer",
            "vast/analytics-openvino-worker:publication-v3": "dlstreamer",
        }

        def fake_run(command, *, env=None):
            values = tuple(command)
            commands.append(values)
            if values[1:3] == ("image", "inspect"):
                reference = values[3]
                if reference not in records:
                    self.assertIn("@sha256:", reference)
                    records[reference] = {
                        "Id": "sha256:" + hashlib.sha256(reference.encode()).hexdigest(),
                        "RepoDigests": [reference],
                        "Architecture": "amd64",
                        "Os": "linux",
                        "Created": "2024-08-01T00:00:00Z",
                        "Config": {"Entrypoint": None, "User": "root", "Labels": {}},
                    }
                return json.dumps([records[reference]])
            if values[1:3] == ("buildx", "build"):
                target = values[values.index("--tag") + 1]
                canonical = target.removesuffix("-determinism-a").removesuffix("-determinism-b")
                build_args = {}
                for index, value in enumerate(values):
                    if value == "--build-arg":
                        key, argument = values[index + 1].split("=", 1)
                        build_args[key] = argument
                records[target] = {
                    "Id": "sha256:" + hashlib.sha256(canonical.encode()).hexdigest(),
                    "RepoDigests": [],
                    "Architecture": "amd64",
                    "Os": "linux",
                    "Created": (
                        "1970-01-01T00:00:00Z"
                        if build_args["SOURCE_DATE_EPOCH"] == "0"
                        else "2024-08-01T00:00:00Z"
                    ),
                        "Config": {
                        "Entrypoint": entrypoints[canonical],
                        "User": users.get(canonical, "root"),
                        "Labels": {
                            "org.vast.publication-image.source-set-sha256": build_args["VAST_SOURCE_SET_SHA256"],
                            "org.vast.publication-image.dependency-set-sha256": build_args["VAST_DEPENDENCY_SET_SHA256"],
                            "org.vast.publication-image.build-context-sha256": build_args["VAST_BUILD_CONTEXT_SHA256"],
                            "org.vast.publication-image.base-image-id": build_args["VAST_BASE_IMAGE_ID"],
                            "org.vast.publication-image.build-image-id": build_args["VAST_BUILD_IMAGE_ID"],
                        },
                    },
                }
                return ""
            if values[1] == "tag":
                source_id, target = values[2], values[3]
                source = next(record for record in records.values() if record["Id"] == source_id)
                records[target] = json.loads(json.dumps(source))
                return ""
            if values[1] == "run":
                return ""
            self.fail(f"unexpected Docker command: {values}")

        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            native_work = parent / "native-work"
            worker_work = parent / "worker-work"
            native_work.mkdir()
            worker_work.mkdir()
            native_receipt = parent / "native.json"
            worker_receipt = parent / "worker.json"
            with mock.patch.object(module, "_run", fake_run):
                native = module.build_publication_image_group(
                    project_root=ROOT,
                    registry_path=REGISTRY,
                    group="native_probe",
                    work_root=native_work,
                    receipt_output=native_receipt,
                )
                workers = module.build_publication_image_group(
                    project_root=ROOT,
                    registry_path=REGISTRY,
                    group="analytics_worker",
                    work_root=worker_work,
                    receipt_output=worker_receipt,
                    producer_receipt=native_receipt,
                )
            self.assertEqual(len(native["images"]), 3)
            self.assertEqual(len(workers["images"]), 2)
            self.assertEqual(
                module.load_publication_image_freeze_receipt(worker_receipt)["receipt_sha256"],
                workers["receipt_sha256"],
            )
            builds = [command for command in commands if command[1:3] == ("buildx", "build")]
            self.assertEqual(len(builds), 10)
            self.assertTrue(all("--network=none" in command for command in builds))
            self.assertTrue(all("--no-cache" in command for command in builds))
            self.assertTrue(all(
                any(
                    value.startswith("VAST_BUILD_IMAGE_ID=sha256:")
                    for value in command
                )
                for command in builds
            ))


if __name__ == "__main__":
    unittest.main()
