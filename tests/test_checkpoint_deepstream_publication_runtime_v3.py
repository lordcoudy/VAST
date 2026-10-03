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

import checkpoint_deepstream_publication_launcher_v3 as launcher  # noqa: E402
from checkpoint_deepstream_publication_runtime_v3 import (  # noqa: E402
    DeepStreamPublicationRuntimeV3Error,
    run_checkpoint_deepstream_publication_runtime_v3,
)
from checkpoint_publication_launcher_adapter_v3 import (  # noqa: E402
    NativePublicationRequestV3,
)


EVIDENCE_NAME = "deepstream-native-evidence.json"
FILE_ROLES = (
    "container_engine",
    "experiments_config",
    "datasets_config",
    "adapter_config",
    "analytics_model_manifest",
    "policy_capability_manifest",
    "policy_calibration",
)
IMAGE_ID = "sha256:" + "a" * 64
REPO_DIGEST = "vast/deepstream-checkpoint@sha256:" + "b" * 64
IMAGE_LABELS = {
    "org.vast.component": "deepstream-checkpoint-native-sdk-runtime",
    "org.vast.publication-runtime-abi": "3",
}


def canonical_sha(value: object) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def descriptor(
    root: Path,
    relative: str,
    payload: bytes,
    *,
    container_path: str,
) -> dict[str, object]:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return {
        "path": relative.replace("\\", "/"),
        "container_path": container_path,
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


@unittest.skipUnless(os.name == "posix", "DeepStream container custody is Linux-only")
class DeepStreamPublicationRuntimeV3Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.output = self.root / "runs" / "arm"
        self.output.mkdir(parents=True)
        self.arm_path = self.output / "backend_publication_arm_contract.json"
        self.arm_path.write_bytes(b"arm\n")
        self.endpoint_path = self.root / "analytics.sock"
        self.endpoint = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        self.endpoint.bind(str(self.endpoint_path))
        self.endpoint.listen(1)
        endpoint_stat = self.endpoint_path.lstat()
        self.engine_socket_path = self.root / "docker.sock"
        self.engine_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.engine_socket.bind(str(self.engine_socket_path))
        self.engine_socket.listen(1)
        engine_socket_stat = self.engine_socket_path.lstat()

        files = {
            role: descriptor(
                self.root,
                f"runtime/{role}.bin",
                f"{role}:frozen-v3\n".encode("ascii"),
                container_path=f"/opt/vast/input/runtime/{role}.bin",
            )
            for role in FILE_ROLES
        }
        engine_path = self.root / str(files["container_engine"]["path"])
        engine_path.chmod(0o755)
        source = descriptor(
            self.root,
            "data/source-h264.mp4",
            b"source-media\n",
            container_path="/opt/vast/input/sources/source-h264.mp4",
        )
        model = descriptor(
            self.root,
            "models/branch.engine",
            b"tensorrt-engine\n",
            container_path="/opt/vast/input/models/branch.engine",
        )
        support = descriptor(
            self.root,
            "runtime/branch-binding.json",
            b'{"binding":"frozen"}\n',
            container_path="/opt/vast/input/runtime/branch-binding.json",
        )
        self.inspect_payload = {
            "Architecture": "amd64",
            "Config": {
                "Entrypoint": ["/usr/local/bin/vast_deepstream_publication_runtime_v3"],
                "Labels": IMAGE_LABELS,
            },
            "Id": IMAGE_ID,
            "Os": "linux",
            "RepoDigests": [REPO_DIGEST],
        }
        runtime_contract = {
            "schema_version": 3,
            "artifact_kind": "vast_deepstream_publication_runtime_inputs_v3",
            "files": files,
            "source_files": [source],
            "model_files": [model],
            "support_files": [support],
            "static_hybrid_map": None,
            "container_image": {
                "image_id": IMAGE_ID,
                "repository_digest": REPO_DIGEST,
                "inspect_sha256": canonical_sha(self.inspect_payload),
                "coordinator_path": "/usr/local/bin/vast_deepstream_publication_runtime_v3",
                "required_labels": IMAGE_LABELS,
            },
            "container_engine_socket": {
                "path": str(self.engine_socket_path),
                "device": int(engine_socket_stat.st_dev),
                "inode": int(engine_socket_stat.st_ino),
                "owner_uid": int(engine_socket_stat.st_uid),
                "owner_gid": int(engine_socket_stat.st_gid),
            },
            "endpoint_sockets": [
                {
                    "host_path": str(self.endpoint_path),
                    "container_path": "/run/vast/analytics.sock",
                    "device": int(endpoint_stat.st_dev),
                    "inode": int(endpoint_stat.st_ino),
                    "owner_uid": int(endpoint_stat.st_uid),
                    "owner_gid": int(endpoint_stat.st_gid),
                }
            ],
            "scratch_root": tempfile.gettempdir(),
            "ready_timeout_s": 300.0,
            "drain_timeout_s": 10.0,
            "start_lead_ms": 100,
            "container_timeout_s": 900.0,
            "defer_full_resource_acceptance": False,
            "evidence_mapping": {EVIDENCE_NAME: EVIDENCE_NAME},
        }
        self.runtime_contract = runtime_contract
        self.request = NativePublicationRequestV3(
            system="deepstream",
            topology_kind="shared_video_dag",
            scenario="checkpoint_video_dag_shared",
            project_root=self.root,
            output_dir=self.output,
            arm_contract_path=self.arm_path,
            arm_contract_file_sha256=hashlib.sha256(b"arm\n").hexdigest(),
            run_id="run-0001",
            arm_id="arm-0001-a",
            runtime_inputs={
                "system": "deepstream",
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
                            "sha256": source["sha256"],
                        }
                        for index in range(6)
                    ],
                    "deepstream_publication_runtime_v3": runtime_contract,
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
        self.endpoint.close()
        self.endpoint_path.unlink(missing_ok=True)
        self.engine_socket.close()
        self.engine_socket_path.unlink(missing_ok=True)
        self.temporary.cleanup()

    def test_launcher_binds_both_topologies_to_real_container_runner(self) -> None:
        self.assertTrue(launcher.PUBLICATION_READY)
        self.assertFalse(hasattr(launcher, "MISSING_RUNTIME_PINS"))
        self.assertIs(
            launcher.NATIVE_TOPOLOGY_RUNNERS["independent_processes"],
            run_checkpoint_deepstream_publication_runtime_v3,
        )
        self.assertIs(
            launcher.NATIVE_TOPOLOGY_RUNNERS["shared_video_dag"],
            run_checkpoint_deepstream_publication_runtime_v3,
        )

    def test_exact_engine_image_inputs_sockets_and_evidence_are_bound(self) -> None:
        observed: dict[str, object] = {}

        def invoke(
            engine: object,
            engine_socket: object,
            argv: tuple[str, ...],
            timeout_s: float,
        ) -> object:
            os.fstat(engine.fd)
            self.assertEqual(engine_socket["path"], str(self.engine_socket_path))
            if argv[:2] == ("image", "inspect"):
                self.assertEqual(argv[2], IMAGE_ID)
                return mock.Mock(
                    returncode=0,
                    stdout=(json.dumps([self.inspect_payload]) + "\n").encode("utf-8"),
                    stderr=b"",
                )
            observed["argv"] = argv
            observed["timeout_s"] = timeout_s
            self.assertEqual(argv[0], "run")
            user_index = argv.index("--user")
            self.assertEqual(
                argv[user_index + 1], f"{os.getuid()}:{os.getgid()}"
            )
            self.assertIn("--gpus", argv)
            self.assertIn("all", argv)
            self.assertIn("--read-only", argv)
            self.assertIn(IMAGE_ID, argv)
            self.assertNotIn("vast/deepstream-checkpoint:latest", argv)
            output_mount = next(
                argv[index + 1]
                for index, value in enumerate(argv[:-1])
                if value == "--mount" and "dst=/opt/vast/output" in argv[index + 1]
            )
            runtime_output = Path(
                next(
                    part.removeprefix("src=")
                    for part in output_mount.split(",")
                    if part.startswith("src=")
                )
            )
            (runtime_output / EVIDENCE_NAME).write_bytes(b'{"deepstream":true}\n')
            status = {
                "schema_version": 3,
                "artifact_kind": "vast_deepstream_publication_terminal_status_v3",
                "run_id": self.request.run_id,
                "arm_id": self.request.arm_id,
                "system": "deepstream",
                "scenario": self.request.scenario,
                "topology_kind": self.request.topology_kind,
                "codec": "h264",
                "policy": "cpu_only",
                "deadline_ms": 50.0,
                "accepted_benchmark_sidecars_written": True,
                "publication_blockers": [],
                "publication_acceptance": {
                    "status": "accepted_native_checkpoint_arm",
                    "run_id": self.request.run_id,
                    "system": "deepstream",
                    "scenario": self.request.scenario,
                    "topology_kind": self.request.topology_kind,
                    "codec": "h264",
                    "policy": "cpu_only",
                    "deadline_ms": 50.0,
                },
            }
            return mock.Mock(
                returncode=0,
                stdout=(json.dumps(status) + "\n").encode("utf-8"),
                stderr=b"",
            )

        with mock.patch(
            "checkpoint_deepstream_publication_runtime_v3._invoke_engine",
            side_effect=invoke,
        ):
            outcome = run_checkpoint_deepstream_publication_runtime_v3(self.request)
        self.assertEqual(outcome.exit_code, 0)
        self.assertEqual(outcome.blockers, ())
        self.assertEqual(
            (self.output / EVIDENCE_NAME).read_bytes(),
            b'{"deepstream":true}\n',
        )
        self.assertEqual(observed["timeout_s"], 900.0)
        argv = observed["argv"]
        for binding in (
            "OPENBLAS_NUM_THREADS=1",
            "OMP_NUM_THREADS=1",
            "MKL_NUM_THREADS=1",
            "NUMEXPR_NUM_THREADS=1",
        ):
            self.assertEqual(argv[argv.index(binding) - 1], "--env")
        self.assertIn("--model-binding", argv)
        self.assertIn(
            self.runtime_contract["model_files"][0]["sha256"]
            + "="
            + str(self.runtime_contract["model_files"][0]["container_path"]),
            argv,
        )
        self.assertIn("--support-binding", argv)
        self.assertIn(
            self.runtime_contract["support_files"][0]["sha256"]
            + "="
            + str(self.runtime_contract["support_files"][0]["container_path"]),
            argv,
        )

    def test_image_inspect_identity_drift_is_rejected_before_run(self) -> None:
        drifted = json.loads(json.dumps(self.inspect_payload))
        drifted["Id"] = "sha256:" + "c" * 64
        invoked = 0

        def invoke(
            _engine: object,
            _engine_socket: object,
            _argv: tuple[str, ...],
            _timeout: float,
        ) -> object:
            nonlocal invoked
            invoked += 1
            return mock.Mock(
                returncode=0,
                stdout=(json.dumps([drifted]) + "\n").encode("utf-8"),
                stderr=b"",
            )

        with mock.patch(
            "checkpoint_deepstream_publication_runtime_v3._invoke_engine",
            side_effect=invoke,
        ), self.assertRaisesRegex(
            DeepStreamPublicationRuntimeV3Error,
            "deepstream_container_image_identity_changed",
        ):
            run_checkpoint_deepstream_publication_runtime_v3(self.request)
        self.assertEqual(invoked, 1)
        self.assertFalse((self.output / EVIDENCE_NAME).exists())

    def test_container_failure_precedes_endpoint_socket_postcondition(self) -> None:
        def invoke(
            _engine: object,
            _engine_socket: object,
            argv: tuple[str, ...],
            _timeout: float,
        ) -> object:
            if argv[:2] == ("image", "inspect"):
                return mock.Mock(
                    returncode=0,
                    stdout=(json.dumps([self.inspect_payload]) + "\n").encode("utf-8"),
                    stderr=b"",
                )
            self.endpoint.close()
            self.endpoint_path.unlink()
            return mock.Mock(
                returncode=2,
                stdout=b"",
                stderr=b"primary container failure\n",
            )

        with mock.patch(
            "checkpoint_deepstream_publication_runtime_v3._invoke_engine",
            side_effect=invoke,
        ), self.assertRaisesRegex(
            DeepStreamPublicationRuntimeV3Error,
            "deepstream_native_runtime_failed.*primary container failure",
        ):
            run_checkpoint_deepstream_publication_runtime_v3(self.request)
        self.assertFalse((self.output / EVIDENCE_NAME).exists())

    def test_transient_input_path_replacement_is_rejected_before_container_run(self) -> None:
        target = self.root / str(
            self.runtime_contract["files"]["adapter_config"]["path"]
        )
        module = __import__("checkpoint_deepstream_publication_runtime_v3")
        original_check = module._require_pins_unchanged
        inspect_done = False

        def invoke(
            _engine: object,
            _engine_socket: object,
            argv: tuple[str, ...],
            _timeout: float,
        ) -> object:
            nonlocal inspect_done
            if argv[:2] == ("image", "inspect"):
                inspect_done = True
                return mock.Mock(
                    returncode=0,
                    stdout=(json.dumps([self.inspect_payload]) + "\n").encode("utf-8"),
                    stderr=b"",
                )
            raise AssertionError("container must not execute")

        checks = 0

        def replace_then_check(pins: object) -> None:
            nonlocal checks
            checks += 1
            if inspect_done and checks >= 2:
                replacement = target.with_name("replacement.bin")
                replacement.write_bytes(b"replacement\n")
                os.replace(replacement, target)
            original_check(pins)

        with mock.patch(
            "checkpoint_deepstream_publication_runtime_v3._invoke_engine",
            side_effect=invoke,
        ), mock.patch(
            "checkpoint_deepstream_publication_runtime_v3._require_pins_unchanged",
            side_effect=replace_then_check,
        ), self.assertRaisesRegex(
            DeepStreamPublicationRuntimeV3Error,
            "deepstream_runtime_input_path_identity_changed",
        ):
            run_checkpoint_deepstream_publication_runtime_v3(self.request)
        self.assertFalse((self.output / EVIDENCE_NAME).exists())

    def test_contract_schema_dataset_and_evidence_mapping_are_closed(self) -> None:
        mutations: list[dict[str, object]] = []
        unknown = json.loads(json.dumps(self.runtime_contract))
        unknown["unknown"] = True
        mutations.append(unknown)
        mutable_image = json.loads(json.dumps(self.runtime_contract))
        mutable_image["container_image"]["image_id"] = "vast/deepstream:latest"
        mutations.append(mutable_image)
        escaped = json.loads(json.dumps(self.runtime_contract))
        escaped["files"]["adapter_config"]["path"] = "../escape"
        mutations.append(escaped)
        remapped = json.loads(json.dumps(self.runtime_contract))
        remapped["evidence_mapping"] = {"other.json": EVIDENCE_NAME}
        mutations.append(remapped)
        duplicate_source = json.loads(json.dumps(self.runtime_contract))
        duplicate_source["source_files"].append(
            descriptor(
                self.root,
                "data/source-h264-duplicate.mp4",
                b"source-media\n",
                container_path="/opt/vast/input/sources/source-h264-duplicate.mp4",
            )
        )
        mutations.append(duplicate_source)

        for index, contract in enumerate(mutations):
            with self.subTest(index=index):
                runtime_inputs = dict(self.request.runtime_inputs)
                dataset = dict(runtime_inputs["dataset"])
                dataset["deepstream_publication_runtime_v3"] = contract
                runtime_inputs["dataset"] = dataset
                request = NativePublicationRequestV3(
                    **{**self.request.__dict__, "runtime_inputs": runtime_inputs}
                )
                with self.assertRaises(DeepStreamPublicationRuntimeV3Error):
                    run_checkpoint_deepstream_publication_runtime_v3(request)


if __name__ == "__main__":
    unittest.main()
