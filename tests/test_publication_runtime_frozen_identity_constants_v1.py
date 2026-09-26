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


OPENVINO_IMAGE_ID = 'sha256:f477601c9c6b9d9265c28099e3360559cff55ad1d0e134257adf9afb2e2ee0ae'
OPENVINO_IMAGE_REFERENCE = 'vast/openvino-gva-publication-runtime-v3:materialized'
OPENVINO_REPOSITORY_DIGEST = (
    "vast/openvino-gva-publication-runtime-v3@" + OPENVINO_IMAGE_ID
)
OPENVINO_PROJECTION_SHA256 = 'e1287cecd1eb062be98e8674f2cdc71b009723726fa7c2ea4fd27b06ed49c493'
OPENVINO_BASE_IMAGE_ID = 'sha256:12d6941b7e8a3c0dbb7737b1f9a2ad1b5956e4d14ab2bf7f53ada6c8c58858c5'
OPENVINO_RUNTIME_SOURCE_SHA256 = 'dbb9883c985125f6b3817aa322ec1e23bf71b24288bb26be83915023d4cefd8a'
NATIVE_SOURCE_SHA256 = '906a1ea8f3a42fa6d6444084811a97998a7cfad26f3c3e22b2a3f6ccb60d8543'
DEPENDENCY_SET_SHA256 = '0f338b3aeca6756d31dccdbbc8caeb6239e8e07fec0541c1df3fea91dfc1963e'
OPENVINO_ALLOWLIST_SHA256 = 'c6ac2d9b54b2a9f9ba883ba814a35c39f319fba9c923497a4fe46432fce7cff9'
OPENVINO_EMBEDDED_SET_SHA256 = '662e49d9251efa751f28bc0ac6d15a13599083ee44fe4dabb9d0ffaacc66b31c'

GSTREAMER_IMAGE_ID = 'sha256:dd9b6106d03a091c4192bd66e1759aa01eb2466d62cb03e82ff21c7fc3ecd096'
GSTREAMER_IMAGE_REFERENCE = 'vast/gstreamer-custom-publication-runtime-v3:materialized'
GSTREAMER_REPOSITORY_DIGEST = (
    "vast/gstreamer-custom-publication-runtime-v3@" + GSTREAMER_IMAGE_ID
)
GSTREAMER_PROJECTION_SHA256 = 'd312ee6a3e6f959edfc02531b57adeba0436b0656e022c010f8de74162708ae1'
GSTREAMER_RUNTIME_SOURCE_SHA256 = 'f0d95a69db76326ccb26147707b28e932e2a6e226365ea22461e3114f41b2275'
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
        patch_path = ROOT / "artifacts/fix_benchmark_preparations_20260926d/qualification_image_identity_patch.json"
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
        self.assertIn("runtime_images", patch["receipts"]["runtime_images"]["openvino_gva"]["path"])
        self.assertIn("runtime_images", patch["receipts"]["runtime_images"]["gstreamer_custom"]["path"])

    def test_current_qualification_fragments_match_physical_receipts(self) -> None:
        base = ROOT / "artifacts/fix_benchmark_preparations_20260926d"
        patch = json.loads((base / "qualification_image_identity_patch.json").read_bytes())
        parity = json.loads(
            (
                ROOT
                / "configs/checkpoint_analytics_model_parity.refreshed.v4.fix-benchmark-20260926d.accepted.acceptance_receipt.json"
            ).read_bytes()
        )
        accepted = parity["accepted_manifest"]
        self.assertEqual(
            gstreamer_fragment.ACCEPTED_PARITY,
            (accepted["path"], accepted["size_bytes"], accepted["sha256"]),
        )
        self.assertEqual(
            gstreamer_fragment.ACCEPTED_PARITY_CONTENT_SHA256,
            parity["accepted_manifest_content_identity_sha256"],
        )
        authority = parity["refresh_authority"]
        binding_set = authority["binding_set"]
        index = binding_set["index"]
        self.assertEqual(
            gstreamer_fragment.ANALYTICS_INDEX,
            (index["path"], index["size_bytes"], index["sha256"]),
        )
        self.assertEqual(
            gstreamer_fragment.ANALYTICS_INDEX_IDENTITY,
            binding_set["identity_sha256"],
        )
        self.assertEqual(
            gstreamer_fragment.ANALYTICS_BINDINGS_IDENTITY,
            binding_set["bindings_identity_sha256"],
        )
        self.assertEqual(
            gstreamer_fragment.EXECUTION_CONFIG_IDENTITY,
            authority["execution_config"]["content_identity_sha256"],
        )
        for resource in ("cpu", "gpu"):
            worker = authority["workers"][resource]
            probe = authority["runtime_probes"][resource]
            expected_image = worker["image_id"]
            expected_implementation = worker["worker_implementation_sha256"]
            self.assertEqual(
                gstreamer_fragment.RUNTIME_PROBES[resource],
                (probe["path"], probe["size_bytes"], probe["sha256"]),
            )
            for fragment in (gstreamer_fragment, openvino_fragment):
                self.assertEqual(
                    getattr(fragment, resource.upper() + "_WORKER_IMAGE_ID"),
                    expected_image,
                )
                self.assertEqual(
                    fragment.WORKER_IMPLEMENTATIONS[resource],
                    expected_implementation,
                )
        for system, fragment, prefix in (
            ("gstreamer_custom", gstreamer_fragment, "GSTREAMER"),
            ("openvino_gva", openvino_fragment, "OPENVINO_GVA"),
        ):
            physical = patch["systems"][system]["fragment_identity"]
            self.assertEqual(getattr(fragment, prefix + "_IMAGE_ID"), physical["image_id"])
            self.assertEqual(
                getattr(fragment, prefix + "_REPOSITORY_DIGEST"),
                physical["repository_digest"],
            )
            self.assertEqual(
                getattr(fragment, prefix + "_IMAGE_PROJECTION_SHA256"),
                physical["inspect_projection_sha256"],
            )
            self.assertEqual(
                getattr(fragment, prefix + "_BASE_IMAGE_ID"),
                physical["base_image_id"],
            )
            self.assertEqual(
                getattr(fragment, prefix + "_RUNTIME_SOURCE_SHA256"),
                physical["runtime_source_sha256"],
            )
        self.assertEqual(
            gstreamer_fragment.GSTREAMER_NATIVE_SOURCE_SHA256,
            patch["systems"]["gstreamer_custom"]["fragment_identity"]["native_probe_source_sha256"],
        )
        self.assertEqual(
            gstreamer_fragment.NATIVE_PROBE_SHA256,
            patch["systems"]["gstreamer_custom"]["fragment_identity"]["embedded_native_probe_sha256"],
        )
        self.assertEqual(
            openvino_fragment.OPENVINO_GVA_NATIVE_SOURCE_SHA256,
            patch["systems"]["openvino_gva"]["fragment_identity"]["native_source_sha256"],
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
                "/opt/vast/checkpoint/checkpoint_gstreamer_runtime.py": "160906b4b6a490f2e4d8e397216f4e8b7defc38234673f70902cbe77e98c38c9",
                "/opt/vast/checkpoint/checkpoint_openvino_gva_container_coordinator_v3.py": "33a94d90919880c8f04b9e49a9841cda21ceceee1bb36ef1489e9103d2b4b583",
                "/opt/vast/lib/gstreamer-1.0/libgstadaptivescheduler.so": "d36642c99d55fac7d834c75b500c7ffd086f022e671cb2b38aecaf38b8d0ad9f",
                "/opt/vast/lib/gstreamer-1.0/libgstvastanalyticsqueue.so": "9909f2b19adc3f7e82dcf8923a3e719f8546cd4e5126663deafdce04121d2258",
                "/opt/vast/lib/gstreamer-1.0/libgstvastanalyticsterminal.so": "04962e14523cc570ce1b24735e76334820ed730b5aee72beac0685a4704f9e45",
                "/opt/vast/lib/gstreamer-1.0/libgstvastcheckpointprefixqueue.so": "797a9311f06cc60ce3768dfc2b3a191525a8577dd8ce2a4eca057aa4fcefdabf",
                "/opt/vast/runtime-source-allowlist.txt": OPENVINO_ALLOWLIST_SHA256,
                "/opt/vast/share/gstreamer-registry.bin": "18b3fb289de3a7c101b12854beaabb38a8edb72c1ecaf6fc5deea39d307508bc",
                "/usr/local/bin/vast_checkpoint_source": "7501479ccb90dc1e322386126c372a7650f40e5c7b76bfb29f4495470bd185df",
                "/usr/local/bin/vast_native_gst_probe": "dc5597b44ea2b69acbab766c2569d52decdbf71ad8dc748a1a63f2d8b1b2b3a1",
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
                "/opt/vast/checkpoint/checkpoint_gstreamer_runtime.py": "160906b4b6a490f2e4d8e397216f4e8b7defc38234673f70902cbe77e98c38c9",
                "/opt/vast/lib/gstreamer-1.0/libgstadaptivescheduler.so": "d36642c99d55fac7d834c75b500c7ffd086f022e671cb2b38aecaf38b8d0ad9f",
                "/opt/vast/lib/gstreamer-1.0/libgstvastanalyticsqueue.so": "9909f2b19adc3f7e82dcf8923a3e719f8546cd4e5126663deafdce04121d2258",
                "/opt/vast/lib/gstreamer-1.0/libgstvastanalyticsterminal.so": "04962e14523cc570ce1b24735e76334820ed730b5aee72beac0685a4704f9e45",
                "/opt/vast/lib/gstreamer-1.0/libgstvastcheckpointprefixqueue.so": "797a9311f06cc60ce3768dfc2b3a191525a8577dd8ce2a4eca057aa4fcefdabf",
                "/opt/vast/runtime-source-allowlist.txt": GSTREAMER_ALLOWLIST_SHA256,
                "/opt/vast/share/gstreamer-registry.bin": "18b3fb289de3a7c101b12854beaabb38a8edb72c1ecaf6fc5deea39d307508bc",
                "/usr/local/bin/vast_checkpoint_source": "7501479ccb90dc1e322386126c372a7650f40e5c7b76bfb29f4495470bd185df",
                "/usr/local/bin/vast_gstreamer_custom_publication_runtime_v3": "2f241d0fbf8e250d09f3dc8c6c97999910991c8649c44e56ee69d4f1cb38b8e7",
                "/usr/local/bin/vast_native_gst_probe": "dc5597b44ea2b69acbab766c2569d52decdbf71ad8dc748a1a63f2d8b1b2b3a1",
            },
        )

    @unittest.skipUnless(
        os.environ.get("VAST_LIVE_PREFLIGHT") == "1"
        and os.name == "posix"
        and Path("/usr/bin/docker").exists()
        and Path("/run/docker.sock").exists()
        and (
            ROOT
            / "models/openvino/public/intel/vehicle-license-plate-detection-barrier-0106/FP16/vehicle-license-plate-detection-barrier-0106.xml"
        ).is_file(),
        "requires VAST_LIVE_PREFLIGHT=1, live WSL Docker and OMZ proxy models",
    )
    def test_live_fix_benchmark_preflight_matches_runtime_materializer(self) -> None:
        inputs = fragment_authority._materialization_inputs(
            root=ROOT,
            identity_patch_path=(
                ROOT
                / "artifacts/fix_benchmark_preparations_20260926d/qualification_image_identity_patch.json"
            ),
            accepted_model_parity_manifest_path=(
                ROOT
                / "configs/checkpoint_analytics_model_parity.refreshed.v4.fix-benchmark-20260926d.accepted.yaml"
            ),
            accepted_model_parity_assessment_path=(
                ROOT
                / "configs/checkpoint_analytics_model_parity.refreshed.v4.fix-benchmark-20260926d.accepted.assessment.json"
            ),
            accepted_model_parity_receipt_path=(
                ROOT
                / "configs/checkpoint_analytics_model_parity.refreshed.v4.fix-benchmark-20260926d.accepted.acceptance_receipt.json"
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
                "deepstream": "sha256:74c1313318d0f78c12c409db2256a6f2791d44668b0388741f77b8cff0e02c0a",
                "savant": "sha256:f1d9e8303d7aa973a56338ff88c868e50707464442462ce3aaaeb68d90b2b7ac",
                "openvino_gva": "sha256:f477601c9c6b9d9265c28099e3360559cff55ad1d0e134257adf9afb2e2ee0ae",
                "gstreamer_custom": "sha256:dd9b6106d03a091c4192bd66e1759aa01eb2466d62cb03e82ff21c7fc3ecd096",
            },
        )
        self.assertEqual(
            observed["openvino_gva"]["contract"],
            {
                "image_id": "sha256:f477601c9c6b9d9265c28099e3360559cff55ad1d0e134257adf9afb2e2ee0ae",
                "repository_digest": "vast/openvino-gva-publication-runtime-v3@sha256:f477601c9c6b9d9265c28099e3360559cff55ad1d0e134257adf9afb2e2ee0ae",
                "inspect_projection_sha256": "e1287cecd1eb062be98e8674f2cdc71b009723726fa7c2ea4fd27b06ed49c493",
            },
        )
        self.assertEqual(
            observed["gstreamer_custom"]["contract"],
            {
                "image_id": "sha256:dd9b6106d03a091c4192bd66e1759aa01eb2466d62cb03e82ff21c7fc3ecd096",
                "repository_digest": "vast/gstreamer-custom-publication-runtime-v3@sha256:dd9b6106d03a091c4192bd66e1759aa01eb2466d62cb03e82ff21c7fc3ecd096",
                "inspect_projection_sha256": "d312ee6a3e6f959edfc02531b57adeba0436b0656e022c010f8de74162708ae1",
                "base_image_id": OPENVINO_BASE_IMAGE_ID,
            },
        )
        self.assertEqual(
            inputs["patch"]["workers"]["cpu"]["image_id"],
            "sha256:40d9cb50fa3a107585af9960c43e252d434de3c0f7a6fca728d0be075db1d4ba",
        )
        self.assertEqual(
            inputs["patch"]["workers"]["gpu"]["image_id"],
            "sha256:a92fe2c21b563715a846b1bd765d9dc85218b068dc4ef858b609d5e00325e931",
        )


if __name__ == "__main__":
    unittest.main()
