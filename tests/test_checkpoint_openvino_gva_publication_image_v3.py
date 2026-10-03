from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy" / "openvino_gva" / "publication"
DOCKERFILE = DEPLOY / "Dockerfile"
ENTRYPOINT = DEPLOY / "vast_openvino_gva_publication_runtime_v3"
ALLOWLIST = DEPLOY / "runtime-source-allowlist.txt"
BUILD = ROOT / "scripts" / "build_openvino_gva_publication_runtime_v3.sh"
DEPENDENCY_ALLOWLIST = (
    ROOT / "deploy" / "gstreamer_custom" / "publication"
    / "runtime-dependency-allowlist.txt"
)
BUILD_CONTEXT_ALLOWLIST = DEPLOY / "runtime-build-context-allowlist.txt"
BASE_ID = "sha256:fc26a96b600484da32fc304461a0484225b931e0e1ddfc9a1f112414d737b16a"
FROZEN_NATIVE_ARTIFACTS = (
    "/usr/local/bin/vast_native_gst_probe",
    "/usr/local/bin/vast_checkpoint_source",
    "/opt/vast/lib/gstreamer-1.0/libgstadaptivescheduler.so",
    "/opt/vast/lib/gstreamer-1.0/libgstvastanalyticsterminal.so",
    "/opt/vast/lib/gstreamer-1.0/libgstvastanalyticsqueue.so",
    "/opt/vast/lib/gstreamer-1.0/libgstvastcheckpointprefixqueue.so",
    "/opt/vast/share/gstreamer-registry.bin",
)


class OpenVINOGVAPublicationImageV3Tests(unittest.TestCase):
    def test_image_is_offline_normalized_and_contains_exact_native_runtime(self) -> None:
        source = DOCKERFILE.read_text(encoding="utf-8")
        self.assertEqual(source.count("FROM ${BASE_IMAGE}"), 3)
        self.assertIn("ARG BASE_IMAGE=vast/openvino-native-probe@" + BASE_ID, source)
        self.assertIn("ARG SOURCE_DATE_EPOCH=0", source)
        self.assertIn("FROM ${BASE_IMAGE} AS native-provider", source)
        self.assertIn("FROM ${BASE_IMAGE} AS runtime_builder", source)
        self.assertIn("# BEGIN VAST_RUNTIME_SOURCE_ALLOWLIST", source)
        self.assertIn("checkpoint_analytics_execution_client.hpp", source)
        self.assertIn("checkpoint_resource_interval_emitter.hpp", source)
        self.assertIn("vast_native_gst_probe.cpp", source)
        self.assertNotIn("COPY scripts/*.py", source)
        self.assertNotIn("COPY deploy/native_gst_probe/ /opt/vast/native-src/", source)
        for forbidden in (
            "/usr/bin/c++",
            "/usr/bin/pkg-config",
            "/usr/bin/strip",
            "-ffile-prefix-map=/opt/vast/native-src=.",
            "-fdebug-prefix-map=/opt/vast/native-src=.",
        ):
            self.assertNotIn(forbidden, source)
        for artifact in FROZEN_NATIVE_ARTIFACTS:
            self.assertIn(
                f"COPY --from=native-provider {artifact} "
                f"/opt/vast/runtime-root{artifact}",
                source,
            )
        self.assertIn('touch -h -d "@${SOURCE_DATE_EPOCH}"', source)
        final = source.rsplit("FROM ${BASE_IMAGE}", maxsplit=1)[1]
        self.assertNotIn("\nRUN ", final)
        self.assertEqual(final.count("\nCOPY --from=runtime_builder "), 1)
        self.assertIn(
            'ENTRYPOINT ["/usr/local/bin/vast_openvino_gva_publication_runtime_v3"]',
            final,
        )
        self.assertEqual(
            ENTRYPOINT.read_text(encoding="utf-8"),
            "#!/bin/sh\n"
            "exec /usr/bin/python3 -B "
            "/opt/vast/checkpoint/checkpoint_openvino_gva_container_coordinator_v3.py "
            '"$@"\n',
        )

    def test_builder_proves_ab_identity_without_network_or_cache(self) -> None:
        source = BUILD.read_text(encoding="utf-8")
        for token in (
            "--no-cache",
            "--network=none",
            "--pull=false",
            "--provenance=false",
            'source_date_epoch="0"',
            "deterministic image IDs differ",
            "validate_runtime_source_closure_v3.py",
            "runtime-dependency-allowlist.txt",
            "materialize_runtime_build_context_v3.py",
            'build_context="$(mktemp -d /tmp/vast-openvino-gva-publication-v3.XXXXXXXX)"',
            '--output-dir "$build_context"',
            '--file "$build_context/deploy/openvino_gva/publication/Dockerfile"',
            '"$build_context"',
            "build_context_inputs_sha256",
            'mapfile -t runtime_sources < "$source_allowlist"',
            "runtime_source_allowlist_sha256",
        ):
            self.assertIn(token, source)
        self.assertNotIn("find scripts -maxdepth 1", source)
        self.assertNotIn("find deploy/native_gst_probe", source)
        self.assertNotIn(
            "--file deploy/openvino_gva/publication/Dockerfile \\\n    .",
            source,
        )

    def test_build_context_allowlist_binds_manifests_validator_and_builder(self) -> None:
        values = BUILD_CONTEXT_ALLOWLIST.read_text(encoding="utf-8").splitlines()
        self.assertEqual(values, sorted({
            "deploy/gstreamer_custom/publication/runtime-dependency-allowlist.txt",
            "deploy/openvino_gva/publication/runtime-build-context-allowlist.txt",
            "deploy/openvino_gva/publication/runtime-source-allowlist.txt",
            "deploy/openvino_gva/publication/validate_runtime_source_closure_v3.py",
            "scripts/build_openvino_gva_publication_runtime_v3.sh",
            "scripts/materialize_runtime_build_context_v3.py",
        }))

    def test_allowlist_is_sorted_exact_and_does_not_reference_itself(self) -> None:
        values = ALLOWLIST.read_text(encoding="utf-8").splitlines()
        self.assertTrue(values)
        self.assertEqual(values, sorted(set(values)))
        self.assertNotIn(
            "deploy/openvino_gva/publication/runtime-source-allowlist.txt",
            values,
        )


if __name__ == "__main__":
    unittest.main()
