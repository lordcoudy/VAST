from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy" / "gstreamer_custom" / "publication"
DOCKERFILE = DEPLOY / "Dockerfile"
ENTRYPOINT = DEPLOY / "vast_gstreamer_custom_publication_runtime_v3"
LOCK = DEPLOY / "requirements.lock"
DEPENDENCY_ALLOWLIST = DEPLOY / "runtime-dependency-allowlist.txt"
BUILD_CONTEXT_ALLOWLIST = DEPLOY / "runtime-build-context-allowlist.txt"
COORDINATOR = (
    ROOT / "scripts" / "checkpoint_gstreamer_custom_container_coordinator_v3.py"
)
BUILD = ROOT / "scripts" / "build_gstreamer_custom_publication_runtime_v3.sh"
BASE_ID = (
    "sha256:fc26a96b600484da32fc304461a0484225b931e0e1ddfc9a1f112414d737b16a"
)
FROZEN_NATIVE_ARTIFACTS = (
    "/usr/local/bin/vast_native_gst_probe",
    "/usr/local/bin/vast_checkpoint_source",
    "/opt/vast/lib/gstreamer-1.0/libgstadaptivescheduler.so",
    "/opt/vast/lib/gstreamer-1.0/libgstvastanalyticsterminal.so",
    "/opt/vast/lib/gstreamer-1.0/libgstvastanalyticsqueue.so",
    "/opt/vast/lib/gstreamer-1.0/libgstvastcheckpointprefixqueue.so",
    "/opt/vast/share/gstreamer-registry.bin",
)


class GStreamerCustomPublicationImageV3Tests(unittest.TestCase):
    def test_image_has_exact_offline_normalized_final_stage(self) -> None:
        source = DOCKERFILE.read_text(encoding="utf-8")
        self.assertEqual(source.count("FROM ${BASE_IMAGE}"), 3)
        self.assertIn(
            "ARG BASE_IMAGE=vast/openvino-native-probe@" + BASE_ID,
            source,
        )
        self.assertIn("ARG SOURCE_DATE_EPOCH=0", source)
        self.assertIn("FROM ${BASE_IMAGE} AS native-provider", source)
        self.assertIn("AS runtime_builder", source)
        self.assertIn("-m pip install", source)
        self.assertIn("--no-index", source)
        self.assertIn("--require-hashes", source)
        self.assertIn("# BEGIN VAST_RUNTIME_SOURCE_ALLOWLIST", source)
        self.assertIn(
            "deploy/native_gst_probe/checkpoint_resource_interval_emitter.hpp",
            source,
        )
        self.assertNotIn("COPY deploy/native_gst_probe/ /opt/vast/native-src/", source)
        self.assertNotIn("COPY scripts/*.py", source)
        for forbidden in (
            "/usr/bin/c++",
            "/usr/bin/pkg-config",
            "/usr/bin/strip",
            "-ffile-prefix-map=/opt/vast/native-src=.",
            "-fdebug-prefix-map=/opt/vast/native-src=.",
        ):
            self.assertNotIn(forbidden, source)
        self.assertIn("vast_native_gst_probe.cpp", source)
        for artifact in FROZEN_NATIVE_ARTIFACTS:
            self.assertIn(
                f"COPY --from=native-provider {artifact} "
                f"/opt/vast/runtime-root{artifact}",
                source,
            )
        self.assertIn('touch -h -d "@${SOURCE_DATE_EPOCH}"', source)
        final_stage = source.rsplit("FROM ${BASE_IMAGE}", maxsplit=1)[1]
        self.assertNotIn("\nRUN ", final_stage)
        self.assertEqual(final_stage.count("\nCOPY --from=runtime_builder "), 1)
        for label in (
            'org.vast.component="gstreamer-custom-checkpoint-publication-runtime"',
            'org.vast.publication-runtime-abi="3"',
            'org.vast.base-image-id="${VAST_BASE_IMAGE_ID}"',
            'org.vast.native_probe.source_sha="${VAST_NATIVE_PROBE_SOURCE_SHA256}"',
        ):
            self.assertIn(label, final_stage)
        self.assertIn(
            'ENTRYPOINT ["/usr/local/bin/vast_gstreamer_custom_publication_runtime_v3"]',
            final_stage,
        )
        self.assertEqual(
            ENTRYPOINT.read_text(encoding="utf-8"),
            "#!/bin/sh\n"
            "exec /usr/bin/python3 -B "
            "/opt/vast/checkpoint/checkpoint_gstreamer_custom_container_coordinator_v3.py "
            '"$@"\n',
        )

    def test_dependency_lock_is_complete_and_hash_pinned(self) -> None:
        lines = [
            line.strip()
            for line in LOCK.read_text(encoding="ascii").splitlines()
            if line.strip() and not line.startswith("#")
        ]
        self.assertEqual(
            {line.split("==", 1)[0].lower() for line in lines},
            {"numpy", "pandas", "python-dateutil", "pyyaml", "six"},
        )
        self.assertTrue(all(" --hash=sha256:" in line for line in lines))

    def test_dependency_allowlist_is_exact_sorted_and_complete(self) -> None:
        values = DEPENDENCY_ALLOWLIST.read_text(encoding="utf-8").splitlines()
        expected = {
            "deploy/gstreamer_custom/publication/requirements.lock",
            *{
                path.relative_to(ROOT).as_posix()
                for path in (DEPLOY / "wheels").iterdir()
                if path.is_file()
            },
        }
        self.assertEqual(values, sorted(expected))

    def test_build_context_allowlist_binds_manifests_validator_and_builder(self) -> None:
        values = BUILD_CONTEXT_ALLOWLIST.read_text(encoding="utf-8").splitlines()
        self.assertEqual(values, sorted({
            "deploy/gstreamer_custom/publication/runtime-build-context-allowlist.txt",
            "deploy/gstreamer_custom/publication/runtime-dependency-allowlist.txt",
            "deploy/gstreamer_custom/publication/validate_runtime_source_closure_v3.py",
            "scripts/build_gstreamer_custom_publication_runtime_v3.sh",
            "scripts/materialize_runtime_build_context_v3.py",
        }))

    def test_coordinator_supplies_fixed_non_cli_gstreamer_authority(self) -> None:
        callback = mock.Mock(return_value=0)
        fake = types.ModuleType("checkpoint_gstreamer_runtime")
        fake.main = callback
        spec = importlib.util.spec_from_file_location(
            "gstreamer_custom_coordinator_v3_under_test", COORDINATOR
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        with mock.patch.dict(sys.modules, {"checkpoint_gstreamer_runtime": fake}):
            spec.loader.exec_module(module)
        self.assertEqual(
            module.main(("--scenario", "checkpoint_video_dag_shared")), 0
        )
        callback.assert_called_once_with(
            (
                "--system", "gstreamer_custom",
                "--scenario", "checkpoint_video_dag_shared",
            )
        )
        with self.assertRaisesRegex(ValueError, "system override"):
            module.main(("--system", "openvino_gva"))

    def test_builder_is_offline_and_proves_repeated_image_identity(self) -> None:
        source = BUILD.read_text(encoding="utf-8")
        for token in (
            "VAST_OPENVINO_NATIVE_PROBE_IMAGE",
            "VAST_OPENVINO_NATIVE_PROBE_IMAGE_ID",
            "--pull=false",
            "--no-cache",
            "--network=none",
            "--provenance=false",
            'source_date_epoch="0"',
            "deterministic image IDs differ",
            "org.vast.publication-runtime-abi",
            "/usr/local/bin/vast_native_gst_probe",
            "/usr/local/bin/vast_checkpoint_source",
            "/opt/vast/share/gstreamer-registry.bin",
            "runtime-source-allowlist.txt",
            "runtime-dependency-allowlist.txt",
            "validate_runtime_source_closure_v3.py",
            "materialize_runtime_build_context_v3.py",
            'build_context="$(mktemp -d /tmp/vast-gstreamer-custom-publication-v3.XXXXXXXX)"',
            '--output-dir "$build_context"',
            '--file "$build_context/deploy/gstreamer_custom/publication/Dockerfile"',
            '"$build_context"',
            "build_context_inputs_sha256",
            'mapfile -t runtime_sources < "$source_allowlist"',
            'native_probe_source_sha256="$(',
            '--build-arg "VAST_NATIVE_PROBE_SOURCE_SHA256=$native_probe_source_sha256"',
            '--build-arg "VAST_BASE_IMAGE_ID=$expected_base_id"',
            'native_source_label="$(docker image inspect',
        ):
            self.assertIn(token, source)
        self.assertNotIn("find scripts -maxdepth 1", source)
        self.assertNotIn("find deploy/native_gst_probe", source)
        self.assertNotIn(
            "--file deploy/gstreamer_custom/publication/Dockerfile \\\n    .",
            source,
        )


if __name__ == "__main__":
    unittest.main()
