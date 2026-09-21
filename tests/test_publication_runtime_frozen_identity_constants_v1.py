from __future__ import annotations

import ast
import hashlib
import json
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import checkpoint_deepstream_publication_runtime_v3 as deepstream_runtime  # noqa: E402
import checkpoint_deepstream_qualification_fragment_v1 as deepstream_fragment  # noqa: E402
import checkpoint_gstreamer_custom_qualification_fragment_v3 as gstreamer_fragment  # noqa: E402
import checkpoint_gstreamer_publication_runtime_v3 as gstreamer_runtime  # noqa: E402
import checkpoint_openvino_gva_publication_runtime_v3 as openvino_runtime  # noqa: E402
import checkpoint_openvino_gva_qualification_fragment_v3 as openvino_fragment  # noqa: E402
import checkpoint_savant_publication_runtime_v3 as savant_runtime  # noqa: E402
import checkpoint_savant_qualification_fragment_v3 as savant_fragment  # noqa: E402
import checkpoint_savant_runtime_image_materialization_v3 as savant_image  # noqa: E402
import publication_policy_qualification_fragments_from_authority_v2 as fragment_authority  # noqa: E402
import publication_policy_qualification_runtime_inputs_v2 as runtime_inputs  # noqa: E402


OPENVINO_IMAGE_ID = 'sha256:261ef8a6a1e4314e567d7d134ae80e45b97f4d1ee2a6eeaed8dbdd294d4dd56a'
OPENVINO_IMAGE_REFERENCE = 'vast/openvino-gva-publication-runtime-v3:materialized'
OPENVINO_REPOSITORY_DIGEST = (
    "vast/openvino-gva-publication-runtime-v3@" + OPENVINO_IMAGE_ID
)
OPENVINO_PROJECTION_SHA256 = '1ab22e139b36a22efeeb696ae386e43badf05b7bb428edd456f929d61adaaaa1'
OPENVINO_BASE_IMAGE_ID = 'sha256:a022b7f35e91ab24199de2ff72475c81f340a1f1ffb24efbd558e8b44c48b618'
OPENVINO_RUNTIME_SOURCE_SHA256 = 'e2ae7f8e1ffaf0711db2e083584f5bde97873580591f96d6b8014982a07ae91d'
NATIVE_SOURCE_SHA256 = 'ba9159f239751a4f226e836606e68dd40d5394782e9e678ef455d832a17dbb90'
DEPENDENCY_SET_SHA256 = '0f338b3aeca6756d31dccdbbc8caeb6239e8e07fec0541c1df3fea91dfc1963e'
OPENVINO_ALLOWLIST_SHA256 = 'c6ac2d9b54b2a9f9ba883ba814a35c39f319fba9c923497a4fe46432fce7cff9'
OPENVINO_EMBEDDED_SET_SHA256 = 'abc2c68d3ad0d50d5f1d72aa49e5bd77d7cac001d185325460de1e23b4d91c0f'

GSTREAMER_IMAGE_ID = 'sha256:4e1cbec0c51eb2d47964242888b3ee87f1747cfa06d17cf04318a1a061d7eab4'
GSTREAMER_IMAGE_REFERENCE = 'vast/gstreamer-custom-publication-runtime-v3:materialized'
GSTREAMER_REPOSITORY_DIGEST = (
    "vast/gstreamer-custom-publication-runtime-v3@" + GSTREAMER_IMAGE_ID
)
GSTREAMER_PROJECTION_SHA256 = '86eb1cfd4b7cae749b95a2e0f310867f664f44b7cfb655ce0d368f9650541269'
GSTREAMER_RUNTIME_SOURCE_SHA256 = '2a7edf7b95158440d1dd2f730330ee2f77ea1f046c8825e22656bcb9c6335dd7'
GSTREAMER_ALLOWLIST_SHA256 = 'dea819344804486529aeb32c0076690b42acfd8f5f861c2651d02b01c54608dc'


class PublicationRuntimeFrozenIdentityConstantsV1Tests(unittest.TestCase):
    def test_deepstream_child_failure_diagnostic_is_bounded_and_single_line(self) -> None:
        completed = deepstream_runtime._Completed(
            7,
            b"prefix" + b"x" * 4096,
            b"first\nsecond\r" + b"y" * 4096,
        )
        diagnostic = deepstream_runtime._completed_failure_diagnostic(completed)
        self.assertIn("exit_code=7", diagnostic)
        self.assertNotIn("\n", diagnostic)
        self.assertNotIn("\r", diagnostic)
        self.assertLessEqual(len(diagnostic), 4200)

    def test_fix_benchmark_patch_matches_exact_runtime_constants(self) -> None:
        patch_path = ROOT / "artifacts/fix_benchmark_preparations_20260921/qualification_image_identity_patch.v2.json"
        patch = json.loads(patch_path.read_bytes())
        receipts = {}
        for system, descriptor in patch["receipts"]["runtime_images"].items():
            path = ROOT / descriptor["path"]
            payload = path.read_bytes()
            self.assertEqual(hashlib.sha256(payload).hexdigest(), descriptor["sha256"])
            self.assertEqual(len(payload), descriptor["size_bytes"])
            receipts[system] = json.loads(payload)
            self.assertEqual(receipts[system]["physical_identity"], patch["systems"][system]["physical_identity"])
        self.assertEqual(openvino_runtime.EXPECTED_IMAGE_ID, receipts["openvino_gva"]["physical_identity"]["image_id"])
        self.assertEqual(gstreamer_runtime.EXPECTED_IMAGE_ID, receipts["gstreamer_custom"]["physical_identity"]["image_id"])
        self.assertIn("runtime_packaging_repair", patch["receipts"]["runtime_images"]["openvino_gva"]["path"])
        self.assertIn("runtime_packaging_repair", patch["receipts"]["runtime_images"]["gstreamer_custom"]["path"])

    def test_runtime_input_materializer_inspects_the_candidate_reference_not_only_id(self) -> None:
        path = SCRIPTS / "publication_policy_qualification_runtime_inputs_v2.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        function = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "_inspect_runtime_images"
        )
        calls = [
            node
            for node in ast.walk(function)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "inspect_image"
        ]
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(calls[0].args), 3)
        self.assertIsInstance(calls[0].args[2], ast.Name)
        self.assertEqual(calls[0].args[2].id, "final_reference")
        source = ast.unparse(function)
        self.assertIn("openvino_runtime.EXPECTED_IMAGE_REFERENCE", source)
        self.assertIn("gstreamer_runtime.EXPECTED_IMAGE_REFERENCE", source)

    def test_deepstream_dynamic_image_contract_keeps_exact_frozen_base_and_entrypoint(self) -> None:
        self.assertEqual(
            deepstream_fragment.EXPECTED_BASE_IMAGE,
            "nvcr.io/nvidia/deepstream@sha256:"
            "c11befa808af8270e8ea0d0d7cc7cabbda08a2f496ee30b95f7acba5dce81759",
        )
        self.assertEqual(
            deepstream_fragment.EXPECTED_ENTRYPOINT,
            "/usr/local/bin/vast_deepstream_publication_runtime_v3",
        )
        self.assertEqual(
            deepstream_runtime.EXPECTED_COORDINATOR_PATH,
            deepstream_fragment.EXPECTED_ENTRYPOINT,
        )
        self.assertEqual(
            deepstream_runtime.REQUIRED_IMAGE_LABELS,
            {
                "org.vast.component": "deepstream-checkpoint-native-sdk-runtime",
                "org.vast.publication-runtime-abi": "3",
            },
        )

    def test_savant_native_builder_is_the_frozen_attempt14_builder(self) -> None:
        builder_image = (
            "sha256:314d4a4d71130e9b86caacb802e92fe97a89ee92b0240f9947dccebca3adc3dc"
        )
        builder_source = (
            "b6772ea56a31886b2599ed602e325d39b876d33d740bd3b983f1b96dbcf82c0f"
        )
        base_image = (
            "sha256:3c0ef6f4bb57e385644da526789626f0c943dcb90ff32b72a7883e05798ce9e6"
        )
        self.assertEqual(savant_fragment.SAVANT_BASE_IMAGE_ID, base_image)
        self.assertEqual(savant_image.BASE_IMAGE_ID, base_image)
        self.assertEqual(savant_fragment.NATIVE_BUILDER_IMAGE_ID, builder_image)
        self.assertEqual(savant_image.NATIVE_BUILDER_IMAGE_ID, builder_image)
        self.assertEqual(savant_fragment.NATIVE_BUILDER_SOURCE_SHA256, builder_source)
        self.assertEqual(savant_image.NATIVE_BUILDER_SOURCE_SHA256, builder_source)
        self.assertEqual(
            savant_image.ENTRYPOINT,
            ["/usr/local/bin/vast_savant_checkpoint_runtime"],
        )
        self.assertEqual(
            savant_runtime.EXPECTED_COORDINATOR_PATH,
            savant_image.ENTRYPOINT[0],
        )
        build = (SCRIPTS / "build_savant_publication_runtime_v3.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("vast/savant-native-probe@" + builder_image, build)
        self.assertIn(
            "VAST_SAVANT_NATIVE_PROBE_IMAGE_ID:-" + builder_image,
            build,
        )
        self.assertIn(
            "VAST_SAVANT_NATIVE_PROBE_SOURCE_SHA256:-" + builder_source,
            build,
        )
        self.assertNotIn("ef70f6fae0558d1d90ae32fc931256bc", build)
        self.assertNotIn("e38aa56050381aef7ce9ff6fb934ae3d", build)

    def test_openvino_current_runtime_is_exactly_refrozen(self) -> None:
        self.assertEqual(
            openvino_runtime.EXPECTED_IMAGE_REFERENCE,
            OPENVINO_IMAGE_REFERENCE,
        )
        self.assertEqual(openvino_runtime.EXPECTED_IMAGE_ID, OPENVINO_IMAGE_ID)
        self.assertEqual(
            openvino_runtime.EXPECTED_REPOSITORY_DIGEST,
            OPENVINO_REPOSITORY_DIGEST,
        )
        self.assertEqual(
            openvino_runtime.EXPECTED_IMAGE_INSPECT_PROJECTION_SHA256,
            OPENVINO_PROJECTION_SHA256,
        )
        self.assertEqual(openvino_runtime.EXPECTED_BASE_IMAGE_ID, OPENVINO_BASE_IMAGE_ID)
        self.assertEqual(
            openvino_runtime.EXPECTED_IMAGE_LABELS,
            {
                "org.vast.base-image-id": OPENVINO_BASE_IMAGE_ID,
                "org.vast.component": "openvino-gva-checkpoint-publication-runtime",
                "org.vast.native_probe.kind": "openvino-dlstreamer-publication-v3",
                "org.vast.native_probe.source_sha": NATIVE_SOURCE_SHA256,
                "org.vast.publication-ready": "false",
                "org.vast.publication-runtime-abi": "3",
                "org.vast.runtime-dependency-set-sha256": DEPENDENCY_SET_SHA256,
                "org.vast.runtime-source-allowlist-sha256": OPENVINO_ALLOWLIST_SHA256,
                "org.vast.runtime-source-sha256": OPENVINO_RUNTIME_SOURCE_SHA256,
            },
        )
        self.assertEqual(
            openvino_runtime.EXPECTED_IMAGE_ENTRYPOINT,
            "/usr/local/bin/vast_openvino_gva_publication_runtime_v3",
        )
        self.assertEqual(openvino_runtime.EXPECTED_IMAGE_USER, "dlstreamer")
        self.assertEqual(
            openvino_runtime.image_projection_sha256(
                {
                    "Architecture": "amd64",
                    "Config": {
                        "Entrypoint": [openvino_runtime.EXPECTED_IMAGE_ENTRYPOINT],
                        "Labels": dict(openvino_runtime.EXPECTED_IMAGE_LABELS),
                        "User": openvino_runtime.EXPECTED_IMAGE_USER,
                    },
                    "Id": OPENVINO_IMAGE_ID,
                    "Os": "linux",
                    "RepoDigests": [OPENVINO_REPOSITORY_DIGEST],
                }
            ),
            OPENVINO_PROJECTION_SHA256,
        )
        self.assertEqual(
            openvino_runtime.EXPECTED_EMBEDDED_ARTIFACTS,
            {
                "/opt/vast/checkpoint/checkpoint_gstreamer_runtime.py": "40d3c7ec7693344de6595b50fa1bad5deadbd5a36a15977feadfd41faeae6efa",
                "/opt/vast/checkpoint/checkpoint_openvino_gva_container_coordinator_v3.py": "33a94d90919880c8f04b9e49a9841cda21ceceee1bb36ef1489e9103d2b4b583",
                "/opt/vast/lib/gstreamer-1.0/libgstadaptivescheduler.so": "d36642c99d55fac7d834c75b500c7ffd086f022e671cb2b38aecaf38b8d0ad9f",
                "/opt/vast/lib/gstreamer-1.0/libgstvastanalyticsqueue.so": "9909f2b19adc3f7e82dcf8923a3e719f8546cd4e5126663deafdce04121d2258",
                "/opt/vast/lib/gstreamer-1.0/libgstvastanalyticsterminal.so": "04962e14523cc570ce1b24735e76334820ed730b5aee72beac0685a4704f9e45",
                "/opt/vast/lib/gstreamer-1.0/libgstvastcheckpointprefixqueue.so": "797a9311f06cc60ce3768dfc2b3a191525a8577dd8ce2a4eca057aa4fcefdabf",
                "/opt/vast/runtime-source-allowlist.txt": OPENVINO_ALLOWLIST_SHA256,
                "/opt/vast/share/gstreamer-registry.bin": "18b3fb289de3a7c101b12854beaabb38a8edb72c1ecaf6fc5deea39d307508bc",
                "/usr/local/bin/vast_checkpoint_source": "7501479ccb90dc1e322386126c372a7650f40e5c7b76bfb29f4495470bd185df",
                "/usr/local/bin/vast_native_gst_probe": "c4120308a97b0b5f6f8d1d659889651dfa8deb45764f47ceac0722a49f1bf42d",
                "/usr/local/bin/vast_openvino_gva_publication_runtime_v3": "3871aeb3037d041deb1722bfb6523125416a8939d204c21f2b9e8c906e9815ae",
            },
        )

    def test_gstreamer_current_runtime_is_exactly_refrozen(self) -> None:
        self.assertEqual(
            gstreamer_runtime.EXPECTED_IMAGE_REFERENCE,
            GSTREAMER_IMAGE_REFERENCE,
        )
        self.assertEqual(gstreamer_runtime.EXPECTED_IMAGE_ID, GSTREAMER_IMAGE_ID)
        self.assertEqual(
            gstreamer_runtime.EXPECTED_REPOSITORY_DIGEST,
            GSTREAMER_REPOSITORY_DIGEST,
        )
        self.assertEqual(
            gstreamer_runtime.EXPECTED_IMAGE_INSPECT_PROJECTION_SHA256,
            GSTREAMER_PROJECTION_SHA256,
        )
        self.assertEqual(
            gstreamer_runtime.EXPECTED_BASE_IMAGE_ID,
            OPENVINO_BASE_IMAGE_ID,
        )
        self.assertEqual(
            gstreamer_runtime.EXPECTED_IMAGE_LABELS,
            {
                "org.opencontainers.image.version": "24.04",
                "org.vast.base-image-id": OPENVINO_BASE_IMAGE_ID,
                "org.vast.claim-status": "deterministic-image-awaiting-exact-kpp-v3-gpu-pilots",
                "org.vast.component": "gstreamer-custom-checkpoint-publication-runtime",
                "org.vast.native_probe.kind": "openvino-dlstreamer",
                "org.vast.native_probe.source_sha": NATIVE_SOURCE_SHA256,
                "org.vast.publication-runtime-abi": "3",
                "org.vast.runtime-dependency-set-sha256": DEPENDENCY_SET_SHA256,
                "org.vast.runtime-source-sha256": GSTREAMER_RUNTIME_SOURCE_SHA256,
            },
        )
        self.assertEqual(
            gstreamer_runtime.EXPECTED_IMAGE_ENTRYPOINT,
            "/usr/local/bin/vast_gstreamer_custom_publication_runtime_v3",
        )
        self.assertEqual(gstreamer_runtime.EXPECTED_IMAGE_USER, "dlstreamer")
        self.assertEqual(
            gstreamer_runtime.image_projection_sha256(
                {
                    "Architecture": "amd64",
                    "Config": {
                        "Entrypoint": [gstreamer_runtime.EXPECTED_IMAGE_ENTRYPOINT],
                        "Labels": dict(gstreamer_runtime.EXPECTED_IMAGE_LABELS),
                        "User": gstreamer_runtime.EXPECTED_IMAGE_USER,
                    },
                    "Created": "1970-01-01T00:00:00Z",
                    "Id": GSTREAMER_IMAGE_ID,
                    "Os": "linux",
                    "RepoDigests": [GSTREAMER_REPOSITORY_DIGEST],
                }
            ),
            GSTREAMER_PROJECTION_SHA256,
        )
        self.assertEqual(
            gstreamer_runtime.EXPECTED_EMBEDDED_ARTIFACTS,
            {
                "/opt/vast/checkpoint/checkpoint_gstreamer_custom_container_coordinator_v3.py": "7f70138de1e87ab43dfab1e37674979c551dd24ee02fba205cd9905790b060c5",
                "/opt/vast/checkpoint/checkpoint_gstreamer_runtime.py": "40d3c7ec7693344de6595b50fa1bad5deadbd5a36a15977feadfd41faeae6efa",
                "/opt/vast/lib/gstreamer-1.0/libgstadaptivescheduler.so": "d36642c99d55fac7d834c75b500c7ffd086f022e671cb2b38aecaf38b8d0ad9f",
                "/opt/vast/lib/gstreamer-1.0/libgstvastanalyticsqueue.so": "9909f2b19adc3f7e82dcf8923a3e719f8546cd4e5126663deafdce04121d2258",
                "/opt/vast/lib/gstreamer-1.0/libgstvastanalyticsterminal.so": "04962e14523cc570ce1b24735e76334820ed730b5aee72beac0685a4704f9e45",
                "/opt/vast/lib/gstreamer-1.0/libgstvastcheckpointprefixqueue.so": "797a9311f06cc60ce3768dfc2b3a191525a8577dd8ce2a4eca057aa4fcefdabf",
                "/opt/vast/runtime-source-allowlist.txt": GSTREAMER_ALLOWLIST_SHA256,
                "/opt/vast/share/gstreamer-registry.bin": "18b3fb289de3a7c101b12854beaabb38a8edb72c1ecaf6fc5deea39d307508bc",
                "/usr/local/bin/vast_checkpoint_source": "7501479ccb90dc1e322386126c372a7650f40e5c7b76bfb29f4495470bd185df",
                "/usr/local/bin/vast_gstreamer_custom_publication_runtime_v3": "2f241d0fbf8e250d09f3dc8c6c97999910991c8649c44e56ee69d4f1cb38b8e7",
                "/usr/local/bin/vast_native_gst_probe": "c4120308a97b0b5f6f8d1d659889651dfa8deb45764f47ceac0722a49f1bf42d",
            },
        )

    @unittest.skipUnless(
        os.name == "posix"
        and Path("/usr/bin/docker").exists()
        and Path("/run/docker.sock").exists()
        and (
            ROOT
            / "models/openvino/public/intel/vehicle-license-plate-detection-barrier-0106/FP16/vehicle-license-plate-detection-barrier-0106.xml"
        ).is_file(),
        "requires live WSL Docker and OMZ proxy models",
    )
    def test_live_fix_benchmark_preflight_matches_runtime_materializer(self) -> None:
        inputs = fragment_authority._materialization_inputs(
            root=ROOT,
            identity_patch_path=(
                ROOT
                / "artifacts/fix_benchmark_preparations_20260921/qualification_image_identity_patch.v2.json"
            ),
            accepted_model_parity_manifest_path=(
                ROOT
                / "configs/checkpoint_analytics_model_parity.refreshed.v4.fix-benchmark-20260921.accepted.yaml"
            ),
            accepted_model_parity_assessment_path=(
                ROOT
                / "configs/checkpoint_analytics_model_parity.refreshed.v4.fix-benchmark-20260921.accepted.assessment.json"
            ),
            accepted_model_parity_receipt_path=(
                ROOT
                / "configs/checkpoint_analytics_model_parity.refreshed.v4.fix-benchmark-20260921.accepted.acceptance_receipt.json"
            ),
            docker="/usr/bin/docker",
            dependencies=fragment_authority.DEFAULT_DEPENDENCIES,
            verify_live=True,
        )
        resource_bindings = {}
        for system in runtime_inputs.SYSTEMS:
            projection = fragment_authority._system_image_projection(
                inputs["patch"], system
            )
            for resource in runtime_inputs.RESOURCES:
                resource_bindings[(system, resource)] = projection
        inventory = SimpleNamespace(resource_bindings=resource_bindings)
        observed = runtime_inputs._inspect_runtime_images(
            inventory,
            engine=Path("/usr/bin/docker"),
            engine_socket=Path("/run/docker.sock"),
            dependencies=runtime_inputs.DEFAULT_DEPENDENCIES,
        )
        self.assertEqual(
            {system: row["physical_identity"]["image_id"]
             for system, row in inputs["patch"]["systems"].items()},
            {
                "deepstream": "sha256:1ebc85158a2e12c0184befb3123ce5fbf37df7e717c580a272d28bc33757cd45",
                "savant": "sha256:190fbb4d0275d0ceae96a1e404e55e32fbfc3b65d8f6cf83941bed40a1fe333a",
                "openvino_gva": "sha256:261ef8a6a1e4314e567d7d134ae80e45b97f4d1ee2a6eeaed8dbdd294d4dd56a",
                "gstreamer_custom": "sha256:4e1cbec0c51eb2d47964242888b3ee87f1747cfa06d17cf04318a1a061d7eab4",
            },
        )
        self.assertEqual(
            observed["openvino_gva"]["contract"],
            {
                "image_id": "sha256:261ef8a6a1e4314e567d7d134ae80e45b97f4d1ee2a6eeaed8dbdd294d4dd56a",
                "repository_digest": "vast/openvino-gva-publication-runtime-v3@sha256:261ef8a6a1e4314e567d7d134ae80e45b97f4d1ee2a6eeaed8dbdd294d4dd56a",
                "inspect_projection_sha256": "1ab22e139b36a22efeeb696ae386e43badf05b7bb428edd456f929d61adaaaa1",
            },
        )
        self.assertEqual(
            observed["gstreamer_custom"]["contract"],
            {
                "image_id": "sha256:4e1cbec0c51eb2d47964242888b3ee87f1747cfa06d17cf04318a1a061d7eab4",
                "repository_digest": "vast/gstreamer-custom-publication-runtime-v3@sha256:4e1cbec0c51eb2d47964242888b3ee87f1747cfa06d17cf04318a1a061d7eab4",
                "inspect_projection_sha256": "86eb1cfd4b7cae749b95a2e0f310867f664f44b7cfb655ce0d368f9650541269",
                "base_image_id": OPENVINO_BASE_IMAGE_ID,
            },
        )
        self.assertEqual(
            inputs["patch"]["workers"]["cpu"]["image_id"],
            "sha256:a3efa6ecf6b6dbc891c17deb7e9491869286ab9bffa01e7a4cb8da009514e9bf",
        )
        self.assertEqual(
            inputs["patch"]["workers"]["gpu"]["image_id"],
            "sha256:933cb0b03b084b1f33dfde7b2a4e3acacc6858b80a57f5e6b373be5f4fa86be0",
        )


if __name__ == "__main__":
    unittest.main()
