from __future__ import annotations

import ast
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


OPENVINO_IMAGE_ID = 'sha256:cf06b8605b0e118723863315edfab2f897f6921fdbb2a77c42cd534356643cc3'
OPENVINO_IMAGE_REFERENCE = 'vast/openvino-gva-publication-runtime-v3:attempt261-20260920'
OPENVINO_REPOSITORY_DIGEST = (
    "vast/openvino-gva-publication-runtime-v3@" + OPENVINO_IMAGE_ID
)
OPENVINO_PROJECTION_SHA256 = '1beb4b1ac9f84b1a0515bae5591028e5383ebb8c66822176548687657b4c8588'
OPENVINO_BASE_IMAGE_ID = 'sha256:72ce8749b7b341a3e9b9591c231289c3bc96418187df04a4915ae6bcdbf5e93d'
OPENVINO_RUNTIME_SOURCE_SHA256 = '737710c1cfbdf7a72ee3530b7b0de7e969891dbb4f3eeb81f509a35285e313c9'
NATIVE_SOURCE_SHA256 = '758ccd1f912c7dc86779891c95e26921cd88a3e9504fbbd306ac77594e820067'
DEPENDENCY_SET_SHA256 = '0f338b3aeca6756d31dccdbbc8caeb6239e8e07fec0541c1df3fea91dfc1963e'
OPENVINO_ALLOWLIST_SHA256 = 'c6ac2d9b54b2a9f9ba883ba814a35c39f319fba9c923497a4fe46432fce7cff9'
OPENVINO_EMBEDDED_SET_SHA256 = 'a15a1c92654fb39913bb3866b00ca9c74136ccb0fc452bafdef458d219128a0a'

GSTREAMER_IMAGE_ID = 'sha256:94f75c897d3abf330055d92198b22306b1f97cc7aeb8f192e87641c40939ec57'
GSTREAMER_IMAGE_REFERENCE = 'vast/gstreamer-custom-publication-runtime-v3:attempt261-20260920'
GSTREAMER_REPOSITORY_DIGEST = (
    "vast/gstreamer-custom-publication-runtime-v3@" + GSTREAMER_IMAGE_ID
)
GSTREAMER_PROJECTION_SHA256 = 'b1ca91d668f8dc21dadb9759616041f2a40783f6dbc4e9b79cbf1f17f0aeaebd'
GSTREAMER_RUNTIME_SOURCE_SHA256 = 'a182644465c570f88c607a6d4cdd9cbea4cdabf180a74a3420ea3b358ab5c3ea'
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

    def test_attempt261_patch_matches_exact_runtime_constants(self) -> None:
        attempt = ROOT / "artifacts/publication_image_build_v1_20260920_attempt261"
        savant_attempt = ROOT / "artifacts/publication_image_build_v1_20260920_attempt261"
        deepstream_attempt = ROOT / "artifacts/publication_image_build_v1_20260920_attempt261"
        attempts = {"deepstream": deepstream_attempt, "savant": savant_attempt}
        receipts = {
            system: json.loads(
                (attempts.get(system, attempt)
                 / f"{system}.runtime.freeze.json").read_bytes()
            )
            for system in (
                "deepstream", "savant", "openvino_gva", "gstreamer_custom"
            )
        }
        for system, receipt in receipts.items():
            self.assertIs(receipt["candidate_binding_eligible"], True, system)
            self.assertEqual(receipt["blockers"], [], system)
            self.assertEqual(
                receipt["physical_identity"]["final_reference"],
                {
                    "deepstream": "vast/deepstream-publication-runtime-v3:attempt261-20260920",
                    "savant": "vast/savant-publication-runtime-v3:attempt261-20260920",
                    "openvino_gva": OPENVINO_IMAGE_REFERENCE,
                    "gstreamer_custom": GSTREAMER_IMAGE_REFERENCE,
                }[system],
            )

        openvino = receipts["openvino_gva"]
        openvino_physical = openvino["physical_identity"]
        self.assertEqual(openvino_runtime.EXPECTED_IMAGE_ID, openvino_physical["image_id"])
        self.assertEqual(
            openvino_runtime.EXPECTED_REPOSITORY_DIGEST,
            openvino_physical["canonical_repository_digest"],
        )
        self.assertEqual(
            openvino_runtime.EXPECTED_IMAGE_INSPECT_PROJECTION_SHA256,
            openvino_physical["inspect_projection_sha256"],
        )
        self.assertEqual(openvino_runtime.EXPECTED_IMAGE_LABELS, openvino_physical["labels"])
        self.assertEqual(
            openvino_runtime.EXPECTED_EMBEDDED_ARTIFACTS,
            openvino_physical["embedded_files"],
        )
        self.assertEqual(
            openvino_runtime.EXPECTED_BASE_IMAGE_ID,
            openvino_physical["base"]["image_id"],
        )

        gstreamer = receipts["gstreamer_custom"]
        gstreamer_physical = gstreamer["physical_identity"]
        self.assertEqual(gstreamer_runtime.EXPECTED_IMAGE_ID, gstreamer_physical["image_id"])
        self.assertEqual(
            gstreamer_runtime.EXPECTED_REPOSITORY_DIGEST,
            gstreamer_physical["canonical_repository_digest"],
        )
        self.assertEqual(
            gstreamer_runtime.EXPECTED_IMAGE_INSPECT_PROJECTION_SHA256,
            gstreamer_physical["inspect_projection_sha256"],
        )
        self.assertEqual(gstreamer_runtime.EXPECTED_IMAGE_LABELS, gstreamer_physical["labels"])
        self.assertEqual(
            gstreamer_runtime.EXPECTED_EMBEDDED_ARTIFACTS,
            gstreamer_physical["embedded_files"],
        )
        self.assertEqual(
            gstreamer_runtime.EXPECTED_BASE_IMAGE_ID,
            gstreamer_physical["base"]["image_id"],
        )

        patch = json.loads(
            (savant_attempt / "qualification_image_identity_patch.json").read_bytes()
        )
        self.assertEqual(
            {
                system: row["physical_identity"]["final_reference"]
                for system, row in patch["systems"].items()
            },
            {
                system: receipt["physical_identity"]["final_reference"]
                for system, receipt in receipts.items()
            },
        )

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
                "/usr/local/bin/vast_native_gst_probe": "cdbed23e0513391453659be23b240ded91a1d0502ea1f545d129f4dd9e77f36d",
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
                "/usr/local/bin/vast_native_gst_probe": "cdbed23e0513391453659be23b240ded91a1d0502ea1f545d129f4dd9e77f36d",
            },
        )

    @unittest.skipUnless(
        os.name == "posix"
        and Path("/usr/bin/docker").exists()
        and Path("/run/docker.sock").exists(),
        "requires live WSL Docker",
    )
    def test_live_attempt261_a262_preflight_matches_runtime_materializer(self) -> None:
        inputs = fragment_authority._materialization_inputs(
            root=ROOT,
            identity_patch_path=(
                ROOT
                / "artifacts/publication_image_build_v1_20260920_attempt261/qualification_image_identity_patch.json"
            ),
            accepted_model_parity_manifest_path=(
                ROOT
                / "configs/checkpoint_analytics_model_parity.refreshed.v4.a262.accepted.yaml"
            ),
            accepted_model_parity_assessment_path=(
                ROOT
                / "configs/checkpoint_analytics_model_parity.refreshed.v4.a262.accepted.assessment.json"
            ),
            accepted_model_parity_receipt_path=(
                ROOT
                / "configs/checkpoint_analytics_model_parity.refreshed.v4.a262.accepted.acceptance_receipt.json"
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
                "deepstream": "sha256:3a069da57cf62f8ebdf63ae1fde21a071da2d671d8bea612ce2a2ba8d714953e",
                "savant": "sha256:a754954c04c42ed8eb72cc0ca6bae4c6b44c969ea624d248de086ce6e3dedd31",
                "openvino_gva": "sha256:cf06b8605b0e118723863315edfab2f897f6921fdbb2a77c42cd534356643cc3",
                "gstreamer_custom": "sha256:94f75c897d3abf330055d92198b22306b1f97cc7aeb8f192e87641c40939ec57",
            },
        )
        self.assertEqual(
            observed["openvino_gva"]["contract"],
            {
                "image_id": "sha256:cf06b8605b0e118723863315edfab2f897f6921fdbb2a77c42cd534356643cc3",
                "repository_digest": "vast/openvino-gva-publication-runtime-v3@sha256:cf06b8605b0e118723863315edfab2f897f6921fdbb2a77c42cd534356643cc3",
                "inspect_projection_sha256": "1beb4b1ac9f84b1a0515bae5591028e5383ebb8c66822176548687657b4c8588",
            },
        )
        self.assertEqual(
            observed["gstreamer_custom"]["contract"],
            {
                "image_id": "sha256:94f75c897d3abf330055d92198b22306b1f97cc7aeb8f192e87641c40939ec57",
                "repository_digest": "vast/gstreamer-custom-publication-runtime-v3@sha256:94f75c897d3abf330055d92198b22306b1f97cc7aeb8f192e87641c40939ec57",
                "inspect_projection_sha256": "b1ca91d668f8dc21dadb9759616041f2a40783f6dbc4e9b79cbf1f17f0aeaebd",
                "base_image_id": OPENVINO_BASE_IMAGE_ID,
            },
        )
        self.assertEqual(
            inputs["patch"]["workers"]["cpu"]["image_id"],
            "sha256:f98d48637805419d0d97a9c2912104e148b4ccecf1a81ea49357e63ad8b20575",
        )
        self.assertEqual(
            inputs["patch"]["workers"]["gpu"]["image_id"],
            "sha256:9b8ab2cc8c0b159a46dbb9dec4bc300bab36fa86d65b196d28fddc3541b027e9",
        )


if __name__ == "__main__":
    unittest.main()
