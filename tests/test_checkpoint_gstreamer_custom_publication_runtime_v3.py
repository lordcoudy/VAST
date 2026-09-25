from __future__ import annotations

import hashlib
import json
import os
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import checkpoint_gstreamer_custom_publication_launcher_v3 as launcher  # noqa: E402
import checkpoint_gstreamer_publication_runtime_v3 as runtime  # noqa: E402
from checkpoint_gstreamer_publication_runtime_v3 import (  # noqa: E402
    GstreamerPublicationRuntimeV3Error,
    run_checkpoint_gstreamer_publication_runtime_v3,
)
from checkpoint_publication_launcher_adapter_v3 import (  # noqa: E402
    NativePublicationRequestV3,
)


EVIDENCE_NAME = "native-runtime-evidence.json"
FILE_ROLES = (
    "container_engine",
    "device_probe",
    "experiments_config",
    "datasets_config",
    "analytics_model_manifest",
    "analytics_execution_manifest",
    "policy_capability_manifest",
    "policy_calibration",
)


class GstreamerPublicationContainerBoundaryV3Tests(unittest.TestCase):
    def test_runtime_is_bound_to_the_materialized_image_and_not_host_native_dispatch(self) -> None:
        self.assertEqual(
            runtime.EXPECTED_IMAGE_REFERENCE,
            "vast/gstreamer-custom-publication-runtime-v3:materialized",
        )
        self.assertEqual(
            runtime.EXPECTED_IMAGE_ID,
            "sha256:4d0355452b1a819ef56f442ebfeb9d0ab0c01ea393b03783d14145676c8e8b65",
        )
        self.assertEqual(
            runtime.EXPECTED_IMAGE_INSPECT_PROJECTION_SHA256,
            "6c9d555aea03d4baab561cb97ec6ae54238b364ad5d38c83981ace73a7c7a335",
        )
        self.assertTrue({
            "container_image", "embedded_artifacts", "container_engine_socket",
            "endpoint_sockets", "device_binding", "container_timeout_s",
        } <= runtime.RUNTIME_FIELDS)
        self.assertFalse(hasattr(runtime, "checkpoint_gstreamer_runtime"))


def descriptor(
    root: Path, relative: str, payload: bytes, *, mounted: bool = True,
) -> dict[str, object]:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    result: dict[str, object] = {
        "path": relative.replace("\\", "/"),
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }
    if mounted:
        result["container_path"] = f"/workspace/project/{result['path']}"
    return result


@unittest.skipUnless(os.name == "posix", "exact descriptor execution is POSIX-only")
class GstreamerPublicationRuntimeV3Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.output = self.root / "runs" / "arm"
        self.output.mkdir(parents=True)
        self.arm_path = self.output / "backend_publication_arm_contract.json"
        self.arm_path.write_bytes(b"arm\n")
        self.sockets: list[socket.socket] = []
        self.socket_paths: list[Path] = []
        self.engine_socket = self._socket("docker.sock", socket.SOCK_STREAM)
        self.analytics_socket = self._socket(
            "analytics.sock", socket.SOCK_SEQPACKET,
        )

        files = {
            role: descriptor(
                self.root,
                f"runtime/{role}.bin",
                f"{role}:frozen-v3\n".encode("ascii"),
                mounted=role != "container_engine",
            )
            for role in FILE_ROLES
        }
        files["container_engine"]["path"] = str(
            (self.root / str(files["container_engine"]["path"])).resolve()
        )
        (self.root / str(files["container_engine"]["path"])).chmod(0o755)
        source_files = [
            descriptor(
                self.root,
                "data/videos/kpp/kpp_iss_publication_v3/h264/front.mp4",
                b"front-source-media\n",
            ),
            descriptor(
                self.root,
                "data/videos/kpp/kpp_iss_publication_v3/h264/underbody.mp4",
                b"underbody-source-media\n",
            ),
        ]
        model_files = [
            descriptor(self.root, "models/branch.xml", b"model-xml\n"),
            descriptor(self.root, "models/branch.bin", b"model-weights\n"),
        ]
        support_files = [
            descriptor(self.root, "artifacts/accepted-sidecar.json", b"support\n")
        ]
        self.inspect_projection = {
            "Architecture": "amd64",
            "Config": {
                "Entrypoint": [runtime.EXPECTED_IMAGE_ENTRYPOINT],
                "Labels": runtime.EXPECTED_IMAGE_LABELS,
                "User": runtime.EXPECTED_IMAGE_USER,
            },
            "Created": "1970-01-01T00:00:00Z",
            "Id": runtime.EXPECTED_IMAGE_ID,
            "Os": "linux",
            "RepoDigests": [runtime.EXPECTED_REPOSITORY_DIGEST],
        }
        self.device_probe = {
            "schema_version": 1,
            "artifact_kind": "vast_openvino_checkpoint_device_probe",
            "openvino_version": "2026.1.0",
            "available_devices": [{
                "device_id": "CPU", "full_device_name": "fixture CPU",
                "vendor": "Intel", "device_type": "integrated",
            }],
            "gstreamer_elements": {
                name: {"available": True, "factory": name}
                for name in runtime.REQUIRED_GSTREAMER_ELEMENTS
            },
        }
        runtime_contract = {
            "schema_version": 3,
            "artifact_kind": "vast_gstreamer_custom_publication_runtime_inputs_v3",
            "files": files,
            "source_files": source_files,
            "model_files": model_files,
            "support_files": support_files,
            "static_hybrid_map": None,
            "container_image": {
                "image_id": runtime.EXPECTED_IMAGE_ID,
                "repository_digest": runtime.EXPECTED_REPOSITORY_DIGEST,
                "inspect_projection_sha256": runtime.image_projection_sha256(
                    self.inspect_projection
                ),
                "base_image_id": runtime.EXPECTED_BASE_IMAGE_ID,
            },
            "embedded_artifacts": runtime.EXPECTED_EMBEDDED_ARTIFACTS,
            "container_engine_socket": self.engine_socket,
            "endpoint_sockets": {
                "analytics_execution": {
                    **self.analytics_socket,
                    "container_path": "/run/vast/analytics-execution.sock",
                }
            },
            "device_binding": {
                "nvidia_decoder_gpu": {
                    "uuid": "GPU-00bb784b-60f3-8bf6-bbd3-5a0c09805266",
                    "name": "NVIDIA GeForce RTX 3060",
                    "driver_version": "610.47",
                },
                "docker_gpus_request": (
                    "device=GPU-00bb784b-60f3-8bf6-bbd3-5a0c09805266"
                ),
                "openvino_device_probe_sha256": hashlib.sha256(
                    runtime._canonical(self.device_probe)
                ).hexdigest(),
                "required_openvino_device_ids": ["CPU"],
                "nvidia_gpu_counted_as_openvino_gpu": False,
                "analytics_resources": {
                    "cpu": {
                        "runtime": "openvino_cpu", "device": "CPU",
                        "capability_sha256": "b" * 64,
                    },
                    "gpu": {
                        "runtime": "tensorrt_cuda",
                        "device": "GPU-00bb784b-60f3-8bf6-bbd3-5a0c09805266",
                        "capability_sha256": "c" * 64,
                    },
                },
            },
            "preprocessing_contract_sha256": "a" * 64,
            "detect_bin": (
                "videoconvert ! video/x-raw,format={input_format} ! "
                "vastanalyticsqueue branch-id={branch} detector-id={detector_id} "
                "expected-downstream-factory={factory} expected-model-sha256={model_sha256} "
                "expected-weights-sha256={weights_sha256} max-buffers={max_buffers} ! "
                "{factory} name=checkpoint_detector_{branch} model={model_path} "
                "device={device} batch-size={batch_size} nireq={nireq} "
                "ie-config={ie_config} ! vastanalyticsterminal branch-id={branch} "
                "detector-id={detector_id} expected-upstream-factory={factory} "
                "expected-model-sha256={model_sha256} expected-weights-sha256={weights_sha256} "
                "expected-device={device}"
            ),
            "analytics_queue_max_buffers": 4,
            "drain_timeout_s": 10.0,
            "ready_timeout_s": 300.0,
            "start_lead_ms": 100,
            "container_timeout_s": 900.0,
            "scratch_root": tempfile.gettempdir(),
            "defer_full_resource_acceptance": False,
            "evidence_mapping": {EVIDENCE_NAME: EVIDENCE_NAME},
        }
        self.runtime_contract = runtime_contract
        self.request = NativePublicationRequestV3(
            system="gstreamer_custom",
            topology_kind="shared_video_dag",
            scenario="checkpoint_video_dag_shared",
            project_root=self.root,
            output_dir=self.output,
            arm_contract_path=self.arm_path,
            arm_contract_file_sha256=hashlib.sha256(b"arm\n").hexdigest(),
            run_id="run-0001",
            arm_id="arm-0001-a",
            runtime_inputs={
                "system": "gstreamer_custom",
                "scenario": "checkpoint_video_dag_shared",
                "topology_kind": "shared_video_dag",
                "codec": "h264",
                "policy": "cpu_only",
                "deadline_ms": 50,
                "dataset": {
                    "name": "kpp_iss_publication_v3_h264",
                    "codec_variant": "h264",
                    "logical_stream_instances": 6,
                    "streams": [
                        {
                            "stream_id": index,
                            "codec_name": "h264",
                            "sha256": source_files[1 if index == 5 else 0]["sha256"],
                        }
                        for index in range(6)
                    ],
                    "gstreamer_custom_publication_runtime_v3": runtime_contract,
                },
                "streams": 6,
                "duration_s": 180,
                "repeat_index": 0,
                "base_seed": 20260824,
                "run_seed": 42,
                "run_id": "run-0001",
                "project_root": str(self.root),
                "output_dir": str(self.output),
                "arm_contract_path": str(self.arm_path),
            },
            launcher_evidence_files=(EVIDENCE_NAME,),
        )

    def tearDown(self) -> None:
        for value in reversed(self.sockets):
            value.close()
        for path in reversed(self.socket_paths):
            path.unlink(missing_ok=True)
        self.temporary.cleanup()

    def _socket(self, name: str, kind: int) -> dict[str, object]:
        path = self.root / name
        value = socket.socket(socket.AF_UNIX, kind)
        value.bind(str(path))
        value.listen(8)
        self.sockets.append(value)
        self.socket_paths.append(path)
        info = path.lstat()
        return {
            "path": str(path), "device": int(info.st_dev),
            "inode": int(info.st_ino), "owner_uid": int(info.st_uid),
            "owner_gid": int(info.st_gid),
        }

    def _engine_fixture(
        self,
        request: NativePublicationRequestV3,
        evidence: dict[str, bytes],
        calls: list[tuple[str, ...]],
    ) -> object:
        def invoke(
            engine: object,
            engine_socket: object,
            argv: tuple[str, ...],
            timeout_s: float,
        ) -> object:
            os.fstat(engine.fd)
            self.assertEqual(engine_socket["path"], self.engine_socket["path"])
            calls.append(argv)
            if argv[:2] == ("image", "inspect"):
                self.assertEqual(
                    argv,
                    ("image", "inspect", runtime.EXPECTED_IMAGE_REFERENCE),
                )
                return mock.Mock(
                    returncode=0,
                    stdout=(json.dumps([self.inspect_projection]) + "\n").encode(),
                    stderr=b"",
                )
            if "/usr/bin/sha256sum" in argv:
                return mock.Mock(
                    returncode=0,
                    stdout=("".join(
                        f"{digest}  {path}\n"
                        for path, digest in runtime.EXPECTED_EMBEDDED_ARTIFACTS.items()
                    )).encode("ascii"),
                    stderr=b"",
                )
            if str(self.runtime_contract["files"]["device_probe"]["container_path"]) in argv:
                return mock.Mock(
                    returncode=0, stdout=runtime._canonical(self.device_probe), stderr=b"",
                )
            if "/usr/bin/nvidia-smi" in argv:
                return mock.Mock(
                    returncode=0,
                    stdout=(
                        "NVIDIA GeForce RTX 3060, "
                        "GPU-00bb784b-60f3-8bf6-bbd3-5a0c09805266, 610.47\n"
                    ).encode("ascii"),
                    stderr=b"",
                )
            self.assertEqual(timeout_s, 900.0)
            self.assertEqual(argv[0], "run")
            user_index = argv.index("--user")
            self.assertEqual(
                argv[user_index + 1], f"{os.getuid()}:{os.getgid()}"
            )
            self.assertIn(runtime.EXPECTED_IMAGE_ID, argv)
            self.assertNotIn("--system", argv)
            for binding in (
                "OPENBLAS_NUM_THREADS=1",
                "OMP_NUM_THREADS=1",
                "MKL_NUM_THREADS=1",
                "NUMEXPR_NUM_THREADS=1",
            ):
                self.assertEqual(argv[argv.index(binding) - 1], "--env")
            for value in (
                "--rm", "--network", "none", "--read-only", "--cap-drop",
                "ALL", "--security-opt", "no-new-privileges", "--gpus",
                "device=GPU-00bb784b-60f3-8bf6-bbd3-5a0c09805266",
            ):
                self.assertIn(value, argv)
            mounts = [
                argv[index + 1] for index, item in enumerate(argv[:-1])
                if item == "--mount"
            ]
            input_mount = next(
                item for item in mounts if "dst=/workspace/project" in item
            )
            self.assertTrue(input_mount.endswith(",readonly"))
            self.assertNotIn(str(self.root), input_mount)
            output_mount = next(
                item for item in mounts if "dst=/opt/vast/output" in item
            )
            output = Path(next(
                item.removeprefix("src=")
                for item in output_mount.split(",") if item.startswith("src=")
            ))
            for name, payload in evidence.items():
                (output / name).write_bytes(payload)
            terminal = {
                "scenario": request.scenario,
                "topology_kind": request.topology_kind,
                "accepted_benchmark_sidecars_written": True,
                "publication_blockers": [],
                "publication_acceptance": {
                    "status": "accepted_native_checkpoint_arm",
                    "run_id": request.run_id,
                    "system": request.system,
                    "scenario": request.scenario,
                    "codec": request.runtime_inputs["codec"],
                    "policy": request.runtime_inputs["policy"],
                    "deadline_ms": float(request.runtime_inputs["deadline_ms"]),
                    "topology_kind": request.topology_kind,
                },
            }
            return mock.Mock(
                returncode=0, stdout=runtime._canonical(terminal), stderr=b"",
            )

        return invoke

    def test_launcher_is_implemented_and_binds_both_topologies_to_genuine_runner(self) -> None:
        self.assertTrue(launcher.PUBLICATION_READY)
        self.assertFalse(hasattr(launcher, "MISSING_RUNTIME_PINS"))
        self.assertEqual(
            set(launcher.NATIVE_TOPOLOGY_RUNNERS),
            {"independent_processes", "shared_video_dag"},
        )
        self.assertIs(
            launcher.NATIVE_TOPOLOGY_RUNNERS["independent_processes"],
            run_checkpoint_gstreamer_publication_runtime_v3,
        )
        self.assertIs(
            launcher.NATIVE_TOPOLOGY_RUNNERS["shared_video_dag"],
            run_checkpoint_gstreamer_publication_runtime_v3,
        )

    def test_exact_image_devices_mounts_and_evidence_are_bound(self) -> None:
        calls: list[tuple[str, ...]] = []
        invoke = self._engine_fixture(
            self.request, {EVIDENCE_NAME: b'{"native_fixture":true}\n'}, calls,
        )
        with mock.patch.object(runtime, "_invoke_engine", side_effect=invoke):
            outcome = run_checkpoint_gstreamer_publication_runtime_v3(self.request)
        self.assertEqual(outcome.exit_code, 0)
        self.assertEqual(outcome.blockers, ())
        self.assertEqual(
            (self.output / EVIDENCE_NAME).read_bytes(),
            b'{"native_fixture":true}\n',
        )
        self.assertEqual(len(calls), 5)

    def test_transient_path_replacement_is_rejected_before_runtime_invocation(self) -> None:
        target = self.root / str(
            self.runtime_contract["files"]["device_probe"]["path"]
        )
        original_check = __import__(
            "checkpoint_gstreamer_publication_runtime_v3"
        )._require_pins_unchanged
        container = mock.Mock(side_effect=AssertionError("container must not execute"))
        checks = 0

        def replace_then_check(pins: object) -> None:
            nonlocal checks
            checks += 1
            if checks == 2:
                replacement = target.with_name("replacement.bin")
                replacement.write_bytes(b"replacement\n")
                os.replace(replacement, target)
            original_check(pins)

        def inspect_only(*_args: object, **_kwargs: object) -> object:
            return mock.Mock(
                returncode=0,
                stdout=(json.dumps([self.inspect_projection]) + "\n").encode(),
                stderr=b"",
            )

        with mock.patch(
            "checkpoint_gstreamer_publication_runtime_v3._require_pins_unchanged",
            side_effect=replace_then_check,
        ), mock.patch(
            "checkpoint_gstreamer_publication_runtime_v3._invoke_engine",
            side_effect=inspect_only,
        ), mock.patch(
            "checkpoint_gstreamer_publication_runtime_v3._probe_embedded_artifacts",
            container,
        ):
            with self.assertRaisesRegex(
                GstreamerPublicationRuntimeV3Error,
                "gstreamer_runtime_input_path_identity_changed",
            ):
                run_checkpoint_gstreamer_publication_runtime_v3(self.request)
        container.assert_not_called()
        self.assertFalse((self.output / EVIDENCE_NAME).exists())

    def test_descriptor_schema_and_evidence_mapping_are_closed(self) -> None:
        mutations = []
        unknown = json.loads(json.dumps(self.runtime_contract))
        unknown["unknown"] = True
        mutations.append(unknown)
        missing = json.loads(json.dumps(self.runtime_contract))
        del missing["files"]["device_probe"]
        mutations.append(missing)
        escaped = json.loads(json.dumps(self.runtime_contract))
        escaped["files"]["device_probe"]["path"] = "../escape"
        mutations.append(escaped)
        remapped = json.loads(json.dumps(self.runtime_contract))
        remapped["evidence_mapping"] = {"other.json": EVIDENCE_NAME}
        mutations.append(remapped)

        for index, contract in enumerate(mutations):
            with self.subTest(index=index):
                runtime_inputs = dict(self.request.runtime_inputs)
                dataset = dict(runtime_inputs["dataset"])
                dataset["gstreamer_custom_publication_runtime_v3"] = contract
                runtime_inputs["dataset"] = dataset
                request = NativePublicationRequestV3(
                    **{
                        **self.request.__dict__,
                        "runtime_inputs": runtime_inputs,
                    }
                )
                with self.assertRaises(GstreamerPublicationRuntimeV3Error):
                    run_checkpoint_gstreamer_publication_runtime_v3(request)

    def test_evidence_set_is_transactional_and_never_overwrites_a_collision(self) -> None:
        first, second = "first-native.json", "second-native.json"
        contract = dict(self.runtime_contract)
        contract["evidence_mapping"] = {first: first, second: second}
        runtime_inputs = dict(self.request.runtime_inputs)
        dataset = dict(runtime_inputs["dataset"])
        dataset["gstreamer_custom_publication_runtime_v3"] = contract
        runtime_inputs["dataset"] = dataset
        request = NativePublicationRequestV3(
            **{
                **self.request.__dict__,
                "runtime_inputs": runtime_inputs,
                "launcher_evidence_files": (first, second),
            }
        )
        collision = self.output / second
        collision.write_bytes(b"preexisting-parent-evidence\n")

        calls: list[tuple[str, ...]] = []
        invoke = self._engine_fixture(
            request,
            {first: b'{"first":true}\n', second: b'{"second":true}\n'},
            calls,
        )
        with mock.patch.object(
            runtime, "_invoke_engine", side_effect=invoke,
        ), self.assertRaisesRegex(
            GstreamerPublicationRuntimeV3Error,
            "gstreamer_child_evidence_materialization_failed",
        ):
            run_checkpoint_gstreamer_publication_runtime_v3(request)
        self.assertFalse((self.output / first).exists())
        self.assertEqual(collision.read_bytes(), b"preexisting-parent-evidence\n")


if __name__ == "__main__":
    unittest.main()
