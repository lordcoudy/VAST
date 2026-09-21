from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import checkpoint_openvino_gva_publication_launcher_v3 as launcher  # noqa: E402
import checkpoint_openvino_gva_publication_runtime_v3 as runtime  # noqa: E402
from checkpoint_openvino_gva_publication_runtime_v3 import (  # noqa: E402
    EXPECTED_IMAGE_ID,
    EXPECTED_IMAGE_REFERENCE,
    EXPECTED_REPOSITORY_DIGEST,
    OpenVINOGVAPublicationRuntimeV3Error,
    run_checkpoint_openvino_gva_publication_runtime_v3,
)
from checkpoint_publication_launcher_adapter_v3 import (  # noqa: E402
    NativePublicationRequestV3,
)


EVIDENCE_NAME = "openvino-gva-native-evidence.json"
GPU_UUID = "GPU-00bb784b-60f3-8bf6-bbd3-5a0c09805266"
SHA = lambda value: hashlib.sha256(value).hexdigest()


def canonical(value: object) -> bytes:
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("ascii")


@unittest.skipUnless(os.name == "posix", "OpenVINO container custody is Linux-only")
class OpenVINOGVAPublicationRuntimeV3Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.output = self.root / "runs" / "openvino-arm"
        self.output.mkdir(parents=True)
        self.arm_path = self.output / "backend_publication_arm_contract.json"
        self.arm_path.write_bytes(b"arm\n")
        self.sockets: list[socket.socket] = []
        self.socket_paths: list[Path] = []
        self.engine_socket = self._socket("docker.sock", socket.SOCK_STREAM)
        self.analytics_socket = self._socket(
            "analytics.sock", socket.SOCK_SEQPACKET
        )

        self.files = {
            "container_engine": self._descriptor(
                "host/docker", b"held docker cli\n", executable=True
            ),
            "checkpoint_runtime": self._descriptor(
                "scripts/checkpoint_gstreamer_runtime.py",
                b"print('fixture runtime')\n",
                container_path="/workspace/project/scripts/checkpoint_gstreamer_runtime.py",
            ),
            "publication_coordinator": self._descriptor(
                "scripts/checkpoint_openvino_gva_container_coordinator_v3.py",
                b"print('fixture coordinator')\n",
                container_path=(
                    "/workspace/project/scripts/"
                    "checkpoint_openvino_gva_container_coordinator_v3.py"
                ),
            ),
            "device_probe": self._descriptor(
                "deploy/openvino/checkpoint/probe_openvino_devices.py",
                b"print('fixture probe')\n",
                container_path=(
                    "/workspace/project/deploy/openvino/checkpoint/"
                    "probe_openvino_devices.py"
                ),
            ),
            "experiments_config": self._descriptor(
                "configs/experiments.yaml",
                b"schema_version: 2\n",
                container_path="/workspace/project/configs/experiments.yaml",
            ),
            "datasets_config": self._descriptor(
                "configs/datasets.yaml",
                b"datasets: {}\n",
                container_path="/workspace/project/configs/datasets.yaml",
            ),
            "analytics_model_manifest": self._descriptor(
                "configs/checkpoint_analytics_models_openvino.yaml",
                b"models: {}\n",
                container_path=(
                    "/workspace/project/configs/"
                    "checkpoint_analytics_models_openvino.yaml"
                ),
            ),
            "analytics_execution_manifest": self._descriptor(
                "configs/analytics_execution_layer.yaml",
                b"workers: {}\n",
                container_path=(
                    "/workspace/project/configs/analytics_execution_layer.yaml"
                ),
            ),
            "policy_capability_manifest": self._descriptor(
                "configs/capability.yaml",
                b"systems: {}\n",
                container_path="/workspace/project/configs/capability.yaml",
            ),
            "policy_calibration": self._descriptor(
                "configs/calibration.yaml",
                b"calibration: {}\n",
                container_path="/workspace/project/configs/calibration.yaml",
            ),
        }
        self.runtime_files = [
            self._descriptor(
                "scripts/benchmark_contract.py",
                b"class ContractError(RuntimeError): pass\n",
                container_path="/workspace/project/scripts/benchmark_contract.py",
            )
        ]
        self.source_files = [
            self._descriptor(
                "data/videos/kpp/kpp_iss_publication_v3/h264/iss_v2_front_gate.mp4",
                b"front gate h264\n",
                container_path=(
                    "/workspace/project/data/videos/kpp/"
                    "kpp_iss_publication_v3/h264/iss_v2_front_gate.mp4"
                ),
            ),
            self._descriptor(
                "data/videos/kpp/kpp_iss_publication_v3/h264/iss_v2_underbody.mp4",
                b"underbody h264\n",
                container_path=(
                    "/workspace/project/data/videos/kpp/"
                    "kpp_iss_publication_v3/h264/iss_v2_underbody.mp4"
                ),
            ),
        ]
        self.model_files = [
            self._descriptor(
                "models/openvino/plate.xml",
                b"<net/>\n",
                container_path="/workspace/project/models/openvino/plate.xml",
            ),
            self._descriptor(
                "models/openvino/plate.bin",
                b"openvino weights\n",
                container_path="/workspace/project/models/openvino/plate.bin",
            ),
        ]
        self.support_files = [
            self._descriptor(
                "artifacts/model-parity.json",
                b'{"accepted":true}\n',
                container_path="/workspace/project/artifacts/model-parity.json",
            )
        ]
        self.inspect_projection = {
            "Architecture": "amd64",
            "Config": {
                "Entrypoint": [runtime.EXPECTED_IMAGE_ENTRYPOINT],
                "Labels": dict(runtime.EXPECTED_IMAGE_LABELS),
                "User": runtime.EXPECTED_IMAGE_USER,
            },
            "Id": EXPECTED_IMAGE_ID,
            "Os": "linux",
            "RepoDigests": [EXPECTED_REPOSITORY_DIGEST],
        }
        self.device_probe = {
            "schema_version": 1,
            "artifact_kind": "vast_openvino_checkpoint_device_probe",
            "openvino_version": "2026.1.0",
            "available_devices": [
                {
                    "device_id": "CPU",
                    "full_device_name": "Intel(R) Core(TM) i7-14700K",
                    "vendor": "Intel",
                    "device_type": "integrated",
                }
            ],
            "gstreamer_elements": {
                name: {"available": True, "plugin": "fixture"}
                for name in (
                    "appsrc",
                    "h264parse",
                    "h265parse",
                    "decodebin",
                    "videoconvert",
                    "tee",
                    "vastanalyticsqueue",
                    "gvadetect",
                    "vastanalyticsterminal",
                )
            },
        }
        self.runtime_contract = {
            "schema_version": 3,
            "artifact_kind": "vast_openvino_gva_publication_runtime_inputs_v3",
            "files": self.files,
            "runtime_files": self.runtime_files,
            "source_files": self.source_files,
            "model_files": self.model_files,
            "support_files": self.support_files,
            "static_hybrid_map": None,
            "container_image": {
                "image_id": EXPECTED_IMAGE_ID,
                "repository_digest": EXPECTED_REPOSITORY_DIGEST,
                "inspect_projection_sha256": (
                    runtime.EXPECTED_IMAGE_INSPECT_PROJECTION_SHA256
                ),
            },
            "embedded_artifacts": dict(runtime.EXPECTED_EMBEDDED_ARTIFACTS),
            "container_engine_socket": self.engine_socket,
            "endpoint_sockets": {
                "analytics_execution": {
                    **self.analytics_socket,
                    "container_path": "/run/vast/analytics-execution.sock",
                }
            },
            "device_binding": {
                "nvidia_decoder_gpu": {
                    "uuid": GPU_UUID,
                    "name": "NVIDIA GeForce RTX 3060",
                    "driver_version": "610.47",
                },
                "docker_gpus_request": f"device={GPU_UUID}",
                "openvino_device_probe_sha256": SHA(canonical(self.device_probe)),
                "required_openvino_device_ids": ["CPU"],
                "nvidia_gpu_counted_as_openvino_gpu": False,
                "analytics_resources": {
                    "cpu": {
                        "runtime": "openvino_cpu",
                        "device": "CPU",
                        "capability_sha256": SHA(b"cpu capability"),
                    },
                    "gpu": {
                        "runtime": "tensorrt_cuda",
                        "device": GPU_UUID,
                        "capability_sha256": SHA(b"gpu capability"),
                    },
                },
            },
            "detect_bin": (
                "videoconvert ! video/x-raw,format={input_format} ! "
                "vastanalyticsqueue branch-id={branch} detector-id={detector_id} "
                "expected-downstream-factory={factory} "
                "expected-model-sha256={model_sha256} "
                "expected-weights-sha256={weights_sha256} "
                "max-buffers={max_buffers} ! {factory} model={model_path} "
                "device={device} batch-size={batch_size} nireq={nireq} "
                "ie-config={ie_config} ! vastanalyticsterminal "
                "branch-id={branch} detector-id={detector_id} "
                "expected-upstream-factory={factory} "
                "expected-model-sha256={model_sha256} "
                "expected-weights-sha256={weights_sha256} "
                "expected-device={device}"
            ),
            "preprocessing_contract_sha256": SHA(b"preprocess"),
            "analytics_queue_max_buffers": 1,
            "scratch_root": tempfile.gettempdir(),
            "ready_timeout_s": 300.0,
            "drain_timeout_s": 10.0,
            "start_lead_ms": 100,
            "container_timeout_s": 900.0,
            "defer_full_resource_acceptance": False,
            "evidence_mapping": {EVIDENCE_NAME: EVIDENCE_NAME},
        }
        self.request = self._request(self.runtime_contract)

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
        value.listen(32)
        self.sockets.append(value)
        self.socket_paths.append(path)
        info = path.lstat()
        return {
            "path": str(path),
            "device": int(info.st_dev),
            "inode": int(info.st_ino),
            "owner_uid": int(info.st_uid),
            "owner_gid": int(info.st_gid),
        }

    def _descriptor(
        self,
        relative: str,
        payload: bytes,
        *,
        executable: bool = False,
        container_path: str | None = None,
    ) -> dict[str, object]:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        if executable:
            path.chmod(0o755)
        result: dict[str, object] = {
            "path": relative.replace("\\", "/"),
            "size_bytes": len(payload),
            "sha256": SHA(payload),
        }
        if container_path is not None:
            result["container_path"] = container_path
        return result

    def _request(
        self,
        contract: dict[str, object],
        *,
        codec: str = "h264",
        topology_kind: str = "shared_video_dag",
    ) -> NativePublicationRequestV3:
        dataset = f"kpp_iss_publication_v3_{codec}"
        scenario = (
            "checkpoint_independent_processes_baseline"
            if topology_kind == "independent_processes"
            else "checkpoint_video_dag_shared"
        )
        contract_sources = contract["source_files"]
        source_shas = [str(value["sha256"]) for value in contract_sources]
        stream_codec = "hevc" if codec == "h265" else codec
        return NativePublicationRequestV3(
            system="openvino_gva",
            topology_kind=topology_kind,
            scenario=scenario,
            project_root=self.root,
            output_dir=self.output,
            arm_contract_path=self.arm_path,
            arm_contract_file_sha256=SHA(b"arm\n"),
            run_id="run-openvino-0001",
            arm_id="arm-openvino-0001-a",
            runtime_inputs={
                "system": "openvino_gva",
                "scenario": scenario,
                "topology_kind": topology_kind,
                "codec": codec,
                "policy": "cpu_only",
                "deadline_ms": 50,
                "dataset": {
                    "name": dataset,
                    "codec_variant": codec,
                    "logical_stream_instances": 6,
                    "streams": [
                        {
                            "stream_id": index,
                            "codec_name": stream_codec,
                            "sha256": source_shas[1 if index == 5 else 0],
                        }
                        for index in range(6)
                    ],
                    "openvino_gva_publication_runtime_v3": contract,
                },
                "streams": 6,
                "duration_s": 180,
                "repeat_index": 0,
                "base_seed": 20260824,
                "run_seed": 42,
                "run_id": "run-openvino-0001",
                "project_root": str(self.root),
                "output_dir": str(self.output),
                "arm_contract_path": str(self.arm_path),
            },
            launcher_evidence_files=(EVIDENCE_NAME,),
        )

    def test_launcher_binds_both_topologies_to_real_container_runner(self) -> None:
        self.assertTrue(launcher.PUBLICATION_READY)
        self.assertFalse(hasattr(launcher, "MISSING_RUNTIME_PINS"))
        for topology in ("independent_processes", "shared_video_dag"):
            self.assertIs(
                launcher.NATIVE_TOPOLOGY_RUNNERS[topology],
                run_checkpoint_openvino_gva_publication_runtime_v3,
            )

    def test_missing_materialized_contract_stays_fail_closed(self) -> None:
        runtime_inputs = dict(self.request.runtime_inputs)
        dataset = dict(runtime_inputs["dataset"])
        dataset.pop("openvino_gva_publication_runtime_v3")
        runtime_inputs["dataset"] = dataset
        request = NativePublicationRequestV3(
            **{**self.request.__dict__, "runtime_inputs": runtime_inputs}
        )
        with self.assertRaisesRegex(
            OpenVINOGVAPublicationRuntimeV3Error,
            "openvino_gva_runtime_input_contract_missing",
        ):
            run_checkpoint_openvino_gva_publication_runtime_v3(request)

    def test_h265_frozen_dataset_accepts_exact_hevc_stream_metadata(self) -> None:
        h265 = json.loads(json.dumps(self.runtime_contract))
        h265["source_files"] = [
            self._descriptor(
                "data/videos/kpp/kpp_iss_publication_v3/h265/"
                "iss_v2_front_gate.mp4",
                b"front gate h265\n",
                container_path=(
                    "/workspace/project/data/videos/kpp/"
                    "kpp_iss_publication_v3/h265/iss_v2_front_gate.mp4"
                ),
            ),
            self._descriptor(
                "data/videos/kpp/kpp_iss_publication_v3/h265/"
                "iss_v2_underbody.mp4",
                b"underbody h265\n",
                container_path=(
                    "/workspace/project/data/videos/kpp/"
                    "kpp_iss_publication_v3/h265/iss_v2_underbody.mp4"
                ),
            ),
        ]
        request = self._request(
            h265, codec="h265", topology_kind="independent_processes"
        )
        contract = runtime._validate_contract(request)
        pins = runtime._open_pins(request, contract)
        try:
            self.assertEqual(len(pins.sources), 2)
            runtime._require_pins_unchanged(pins)
        finally:
            pins.close()

    def test_versioned_analytics_execution_manifest_pins_open(self) -> None:
        contract = json.loads(json.dumps(self.runtime_contract))
        relative = "configs/analytics_execution_layer.refreshed.v4.a215.json"
        contract["files"]["analytics_execution_manifest"] = self._descriptor(
            relative,
            b'{"artifact_kind":"vast_analytics_execution_layer_config"}\n',
            container_path="/workspace/project/" + relative,
        )
        request = self._request(contract)
        validated = runtime._validate_contract(request)
        pins = runtime._open_pins(request, validated)
        try:
            pin = pins.roles["analytics_execution_manifest"]
            self.assertEqual(pin.container_path, "/workspace/project/" + relative)
            self.assertEqual(pin.path.resolve().relative_to(self.root).as_posix(), relative)
        finally:
            pins.close()

    def test_packaged_runtime_script_container_path_cannot_drift(self) -> None:
        contract = json.loads(json.dumps(self.runtime_contract))
        drifted = dict(contract["files"]["checkpoint_runtime"])
        drifted["container_path"] = (
            "/workspace/project/scripts/checkpoint_gstreamer_runtime.other.py"
        )
        contract["files"]["checkpoint_runtime"] = drifted
        request = self._request(contract)
        validated = runtime._validate_contract(request)
        with self.assertRaisesRegex(
            OpenVINOGVAPublicationRuntimeV3Error,
            "openvino_gva_runtime_file_role_container_path_drifted",
        ):
            runtime._open_pins(request, validated)

    def test_stream_five_cannot_be_rebound_to_front_gate_media(self) -> None:
        runtime_inputs = json.loads(json.dumps(self.request.runtime_inputs))
        streams = runtime_inputs["dataset"]["streams"]
        streams[0]["sha256"], streams[5]["sha256"] = (
            streams[5]["sha256"], streams[0]["sha256"],
        )
        request = NativePublicationRequestV3(
            **{**self.request.__dict__, "runtime_inputs": runtime_inputs}
        )
        with self.assertRaisesRegex(
            OpenVINOGVAPublicationRuntimeV3Error,
            "openvino_gva_frozen_kpp_stream_source_binding_invalid",
        ):
            run_checkpoint_openvino_gva_publication_runtime_v3(request)

    def test_exact_image_artifacts_devices_mounts_and_evidence_are_bound(self) -> None:
        calls: list[tuple[str, ...]] = []

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
                    argv, ("image", "inspect", EXPECTED_IMAGE_REFERENCE),
                )
                return mock.Mock(
                    returncode=0,
                    stdout=(json.dumps([self.inspect_projection]) + "\n").encode(),
                    stderr=b"",
                )
            if "/usr/bin/sha256sum" in argv:
                lines = [
                    f"{digest}  {path}"
                    for path, digest in self.runtime_contract[
                        "embedded_artifacts"
                    ].items()
                ]
                return mock.Mock(
                    returncode=0,
                    stdout=("\n".join(lines) + "\n").encode(),
                    stderr=b"",
                )
            if str(self.files["device_probe"]["container_path"]) in argv:
                return mock.Mock(
                    returncode=0,
                    stdout=canonical(self.device_probe),
                    stderr=b"",
                )
            if "/usr/bin/nvidia-smi" in argv:
                value = f"NVIDIA GeForce RTX 3060, {GPU_UUID}, 610.47\n"
                return mock.Mock(
                    returncode=0, stdout=value.encode("ascii"), stderr=b""
                )

            self.assertEqual(timeout_s, 900.0)
            self.assertEqual(argv[0], "run")
            user_index = argv.index("--user")
            self.assertEqual(
                argv[user_index + 1], f"{os.getuid()}:{os.getgid()}"
            )
            for token in (
                "--rm",
                "--network",
                "none",
                "--read-only",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--gpus",
                f"device={GPU_UUID}",
            ):
                self.assertIn(token, argv)
            self.assertIn(EXPECTED_IMAGE_ID, argv)
            self.assertNotIn("vast/openvino-native-probe:dlstreamer-2026.1", argv)
            self.assertIn("HOME=/tmp", argv)
            self.assertIn("XDG_CACHE_HOME=/tmp", argv)
            for binding in (
                "OPENBLAS_NUM_THREADS=1",
                "OMP_NUM_THREADS=1",
                "MKL_NUM_THREADS=1",
                "NUMEXPR_NUM_THREADS=1",
            ):
                self.assertEqual(argv[argv.index(binding) - 1], "--env")
            mounts = [
                argv[index + 1]
                for index, value in enumerate(argv[:-1])
                if value == "--mount"
            ]
            self.assertTrue(any("dst=/opt/vast/output" in value for value in mounts))
            self.assertTrue(any(
                "dst=/run/vast/analytics-execution.sock" in value
                for value in mounts
            ))
            input_mounts = [
                value for value in mounts if "dst=/workspace/project" in value
            ]
            self.assertEqual(len(input_mounts), 1)
            self.assertNotIn("/proc/", input_mounts[0])
            self.assertTrue(input_mounts[0].endswith(",readonly"))
            output_mount = next(
                value for value in mounts if "dst=/opt/vast/output" in value
            )
            runtime_output = Path(next(
                part.removeprefix("src=")
                for part in output_mount.split(",")
                if part.startswith("src=")
            ))
            (runtime_output / EVIDENCE_NAME).write_bytes(b'{"openvino":true}\n')
            terminal = {
                "scenario": self.request.scenario,
                "topology_kind": self.request.topology_kind,
                "accepted_benchmark_sidecars_written": True,
                "publication_blockers": [],
                "publication_acceptance": {
                    "status": "accepted_native_checkpoint_arm",
                    "run_id": self.request.run_id,
                    "system": "openvino_gva",
                    "scenario": self.request.scenario,
                    "topology_kind": self.request.topology_kind,
                    "codec": "h264",
                    "policy": "cpu_only",
                    "deadline_ms": 50.0,
                },
            }
            return mock.Mock(
                returncode=0,
                stdout=canonical(terminal),
                stderr=b"",
            )

        with mock.patch.object(runtime, "_invoke_engine", side_effect=invoke):
            outcome = run_checkpoint_openvino_gva_publication_runtime_v3(self.request)
        self.assertEqual(outcome.exit_code, 0)
        self.assertEqual(outcome.blockers, ())
        self.assertEqual(
            (self.output / EVIDENCE_NAME).read_bytes(),
            b'{"openvino":true}\n',
        )
        self.assertEqual(len(calls), 6)

    def test_image_device_and_embedded_artifact_drift_fail_before_measurement(self) -> None:
        cases = ("image", "device", "artifact")
        for case in cases:
            with self.subTest(case=case):
                measurement_invoked = False

                def invoke(
                    _engine: object,
                    _engine_socket: object,
                    argv: tuple[str, ...],
                    _timeout_s: float,
                ) -> object:
                    nonlocal measurement_invoked
                    if argv[:2] == ("image", "inspect"):
                        value = json.loads(json.dumps(self.inspect_projection))
                        if case == "image":
                            value["Id"] = "sha256:" + "f" * 64
                        return mock.Mock(
                            returncode=0,
                            stdout=(json.dumps([value]) + "\n").encode(),
                            stderr=b"",
                        )
                    if "/usr/bin/sha256sum" in argv:
                        artifacts = dict(self.runtime_contract["embedded_artifacts"])
                        if case == "artifact":
                            artifacts["/usr/local/bin/vast_native_gst_probe"] = "f" * 64
                        return mock.Mock(
                            returncode=0,
                            stdout=("".join(
                                f"{digest}  {path}\n"
                                for path, digest in artifacts.items()
                            )).encode(),
                            stderr=b"",
                        )
                    if str(self.files["device_probe"]["container_path"]) in argv:
                        probe = json.loads(json.dumps(self.device_probe))
                        if case == "device":
                            probe["available_devices"] = []
                        return mock.Mock(
                            returncode=0,
                            stdout=canonical(probe),
                            stderr=b"",
                        )
                    if "/usr/bin/nvidia-smi" in argv:
                        value = (
                            "NVIDIA GeForce RTX 3060, "
                            f"{GPU_UUID}, 610.47\n"
                        )
                        return mock.Mock(
                            returncode=0, stdout=value.encode("ascii"), stderr=b""
                        )
                    measurement_invoked = True
                    raise AssertionError("measurement must not execute")

                with mock.patch.object(runtime, "_invoke_engine", side_effect=invoke), self.assertRaises(
                    OpenVINOGVAPublicationRuntimeV3Error
                ):
                    run_checkpoint_openvino_gva_publication_runtime_v3(self.request)
                self.assertFalse(measurement_invoked)
                self.assertFalse((self.output / EVIDENCE_NAME).exists())

    def test_device_probe_identity_mismatch_retains_observed_probe_and_stays_fail_closed(self) -> None:
        observed = json.loads(json.dumps(self.device_probe))
        observed["available_devices"] = []
        observed_bytes = canonical(observed)
        pinned = str(
            self.runtime_contract["device_binding"]["openvino_device_probe_sha256"]
        )
        measurement_invoked = False

        def invoke(
            _engine: object,
            _engine_socket: object,
            argv: tuple[str, ...],
            _timeout_s: float,
        ) -> object:
            nonlocal measurement_invoked
            if argv[:2] == ("image", "inspect"):
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
                        for path, digest in self.runtime_contract[
                            "embedded_artifacts"
                        ].items()
                    )).encode(),
                    stderr=b"",
                )
            if str(self.files["device_probe"]["container_path"]) in argv:
                return mock.Mock(
                    returncode=0, stdout=observed_bytes, stderr=b""
                )
            measurement_invoked = True
            raise AssertionError("measurement must not execute")

        with mock.patch.object(runtime, "_invoke_engine", side_effect=invoke), self.assertRaisesRegex(
            OpenVINOGVAPublicationRuntimeV3Error,
            "openvino_gva_device_probe_identity_changed",
        ):
            run_checkpoint_openvino_gva_publication_runtime_v3(self.request)
        retained = self.output / "openvino_device_probe.observed.json"
        self.assertEqual(retained.read_bytes(), observed_bytes)
        self.assertEqual(SHA(retained.read_bytes()), SHA(observed_bytes))
        self.assertNotEqual(SHA(observed_bytes), pinned)
        self.assertFalse(measurement_invoked)
        self.assertFalse((self.output / EVIDENCE_NAME).exists())

    def test_transient_config_replacement_is_rejected_after_preflight(self) -> None:
        target = self.root / str(self.files["datasets_config"]["path"])
        original = runtime._require_pins_unchanged
        preflight_complete = False
        checks = 0

        def invoke(
            _engine: object,
            _engine_socket: object,
            argv: tuple[str, ...],
            _timeout_s: float,
        ) -> object:
            nonlocal preflight_complete
            if argv[:2] == ("image", "inspect"):
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
                        for path, digest in self.runtime_contract[
                            "embedded_artifacts"
                        ].items()
                    )).encode(),
                    stderr=b"",
                )
            if str(self.files["device_probe"]["container_path"]) in argv:
                preflight_complete = True
                return mock.Mock(
                    returncode=0, stdout=canonical(self.device_probe), stderr=b""
                )
            raise AssertionError("measurement must not execute")

        def replace_then_check(pins: object) -> None:
            nonlocal checks
            checks += 1
            if preflight_complete and checks >= 2:
                replacement = target.with_name("datasets-replacement.yaml")
                replacement.write_bytes(b"datasets: drifted\n")
                os.replace(replacement, target)
            original(pins)

        with mock.patch.object(runtime, "_invoke_engine", side_effect=invoke), mock.patch.object(
            runtime, "_require_pins_unchanged", side_effect=replace_then_check
        ), self.assertRaisesRegex(
            OpenVINOGVAPublicationRuntimeV3Error,
            "openvino_gva_runtime_input_path_identity_changed",
        ):
            run_checkpoint_openvino_gva_publication_runtime_v3(self.request)

    def test_contract_dataset_topology_and_evidence_mapping_are_closed(self) -> None:
        mutations: list[tuple[dict[str, object], str]] = []
        unknown = json.loads(json.dumps(self.runtime_contract))
        unknown["unknown"] = True
        mutations.append((unknown, "h264"))
        mutable_image = json.loads(json.dumps(self.runtime_contract))
        mutable_image["container_image"]["image_id"] = "openvino:latest"
        mutations.append((mutable_image, "h264"))
        escaped = json.loads(json.dumps(self.runtime_contract))
        escaped["source_files"][0]["path"] = "../escape.mp4"
        mutations.append((escaped, "h264"))
        remapped = json.loads(json.dumps(self.runtime_contract))
        remapped["evidence_mapping"] = {"other.json": EVIDENCE_NAME}
        mutations.append((remapped, "h264"))
        wrong_codec = json.loads(json.dumps(self.runtime_contract))
        mutations.append((wrong_codec, "h265"))

        for index, (contract, codec) in enumerate(mutations):
            with self.subTest(index=index), self.assertRaises(
                OpenVINOGVAPublicationRuntimeV3Error
            ):
                run_checkpoint_openvino_gva_publication_runtime_v3(
                    self._request(contract, codec=codec)
                )

    def test_real_engine_invocation_uses_held_cli_fd_and_pass_fds(self) -> None:
        path = self.root / str(self.files["container_engine"]["path"])
        fd = os.open(path, os.O_RDONLY)
        try:
            engine = mock.Mock(fd=fd, proc_path=f"/proc/self/fd/{fd}")
            process = mock.Mock()
            process.stdout = __import__("io").BytesIO(b"{}\n")
            process.stderr = __import__("io").BytesIO(b"")
            process.returncode = 0
            process.pid = os.getpid()
            process.poll.return_value = 0
            process.wait.return_value = 0
            with mock.patch.object(
                runtime.subprocess, "Popen", return_value=process
            ) as execute:
                observed = runtime._invoke_engine(
                    engine,
                    self.engine_socket,
                    ("version", "--format", "{{json .Server}}"),
                    10.0,
                )
            self.assertEqual(observed.returncode, 0)
            args, kwargs = execute.call_args
            self.assertEqual(args[0][0], engine.proc_path)
            self.assertEqual(kwargs["executable"], engine.proc_path)
            self.assertIn(fd, kwargs["pass_fds"])
            self.assertEqual(
                kwargs["env"]["DOCKER_HOST"],
                f"unix://{self.engine_socket['path']}",
            )
            self.assertTrue(kwargs["close_fds"])
            self.assertTrue(kwargs["start_new_session"])
        finally:
            os.close(fd)

    def test_private_held_fd_copy_is_read_only_and_rehashed(self) -> None:
        source = self.root / "materialized-source.bin"
        payload = b"private-openvino-input\n"
        source.write_bytes(payload)
        source_fd = os.open(source, os.O_RDONLY | os.O_CLOEXEC)
        materialized = None
        try:
            info = source.lstat()
            pin = runtime._Pin(
                role="payload",
                path=source,
                fd=source_fd,
                snapshot=runtime._snapshot(info),
                size=len(payload),
                sha256=SHA(payload),
                container_path="/workspace/project/input/payload.bin",
            )
            pins = runtime._Pins({"payload": pin}, (), (), (), (), None)
            materialized = runtime._materialize_inputs(
                pins, self.root / "private-inputs"
            )
            copied = materialized.files[0].path
            self.assertEqual(copied.read_bytes(), payload)
            self.assertEqual(copied.stat().st_mode & 0o777, 0o444)
            runtime._require_materialized_unchanged(materialized)
            copied.chmod(0o644)
            copied.write_bytes(b"drift\n")
            with self.assertRaisesRegex(
                OpenVINOGVAPublicationRuntimeV3Error,
                "openvino_gva_runtime_materialized_input_changed",
            ):
                runtime._require_materialized_unchanged(materialized)
        finally:
            if materialized is not None:
                materialized.close()
            os.close(source_fd)

    @unittest.skipUnless(
        os.environ.get("VAST_RUN_OPENVINO_LIVE_DOCKER_TEST") == "1",
        "set VAST_RUN_OPENVINO_LIVE_DOCKER_TEST=1 for the WSL Docker proof",
    )
    def test_live_daemon_reads_private_held_fd_copy(self) -> None:
        docker_path = Path("/usr/bin/docker")
        socket_path = Path("/var/run/docker.sock")
        self.assertTrue(docker_path.is_file())
        self.assertTrue(socket_path.is_socket())
        docker_fd = os.open(docker_path, os.O_RDONLY | os.O_CLOEXEC)
        payload_path = self.root / "held-input.bin"
        payload = b"openvino-held-fd-v3\n"
        payload_path.write_bytes(payload)
        payload_path.chmod(0o644)
        payload_fd = os.open(payload_path, os.O_RDONLY | os.O_CLOEXEC)
        probe_path = ROOT / "deploy/openvino/checkpoint/probe_openvino_devices.py"
        probe_fd = os.open(probe_path, os.O_RDONLY | os.O_CLOEXEC)
        materialized = None
        try:
            docker_info = os.fstat(docker_fd)
            engine = runtime._Pin(
                role="container_engine",
                path=docker_path,
                fd=docker_fd,
                snapshot=runtime._snapshot(docker_info),
                size=int(docker_info.st_size),
                sha256=runtime._fd_hash(docker_fd)[1],
            )
            payload_info = payload_path.lstat()
            payload_pin = runtime._Pin(
                role="payload",
                path=payload_path,
                fd=payload_fd,
                snapshot=runtime._snapshot(payload_info),
                size=len(payload),
                sha256=SHA(payload),
                container_path="/workspace/project/held-input.bin",
            )
            probe_info = probe_path.lstat()
            probe_size, probe_sha = runtime._fd_hash(probe_fd)
            probe_pin = runtime._Pin(
                role="device_probe",
                path=probe_path,
                fd=probe_fd,
                snapshot=runtime._snapshot(probe_info),
                size=probe_size,
                sha256=probe_sha,
                container_path=(
                    "/workspace/project/deploy/openvino/checkpoint/"
                    "probe_openvino_devices.py"
                ),
            )
            pins = runtime._Pins(
                {"payload": payload_pin, "device_probe": probe_pin},
                (), (), (), (), None,
            )
            materialized = runtime._materialize_inputs(
                pins, self.root / "private-project"
            )
            container_options = (
                "run", "--rm", "--network", "none", "--read-only",
                "--cap-drop", "ALL", "--security-opt",
                "no-new-privileges", "--pids-limit", "64", "--ipc",
                "none", "--gpus", f"device={GPU_UUID}", "--tmpfs",
                "/tmp:rw,nosuid,nodev,noexec,size=1073741824",
                "--tmpfs", "/run/vast:rw,nosuid,nodev,noexec,size=16777216",
                "--mount",
                (
                    f"type=bind,src={materialized.root},"
                    "dst=/workspace/project,readonly"
                ),
                "--mount",
                (
                    f"type=bind,src={self.analytics_socket['path']},"
                    "dst=/run/vast/analytics-execution.sock,readonly"
                ),
            )
            engine_socket = {"path": str(socket_path)}
            completed = runtime._invoke_engine(
                engine, engine_socket,
                (
                    *container_options, "--entrypoint", "/usr/bin/sha256sum",
                    EXPECTED_IMAGE_ID, "/workspace/project/held-input.bin",
                ),
                60.0,
            )
            self.assertEqual(
                completed.returncode,
                0,
                completed.stderr.decode("utf-8", errors="replace"),
            )
            self.assertEqual(
                completed.stdout.decode("ascii").split()[0], SHA(payload)
            )
            device = runtime._invoke_engine(
                engine, engine_socket,
                (
                    *container_options, "--env", "HOME=/tmp", "--env",
                    "XDG_CACHE_HOME=/tmp", "--workdir", "/workspace/project",
                    "--entrypoint", "/usr/bin/python3", EXPECTED_IMAGE_ID,
                    "-B", str(probe_pin.container_path),
                ),
                180.0,
            )
            self.assertEqual(device.returncode, 0)
            self.assertEqual(device.stderr, b"")
            probe = json.loads(device.stdout)
            self.assertEqual(
                SHA(canonical(probe)),
                "66e849f80ecf859bc76d200d65ff3f07f58fcf1a230de2f098b26accf8922aaf",
            )
            self.assertEqual(
                probe["available_devices"],
                [{
                    "device_id": "CPU",
                    "device_type": "Type.INTEGRATED",
                    "full_device_name": "Intel(R) Core(TM) i7-14700K",
                    "vendor": "",
                }],
            )
            self.assertTrue(all(
                probe["gstreamer_elements"][name]["available"]
                for name in runtime.REQUIRED_GSTREAMER_ELEMENTS
            ))
            nvidia = runtime._invoke_engine(
                engine, engine_socket,
                (
                    *container_options, "--entrypoint", "/usr/bin/nvidia-smi",
                    EXPECTED_IMAGE_ID, "--query-gpu=name,uuid,driver_version",
                    "--format=csv,noheader,nounits",
                ),
                120.0,
            )
            self.assertEqual(nvidia.returncode, 0)
            self.assertEqual(nvidia.stderr, b"")
            self.assertEqual(
                nvidia.stdout.decode("ascii").strip(),
                f"NVIDIA GeForce RTX 3060, {GPU_UUID}, 610.47",
            )
            runtime._require_materialized_unchanged(materialized)
        finally:
            if materialized is not None:
                materialized.close()
            os.close(probe_fd)
            os.close(payload_fd)
            os.close(docker_fd)


if __name__ == "__main__":
    unittest.main()
