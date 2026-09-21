from __future__ import annotations

import ast
import copy
import errno
import hashlib
import io
import json
import os
import signal
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
from contextlib import contextmanager
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import kpp_legacy_iss_v2_secondary_sensitivity_executor as executor
import kpp_legacy_iss_v2_secondary_sensitivity_pilot as pilot


V2_MOUNT_FORENSIC = ROOT / (
    "runs/nonpublication/runtime_environments/"
    "kpp-v2-cp312-pandas3.0.1-20260822-v1/"
    "secondary_v2_mount_mode_failure_forensic"
)
V2_RUN_ID = "kpp-v2-secondary-pilot-20260822-v2"
V2_RUN_IDENTITY = "9086fffb159ecd95363e4ca4a5ee8c8d57f7ff6582632284e478272215d92b13"
V2_CONTAINER_FIXTURES = {
    "damage": (
        "f522152c1b433293f5ccd803344c1dfe4248eb226cb6bb7c3860469dd893f1bd",
        "26bd6480b2d42b5763da880673f9dfdcf82fcba21a2b786ec85d02582dbd5e6a",
        9_266,
    ),
    "foreign_object": (
        "1ce47bc93dbf3a8146d3cc77d106d48711da436a8af48ad5346fdd15ccb676e2",
        "9d078a307fc5f2f5685794782de654c595ddbd824e51bf7d55280f9a1e10d613",
        9_346,
    ),
    "plate_number": (
        "e98629cacada4252750153667c3ab77481495b2356c0902b12d9f766600c8f88",
        "e8ff8e3fe8700c9315b083ba85426aa8b69c37663f11fea3d63973a57ca7314b",
        9_318,
    ),
    "vehicle_type": (
        "9fd78df4793f6263551d61cb5f85b0c12530c70eef19878a0362af7c545fb90d",
        "744d152b32db1544a1c982572d6ec5188f880f9038811d17fbc030590d3745aa",
        9_318,
    ),
}
V3_ZERO_MOUNT_FORENSIC = ROOT / (
    "runs/nonpublication/runtime_environments/"
    "kpp-v2-cp312-pandas3.0.1-20260822-v1/"
    "secondary_v3_zero_mount_failure_forensic"
)
V3_RUN_ID = "kpp-v2-secondary-pilot-20260822-v3"
V3_RUN_IDENTITY = "33466eb7218caae775c703f538a6367962e7d9c81a69c8ee736b00b9c2fde165"
V3_PROBE_FIXTURE = (
    "5d636718f4eea6399c40578711508ef683f16c483560a7b0bd41e5b91bee5151",
    "310d38ce48f77f9bbcbdb94a30f7d951dd97b7640db6c22d0d5dc82cfb59fc69",
    7_422,
)
PEERCRED_DIAGNOSTIC_RUN_ROOT = ROOT / (
    "runs/nonpublication/"
    "kpp-v2-secondary-peercred-diagnostic-20260822-v1"
)
PEERCRED_DIAGNOSTIC_CAPTURE_ROOT = ROOT / (
    "runs/nonpublication/runtime_environments/"
    "kpp-v2-cp312-pandas3.0.1-20260822-v1/"
    "secondary_peercred_diagnostic_invocation_capture_v1"
)
PEERCRED_DAEMON_INFO_FIXTURE = ROOT / (
    "runs/nonpublication/runtime_environments/"
    "kpp-v2-cp312-pandas3.0.1-20260822-v1/"
    "secondary_v3_retry1_peercred_failure_forensic/daemon.info.stdout.bin"
)
PEERCRED_DAEMON_INFO_FIXTURE_SHA256 = (
    "4fc97e33301bc90e11b8560974d7de8a4348f3056a69730ef4823f883893fb88"
)
PEERCRED_DAEMON_INFO_FIXTURE_SIZE = 15_770
PEERCRED_DIAGNOSTIC_FIXTURES = {
    "damage": {
        "diagnostic_sha256": "b9687d94bd84081d01d887a988d02c5d2315a78050cc595a4ff31582d895e75b",
        "inspect_sha256": "e2b93751a3c003edcaf5093fdb1cdd5f3a879923f88e13bdd7382cc11bb5d6c6",
        "state_pid": 6622,
    },
    "foreign_object": {
        "diagnostic_sha256": "17918e28385b3a7f463fc34f2f26b9bb13d12a8cd7b226f17c2e5de6c6cd03ad",
        "inspect_sha256": "5db2e25859569177302077c278de00b0637cedc67e0d15160ff921743d587d9f",
        "state_pid": 6771,
    },
    "plate_number": {
        "diagnostic_sha256": "657212b2fef54650e664994c66d26005df514dd9cd7d7d3f637ce2b8d085146d",
        "inspect_sha256": "5913a4d12b268001523d471ab48ea597ea109229db00c22fa0943d92c8cfdb9b",
        "state_pid": 6749,
    },
    "vehicle_type": {
        "diagnostic_sha256": "b5ceb31b11c89802275e018a260b6994a8d7ad7743c77c34c062af40097345d8",
        "inspect_sha256": "4dd5b6c8e868b33b046e8d16ad297d5b862481e47eb97420f7289ad3b174d4cd",
        "state_pid": 6659,
    },
}


@dataclass
class ScriptedRunner:
    image_present: bool

    def __post_init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def run(
        self,
        argv: list[str],
        *,
        timeout_seconds: float,
        stdout_limit: int,
        stderr_limit: int,
    ) -> executor.CommandCapture:
        del timeout_seconds, stdout_limit, stderr_limit
        command = tuple(argv)
        self.calls.append(command)
        if "info" in command:
            return executor.CommandCapture(
                0,
                (
                    b'{"ID":"1e493309-3767-45fb-9078-05b838bdfd80",'
                    b'"ServerVersion":"29.5.3","OSType":"linux",'
                    b'"Architecture":"x86_64","Name":"docker-desktop",'
                    b'"OperatingSystem":"Docker Desktop",'
                    b'"KernelVersion":"6.6.87.2-microsoft-standard-WSL2",'
                    b'"Driver":"overlayfs",'
                    b'"DriverStatus":[["driver-type","io.containerd.snapshotter.v1"]],'
                    b'"DefaultRuntime":"runc",'
                    b'"ContainerdCommit":{"ID":"e53c7c1516c3b2bff98eb76f1f4117477e6f4e66"}}\n'
                ),
                b"",
            )
        if "version" in command:
            return executor.CommandCapture(
                0,
                b'{"Version":"29.5.3","ApiVersion":"1.54",'
                b'"Os":"linux","Arch":"amd64"}\n',
                b"",
            )
        if "image" in command and "inspect" in command:
            if not self.image_present:
                return executor.CommandCapture(
                    1,
                    b"",
                    f"Error response from daemon: No such image: {executor.TENSORRT_IMAGE_ID}\n".encode("ascii"),
                )
            value = {
                "Id": executor.TENSORRT_IMAGE_ID,
                "Os": "linux",
                "Architecture": "amd64",
                "Config": {
                    "Entrypoint": [executor.TENSORRT_ENTRYPOINT],
                    "Labels": {
                        "org.vast.analytics_worker.base_image_id": executor.TENSORRT_BASE_IMAGE_ID,
                        "org.vast.analytics_worker.engine": "tensorrt_cuda",
                    },
                },
            }
            return executor.CommandCapture(0, executor.canonical_line(value), b"")
        if "image" in command and "ls" in command:
            return executor.CommandCapture(0, b"", b"")
        if "container" in command and "inspect" in command:
            reference = command[-1]
            return executor.CommandCapture(
                1,
                b"",
                f"Error: No such container: {reference}\n".encode("ascii"),
            )
        if "container" in command and "ls" in command:
            return executor.CommandCapture(0, b"", b"")
        raise AssertionError(f"unexpected Docker command: {command!r}")


class KppLegacyIssV2SecondarySensitivityExecutorTests(unittest.TestCase):
    @contextmanager
    def _native_run_lease(self, run_identity: str) -> object:
        unresolved_root = executor._unresolved_operation_root_path()
        lease = executor._acquire_run_lease(run_identity)
        try:
            yield lease
        finally:
            lease.release()
            self.assertEqual(os.listdir(unresolved_root), [])

    @contextmanager
    def _native_cleanup_mutex(
        self,
        run_identity: str,
    ) -> object:
        path = executor._cleanup_mutex_path(run_identity)
        self.assertFalse(path.exists(), "cleanup mutex test path is not fresh")
        reservation = executor._create_cleanup_mutex(run_identity)
        expected_inode = int(reservation.contract["mutex_identity"]["inode"])
        try:
            yield reservation
        finally:
            reservation.close()
            value = path.lstat()
            self.assertTrue(stat.S_ISREG(value.st_mode))
            self.assertEqual(int(value.st_ino), expected_inode)
            self.assertEqual(stat.S_IMODE(value.st_mode), 0o600)
            self.assertEqual(value.st_nlink, 1)
            self.assertEqual(value.st_size, 0)
            path.unlink()

    def _peercred_daemon(self, **changes: object) -> dict[str, object]:
        core: dict[str, object] = {
            "daemon_id": "aa8f3d33-e1dc-4ed2-ad06-488b46b332d0",
            "server_version": "29.7.2",
            "api_version": "1.55",
            "os": "linux",
            "architecture": "amd64",
            "name": "docker-desktop",
            "operating_system": "Docker Desktop",
            "kernel_version": "6.6.87.2-microsoft-standard-WSL2",
            "driver": "overlayfs",
            "driver_status": [["driver-type", "io.containerd.snapshotter.v1"]],
            "default_runtime": "runc",
            "containerd_commit": {
                "ID": "e53c7c1516c3b2bff98eb76f1f4117477e6f4e66"
            },
        }
        core.update(changes)
        return {
            **core,
            "observation_sha256": hashlib.sha256(
                executor._canonical_json(core)
            ).hexdigest(),
        }

    def _daemon_info_document(
        self, daemon: Mapping[str, object]
    ) -> dict[str, object]:
        return {
            "ID": daemon["daemon_id"],
            "ServerVersion": daemon["server_version"],
            "OSType": "linux",
            "Architecture": "x86_64",
            "Name": daemon["name"],
            "OperatingSystem": daemon["operating_system"],
            "KernelVersion": daemon["kernel_version"],
            "Driver": daemon["driver"],
            "DriverStatus": daemon["driver_status"],
            "DefaultRuntime": daemon["default_runtime"],
            "ContainerdCommit": daemon["containerd_commit"],
        }

    def _peercred_daemon_info_document(self) -> dict[str, object]:
        return self._daemon_info_document(self._peercred_daemon())

    def _peer_runtime_custody(
        self,
        *,
        desktop_label: bool,
        **changes: object,
    ) -> dict[str, object]:
        value: dict[str, object] = {
            "native_ipc_namespace_attested": True,
            "readonly_mounts_attested": True,
            "container_image_entrypoint_identity_attested": True,
            "docker_desktop_wsl_distro_label_attested": desktop_label,
            "container_runtime": "runc",
        }
        value.update(changes)
        return value

    def _image_inspect(self) -> dict[str, object]:
        return {
            "Id": executor.TENSORRT_IMAGE_ID,
            "Os": "linux",
            "Architecture": "amd64",
            "Config": {
                "Entrypoint": [executor.TENSORRT_ENTRYPOINT],
                "Labels": {
                    "org.vast.analytics_worker.base_image_id": executor.TENSORRT_BASE_IMAGE_ID,
                    "org.vast.analytics_worker.engine": "tensorrt_cuda",
                },
            },
        }

    def _container_document(
        self,
        *,
        container_id: str,
        name: str,
        labels: dict[str, str],
        state: str,
        mounts: dict[str, Path] | None = None,
        exit_code: int = 0,
        daemon_injected_labels: dict[object, object] | None = None,
        mount_mode: str = "ro",
    ) -> dict[str, object]:
        expected_mounts = mounts or {}
        return {
            "Id": container_id,
            "Name": "/" + name,
            "Image": executor.TENSORRT_IMAGE_ID,
            "Config": {
                "Image": executor.TENSORRT_IMAGE_ID,
                "User": f"{executor.CONTAINER_UID}:{executor.CONTAINER_GID}",
                "Entrypoint": [executor.TENSORRT_ENTRYPOINT],
                "Cmd": ["--capability", "--gpu-device-index", "0"],
                "Labels": {
                    "org.vast.analytics_worker.base_image_id": executor.TENSORRT_BASE_IMAGE_ID,
                    "org.vast.analytics_worker.engine": "tensorrt_cuda",
                    **labels,
                    **(daemon_injected_labels or {}),
                },
            },
            "HostConfig": {
                "Binds": None,
                "Mounts": [
                    {
                        "Type": "bind",
                        "Source": str(source),
                        "Target": destination,
                        "ReadOnly": True,
                    }
                    for destination, source in expected_mounts.items()
                ],
                "NetworkMode": "none",
                "ReadonlyRootfs": True,
                "CapDrop": ["ALL"],
                "SecurityOpt": ["no-new-privileges"],
                "Privileged": False,
                "PidMode": "",
                "IpcMode": "private",
                "Runtime": "runc",
                "Memory": executor.CONTAINER_MEMORY_BYTES,
                "MemorySwap": executor.CONTAINER_MEMORY_BYTES,
                "NanoCpus": executor.CONTAINER_NANO_CPUS,
                "PidsLimit": executor.CONTAINER_PIDS_LIMIT,
                "RestartPolicy": {"Name": "no", "MaximumRetryCount": 0},
                "AutoRemove": False,
                "Ulimits": [{"Name": "nofile", "Hard": 1024, "Soft": 1024}],
                "DeviceRequests": [
                    {
                        "Driver": "",
                        "Count": 0,
                        "DeviceIDs": [executor.TENSORRT_GPU_UUID],
                        "Capabilities": [["gpu"]],
                        "Options": {},
                    }
                ],
            },
            "Mounts": [
                {
                    "Type": "bind",
                    "Source": str(source),
                    "Destination": destination,
                    "Mode": mount_mode,
                    "RW": False,
                    "Propagation": "rprivate",
                }
                for destination, source in expected_mounts.items()
            ],
            "State": {
                "Status": state,
                "Running": state in {"running", "paused", "restarting"},
                "Pid": 4321 if state in {"running", "paused", "restarting"} else 0,
                "ExitCode": exit_code,
                "OOMKilled": False,
                "Dead": False,
                "Paused": state == "paused",
                "Restarting": state == "restarting",
                "Error": "",
            },
        }

    def _v2_mount_fixture(
        self, branch: str
    ) -> tuple[dict[str, object], dict[str, PurePosixPath], dict[str, str]]:
        container_id, expected_sha256, expected_size = V2_CONTAINER_FIXTURES[branch]
        path = V2_MOUNT_FORENSIC / f"{branch}.inspect.stdout.bin"
        payload = path.read_bytes()
        self.assertEqual(len(payload), expected_size)
        self.assertEqual(hashlib.sha256(payload).hexdigest(), expected_sha256)
        document = executor._parse_json(payload, f"captured Docker 29 {branch} fixture")
        host_mounts = document["HostConfig"]["Mounts"]
        mounts = {
            str(item["Target"]): PurePosixPath(str(item["Source"]))
            for item in host_mounts
        }
        labels = {
            executor.OWNER_LABEL: executor.OWNER_VALUE,
            executor.RUN_LABEL: V2_RUN_IDENTITY,
            executor.BRANCH_LABEL: branch,
        }
        actual_labels = dict(document["Config"]["Labels"])
        expected_image_labels = {
            str(key): str(value)
            for key, value in actual_labels.items()
            if key
            not in {
                executor.OWNER_LABEL,
                executor.RUN_LABEL,
                executor.BRANCH_LABEL,
                "desktop.docker.io/wsl-distro",
            }
        }
        self.assertEqual(document["Id"], container_id)
        return document, mounts, expected_image_labels

    def _v3_zero_mount_probe_fixture(
        self,
    ) -> tuple[dict[str, object], dict[str, str], dict[str, str]]:
        container_id, expected_sha256, expected_size = V3_PROBE_FIXTURE
        path = V3_ZERO_MOUNT_FORENSIC / "probe.inspect.stdout.bin"
        payload = path.read_bytes()
        self.assertEqual(len(payload), expected_size)
        self.assertEqual(hashlib.sha256(payload).hexdigest(), expected_sha256)
        document = executor._parse_json(
            payload, "captured Docker 29 zero-mount probe fixture"
        )
        labels = {
            executor.OWNER_LABEL: executor.OWNER_VALUE,
            executor.RUN_LABEL: V3_RUN_IDENTITY,
            executor.BRANCH_LABEL: "runtime_probe",
        }
        actual_labels = dict(document["Config"]["Labels"])
        expected_image_labels = {
            str(key): str(value)
            for key, value in actual_labels.items()
            if key
            not in {
                executor.OWNER_LABEL,
                executor.RUN_LABEL,
                executor.BRANCH_LABEL,
                "desktop.docker.io/wsl-distro",
            }
        }
        self.assertEqual(document["Id"], container_id)
        self.assertNotIn("Mounts", document["HostConfig"])
        self.assertEqual(document["Mounts"], [])
        return document, labels, expected_image_labels

    def test_worker_create_command_is_offline_nonroot_and_exact_gpu_pinned(self) -> None:
        command = executor._build_worker_create_command(
            container_name="vast-kpp-v2-np-0123456789abcdef-plate-number",
            labels={
                executor.OWNER_LABEL: executor.OWNER_VALUE,
                executor.RUN_LABEL: "a" * 64,
                executor.BRANCH_LABEL: "plate_number",
            },
            binding_source=Path("/run/private/bindings/plate_number.json"),
            source_model=Path("/run/private/models/resnet18-v1-7.onnx"),
            engine=Path("/run/private/models/resnet18-v1-7.engine"),
            socket_root=Path("/run/private/sockets"),
            socket_name="plate_number.sock",
        )

        self.assertEqual(command[:2], [executor.DOCKER_CLI, executor.DOCKER_HOST_ARG])
        self.assertIn("--pull=never", command)
        self.assertIn("--network=none", command)
        self.assertIn("--read-only", command)
        self.assertIn("--cap-drop=ALL", command)
        self.assertIn("--security-opt=no-new-privileges", command)
        self.assertIn(f"--user={executor.CONTAINER_UID}:{executor.CONTAINER_GID}", command)
        self.assertIn(f"device={executor.TENSORRT_GPU_UUID}", command)
        self.assertIn(executor.TENSORRT_IMAGE_ID, command)
        self.assertNotIn("pull", command)
        self.assertNotIn("build", command)
        self.assertNotIn("--gpus=all", command)
        self.assertFalse(any("docker.sock" in token for token in command[2:]))

    def test_inference_request_uses_exact_sample_id_and_coordinator_ordinal(self) -> None:
        sample_id = "kpp-v2-underbody-h265-calibration-0007"
        request = {
            "request_id": "kpp-v2-nonpublication-underbody-h265-calibration-smoke-v1",
            "sample_id": sample_id,
            "branch": "underbody",
            "codec": "h265",
            "tensor": {
                "offset_bytes": 17 * pilot.TENSOR_SEGMENT_BYTES,
                "dtype": "float32",
                "layout": "NCHW",
                "shape": [1, 3, 224, 224],
                "segment_sha256": "1" * 64,
                "preprocessing_contract_sha256": "2" * 64,
            },
        }
        capability = {
            "worker_id": "vast.underbody.tensorrt",
            "model_id": "underbody_model",
            "source_model_sha256": "3" * 64,
            "model_artifact_sha256": "4" * 64,
            "output_contract_sha256": "5" * 64,
        }

        built = executor._build_inference_request(
            request=request,
            binding={"input": {"name": "data"}},
            capability=capability,
            run_id="synthetic-run-v1",
        )

        self.assertEqual(built["frame"]["input_frame_key"], sample_id)
        self.assertEqual(built["frame"]["frame_id"], 1)
        self.assertEqual(built["frame"]["transport_pts_ns"], 0)

    def test_watchdog_control_failure_still_reaps_the_watchdog_process(self) -> None:
        read_fd, write_fd = os.pipe()
        process = mock.Mock()
        process.wait.return_value = 0
        handle = executor._ContainerWatchdogProcess(
            process=process,
            control_fd=write_fd,
        )
        try:
            with mock.patch.object(executor.os, "write", return_value=0):
                with self.assertRaisesRegex(
                    executor.ExecutorContractError,
                    "marker write stalled",
                ):
                    handle.complete()
            process.wait.assert_called_once_with(timeout=300.0)
        finally:
            os.close(read_fd)

    def test_container_watchdog_v4_markers_and_ambiguous_late_commit_owner(self) -> None:
        read_fd, write_fd = os.pipe()
        process = mock.Mock()
        process.wait.return_value = 0
        handle = executor._ContainerWatchdogProcess(
            process=process,
            control_fd=write_fd,
        )
        handle.mark_create_dispatch()
        handle.mark_create_terminal()
        handle.complete()
        self.assertEqual(os.read(read_fd, 3), b"DTC")
        os.close(read_fd)

        control_read, control_write = os.pipe()
        ready_read, ready_write = os.pipe()
        raw_contract = b"{}\n"
        os.write(
            control_write,
            len(raw_contract).to_bytes(4, "big") + raw_contract,
        )
        daemon = {
            "daemon_id": "synthetic-daemon",
            "server_version": "29.7.2",
            "api_version": "1.55",
            "observation_sha256": "a" * 64,
        }
        contract = {
            "docker_cli": {
                "path": "/synthetic/docker",
                "size_bytes": 1,
                "sha256": "b" * 64,
            },
            "daemon": daemon,
            "cleanup_mutex": {},
            "run_lease": {},
            "unresolved_operation": {},
            "container_name": "vast-kpp-v2-np-0123456789abcdef-probe",
            "labels": {
                executor.OWNER_LABEL: executor.OWNER_VALUE,
                executor.RUN_LABEL: "c" * 64,
                executor.BRANCH_LABEL: "runtime_probe",
            },
            "expected_mounts": {},
            "image_labels": dict(executor.IMAGE_LABELS),
        }
        first_absence = threading.Event()
        allow_late_commit = threading.Event()
        recovery_calls: list[str] = []

        def recover_late(**kwargs: object) -> str | None:
            recovery_calls.append(str(kwargs["container_name"]))
            return None if len(recovery_calls) == 1 else "d" * 64

        def wait_between_observations(_seconds: float) -> None:
            first_absence.set()
            if not allow_late_commit.wait(timeout=5):
                raise AssertionError("late commit was not released")

        child_status: list[int] = []
        retention_hold = mock.Mock()
        unresolved_hold = mock.Mock()

        def run_child() -> None:
            child_status.append(
                executor._owned_container_watchdog_main(
                    control_read,
                    ready_write,
                )
            )

        with mock.patch.object(
            executor,
            "_validate_watchdog_contract",
            return_value=contract,
        ), mock.patch.object(
            executor,
            "_observe_regular_file",
            return_value=executor.FileIdentity(1, "b" * 64),
        ), mock.patch.object(
            executor,
            "_validate_daemon",
            return_value=daemon,
        ), mock.patch.object(
            executor,
            "_CleanupMutexReference",
            return_value=executor._NullCleanupMutex(),
        ), mock.patch.object(
            executor,
            "_validate_cleanup_mutex_contract",
            return_value={},
        ), mock.patch.object(
            executor,
            "_acquire_run_retention_hold",
            return_value=retention_hold,
        ), mock.patch.object(
            executor,
            "_acquire_unresolved_operation_marker_hold",
            return_value=unresolved_hold,
        ), mock.patch.object(
            executor,
            "_recover_and_cleanup_owned_container_by_name",
            side_effect=recover_late,
        ), mock.patch.object(
            executor.time,
            "sleep",
            side_effect=wait_between_observations,
        ):
            child = threading.Thread(target=run_child)
            child.start()
            self.assertEqual(os.read(ready_read, 1), b"R")
            os.write(control_write, b"D")
            os.close(control_write)
            self.assertTrue(first_absence.wait(timeout=5))
            self.assertTrue(child.is_alive())
            self.assertEqual(len(recovery_calls), 1)
            allow_late_commit.set()
            child.join(timeout=5)
        os.close(ready_read)
        self.assertFalse(child.is_alive())
        self.assertEqual(
            child_status,
            [executor._WATCHDOG_LATE_COMMIT_REMOVED_RC],
        )
        self.assertEqual(len(recovery_calls), 2)
        unresolved_hold.resolve.assert_called_once_with()
        unresolved_hold.close.assert_called_once_with()
        retention_hold.close.assert_called_once_with()

    def test_container_watchdog_name_binding_is_deterministic_and_disjoint(
        self,
    ) -> None:
        run_identity = "c" * 64
        for branch in ("runtime_probe", *pilot.BRANCHES):
            with self.subTest(branch=branch, case="exact"):
                suffix = "probe" if branch == "runtime_probe" else branch
                name = f"vast-kpp-v2-np-{run_identity[:16]}-{suffix}"
                labels = {
                    executor.OWNER_LABEL: executor.OWNER_VALUE,
                    executor.RUN_LABEL: run_identity,
                    executor.BRANCH_LABEL: branch,
                }
                self.assertEqual(
                    executor._validate_container_watchdog_name_binding(
                        name,
                        labels,
                    ),
                    name,
                )
                wrong_suffixes = {
                    "synthetic-container",
                    f"vast-kpp-v2-np-{'d' * 16}-{suffix}",
                    f"vast-kpp-v2-np-{run_identity[:16]}-runtime_probe",
                    f"vast-kpp-v2-np-{run_identity[:16]}-probe",
                    *(
                        f"vast-kpp-v2-np-{run_identity[:16]}-{other}"
                        for other in pilot.BRANCHES
                        if other != branch
                    ),
                }
                wrong_suffixes.discard(name)
                for wrong_name in sorted(wrong_suffixes):
                    with self.subTest(branch=branch, wrong_name=wrong_name):
                        with self.assertRaises(executor.ExecutorContractError):
                            executor._validate_container_watchdog_name_binding(
                                wrong_name,
                                labels,
                            )

    def test_container_watchdog_mount_binding_is_exact_and_full_run_bound(
        self,
    ) -> None:
        run_identity = "a" * 64
        branch = "damage"
        run_id = "synthetic-watchdog-mounts-v1"
        run_root = PurePosixPath(
            f"/project/runs/nonpublication/{run_id}"
        )
        labels = {
            executor.OWNER_LABEL: executor.OWNER_VALUE,
            executor.RUN_LABEL: run_identity,
            executor.BRANCH_LABEL: branch,
        }
        binding_name = f"{branch}.tensorrt_cuda.json"
        mounts = {
            "/run/vast/analytics": executor._ipc_runtime_path(
                run_identity
            ).as_posix(),
            f"/run/vast/bindings/{binding_name}": str(
                run_root / "bindings" / binding_name
            ),
            "/run/vast/models/model-source.bin": str(
                run_root / "model_staging" / "model-source.bin"
            ),
            "/run/vast/models/model-engine.bin": str(
                run_root / "model_staging" / "model-engine.bin"
            ),
        }
        self.assertEqual(
            executor._validate_container_watchdog_mount_binding(
                mounts,
                labels,
            ),
            mounts,
        )
        probe_labels = {
            **labels,
            executor.BRANCH_LABEL: "runtime_probe",
        }
        self.assertEqual(
            executor._validate_container_watchdog_mount_binding(
                {},
                probe_labels,
            ),
            {},
        )
        with self.assertRaises(executor.ExecutorContractError):
            executor._validate_container_watchdog_mount_binding(
                mounts,
                probe_labels,
            )

        other_full_run = run_identity[:16] + "b" * 48
        near_misses: list[dict[str, str]] = []
        for removed in mounts:
            near_misses.append(
                {key: value for key, value in mounts.items() if key != removed}
            )
        near_misses.extend(
            [
                {**mounts, "/run/vast/extra": "/project/extra"},
                {
                    **mounts,
                    "/run/vast/analytics": executor._ipc_runtime_path(
                        other_full_run
                    ).as_posix(),
                },
                {
                    **mounts,
                    f"/run/vast/bindings/{binding_name}": str(
                        run_root / "bindings" / "vehicle_type.tensorrt_cuda.json"
                    ),
                },
                {
                    key: value
                    for key, value in mounts.items()
                    if key != "/run/vast/models/model-source.bin"
                }
                | {
                    "/run/vast/models/nested/model-source.bin": str(
                        run_root / "model_staging" / "model-source.bin"
                    )
                },
                {
                    **mounts,
                    "/run/vast/models/model-source.bin": str(
                        run_root / "other" / "model-source.bin"
                    ),
                },
                {
                    **mounts,
                    "/run/vast/models/model-source.bin": str(
                        run_root
                        / "model_staging"
                        / ".."
                        / "model-source.bin"
                    ),
                },
            ]
        )
        for ordinal, candidate in enumerate(near_misses):
            with self.subTest(ordinal=ordinal):
                with self.assertRaises(executor.ExecutorContractError):
                    executor._validate_container_watchdog_mount_binding(
                        candidate,
                        labels,
                    )

    @unittest.skipUnless(os.name == "posix", "POSIX bounded-runner contract")
    def test_bounded_runner_captures_raw_bytes_and_kills_timeout_or_overflow(self) -> None:
        runner = executor._BoundedCommandRunner()
        capture = runner.run(
            [
                sys.executable,
                "-c",
                "import os;os.write(1,b'out\\x00');os.write(2,b'err\\xff')",
            ],
            timeout_seconds=5,
            stdout_limit=16,
            stderr_limit=16,
        )
        self.assertEqual((capture.returncode, capture.stdout, capture.stderr), (0, b"out\x00", b"err\xff"))
        for source, message in (
            ("import os;os.write(1,b'x'*64)", "stdout overflowed"),
            ("import time;time.sleep(30)", "timed out"),
        ):
            with self.subTest(message=message):
                with self.assertRaisesRegex(executor.ExecutorContractError, message):
                    runner.run(
                        [sys.executable, "-c", source],
                        timeout_seconds=0.2,
                        stdout_limit=16,
                        stderr_limit=16,
                    )

    @unittest.skipUnless(os.name == "posix", "POSIX controller-death watchdog contract")
    def test_controller_sigkill_watchdog_revalidates_exact_owned_container_and_removes(self) -> None:
        container_id = "6" * 64
        name = "vast-kpp-v2-np-7777777777777777-probe"
        labels = {
            executor.OWNER_LABEL: executor.OWNER_VALUE,
            executor.RUN_LABEL: "7" * 64,
            executor.BRANCH_LABEL: "runtime_probe",
        }
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            state_path = root / "container.json"
            removal_path = root / "removed"
            ready_path = root / "controller-ready"
            docker_path = root / "fake-docker"
            daemon = self._peercred_daemon(
                daemon_id="1e493309-3767-45fb-9078-05b838bdfd80",
                server_version="29.5.3",
                api_version="1.54",
                name="synthetic-daemon",
            )
            daemon_info_line = executor.canonical_line(
                self._daemon_info_document(daemon)
            )
            executor._write_new(
                state_path,
                executor.canonical_line(
                    self._container_document(
                        container_id=container_id,
                        name=name,
                        labels=labels,
                        state="running",
                        daemon_injected_labels={
                            "desktop.docker.io/wsl-distro": "Ubuntu"
                        },
                    )
                ),
            )
            fake_source = f"""#!{sys.executable}
import json, os, sys
from pathlib import Path
state = Path({str(state_path)!r})
removed = Path({str(removal_path)!r})
args = sys.argv[1:]
if args and args[0].startswith('--host='):
    args = args[1:]
if args[0] == 'info':
    os.write(1, {daemon_info_line!r})
    raise SystemExit(0)
if args[0] == 'version':
    print('{{"Version":"29.5.3","ApiVersion":"1.54","Os":"linux","Arch":"amd64"}}')
    raise SystemExit(0)
if args[:2] == ['container', 'inspect']:
    reference = args[-1]
    if state.exists():
        value = json.loads(state.read_text('ascii'))
        if reference in (value['Id'], value['Name'], value['Name'][1:]):
            print(json.dumps(value, sort_keys=True, separators=(',', ':')))
            raise SystemExit(0)
    os.write(2, f'Error: No such container: {{reference}}\\n'.encode('ascii'))
    raise SystemExit(1)
if args[:2] == ['container', 'ls']:
    if state.exists():
        value = json.loads(state.read_text('ascii'))
        print(json.dumps({{'ID': value['Id'], 'Names': value['Name'][1:]}}, sort_keys=True, separators=(',', ':')))
    raise SystemExit(0)
if args[:2] == ['container', 'rm']:
    value = json.loads(state.read_text('ascii'))
    assert args[-1] == value['Id']
    state.unlink()
    fd = os.open(removed, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.write(fd, value['Id'].encode('ascii'))
    os.close(fd)
    print(value['Id'])
    raise SystemExit(0)
raise SystemExit(97)
""".encode("utf-8")
            executor._write_new(docker_path, fake_source, mode=0o700)
            cli = executor._observe_regular_file(docker_path)
            cleanup_context = self._native_cleanup_mutex(
                str(labels[executor.RUN_LABEL])
            )
            cleanup_mutex = cleanup_context.__enter__()
            self.addCleanup(cleanup_context.__exit__, None, None, None)
            controller_source = f"""
import os, sys, time
from pathlib import Path
sys.path.insert(0, {str(SCRIPTS)!r})
import kpp_legacy_iss_v2_secondary_sensitivity_executor as e
cleanup_mutex = e._CleanupMutexReference({dict(cleanup_mutex.contract)!r})
run_lease = e._acquire_run_lease({str(labels[executor.RUN_LABEL])!r})
handle = e._spawn_container_watchdog(
    container_name={name!r},
    labels={labels!r},
    expected_mounts={{}},
    docker_cli_identity=e.FileIdentity({cli.size_bytes}, {cli.sha256!r}),
    daemon={daemon!r},
    cleanup_mutex=cleanup_mutex,
    run_lease=run_lease,
    docker_cli_path=Path({str(docker_path)!r}),
)
fd = os.open({str(ready_path)!r}, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
os.write(fd, b'ready')
os.close(fd)
time.sleep(600)
"""
            controller = subprocess.Popen(
                [sys.executable, "-B", "-c", controller_source],
                shell=False,
                env={},
                cwd="/",
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                start_new_session=True,
            )
            deadline = time.monotonic() + 10
            while not ready_path.exists() and controller.poll() is None and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(ready_path.exists(), "controller did not arm watchdog")
            os.kill(controller.pid, signal.SIGKILL)
            controller.wait(timeout=10)
            deadline = time.monotonic() + 15
            while not removal_path.exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(removal_path.exists(), "watchdog did not remove owned container")
            self.assertFalse(state_path.exists())
            self.assertEqual(removal_path.read_text("ascii"), container_id)
            reacquired: object | None = None
            deadline = time.monotonic() + 10
            while reacquired is None and time.monotonic() < deadline:
                try:
                    reacquired = executor._acquire_run_lease(
                        str(labels[executor.RUN_LABEL])
                    )
                except executor.ExecutorContractError:
                    time.sleep(0.02)
            self.assertIsNotNone(reacquired, "retained watchdog did not release run lease")
            reacquired.release()

    @unittest.skipUnless(os.name == "posix", "POSIX watchdog readiness contract")
    def test_watchdog_pre_ready_failure_prevents_any_container_create_or_start(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            log_path = root / "calls"
            docker_path = root / "failing-docker"
            source = f"""#!{sys.executable}
import os, sys
fd = os.open({str(log_path)!r}, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
os.write(fd, (' '.join(sys.argv[1:]) + '\\n').encode('ascii'))
os.close(fd)
raise SystemExit(97)
""".encode("utf-8")
            executor._write_new(docker_path, source, mode=0o700)
            cli = executor._observe_regular_file(docker_path)
            daemon = self._peercred_daemon(
                daemon_id="1e493309-3767-45fb-9078-05b838bdfd80",
                server_version="29.5.3",
                api_version="1.54",
                name="synthetic-daemon",
            )
            with self._native_cleanup_mutex(
                "7" * 64
            ) as cleanup_mutex, self._native_run_lease(
                "7" * 64
            ) as run_lease:
                with self.assertRaisesRegex(
                    executor.ExecutorContractError, "before readiness"
                ):
                    executor._spawn_container_watchdog(
                        container_name="vast-kpp-v2-np-7777777777777777-probe",
                        labels={
                            executor.OWNER_LABEL: executor.OWNER_VALUE,
                            executor.RUN_LABEL: "7" * 64,
                            executor.BRANCH_LABEL: "runtime_probe",
                        },
                        expected_mounts={},
                        expected_image_labels={
                            **executor.IMAGE_LABELS,
                            "synthetic.image.label": "bound",
                        },
                        docker_cli_identity=cli,
                        daemon=daemon,
                        cleanup_mutex=cleanup_mutex,
                        run_lease=run_lease,
                        docker_cli_path=docker_path,
                    )
            calls = log_path.read_text("ascii")
            self.assertNotIn(" create ", f" {calls} ")
            self.assertNotIn(" start ", f" {calls} ")

    def test_exact_image_inspect_requires_full_id_platform_entrypoint_and_base_pin(self) -> None:
        expected = executor._validate_image_inspect(self._image_inspect())
        self.assertEqual(expected["image_id"], executor.TENSORRT_IMAGE_ID)

        mutations = (
            ("Id", "sha256:" + "0" * 64),
            ("Os", "windows"),
            ("Architecture", "arm64"),
        )
        for field, value in mutations:
            with self.subTest(field=field):
                document = self._image_inspect()
                document[field] = value
                with self.assertRaises(executor.ExecutorContractError):
                    executor._validate_image_inspect(document)

        document = self._image_inspect()
        document["Config"]["Labels"][
            "org.vast.analytics_worker.base_image_id"
        ] = "sha256:" + "f" * 64
        with self.assertRaises(executor.ExecutorContractError):
            executor._validate_image_inspect(document)

    def test_created_container_inspect_rejects_privilege_extra_mount_and_wrong_gpu(self) -> None:
        run_identity = "a" * 64
        branch = "plate_number"
        run_root = PurePosixPath(
            "/project/runs/nonpublication/synthetic-container-inspect-v1"
        )
        name = f"vast-kpp-v2-np-{run_identity[:16]}-{branch}"
        container_id = "b" * 64
        labels = {
            executor.OWNER_LABEL: executor.OWNER_VALUE,
            executor.RUN_LABEL: run_identity,
            executor.BRANCH_LABEL: branch,
        }
        binding_name = f"{branch}.tensorrt_cuda.json"
        sources = {
            f"/run/vast/bindings/{binding_name}": (
                run_root / "bindings" / binding_name
            ),
            "/run/vast/models/resnet18-v1-7.onnx": (
                run_root / "model_staging" / "resnet18-v1-7.onnx"
            ),
            "/run/vast/models/resnet18-v1-7.engine": (
                run_root / "model_staging" / "resnet18-v1-7.engine"
            ),
            "/run/vast/analytics": PurePosixPath(
                executor._ipc_runtime_path(run_identity).as_posix()
            ),
        }
        document = {
            "Id": container_id,
            "Name": "/" + name,
            "Image": executor.TENSORRT_IMAGE_ID,
            "Config": {
                "Image": executor.TENSORRT_IMAGE_ID,
                "User": f"{executor.CONTAINER_UID}:{executor.CONTAINER_GID}",
                "Entrypoint": [executor.TENSORRT_ENTRYPOINT],
                "Cmd": [
                    "--binding",
                    f"/run/vast/bindings/{binding_name}",
                    "--socket",
                    "/run/vast/analytics/plate_number.sock",
                    "--max-requests",
                    "2",
                    "--gpu-device-index",
                    "0",
                ],
                "Labels": {
                    "org.vast.analytics_worker.base_image_id": executor.TENSORRT_BASE_IMAGE_ID,
                    "org.vast.analytics_worker.engine": "tensorrt_cuda",
                    **labels,
                },
            },
            "HostConfig": {
                "Binds": None,
                "Mounts": [
                    {
                        "Type": "bind",
                        "Source": str(source),
                        "Target": destination,
                        "ReadOnly": True,
                    }
                    for destination, source in sources.items()
                ],
                "NetworkMode": "none",
                "ReadonlyRootfs": True,
                "CapDrop": ["ALL"],
                "SecurityOpt": ["no-new-privileges"],
                "Privileged": False,
                "PidMode": "",
                "IpcMode": "private",
                "Runtime": "runc",
                "Memory": executor.CONTAINER_MEMORY_BYTES,
                "MemorySwap": executor.CONTAINER_MEMORY_BYTES,
                "NanoCpus": executor.CONTAINER_NANO_CPUS,
                "PidsLimit": executor.CONTAINER_PIDS_LIMIT,
                "RestartPolicy": {"Name": "no", "MaximumRetryCount": 0},
                "AutoRemove": False,
                "Ulimits": [{"Name": "nofile", "Hard": 1024, "Soft": 1024}],
                "DeviceRequests": [
                    {
                        "Driver": "",
                        "Count": 0,
                        "DeviceIDs": [executor.TENSORRT_GPU_UUID],
                        "Capabilities": [["gpu"]],
                        "Options": {},
                    }
                ],
            },
            "Mounts": [
                {
                    "Type": "bind",
                    "Source": str(source),
                    "Destination": destination,
                    "Mode": "ro",
                    "RW": False,
                    "Propagation": "rprivate",
                }
                for destination, source in sources.items()
            ],
            "State": {"Status": "created", "Running": False, "Pid": 0},
        }
        executor._validate_container_inspect(
            document,
            container_id=container_id,
            container_name=name,
            labels=labels,
            expected_mounts=sources,
            expected_state="created",
        )

        for mutation in ("privileged", "gpu", "mount", "ipc_rw"):
            with self.subTest(mutation=mutation):
                import copy

                changed = copy.deepcopy(document)
                if mutation == "privileged":
                    changed["HostConfig"]["Privileged"] = True
                elif mutation == "gpu":
                    changed["HostConfig"]["DeviceRequests"][0]["DeviceIDs"] = [
                        "GPU-11111111-1111-1111-1111-111111111111"
                    ]
                elif mutation == "mount":
                    changed["Mounts"].append(
                        {
                            "Source": "/var/run/docker.sock",
                            "Destination": "/var/run/docker.sock",
                            "RW": True,
                        }
                    )
                else:
                    ipc_mount = next(
                        item
                        for item in changed["Mounts"]
                        if item["Destination"] == "/run/vast/analytics"
                    )
                    ipc_mount["Mode"] = ""
                    ipc_mount["RW"] = True
                with self.assertRaises(executor.ExecutorContractError):
                    executor._validate_container_inspect(
                        changed,
                        container_id=container_id,
                        container_name=name,
                        labels=labels,
                        expected_mounts=sources,
                        expected_state="created",
                    )

        closed_mutations = ("extra_label", "restart", "mount_type", "gpu_driver")
        for mutation in closed_mutations:
            with self.subTest(closed=mutation):
                import copy

                changed = copy.deepcopy(document)
                if mutation == "extra_label":
                    changed["Config"]["Labels"]["unapproved"] = "true"
                elif mutation == "restart":
                    changed["HostConfig"]["RestartPolicy"]["Name"] = "always"
                elif mutation == "mount_type":
                    changed["Mounts"][0]["Type"] = "volume"
                else:
                    changed["HostConfig"]["DeviceRequests"][0]["Driver"] = "unexpected"
                with self.assertRaises(executor.ExecutorContractError):
                    executor._validate_container_inspect(
                        changed,
                        container_id=container_id,
                        container_name=name,
                        labels=labels,
                        expected_mounts=sources,
                        expected_state="created",
                    )

    def test_real_docker29_four_worker_readonly_mount_projection_is_closed_and_cross_bound(
        self,
    ) -> None:
        for branch, (container_id, _sha256, _size) in V2_CONTAINER_FIXTURES.items():
            with self.subTest(branch=branch, mode="docker29-empty"):
                document, mounts, image_labels = self._v2_mount_fixture(branch)
                labels = {
                    executor.OWNER_LABEL: executor.OWNER_VALUE,
                    executor.RUN_LABEL: V2_RUN_IDENTITY,
                    executor.BRANCH_LABEL: branch,
                }
                executor._validate_container_inspect(
                    document,
                    container_id=container_id,
                    container_name=f"vast-kpp-v2-np-{V2_RUN_IDENTITY[:16]}-{branch}",
                    labels=labels,
                    expected_mounts=mounts,
                    expected_state="created",
                    expected_image_labels=image_labels,
                )
                legacy_projection = copy.deepcopy(document)
                for item in legacy_projection["Mounts"]:
                    item["Mode"] = "ro"
                executor._validate_container_inspect(
                    legacy_projection,
                    container_id=container_id,
                    container_name=f"vast-kpp-v2-np-{V2_RUN_IDENTITY[:16]}-{branch}",
                    labels=labels,
                    expected_mounts=mounts,
                    expected_state="created",
                    expected_image_labels=image_labels,
                )

        branch = "plate_number"
        container_id = V2_CONTAINER_FIXTURES[branch][0]
        baseline, mounts, image_labels = self._v2_mount_fixture(branch)
        labels = {
            executor.OWNER_LABEL: executor.OWNER_VALUE,
            executor.RUN_LABEL: V2_RUN_IDENTITY,
            executor.BRANCH_LABEL: branch,
        }

        other_run_identity = V2_RUN_IDENTITY[:16] + (
            "0" * 48
            if V2_RUN_IDENTITY[16:] != "0" * 48
            else "1" * 48
        )
        cross_run_mounts = dict(mounts)
        cross_run_mounts["/run/vast/analytics"] = PurePosixPath(
            executor._ipc_runtime_path(other_run_identity).as_posix()
        )
        cross_run_document = copy.deepcopy(baseline)
        for raw_mount in cross_run_document["HostConfig"]["Mounts"]:
            if raw_mount["Target"] == "/run/vast/analytics":
                raw_mount["Source"] = str(
                    cross_run_mounts["/run/vast/analytics"]
                )
        for raw_mount in cross_run_document["Mounts"]:
            if raw_mount["Destination"] == "/run/vast/analytics":
                raw_mount["Source"] = str(
                    cross_run_mounts["/run/vast/analytics"]
                )
        with self.assertRaisesRegex(
            executor.ExecutorContractError,
            "analytics mount run identity drifted",
        ):
            executor._validate_container_inspect(
                cross_run_document,
                container_id=container_id,
                container_name=(
                    f"vast-kpp-v2-np-{V2_RUN_IDENTITY[:16]}-{branch}"
                ),
                labels=labels,
                expected_mounts=cross_run_mounts,
                expected_state="created",
                expected_image_labels=image_labels,
            )

        def rejected(document: dict[str, object], label: str) -> None:
            with self.subTest(rejected=label):
                with self.assertRaises(executor.ExecutorContractError):
                    executor._validate_container_inspect(
                        document,
                        container_id=container_id,
                        container_name=f"vast-kpp-v2-np-{V2_RUN_IDENTITY[:16]}-{branch}",
                        labels=labels,
                        expected_mounts=mounts,
                        expected_state="created",
                        expected_image_labels=image_labels,
                    )

        mixed = copy.deepcopy(baseline)
        mixed["Mounts"][0]["Mode"] = "ro"
        rejected(mixed, "mixed wire families")
        for value in (None, False, "rw", "readonly"):
            changed = copy.deepcopy(baseline)
            changed["Mounts"][0]["Mode"] = value
            rejected(changed, f"runtime mode {value!r}")
        changed = copy.deepcopy(baseline)
        del changed["Mounts"][0]["Mode"]
        rejected(changed, "runtime mode missing")
        runtime_mutations = {
            "runtime type": ("Type", "volume"),
            "runtime source type": ("Source", 7),
            "runtime destination type": ("Destination", 7),
            "runtime rw": ("RW", True),
            "runtime rw integer": ("RW", 0),
            "runtime propagation": ("Propagation", "shared"),
        }
        for label, (field, value) in runtime_mutations.items():
            changed = copy.deepcopy(baseline)
            changed["Mounts"][0][field] = value
            rejected(changed, label)
        changed = copy.deepcopy(baseline)
        changed["Mounts"][0]["Extra"] = "forbidden"
        rejected(changed, "runtime extra field")
        changed = copy.deepcopy(baseline)
        changed["Mounts"].append(copy.deepcopy(changed["Mounts"][0]))
        rejected(changed, "runtime duplicate mount")
        changed = copy.deepcopy(baseline)
        changed["Mounts"].pop()
        rejected(changed, "runtime missing mount")
        changed = copy.deepcopy(baseline)
        changed["Mounts"][0]["Source"] += ".other"
        rejected(changed, "runtime expected-source drift")

        for binds in ([], ["/host:/container:ro"], "bad"):
            changed = copy.deepcopy(baseline)
            changed["HostConfig"]["Binds"] = binds
            rejected(changed, f"legacy binds {binds!r}")
        changed = copy.deepcopy(baseline)
        del changed["HostConfig"]["Binds"]
        rejected(changed, "legacy binds missing")
        host_mutations = {
            "host type": ("Type", "volume"),
            "host source type": ("Source", 7),
            "host target type": ("Target", 7),
            "host readonly false": ("ReadOnly", False),
            "host readonly integer": ("ReadOnly", 1),
        }
        for label, (field, value) in host_mutations.items():
            changed = copy.deepcopy(baseline)
            changed["HostConfig"]["Mounts"][0][field] = value
            rejected(changed, label)
        changed = copy.deepcopy(baseline)
        changed["HostConfig"]["Mounts"][0]["Extra"] = "forbidden"
        rejected(changed, "host extra field")
        changed = copy.deepcopy(baseline)
        changed["HostConfig"]["Mounts"].append(
            copy.deepcopy(changed["HostConfig"]["Mounts"][0])
        )
        rejected(changed, "host duplicate mount")
        changed = copy.deepcopy(baseline)
        changed["HostConfig"]["Mounts"].pop()
        rejected(changed, "host missing mount")
        changed = copy.deepcopy(baseline)
        changed["HostConfig"]["Mounts"][0]["Source"] += ".other"
        rejected(changed, "host/runtime source cross-pair")
        changed = copy.deepcopy(baseline)
        changed["HostConfig"]["Mounts"][0]["Target"] += ".other"
        rejected(changed, "host/runtime target cross-pair")
        changed = copy.deepcopy(baseline)
        del changed["HostConfig"]["Mounts"]
        rejected(changed, "host mounts missing")

    def test_real_docker29_zero_mount_probe_projection_is_closed(self) -> None:
        container_id = V3_PROBE_FIXTURE[0]
        name = f"vast-kpp-v2-np-{V3_RUN_IDENTITY[:16]}-probe"
        baseline, labels, image_labels = self._v3_zero_mount_probe_fixture()

        def validate(document: dict[str, object]) -> None:
            executor._validate_container_inspect(
                document,
                container_id=container_id,
                container_name=name,
                labels=labels,
                expected_mounts={},
                expected_state="created",
                expected_image_labels=image_labels,
            )

        def rejected(document: dict[str, object], label: str) -> None:
            with self.subTest(rejected=label):
                with self.assertRaises(executor.ExecutorContractError):
                    validate(document)

        validate(baseline)
        synthetic_empty = copy.deepcopy(baseline)
        synthetic_empty["HostConfig"]["Mounts"] = []
        validate(synthetic_empty)

        for value in (None, (), {}, "", [None]):
            changed = copy.deepcopy(baseline)
            changed["HostConfig"]["Mounts"] = value
            rejected(changed, f"host mounts explicit {value!r}")

        for value in (None, (), {}, ""):
            changed = copy.deepcopy(baseline)
            changed["Mounts"] = value
            rejected(changed, f"runtime mounts {value!r}")
        changed = copy.deepcopy(baseline)
        del changed["Mounts"]
        rejected(changed, "runtime mounts missing")
        changed = copy.deepcopy(baseline)
        changed["Mounts"] = [
            {
                "Type": "bind",
                "Source": "/tmp/other",
                "Destination": "/run/vast/analytics",
                "Mode": "ro",
                "RW": False,
                "Propagation": "rprivate",
            }
        ]
        rejected(changed, "runtime nonempty while host absent")

        for value in ([], ["/tmp:/run/vast/analytics:ro"], "bad"):
            changed = copy.deepcopy(baseline)
            changed["HostConfig"]["Binds"] = value
            rejected(changed, f"legacy binds {value!r}")
        changed = copy.deepcopy(baseline)
        del changed["HostConfig"]["Binds"]
        rejected(changed, "legacy binds missing")

        with self.assertRaises(executor.ExecutorContractError):
            executor._validate_container_inspect(
                baseline,
                container_id=container_id,
                container_name=name,
                labels=labels,
                expected_mounts={
                    "/run/vast/analytics": Path("/tmp/unexpected-required-mount")
                },
                expected_state="created",
                expected_image_labels=image_labels,
            )

        create_command = executor._build_probe_create_command(
            container_name=name,
            labels=labels,
        )
        self.assertFalse(
            any(token == "--mount" or token.startswith("--mount=") for token in create_command)
        )

    def test_real_docker29_zero_mount_probe_passes_postcreate_and_parent_cleanup(
        self,
    ) -> None:
        document, labels, image_labels = self._v3_zero_mount_probe_fixture()
        container_id = V3_PROBE_FIXTURE[0]
        name = f"vast-kpp-v2-np-{V3_RUN_IDENTITY[:16]}-probe"
        created = False
        removed = False
        calls: list[tuple[str, ...]] = []

        class Runner:
            def run(
                runner_self,
                argv: list[str],
                *,
                timeout_seconds: float,
                stdout_limit: int,
                stderr_limit: int,
            ) -> executor.CommandCapture:
                nonlocal created, removed
                del runner_self, timeout_seconds, stdout_limit, stderr_limit
                command = tuple(argv)
                calls.append(command)
                if "inspect" in command:
                    reference = command[-1]
                    if created and not removed and reference in {name, container_id}:
                        return executor.CommandCapture(
                            0, executor.canonical_line(document), b""
                        )
                    return executor.CommandCapture(
                        1,
                        b"\n",
                        f"Error response from daemon: No such container: {reference}\n".encode(
                            "ascii"
                        ),
                    )
                if "create" in command:
                    self.assertFalse(created)
                    created = True
                    return executor.CommandCapture(
                        0, (container_id + "\n").encode("ascii"), b""
                    )
                if "start" in command:
                    return executor.CommandCapture(
                        1, b"", b"synthetic start gate stop\n"
                    )
                if "rm" in command:
                    self.assertEqual(command[-1], container_id)
                    removed = True
                    return executor.CommandCapture(
                        0, (container_id + "\n").encode("ascii"), b""
                    )
                if "ls" in command:
                    return executor.CommandCapture(0, b"", b"")
                raise AssertionError(command)

        with self.assertRaisesRegex(
            executor.ExecutorContractError, "container start failed"
        ):
            executor._run_owned_container_transaction(
                runner=Runner(),
                create_command=executor._build_probe_create_command(
                    container_name=name,
                    labels=labels,
                ),
                container_name=name,
                labels=labels,
                expected_mounts={},
                after_start=lambda _container_id: None,
                cleanup_mutex=executor._NullCleanupMutex(),
                expected_image_labels=image_labels,
            )
        self.assertTrue(removed)
        self.assertEqual(
            [command[-1] for command in calls if "rm" in command],
            [container_id],
        )
        self.assertFalse(any("wait" in command or "logs" in command for command in calls))

    def test_nonzero_create_capture_remains_dispatch_ambiguous_without_terminal_marker(
        self,
    ) -> None:
        _document, labels, image_labels = self._v3_zero_mount_probe_fixture()
        name = f"vast-kpp-v2-np-{V3_RUN_IDENTITY[:16]}-probe"
        markers: list[str] = []

        class Runner:
            def run(
                runner_self,
                argv: list[str],
                *,
                timeout_seconds: float,
                stdout_limit: int,
                stderr_limit: int,
            ) -> executor.CommandCapture:
                del runner_self, timeout_seconds, stdout_limit, stderr_limit
                command = tuple(argv)
                if "create" in command:
                    return executor.CommandCapture(
                        1,
                        b"",
                        b"synthetic transport disconnect after POST\n",
                    )
                if "inspect" in command:
                    reference = command[-1]
                    return executor.CommandCapture(
                        1,
                        b"",
                        f"Error: No such container: {reference}\n".encode(),
                    )
                if "ls" in command:
                    return executor.CommandCapture(0, b"", b"")
                raise AssertionError(command)

        class Watchdog:
            def mark_create_dispatch(self) -> None:
                markers.append("D")

            def mark_create_terminal(self) -> None:
                markers.append("T")

            def complete(self) -> None:
                markers.append("C")

            def abort(self) -> None:
                markers.append("abort")

        with self.assertRaises(executor._DockerOperationError):
            executor._run_owned_container_transaction(
                runner=Runner(),
                create_command=executor._build_probe_create_command(
                    container_name=name,
                    labels=labels,
                ),
                container_name=name,
                labels=labels,
                expected_mounts={},
                after_start=lambda _container_id: None,
                cleanup_mutex=executor._NullCleanupMutex(),
                watchdog_factory=lambda **_kwargs: Watchdog(),
                expected_image_labels=image_labels,
            )
        self.assertEqual(markers, ["D", "abort"])

    def test_nonzero_create_with_real_guardian_detaches_retained_owner(self) -> None:
        _document, labels, image_labels = self._v3_zero_mount_probe_fixture()
        name = f"vast-kpp-v2-np-{V3_RUN_IDENTITY[:16]}-probe"

        class Runner:
            def run(
                runner_self,
                argv: list[str],
                *,
                timeout_seconds: float,
                stdout_limit: int,
                stderr_limit: int,
            ) -> executor.CommandCapture:
                del runner_self, timeout_seconds, stdout_limit, stderr_limit
                command = tuple(argv)
                if "create" in command:
                    return executor.CommandCapture(
                        1,
                        b"",
                        b"synthetic transport disconnect after POST\n",
                    )
                if "inspect" in command:
                    reference = command[-1]
                    return executor.CommandCapture(
                        1,
                        b"",
                        f"Error: No such container: {reference}\n".encode(),
                    )
                if "ls" in command:
                    return executor.CommandCapture(0, b"", b"")
                raise AssertionError(command)

        read_fd, write_fd = os.pipe()
        process = mock.Mock()
        process.poll.return_value = None
        guardian = executor._ContainerWatchdogProcess(
            process=process,
            control_fd=write_fd,
            unresolved_operation_contract={"synthetic": True},
        )
        try:
            with self.assertRaises(executor._DockerOperationError):
                executor._run_owned_container_transaction(
                    runner=Runner(),
                    create_command=executor._build_probe_create_command(
                        container_name=name,
                        labels=labels,
                    ),
                    container_name=name,
                    labels=labels,
                    expected_mounts={},
                    after_start=lambda _container_id: None,
                    cleanup_mutex=executor._NullCleanupMutex(),
                    watchdog_factory=lambda **_kwargs: guardian,
                    expected_image_labels=image_labels,
                )
            self.assertEqual(os.read(read_fd, 2), b"D")
            self.assertEqual(os.read(read_fd, 1), b"")
            self.assertTrue(guardian.ambiguous_owner_detached)
            self.assertTrue(guardian.cleanup_ownership_retained)
            process.poll.assert_called_once_with()
            process.wait.assert_not_called()
            process.kill.assert_not_called()
        finally:
            os.close(read_fd)

    @unittest.skipUnless(os.name == "posix", "POSIX container watchdog recovery")
    def test_real_docker29_zero_mount_probe_passes_watchdog_recovery(self) -> None:
        document, labels, image_labels = self._v3_zero_mount_probe_fixture()
        container_id = V3_PROBE_FIXTURE[0]
        name = f"vast-kpp-v2-np-{V3_RUN_IDENTITY[:16]}-probe"
        daemon = self._peercred_daemon(
            daemon_id="1e493309-3767-45fb-9078-05b838bdfd80",
            server_version="29.7.2",
            api_version="1.55",
            name="synthetic-daemon",
        )
        daemon_info_line = executor.canonical_line(
            self._daemon_info_document(daemon)
        )
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            state_path = root / "container.json"
            removal_path = root / "removed"
            docker_path = root / "fake-docker"
            executor._write_new(state_path, executor.canonical_line(document))
            fake_source = f"""#!{sys.executable}
import json, os, sys
from pathlib import Path
state = Path({str(state_path)!r})
removed = Path({str(removal_path)!r})
args = sys.argv[1:]
if args and args[0].startswith('--host='):
    args = args[1:]
if args[0] == 'info':
    os.write(1, {daemon_info_line!r})
    raise SystemExit(0)
if args[0] == 'version':
    print('{{"Version":"29.7.2","ApiVersion":"1.55","Os":"linux","Arch":"amd64"}}')
    raise SystemExit(0)
if args[:2] == ['container', 'inspect']:
    reference = args[-1]
    if state.exists():
        value = json.loads(state.read_text('ascii'))
        if reference in (value['Id'], value['Name'], value['Name'][1:]):
            print(json.dumps(value, sort_keys=True, separators=(',', ':')))
            raise SystemExit(0)
    print()
    os.write(2, f'Error response from daemon: No such container: {{reference}}\\n'.encode('ascii'))
    raise SystemExit(1)
if args[:2] == ['container', 'ls']:
    if state.exists():
        value = json.loads(state.read_text('ascii'))
        print(json.dumps({{'ID': value['Id'], 'Names': value['Name'][1:]}}, sort_keys=True, separators=(',', ':')))
    raise SystemExit(0)
if args[:2] == ['container', 'rm']:
    value = json.loads(state.read_text('ascii'))
    assert args[-1] == value['Id']
    state.unlink()
    fd = os.open(removed, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.write(fd, value['Id'].encode('ascii'))
    os.close(fd)
    print(value['Id'])
    raise SystemExit(0)
raise SystemExit(97)
""".encode("utf-8")
            executor._write_new(docker_path, fake_source, mode=0o700)
            cli = executor._observe_regular_file(docker_path)
            with self._native_cleanup_mutex(
                V3_RUN_IDENTITY
            ) as cleanup_mutex, self._native_run_lease(
                V3_RUN_IDENTITY
            ) as run_lease:
                watchdog = executor._spawn_container_watchdog(
                    container_name=name,
                    labels=labels,
                    expected_mounts={},
                    expected_image_labels=image_labels,
                    docker_cli_identity=cli,
                    daemon=daemon,
                    cleanup_mutex=cleanup_mutex,
                    run_lease=run_lease,
                    docker_cli_path=docker_path,
                )
                watchdog.abort()
                self.assertTrue(watchdog.closed)
            self.assertFalse(state_path.exists())
            self.assertEqual(removal_path.read_text("ascii"), container_id)

    def test_real_docker29_zero_mount_probe_passes_stale_reaper(self) -> None:
        document, _labels, image_labels = self._v3_zero_mount_probe_fixture()
        container_id = V3_PROBE_FIXTURE[0]
        probe_name = f"vast-kpp-v2-np-{V3_RUN_IDENTITY[:16]}-probe"
        removed = False
        calls: list[tuple[str, ...]] = []

        class Runner:
            def run(
                runner_self,
                argv: list[str],
                *,
                timeout_seconds: float,
                stdout_limit: int,
                stderr_limit: int,
            ) -> executor.CommandCapture:
                nonlocal removed
                del runner_self, timeout_seconds, stdout_limit, stderr_limit
                command = tuple(argv)
                calls.append(command)
                if "inspect" in command:
                    reference = command[-1]
                    if not removed and reference in {probe_name, container_id}:
                        return executor.CommandCapture(
                            0, executor.canonical_line(document), b""
                        )
                    return executor.CommandCapture(
                        1,
                        b"\n",
                        f"Error response from daemon: No such container: {reference}\n".encode(
                            "ascii"
                        ),
                    )
                if "ls" in command:
                    if removed:
                        return executor.CommandCapture(0, b"", b"")
                    return executor.CommandCapture(
                        0,
                        executor.canonical_line(
                            {"ID": container_id, "Names": probe_name}
                        ),
                        b"",
                    )
                if "rm" in command:
                    self.assertEqual(command[-1], container_id)
                    removed = True
                    return executor.CommandCapture(
                        0, (container_id + "\n").encode("ascii"), b""
                    )
                raise AssertionError(command)

        bindings: dict[str, dict[str, object]] = {}
        source_paths: dict[str, Path] = {}
        engine_paths: dict[str, Path] = {}
        identities: dict[str, executor.FileIdentity] = {}
        for branch in pilot.BRANCHES:
            bindings[branch] = {
                "source_path": f"/run/vast/models/{branch}.onnx",
                "engine_path": f"/run/vast/models/{branch}.engine",
            }
            source_paths[branch] = Path(f"/source/{branch}.onnx")
            engine_paths[branch] = Path(f"/engine/{branch}.engine")
            identities[branch] = executor.FileIdentity(
                1, hashlib.sha256(branch.encode("ascii")).hexdigest()
            )
        inventory = executor.BindingInventory(
            bindings=bindings,
            source_paths=source_paths,
            engine_paths=engine_paths,
            source_identities=identities,
            engine_identities=identities,
            manifest_identity_sha256="1" * 64,
            execution_config_identity_sha256="2" * 64,
        )
        with tempfile.TemporaryDirectory() as raw:
            reaped, existed = executor._reap_stale_execution(
                runner=Runner(),
                project_root=Path(raw),
                run_id=V3_RUN_ID,
                run_identity=V3_RUN_IDENTITY,
                bindings=inventory,
                cleanup_mutex=executor._NullCleanupMutex(),
                expected_image_labels=image_labels,
            )
        self.assertFalse(existed)
        self.assertTrue(removed)
        self.assertEqual(
            reaped,
            [hashlib.sha256(container_id.encode("ascii")).hexdigest()],
        )
        self.assertEqual(
            [command[-1] for command in calls if "rm" in command],
            [container_id],
        )
        self.assertFalse(
            any("create" in command or "start" in command for command in calls)
        )

        class RecoveryGate(BaseException):
            pass

        removed = False
        calls.clear()
        gpu_probe_seen = False

        def gpu_probe(**_kwargs: object) -> dict[str, object]:
            nonlocal gpu_probe_seen
            self.assertTrue(removed, "stale probe was not destroyed before GPU probe")
            self.assertEqual(
                [command[-1] for command in calls if "rm" in command],
                [container_id],
            )
            self.assertFalse(
                any("create" in command or "start" in command for command in calls)
            )
            gpu_probe_seen = True
            raise RecoveryGate()

        dependencies = executor._ExecutorDependencies(
            platform_name="posix",
            environment={},
            observe_docker_cli=mock.Mock(),
            command_runner=Runner(),
            planner_builder=mock.Mock(),
            gpu_probe=gpu_probe,
            observe_file=mock.Mock(),
            worker_runner=mock.Mock(),
            stale_reaper=executor._reap_stale_execution,
        )
        with tempfile.TemporaryDirectory() as raw:
            project_root = Path(raw)
            attempt_requests = [
                {
                    "request_id": f"recovery-{branch}-{codec}",
                    "branch": branch,
                    "codec": codec,
                }
                for branch in pilot.BRANCHES
                for codec in pilot.CODECS
            ]
            with self.assertRaises(RecoveryGate):
                executor._execute_mutating_phase(
                    dependencies=dependencies,
                    image={"labels": image_labels},
                    daemon={},
                    cli=executor.FileIdentity(44_986_088, "3" * 64),
                    run_identity=V3_RUN_IDENTITY,
                    role="secondary",
                    project_root=project_root,
                    run_id=V3_RUN_ID,
                    plan={},
                    requests=attempt_requests,
                    bindings=inventory,
                    payloads=executor.TensorInventory(
                        payloads={}, bundle_observations=[]
                    ),
                    model_file_observations={},
                    expected_daemon_id="unused",
                    expected_daemon_server_version="unused",
                    expected_daemon_api_version="unused",
                    cleanup_mutex=executor._NullCleanupMutex(),
                    run_lease=executor._NullRunLease(),
                    container_registry=executor._OwnedContainerRegistry(
                        V3_RUN_IDENTITY
                    ),
                    attempt_context=executor._ExecutionAttemptContext(
                        run_id=V3_RUN_ID,
                        run_identity=V3_RUN_IDENTITY,
                        role="secondary",
                        requests=attempt_requests,
                    ),
                )
            self.assertFalse(
                (project_root / "runs" / "nonpublication" / V3_RUN_ID).exists()
            )
        self.assertTrue(gpu_probe_seen)

    def test_real_docker29_four_worker_fixtures_pass_parent_cleanup(self) -> None:
        for branch, (container_id, _sha256, _size) in V2_CONTAINER_FIXTURES.items():
            with self.subTest(branch=branch):
                document, mounts, image_labels = self._v2_mount_fixture(branch)
                labels = {
                    executor.OWNER_LABEL: executor.OWNER_VALUE,
                    executor.RUN_LABEL: V2_RUN_IDENTITY,
                    executor.BRANCH_LABEL: branch,
                }
                removed = False
                calls: list[tuple[str, ...]] = []

                class Runner:
                    def run(
                        runner_self,
                        argv: list[str],
                        *,
                        timeout_seconds: float,
                        stdout_limit: int,
                        stderr_limit: int,
                    ) -> executor.CommandCapture:
                        nonlocal removed
                        del runner_self, timeout_seconds, stdout_limit, stderr_limit
                        command = tuple(argv)
                        calls.append(command)
                        if "inspect" in command:
                            reference = command[-1]
                            if not removed:
                                return executor.CommandCapture(
                                    0, executor.canonical_line(document), b""
                                )
                            return executor.CommandCapture(
                                1,
                                b"\n",
                                f"Error response from daemon: No such container: {reference}\n".encode(
                                    "ascii"
                                ),
                            )
                        if "rm" in command:
                            self.assertEqual(command[-1], container_id)
                            removed = True
                            return executor.CommandCapture(
                                0, (container_id + "\n").encode("ascii"), b""
                            )
                        if "ls" in command:
                            return executor.CommandCapture(0, b"", b"")
                        raise AssertionError(command)

                executor._cleanup_owned_container(
                    runner=Runner(),
                    container_id=container_id,
                    container_name=f"vast-kpp-v2-np-{V2_RUN_IDENTITY[:16]}-{branch}",
                    labels=labels,
                    expected_mounts=mounts,
                    cleanup_mutex=executor._NullCleanupMutex(),
                    expected_image_labels=image_labels,
                )
                self.assertTrue(removed)
                self.assertEqual(
                    [command[-1] for command in calls if "rm" in command],
                    [container_id],
                )

    @unittest.skipUnless(os.name == "posix", "POSIX container watchdog recovery")
    def test_real_docker29_four_worker_fixtures_pass_watchdog_recovery(self) -> None:
        daemon = self._peercred_daemon(
            daemon_id="1e493309-3767-45fb-9078-05b838bdfd80",
            server_version="29.7.2",
            api_version="1.55",
            name="synthetic-daemon",
        )
        daemon_info_line = executor.canonical_line(
            self._daemon_info_document(daemon)
        )
        for branch, (container_id, _sha256, _size) in V2_CONTAINER_FIXTURES.items():
            with self.subTest(branch=branch), tempfile.TemporaryDirectory() as raw:
                document, mounts, image_labels = self._v2_mount_fixture(branch)
                labels = {
                    executor.OWNER_LABEL: executor.OWNER_VALUE,
                    executor.RUN_LABEL: V2_RUN_IDENTITY,
                    executor.BRANCH_LABEL: branch,
                }
                root = Path(raw)
                state_path = root / "container.json"
                removal_path = root / "removed"
                docker_path = root / "fake-docker"
                executor._write_new(
                    state_path,
                    executor.canonical_line(document),
                )
                fake_source = f"""#!{sys.executable}
import json, os, sys
from pathlib import Path
state = Path({str(state_path)!r})
removed = Path({str(removal_path)!r})
args = sys.argv[1:]
if args and args[0].startswith('--host='):
    args = args[1:]
if args[0] == 'info':
    os.write(1, {daemon_info_line!r})
    raise SystemExit(0)
if args[0] == 'version':
    print('{{"Version":"29.7.2","ApiVersion":"1.55","Os":"linux","Arch":"amd64"}}')
    raise SystemExit(0)
if args[:2] == ['container', 'inspect']:
    reference = args[-1]
    if state.exists():
        value = json.loads(state.read_text('ascii'))
        if reference in (value['Id'], value['Name'], value['Name'][1:]):
            print(json.dumps(value, sort_keys=True, separators=(',', ':')))
            raise SystemExit(0)
    os.write(2, f'Error: No such container: {{reference}}\\n'.encode('ascii'))
    raise SystemExit(1)
if args[:2] == ['container', 'ls']:
    if state.exists():
        value = json.loads(state.read_text('ascii'))
        print(json.dumps({{'ID': value['Id'], 'Names': value['Name'][1:]}}, sort_keys=True, separators=(',', ':')))
    raise SystemExit(0)
if args[:2] == ['container', 'rm']:
    value = json.loads(state.read_text('ascii'))
    assert args[-1] == value['Id']
    state.unlink()
    fd = os.open(removed, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.write(fd, value['Id'].encode('ascii'))
    os.close(fd)
    print(value['Id'])
    raise SystemExit(0)
raise SystemExit(97)
""".encode("utf-8")
                executor._write_new(docker_path, fake_source, mode=0o700)
                cli = executor._observe_regular_file(docker_path)
                with self._native_cleanup_mutex(
                    V2_RUN_IDENTITY
                ) as cleanup_mutex, self._native_run_lease(
                    V2_RUN_IDENTITY
                ) as run_lease:
                    watchdog = executor._spawn_container_watchdog(
                        container_name=f"vast-kpp-v2-np-{V2_RUN_IDENTITY[:16]}-{branch}",
                        labels=labels,
                        expected_mounts=mounts,
                        expected_image_labels=image_labels,
                        docker_cli_identity=cli,
                        daemon=daemon,
                        cleanup_mutex=cleanup_mutex,
                        run_lease=run_lease,
                        docker_cli_path=docker_path,
                    )
                    watchdog.abort()
                    self.assertTrue(watchdog.closed)
                self.assertFalse(state_path.exists())
                self.assertEqual(removal_path.read_text("ascii"), container_id)

    def test_container_inspect_accepts_only_exact_docker_desktop_wsl_label_injection(
        self,
    ) -> None:
        key = "desktop.docker.io/wsl-distro"
        value = "Ubuntu"
        container_id = "8" * 64
        name = "vast-kpp-v2-np-0123456789abcdef-probe"
        labels = {
            executor.OWNER_LABEL: executor.OWNER_VALUE,
            executor.RUN_LABEL: "9" * 64,
            executor.BRANCH_LABEL: "runtime_probe",
        }

        baseline = self._container_document(
            container_id=container_id,
            name=name,
            labels=labels,
            state="created",
        )
        exact_docker_desktop = self._container_document(
            container_id=container_id,
            name=name,
            labels=labels,
            state="created",
            daemon_injected_labels={key: value},
        )
        for document in (baseline, exact_docker_desktop):
            with self.subTest(accepted_labels=document["Config"]["Labels"]):
                executor._validate_container_inspect(
                    document,
                    container_id=container_id,
                    container_name=name,
                    labels=labels,
                    expected_mounts={},
                    expected_state="created",
                )

        rejected_injections = (
            {key: "ubuntu"},
            {key: 1},
            {"Desktop.docker.io/wsl-distro": value},
            {"desktop.docker.io/wsl-distro ": value},
            {"desktop.docker.io/wsl_distro": value},
            {"unapproved": "true"},
            {key: value, "unapproved": "true"},
        )
        for injected in rejected_injections:
            with self.subTest(rejected_injection=injected):
                document = self._container_document(
                    container_id=container_id,
                    name=name,
                    labels=labels,
                    state="created",
                    daemon_injected_labels=injected,
                )
                with self.assertRaisesRegex(
                    executor.ExecutorContractError,
                    "ownership labels drifted",
                ):
                    executor._validate_container_inspect(
                        document,
                        container_id=container_id,
                        container_name=name,
                        labels=labels,
                        expected_mounts={},
                        expected_state="created",
                    )

        duplicate_label_payload = (
            b'{"Config":{"Labels":{"desktop.docker.io/wsl-distro":"Ubuntu",'
            b'"desktop.docker.io/wsl-distro":"Ubuntu"}}}'
        )
        with self.assertRaisesRegex(
            executor.ExecutorContractError,
            "duplicate Docker JSON key",
        ):
            executor._parse_json(
                duplicate_label_payload,
                "Docker container inspect duplicate-label fixture",
            )

        for mutation in ("missing_owner", "drifted_image"):
            with self.subTest(expected_label_mutation=mutation):
                import copy

                document = copy.deepcopy(exact_docker_desktop)
                actual = document["Config"]["Labels"]
                if mutation == "missing_owner":
                    actual.pop(executor.OWNER_LABEL)
                else:
                    actual["org.vast.analytics_worker.engine"] = "other"
                with self.assertRaisesRegex(
                    executor.ExecutorContractError,
                    "ownership labels drifted",
                ):
                    executor._validate_container_inspect(
                        document,
                        container_id=container_id,
                        container_name=name,
                        labels=labels,
                        expected_mounts={},
                        expected_state="created",
                    )

        with self.assertRaisesRegex(
            executor.ExecutorContractError,
            "injected label collides",
        ):
            executor._validate_container_inspect(
                exact_docker_desktop,
                container_id=container_id,
                container_name=name,
                labels=labels,
                expected_mounts={},
                expected_state="created",
                expected_image_labels={**executor.IMAGE_LABELS, key: value},
            )

        caller_labels = {**labels, key: value}
        with self.assertRaisesRegex(
            executor.ExecutorContractError,
            "injected label collides",
        ):
            executor._validate_container_inspect(
                exact_docker_desktop,
                container_id=container_id,
                container_name=name,
                labels=caller_labels,
                expected_mounts={},
                expected_state="created",
            )
        with self.assertRaisesRegex(
            executor.ExecutorContractError,
            "injected label",
        ):
            executor._build_probe_create_command(
                container_name=name,
                labels=caller_labels,
            )
        with self.assertRaisesRegex(
            executor.ExecutorContractError,
            "injected label",
        ):
            executor._build_worker_create_command(
                container_name=name.replace("probe", "plate-number"),
                labels=caller_labels,
                binding_source=Path("/private/plate_number.json"),
                source_model=Path("/private/resnet18.onnx"),
                engine=Path("/private/resnet18.engine"),
                socket_root=Path("/private/ipc"),
                socket_name="plate_number.sock",
            )

    def test_peer_container_running_projection_rejects_runtime_and_pid_type_drift(
        self,
    ) -> None:
        container_id = "8" * 64
        name = "vast-kpp-v2-np-0123456789abcdef-probe"
        labels = {
            executor.OWNER_LABEL: executor.OWNER_VALUE,
            executor.RUN_LABEL: "9" * 64,
            executor.BRANCH_LABEL: "runtime_probe",
        }
        baseline = self._container_document(
            container_id=container_id,
            name=name,
            labels=labels,
            state="running",
            daemon_injected_labels={
                "desktop.docker.io/wsl-distro": "Ubuntu"
            },
        )
        facts = executor._validate_container_inspect(
            baseline,
            container_id=container_id,
            container_name=name,
            labels=labels,
            expected_mounts={},
            expected_state="running",
        )
        self.assertEqual(facts["state_pid"], 4321)
        self.assertEqual(facts["container_runtime"], "runc")
        self.assertIs(
            facts["docker_desktop_wsl_distro_label_attested"],
            True,
        )
        for field, value, missing in (
            ("Runtime", None, False),
            ("Runtime", "crun", False),
            ("Runtime", True, False),
            ("Runtime", None, True),
        ):
            with self.subTest(host_field=field, value=value, missing=missing):
                drifted = copy.deepcopy(baseline)
                if missing:
                    drifted["HostConfig"].pop(field)
                else:
                    drifted["HostConfig"][field] = value
                with self.assertRaises(executor.ExecutorContractError):
                    executor._validate_container_inspect(
                        drifted,
                        container_id=container_id,
                        container_name=name,
                        labels=labels,
                        expected_mounts={},
                        expected_state="running",
                    )
        for value in (0, -1, True, False, "4321", None, 2**31):
            with self.subTest(state_pid=value):
                drifted = copy.deepcopy(baseline)
                drifted["State"]["Pid"] = value
                with self.assertRaises(executor.ExecutorContractError):
                    executor._validate_container_inspect(
                        drifted,
                        container_id=container_id,
                        container_name=name,
                        labels=labels,
                        expected_mounts={},
                        expected_state="running",
                    )

    def test_successful_terminal_state_rejects_every_contradictory_failure_field(self) -> None:
        valid = {
            "Status": "exited",
            "Running": False,
            "Pid": 0,
            "ExitCode": 0,
            "OOMKilled": False,
            "Dead": False,
            "Paused": False,
            "Restarting": False,
            "Error": "",
        }
        executor._validate_successful_terminal_state(valid)
        mutations = {
            "Status": "dead",
            "Running": True,
            "Pid": 42,
            "ExitCode": 1,
            "OOMKilled": True,
            "Dead": True,
            "Paused": True,
            "Restarting": True,
            "Error": "synthetic daemon failure",
        }
        for field, value in mutations.items():
            with self.subTest(field=field):
                drifted = {**valid, field: value}
                with self.assertRaises(executor.ExecutorContractError):
                    executor._validate_successful_terminal_state(drifted)

    def test_missing_image_is_exit78_before_planner_candidate_output_or_daemon_mutation(self) -> None:
        runner = ScriptedRunner(image_present=False)
        planner = mock.Mock(side_effect=AssertionError("planner must not run"))
        gpu_probe = mock.Mock(side_effect=AssertionError("GPU probe must not run"))
        platform_observer = mock.Mock(
            side_effect=AssertionError("native mode must not observe pid0 platform")
        )
        dependencies = executor._ExecutorDependencies(
            platform_name="posix",
            environment={},
            observe_docker_cli=lambda: executor.FileIdentity(
                size_bytes=44_986_088,
                sha256="fb7b1ca4b4c579d4a0dbecca8ab6ec9a1045a8bffb984f07347edf7593a3927d",
            ),
            command_runner=runner,
            planner_builder=planner,
            gpu_probe=gpu_probe,
            peercred_platform_observer=platform_observer,
        )
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            before = sorted(path.relative_to(root) for path in root.rglob("*"))
            artifact, status = executor.execute_nonpublication_pilot(
                project_root=root,
                decision_path="configs/never-open.json",
                candidate_root="staging/never-open",
                role="secondary",
                expected_receipt_file_sha256="1" * 64,
                expected_receipt_self_sha256="2" * 64,
                run_id="synthetic-missing-image",
                expected_docker_cli_size_bytes=44_986_088,
                expected_docker_cli_sha256=(
                    "fb7b1ca4b4c579d4a0dbecca8ab6ec9a1045a8bffb984f07347edf7593a3927d"
                ),
                expected_daemon_id="1e493309-3767-45fb-9078-05b838bdfd80",
                expected_daemon_server_version="29.5.3",
                expected_daemon_api_version="1.54",
                _dependencies=dependencies,
            )
            after = sorted(path.relative_to(root) for path in root.rglob("*"))

        self.assertEqual(status, 78)
        self.assertEqual(artifact["status"], "blocked_missing_exact_pinned_docker_image")
        self.assertIs(
            artifact["runtime_preflight"][
                "network_or_pull_performed_during_executor_invocation"
            ],
            False,
        )
        self.assertNotIn(
            "network_or_pull_performed", artifact["runtime_preflight"]
        )
        self.assertEqual(before, after)
        planner.assert_not_called()
        gpu_probe.assert_not_called()
        platform_observer.assert_not_called()
        self.assertFalse(
            any(
                token in call
                for call in runner.calls
                for token in ("create", "start", "rm", "kill")
            )
        )
        for field in executor.FALSE_CLAIM_FIELDS:
            self.assertIs(artifact[field], False)

    def test_image_transport_failure_is_not_misclassified_as_exact_absence(self) -> None:
        class Runner(ScriptedRunner):
            def run(self, argv: list[str], **kwargs: object) -> executor.CommandCapture:
                command = tuple(argv)
                if "image" in command and "inspect" in command:
                    self.calls.append(command)
                    return executor.CommandCapture(1, b"", b"Cannot connect to the Docker daemon\n")
                return super().run(argv, **kwargs)

        runner = Runner(image_present=True)
        planner = mock.Mock(side_effect=AssertionError("planner must not run"))
        dependencies = executor._ExecutorDependencies(
            platform_name="posix",
            environment={},
            observe_docker_cli=lambda: executor.FileIdentity(
                44_986_088,
                "fb7b1ca4b4c579d4a0dbecca8ab6ec9a1045a8bffb984f07347edf7593a3927d",
            ),
            command_runner=runner,
            planner_builder=planner,
            gpu_probe=mock.Mock(side_effect=AssertionError("GPU must not run")),
        )
        with tempfile.TemporaryDirectory() as raw:
            artifact, status = executor.execute_nonpublication_pilot(
                project_root=raw,
                decision_path="never",
                candidate_root="never",
                role="secondary",
                expected_receipt_file_sha256="1" * 64,
                expected_receipt_self_sha256="2" * 64,
                run_id="image-transport-failure",
                expected_docker_cli_size_bytes=44_986_088,
                expected_docker_cli_sha256="fb7b1ca4b4c579d4a0dbecca8ab6ec9a1045a8bffb984f07347edf7593a3927d",
                expected_daemon_id="1e493309-3767-45fb-9078-05b838bdfd80",
                expected_daemon_server_version="29.5.3",
                expected_daemon_api_version="1.54",
                _dependencies=dependencies,
            )
            self.assertFalse((Path(raw) / "runs").exists())
        self.assertEqual(status, 78)
        self.assertEqual(artifact["status"], "blocked_local_docker_image_inspect_failure")
        planner.assert_not_called()

    def test_container_not_found_classifier_accepts_exact_docker29_pair_only(self) -> None:
        reference = "vast-kpp-v2-np-188eadf55b324566-probe"
        legacy_container = (
            f"Error: No such container: {reference}\n".encode("ascii")
        )
        legacy_object = f"Error: No such object: {reference}\n".encode("ascii")
        docker29_container = (
            f"Error response from daemon: No such container: {reference}\n".encode(
                "ascii"
            )
        )

        accepted = (
            executor.CommandCapture(1, b"", legacy_container),
            executor.CommandCapture(1, b"", legacy_object),
            executor.CommandCapture(1, b"\n", docker29_container),
        )
        for capture in accepted:
            with self.subTest(accepted=capture):
                self.assertTrue(
                    executor._is_exact_container_not_found(capture, reference)
                )

        rejected = (
            executor.CommandCapture(0, b"\n", docker29_container),
            executor.CommandCapture(2, b"\n", docker29_container),
            executor.CommandCapture(True, b"\n", docker29_container),
            executor.CommandCapture(1, b"", docker29_container),
            executor.CommandCapture(1, b"\n", legacy_container),
            executor.CommandCapture(1, b"\n", legacy_object),
            executor.CommandCapture(1, b"\r\n", docker29_container),
            executor.CommandCapture(1, b"\n\n", docker29_container),
            executor.CommandCapture(1, b" ", docker29_container),
            executor.CommandCapture(
                1,
                b"\n",
                f"Error response from daemon: No such container: {reference}-other\n".encode(
                    "ascii"
                ),
            ),
            executor.CommandCapture(
                1,
                b"\n",
                f"Error response from daemon: No such image: {reference}\n".encode(
                    "ascii"
                ),
            ),
            executor.CommandCapture(
                1,
                b"\n",
                f"Error response from daemon: No such object: {reference}\n".encode(
                    "ascii"
                ),
            ),
            executor.CommandCapture(1, b"\n", b"leading " + docker29_container),
            executor.CommandCapture(1, b"\n", docker29_container + b"trailing"),
            executor.CommandCapture(1, b"\n", docker29_container + b"\n"),
            executor.CommandCapture(
                1, b"\n", docker29_container.removesuffix(b"\n") + b"\r\n"
            ),
            executor.CommandCapture(1, b"\n", docker29_container.removesuffix(b"\n")),
            executor.CommandCapture(
                1, b"\n", b"Cannot connect to the Docker daemon\n"
            ),
            executor.CommandCapture(1, b"\n", b"permission denied\n"),
            executor.CommandCapture(1, bytearray(b"\n"), docker29_container),
            executor.CommandCapture(1, b"\n", bytearray(docker29_container)),
        )
        for capture in rejected:
            with self.subTest(rejected=capture):
                self.assertFalse(
                    executor._is_exact_container_not_found(capture, reference)
                )

        self.assertFalse(
            executor._is_exact_container_not_found(
                executor.CommandCapture(
                    1,
                    b"\n",
                    b"Error response from daemon: No such container: \n",
                ),
                "",
            )
        )
        self.assertFalse(
            executor._is_exact_container_not_found(
                executor.CommandCapture(1, b"\n", docker29_container),
                b"vast-kpp-v2-np-188eadf55b324566-probe",
            )
        )

    def test_cli_missing_image_emits_one_canonical_exit78_assessment(self) -> None:
        runner = ScriptedRunner(image_present=False)
        planner = mock.Mock(side_effect=AssertionError("planner must not run"))
        dependencies = executor._ExecutorDependencies(
            platform_name="posix",
            environment={},
            observe_docker_cli=lambda: executor.FileIdentity(
                44_986_088,
                "fb7b1ca4b4c579d4a0dbecca8ab6ec9a1045a8bffb984f07347edf7593a3927d",
            ),
            command_runner=runner,
            planner_builder=planner,
            gpu_probe=mock.Mock(side_effect=AssertionError("GPU must not run")),
        )
        output = io.BytesIO()
        with tempfile.TemporaryDirectory() as raw:
            status = executor.main(
                [
                    "--project-root", raw,
                    "--decision-path", "configs/never.json",
                    "--candidate-root", "staging/never",
                    "--role", "secondary",
                    "--expected-receipt-file-sha256", "1" * 64,
                    "--expected-receipt-self-sha256", "2" * 64,
                    "--run-id", "cli-missing-image",
                    "--expected-docker-cli-size-bytes", "44986088",
                    "--expected-docker-cli-sha256", "fb7b1ca4b4c579d4a0dbecca8ab6ec9a1045a8bffb984f07347edf7593a3927d",
                    "--expected-daemon-id", "1e493309-3767-45fb-9078-05b838bdfd80",
                    "--expected-daemon-server-version", "29.5.3",
                    "--expected-daemon-api-version", "1.54",
                ],
                _dependencies=dependencies,
                _stdout=output,
            )
            self.assertFalse((Path(raw) / "runs").exists())
        artifact = json.loads(output.getvalue())
        self.assertEqual(status, 78)
        self.assertEqual(output.getvalue(), executor.canonical_line(artifact))
        self.assertEqual(artifact["status"], "blocked_missing_exact_pinned_docker_image")
        for field in executor.FALSE_CLAIM_FIELDS:
            self.assertIs(artifact[field], False)

        diagnostic_output = io.BytesIO()
        status = executor.main(
            [
                "--project-root", raw,
                "--decision-path", "configs/never.json",
                "--candidate-root", "staging/never",
                "--role", "secondary",
                "--expected-receipt-file-sha256", "1" * 64,
                "--expected-receipt-self-sha256", "2" * 64,
                "--run-id", "kpp-v2-secondary-peercred-diagnostic-20260822-v1",
                "--expected-docker-cli-size-bytes", "44986088",
                "--expected-docker-cli-sha256", "fb7b1ca4b4c579d4a0dbecca8ab6ec9a1045a8bffb984f07347edf7593a3927d",
                "--expected-daemon-id", "1e493309-3767-45fb-9078-05b838bdfd80",
                "--expected-daemon-server-version", "29.5.3",
                "--expected-daemon-api-version", "1.54",
                "--diagnostic-so-peercred-only",
            ],
            _dependencies=dependencies,
            _stdout=diagnostic_output,
        )
        diagnostic_artifact = json.loads(diagnostic_output.getvalue())
        self.assertEqual(status, 78)
        self.assertIs(
            diagnostic_artifact["runtime_preflight"][
                "diagnostic_so_peercred_only"
            ],
            True,
        )
        self.assertIs(diagnostic_artifact["inference_performed"], False)

    def test_peercred_diagnostic_only_cli_flag_is_explicit_and_defaults_off(
        self,
    ) -> None:
        arguments = [
            "--project-root", "E:/STUDY/VAST",
            "--decision-path", "configs/decision.json",
            "--candidate-root", "staging/candidate",
            "--role", "secondary",
            "--expected-receipt-file-sha256", "1" * 64,
            "--expected-receipt-self-sha256", "2" * 64,
            "--run-id", "kpp-v2-secondary-peercred-diagnostic-20260822-v1",
            "--expected-docker-cli-size-bytes", "44986088",
            "--expected-docker-cli-sha256", "3" * 64,
            "--expected-daemon-id", "daemon-id",
            "--expected-daemon-server-version", "29.5.3",
            "--expected-daemon-api-version", "1.54",
        ]
        default = executor._build_parser().parse_args(arguments)
        self.assertIs(default.diagnostic_so_peercred_only, False)
        self.assertEqual(
            default.peer_identity_mode,
            executor.PEER_IDENTITY_MODE_NATIVE_VISIBLE,
        )
        hidden = executor._build_parser().parse_args(
            [
                *arguments,
                "--peer-identity-mode",
                executor.PEER_IDENTITY_MODE_DOCKER_DESKTOP_WSL2_PID0,
            ]
        )
        self.assertEqual(
            hidden.peer_identity_mode,
            executor.PEER_IDENTITY_MODE_DOCKER_DESKTOP_WSL2_PID0,
        )
        diagnostic = executor._build_parser().parse_args(
            [*arguments, "--diagnostic-so-peercred-only"]
        )
        self.assertIs(diagnostic.diagnostic_so_peercred_only, True)
        with self.assertRaises(executor.ExecutorContractError):
            executor._build_parser().parse_args(
                [*arguments, "--diagnostic-so-peercred-only=true"]
            )
        for invalid_mode in (
            "automatic",
            "native_visible",
            "docker_desktop_containerd_wsl2_pid0",
            "namespace-hidden-wsl2-docker-desktop ",
        ):
            with self.subTest(invalid_peer_identity_mode=invalid_mode):
                with self.assertRaises(executor.ExecutorContractError):
                    executor._build_parser().parse_args(
                        [*arguments, "--peer-identity-mode", invalid_mode]
                    )

        common = {
            "project_root": Path("."),
            "decision_path": Path("configs/decision.json"),
            "candidate_root": Path("staging/candidate"),
            "expected_receipt_file_sha256": "1" * 64,
            "expected_receipt_self_sha256": "2" * 64,
            "expected_docker_cli_size_bytes": 1,
            "expected_docker_cli_sha256": "3" * 64,
            "expected_daemon_id": "daemon-id",
            "expected_daemon_server_version": "29.5.3",
            "expected_daemon_api_version": "1.54",
        }
        for role, run_id, diagnostic_only in (
            (
                "secondary",
                "kpp-v2-secondary-pilot-20260822-v4",
                True,
            ),
            (
                "sensitivity",
                "kpp-v2-secondary-peercred-diagnostic-20260822-v1",
                True,
            ),
            (
                "secondary",
                "kpp-v2-secondary-peercred-diagnostic-20260822-v1",
                False,
            ),
        ):
            with self.subTest(
                role=role,
                run_id=run_id,
                diagnostic_only=diagnostic_only,
            ):
                with self.assertRaisesRegex(
                    executor.ExecutorContractError,
                    "diagnostic-only run identity selector drifted",
                ):
                    executor.execute_nonpublication_pilot(
                        **common,
                        role=role,
                        run_id=run_id,
                        diagnostic_so_peercred_only=diagnostic_only,
                    )
        with self.assertRaisesRegex(
            executor.ExecutorContractError,
            "peer identity mode selector drifted",
        ):
            executor.execute_nonpublication_pilot(
                **common,
                role="secondary",
                run_id="kpp-v2-secondary-peercred-diagnostic-20260822-v1",
                diagnostic_so_peercred_only=True,
                peer_identity_mode=(
                    executor.PEER_IDENTITY_MODE_DOCKER_DESKTOP_WSL2_PID0
                ),
            )

    def test_gpu_probe_does_not_run_before_read_only_candidate_validation(self) -> None:
        runner = ScriptedRunner(image_present=True)
        planner_error = executor.ExecutorContractError("synthetic candidate drift")
        planner = mock.Mock(side_effect=planner_error)
        gpu_probe = mock.Mock(side_effect=AssertionError("GPU probe must not run"))
        dependencies = executor._ExecutorDependencies(
            platform_name="posix",
            environment={},
            observe_docker_cli=lambda: executor.FileIdentity(
                44_986_088,
                "fb7b1ca4b4c579d4a0dbecca8ab6ec9a1045a8bffb984f07347edf7593a3927d",
            ),
            command_runner=runner,
            planner_builder=planner,
            gpu_probe=gpu_probe,
        )
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            with self.assertRaisesRegex(executor.ExecutorContractError, "synthetic candidate drift"):
                executor.execute_nonpublication_pilot(
                    project_root=root,
                    decision_path="configs/synthetic.json",
                    candidate_root="staging/synthetic",
                    role="secondary",
                    expected_receipt_file_sha256="1" * 64,
                    expected_receipt_self_sha256="2" * 64,
                    run_id="candidate-validation-first",
                    expected_docker_cli_size_bytes=44_986_088,
                    expected_docker_cli_sha256="fb7b1ca4b4c579d4a0dbecca8ab6ec9a1045a8bffb984f07347edf7593a3927d",
                    expected_daemon_id="1e493309-3767-45fb-9078-05b838bdfd80",
                    expected_daemon_server_version="29.5.3",
                    expected_daemon_api_version="1.54",
                    _dependencies=dependencies,
                )
            self.assertFalse((root / "runs").exists())
        planner.assert_called_once()
        gpu_probe.assert_not_called()

    def test_cleanup_rejects_transport_failure_as_container_absence(self) -> None:
        class Runner:
            def run(
                self,
                argv: list[str],
                *,
                timeout_seconds: float,
                stdout_limit: int,
                stderr_limit: int,
            ) -> executor.CommandCapture:
                del argv, timeout_seconds, stdout_limit, stderr_limit
                return executor.CommandCapture(1, b"", b"Cannot connect to the Docker daemon\n")

        with self.assertRaisesRegex(executor.ExecutorContractError, "inspect failed"):
            executor._cleanup_owned_container(
                runner=Runner(),
                container_id="1" * 64,
                container_name="vast-kpp-v2-np-0123456789abcdef-probe",
                labels={
                    executor.OWNER_LABEL: executor.OWNER_VALUE,
                    executor.RUN_LABEL: "2" * 64,
                    executor.BRANCH_LABEL: "runtime_probe",
                },
                expected_mounts={},
                cleanup_mutex=executor._NullCleanupMutex(),
            )

    def test_cleanup_force_removes_all_exact_owned_error_states(self) -> None:
        for state in ("paused", "restarting", "removing", "dead"):
            with self.subTest(state=state):
                container_id = hashlib.sha256(state.encode()).hexdigest()
                name = f"vast-kpp-v2-np-{container_id[:16]}-probe"
                labels = {
                    executor.OWNER_LABEL: executor.OWNER_VALUE,
                    executor.RUN_LABEL: "2" * 64,
                    executor.BRANCH_LABEL: "runtime_probe",
                }
                removed = False
                document = self._container_document(
                    container_id=container_id,
                    name=name,
                    labels=labels,
                    state=state,
                    daemon_injected_labels={
                        "desktop.docker.io/wsl-distro": "Ubuntu"
                    },
                )

                class Runner:
                    def run(
                        runner_self,
                        argv: list[str],
                        *,
                        timeout_seconds: float,
                        stdout_limit: int,
                        stderr_limit: int,
                    ) -> executor.CommandCapture:
                        nonlocal removed
                        del runner_self, timeout_seconds, stdout_limit, stderr_limit
                        command = tuple(argv)
                        if "inspect" in command:
                            reference = command[-1]
                            if not removed:
                                return executor.CommandCapture(0, executor.canonical_line(document), b"")
                            return executor.CommandCapture(
                                1,
                                b"",
                                f"Error: No such container: {reference}\n".encode("ascii"),
                            )
                        if "ls" in command:
                            return executor.CommandCapture(0, b"", b"")
                        if "rm" in command:
                            self.assertEqual(command[-1], container_id)
                            removed = True
                            return executor.CommandCapture(
                                1 if state == "removing" else 0,
                                b"",
                                b"already removing\n" if state == "removing" else b"",
                            )
                        raise AssertionError(command)

                executor._cleanup_owned_container(
                    runner=Runner(),
                    container_id=container_id,
                    container_name=name,
                    labels=labels,
                    expected_mounts={},
                    cleanup_mutex=executor._NullCleanupMutex(),
                )
                self.assertTrue(removed)

    def test_cleanup_mutex_serializes_four_concurrent_remove_inventory_sequences(
        self,
    ) -> None:
        """The real Docker29 failure: a list call must not overlap a sibling DELETE."""

        cleanup_lock = threading.Lock()

        class CleanupMutex:
            def hold(self) -> threading.Lock:
                return cleanup_lock

        mutex = CleanupMutex()
        state_lock = threading.Lock()
        active_removes: set[str] = set()
        removed: set[str] = set()
        calls: list[tuple[str, str]] = []
        start = threading.Barrier(len(pilot.BRANCHES))
        ids = {
            branch: hashlib.sha256(f"cleanup-race:{branch}".encode()).hexdigest()
            for branch in pilot.BRANCHES
        }
        names = {
            branch: f"vast-kpp-v2-np-0123456789abcdef-{branch}"
            for branch in pilot.BRANCHES
        }
        labels = {
            branch: {
                executor.OWNER_LABEL: executor.OWNER_VALUE,
                executor.RUN_LABEL: "2" * 64,
                executor.BRANCH_LABEL: "runtime_probe",
            }
            for branch in pilot.BRANCHES
        }

        class RaceRunner:
            def run(
                runner_self,
                argv: list[str],
                *,
                timeout_seconds: float,
                stdout_limit: int,
                stderr_limit: int,
            ) -> executor.CommandCapture:
                del runner_self, timeout_seconds, stdout_limit, stderr_limit
                command = tuple(argv)
                reference = command[-1] if command else ""
                branch = next(
                    (
                        item
                        for item in pilot.BRANCHES
                        if reference in {ids[item], names[item]}
                    ),
                    None,
                )
                if "inspect" in command:
                    self.assertIsNotNone(branch)
                    with state_lock:
                        calls.append((str(branch), "inspect"))
                        is_removed = ids[str(branch)] in removed
                    if is_removed:
                        return executor.CommandCapture(
                            1,
                            b"",
                            (
                                f"Error: No such container: {reference}\n"
                            ).encode("ascii"),
                        )
                    document = self._container_document(
                        container_id=ids[str(branch)],
                        name=names[str(branch)],
                        labels=labels[str(branch)],
                        state="exited",
                        daemon_injected_labels={
                            "desktop.docker.io/wsl-distro": "Ubuntu"
                        },
                    )
                    return executor.CommandCapture(
                        0,
                        executor.canonical_line(document),
                        b"",
                    )
                if "rm" in command:
                    self.assertIsNotNone(branch)
                    with state_lock:
                        active_removes.add(ids[str(branch)])
                        calls.append((str(branch), "remove_begin"))
                    time.sleep(0.01 if branch == pilot.BRANCHES[0] else 0.08)
                    with state_lock:
                        removed.add(ids[str(branch)])
                        active_removes.remove(ids[str(branch)])
                        calls.append((str(branch), "remove_end"))
                    return executor.CommandCapture(
                        0,
                        (ids[str(branch)] + "\n").encode("ascii"),
                        b"",
                    )
                if "ls" in command:
                    with state_lock:
                        calls.append(("catalog", "list"))
                        overlapping = bool(active_removes)
                    if overlapping:
                        return executor.CommandCapture(
                            1,
                            b"",
                            (
                                b"cannot decode []container.Summary: json: cannot "
                                b"unmarshal object into Go value of type "
                                b"[]container.Summary\n"
                            ),
                        )
                    return executor.CommandCapture(0, b"", b"")
                raise AssertionError(command)

        runner = RaceRunner()
        errors: list[BaseException] = []

        def cleanup(branch: str) -> None:
            try:
                start.wait(timeout=5)
                executor._cleanup_owned_container(
                    runner=runner,
                    container_id=ids[branch],
                    container_name=names[branch],
                    labels=labels[branch],
                    expected_mounts={},
                    cleanup_mutex=mutex,
                )
            except BaseException as error:
                errors.append(error)

        threads = [
            threading.Thread(target=cleanup, args=(branch,))
            for branch in pilot.BRANCHES
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
            self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(removed, set(ids.values()))
        remove_depth = 0
        for _branch, action in calls:
            if action == "remove_begin":
                remove_depth += 1
                self.assertEqual(remove_depth, 1)
            elif action == "remove_end":
                self.assertEqual(remove_depth, 1)
                remove_depth -= 1
            elif action == "list":
                self.assertEqual(remove_depth, 0)
        self.assertEqual(remove_depth, 0)

    def test_cleanup_delete_inventory_callgraph_has_only_locked_primitives(
        self,
    ) -> None:
        parsed = ast.parse(
            (SCRIPTS / "kpp_legacy_iss_v2_secondary_sensitivity_executor.py")
            .read_bytes(),
            filename="scripts/kpp_legacy_iss_v2_secondary_sensitivity_executor.py",
            mode="exec",
        )
        functions = {
            node.name: node
            for node in parsed.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        docker_primitives: list[tuple[str, tuple[str, ...]]] = []
        direct_callers: dict[str, set[str]] = {
            "_container_reference_absent": set(),
            "_require_exact_absence_locked": set(),
            "_cleanup_owned_container_locked": set(),
            "_recover_owned_container_by_name_locked": set(),
        }
        for function_name, function in functions.items():
            for node in ast.walk(function):
                if not isinstance(node, ast.Call):
                    continue
                callee = node.func.id if isinstance(node.func, ast.Name) else None
                if callee in direct_callers:
                    direct_callers[callee].add(function_name)
                command_argument = next(
                    (
                        argument
                        for argument in node.args
                        if isinstance(argument, (ast.List, ast.Tuple))
                    ),
                    None,
                )
                if command_argument is not None:
                    literals = tuple(
                        element.value
                        for element in command_argument.elts
                        if isinstance(element, ast.Constant)
                        and type(element.value) is str
                    )
                    if (
                        "container" in literals
                        and ("rm" in literals or "ls" in literals)
                    ):
                        docker_primitives.append((function_name, literals))
        self.assertEqual(
            docker_primitives,
            [
                (
                    "_finalize_owned_container_cleanup",
                    (
                        "container",
                        "ls",
                        "--all",
                        "--no-trunc",
                        "--format={{json .}}",
                    ),
                ),
                (
                    "_container_reference_absent",
                    (
                        "container",
                        "ls",
                        "--all",
                        "--no-trunc",
                        "--format={{json .}}",
                    ),
                ),
                (
                    "_cleanup_owned_container_locked",
                    ("container", "rm", "--force"),
                ),
            ],
        )
        self.assertEqual(
            direct_callers,
            {
                "_container_reference_absent": {
                    "_require_exact_absence_locked"
                },
                "_require_exact_absence_locked": {
                    "_require_exact_absence",
                    "_cleanup_owned_container_locked",
                    "_recover_owned_container_by_name_locked",
                    "_recover_and_cleanup_owned_container_by_name",
                    "_run_owned_container_transaction",
                },
                "_cleanup_owned_container_locked": {
                    "_cleanup_owned_container",
                    "_recover_and_cleanup_owned_container_by_name",
                },
                "_recover_owned_container_by_name_locked": {
                    "_recover_owned_container_by_name",
                    "_recover_and_cleanup_owned_container_by_name",
                },
            },
        )
        locked_wrapper_calls = {
            "_finalize_owned_container_cleanup": {"_run_read_only"},
            "_require_exact_absence": {"_require_exact_absence_locked"},
            "_cleanup_owned_container": {"_cleanup_owned_container_locked"},
            "_recover_owned_container_by_name": {
                "_recover_owned_container_by_name_locked"
            },
            "_recover_and_cleanup_owned_container_by_name": {
                "_recover_owned_container_by_name_locked",
                "_cleanup_owned_container_locked",
                "_require_exact_absence_locked",
            },
            "_run_owned_container_transaction": {
                "_require_exact_absence_locked"
            },
        }
        for function_name, expected_calls in locked_wrapper_calls.items():
            calls_inside_with = {
                node.func.id
                for with_node in ast.walk(functions[function_name])
                if isinstance(with_node, ast.With)
                for node in ast.walk(with_node)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in expected_calls
            }
            self.assertEqual(calls_inside_with, expected_calls, function_name)

    def test_early_ipc_setup_failure_preserves_primary_and_every_cleanup_error(
        self,
    ) -> None:
        requests = [
            {
                "request_id": f"early-ipc-{index}",
                "branch": pilot.BRANCHES[index // 2],
                "codec": pilot.CODECS[index % 2],
            }
            for index in range(8)
        ]
        inventory = executor.BindingInventory(
            bindings={},
            source_paths={},
            engine_paths={},
            source_identities={},
            engine_identities={},
            manifest_identity_sha256="1" * 64,
            execution_config_identity_sha256="2" * 64,
        )
        run_identity = "3" * 64

        def run_case(
            *,
            caller: str,
            watchdog_fails: bool,
            namespace_fails: bool,
            primary: BaseException,
        ) -> executor._ExecutionFailureBundle:
            self.assertIn(caller, {"namespace_validation", "model_staging"})
            expected_ipc = (
                Path(tempfile.gettempdir()).resolve()
                / "vast-synthetic-early-ipc"
            )
            namespace = executor._IpcRuntimeNamespace(
                run_identity=run_identity,
                path=expected_ipc,
                parent_path=expected_ipc.parent,
                name=expected_ipc.name,
                parent_fd=-1,
                root_fd=-1,
                parent_identity=(1, 2, 3, 4, 5),
                root_identity=(6, 7, 8, 9, 10),
                filesystem_magic=executor._LINUX_EXT_FILESYSTEM_MAGIC,
            )
            watchdog = executor._IpcRuntimeWatchdogProcess(
                process=mock.Mock(),
                control_fd=-1,
                ack_fd=-1,
                namespace=namespace,
            )
            abort_error = executor.ExecutorContractError(
                "synthetic early IPC watchdog abort failure"
            )
            destroy_error = executor.ExecutorContractError(
                "synthetic early IPC namespace destroy failure"
            )
            abort = mock.Mock(
                side_effect=abort_error if watchdog_fails else None
            )
            watchdog.abort = abort  # type: ignore[method-assign]
            destroy = mock.Mock(
                side_effect=destroy_error if namespace_fails else None
            )
            validate = mock.Mock(
                side_effect=(
                    primary if caller == "namespace_validation" else None
                )
            )
            stage = mock.Mock(
                side_effect=primary if caller == "model_staging" else None
            )
            progress = executor._ExecutionProgressLedger(
                run_root=None,
                run_id="early-ipc-cleanup",
                run_identity=run_identity,
                role="secondary",
                requests=requests,
            )
            with tempfile.TemporaryDirectory() as raw, mock.patch.object(
                executor,
                "_ipc_runtime_path",
                return_value=expected_ipc,
            ), mock.patch.object(
                executor,
                "_validate_ipc_runtime_namespace",
                side_effect=validate,
            ), mock.patch.object(
                executor,
                "_destroy_ipc_runtime_namespace",
                side_effect=destroy,
            ), mock.patch.object(
                executor,
                "_run_lease_contract_from_actor",
                return_value={},
            ):
                with self.assertRaises(
                    executor._ExecutionFailureBundle
                ) as caught:
                    executor._run_tensor_workers(
                        project_root=Path(raw),
                        run_root=Path(raw),
                        logical_run_root=(
                            "runs/nonpublication/early-ipc-cleanup"
                        ),
                        run_identity=run_identity,
                        plan={},
                        requests=requests,
                        bindings=inventory,
                        payloads=executor.TensorInventory(
                            payloads={},
                            bundle_observations=[],
                        ),
                        binding_descriptors={},
                        runtime_probe={"validated_runtime_probe": {}},
                        runtime_image={"labels": dict(executor.IMAGE_LABELS)},
                        runtime_daemon=self._peercred_daemon(),
                        docker_cli_identity=executor.FileIdentity(1, "4" * 64),
                        command_runner=mock.Mock(),
                        cleanup_mutex=executor._NullCleanupMutex(),
                        run_lease=executor._NullRunLease(),
                        container_registry=executor._OwnedContainerRegistry(
                            run_identity
                        ),
                        progress=progress,
                        _stage_inventory=stage,
                        _ipc_watchdog_spawner=(
                            lambda _identity, **_kwargs: watchdog
                        ),
                    )
            progress.close()
            self.assertEqual(abort.call_count, 1)
            self.assertEqual(destroy.call_count, 1)
            self.assertEqual(
                validate.call_count,
                1,
            )
            self.assertEqual(
                stage.call_count,
                1 if caller == "model_staging" else 0,
            )
            expected_scopes = []
            if watchdog_fails:
                expected_scopes.append("ipc_watchdog_cleanup")
            if namespace_fails:
                expected_scopes.append("ipc_namespace_cleanup")
            if isinstance(primary, executor._ExecutionFailureBundle):
                self.assertIs(caught.exception.primary, primary.primary)
                expected_scopes = [
                    *(item.scope for item in primary.supplemental_failures),
                    *expected_scopes,
                ]
            else:
                self.assertIs(caught.exception.primary, primary)
            self.assertEqual(
                caught.exception.primary_phase,
                (
                    primary.primary_phase
                    if isinstance(primary, executor._ExecutionFailureBundle)
                    else "worker_execution"
                ),
            )
            self.assertEqual(
                caught.exception.primary_stage,
                (
                    primary.primary_stage
                    if isinstance(primary, executor._ExecutionFailureBundle)
                    else "worker_orchestration"
                ),
            )
            self.assertEqual(
                [
                    item.scope
                    for item in caught.exception.supplemental_failures
                ],
                expected_scopes,
            )
            return caught.exception

        for caller in ("namespace_validation", "model_staging"):
            for watchdog_fails, namespace_fails in (
                (True, False),
                (False, True),
                (True, True),
            ):
                with self.subTest(
                    caller=caller,
                    watchdog_fails=watchdog_fails,
                    namespace_fails=namespace_fails,
                ):
                    run_case(
                        caller=caller,
                        watchdog_fails=watchdog_fails,
                        namespace_fails=namespace_fails,
                        primary=executor.ExecutorContractError(
                            f"synthetic {caller} primary"
                        ),
                    )

        docker_stderr = b"synthetic Docker primary\n"
        docker_primary = executor._DockerOperationError(
            "synthetic preexisting bundled Docker primary",
            stage="initial_freshness_inventory",
            command_class="container_inventory",
            capture=executor.CommandCapture(1, b"", docker_stderr),
        )
        prior = executor._SupplementalExecutionFailure(
            scope="runtime_namespace_cleanup",
            phase="final_cleanup",
            stage="runtime_namespace_cleanup",
            branch=None,
            error=executor._DescriptorClosureError(
                operation="synthetic_prior_closure",
                primary=executor.ExecutorContractError(
                    "synthetic prior cleanup primary"
                ),
                close_failures=[OSError("synthetic prior close")],
            ),
        )
        existing = executor._ExecutionFailureBundle(
            primary=docker_primary,
            primary_phase="worker_execution",
            primary_stage="worker_orchestration",
            primary_branch=None,
            supplemental_failures=[prior],
        )
        merged = run_case(
            caller="model_staging",
            watchdog_fails=True,
            namespace_fails=True,
            primary=existing,
        )
        artifact = executor._build_execution_failure_diagnostic(
            progress=None,
            progress_facts=executor._ExecutionProgressLedger(
                run_root=None,
                run_id="early-ipc-cleanup",
                run_identity=run_identity,
                role="secondary",
                requests=requests,
            ).summary(),
            run_id="early-ipc-cleanup",
            run_identity=run_identity,
            role="secondary",
            error=merged,
            phase="worker_execution",
            stage="worker_orchestration",
            branch=None,
            diagnostic_path=None,
            diagnostic_persistence_state="not_started",
        )
        self.assertEqual(
            artifact["failure"]["docker_command"]["stderr"],
            executor._bounded_command_stream_facts(docker_stderr),
        )
        self.assertEqual(
            artifact["supplemental_failures"][0]["closure_failure"][
                "primary"
            ]["exception_type"],
            "ExecutorContractError",
        )
        self.assertEqual(
            [item["scope"] for item in artifact["supplemental_failures"]],
            [
                "runtime_namespace_cleanup",
                "ipc_watchdog_cleanup",
                "ipc_namespace_cleanup",
            ],
        )

    def test_progress_ledger_truth_is_monotonic_for_zero_one_and_eight_responses(
        self,
    ) -> None:
        requests = [
            {
                "request_id": f"request-{index}",
                "branch": pilot.BRANCHES[index // 2],
                "codec": pilot.CODECS[index % 2],
            }
            for index in range(8)
        ]
        for dispatched, completed, expected_inference, expected_attested, expected_all in (
            (0, 0, False, True, False),
            (1, 0, None, False, False),
            (1, 1, True, True, False),
            (8, 8, True, True, True),
        ):
            with self.subTest(dispatched=dispatched, completed=completed):
                ledger = executor._ExecutionProgressLedger(
                    run_root=None,
                    run_id="truth-ledger-test",
                    run_identity="3" * 64,
                    role="secondary",
                    requests=requests,
                )
                for branch in pilot.BRANCHES:
                    ledger.record_handshake(
                        branch=branch,
                        capability_sha256=hashlib.sha256(
                            f"capability:{branch}".encode()
                        ).hexdigest(),
                        peer_identity_sha256=hashlib.sha256(
                            f"peer:{branch}".encode()
                        ).hexdigest(),
                    )
                ledger.record_barrier_released()
                for index, request in enumerate(requests[:dispatched]):
                    capability_sha = hashlib.sha256(
                        f"capability:{request['branch']}".encode()
                    ).hexdigest()
                    peer_sha = hashlib.sha256(
                        f"peer:{request['branch']}".encode()
                    ).hexdigest()
                    ledger.record_infer_dispatched(
                        branch=str(request["branch"]),
                        request_id=str(request["request_id"]),
                        request_ordinal=index % 2,
                        capability_sha256=capability_sha,
                        peer_identity_sha256=peer_sha,
                    )
                    if index >= completed:
                        continue
                    ledger.record_client_returned(
                        branch=str(request["branch"]),
                        request_id=str(request["request_id"]),
                        request_ordinal=index % 2,
                        response_is_dict=True,
                        output_is_bytes=True,
                        output_size_bytes=4000,
                    )
                    ledger.record_infer_response(
                        branch=str(request["branch"]),
                        request_id=str(request["request_id"]),
                        request_ordinal=index % 2,
                        response_sha256=hashlib.sha256(
                            f"response:{index}".encode()
                        ).hexdigest(),
                        output_sha256=hashlib.sha256(
                            f"output:{index}".encode()
                        ).hexdigest(),
                        output_size_bytes=4000,
                        capability_sha256=capability_sha,
                        peer_identity_sha256=peer_sha,
                    )
                artifact = executor._build_execution_failure_diagnostic(
                    progress=ledger,
                    error=executor.ExecutorContractError("synthetic cleanup drift"),
                    phase="final_cleanup",
                    stage="cleanup_inventory_after_remove",
                    branch=(
                        str(requests[max(0, completed - 1)]["branch"])
                        if completed
                        else None
                    ),
                    diagnostic_path=None,
                    diagnostic_persistence_state="not_started",
                )
                facts = artifact["progress"]
                self.assertEqual(
                    facts["dispatched_checkpoint_count"], dispatched
                )
                self.assertEqual(facts["validated_checkpoint_count"], completed)
                self.assertIs(facts["inference_performed"], expected_inference)
                self.assertIs(
                    facts["inference_performed_attested"], expected_attested
                )
                self.assertIs(facts["all_inferences_completed"], expected_all)
                self.assertIs(artifact["inference_performed"], expected_inference)
                self.assertNotEqual(
                    artifact["claim_status"],
                    "blocked_nonpublication_preflight_not_execution",
                )
                for field in executor.FALSE_CLAIM_FIELDS:
                    self.assertIs(artifact[field], False)

    def test_progress_close_failure_preserves_truth_and_is_supplemental(self) -> None:
        requests = [
            {
                "request_id": f"close-failure-{index}",
                "branch": pilot.BRANCHES[index // 2],
                "codec": pilot.CODECS[index % 2],
            }
            for index in range(8)
        ]
        ledger = executor._ExecutionProgressLedger(
            run_root=None,
            run_id="progress-close-failure",
            run_identity="4" * 64,
            role="secondary",
            requests=requests,
        )
        context = executor._ExecutionAttemptContext(
            run_id="progress-close-failure",
            run_identity="4" * 64,
            role="secondary",
            requests=requests,
        )
        context.bind_progress(ledger)
        before = context.snapshot_progress()
        self.assertIs(before["persistence"]["integrity_attested"], True)
        with mock.patch.object(
            ledger,
            "close",
            side_effect=executor.ExecutorContractError(
                "synthetic progress directory fsync failed"
            ),
        ):
            context.close_progress()
        after = context.snapshot_progress()
        self.assertIs(after["persistence"]["integrity_attested"], False)
        self.assertRegex(
            str(after["persistence"]["closure_error_sha256"]),
            r"^[0-9a-f]{64}$",
        )
        bundled = context.bundle_failure(
            executor.ExecutorContractError("synthetic primary failure")
        )
        self.assertIsInstance(bundled, executor._ExecutionFailureBundle)
        artifact = executor._build_execution_failure_diagnostic(
            progress=None,
            progress_facts=after,
            run_id=context.run_id,
            run_identity=context.run_identity,
            role=context.role,
            error=bundled,
            phase="worker_execution",
            stage="worker_orchestration",
            branch=None,
            diagnostic_path=None,
            diagnostic_persistence_state="not_started",
        )
        self.assertEqual(
            [item["scope"] for item in artifact["supplemental_failures"]],
            ["progress_closure"],
        )

    @unittest.skipUnless(os.name == "posix", "native descriptor closure matrix")
    def test_descriptor_closure_preserves_primary_and_attempts_every_fd(self) -> None:
        requests = [
            {
                "request_id": f"descriptor-close-{index}",
                "branch": pilot.BRANCHES[index // 2],
                "codec": pilot.CODECS[index % 2],
            }
            for index in range(8)
        ]
        original_close = os.close

        with tempfile.TemporaryDirectory() as raw:
            ledger = executor._ExecutionProgressLedger(
                run_root=Path(raw),
                run_id="descriptor-progress-close",
                run_identity="5" * 64,
                role="secondary",
                requests=requests,
            )
            progress_fd = ledger._progress_fd
            root_fd = ledger._root_fd
            self.assertIsNotNone(progress_fd)
            self.assertIsNotNone(root_fd)
            close_attempts: list[int] = []

            def fail_every_close(descriptor: int) -> None:
                close_attempts.append(descriptor)
                raise OSError(f"synthetic close failure {descriptor}")

            with mock.patch.object(
                ledger,
                "_validate_persisted_records",
                side_effect=executor.ExecutorContractError(
                    "synthetic progress validation failure"
                ),
            ), mock.patch.object(
                executor.os,
                "close",
                side_effect=fail_every_close,
            ):
                with self.assertRaises(
                    executor._DescriptorClosureError
                ) as progress_error:
                    ledger.close()
            self.assertIn(
                "progress validation failure",
                str(progress_error.exception.primary),
            )
            self.assertEqual(len(progress_error.exception.close_failures), 2)
            self.assertCountEqual(close_attempts, [progress_fd, root_fd])
            self.assertIsNone(ledger._progress_fd)
            self.assertIsNone(ledger._root_fd)
            self.assertTrue(ledger._closed)
            failed_summary = ledger.failure_summary(progress_error.exception)
            self.assertEqual(
                failed_summary["persistence"]["mode"],
                "durable_o_excl_fsync",
            )
            self.assertEqual(
                failed_summary["persistence"]["relative_directory"],
                "runtime_progress",
            )
            self.assertEqual(
                failed_summary["persistence"]["requested_file_mode"],
                "0400",
            )
            self.assertIs(
                failed_summary["persistence"]["integrity_attested"],
                False,
            )
            original_close(progress_fd)
            original_close(root_fd)

        lease_fds = [os.open(os.devnull, os.O_RDONLY) for _ in range(5)]
        lease = executor._RunLease(
            contract={},
            parent_fd=lease_fds[0],
            identity_fd=lease_fds[1],
            admission_fd=lease_fds[2],
            retention_fd=lease_fds[3],
            unresolved_root_fd=lease_fds[4],
        )
        lease_close_attempts: list[int] = []

        def fail_lease_close(descriptor: int) -> None:
            lease_close_attempts.append(descriptor)
            raise OSError("synthetic lease close failure")

        with mock.patch.object(
            executor,
            "_validate_run_lease_held",
            side_effect=executor.ExecutorContractError(
                "synthetic lease validation failure"
            ),
        ), mock.patch(
            "fcntl.flock",
            side_effect=OSError("synthetic lease unlock failure"),
        ), mock.patch.object(
            executor.os,
            "close",
            side_effect=fail_lease_close,
        ):
            with self.assertRaises(
                executor._DescriptorClosureError
            ) as lease_error:
                lease.release()
        self.assertIn("validation failure", str(lease_error.exception.primary))
        self.assertEqual(len(lease_error.exception.close_failures), 8)
        self.assertCountEqual(lease_close_attempts, lease_fds)
        self.assertTrue(lease.released)
        self.assertEqual(
            (
                lease.parent_fd,
                lease.identity_fd,
                lease.admission_fd,
                lease.retention_fd,
                lease.unresolved_root_fd,
            ),
            (-1, -1, -1, -1, -1),
        )
        for descriptor in lease_fds:
            original_close(descriptor)

        mutex_fd = os.open(os.devnull, os.O_RDONLY)
        parent_fd = os.open(os.devnull, os.O_RDONLY)
        reservation = executor._CleanupMutexReservation(
            contract={},
            parent_fd=parent_fd,
            descriptor=mutex_fd,
        )
        mutex_close_attempts: list[int] = []

        @contextmanager
        def failing_hold(_contract: object) -> object:
            raise executor.ExecutorContractError(
                "synthetic mutex validation failure"
            )
            yield

        def fail_mutex_close(descriptor: int) -> None:
            mutex_close_attempts.append(descriptor)
            raise OSError(f"synthetic mutex close failure {descriptor}")

        with mock.patch.object(
            executor,
            "_hold_cleanup_mutex_contract",
            side_effect=failing_hold,
        ), mock.patch.object(
            executor.os,
            "close",
            side_effect=fail_mutex_close,
        ):
            with self.assertRaises(
                executor._DescriptorClosureError
            ) as mutex_error:
                reservation.close()
        self.assertIn("validation failure", str(mutex_error.exception.primary))
        self.assertEqual(len(mutex_error.exception.close_failures), 2)
        self.assertCountEqual(
            mutex_close_attempts,
            [mutex_fd, parent_fd],
        )
        self.assertEqual((reservation.descriptor, reservation.parent_fd), (-1, -1))
        self.assertTrue(reservation.closed)
        original_close(mutex_fd)
        original_close(parent_fd)

    @unittest.skipUnless(os.name == "posix", "native progress namespace custody")
    def test_progress_namespace_constructor_preserves_every_cleanup_failure(
        self,
    ) -> None:
        requests = [
            {
                "request_id": f"namespace-close-{index}",
                "branch": pilot.BRANCHES[index // 2],
                "codec": pilot.CODECS[index % 2],
            }
            for index in range(8)
        ]
        original_close = os.close
        original_rmdir = os.rmdir
        close_attempts: list[int] = []
        rmdir_attempts: list[str] = []

        def close_then_fail(descriptor: int) -> None:
            close_attempts.append(descriptor)
            original_close(descriptor)
            raise OSError(f"synthetic namespace close failure {descriptor}")

        def remove_then_fail(
            path: str,
            *,
            dir_fd: int | None = None,
        ) -> None:
            rmdir_attempts.append(path)
            original_rmdir(path, dir_fd=dir_fd)
            raise OSError("synthetic namespace rmdir failure")

        with tempfile.TemporaryDirectory() as raw, mock.patch.object(
            executor.os,
            "fsync",
            side_effect=OSError("synthetic namespace fsync failure"),
        ), mock.patch.object(
            executor.os,
            "close",
            side_effect=close_then_fail,
        ), mock.patch.object(
            executor.os,
            "rmdir",
            side_effect=remove_then_fail,
        ):
            with self.assertRaises(
                executor._DescriptorClosureError
            ) as caught:
                executor._ExecutionProgressLedger(
                    run_root=Path(raw),
                    run_id="progress-namespace-close",
                    run_identity="6" * 64,
                    role="secondary",
                    requests=requests,
                )
        self.assertEqual(
            caught.exception.operation,
            "execution_progress_namespace_creation",
        )
        self.assertIsInstance(
            caught.exception.primary,
            executor.ExecutorContractError,
        )
        self.assertIn("cannot create", str(caught.exception.primary))
        self.assertEqual(len(close_attempts), 2)
        self.assertEqual(rmdir_attempts, ["runtime_progress"])
        self.assertEqual(len(caught.exception.close_failures), 3)
        self.assertIn(
            "rmdir failure",
            str(caught.exception.close_failures[1]),
        )

    @unittest.skipUnless(os.name == "posix", "native progress record custody")
    def test_progress_record_paths_preserve_primary_and_close_failure(self) -> None:
        requests = [
            {
                "request_id": f"record-close-{index}",
                "branch": pilot.BRANCHES[index // 2],
                "codec": pilot.CODECS[index % 2],
            }
            for index in range(8)
        ]
        original_close = os.close

        with tempfile.TemporaryDirectory() as raw:
            ledger = executor._ExecutionProgressLedger(
                run_root=Path(raw),
                run_id="progress-record-persist-close",
                run_identity="7" * 64,
                role="secondary",
                requests=requests,
            )
            closed: list[int] = []

            def close_record_then_fail(descriptor: int) -> None:
                closed.append(descriptor)
                original_close(descriptor)
                raise OSError("synthetic record close failure")

            with mock.patch.object(
                executor.os,
                "write",
                side_effect=OSError("synthetic record write failure"),
            ), mock.patch.object(
                executor.os,
                "close",
                side_effect=close_record_then_fail,
            ):
                with self.assertRaises(
                    executor._DescriptorClosureError
                ) as persist_error:
                    ledger._persist_record({"sequence": 1})
            self.assertEqual(
                persist_error.exception.operation,
                "execution_progress_record_persistence",
            )
            self.assertIsInstance(
                persist_error.exception.primary,
                executor.ExecutorContractError,
            )
            self.assertIn("cannot persist", str(persist_error.exception.primary))
            self.assertEqual(len(persist_error.exception.close_failures), 1)
            self.assertEqual(len(closed), 1)
            (Path(raw) / "runtime_progress" / "0001.json").unlink()
            ledger.close()

        with tempfile.TemporaryDirectory() as raw:
            ledger = executor._ExecutionProgressLedger(
                run_root=Path(raw),
                run_id="progress-record-validate-close",
                run_identity="8" * 64,
                role="secondary",
                requests=requests,
            )
            ledger._append("operation_stage", {"stage": "synthetic"})
            closed = []

            def close_validation_then_fail(descriptor: int) -> None:
                closed.append(descriptor)
                original_close(descriptor)
                raise OSError("synthetic validation close failure")

            with mock.patch.object(
                executor.os,
                "read",
                side_effect=OSError("synthetic validation read failure"),
            ), mock.patch.object(
                executor.os,
                "close",
                side_effect=close_validation_then_fail,
            ):
                with self.assertRaises(
                    executor._DescriptorClosureError
                ) as validation_error:
                    ledger._validate_persisted_records()
            self.assertEqual(
                validation_error.exception.operation,
                "execution_progress_records_validation",
            )
            self.assertEqual(validation_error.exception.close_failures, ())
            self.assertIsInstance(
                validation_error.exception.primary,
                executor._DescriptorClosureError,
            )
            record_validation_error = validation_error.exception.primary
            self.assertEqual(
                record_validation_error.operation,
                "execution_progress_record_validation",
            )
            self.assertIsInstance(
                record_validation_error.primary,
                executor.ExecutorContractError,
            )
            self.assertIn(
                "cannot validate",
                str(record_validation_error.primary),
            )
            self.assertEqual(len(record_validation_error.close_failures), 1)
            self.assertIsInstance(
                record_validation_error.close_failures[0], OSError
            )
            self.assertEqual(len(closed), 1)
            ledger.close()

    @unittest.skipUnless(os.name == "posix", "native cleanup mutex custody")
    def test_cleanup_mutex_nested_failures_are_preserved_and_projected(self) -> None:
        import fcntl

        original_close = os.close
        original_flock = fcntl.flock
        original_magic = executor._linux_fstatfs_magic
        validation_calls = 0
        close_attempts: list[int] = []

        def drift_on_final_validation(descriptor: int) -> int:
            nonlocal validation_calls
            validation_calls += 1
            if validation_calls == 3:
                return 0
            return original_magic(descriptor)

        def unlock_then_fail(descriptor: int, operation: int) -> object:
            if operation == fcntl.LOCK_UN:
                raise OSError("synthetic mutex unlock failure")
            return original_flock(descriptor, operation)

        def close_then_fail(descriptor: int) -> None:
            close_attempts.append(descriptor)
            original_close(descriptor)
            raise OSError(f"synthetic mutex actor close failure {descriptor}")

        with self._native_cleanup_mutex("9" * 64) as reservation:
            with mock.patch.object(
                executor,
                "_linux_fstatfs_magic",
                side_effect=drift_on_final_validation,
            ), mock.patch(
                "fcntl.flock",
                side_effect=unlock_then_fail,
            ), mock.patch.object(
                executor.os,
                "close",
                side_effect=close_then_fail,
            ):
                with self.assertRaises(
                    executor._DescriptorClosureError
                ) as caught:
                    with executor._hold_cleanup_mutex_contract(
                        reservation.contract
                    ):
                        raise executor.ExecutorContractError(
                            "synthetic mutex body failure"
                        )

        self.assertEqual(caught.exception.operation, "cleanup_mutex_hold")
        self.assertIsInstance(
            caught.exception.primary,
            executor._DescriptorClosureError,
        )
        self.assertEqual(
            caught.exception.primary.operation,
            "cleanup_mutex_body_and_final_validation",
        )
        self.assertIn(
            "body failure",
            str(caught.exception.primary.primary),
        )
        self.assertEqual(len(caught.exception.primary.close_failures), 1)
        self.assertEqual(len(caught.exception.close_failures), 3)
        self.assertEqual(len(close_attempts), 2)

        projection = executor._execution_failure_projection(
            error=caught.exception,
            phase="final_cleanup",
            stage="cleanup_mutex_close",
            branch=None,
        )
        outer = projection["closure_failure"]
        inner = outer["primary"]["closure_failure"]
        self.assertEqual(outer["operation"], "cleanup_mutex_hold")
        self.assertEqual(
            inner["operation"],
            "cleanup_mutex_body_and_final_validation",
        )
        self.assertEqual(
            inner["primary"]["exception_type"],
            "ExecutorContractError",
        )
        self.assertIn(
            "body failure",
            str(caught.exception.primary.primary),
        )
        self.assertEqual(
            [item["exception_type"] for item in inner["close_failures"]],
            ["ExecutorContractError"],
        )
        self.assertEqual(
            [item["exception_type"] for item in outer["close_failures"]],
            ["OSError", "OSError", "OSError"],
        )

        docker_stderr = (
            b"cannot decode []container.Summary: json: cannot unmarshal "
            b"object into Go value of type []container.Summary\n"
        )
        docker_error = executor._DockerOperationError(
            "synthetic nested Docker inventory failure",
            stage="cleanup_inventory_after_remove",
            command_class="container_inventory",
            capture=executor.CommandCapture(1, b"", docker_stderr),
        )
        nested = executor._DescriptorClosureError(
            operation="synthetic_inner_closure",
            primary=docker_error,
            close_failures=[OSError("synthetic inner close")],
        )
        wrapped = executor._DescriptorClosureError(
            operation="synthetic_outer_closure",
            primary=nested,
            close_failures=[OSError("synthetic outer close")],
        )
        docker_projection = executor._execution_failure_projection(
            error=wrapped,
            phase="final_cleanup",
            stage="cleanup_mutex_close",
            branch=None,
        )
        nested_docker = docker_projection["closure_failure"]["primary"][
            "closure_failure"
        ]["primary"]
        self.assertEqual(
            nested_docker["docker_command"]["command_class"],
            "container_inventory",
        )
        self.assertEqual(
            nested_docker["docker_command"]["returncode"],
            1,
        )
        self.assertEqual(
            nested_docker["docker_command"]["stderr"],
            executor._bounded_command_stream_facts(docker_stderr),
        )
        self.assertIsNone(nested_docker["closure_failure"])

    def test_main_stdout_is_exactly_once_and_short_or_flush_failure_returns_78(
        self,
    ) -> None:
        argv = [
            "--project-root", ".",
            "--decision-path", "decision.json",
            "--candidate-root", "candidate",
            "--role", "secondary",
            "--expected-receipt-file-sha256", "1" * 64,
            "--expected-receipt-self-sha256", "2" * 64,
            "--run-id", "stdout-at-most-once",
            "--expected-docker-cli-size-bytes", "1",
            "--expected-docker-cli-sha256", "3" * 64,
            "--expected-daemon-id", "daemon",
            "--expected-daemon-server-version", "version",
            "--expected-daemon-api-version", "api",
        ]
        artifact = {"schema_version": 1, "status": "synthetic"}

        class Sink:
            def __init__(self, outcome: object, *, fail_flush: bool = False) -> None:
                self.outcome = outcome
                self.fail_flush = fail_flush
                self.write_calls = 0
                self.flush_calls = 0
                self.payloads: list[bytes] = []
                self.accepted = bytearray()

            def write(self, payload: bytes) -> object:
                self.write_calls += 1
                self.payloads.append(payload)
                if self.outcome == "prefix_then_raise":
                    self.accepted.extend(payload[:7])
                    raise OSError("synthetic partial write failure")
                if isinstance(self.outcome, BaseException):
                    raise self.outcome
                if self.outcome == "full":
                    self.accepted.extend(payload)
                    return len(payload)
                if self.outcome == "short":
                    accepted = max(0, len(payload) - 1)
                    self.accepted.extend(payload[:accepted])
                    return accepted
                if type(self.outcome) is int and self.outcome > 0:
                    self.accepted.extend(payload[: min(self.outcome, len(payload))])
                return self.outcome

            def flush(self) -> None:
                self.flush_calls += 1
                if self.fail_flush:
                    raise OSError("synthetic flush failure")

        with mock.patch.object(
            executor,
            "execute_nonpublication_pilot",
            return_value=(artifact, 0),
        ):
            full = Sink("full")
            self.assertEqual(executor.main(argv, _stdout=full), 0)
            self.assertEqual((full.write_calls, full.flush_calls), (1, 1))
            self.assertEqual(full.payloads, [executor.canonical_line(artifact)])
            for outcome in (None, True, -1, 0, "short", 10**9):
                with self.subTest(outcome=outcome):
                    sink = Sink(outcome)
                    self.assertEqual(executor.main(argv, _stdout=sink), 78)
                    self.assertEqual((sink.write_calls, sink.flush_calls), (1, 0))
            raised = Sink("prefix_then_raise")
            self.assertEqual(executor.main(argv, _stdout=raised), 78)
            self.assertEqual((raised.write_calls, raised.flush_calls), (1, 0))
            self.assertEqual(len(raised.accepted), 7)
            flush = Sink("full", fail_flush=True)
            self.assertEqual(executor.main(argv, _stdout=flush), 78)
            self.assertEqual((flush.write_calls, flush.flush_calls), (1, 1))

    @unittest.skipUnless(os.name == "posix", "native failure diagnostic custody")
    def test_failure_diagnostic_writer_is_o_excl_and_leaves_partial_without_retry(
        self,
    ) -> None:
        artifact = {
            "schema_version": 1,
            "artifact_kind": "synthetic_failure_diagnostic",
            "diagnostic_persistence": {
                "commit_attested": False,
                "state": "self_commit_unattested",
            },
        }
        payload = executor.canonical_line(artifact)
        with tempfile.TemporaryDirectory() as raw:
            run_root = Path(raw) / "run"
            run_root.mkdir(mode=0o700)
            custody = executor._RunRootCustody.bind(run_root)
            facts = executor._persist_execution_failure_diagnostic(custody, artifact)
            destination = (
                run_root / executor.EXECUTION_FAILURE_DIAGNOSTIC_NAME
            )
            original = destination.stat()
            self.assertEqual(destination.read_bytes(), payload)
            self.assertEqual(facts["size_bytes"], len(payload))
            self.assertEqual(
                facts["sha256"], hashlib.sha256(payload).hexdigest()
            )
            with self.assertRaisesRegex(
                executor.ExecutorContractError,
                "already exists",
            ):
                executor._persist_execution_failure_diagnostic(
                    custody,
                    artifact,
                )
            current = destination.stat()
            self.assertEqual(
                (current.st_dev, current.st_ino, destination.read_bytes()),
                (original.st_dev, original.st_ino, payload),
            )
            custody.close()

        with tempfile.TemporaryDirectory() as raw:
            run_root = Path(raw) / "positive-short"
            run_root.mkdir(mode=0o700)
            custody = executor._RunRootCustody.bind(run_root)
            original_write = os.write
            calls = 0

            def positive_short_write(descriptor: int, view: object) -> int:
                nonlocal calls
                calls += 1
                value = bytes(view)
                if calls == 1:
                    return original_write(
                        descriptor,
                        value[: max(1, len(value) // 2)],
                    )
                return original_write(descriptor, value)

            with mock.patch.object(
                executor.os,
                "write",
                side_effect=positive_short_write,
            ):
                facts = executor._persist_execution_failure_diagnostic(
                    custody,
                    artifact,
                )
            destination = (
                run_root / executor.EXECUTION_FAILURE_DIAGNOSTIC_NAME
            )
            self.assertEqual(destination.read_bytes(), payload)
            self.assertEqual(facts["size_bytes"], len(payload))
            self.assertEqual(calls, 2)
            custody.close()

        with tempfile.TemporaryDirectory() as raw:
            run_root = Path(raw) / "file-fsync-failure"
            run_root.mkdir(mode=0o700)
            custody = executor._RunRootCustody.bind(run_root)
            original_fsync = os.fsync
            calls = 0

            def fail_first_fsync(descriptor: int) -> None:
                nonlocal calls
                calls += 1
                if calls == 1:
                    raise OSError("synthetic file fsync failure")
                original_fsync(descriptor)

            with mock.patch.object(
                executor.os,
                "fsync",
                side_effect=fail_first_fsync,
            ):
                with self.assertRaisesRegex(
                    executor.ExecutorContractError,
                    "cannot persist execution failure diagnostic",
                ):
                    executor._persist_execution_failure_diagnostic(
                        custody,
                        artifact,
                    )
            failed = run_root / executor.EXECUTION_FAILURE_DIAGNOSTIC_NAME
            self.assertTrue(failed.is_file())
            self.assertEqual(failed.read_bytes(), payload)
            self.assertEqual(calls, 1)
            custody.close()

        with tempfile.TemporaryDirectory() as raw:
            run_root = Path(raw) / "partial"
            run_root.mkdir(mode=0o700)
            custody = executor._RunRootCustody.bind(run_root)
            original_write = os.write
            calls = 0

            def stalled_write(descriptor: int, view: object) -> int:
                nonlocal calls
                calls += 1
                if calls == 1:
                    value = bytes(view)
                    return original_write(
                        descriptor,
                        value[: max(1, len(value) // 2)],
                    )
                return 0

            with mock.patch.object(executor.os, "write", side_effect=stalled_write):
                with self.assertRaisesRegex(
                    executor.ExecutorContractError,
                    "write stalled",
                ):
                    executor._persist_execution_failure_diagnostic(
                        custody,
                        artifact,
                    )
            partial = run_root / executor.EXECUTION_FAILURE_DIAGNOSTIC_NAME
            self.assertTrue(partial.is_file())
            self.assertGreater(partial.stat().st_size, 0)
            self.assertLess(partial.stat().st_size, len(payload))
            self.assertEqual(calls, 2)
            custody.close()

        with tempfile.TemporaryDirectory() as raw:
            run_root = Path(raw) / "primary-and-close"
            run_root.mkdir(mode=0o700)
            custody = executor._RunRootCustody.bind(run_root)
            original_close = os.close
            failed_descriptors: list[int] = []

            def fail_leaf_close(descriptor: int) -> None:
                if descriptor != custody.descriptor:
                    failed_descriptors.append(descriptor)
                    raise OSError("synthetic leaf close failure")
                original_close(descriptor)

            with mock.patch.object(executor.os, "write", return_value=0), mock.patch.object(
                executor.os,
                "close",
                side_effect=fail_leaf_close,
            ):
                with self.assertRaises(
                    executor._RunRootArtifactPersistenceError
                ) as caught:
                    executor._persist_execution_failure_diagnostic(
                        custody,
                        artifact,
                    )
            self.assertIsInstance(
                caught.exception.primary,
                executor.ExecutorContractError,
            )
            self.assertIn("write stalled", str(caught.exception.primary))
            self.assertEqual(len(caught.exception.close_failures), 1)
            self.assertEqual(len(failed_descriptors), 1)
            projection = executor._execution_failure_projection(
                error=caught.exception,
                phase="failure_reporting",
                stage="failure_diagnostic_write",
                branch=None,
            )
            self.assertEqual(
                projection["closure_failure"]["operation"],
                "held_run_root_artifact",
            )
            self.assertEqual(
                projection["closure_failure"]["primary"]["exception_type"],
                "ExecutorContractError",
            )
            self.assertEqual(
                [
                    item["exception_type"]
                    for item in projection["closure_failure"][
                        "close_failures"
                    ]
                ],
                ["OSError"],
            )
            original_close(failed_descriptors[0])
            custody.close()

    @unittest.skipUnless(os.name == "posix", "native run-root leaf custody")
    def test_held_runroot_leaf_modes_and_final_named_identity_are_exact(self) -> None:
        cases = (
            (
                executor.ASSESSMENT_NAME,
                0o600,
                b'{"synthetic":"assessment"}\n',
            ),
            (
                executor.EXECUTION_FAILURE_DIAGNOSTIC_NAME,
                0o400,
                b'{"synthetic":"failure"}\n',
            ),
        )
        for parent in (None, ROOT):
            for name, requested_mode, payload in cases:
                with self.subTest(
                    parent=str(parent),
                    name=name,
                    requested_mode=oct(requested_mode),
                ), tempfile.TemporaryDirectory(dir=parent) as raw:
                    run_root = Path(raw) / "run"
                    run_root.mkdir(mode=0o700)
                    custody = executor._RunRootCustody.bind(run_root)
                    facts = executor._persist_held_runroot_leaf(
                        custody,
                        name=name,
                        payload=payload,
                        requested_mode=requested_mode,
                    )
                    expected_mode = (
                        requested_mode
                        if custody.filesystem_magic
                        == executor._LINUX_EXT_FILESYSTEM_MAGIC
                        else (0o555 if requested_mode == 0o400 else 0o777)
                    )
                    self.assertEqual(
                        stat.S_IMODE((run_root / name).stat().st_mode),
                        expected_mode,
                    )
                    self.assertEqual(facts["effective_mode"], f"{expected_mode:04o}")
                    self.assertIn(name, custody.leaves)
                    held_descriptor = custody.leaves[name].descriptor
                    self.assertGreaterEqual(held_descriptor, 0)
                    self.assertEqual(os.fstat(held_descriptor).st_size, len(payload))
                    custody.close()
                    self.assertEqual(custody.leaves[name].descriptor, -1)

        with tempfile.TemporaryDirectory() as raw:
            run_root = Path(raw) / "replacement"
            run_root.mkdir(mode=0o700)
            custody = executor._RunRootCustody.bind(run_root)
            payload = b'{"synthetic":"held-original"}\n'
            executor._persist_held_runroot_leaf(
                custody,
                name=executor.EXECUTION_FAILURE_DIAGNOSTIC_NAME,
                payload=payload,
                requested_mode=0o400,
            )
            destination = run_root / executor.EXECUTION_FAILURE_DIAGNOSTIC_NAME
            displaced = run_root / "displaced-original.json"
            os.replace(destination, displaced)
            destination.write_bytes(payload)
            os.chmod(destination, 0o400)
            with self.assertRaises(executor._RunRootArtifactPersistenceError):
                custody.close()
            self.assertTrue(custody.close_attempted)
            self.assertEqual(
                custody.leaves[
                    executor.EXECUTION_FAILURE_DIAGNOSTIC_NAME
                ].descriptor,
                -1,
            )

    @unittest.skipUnless(os.name == "posix", "native create-and-bind custody")
    def test_run_namespace_returns_created_held_identity_before_use(self) -> None:
        run_id = "synthetic-created-held-runroot"
        with tempfile.TemporaryDirectory() as raw:
            run_root, logical, custody = executor._create_run_namespace(
                raw,
                run_id,
            )
            self.assertEqual(logical, f"runs/nonpublication/{run_id}")
            self.assertIs(type(custody), executor._RunRootCustody)
            assert custody is not None
            self.assertEqual(custody.path, run_root)
            custody.validate()
            context = executor._ExecutionAttemptContext(
                run_id=run_id,
                run_identity="9" * 64,
                role="secondary",
                requests=[
                    {
                        "request_id": f"created-held-{index}",
                        "branch": pilot.BRANCHES[index // 2],
                        "codec": pilot.CODECS[index % 2],
                    }
                    for index in range(8)
                ],
            )
            context.bind_run_root(run_root, custody)
            self.assertIs(context.run_root_custody, custody)
            context.close_run_root()
            self.assertTrue(custody.close_attempted)

        with tempfile.TemporaryDirectory() as raw:
            run_root, _, custody = executor._create_run_namespace(raw, run_id)
            assert custody is not None
            displaced = run_root.with_name(f"{run_id}-displaced")
            os.replace(run_root, displaced)
            run_root.mkdir(mode=0o700)
            context = executor._ExecutionAttemptContext(
                run_id=run_id,
                run_identity="a" * 64,
                role="secondary",
                requests=[
                    {
                        "request_id": f"replacement-{index}",
                        "branch": pilot.BRANCHES[index // 2],
                        "codec": pilot.CODECS[index % 2],
                    }
                    for index in range(8)
                ],
            )
            with self.assertRaisesRegex(
                executor.ExecutorContractError,
                "run-root identity changed",
            ):
                context.bind_run_root(run_root, custody)
            self.assertIs(context.run_root_custody, custody)
            self.assertEqual(list(run_root.iterdir()), [])
            context.close_run_root()
            self.assertTrue(custody.close_attempted)
            self.assertEqual(
                [item.scope for item in context.supplemental_failures],
                ["run_root_closure"],
            )

    def test_malformed_create_id_recovers_owned_container_by_exact_name_and_removes(self) -> None:
        container_id = "3" * 64
        name = "vast-kpp-v2-np-0123456789abcdef-probe"
        labels = {
            executor.OWNER_LABEL: executor.OWNER_VALUE,
            executor.RUN_LABEL: "4" * 64,
            executor.BRANCH_LABEL: "runtime_probe",
        }
        inspect_count = 0
        removed = False

        class Runner:
            def run(
                runner_self,
                argv: list[str],
                *,
                timeout_seconds: float,
                stdout_limit: int,
                stderr_limit: int,
            ) -> executor.CommandCapture:
                nonlocal inspect_count, removed
                del timeout_seconds, stdout_limit, stderr_limit, runner_self
                command = tuple(argv)
                if "inspect" in command:
                    inspect_count += 1
                    reference = command[-1]
                    if inspect_count == 1 or removed:
                        return executor.CommandCapture(
                            1,
                            b"",
                            f"Error: No such container: {reference}\n".encode("ascii"),
                        )
                    return executor.CommandCapture(
                        0,
                        executor.canonical_line(
                            self._container_document(
                                container_id=container_id,
                                name=name,
                                labels=labels,
                                state="created",
                                daemon_injected_labels={
                                    "desktop.docker.io/wsl-distro": "Ubuntu"
                                },
                            )
                        ),
                        b"",
                    )
                if "create" in command:
                    return executor.CommandCapture(0, b"malformed-container-id\n", b"")
                if "ls" in command:
                    return executor.CommandCapture(0, b"", b"")
                if "rm" in command:
                    self.assertEqual(command[-1], container_id)
                    removed = True
                    return executor.CommandCapture(0, (container_id + "\n").encode(), b"")
                raise AssertionError(command)

        runner = Runner()

        class RetainedWatchdog:
            def mark_create_dispatch(self) -> None:
                return None

            def mark_create_terminal(self) -> None:
                raise AssertionError("malformed create must remain D&&!T")

            def complete(self) -> None:
                raise AssertionError("malformed create cannot complete")

            def abort(self) -> None:
                recovered = executor._recover_and_cleanup_owned_container_by_name(
                    runner=runner,
                    container_name=name,
                    labels=labels,
                    expected_mounts={},
                    cleanup_mutex=executor._NullCleanupMutex(),
                    expected_image_labels=executor.IMAGE_LABELS,
                )
                if recovered != container_id:
                    raise AssertionError("retained watchdog did not remove late create")

            def detach_ambiguous_owner(self) -> None:
                self.abort()

        with self.assertRaisesRegex(executor.ExecutorContractError, "invalid container ID"):
            executor._run_owned_container_transaction(
                runner=runner,
                create_command=executor._build_probe_create_command(
                    container_name=name,
                    labels=labels,
                ),
                container_name=name,
                labels=labels,
                expected_mounts={},
                after_start=lambda _container_id: None,
                cleanup_mutex=executor._NullCleanupMutex(),
                watchdog_factory=lambda **_kwargs: RetainedWatchdog(),
            )
        self.assertTrue(removed)
        self.assertGreaterEqual(inspect_count, 3)

    def test_transaction_preserves_primary_controller_and_watchdog_failures(self) -> None:
        class PrimaryFailure(BaseException):
            pass

        class WatchdogFailure(BaseException):
            pass

        container_id = "6" * 64
        run_identity = "7" * 64
        name = f"vast-kpp-v2-np-{run_identity[:16]}-probe"
        labels = {
            executor.OWNER_LABEL: executor.OWNER_VALUE,
            executor.RUN_LABEL: run_identity,
            executor.BRANCH_LABEL: "runtime_probe",
        }
        created = False
        removed = False
        inspect_states = iter(("created", "running", "running"))
        docker29_error = (
            b"cannot decode []container.Summary: json: cannot unmarshal object "
            b"into Go value of type []container.Summary\n"
        )

        class Runner:
            def run(
                runner_self,
                argv: list[str],
                *,
                timeout_seconds: float,
                stdout_limit: int,
                stderr_limit: int,
            ) -> executor.CommandCapture:
                nonlocal created, removed
                del runner_self, timeout_seconds, stdout_limit, stderr_limit
                command = tuple(argv)
                if "create" in command:
                    created = True
                    return executor.CommandCapture(
                        0, (container_id + "\n").encode(), b""
                    )
                if "start" in command:
                    return executor.CommandCapture(0, b"", b"")
                if "rm" in command:
                    removed = True
                    return executor.CommandCapture(0, b"", b"")
                if "ls" in command:
                    if removed:
                        return executor.CommandCapture(1, b"", docker29_error)
                    return executor.CommandCapture(0, b"", b"")
                if "inspect" in command:
                    reference = command[-1]
                    if not created or removed:
                        return executor.CommandCapture(
                            1,
                            b"",
                            f"Error: No such container: {reference}\n".encode(),
                        )
                    document = self._container_document(
                        container_id=container_id,
                        name=name,
                        labels=labels,
                        state=next(inspect_states),
                        daemon_injected_labels={
                            "desktop.docker.io/wsl-distro": "Ubuntu"
                        },
                    )
                    return executor.CommandCapture(
                        0,
                        executor.canonical_line(document),
                        b"",
                    )
                raise AssertionError(command)

        class Watchdog:
            def mark_create_dispatch(self) -> None:
                return None

            def mark_create_terminal(self) -> None:
                return None

            def complete(self) -> None:
                raise AssertionError("failed body must not complete watchdog")

            def abort(self) -> None:
                raise WatchdogFailure()

        with self.assertRaises(executor._ExecutionFailureBundle) as raised:
            executor._run_owned_container_transaction(
                runner=Runner(),
                create_command=executor._build_probe_create_command(
                    container_name=name,
                    labels=labels,
                ),
                container_name=name,
                labels=labels,
                expected_mounts={},
                after_start=lambda _container_id: (_ for _ in ()).throw(
                    PrimaryFailure()
                ),
                cleanup_mutex=executor._NullCleanupMutex(),
                watchdog_factory=lambda **_kwargs: Watchdog(),
                allowed_started_states=("running",),
            )
        failure = raised.exception
        self.assertIsInstance(failure.primary, PrimaryFailure)
        self.assertEqual(failure.primary_phase, "worker_execution")
        self.assertEqual(
            [item.scope for item in failure.supplemental_failures],
            ["controller_container_cleanup", "container_watchdog_cleanup"],
        )
        controller = failure.supplemental_failures[0].error
        self.assertIsInstance(controller, executor._DockerOperationError)
        self.assertEqual(controller.stage, "cleanup_inventory_after_remove")
        self.assertEqual(
            controller.command_facts["stderr"]["sha256"],
            hashlib.sha256(docker29_error).hexdigest(),
        )
        self.assertIsInstance(
            failure.supplemental_failures[1].error,
            WatchdogFailure,
        )

    def test_final_catalog_docker29_failure_retains_exact_command_facts(self) -> None:
        run_identity = "8" * 64
        registry = executor._OwnedContainerRegistry(run_identity)
        for ordinal, name in enumerate(registry.expected_names):
            registry.record(name, f"{ordinal + 1:064x}")
        docker29_error = (
            b"cannot decode []container.Summary: json: cannot unmarshal object "
            b"into Go value of type []container.Summary\n"
        )

        class Runner:
            def run(
                runner_self,
                argv: list[str],
                *,
                timeout_seconds: float,
                stdout_limit: int,
                stderr_limit: int,
            ) -> executor.CommandCapture:
                del runner_self, timeout_seconds, stdout_limit, stderr_limit
                command = tuple(argv)
                if "inspect" in command:
                    reference = command[-1]
                    return executor.CommandCapture(
                        1,
                        b"",
                        f"Error: No such container: {reference}\n".encode(),
                    )
                if "ls" in command:
                    return executor.CommandCapture(1, b"", docker29_error)
                raise AssertionError(command)

        with self.assertRaises(
            executor._FinalOwnedContainerCleanupError
        ) as raised:
            executor._finalize_owned_container_cleanup(
                runner=Runner(),
                cleanup_mutex=executor._NullCleanupMutex(),
                container_registry=registry,
            )
        failure = raised.exception
        self.assertEqual(
            failure.operation,
            "final_owned_container_cleanup_attestation",
        )
        self.assertEqual(len(failure.close_failures), 0)
        self.assertEqual(len(failure.absence_inspects), 10)
        self.assertEqual(
            failure.registry_id_sha256s,
            {
                name: hashlib.sha256(container_id.encode("ascii")).hexdigest()
                for name, container_id in registry.snapshot().items()
            },
        )
        self.assertIsNotNone(failure.final_catalog)
        self.assertIs(
            failure.final_catalog["exact_empty_observed"],
            False,
        )
        self.assertIsInstance(failure.primary, executor._DockerOperationError)
        primary = failure.primary
        self.assertEqual(primary.stage, "final_owned_container_cleanup")
        self.assertEqual(
            primary.command_facts["command_class"], "container_inventory"
        )
        self.assertEqual(primary.command_facts["returncode"], 1)
        self.assertEqual(
            primary.command_facts["stderr"],
            {
                "size_bytes": len(docker29_error),
                "sha256": hashlib.sha256(docker29_error).hexdigest(),
                "safe_bounded_text": docker29_error.decode("ascii"),
            },
        )

    def test_final_catalog_exhausts_corrupt_and_extra_registry_references(self) -> None:
        registry = executor._OwnedContainerRegistry("9" * 64)
        expected_names = registry.expected_names
        extra_id = "e" * 64
        snapshot = {
            expected_names[0]: "é",
            "unexpected-registry-name": extra_id,
        }
        calls: list[tuple[str, ...]] = []

        class Runner:
            def run(
                runner_self,
                argv: list[str],
                *,
                timeout_seconds: float,
                stdout_limit: int,
                stderr_limit: int,
            ) -> executor.CommandCapture:
                del runner_self, timeout_seconds, stdout_limit, stderr_limit
                command = tuple(argv)
                calls.append(command)
                if "inspect" in command:
                    reference = command[-1]
                    return executor.CommandCapture(
                        1,
                        b"",
                        f"Error: No such container: {reference}\n".encode(),
                    )
                if "ls" in command:
                    return executor.CommandCapture(0, b"", b"")
                raise AssertionError(command)

        with mock.patch.object(
            registry,
            "snapshot",
            return_value=snapshot,
        ), self.assertRaises(
            executor._FinalOwnedContainerCleanupError
        ) as raised:
            executor._finalize_owned_container_cleanup(
                runner=Runner(),
                cleanup_mutex=executor._NullCleanupMutex(),
                container_registry=registry,
            )
        failure = raised.exception
        self.assertIsInstance(failure.primary, executor.ExecutorContractError)
        self.assertEqual(len(failure.absence_inspects), 6)
        self.assertEqual(
            [call[-1] for call in calls if "inspect" in call],
            [*expected_names, extra_id],
        )
        self.assertEqual(sum("ls" in call for call in calls), 1)
        self.assertEqual(
            failure.registry_id_sha256s,
            {
                "unexpected-registry-name": hashlib.sha256(
                    extra_id.encode("ascii")
                ).hexdigest()
            },
        )
        first_name_fact = next(
            item
            for item in failure.absence_inspects
            if item["container_name"] == expected_names[0]
        )
        self.assertIsNone(first_name_fact["container_id_sha256"])
        self.assertIs(failure.final_catalog["exact_empty_observed"], True)

    def test_failure_safe_final_catalog_accepts_partial_registry_but_checks_all_names(
        self,
    ) -> None:
        registry = executor._OwnedContainerRegistry("7" * 64)
        recorded_name = registry.expected_names[1]
        recorded_id = "d" * 64
        registry.record(recorded_name, recorded_id)
        calls: list[tuple[str, ...]] = []

        class Runner:
            def run(
                runner_self,
                argv: list[str],
                *,
                timeout_seconds: float,
                stdout_limit: int,
                stderr_limit: int,
            ) -> executor.CommandCapture:
                del runner_self, timeout_seconds, stdout_limit, stderr_limit
                command = tuple(argv)
                calls.append(command)
                if "inspect" in command:
                    reference = command[-1]
                    return executor.CommandCapture(
                        1,
                        b"",
                        f"Error: No such container: {reference}\n".encode(),
                    )
                if "ls" in command:
                    return executor.CommandCapture(0, b"", b"")
                raise AssertionError(command)

        facts = executor._finalize_owned_container_cleanup(
            runner=Runner(),
            cleanup_mutex=executor._NullCleanupMutex(),
            container_registry=registry,
            require_complete_registry=False,
        )
        self.assertIs(facts["registry_coverage_complete"], False)
        self.assertEqual(facts["recorded_container_count"], 1)
        self.assertEqual(len(facts["absence_inspects"]), 6)
        self.assertIs(facts["final_catalog"]["exact_empty_observed"], True)
        self.assertEqual(
            [call[-1] for call in calls if "inspect" in call],
            [
                registry.expected_names[0],
                recorded_id,
                recorded_name,
                *registry.expected_names[2:],
            ],
        )
        self.assertEqual(sum("ls" in call for call in calls), 1)

    def test_recovery_always_attempts_final_absence_and_preserves_both_failures(
        self,
    ) -> None:
        class CleanupFailure(RuntimeError):
            pass

        class FinalObservationFailure(RuntimeError):
            pass

        cleanup_failure = CleanupFailure("synthetic cleanup failure")
        final_failure = FinalObservationFailure(
            "synthetic final observation failure"
        )
        final_capture = executor.CommandCapture(
            1,
            b"",
            b"Error: No such container: synthetic-name\n",
        )
        with mock.patch.object(
            executor,
            "_recover_owned_container_by_name_locked",
            return_value="a" * 64,
        ) as recover, mock.patch.object(
            executor,
            "_cleanup_owned_container_locked",
            side_effect=cleanup_failure,
        ) as cleanup, mock.patch.object(
            executor,
            "_container_inspect_capture",
            return_value=final_capture,
        ) as inspect, mock.patch.object(
            executor,
            "_require_exact_absence_locked",
            side_effect=final_failure,
        ) as final_absence, self.assertRaises(
            executor._DescriptorClosureError
        ) as raised:
            executor._recover_and_cleanup_owned_container_by_name(
                runner=object(),
                container_name="synthetic-name",
                labels={},
                expected_mounts={},
                cleanup_mutex=executor._NullCleanupMutex(),
            )
        self.assertIs(raised.exception.primary, cleanup_failure)
        self.assertEqual(raised.exception.close_failures, (final_failure,))
        recover.assert_called_once()
        cleanup.assert_called_once()
        inspect.assert_called_once_with(mock.ANY, "synthetic-name")
        final_absence.assert_called_once_with(
            mock.ANY,
            final_capture,
            "synthetic-name",
            inventory_stage="recovery_inventory_absence",
        )

    def test_watchdog_wait_failure_never_kills_abort_owner_and_dead_ipc_transfers(
        self,
    ) -> None:
        class Process:
            def __init__(self, returncode: int) -> None:
                self.returncode = returncode
                self.kill_calls = 0

            def wait(self, *, timeout: float) -> int:
                del timeout
                raise subprocess.TimeoutExpired("synthetic-watchdog", 1)

            def poll(self) -> int:
                return self.returncode

            def kill(self) -> None:
                self.kill_calls += 1

        namespace = executor._IpcRuntimeNamespace(
            run_identity="a" * 64,
            path=Path("/tmp/synthetic-ipc"),
            parent_path=Path("/tmp"),
            name="synthetic-ipc",
            parent_fd=20,
            root_fd=21,
            parent_identity=(1, 2, stat.S_IFDIR | 0o1777, 0, 0),
            root_identity=(1, 3, stat.S_IFDIR | 0o700, 1000, 1000),
            filesystem_magic=executor._LINUX_EXT_FILESYSTEM_MAGIC,
            watchdog_owned=True,
        )
        ipc_process = Process(78)
        ipc_watchdog = executor._IpcRuntimeWatchdogProcess(
            process=ipc_process,
            control_fd=22,
            ack_fd=23,
            namespace=namespace,
        )
        with mock.patch.object(
            executor,
            "_ipc_watchdog_roundtrip",
        ), mock.patch.object(
            executor,
            "_close_ipc_watchdog_transport",
            return_value=(),
        ), mock.patch.object(
            executor,
            "_attest_ipc_watchdog_namespace_unlinked",
            side_effect=executor.ExecutorContractError(
                "synthetic linked namespace"
            ),
        ), self.assertRaises(executor._DescriptorClosureError):
            ipc_watchdog.abort()
        self.assertEqual(ipc_process.kill_calls, 0)
        self.assertEqual(ipc_watchdog.terminal_returncode, 78)
        self.assertIs(ipc_watchdog.cleanup_ownership_retained, False)
        self.assertIs(namespace.watchdog_owned, False)

        container_process = Process(78)
        container_watchdog = executor._ContainerWatchdogProcess(
            process=container_process,
            control_fd=24,
        )
        with mock.patch.object(executor.os, "close"), self.assertRaises(
            executor._DescriptorClosureError
        ):
            container_watchdog.abort()
        self.assertEqual(container_process.kill_calls, 0)
        self.assertEqual(container_watchdog.terminal_returncode, 78)
        self.assertIs(container_watchdog.cleanup_ownership_retained, False)

    def test_dead_terminal_container_watchdog_takeover_recovers_before_marker_resolution(
        self,
    ) -> None:
        run_identity = "a" * 64
        container_name = f"vast-kpp-v2-np-{run_identity[:16]}-damage"
        labels = {
            executor.OWNER_LABEL: executor.OWNER_VALUE,
            executor.RUN_LABEL: run_identity,
            executor.BRANCH_LABEL: "damage",
        }
        validated_contract = {
            "operation_kind": "container_create",
            "operation_id": container_name,
            "run_identity_sha256": run_identity,
        }

        def dead_watchdog(*, terminal_marked: bool = True):
            process = mock.Mock()
            return executor._ContainerWatchdogProcess(
                process=process,
                control_fd=-1,
                closed=True,
                terminal_returncode=78,
                cleanup_ownership_retained=False,
                create_dispatch_marked=True,
                create_terminal_marked=terminal_marked,
                unresolved_operation_contract={"synthetic": True},
            )

        order: list[str] = []
        with mock.patch.object(
            executor,
            "_validate_unresolved_operation_contract",
            return_value=validated_contract,
        ), mock.patch.object(
            executor,
            "_recover_and_cleanup_owned_container_by_name",
            side_effect=lambda **_kwargs: order.append("recover"),
        ) as recover, mock.patch.object(
            executor,
            "_resolve_or_attest_unresolved_operation_marker",
            side_effect=lambda _contract: order.append("resolve"),
        ) as resolve:
            self.assertTrue(
                executor._take_over_dead_container_watchdog_cleanup(
                    runner=object(),
                    watchdog=dead_watchdog(),
                    container_name=container_name,
                    labels=labels,
                    expected_mounts={},
                    cleanup_mutex=executor._NullCleanupMutex(),
                    expected_image_labels=executor.IMAGE_LABELS,
                )
            )
            self.assertEqual(order, ["recover", "resolve"])
            recover.assert_called_once()
            resolve.assert_called_once_with(validated_contract)

        with mock.patch.object(
            executor,
            "_validate_unresolved_operation_contract",
            return_value=validated_contract,
        ), mock.patch.object(
            executor,
            "_recover_and_cleanup_owned_container_by_name",
            side_effect=RuntimeError("synthetic recovery failure"),
        ), mock.patch.object(
            executor,
            "_resolve_or_attest_unresolved_operation_marker",
        ) as resolve, self.assertRaisesRegex(
            RuntimeError, "synthetic recovery failure"
        ):
            executor._take_over_dead_container_watchdog_cleanup(
                runner=object(),
                watchdog=dead_watchdog(),
                container_name=container_name,
                labels=labels,
                expected_mounts={},
                cleanup_mutex=executor._NullCleanupMutex(),
                expected_image_labels=executor.IMAGE_LABELS,
            )
        resolve.assert_not_called()

        for watchdog in (
            dead_watchdog(terminal_marked=False),
            executor._ContainerWatchdogProcess(
                process=mock.Mock(),
                control_fd=-1,
                closed=True,
                terminal_returncode=None,
                cleanup_ownership_retained=True,
                create_dispatch_marked=True,
                create_terminal_marked=True,
                unresolved_operation_contract={"synthetic": True},
            ),
        ):
            with mock.patch.object(
                executor,
                "_validate_unresolved_operation_contract",
            ) as validate, mock.patch.object(
                executor,
                "_recover_and_cleanup_owned_container_by_name",
            ) as recover, mock.patch.object(
                executor,
                "_resolve_or_attest_unresolved_operation_marker",
            ) as resolve:
                self.assertFalse(
                    executor._take_over_dead_container_watchdog_cleanup(
                        runner=object(),
                        watchdog=watchdog,
                        container_name=container_name,
                        labels=labels,
                        expected_mounts={},
                        cleanup_mutex=executor._NullCleanupMutex(),
                        expected_image_labels=executor.IMAGE_LABELS,
                    )
                )
                validate.assert_not_called()
                recover.assert_not_called()
                resolve.assert_not_called()

    def test_container_watchdog_post_readiness_close_fault_still_recovers_name(
        self,
    ) -> None:
        cli = executor.FileIdentity(17, "1" * 64)
        daemon = {
            "daemon_id": "daemon",
            "server_version": "version",
            "api_version": "api",
        }
        contract = {
            "docker_cli": {
                "path": "/usr/bin/docker",
                "size_bytes": cli.size_bytes,
                "sha256": cli.sha256,
            },
            "daemon": daemon,
            "cleanup_mutex": {},
            "run_lease": {},
            "unresolved_operation": {},
            "container_name": "synthetic-container",
            "labels": {
                executor.OWNER_LABEL: executor.OWNER_VALUE,
                executor.RUN_LABEL: "2" * 64,
                executor.BRANCH_LABEL: "damage",
            },
            "expected_mounts": {},
            "image_labels": dict(executor.IMAGE_LABELS),
        }

        class Mutex:
            @contextmanager
            def hold(self):
                yield

        close_calls: list[int] = []
        retention_hold = mock.Mock()
        unresolved_hold = mock.Mock()

        def close(descriptor: int) -> None:
            close_calls.append(descriptor)
            if descriptor == 31:
                raise OSError("synthetic readiness close failure")

        with mock.patch.object(
            executor,
            "_read_exact_fd",
            side_effect=[(2).to_bytes(4, "big"), b"{}"],
        ), mock.patch.object(
            executor,
            "_validate_watchdog_contract",
            return_value=contract,
        ), mock.patch.object(
            executor,
            "_observe_regular_file",
            return_value=cli,
        ), mock.patch.object(
            executor,
            "_validate_daemon",
            return_value=daemon,
        ), mock.patch.object(
            executor,
            "_CleanupMutexReference",
            return_value=Mutex(),
        ), mock.patch.object(
            executor,
            "_validate_cleanup_mutex_contract",
            return_value={},
        ), mock.patch.object(
            executor,
            "_acquire_run_retention_hold",
            return_value=retention_hold,
        ), mock.patch.object(
            executor,
            "_acquire_unresolved_operation_marker_hold",
            return_value=unresolved_hold,
        ), mock.patch.object(
            executor.os,
            "write",
            return_value=1,
        ), mock.patch.object(
            executor.os,
            "read",
            return_value=b"",
        ), mock.patch.object(
            executor.os,
            "close",
            side_effect=close,
        ), mock.patch.object(
            executor,
            "_recover_and_cleanup_owned_container_by_name",
            return_value=None,
        ) as recover:
            status = executor._owned_container_watchdog_main(30, 31)
        self.assertEqual(status, 78)
        recover.assert_called_once()
        self.assertEqual(close_calls, [31, 30])

    def test_tensor_inventory_binds_whole_bundle_identity_and_segment_bounds(self) -> None:
        payload = b"x" * pilot.TENSOR_SEGMENT_BYTES
        request = {
            "request_id": "request-1",
            "tensor": {
                "path": "staging/synthetic/tensor.f32.bin",
                "size_bytes": pilot.TENSOR_SEGMENT_BYTES,
                "sha256": hashlib.sha256(payload).hexdigest(),
                "offset_bytes": 0,
                "segment_size_bytes": pilot.TENSOR_SEGMENT_BYTES,
                "segment_sha256": hashlib.sha256(payload).hexdigest(),
            },
        }
        valid = executor.TensorInventory(
            payloads={"request-1": payload},
            bundle_observations=[
                {
                    "path": "staging/synthetic/tensor.f32.bin",
                    "size_bytes": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
            ],
        )
        executor._validate_tensor_inventory(valid, [request])
        for mutation in ("sha256", "size_bytes", "offset"):
            with self.subTest(mutation=mutation):
                if mutation == "offset":
                    changed_request = {**request, "tensor": {**request["tensor"], "offset_bytes": 1}}
                    changed = valid
                else:
                    observation = dict(valid.bundle_observations[0])
                    observation[mutation] = "0" * 64 if mutation == "sha256" else len(payload) + 1
                    changed = executor.TensorInventory(
                        payloads=valid.payloads,
                        bundle_observations=[observation],
                    )
                    changed_request = request
                with self.assertRaises(executor.ExecutorContractError):
                    executor._validate_tensor_inventory(changed, [changed_request])

    def test_tensor_reader_rejects_project_local_path_outside_exact_candidate_root(self) -> None:
        request = {
            "request_id": "request-escape",
            "tensor": {
                "path": "staging/other/tensor.f32.bin",
                "size_bytes": pilot.TENSOR_SEGMENT_BYTES,
                "sha256": "1" * 64,
                "offset_bytes": 0,
            },
        }
        with self.assertRaisesRegex(executor.ExecutorContractError, "escaped the candidate root"):
            executor._read_selected_tensors(
                project_root=ROOT,
                candidate_root="staging/candidate",
                plan={"candidate": {"root": "staging/candidate"}},
                requests=[request],
            )

    def test_run_lease_path_builders_accept_concrete_path_subclasses(self) -> None:
        run_identity = "a" * 64
        parent = Path(tempfile.gettempdir()).resolve()
        paths = executor._run_lease_paths(run_identity, parent=parent)
        self.assertEqual(
            paths["identity"],
            parent / f"{executor._RUN_LEASE_IDENTITY_NAME_PREFIX}{run_identity}",
        )
        self.assertEqual(
            paths["admission"],
            parent
            / (
                executor._RUN_LEASE_ADMISSION_NAME_PREFIX
                + executor._run_lease_scope_sha256()[:48]
            ),
        )
        self.assertEqual(
            paths["retention"],
            parent
            / (
                executor._RUN_LEASE_RETENTION_NAME_PREFIX
                + executor._run_lease_scope_sha256()[:48]
            ),
        )
        self.assertEqual(
            executor._unresolved_operation_root_path(parent=parent),
            parent
            / (
                executor._UNRESOLVED_ROOT_NAME_PREFIX
                + executor._run_lease_scope_sha256()[:48]
            ),
        )

    def test_ipc_v3_provision_frame_fits_minimum_atomic_pipe_bound(self) -> None:
        run_identity = "b" * 64
        parent = Path(tempfile.gettempdir()).resolve()
        largest_identity = (1 << 63) - 1
        largest_owner = (1 << 32) - 1

        def state(
            *,
            mode: int,
            uid: int,
            gid: int,
            nlink: int,
            size: int = 0,
        ) -> object:
            return types.SimpleNamespace(
                st_dev=largest_identity,
                st_ino=largest_identity,
                st_mode=mode,
                st_uid=uid,
                st_gid=gid,
                st_nlink=nlink,
                st_size=size,
            )

        parent_state = state(
            mode=stat.S_IFDIR | 0o1777,
            uid=0,
            gid=0,
            nlink=2,
        )
        leaf_state = state(
            mode=stat.S_IFREG | 0o600,
            uid=largest_owner,
            gid=largest_owner,
            nlink=1,
        )
        root_state = state(
            mode=stat.S_IFDIR | 0o700,
            uid=largest_owner,
            gid=largest_owner,
            nlink=2,
        )
        marker_state = state(
            mode=stat.S_IFREG | 0o600,
            uid=largest_owner,
            gid=largest_owner,
            nlink=1,
        )
        real_run_lease_paths = executor._run_lease_paths
        real_unresolved_root_path = executor._unresolved_operation_root_path
        with (
            mock.patch.object(executor, "RUN_LEASE_PARENT", parent),
            mock.patch.object(executor, "_AF_UNIX_PATH_MAX_BYTES", 4096),
            mock.patch.object(
                executor,
                "_run_lease_paths",
                side_effect=lambda identity, parent=parent: real_run_lease_paths(
                    identity,
                    parent=parent,
                ),
            ),
            mock.patch.object(
                executor,
                "_unresolved_operation_root_path",
                side_effect=lambda parent=parent: real_unresolved_root_path(
                    parent=parent,
                ),
            ),
            mock.patch.object(
                executor.os,
                "getuid",
                create=True,
                return_value=largest_owner,
            ),
            mock.patch.object(
                executor.os,
                "getgid",
                create=True,
                return_value=largest_owner,
            ),
        ):
            run_lease_contract = executor._run_lease_contract(
                run_identity=run_identity,
                parent_state=parent_state,
                filesystem_magic=executor._LINUX_EXT_FILESYSTEM_MAGIC,
                leaf_states={
                    "identity": leaf_state,
                    "admission": leaf_state,
                    "retention": leaf_state,
                },
                unresolved_root_state=root_state,
                parent=parent,
            )
            operation_id = executor._ipc_unresolved_operation_id(
                run_identity,
                parent=parent,
            )
            unresolved_contract = (
                executor._unresolved_operation_marker_contract(
                    run_lease_contract=run_lease_contract,
                    operation_kind="ipc_namespace",
                    operation_id=operation_id,
                    marker_state=marker_state,
                )
            )
            request = executor._ipc_watchdog_provision_request(
                run_identity,
                parent=parent,
                run_lease_contract=run_lease_contract,
                unresolved_operation_contract=unresolved_contract,
            )
            framed = {
                **request,
                "self_sha256": hashlib.sha256(
                    executor.IPC_WATCHDOG_DOMAIN
                    + executor.canonical_line(request)
                ).hexdigest(),
            }
            payload = executor.canonical_line(framed)
        self.assertLessEqual(
            len(payload) + 4,
            4096,
            "IPC v3 provision must fit the POSIX minimum atomic pipe frame",
        )

    @unittest.skipUnless(os.name == "posix", "POSIX run lease contract")
    def test_run_lease_denies_same_identity_concurrency_and_releases(self) -> None:
        identity = hashlib.sha256(f"lease:{os.getpid()}:{time.time_ns()}".encode()).hexdigest()
        first = executor._acquire_run_lease(identity)
        try:
            with self.assertRaisesRegex(executor.ExecutorContractError, "already active"):
                executor._acquire_run_lease(identity)
        finally:
            first.release()
        second = executor._acquire_run_lease(identity)
        second.release()

    @unittest.skipUnless(os.name == "posix", "POSIX global retention lease contract")
    def test_global_retention_holds_block_different_run_until_every_independent_ofd_releases(
        self,
    ) -> None:
        first_identity = hashlib.sha256(
            f"retention:first:{os.getpid()}:{time.time_ns()}".encode()
        ).hexdigest()
        second_identity = hashlib.sha256(
            f"retention:second:{os.getpid()}:{time.time_ns()}".encode()
        ).hexdigest()
        unresolved_root = executor._unresolved_operation_root_path()
        first: executor._RunLease | None = None
        second: executor._RunLease | None = None
        hold_one: executor._RunRetentionHold | None = None
        hold_two: executor._RunRetentionHold | None = None
        try:
            first = executor._acquire_run_lease(first_identity)
            hold_one = executor._acquire_run_retention_hold(first.contract)
            hold_two = executor._acquire_run_retention_hold(first.contract)
            self.assertEqual(
                len(
                    {
                        first.retention_fd,
                        hold_one.retention_fd,
                        hold_two.retention_fd,
                    }
                ),
                3,
                "every actor must own a separate flock open-file description",
            )

            first.release()
            first = None
            with self.assertRaisesRegex(
                executor.ExecutorContractError,
                "retained cleanup ownership blocks global admission",
            ):
                executor._acquire_run_lease(second_identity)

            hold_one.close()
            hold_one = None
            with self.assertRaisesRegex(
                executor.ExecutorContractError,
                "retained cleanup ownership blocks global admission",
            ):
                executor._acquire_run_lease(second_identity)

            hold_two.close()
            hold_two = None
            second = executor._acquire_run_lease(second_identity)
            self.assertEqual(
                second.contract["global_scope_sha256"],
                executor._run_lease_scope_sha256(),
            )
            second.release()
            second = None
        finally:
            for actor in (hold_two, hold_one):
                if actor is not None and not actor.closed:
                    actor.close()
            for actor in (second, first):
                if actor is not None and not actor.released:
                    actor.release()
            self.assertEqual(os.listdir(unresolved_root), [])

    @unittest.skipUnless(os.name == "posix", "POSIX durable unresolved marker contract")
    def test_durable_unresolved_marker_blocks_fresh_run_after_all_flock_holders_die(
        self,
    ) -> None:
        first_identity = hashlib.sha256(
            f"marker:first:{os.getpid()}:{time.time_ns()}".encode()
        ).hexdigest()
        second_identity = hashlib.sha256(
            f"marker:second:{os.getpid()}:{time.time_ns()}".encode()
        ).hexdigest()
        container_name = f"vast-kpp-v2-np-{first_identity[:16]}-probe"
        unresolved_root = executor._unresolved_operation_root_path()
        first: executor._RunLease | None = None
        second: executor._RunLease | None = None
        reservation: executor._UnresolvedOperationMarkerReservation | None = None
        guardian: executor._UnresolvedOperationMarkerHold | None = None
        recovery: executor._UnresolvedOperationMarkerHold | None = None
        marker_contract: Mapping[str, object] | None = None
        try:
            first = executor._acquire_run_lease(first_identity)
            reservation = first.create_unresolved_container_marker(
                container_name=container_name,
            )
            marker_contract = dict(reservation.contract)
            guardian = executor._acquire_unresolved_operation_marker_hold(
                marker_contract
            )
            marker_name = str(
                executor._mapping(
                    marker_contract["marker"],
                    "test unresolved marker",
                )["name"]
            )
            marker_path = unresolved_root / marker_name
            self.assertTrue(marker_path.is_file())

            reservation.close()
            reservation = None
            first.release()
            first = None
            guardian.close()
            guardian = None

            # No process holds A or R now.  The immutable unresolved marker is
            # the durable crash boundary and must still deny a different run.
            with self.assertRaisesRegex(
                executor.ExecutorContractError,
                "durable unresolved operation blocks global admission",
            ):
                executor._acquire_run_lease(second_identity)
            self.assertTrue(marker_path.is_file())

            recovery = executor._acquire_unresolved_operation_marker_hold(
                marker_contract
            )
            recovery.resolve()
            recovery.close()
            recovery = None
            self.assertFalse(marker_path.exists())
            self.assertEqual(os.listdir(unresolved_root), [])

            second = executor._acquire_run_lease(second_identity)
            second.release()
            second = None
        finally:
            if recovery is not None and not recovery.closed:
                recovery.close()
            if guardian is not None and not guardian.closed:
                guardian.close()
            if reservation is not None and not reservation.closed:
                reservation.close()
            for actor in (second, first):
                if actor is not None and not actor.released:
                    actor.release()
            if (
                marker_contract is not None
                and os.path.isdir(unresolved_root)
                and os.listdir(unresolved_root)
            ):
                executor._resolve_or_attest_unresolved_operation_marker(
                    marker_contract
                )
            self.assertEqual(os.listdir(unresolved_root), [])

    @unittest.skipUnless(os.name == "posix", "POSIX unresolved marker observation")
    def test_unresolved_operation_observation_revalidates_held_marker_inode(
        self,
    ) -> None:
        run_identity = hashlib.sha256(
            f"marker-observation:{os.getpid()}:{time.time_ns()}".encode()
        ).hexdigest()
        container_name = f"vast-kpp-v2-np-{run_identity[:16]}-probe"
        lease: executor._RunLease | None = None
        reservation: executor._UnresolvedOperationMarkerReservation | None = None
        marker_name: str | None = None
        replacement_created = False
        try:
            lease = executor._acquire_run_lease(run_identity)
            reservation = lease.create_unresolved_container_marker(
                container_name=container_name,
            )
            marker = executor._mapping(
                reservation.contract["marker"],
                "test unresolved marker",
            )
            marker_name = str(marker["name"])
            before_handle = os.fstat(reservation.marker_fd)
            before_named = os.stat(
                marker_name,
                dir_fd=lease.unresolved_root_fd,
                follow_symlinks=False,
            )
            facts = executor._observe_unresolved_operation_root(lease)
            self.assertEqual(
                facts,
                {
                    "schema_version": 1,
                    "policy_id": "held_run_lease_unresolved_root_snapshot_v1",
                    "entry_count": 1,
                    "entry_name_sha256s": [
                        hashlib.sha256(marker_name.encode("ascii")).hexdigest()
                    ],
                    "exact_empty_attested": False,
                },
            )
            after_handle = os.fstat(reservation.marker_fd)
            after_named = os.stat(
                marker_name,
                dir_fd=lease.unresolved_root_fd,
                follow_symlinks=False,
            )
            self.assertEqual(
                (
                    before_handle.st_dev,
                    before_handle.st_ino,
                    before_handle.st_mode,
                    before_handle.st_uid,
                    before_handle.st_gid,
                    before_handle.st_nlink,
                    before_handle.st_size,
                ),
                (
                    after_handle.st_dev,
                    after_handle.st_ino,
                    after_handle.st_mode,
                    after_handle.st_uid,
                    after_handle.st_gid,
                    after_handle.st_nlink,
                    after_handle.st_size,
                ),
            )
            self.assertEqual(
                (before_named.st_dev, before_named.st_ino),
                (after_named.st_dev, after_named.st_ino),
            )
            self.assertFalse(reservation.closed)
            self.assertFalse(reservation.resolved)

            real_listdir = os.listdir
            list_calls = 0

            def replace_on_second_listdir(path: object) -> list[str]:
                nonlocal list_calls, replacement_created
                names = real_listdir(path)
                list_calls += 1
                if list_calls == 2:
                    os.unlink(marker_name, dir_fd=lease.unresolved_root_fd)
                    descriptor = os.open(
                        marker_name,
                        os.O_WRONLY
                        | os.O_CREAT
                        | os.O_EXCL
                        | getattr(os, "O_NOFOLLOW", 0)
                        | getattr(os, "O_CLOEXEC", 0),
                        0o600,
                        dir_fd=lease.unresolved_root_fd,
                    )
                    try:
                        os.fchmod(descriptor, 0o600)
                        os.fsync(descriptor)
                    finally:
                        os.close(descriptor)
                    os.fsync(lease.unresolved_root_fd)
                    replacement_created = True
                    return real_listdir(path)
                return names

            with mock.patch.object(
                executor.os,
                "listdir",
                side_effect=replace_on_second_listdir,
            ):
                with self.assertRaisesRegex(
                    executor.ExecutorContractError,
                    "unresolved operation marker changed during observation",
                ):
                    executor._observe_unresolved_operation_root(lease)
        finally:
            if replacement_created and lease is not None and marker_name is not None:
                replacement = os.stat(
                    marker_name,
                    dir_fd=lease.unresolved_root_fd,
                    follow_symlinks=False,
                )
                self.assertNotEqual(
                    (replacement.st_dev, replacement.st_ino),
                    (
                        os.fstat(reservation.marker_fd).st_dev,
                        os.fstat(reservation.marker_fd).st_ino,
                    ),
                )
                os.unlink(marker_name, dir_fd=lease.unresolved_root_fd)
                os.fsync(lease.unresolved_root_fd)
            if reservation is not None and not reservation.closed:
                if replacement_created:
                    with self.assertRaises(executor._DescriptorClosureError):
                        reservation.close()
                else:
                    reservation.close()
            if lease is not None and not lease.released:
                lease.release()
            self.assertEqual(
                os.listdir(executor._unresolved_operation_root_path()),
                [],
            )

    @unittest.skipUnless(os.name == "posix", "POSIX durable marker resolution guard")
    def test_marker_resolution_guard_blocks_admission_after_rename_fsync_failure(
        self,
    ) -> None:
        first_identity = hashlib.sha256(
            f"marker-guard:first:{os.getpid()}:{time.time_ns()}".encode()
        ).hexdigest()
        second_identity = hashlib.sha256(
            f"marker-guard:second:{os.getpid()}:{time.time_ns()}".encode()
        ).hexdigest()
        container_name = f"vast-kpp-v2-np-{first_identity[:16]}-probe"
        unresolved_root = executor._unresolved_operation_root_path()
        first: executor._RunLease | None = None
        second: executor._RunLease | None = None
        reservation: executor._UnresolvedOperationMarkerReservation | None = None
        marker_contract: Mapping[str, object] | None = None
        try:
            first = executor._acquire_run_lease(first_identity)
            reservation = first.create_unresolved_container_marker(
                container_name=container_name,
            )
            marker_contract = dict(reservation.contract)
            marker = executor._mapping(
                marker_contract["marker"],
                "test unresolved marker",
            )
            marker_path = unresolved_root / str(marker["name"])
            guard_path = unresolved_root / executor._unresolved_resolution_guard_name(
                marker_contract
            )
            real_fsync = os.fsync
            failed = False

            def fail_first_resolution_fsync(descriptor: int) -> None:
                nonlocal failed
                if descriptor == reservation.root_fd and not failed:
                    failed = True
                    raise OSError(errno.EIO, "synthetic marker-root fsync failure")
                real_fsync(descriptor)

            with mock.patch.object(
                executor.os,
                "fsync",
                side_effect=fail_first_resolution_fsync,
            ):
                with self.assertRaises(executor._DescriptorClosureError):
                    reservation.resolve()
            self.assertTrue(failed)
            self.assertFalse(marker_path.exists())
            self.assertTrue(guard_path.is_file())

            with self.assertRaises(executor._DescriptorClosureError):
                reservation.close()
            reservation = None
            first.release()
            first = None
            with self.assertRaisesRegex(
                executor.ExecutorContractError,
                "durable unresolved operation blocks global admission",
            ):
                executor._acquire_run_lease(second_identity)

            executor._resolve_or_attest_unresolved_operation_marker(
                marker_contract
            )
            self.assertFalse(marker_path.exists())
            self.assertFalse(guard_path.exists())
            self.assertEqual(os.listdir(unresolved_root), [])
            second = executor._acquire_run_lease(second_identity)
            second.release()
            second = None
        finally:
            if reservation is not None and not reservation.closed:
                try:
                    reservation.close()
                except executor._DescriptorClosureError:
                    pass
            for actor in (second, first):
                if actor is not None and not actor.released:
                    actor.release()
            if (
                marker_contract is not None
                and os.path.isdir(unresolved_root)
                and os.listdir(unresolved_root)
            ):
                executor._resolve_or_attest_unresolved_operation_marker(
                    marker_contract
                )
            self.assertEqual(os.listdir(unresolved_root), [])

    @unittest.skipUnless(os.name == "posix", "POSIX durable marker unwind contract")
    def test_container_watchdog_contract_failure_resolves_marker_before_dispatch(
        self,
    ) -> None:
        run_identity = hashlib.sha256(
            f"marker-unwind:{os.getpid()}:{time.time_ns()}".encode()
        ).hexdigest()
        container_name = f"vast-kpp-v2-np-{run_identity[:16]}-probe"
        labels = {
            executor.OWNER_LABEL: executor.OWNER_VALUE,
            executor.RUN_LABEL: run_identity,
            executor.BRANCH_LABEL: "runtime_probe",
        }
        with self._native_run_lease(run_identity) as run_lease:
            with self.assertRaisesRegex(
                executor.ExecutorContractError,
                "cleanup mutex actor contract is unavailable",
            ):
                executor._spawn_container_watchdog(
                    container_name=container_name,
                    labels=labels,
                    expected_mounts={},
                    docker_cli_identity=executor.FileIdentity(1, "f" * 64),
                    daemon={"synthetic": True},
                    cleanup_mutex=object(),
                    run_lease=run_lease,
                )
            self.assertEqual(
                os.listdir(executor._unresolved_operation_root_path()),
                [],
            )

    @unittest.skipUnless(os.name == "posix", "POSIX marker construction unwind contract")
    def test_local_marker_contract_failure_unlinks_exact_created_inode(self) -> None:
        class MarkerContractFailure(RuntimeError):
            pass

        run_identity = hashlib.sha256(
            f"marker-local-failure:{os.getpid()}:{time.time_ns()}".encode()
        ).hexdigest()
        container_name = f"vast-kpp-v2-np-{run_identity[:16]}-probe"
        with self._native_run_lease(run_identity) as run_lease, mock.patch.object(
            executor,
            "_unresolved_operation_marker_contract",
            side_effect=MarkerContractFailure(
                "synthetic marker contract projection failure"
            ),
        ):
            with self.assertRaises(MarkerContractFailure):
                run_lease.create_unresolved_container_marker(
                    container_name=container_name,
                )
            self.assertEqual(
                os.listdir(executor._unresolved_operation_root_path()),
                [],
            )

    def test_ambiguous_container_guardian_detaches_without_wait_or_kill(self) -> None:
        read_fd, write_fd = os.pipe()
        process = mock.Mock()
        process.poll.return_value = None
        watchdog = executor._ContainerWatchdogProcess(
            process=process,
            control_fd=write_fd,
            unresolved_operation_contract={"synthetic": True},
        )
        try:
            watchdog.mark_create_dispatch()
            watchdog.detach_ambiguous_owner()
            self.assertEqual(os.read(read_fd, 2), b"D")
            self.assertEqual(os.read(read_fd, 1), b"")
            self.assertTrue(watchdog.closed)
            self.assertTrue(watchdog.cleanup_ownership_retained)
            self.assertTrue(watchdog.ambiguous_owner_detached)
            self.assertIsNone(watchdog.terminal_returncode)
            process.poll.assert_called_once_with()
            process.wait.assert_not_called()
            process.kill.assert_not_called()
        finally:
            os.close(read_fd)

    def test_model_files_are_independently_rehashed_and_nonlink_bound(self) -> None:
        bindings: dict[str, dict[str, object]] = {}
        sources: dict[str, Path] = {}
        engines: dict[str, Path] = {}
        source_identities: dict[str, executor.FileIdentity] = {}
        engine_identities: dict[str, executor.FileIdentity] = {}
        for branch in pilot.BRANCHES:
            source_sha = hashlib.sha256(f"source:{branch}".encode()).hexdigest()
            bindings[branch] = {"source_model_sha256": source_sha}
            sources[branch] = Path(f"/synthetic/{branch}.onnx")
            engines[branch] = Path(f"/synthetic/{branch}.engine")
            source_identities[branch] = executor.FileIdentity(123, source_sha)
            pin = pilot.TENSORRT_ENGINE_PINS[branch]
            engine_identities[branch] = executor.FileIdentity(
                int(pin["size_bytes"]), str(pin["engine_sha256"])
            )
        inventory = executor.BindingInventory(
            bindings=bindings,
            source_paths=sources,
            engine_paths=engines,
            source_identities=source_identities,
            engine_identities=engine_identities,
            manifest_identity_sha256="d" * 64,
            execution_config_identity_sha256="e" * 64,
        )
        observed = {
            **{str(sources[branch]): source_identities[branch] for branch in pilot.BRANCHES},
            **{str(engines[branch]): engine_identities[branch] for branch in pilot.BRANCHES},
        }
        executor._validate_binding_file_identities(
            inventory,
            lambda path: observed[str(path)],
        )
        first = str(sources[pilot.BRANCHES[0]])
        observed[first] = executor.FileIdentity(
            observed[first].size_bytes,
            observed[first].sha256,
            is_regular_file=True,
            is_symlink=True,
        )
        with self.assertRaises(executor.ExecutorContractError):
            executor._validate_binding_file_identities(
                inventory,
                lambda path: observed[str(path)],
            )

    def test_watched_listener_cleanup_never_parent_unlinks_and_release_is_independent(self) -> None:
        class CloseFailure(BaseException):
            pass

        lock = threading.Lock()
        listener = mock.Mock()
        watchdog = mock.Mock()
        with mock.patch.object(
            executor,
            "_unlink_owned_ipc_socket",
            side_effect=AssertionError("controller must not unlink a watcher-owned socket"),
        ) as parent_unlink:
            executor._close_watched_ipc_listener(
                listener=listener,
                ipc_watchdog=watchdog,
                ipc_control_lock=lock,
                branch="damage",
                registered=False,
            )
        listener.close.assert_called_once_with()
        watchdog.release.assert_not_called()
        parent_unlink.assert_not_called()

        listener = mock.Mock()
        listener.close.side_effect = CloseFailure()
        watchdog = mock.Mock()
        with self.assertRaises(executor._ExecutionFailureBundle) as raised:
            executor._close_watched_ipc_listener(
                listener=listener,
                ipc_watchdog=watchdog,
                ipc_control_lock=lock,
                branch="foreign_object",
                registered=True,
            )
        self.assertIsInstance(raised.exception.primary, CloseFailure)
        self.assertEqual(raised.exception.primary_phase, "final_cleanup")
        self.assertEqual(raised.exception.primary_stage, "ipc_listener_close")
        self.assertEqual(raised.exception.primary_branch, "foreign_object")
        listener.close.assert_called_once_with()
        watchdog.release.assert_called_once_with("foreign_object")

    @unittest.skipUnless(os.name == "posix", "native POSIX IPC custody contract")
    def test_native_ipc_namespace_is_held_create_new_mode_bound_and_symlink_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            parent = Path(raw) / "native"
            parent.mkdir(mode=0o700)
            run_identity = "1" * 64
            expected = executor._ipc_runtime_path(run_identity, parent=parent)
            namespace = executor._create_ipc_runtime_namespace(
                run_identity,
                parent=parent,
            )
            try:
                self.assertEqual(namespace.path, expected)
                observed = expected.lstat()
                self.assertTrue(stat.S_ISDIR(observed.st_mode))
                self.assertEqual(stat.S_IMODE(observed.st_mode), 0o700)
                self.assertEqual(observed.st_uid, os.getuid())
                self.assertEqual(os.listdir(namespace.root_fd), [])
                self.assertEqual(
                    (observed.st_dev, observed.st_ino),
                    (os.fstat(namespace.root_fd).st_dev, os.fstat(namespace.root_fd).st_ino),
                )
                for name in (
                    executor._IPC_CAPABILITY_SOCKET_NAME,
                    *(f"{branch}.sock" for branch in pilot.BRANCHES),
                ):
                    encoded = os.fsencode(namespace.path / name)
                    self.assertNotIn(b"\0", encoded)
                    self.assertLessEqual(
                        len(encoded),
                        executor._AF_UNIX_PATH_MAX_BYTES,
                    )
            finally:
                executor._destroy_ipc_runtime_namespace(namespace)
            self.assertFalse(expected.exists())

            preexisting = executor._ipc_runtime_path("2" * 64, parent=parent)
            preexisting.mkdir(mode=0o700)
            with self.assertRaisesRegex(
                executor.ExecutorContractError,
                "already exists",
            ):
                executor._create_ipc_runtime_namespace("2" * 64, parent=parent)
            self.assertTrue(preexisting.is_dir())
            preexisting.rmdir()

            target = parent / "unrelated"
            target.mkdir(mode=0o700)
            symlink = executor._ipc_runtime_path("3" * 64, parent=parent)
            symlink.symlink_to(target, target_is_directory=True)
            with self.assertRaisesRegex(
                executor.ExecutorContractError,
                "already exists",
            ):
                executor._create_ipc_runtime_namespace("3" * 64, parent=parent)
            self.assertTrue(symlink.is_symlink())
            self.assertEqual(list(target.iterdir()), [])
            symlink.unlink()

            linked_parent = Path(raw) / "linked-native"
            linked_parent.symlink_to(parent, target_is_directory=True)
            with self.assertRaisesRegex(
                executor.ExecutorContractError,
                "parent",
            ):
                executor._create_ipc_runtime_namespace("4" * 64, parent=linked_parent)

            long_parent = parent / ("x" * 96)
            with self.assertRaisesRegex(
                executor.ExecutorContractError,
                "AF_UNIX path",
            ):
                executor._ipc_runtime_path("5" * 64, parent=long_parent)

    @unittest.skipUnless(os.name == "posix", "native POSIX IPC listener cleanup contract")
    def test_ipc_bind_and_listen_baseexceptions_close_fd_and_remove_socket(self) -> None:
        class Cancellation(BaseException):
            pass

        with tempfile.TemporaryDirectory() as raw:
            parent = Path(raw) / "native"
            parent.mkdir(mode=0o700)
            namespace = executor._create_ipc_runtime_namespace("6" * 64, parent=parent)
            try:
                class BindFailure:
                    def __init__(self) -> None:
                        self.closed = False

                    def settimeout(self, _seconds: float) -> None:
                        return None

                    def bind(self, _path: str) -> None:
                        raise OSError("synthetic bind failure")

                    def close(self) -> None:
                        self.closed = True

                bind_failure = BindFailure()
                with self.assertRaisesRegex(
                    executor.ExecutorContractError,
                    "cannot create exact IPC listener",
                ):
                    executor._open_ipc_listener(
                        namespace,
                        "damage",
                        socket_factory=lambda *_args: bind_failure,
                    )
                self.assertTrue(bind_failure.closed)
                self.assertEqual(os.listdir(namespace.root_fd), [])

                class ListenFailure:
                    def __init__(self) -> None:
                        self.inner = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
                        self.closed = False

                    def settimeout(self, seconds: float) -> None:
                        self.inner.settimeout(seconds)

                    def bind(self, path: str) -> None:
                        self.inner.bind(path)

                    def listen(self, _backlog: int) -> None:
                        raise Cancellation()

                    def close(self) -> None:
                        self.inner.close()
                        self.closed = True

                listen_failure = ListenFailure()
                with self.assertRaises(Cancellation):
                    executor._open_ipc_listener(
                        namespace,
                        "foreign_object",
                        socket_factory=lambda *_args: listen_failure,
                    )
                self.assertTrue(listen_failure.closed)
                self.assertEqual(os.listdir(namespace.root_fd), [])
            finally:
                executor._destroy_ipc_runtime_namespace(namespace)

    @unittest.skipUnless(os.name == "posix", "POSIX IPC marker cross-bind contract")
    def test_ipc_namespace_rejects_container_marker_as_cleanup_authority(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            parent = Path(raw) / "native"
            parent.mkdir(mode=0o700)
            run_identity = hashlib.sha256(
                f"ipc-marker-crossbind:{os.getpid()}:{time.time_ns()}".encode()
            ).hexdigest()
            container_name = f"vast-kpp-v2-np-{run_identity[:16]}-probe"
            with self._native_run_lease(run_identity) as run_lease:
                reservation = run_lease.create_unresolved_container_marker(
                    container_name=container_name,
                )
                namespace = executor._create_ipc_runtime_namespace(
                    run_identity,
                    parent=parent,
                )
                try:
                    namespace.unresolved_operation_contract = dict(
                        reservation.contract
                    )
                    with self.assertRaisesRegex(
                        executor.ExecutorContractError,
                        "IPC unresolved operation cross-bind drifted",
                    ):
                        executor._validate_ipc_runtime_namespace(namespace)
                    namespace.unresolved_operation_contract = None
                    executor._destroy_ipc_runtime_namespace(namespace)
                    reservation.resolve()
                    reservation.close()
                finally:
                    if not namespace.closed:
                        namespace.unresolved_operation_contract = None
                        executor._destroy_ipc_runtime_namespace(namespace)
                    if not reservation.closed:
                        if not reservation.resolved:
                            reservation.resolve()
                        reservation.close()

    @unittest.skipUnless(os.name == "posix", "POSIX IPC cleanup durability contract")
    def test_ipc_parent_fsync_failure_preserves_unresolved_admission_blocker(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            parent = Path(raw) / "native"
            parent.mkdir(mode=0o700)
            first_identity = hashlib.sha256(
                f"ipc-fsync:first:{os.getpid()}:{time.time_ns()}".encode()
            ).hexdigest()
            second_identity = hashlib.sha256(
                f"ipc-fsync:second:{os.getpid()}:{time.time_ns()}".encode()
            ).hexdigest()
            unresolved_root = executor._unresolved_operation_root_path()
            first: executor._RunLease | None = None
            second: executor._RunLease | None = None
            reservation: executor._UnresolvedOperationMarkerReservation | None = None
            marker_contract: Mapping[str, object] | None = None
            namespace: executor._IpcRuntimeNamespace | None = None
            try:
                first = executor._acquire_run_lease(first_identity)
                reservation = first.create_unresolved_ipc_marker(parent=parent)
                marker_contract = dict(reservation.contract)
                reservation.close()
                reservation = None
                namespace = executor._create_ipc_runtime_namespace(
                    first_identity,
                    parent=parent,
                )
                namespace.unresolved_operation_contract = marker_contract
                parent_fd = namespace.parent_fd
                real_fsync = os.fsync
                failed = False

                def fail_parent_fsync(descriptor: int) -> None:
                    nonlocal failed
                    if descriptor == parent_fd and not failed:
                        failed = True
                        raise OSError(errno.EIO, "synthetic IPC parent fsync failure")
                    real_fsync(descriptor)

                with mock.patch.object(
                    executor.os,
                    "fsync",
                    side_effect=fail_parent_fsync,
                ):
                    with self.assertRaises(executor._DescriptorClosureError):
                        executor._destroy_ipc_runtime_namespace(namespace)
                self.assertTrue(failed)
                self.assertTrue(namespace.closed)
                self.assertFalse(namespace.path.exists())
                self.assertEqual(len(os.listdir(unresolved_root)), 1)

                first.release()
                first = None
                with self.assertRaisesRegex(
                    executor.ExecutorContractError,
                    "durable unresolved operation blocks global admission",
                ):
                    executor._acquire_run_lease(second_identity)
                executor._durably_attest_ipc_namespace_absent(
                    first_identity,
                    parent=parent,
                )
                executor._resolve_or_attest_unresolved_operation_marker(
                    marker_contract
                )
                self.assertEqual(os.listdir(unresolved_root), [])
                second = executor._acquire_run_lease(second_identity)
                second.release()
                second = None
            finally:
                if namespace is not None and not namespace.closed:
                    namespace.unresolved_operation_contract = None
                    executor._destroy_ipc_runtime_namespace(namespace)
                if reservation is not None and not reservation.closed:
                    reservation.close()
                for actor in (second, first):
                    if actor is not None and not actor.released:
                        actor.release()
                if (
                    marker_contract is not None
                    and os.path.isdir(unresolved_root)
                    and os.listdir(unresolved_root)
                ):
                    executor._durably_attest_ipc_namespace_absent(
                        first_identity,
                        parent=parent,
                    )
                    executor._resolve_or_attest_unresolved_operation_marker(
                        marker_contract
                    )
                self.assertEqual(os.listdir(unresolved_root), [])

    @unittest.skipUnless(os.name == "posix", "native POSIX IPC watchdog contract")
    def test_ipc_watchdog_register_release_abort_and_unknown_entry_are_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            parent = Path(raw) / "native"
            parent.mkdir(mode=0o700)

            with self._native_run_lease("7" * 64) as run_lease:
                watchdog = executor._spawn_ipc_runtime_watchdog(
                    "7" * 64, parent=parent, run_lease=run_lease
                )
                namespace = watchdog.namespace
                listener = executor._open_ipc_listener(namespace, "damage")
                watchdog.register("damage")
                listener.close()
                watchdog.release("damage")
                watchdog.complete()
                self.assertTrue(namespace.unlinked)
                self.assertFalse(namespace.path.exists())
                executor._destroy_ipc_runtime_namespace(namespace)

            with self._native_run_lease("8" * 64) as run_lease:
                watchdog = executor._spawn_ipc_runtime_watchdog(
                    "8" * 64, parent=parent, run_lease=run_lease
                )
                namespace = watchdog.namespace
                listener = executor._open_ipc_listener(
                    namespace, "foreign_object"
                )
                listener.close()
                watchdog.abort()
                self.assertTrue(namespace.unlinked)
                self.assertFalse(namespace.path.exists())
                executor._destroy_ipc_runtime_namespace(namespace)

            namespace = executor._create_ipc_runtime_namespace("c" * 64, parent=parent)
            contract = executor._ipc_watchdog_contract(namespace)
            real_rmdir = os.rmdir
            attempts = 0

            def busy_then_release(path: object, *args: object, **kwargs: object) -> None:
                nonlocal attempts
                attempts += 1
                if attempts <= 3:
                    raise OSError(errno.EBUSY, "synthetic bind-mount hold")
                real_rmdir(path, *args, **kwargs)

            with (
                mock.patch.object(os, "rmdir", side_effect=busy_then_release),
                mock.patch.object(
                    time,
                    "monotonic",
                    side_effect=AssertionError("watchdog must retain cleanup ownership"),
                ),
            ):
                executor._ipc_watchdog_remove_owned_namespace(
                    contract,
                    {},
                    require_empty=True,
                )
            namespace.unlinked = True
            self.assertEqual(attempts, 4)
            self.assertFalse(namespace.path.exists())
            executor._destroy_ipc_runtime_namespace(namespace)

            with self._native_run_lease("9" * 64) as run_lease:
                watchdog = executor._spawn_ipc_runtime_watchdog(
                    "9" * 64, parent=parent, run_lease=run_lease
                )
                namespace = watchdog.namespace
                listener = executor._open_ipc_listener(namespace, "plate_number")
                watchdog.register("plate_number")
                listener.close()
                unknown = namespace.path / "unknown"
                executor._write_new(unknown, b"unknown", mode=0o600)
                with self.assertRaises(
                    executor._DescriptorClosureError
                ) as raised:
                    watchdog.abort()
                self.assertEqual(
                    raised.exception.operation,
                    "ipc_watchdog_finish",
                )
                self.assertIsInstance(
                    raised.exception.primary,
                    executor._DescriptorClosureError,
                )
                self.assertEqual(
                    raised.exception.primary.operation,
                    "ipc_watchdog_roundtrip",
                )
                self.assertEqual(watchdog.terminal_returncode, 78)
                self.assertIs(watchdog.cleanup_ownership_retained, False)
                self.assertIs(namespace.watchdog_owned, False)
                self.assertTrue(namespace.path.is_dir())
                self.assertTrue(unknown.is_file())
                unknown.unlink()
                executor._destroy_ipc_runtime_namespace(namespace)

            rejected_path = executor._ipc_runtime_path("a" * 64, parent=parent)
            with mock.patch.object(
                executor,
                "_linux_fstatfs_magic",
                return_value=0x01021997,
            ):
                with self.assertRaisesRegex(
                    executor.ExecutorContractError,
                    "directory identity drifted",
                ):
                    executor._create_ipc_runtime_namespace("a" * 64, parent=parent)
            self.assertFalse(rejected_path.exists())

            preexisting = executor._ipc_runtime_path("b" * 64, parent=parent)
            preexisting.mkdir(mode=0o700)
            with self._native_run_lease("b" * 64) as run_lease:
                with self.assertRaises(executor.ExecutorContractError):
                    executor._spawn_ipc_runtime_watchdog(
                        "b" * 64,
                        parent=parent,
                        run_lease=run_lease,
                    )
                self.assertTrue(preexisting.is_dir())
                self.assertEqual(list(preexisting.iterdir()), [])
                unresolved_root = executor._unresolved_operation_root_path()
                marker_name = executor._unresolved_marker_name(
                    run_identity="b" * 64,
                    operation_kind="ipc_namespace",
                    operation_id=executor._ipc_unresolved_operation_id(
                        "b" * 64,
                        parent=parent,
                    ),
                )
                self.assertEqual(os.listdir(unresolved_root), [marker_name])
                marker_state = (unresolved_root / marker_name).lstat()
                unresolved_contract = (
                    executor._unresolved_operation_marker_contract(
                        run_lease_contract=run_lease.contract,
                        operation_kind="ipc_namespace",
                        operation_id=executor._ipc_unresolved_operation_id(
                            "b" * 64,
                            parent=parent,
                        ),
                        marker_state=marker_state,
                    )
                )
                preexisting.rmdir()
                executor._durably_attest_ipc_namespace_absent(
                    "b" * 64,
                    parent=parent,
                )
                executor._resolve_or_attest_unresolved_operation_marker(
                    unresolved_contract
                )
                self.assertEqual(os.listdir(unresolved_root), [])

    @unittest.skipUnless(os.name == "posix", "POSIX IPC durable guardian crash contract")
    def test_dead_ipc_guardian_marker_blocks_different_run_until_controller_exact_cleanup(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            parent = Path(raw) / "native"
            parent.mkdir(mode=0o700)
            first_identity = hashlib.sha256(
                f"ipc-crash:first:{os.getpid()}:{time.time_ns()}".encode()
            ).hexdigest()
            second_identity = hashlib.sha256(
                f"ipc-crash:second:{os.getpid()}:{time.time_ns()}".encode()
            ).hexdigest()
            unresolved_root = executor._unresolved_operation_root_path()
            first: executor._RunLease | None = None
            second: executor._RunLease | None = None
            watchdog: executor._IpcRuntimeWatchdogProcess | None = None
            try:
                first = executor._acquire_run_lease(first_identity)
                watchdog = executor._spawn_ipc_runtime_watchdog(
                    first_identity,
                    parent=parent,
                    run_lease=first,
                )
                namespace = watchdog.namespace
                marker_contract = executor._validate_unresolved_operation_contract(
                    executor._mapping(
                        namespace.unresolved_operation_contract,
                        "test IPC unresolved operation",
                    )
                )
                self.assertEqual(
                    marker_contract["operation_id"],
                    executor._ipc_unresolved_operation_id(
                        first_identity,
                        parent=parent,
                    ),
                )
                watchdog.process.kill()
                child_returncode = watchdog.process.wait(timeout=15)
                self.assertNotEqual(child_returncode, 0)
                for field_name in ("control_fd", "ack_fd"):
                    descriptor = getattr(watchdog, field_name)
                    setattr(watchdog, field_name, -1)
                    os.close(descriptor)
                watchdog.closed = True
                watchdog.terminal_returncode = child_returncode
                watchdog.cleanup_ownership_retained = False

                first.release()
                first = None
                self.assertTrue(namespace.path.is_dir())
                self.assertEqual(len(os.listdir(unresolved_root)), 1)
                with self.assertRaisesRegex(
                    executor.ExecutorContractError,
                    "durable unresolved operation blocks global admission",
                ):
                    executor._acquire_run_lease(second_identity)

                namespace.watchdog_owned = False
                executor._destroy_ipc_runtime_namespace(namespace)
                self.assertTrue(namespace.closed)
                self.assertFalse(namespace.path.exists())
                self.assertEqual(os.listdir(unresolved_root), [])

                second = executor._acquire_run_lease(second_identity)
                second.release()
                second = None
            finally:
                if watchdog is not None:
                    if watchdog.process.poll() is None:
                        watchdog.process.kill()
                        watchdog.process.wait(timeout=15)
                    for field_name in ("control_fd", "ack_fd"):
                        descriptor = getattr(watchdog, field_name)
                        if descriptor >= 0:
                            setattr(watchdog, field_name, -1)
                            os.close(descriptor)
                    namespace = watchdog.namespace
                    if not namespace.closed:
                        namespace.watchdog_owned = False
                        executor._destroy_ipc_runtime_namespace(namespace)
                for actor in (second, first):
                    if actor is not None and not actor.released:
                        actor.release()
                self.assertEqual(os.listdir(unresolved_root), [])

    @unittest.skipUnless(os.name == "posix", "POSIX IPC watchdog ambiguity contract")
    def test_ipc_watchdog_control_commit_ambiguity_closes_to_eof_without_sequence_reuse(self) -> None:
        cases = (
            "register_write_before",
            "register_write_partial",
            "register_write_after",
            "register_ack_lost",
            "register_ack_eof",
            "register_ack_malformed",
            "release_write_before",
            "release_write_partial",
            "release_write_after",
            "release_ack_lost",
            "release_ack_eof",
            "release_ack_malformed",
        )
        with tempfile.TemporaryDirectory() as raw:
            parent = Path(raw) / "native"
            parent.mkdir(mode=0o700)
            for ordinal, case in enumerate(cases, start=1):
                with self.subTest(case=case):
                    run_identity = hashlib.sha256(f"ambiguity:{ordinal}".encode()).hexdigest()
                    lease_context = self._native_run_lease(run_identity)
                    run_lease = lease_context.__enter__()
                    watchdog = executor._spawn_ipc_runtime_watchdog(
                        run_identity,
                        parent=parent,
                        run_lease=run_lease,
                    )
                    namespace = watchdog.namespace
                    listener = executor._open_ipc_listener(namespace, "damage")
                    if case.startswith("release_"):
                        watchdog.register("damage")
                    actions: list[str] = []
                    injected = False
                    real_frame_writer = executor._write_ipc_watchdog_frame
                    real_read = os.read

                    def ambiguous_writer(
                        descriptor: int,
                        core: Mapping[str, object],
                    ) -> None:
                        nonlocal injected
                        action = str(core["action"])
                        actions.append(action)
                        target = "release" if case.startswith("release_") else "register"
                        if action != target or injected:
                            real_frame_writer(descriptor, core)
                            return
                        if case.endswith("write_before"):
                            injected = True
                            raise OSError(errno.EPIPE, "synthetic pre-commit write failure")
                        if case.endswith("write_partial"):
                            injected = True
                            self.assertEqual(os.write(descriptor, b"\0\0"), 2)
                            raise OSError(errno.EIO, "synthetic partial-frame write failure")
                        if case.endswith("write_after"):
                            real_frame_writer(descriptor, core)
                            injected = True
                            raise OSError(errno.EIO, "synthetic post-commit write failure")
                        real_frame_writer(descriptor, core)

                    def ambiguous_read(descriptor: int, count: int) -> bytes:
                        nonlocal injected
                        value = real_read(descriptor, count)
                        if (
                            descriptor == watchdog.ack_fd
                            and count == 2
                            and not injected
                            and case.endswith(("ack_lost", "ack_eof", "ack_malformed"))
                        ):
                            self.assertEqual(value, b"K")
                            injected = True
                            if case.endswith("ack_lost"):
                                raise OSError(errno.EIO, "synthetic lost acknowledgement")
                            if case.endswith("ack_eof"):
                                return b""
                            return b"X"
                        return value

                    operation_error: BaseException | None = None
                    cleanup_error: BaseException | None = None
                    try:
                        with (
                            mock.patch.object(
                                executor,
                                "_write_ipc_watchdog_frame",
                                side_effect=ambiguous_writer,
                            ),
                            mock.patch.object(os, "read", side_effect=ambiguous_read),
                        ):
                            try:
                                if case.startswith("release_"):
                                    listener.close()
                                    watchdog.release("damage")
                                else:
                                    watchdog.register("damage")
                            except BaseException as error:
                                operation_error = error
                            try:
                                if not case.startswith("release_"):
                                    listener.close()
                                watchdog.abort()
                            except BaseException as error:
                                cleanup_error = error
                    finally:
                        try:
                            listener.close()
                        except BaseException:
                            pass
                        if watchdog.process.poll() is None:
                            for descriptor in (watchdog.control_fd, watchdog.ack_fd):
                                if descriptor >= 0:
                                    try:
                                        os.close(descriptor)
                                    except OSError:
                                        pass
                            watchdog.process.wait(timeout=15)
                        if not namespace.path.exists():
                            namespace.unlinked = True
                        if not namespace.closed:
                            executor._destroy_ipc_runtime_namespace(namespace)
                        lease_context.__exit__(None, None, None)
                    self.assertIsInstance(operation_error, executor.ExecutorContractError)
                    self.assertIsNone(cleanup_error)
                    self.assertTrue(injected)
                    self.assertEqual(
                        actions,
                        ["release" if case.startswith("release_") else "register"],
                    )
                    self.assertTrue(watchdog.closed)
                    self.assertTrue(watchdog.protocol_poisoned)
                    if case.startswith("release_"):
                        self.assertIn("damage", watchdog.registered)
                        self.assertNotIn("damage", watchdog.pending)
                    else:
                        self.assertNotIn("damage", watchdog.registered)
                        self.assertIn("damage", watchdog.pending)
                    self.assertFalse(namespace.path.exists())
                    self.assertIsNotNone(watchdog.process.returncode)

            terminal_cases = (
                "write_before",
                "write_partial",
                "write_after",
                "ack_lost",
                "ack_eof",
                "ack_malformed",
            )
            for ordinal, case in enumerate(terminal_cases, start=1):
                with self.subTest(terminal_case=case):
                    terminal_identity = hashlib.sha256(
                        f"ambiguity:terminal:{ordinal}".encode()
                    ).hexdigest()
                    terminal_lease_context = self._native_run_lease(
                        terminal_identity
                    )
                    terminal_run_lease = terminal_lease_context.__enter__()
                    terminal = executor._spawn_ipc_runtime_watchdog(
                        terminal_identity,
                        parent=parent,
                        run_lease=terminal_run_lease,
                    )
                    terminal_root = terminal.namespace.path
                    real_frame_writer = executor._write_ipc_watchdog_frame
                    real_read = os.read
                    injected = False
                    actions: list[str] = []

                    def ambiguous_terminal_writer(
                        descriptor: int,
                        core: Mapping[str, object],
                    ) -> None:
                        nonlocal injected
                        actions.append(str(core["action"]))
                        if case == "write_before" and not injected:
                            injected = True
                            raise OSError(errno.EPIPE, "synthetic terminal pre-commit failure")
                        if case == "write_partial" and not injected:
                            injected = True
                            self.assertEqual(os.write(descriptor, b"\0\0"), 2)
                            raise OSError(errno.EIO, "synthetic terminal partial-frame failure")
                        real_frame_writer(descriptor, core)
                        if case == "write_after" and not injected:
                            injected = True
                            raise OSError(errno.EIO, "synthetic terminal post-commit failure")

                    def ambiguous_terminal_read(descriptor: int, count: int) -> bytes:
                        nonlocal injected
                        value = real_read(descriptor, count)
                        if (
                            descriptor == terminal.ack_fd
                            and count == 2
                            and not injected
                            and case in {"ack_lost", "ack_eof", "ack_malformed"}
                        ):
                            self.assertEqual(value, b"K")
                            injected = True
                            if case == "ack_lost":
                                raise OSError(errno.EIO, "synthetic terminal lost ACK")
                            if case == "ack_eof":
                                return b""
                            return b"X"
                        return value

                    with (
                        mock.patch.object(
                            executor,
                            "_write_ipc_watchdog_frame",
                            side_effect=ambiguous_terminal_writer,
                        ),
                        mock.patch.object(
                            os,
                            "read",
                            side_effect=ambiguous_terminal_read,
                        ),
                    ):
                        with self.assertRaises(executor.ExecutorContractError):
                            terminal.complete()
                    self.assertTrue(injected)
                    self.assertEqual(actions, ["complete"])
                    self.assertTrue(terminal.closed)
                    self.assertTrue(terminal.protocol_poisoned)
                    self.assertFalse(terminal_root.exists())
                    self.assertIsNotNone(terminal.process.returncode)
                    executor._destroy_ipc_runtime_namespace(terminal.namespace)
                    terminal_lease_context.__exit__(None, None, None)

    @unittest.skipUnless(os.name == "posix", "non-native WSL filesystem rejection")
    def test_default_watchdog_provisioner_rejects_non_native_workspace_filesystem(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            parent = Path(raw)
            descriptor = os.open(
                parent,
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0),
            )
            try:
                filesystem_magic = executor._linux_fstatfs_magic(descriptor)
            finally:
                os.close(descriptor)
            if filesystem_magic == executor._LINUX_EXT_FILESYSTEM_MAGIC:
                self.skipTest("workspace filesystem is already native Linux ext")
            run_identity = hashlib.sha256(os.fsencode(parent)).hexdigest()
            expected = executor._ipc_runtime_path(run_identity, parent=parent)
            with self._native_run_lease(
                run_identity
            ) as run_lease, mock.patch.object(
                executor.subprocess,
                "Popen",
                side_effect=AssertionError(
                    "unsupported IPC parent must reject before child spawn"
                ),
            ) as popen:
                with self.assertRaises(executor.ExecutorContractError):
                    executor._spawn_ipc_runtime_watchdog(
                        run_identity,
                        parent=parent,
                        run_lease=run_lease,
                    )
            popen.assert_not_called()
            self.assertFalse(expected.exists())

    @unittest.skipUnless(os.name == "posix", "POSIX IPC controller-death watchdog matrix")
    def test_controller_sigkill_ipc_watchdog_cleans_root_before_ready_and_after_n_sockets(self) -> None:
        controller_source = f"""
import json, os, sys, time
from pathlib import Path
sys.path.insert(0, {str(SCRIPTS)!r})
import kpp_legacy_iss_v2_secondary_sensitivity_executor as e
parent = Path(sys.argv[1])
phase = sys.argv[2]
count = int(sys.argv[3])
ready = Path(sys.argv[4])
identity = sys.argv[5]
run_lease = e._acquire_run_lease(identity)
root = e._ipc_runtime_path(identity, parent=parent)
def signal_armed(pid):
    if root.exists():
        raise SystemExit(97)
    e._write_new(ready, e.canonical_line({{'watchdog_pid': pid, 'phase': phase, 'count': count, 'root_exists': False}}))
    time.sleep(600)
def signal_provisioned(pid):
    deadline = time.monotonic() + 15
    while not root.is_dir() and time.monotonic() < deadline:
        time.sleep(0.01)
    if not root.is_dir():
        raise SystemExit(96)
    e._write_new(ready, e.canonical_line({{'watchdog_pid': pid, 'phase': phase, 'count': count, 'root_exists': True}}))
    time.sleep(600)
if phase == 'armed_before_create':
    e._spawn_ipc_runtime_watchdog(identity, parent=parent, run_lease=run_lease, _after_arm_before_provision=signal_armed)
    raise SystemExit(99)
if phase == 'provisioned_before_ready':
    e._spawn_ipc_runtime_watchdog(identity, parent=parent, run_lease=run_lease, _after_provision_before_ready=signal_provisioned)
    raise SystemExit(99)
watchdog = e._spawn_ipc_runtime_watchdog(identity, parent=parent, run_lease=run_lease)
namespace = watchdog.namespace
listeners = []
for index, branch in enumerate(e.BRANCHES[:count]):
    listener = e._open_ipc_listener(namespace, branch)
    listeners.append(listener)
    if phase == 'registered' or (phase == 'mixed' and index % 2 == 0):
        watchdog.register(branch)
e._write_new(ready, e.canonical_line({{'watchdog_pid': watchdog.process.pid, 'phase': phase, 'count': count, 'root_exists': True}}))
time.sleep(600)
"""
        matrix = [
            ("armed_before_create", 0),
            ("provisioned_before_ready", 0),
            ("ready", 0),
            *(("unregistered", count) for count in range(1, 5)),
            ("mixed", 4),
            *(('registered', count) for count in range(1, 5)),
        ]
        with tempfile.TemporaryDirectory() as raw:
            parent = Path(raw) / "native"
            parent.mkdir(mode=0o700)
            unresolved_root = executor._unresolved_operation_root_path()

            def cleanup_run_lease_paths() -> None:
                self.assertEqual(os.listdir(unresolved_root), [])

            self.addCleanup(cleanup_run_lease_paths)
            for ordinal, (phase, count) in enumerate(matrix, start=1):
                with self.subTest(phase=phase, count=count):
                    run_identity = f"{ordinal:x}" * 64
                    ready = Path(raw) / f"ready-{ordinal}.json"
                    expected_root = executor._ipc_runtime_path(
                        run_identity,
                        parent=parent,
                    )
                    controller = subprocess.Popen(
                        [
                            sys.executable,
                            "-B",
                            "-c",
                            controller_source,
                            str(parent),
                            phase,
                            str(count),
                            str(ready),
                            run_identity,
                        ],
                        shell=False,
                        env={},
                        cwd="/",
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        close_fds=True,
                        start_new_session=True,
                    )
                    deadline = time.monotonic() + 15
                    while (
                        not ready.exists()
                        and controller.poll() is None
                        and time.monotonic() < deadline
                    ):
                        time.sleep(0.02)
                    self.assertTrue(ready.exists(), "controller did not arm IPC watchdog")
                    record = json.loads(ready.read_text("ascii"))
                    watchdog_pid = int(record["watchdog_pid"])
                    self.assertEqual(
                        expected_root.is_dir(),
                        bool(record["root_exists"]),
                    )
                    os.kill(controller.pid, signal.SIGKILL)
                    controller.wait(timeout=10)
                    deadline = time.monotonic() + 15
                    while expected_root.exists() and time.monotonic() < deadline:
                        time.sleep(0.02)
                    self.assertFalse(expected_root.exists())
                    deadline = time.monotonic() + 10
                    watchdog_proc = Path(f"/proc/{watchdog_pid}")
                    while watchdog_proc.exists() and time.monotonic() < deadline:
                        time.sleep(0.02)
                    self.assertFalse(watchdog_proc.exists())

    def test_default_worker_orchestrator_runs_four_concurrent_two_request_watchdog_transactions(self) -> None:
        requests: list[dict[str, object]] = []
        payload_map: dict[str, bytes] = {}
        bindings: dict[str, dict[str, object]] = {}
        sources: dict[str, Path] = {}
        engines: dict[str, Path] = {}
        source_identities: dict[str, executor.FileIdentity] = {}
        engine_identities: dict[str, executor.FileIdentity] = {}
        for branch in pilot.BRANCHES:
            model = pilot.TENSORRT_ENGINE_PINS[branch]
            source_sha = hashlib.sha256(f"source:{branch}".encode()).hexdigest()
            sources[branch] = Path(f"/private/{branch}.onnx")
            engines[branch] = Path(f"/private/{branch}.engine")
            source_identities[branch] = executor.FileIdentity(123, source_sha)
            engine_identities[branch] = executor.FileIdentity(
                int(model["size_bytes"]), str(model["engine_sha256"])
            )
            bindings[branch] = {
                "worker_id": f"vast.{branch}.tensorrt",
                "branch": branch,
                "model_id": model["model_id"],
                "source_path": f"/run/vast/models/{branch}.onnx",
                "source_model_sha256": source_sha,
                "engine_path": f"/run/vast/models/{branch}.engine",
                "model_artifact_sha256": model["engine_sha256"],
                "input": {"name": "data", "dtype": "float32", "layout": "NCHW", "shape": [1, 3, 224, 224]},
                "preprocessing_contract_sha256": "4" * 64,
                "output_contract_sha256": "5" * 64,
            }
            for codec, ordinal in zip(pilot.CODECS, range(2), strict=True):
                request_id = f"kpp-v2-nonpublication-{branch}-{codec}-calibration-smoke-v1"
                payload = hashlib.sha256(request_id.encode()).digest() * (
                    pilot.TENSOR_SEGMENT_BYTES // 32
                )
                payload_map[request_id] = payload
                requests.append(
                    {
                        "request_id": request_id,
                        "sample_id": f"sample.{branch}.{codec}",
                        "branch": branch,
                        "codec": codec,
                        "tensor": {
                            "offset_bytes": ordinal * pilot.TENSOR_SEGMENT_BYTES,
                            "dtype": "float32",
                            "layout": "NCHW",
                            "shape": [1, 3, 224, 224],
                            "segment_sha256": hashlib.sha256(payload).hexdigest(),
                            "preprocessing_contract_sha256": "4" * 64,
                        },
                    }
                )
        inventory = executor.BindingInventory(
            bindings=bindings,
            source_paths=sources,
            engine_paths=engines,
            source_identities=source_identities,
            engine_identities=engine_identities,
            manifest_identity_sha256="6" * 64,
            execution_config_identity_sha256="7" * 64,
        )
        payloads = executor.TensorInventory(payloads=payload_map, bundle_observations=[])
        barrier = threading.Barrier(4)
        transaction_branches: list[str] = []
        inferred: list[tuple[str, str]] = []
        watchdog_completed: list[str] = []
        ipc_mounts: list[Path] = []
        expected_ipc_path: Path | None = None
        delayed_branch: str | None = None
        delayed_entered = threading.Event()
        allow_delayed_finish = threading.Event()

        class Client:
            def __init__(self, branch: str, capability: dict[str, object]) -> None:
                self.branch = branch
                self.capability = capability

            def handshake(self) -> dict[str, object]:
                return self.capability

            def infer(self, request: dict[str, object], tensor: bytes) -> tuple[dict[str, object], bytes]:
                self.assert_tensor = tensor
                if self.branch == delayed_branch:
                    delayed_entered.set()
                    if not allow_delayed_finish.wait(timeout=5):
                        raise AssertionError(
                            "synthetic delayed branch was not released"
                        )
                codec = str(request["request_id"]).split("-")[-4]
                inferred.append((self.branch, codec))
                return {"request_id": request["request_id"], "terminal": "completed"}, b"o" * 4000

        def session_factory(**kwargs: object) -> tuple[Client, dict[str, object]]:
            branch = str(kwargs["branch"])
            binding = bindings[branch]
            capability = {
                "worker_id": binding["worker_id"],
                "model_id": binding["model_id"],
                "source_model_sha256": binding["source_model_sha256"],
                "model_artifact_sha256": binding["model_artifact_sha256"],
                "output_contract_sha256": binding["output_contract_sha256"],
            }
            return Client(branch, capability), capability

        class Watchdog:
            def __init__(self, branch: str) -> None:
                self.branch = branch

            def mark_create_dispatch(self) -> None:
                return None

            def mark_create_terminal(self) -> None:
                return None

            def complete(self) -> None:
                watchdog_completed.append(self.branch)

            def abort(self) -> None:
                raise AssertionError("synthetic transaction unexpectedly aborted")

        def watchdog_spawner(**kwargs: object) -> Watchdog:
            return Watchdog(str(kwargs["labels"][executor.BRANCH_LABEL]))

        def transaction_runner(**kwargs: object) -> dict[str, object]:
            branch = str(kwargs["labels"][executor.BRANCH_LABEL])
            transaction_branches.append(branch)
            expected_mounts = kwargs["expected_mounts"]
            self.assertIsNotNone(expected_ipc_path)
            self.assertEqual(
                expected_mounts["/run/vast/analytics"],
                expected_ipc_path,
            )
            ipc_mounts.append(expected_mounts["/run/vast/analytics"])
            self.assertIn(
                f"type=bind,src={expected_ipc_path},dst=/run/vast/analytics,readonly",
                kwargs["create_command"],
            )
            watchdog = kwargs["watchdog_factory"](
                container_name=kwargs["container_name"],
                labels=kwargs["labels"],
                expected_mounts=kwargs["expected_mounts"],
            )
            barrier.wait(timeout=5)
            action = kwargs["after_start"]("8" * 64)
            watchdog.complete()
            return {
                "container_id": "8" * 64,
                "action": action,
                "stdout": b"",
                "stderr": b"",
                "preinspect_sha256": "9" * 64,
                "running_inspect_sha256": "a" * 64,
                "postinspect_sha256": "b" * 64,
            }

        def stage(run_root: Path, source: executor.BindingInventory):
            model_root = run_root / "model_staging"
            model_root.mkdir()
            return source, (), model_root

        with tempfile.TemporaryDirectory() as raw:
            run_root = Path(raw) / "run"
            run_root.mkdir(mode=0o700)
            native_parent = Path(raw) / "simulated-native-posix-runtime"
            native_parent.mkdir()
            expected_ipc_path = native_parent / "held-ipc"

            @dataclass
            class SyntheticIpcNamespace:
                path: Path

            def create_ipc(_run_identity: str) -> SyntheticIpcNamespace:
                os.mkdir(expected_ipc_path, 0o700)
                return SyntheticIpcNamespace(expected_ipc_path)

            def destroy_ipc(namespace: SyntheticIpcNamespace) -> None:
                self.assertEqual(namespace.path, expected_ipc_path)
                self.assertEqual(list(namespace.path.iterdir()), [])
                namespace.path.rmdir()

            bindings_root = run_root / "bindings"
            bindings_root.mkdir()
            descriptors = {}
            for branch in pilot.BRANCHES:
                path = bindings_root / f"{branch}.tensorrt_cuda.json"
                executor._write_new(path, b"{}\n")
                descriptors[branch] = {"path": f"bindings/{path.name}"}
            observations = executor._run_tensor_workers(
                project_root=Path(raw),
                run_root=run_root,
                logical_run_root="runs/nonpublication/synthetic",
                run_identity="c" * 64,
                plan={},
                requests=requests,
                bindings=inventory,
                payloads=payloads,
                binding_descriptors=descriptors,
                runtime_probe={"validated_runtime_probe": {"synthetic": True}},
                runtime_image={"labels": dict(executor.IMAGE_LABELS)},
                runtime_daemon={"synthetic": True},
                docker_cli_identity=executor.FileIdentity(1, "d" * 64),
                command_runner=mock.Mock(),
                cleanup_mutex=executor._NullCleanupMutex(),
                container_registry=executor._OwnedContainerRegistry("c" * 64),
                progress=executor._ExecutionProgressLedger(
                    run_root=run_root,
                    run_id="synthetic-worker-orchestrator",
                    run_identity="c" * 64,
                    role="secondary",
                    requests=requests,
                ),
                _session_factory=session_factory,
                _transaction_runner=transaction_runner,
                _stage_inventory=stage,
                _watchdog_spawner=watchdog_spawner,
                _ipc_namespace_factory=create_ipc,
                _ipc_namespace_destroyer=destroy_ipc,
            )
            self.assertFalse((run_root / "ipc").exists())
            self.assertFalse((run_root / "model_staging").exists())
            self.assertFalse(expected_ipc_path.exists())
            self.assertEqual(set(transaction_branches), set(pilot.BRANCHES))
            self.assertEqual(len(transaction_branches), 4)
            self.assertEqual(set(watchdog_completed), set(pilot.BRANCHES))
            self.assertEqual(len(watchdog_completed), 4)
            self.assertEqual(ipc_mounts, [expected_ipc_path] * 4)
            self.assertEqual(len(inferred), 8)
            self.assertEqual(len(observations), 8)
            executor._validate_worker_observations(
                observations,
                requests,
                require_peer_identity=False,
            )

            run_root_2 = Path(raw) / "run-terminal-drain"
            run_root_2.mkdir(mode=0o700)
            bindings_root_2 = run_root_2 / "bindings"
            bindings_root_2.mkdir()
            descriptors_2 = {}
            for branch in pilot.BRANCHES:
                path = bindings_root_2 / f"{branch}.tensorrt_cuda.json"
                executor._write_new(path, b"{}\n")
                descriptors_2[branch] = {
                    "path": f"bindings/{path.name}"
                }
            delayed_branch = "damage"
            delayed_entered.clear()
            allow_delayed_finish.clear()
            destroy_observations: list[tuple[bool, int]] = []

            def destroy_after_terminal(namespace: SyntheticIpcNamespace) -> None:
                destroy_observations.append(
                    (
                        allow_delayed_finish.is_set(),
                        sum(branch == "damage" for branch, _codec in inferred),
                    )
                )
                destroy_ipc(namespace)

            actual_pool = executor.ThreadPoolExecutor
            actual_as_completed = executor.as_completed
            faulting_pools: list[object] = []

            class CollectionFailure(RuntimeError):
                pass

            class ShutdownFailure(RuntimeError):
                pass

            class FaultingPool:
                def __init__(self, *args: object, **kwargs: object) -> None:
                    self.delegate = actual_pool(*args, **kwargs)
                    faulting_pools.append(self)

                def submit(self, *args: object, **kwargs: object):
                    return self.delegate.submit(*args, **kwargs)

                def shutdown(self, *, wait: bool) -> None:
                    del wait
                    raise ShutdownFailure("synthetic shutdown before join")

            def broken_as_completed(futures: object):
                iterator = actual_as_completed(futures)
                yield next(iterator)
                if not delayed_entered.wait(timeout=5):
                    raise AssertionError(
                        "delayed branch did not enter before collection fault"
                    )
                raise CollectionFailure("synthetic completion traversal failure")

            destroy_before_release: list[bool] = []

            def release_delayed_branch() -> None:
                if not delayed_entered.wait(timeout=5):
                    return
                time.sleep(0.05)
                destroy_before_release.append(bool(destroy_observations))
                allow_delayed_finish.set()

            releaser = threading.Thread(target=release_delayed_branch)
            releaser.start()
            try:
                with mock.patch.object(
                    executor,
                    "ThreadPoolExecutor",
                    FaultingPool,
                ), mock.patch.object(
                    executor,
                    "as_completed",
                    broken_as_completed,
                ), self.assertRaises(
                    executor._ExecutionFailureBundle
                ) as drained:
                    executor._run_tensor_workers(
                        project_root=Path(raw),
                        run_root=run_root_2,
                        logical_run_root=(
                            "runs/nonpublication/synthetic-terminal-drain"
                        ),
                        run_identity="c" * 64,
                        plan={},
                        requests=requests,
                        bindings=inventory,
                        payloads=payloads,
                        binding_descriptors=descriptors_2,
                        runtime_probe={
                            "validated_runtime_probe": {"synthetic": True}
                        },
                        runtime_image={"labels": dict(executor.IMAGE_LABELS)},
                        runtime_daemon={"synthetic": True},
                        docker_cli_identity=executor.FileIdentity(1, "d" * 64),
                        command_runner=mock.Mock(),
                        cleanup_mutex=executor._NullCleanupMutex(),
                        container_registry=executor._OwnedContainerRegistry(
                            "c" * 64
                        ),
                        progress=executor._ExecutionProgressLedger(
                            run_root=run_root_2,
                            run_id="synthetic-worker-terminal-drain",
                            run_identity="c" * 64,
                            role="secondary",
                            requests=requests,
                        ),
                        _session_factory=session_factory,
                        _transaction_runner=transaction_runner,
                        _stage_inventory=stage,
                        _watchdog_spawner=watchdog_spawner,
                        _ipc_namespace_factory=create_ipc,
                        _ipc_namespace_destroyer=destroy_after_terminal,
                    )
            finally:
                allow_delayed_finish.set()
                releaser.join(timeout=5)
                for pool in faulting_pools:
                    pool.delegate.shutdown(wait=True)
            self.assertEqual(destroy_before_release, [False])
            self.assertEqual(destroy_observations, [(True, 4)])
            self.assertIsInstance(drained.exception.primary, CollectionFailure)
            self.assertIn(
                "worker_pool_shutdown",
                [
                    item.scope
                    for item in drained.exception.supplemental_failures
                ],
            )
            self.assertFalse(expected_ipc_path.exists())
            self.assertFalse((run_root_2 / "model_staging").exists())

        self.assertEqual(set(transaction_branches), set(pilot.BRANCHES))
        self.assertEqual(len(transaction_branches), 8)
        self.assertEqual(set(watchdog_completed), set(pilot.BRANCHES))
        self.assertGreaterEqual(len(watchdog_completed), 5)
        self.assertEqual(ipc_mounts, [expected_ipc_path] * 8)
        self.assertGreaterEqual(len(inferred), 10)

    def test_peer_credentials_exact_predicate_is_closed(self) -> None:
        accepted = (4321, executor.CONTAINER_UID, executor.CONTAINER_GID)
        self.assertTrue(executor._peer_credentials_are_exact(*accepted))
        for values in (
            (0, executor.CONTAINER_UID, executor.CONTAINER_GID),
            (-1, executor.CONTAINER_UID, executor.CONTAINER_GID),
            (4321, 0, executor.CONTAINER_GID),
            (4321, executor.CONTAINER_UID, 0),
            (4321, executor.CONTAINER_UID + 1, executor.CONTAINER_GID),
            (4321, executor.CONTAINER_UID, executor.CONTAINER_GID + 1),
        ):
            self.assertFalse(executor._peer_credentials_are_exact(*values))

    def test_peer_identity_modes_are_explicit_disjoint_and_sealed_pid0_evidence_passes(
        self,
    ) -> None:
        daemon = self._peercred_daemon()
        daemon_fixture = PEERCRED_DAEMON_INFO_FIXTURE.read_bytes()
        self.assertEqual(len(daemon_fixture), PEERCRED_DAEMON_INFO_FIXTURE_SIZE)
        self.assertEqual(
            hashlib.sha256(daemon_fixture).hexdigest(),
            PEERCRED_DAEMON_INFO_FIXTURE_SHA256,
        )
        daemon_info = json.loads(daemon_fixture)
        for key, value in self._daemon_info_document(daemon).items():
            self.assertEqual(daemon_info[key], value)
        self.assertEqual(
            executor.PEER_IDENTITY_MODES,
            (
                executor.PEER_IDENTITY_MODE_NATIVE_VISIBLE,
                executor.PEER_IDENTITY_MODE_DOCKER_DESKTOP_WSL2_PID0,
            ),
        )
        self.assertEqual(executor.PEER_IDENTITY_POLICY_VERSION, 2)
        raw_osrelease = b"6.6.87.2-microsoft-standard-WSL2\n"
        platform_observation = (
            executor._build_peercred_pid0_platform_observation(
                raw_osrelease,
                daemon,
            )
        )
        self.assertEqual(
            platform_observation["wsl_osrelease"],
            {
                "path": "/proc/sys/kernel/osrelease",
                "raw_ascii": raw_osrelease.decode("ascii"),
                "size_bytes": 33,
                "sha256": "ccd199c039f7944eb5289351597af34c9388338a60b6531c0d2fe55e8425019a",
                "marker": "-microsoft-standard-WSL2",
                "marker_present": True,
            },
        )
        self.assertEqual(
            executor._validate_peercred_pid0_platform_observation(
                platform_observation
            ),
            platform_observation,
        )

        observed: dict[str, dict[str, object]] = {}
        for branch, pins in PEERCRED_DIAGNOSTIC_FIXTURES.items():
            diagnostic_path = (
                PEERCRED_DIAGNOSTIC_RUN_ROOT
                / f"so_peercred_diagnostic.{branch}.json"
            )
            inspect_path = (
                PEERCRED_DIAGNOSTIC_CAPTURE_ROOT
                / f"{branch}.running_inspect.json"
            )
            diagnostic_payload = diagnostic_path.read_bytes()
            inspect_payload = inspect_path.read_bytes()
            self.assertEqual(
                hashlib.sha256(diagnostic_payload).hexdigest(),
                pins["diagnostic_sha256"],
            )
            self.assertEqual(
                hashlib.sha256(inspect_payload).hexdigest(),
                pins["inspect_sha256"],
            )
            diagnostic = json.loads(diagnostic_payload)
            inspect = json.loads(inspect_payload)
            peer = diagnostic["peer_credentials"]
            self.assertEqual(
                (peer["pid"], peer["uid"], peer["gid"]),
                (0, executor.CONTAINER_UID, executor.CONTAINER_GID),
            )
            self.assertEqual(inspect["State"]["Pid"], pins["state_pid"])
            identity = executor._select_peer_identity(
                selected_mode=(
                    executor.PEER_IDENTITY_MODE_DOCKER_DESKTOP_WSL2_PID0
                ),
                peer_raw=bytes.fromhex(peer["raw_hex"]),
                docker_state_pid=inspect["State"]["Pid"],
                runtime_daemon=daemon,
                runtime_platform=platform_observation,
                runtime_custody=self._peer_runtime_custody(
                    desktop_label=True
                ),
            )
            observed[branch] = identity
            self.assertEqual(
                identity["peer_identity_mode"],
                executor.PEER_IDENTITY_MODE_DOCKER_DESKTOP_WSL2_PID0,
            )
            self.assertIs(identity["peer_pid_visible_in_controller_namespace"], False)
            self.assertIs(identity["peer_pid_state_pid_equality_attested"], False)
            self.assertIs(identity["peer_identity_by_pid_attested"], False)
            self.assertIs(identity["peer_uid_gid_exact"], True)
            self.assertIs(identity["container_state_pid_positive"], True)
            self.assertIs(identity["protocol_nonce_capability_handshake_required"], True)
            self.assertIs(identity["protocol_nonce_capability_handshake_performed"], False)
        self.assertEqual(set(observed), set(pilot.BRANCHES))

        native_pid = 4321
        native = executor._select_peer_identity(
            selected_mode=executor.PEER_IDENTITY_MODE_NATIVE_VISIBLE,
            peer_raw=struct.pack(
                "3i",
                native_pid,
                executor.CONTAINER_UID,
                executor.CONTAINER_GID,
            ),
            docker_state_pid=native_pid,
            runtime_daemon=daemon,
            runtime_platform=None,
            runtime_custody=self._peer_runtime_custody(
                desktop_label=False
            ),
        )
        self.assertEqual(
            native["peer_identity_mode"],
            executor.PEER_IDENTITY_MODE_NATIVE_VISIBLE,
        )
        self.assertIs(native["peer_pid_visible_in_controller_namespace"], True)
        self.assertIs(native["peer_pid_state_pid_equality_attested"], True)
        self.assertIs(native["peer_identity_by_pid_attested"], True)
        self.assertIs(native["peer_uid_gid_exact"], True)
        self.assertIs(native["container_state_pid_positive"], True)
        for drifted in (
            {**native, "peer_identity_mode": "native_visible"},
            {key: value for key, value in native.items() if key != "peer_identity_mode"}
            | {"mode": executor.PEER_IDENTITY_MODE_NATIVE_VISIBLE},
            {**native, "mode": executor.PEER_IDENTITY_MODE_NATIVE_VISIBLE},
        ):
            with self.assertRaises(executor.ExecutorContractError):
                executor._validate_peer_identity_observation(
                    drifted,
                    completed_handshake=False,
                )
        with self.assertRaisesRegex(
            executor.ExecutorContractError,
            "peer PID differs from container init",
        ):
            executor._select_peer_identity(
                selected_mode=executor.PEER_IDENTITY_MODE_NATIVE_VISIBLE,
                peer_raw=struct.pack(
                    "3i",
                    native_pid,
                    executor.CONTAINER_UID,
                    executor.CONTAINER_GID,
                ),
                docker_state_pid=native_pid + 1,
                runtime_daemon=daemon,
                runtime_platform=platform_observation,
                runtime_custody=self._peer_runtime_custody(
                    desktop_label=True
                ),
            )

    def test_peer_identity_pid0_mode_rejects_every_backend_platform_and_type_near_miss(
        self,
    ) -> None:
        daemon = self._peercred_daemon()
        platform_observation = (
            executor._build_peercred_pid0_platform_observation(
                b"6.6.87.2-microsoft-standard-WSL2\n",
                daemon,
            )
        )
        valid = {
            "selected_mode": (
                executor.PEER_IDENTITY_MODE_DOCKER_DESKTOP_WSL2_PID0
            ),
            "peer_raw": struct.pack(
                "3i", 0, executor.CONTAINER_UID, executor.CONTAINER_GID
            ),
            "docker_state_pid": 4321,
            "runtime_daemon": daemon,
            "runtime_platform": platform_observation,
            "runtime_custody": self._peer_runtime_custody(
                desktop_label=True
            ),
        }
        invalid_calls: list[dict[str, object]] = []
        for field, value in (
            ("peer_raw", struct.pack("3i", -1, 1000, 1000)),
            ("peer_raw", struct.pack("3i", 1, 1000, 1000)),
            ("peer_raw", struct.pack("3i", 0, 0, 1000)),
            ("peer_raw", struct.pack("3i", 0, 1000, 0)),
            ("peer_raw", bytearray(struct.pack("3i", 0, 1000, 1000))),
            ("peer_raw", b"\0" * 11),
            ("docker_state_pid", 0),
            ("docker_state_pid", -1),
            ("docker_state_pid", True),
            ("selected_mode", executor.PEER_IDENTITY_MODE_NATIVE_VISIBLE),
            ("selected_mode", "automatic"),
        ):
            invalid_calls.append({**valid, field: value})
        for field, value in (
            ("daemon_id", "other-daemon-id"),
            ("server_version", "29.7.3"),
            ("api_version", "1.56"),
            ("os", "windows"),
            ("architecture", "arm64"),
            ("name", "other-daemon"),
            ("operating_system", "Linux"),
            ("driver", "overlay2"),
            ("driver_status", []),
            ("driver_status", [["driver-type", "overlayfs"]]),
            ("driver_status", [("driver-type", "io.containerd.snapshotter.v1")]),
            (
                "driver_status",
                [["driver-type", "io.containerd.snapshotter.v1"], ["x", "y"]],
            ),
            ("default_runtime", "crun"),
            ("kernel_version", "6.6.87.2-linux"),
            ("containerd_commit", {"ID": "0" * 40}),
            (
                "containerd_commit",
                {
                    "ID": "e53c7c1516c3b2bff98eb76f1f4117477e6f4e66",
                    "Expected": "extra",
                },
            ),
        ):
            invalid_calls.append(
                {**valid, "runtime_daemon": self._peercred_daemon(**{field: value})}
            )
        for missing in (
            "operating_system",
            "kernel_version",
            "driver",
            "driver_status",
            "default_runtime",
            "containerd_commit",
        ):
            incomplete_daemon = dict(daemon)
            incomplete_daemon.pop(missing)
            invalid_calls.append({**valid, "runtime_daemon": incomplete_daemon})
        for field, value in (
            ("native_ipc_namespace_attested", False),
            ("readonly_mounts_attested", False),
            ("container_image_entrypoint_identity_attested", False),
            ("docker_desktop_wsl_distro_label_attested", False),
            ("container_runtime", "crun"),
        ):
            invalid_calls.append(
                {
                    **valid,
                    "runtime_custody": self._peer_runtime_custody(
                        desktop_label=True,
                        **{field: value},
                    ),
                }
            )
        invalid_platform = dict(platform_observation)
        invalid_platform["observation_sha256"] = "0" * 64
        invalid_calls.append({**valid, "runtime_platform": invalid_platform})
        forged_platform = copy.deepcopy(platform_observation)
        forged_platform["daemon_observation_sha256"] = "0" * 64
        forged_core = {
            key: value
            for key, value in forged_platform.items()
            if key != "observation_sha256"
        }
        forged_platform["observation_sha256"] = hashlib.sha256(
            executor.PEERCRED_PLATFORM_DOMAIN
            + executor.canonical_line(forged_core)
        ).hexdigest()
        invalid_calls.append({**valid, "runtime_platform": forged_platform})
        invalid_calls.append({**valid, "runtime_platform": None})
        for index, call in enumerate(invalid_calls):
            with self.subTest(index=index):
                with self.assertRaises(executor.ExecutorContractError):
                    executor._select_peer_identity(**call)

        for raw in (
            b"",
            b"6.6.87.2-microsoft-standard-WSL2",
            b"6.6.87.2-microsoft-standard-WSL2\r\n",
            b"6.6.87.2-microsoft-standard-WSL2\nextra\n",
            b"6.6.87.2-microsoft-standard-WSL2\0\n",
            b"6.6.87.2-linux\n",
            b"6evil-microsoft-standard-WSL2\n",
            b"06.6.87.2-microsoft-standard-WSL2\n",
            b"6.0000.87.2-microsoft-standard-WSL2\n",
            b"6.6.87.2-extra-microsoft-standard-WSL2\n",
            b"A" * 256 + b"\n",
            b"\xff\n",
        ):
            with self.subTest(raw=raw):
                with self.assertRaises(executor.ExecutorContractError):
                    executor._build_peercred_pid0_platform_observation(
                        raw,
                        daemon,
                    )
        for raw in (
            b"6evil-microsoft-standard-WSL2\n",
            b"06.6.87.2-microsoft-standard-WSL2\n",
            b"6.0000.87.2-microsoft-standard-WSL2\n",
            b"6.6.87.2-extra-microsoft-standard-WSL2\n",
        ):
            with self.subTest(malformed_matching_daemon=raw):
                matching_daemon = self._peercred_daemon(
                    kernel_version=raw[:-1].decode("ascii")
                )
                with self.assertRaises(executor.ExecutorContractError):
                    executor._build_peercred_pid0_platform_observation(
                        raw,
                        matching_daemon,
                    )

    @unittest.skipUnless(os.name == "posix", "native WSL2 platform observation")
    def test_peercred_pid0_platform_observer_is_nofollow_bounded_and_exact_on_wsl(
        self,
    ) -> None:
        daemon = self._peercred_daemon()
        observed = executor._observe_peercred_pid0_platform(daemon)
        self.assertEqual(
            observed,
            executor._validate_peercred_pid0_platform_observation(observed),
        )
        self.assertEqual(
            observed["wsl_osrelease"],
            {
                "path": "/proc/sys/kernel/osrelease",
                "raw_ascii": "6.6.87.2-microsoft-standard-WSL2\n",
                "size_bytes": 33,
                "sha256": (
                    "ccd199c039f7944eb5289351597af34c9388338a60b6531c0d2fe55e8425019a"
                ),
                "marker": "-microsoft-standard-WSL2",
                "marker_present": True,
            },
        )

        def state(**changes: object) -> object:
            value = {
                "st_mode": stat.S_IFREG | 0o444,
                "st_dev": 17,
                "st_ino": 23,
                "st_uid": 0,
                "st_gid": 0,
                "st_nlink": 1,
            }
            value.update(changes)
            return types.SimpleNamespace(**value)

        raw_release = b"6.6.87.2-microsoft-standard-WSL2\n"
        open_flags: list[int] = []

        def exact_open(path: object, flags: int) -> int:
            self.assertEqual(Path(path), Path("/proc/sys/kernel/osrelease"))
            open_flags.append(flags)
            return 91

        with mock.patch.object(executor.os, "open", side_effect=exact_open), mock.patch.object(
            executor.os, "fstat", side_effect=(state(), state())
        ), mock.patch.object(
            executor.os, "stat", side_effect=(state(), state())
        ), mock.patch.object(
            executor.os, "read", side_effect=(raw_release, b"")
        ), mock.patch.object(executor.os, "close") as close:
            synthetic = executor._observe_peercred_pid0_platform(daemon)
        self.assertEqual(synthetic, observed)
        self.assertEqual(len(open_flags), 1)
        self.assertNotEqual(open_flags[0] & getattr(os, "O_NOFOLLOW", 0), 0)
        close.assert_called_once_with(91)

        for label, before, named in (
            ("mode", state(st_mode=stat.S_IFREG | 0o644), state()),
            ("owner", state(st_uid=1000), state()),
            ("group", state(st_gid=1000), state()),
            ("link", state(st_nlink=2), state()),
            ("nonregular", state(st_mode=stat.S_IFLNK | 0o777), state()),
            ("named_identity", state(), state(st_ino=24)),
        ):
            with self.subTest(custody=label), mock.patch.object(
                executor.os, "open", return_value=92
            ), mock.patch.object(
                executor.os, "fstat", return_value=before
            ), mock.patch.object(
                executor.os, "stat", return_value=named
            ), mock.patch.object(executor.os, "close"):
                with self.assertRaises(executor.ExecutorContractError):
                    executor._observe_peercred_pid0_platform(daemon)
        with mock.patch.object(
            executor.os, "open", side_effect=OSError(errno.ELOOP, "symlink")
        ):
            with self.assertRaises(executor.ExecutorContractError):
                executor._observe_peercred_pid0_platform(daemon)
        with mock.patch.object(
            executor.os, "open", return_value=93
        ), mock.patch.object(
            executor.os, "fstat", return_value=state()
        ), mock.patch.object(
            executor.os, "stat", return_value=state()
        ), mock.patch.object(
            executor.os, "read", side_effect=OSError(errno.EIO, "read")
        ), mock.patch.object(executor.os, "close"):
            with self.assertRaises(executor.ExecutorContractError):
                executor._observe_peercred_pid0_platform(daemon)

    @unittest.skipUnless(os.name == "posix", "POSIX diagnostic custody")
    def test_peercred_failure_diagnostic_is_exact_o_excl_self_hashed_and_acceptance_closed(
        self,
    ) -> None:
        plan = {
            "role": "secondary",
            "pilot_plan_sha256": "1" * 64,
            "matrix_identity_sha256": "2" * 64,
            "decision": {"decision_sha256": "3" * 64},
            "candidate": {
                "receipt": {
                    "sha256": "4" * 64,
                    "candidate_receipt_sha256": "5" * 64,
                }
            },
        }
        inventory = executor.BindingInventory(
            bindings={},
            source_paths={},
            engine_paths={},
            source_identities={},
            engine_identities={},
            manifest_identity_sha256="6" * 64,
            execution_config_identity_sha256="7" * 64,
        )
        executor_identity = executor.FileIdentity(123, "8" * 64)
        with tempfile.TemporaryDirectory() as raw:
            project_root = Path(raw).resolve()
            run_root = project_root / "runs" / "nonpublication" / "diagnostic-run"
            run_root.mkdir(mode=0o700, parents=True)
            written: list[Path] = []
            for ordinal, branch in enumerate(pilot.BRANCHES):
                peer = (
                    (
                        0
                        if branch == "plate_number"
                        else (-1 if branch == "foreign_object" else 5000 + ordinal)
                    ),
                    0 if branch == "vehicle_type" else executor.CONTAINER_UID,
                    0 if branch == "damage" else executor.CONTAINER_GID,
                )
                path = executor._write_peercred_failure_diagnostic(
                    project_root=project_root,
                    run_root=run_root,
                    logical_run_root="runs/nonpublication/diagnostic-run",
                    run_identity="9" * 64,
                    plan=plan,
                    bindings=inventory,
                    branch=branch,
                    container_id=hashlib.sha256(branch.encode("ascii")).hexdigest(),
                    container_name=f"vast-kpp-v2-np-{'9' * 16}-{branch}",
                    peer_pid=peer[0],
                    peer_uid=peer[1],
                    peer_gid=peer[2],
                    peer_raw=struct.pack("3i", *peer),
                    docker_state_pid=6000 + ordinal,
                    container_user=(
                        f"{executor.CONTAINER_UID}:{executor.CONTAINER_GID}"
                    ),
                    executor_source_path="scripts/kpp_legacy_iss_v2_secondary_sensitivity_executor.py",
                    executor_source_identity=executor_identity,
                )
                written.append(path)
                payload = path.read_bytes()
                document = json.loads(payload)
                self.assertEqual(payload, executor.canonical_line(document))
                claimed = document.pop("diagnostic_sha256")
                self.assertEqual(
                    set(document),
                    {
                        "schema_version",
                        "artifact_kind",
                        "claim_status",
                        "diagnostic_reason",
                        "branch",
                        "container",
                        "peer_credentials",
                        "stages",
                        "execution_pins",
                        "filesystem_custody",
                        "diagnostic_only",
                        "confidentiality_attested",
                        "filesystem_acl_attested",
                        "windows_acl_attested",
                        "peer_credentials_accepted_for_inference",
                        "capability_handshake_performed",
                        "operational_completion_observed",
                        "inference_performed",
                        *executor.FALSE_CLAIM_FIELDS,
                    },
                )
                self.assertEqual(
                    claimed,
                    hashlib.sha256(
                        executor.PEERCRED_DIAGNOSTIC_DOMAIN
                        + executor.canonical_line(document)
                    ).hexdigest(),
                )
                self.assertEqual(document["branch"], branch)
                self.assertEqual(document["peer_credentials"]["pid"], peer[0])
                self.assertEqual(document["peer_credentials"]["uid"], peer[1])
                self.assertEqual(document["peer_credentials"]["gid"], peer[2])
                self.assertEqual(
                    set(document["peer_credentials"]),
                    {
                        "pid",
                        "uid",
                        "gid",
                        "raw_hex",
                        "raw_size_bytes",
                        "native_struct_format",
                        "native_byteorder",
                        "expected_uid",
                        "expected_gid",
                        "pid_positive",
                        "uid_matches",
                        "gid_matches",
                        "state_pid_matches",
                    },
                )
                self.assertEqual(
                    document["peer_credentials"]["raw_hex"],
                    struct.pack("3i", *peer).hex(),
                )
                self.assertEqual(
                    document["peer_credentials"]["raw_size_bytes"],
                    struct.calcsize("3i"),
                )
                self.assertEqual(
                    document["peer_credentials"]["native_byteorder"],
                    sys.byteorder,
                )
                self.assertEqual(document["container"]["state_pid"], 6000 + ordinal)
                self.assertIs(document["diagnostic_only"], False)
                self.assertIs(
                    document["peer_credentials_accepted_for_inference"],
                    False,
                )
                self.assertIs(document["capability_handshake_performed"], False)
                self.assertEqual(
                    document["filesystem_custody"],
                    {
                        "statfs_magic": executor._LINUX_EXT_FILESYSTEM_MAGIC,
                        "statfs_magic_hex": "0x0000ef53",
                        "filesystem_type": "linux_ext_native",
                        "mount_observation": "native_ext_mode_enforcement",
                        "run_root_effective_mode": "0700",
                        "requested_file_mode": "0400",
                        "file_effective_mode": "0400",
                    },
                )
                self.assertIs(document["confidentiality_attested"], False)
                self.assertIs(document["filesystem_acl_attested"], False)
                self.assertIs(document["windows_acl_attested"], False)
                self.assertFalse(document["inference_performed"])
                self.assertFalse(document["operational_completion_observed"])
                self.assertFalse(document["stages"]["capability_handshake_started"])
                self.assertFalse(document["stages"]["inference_started"])
                for field in executor.FALSE_CLAIM_FIELDS:
                    self.assertIs(document[field], False)
                observed = path.stat()
                self.assertEqual(observed.st_nlink, 1)
                if os.name == "posix":
                    self.assertEqual(stat.S_IMODE(observed.st_mode), 0o400)

            self.assertEqual(
                [path.name for path in sorted(written)],
                sorted(
                    f"so_peercred_failure.{branch}.json"
                    for branch in pilot.BRANCHES
                ),
            )
            original = written[0].read_bytes()
            with self.assertRaises(executor.ExecutorContractError):
                executor._write_peercred_failure_diagnostic(
                    project_root=project_root,
                    run_root=run_root,
                    logical_run_root="runs/nonpublication/diagnostic-run",
                    run_identity="9" * 64,
                    plan=plan,
                    bindings=inventory,
                    branch=pilot.BRANCHES[0],
                    container_id=hashlib.sha256(
                        pilot.BRANCHES[0].encode("ascii")
                    ).hexdigest(),
                    container_name=(
                        f"vast-kpp-v2-np-{'9' * 16}-{pilot.BRANCHES[0]}"
                    ),
                    peer_pid=0,
                    peer_uid=executor.CONTAINER_UID,
                    peer_gid=executor.CONTAINER_GID,
                    peer_raw=struct.pack(
                        "3i", 0, executor.CONTAINER_UID, executor.CONTAINER_GID
                    ),
                    docker_state_pid=6000,
                    container_user=(
                        f"{executor.CONTAINER_UID}:{executor.CONTAINER_GID}"
                    ),
                    executor_source_path="scripts/kpp_legacy_iss_v2_secondary_sensitivity_executor.py",
                    executor_source_identity=executor_identity,
                )
            self.assertEqual(written[0].read_bytes(), original)

            diagnostic_only_root = (
                project_root / "runs" / "nonpublication" / "diagnostic-only-run"
            )
            diagnostic_only_root.mkdir(mode=0o700)
            diagnostic_only_path = executor._write_peercred_failure_diagnostic(
                project_root=project_root,
                run_root=diagnostic_only_root,
                logical_run_root="runs/nonpublication/diagnostic-only-run",
                run_identity="a" * 64,
                plan=plan,
                bindings=inventory,
                branch="plate_number",
                container_id="b" * 64,
                container_name=f"vast-kpp-v2-np-{'a' * 16}-plate_number",
                peer_pid=4321,
                peer_uid=executor.CONTAINER_UID,
                peer_gid=executor.CONTAINER_GID,
                peer_raw=struct.pack(
                    "3i",
                    4321,
                    executor.CONTAINER_UID,
                    executor.CONTAINER_GID,
                ),
                docker_state_pid=4321,
                container_user=(
                    f"{executor.CONTAINER_UID}:{executor.CONTAINER_GID}"
                ),
                executor_source_path="scripts/kpp_legacy_iss_v2_secondary_sensitivity_executor.py",
                executor_source_identity=executor_identity,
                diagnostic_only=True,
            )
            diagnostic_only_document = json.loads(
                diagnostic_only_path.read_bytes()
            )
            self.assertEqual(
                diagnostic_only_path.name,
                "so_peercred_diagnostic.plate_number.json",
            )
            self.assertEqual(
                diagnostic_only_document["diagnostic_reason"],
                "diagnostic_only_stop_before_handshake",
            )
            self.assertIs(diagnostic_only_document["diagnostic_only"], True)
            self.assertIs(
                diagnostic_only_document["execution_pins"]["diagnostic_only"],
                True,
            )
            self.assertIs(
                diagnostic_only_document["stages"][
                    "peercred_exact_uid_gid_match_observed"
                ],
                True,
            )
            self.assertIs(
                diagnostic_only_document["stages"][
                    "peer_credentials_accepted_for_inference"
                ],
                False,
            )

    @unittest.skipUnless(os.name == "posix", "POSIX diagnostic custody")
    def test_peercred_diagnostic_rejects_types_bounds_raw_drift_and_partial_write(
        self,
    ) -> None:
        plan = {
            "role": "secondary",
            "pilot_plan_sha256": "1" * 64,
            "matrix_identity_sha256": "2" * 64,
            "decision": {"decision_sha256": "3" * 64},
            "candidate": {
                "receipt": {
                    "sha256": "4" * 64,
                    "candidate_receipt_sha256": "5" * 64,
                }
            },
        }
        inventory = executor.BindingInventory(
            bindings={},
            source_paths={},
            engine_paths={},
            source_identities={},
            engine_identities={},
            manifest_identity_sha256="6" * 64,
            execution_config_identity_sha256="7" * 64,
        )
        source_identity = executor.FileIdentity(123, "8" * 64)

        def arguments(run_root: Path) -> dict[str, object]:
            peer = (0, executor.CONTAINER_UID, executor.CONTAINER_GID)
            return {
                "project_root": project_root,
                "run_root": run_root,
                "logical_run_root": f"runs/nonpublication/{run_root.name}",
                "run_identity": "9" * 64,
                "plan": plan,
                "bindings": inventory,
                "branch": "plate_number",
                "container_id": "a" * 64,
                "container_name": f"vast-kpp-v2-np-{'9' * 16}-plate_number",
                "peer_pid": peer[0],
                "peer_uid": peer[1],
                "peer_gid": peer[2],
                "peer_raw": struct.pack("3i", *peer),
                "docker_state_pid": 4321,
                "container_user": (
                    f"{executor.CONTAINER_UID}:{executor.CONTAINER_GID}"
                ),
                "executor_source_path": "scripts/kpp_legacy_iss_v2_secondary_sensitivity_executor.py",
                "executor_source_identity": source_identity,
            }

        with tempfile.TemporaryDirectory() as raw:
            project_root = Path(raw).resolve()
            root = project_root / "runs" / "nonpublication"
            root.mkdir(parents=True)
            for index, changes in enumerate(
                (
                    {"peer_pid": True},
                    {"peer_uid": True},
                    {"peer_gid": 1.0},
                    {"peer_pid": -(2**31) - 1},
                    {"peer_uid": 2**31},
                    {"peer_raw": bytearray(struct.pack("3i", 0, 1000, 1000))},
                    {"peer_raw": b"\0" * (struct.calcsize("3i") - 1)},
                    {
                        "peer_raw": struct.pack(
                            "3i", 1, executor.CONTAINER_UID, executor.CONTAINER_GID
                        )
                    },
                    {"docker_state_pid": True},
                    {"docker_state_pid": 0},
                    {"container_user": "0:0"},
                    {"diagnostic_only": 1},
                    {"logical_run_root": PurePosixPath("runs/nonpublication/x")},
                    {"run_identity": "A" * 64},
                    {"branch": "Plate_Number"},
                    {"container_id": "A" * 64},
                    {"container_name": "wrong"},
                    {"project_root": root},
                    {"executor_source_path": "scripts/other.py"},
                    {
                        "executor_source_identity": executor.FileIdentity(
                            123,
                            "8" * 64,
                            is_regular_file=False,
                        )
                    },
                    {"plan": {**plan, "role": True}},
                )
            ):
                with self.subTest(index=index, changes=changes):
                    run_root = root / f"invalid-{index}"
                    run_root.mkdir(mode=0o700)
                    call = arguments(run_root)
                    call.update(changes)
                    with self.assertRaises(executor.ExecutorContractError):
                        executor._write_peercred_failure_diagnostic(**call)
                    self.assertEqual(list(run_root.iterdir()), [])

            accepted_root = root / "accepted-without-diagnostic-mode"
            accepted_root.mkdir(mode=0o700)
            accepted = arguments(accepted_root)
            accepted.update(
                {
                    "peer_pid": 4321,
                    "peer_raw": struct.pack(
                        "3i",
                        4321,
                        executor.CONTAINER_UID,
                        executor.CONTAINER_GID,
                    ),
                }
            )
            with self.assertRaisesRegex(
                executor.ExecutorContractError,
                "cannot record accepted credentials",
            ):
                executor._write_peercred_failure_diagnostic(**accepted)
            self.assertEqual(list(accepted_root.iterdir()), [])

            unknown_filesystem_root = root / "unknown-filesystem"
            unknown_filesystem_root.mkdir(mode=0o700)
            unknown_filesystem_call = arguments(unknown_filesystem_root)
            with mock.patch.object(
                executor,
                "_linux_fstatfs_magic",
                return_value=0xDEADBEEF,
            ):
                with self.assertRaisesRegex(
                    executor.ExecutorContractError,
                    "filesystem type or root mode drifted",
                ):
                    executor._write_peercred_failure_diagnostic(
                        **unknown_filesystem_call
                    )
            self.assertEqual(list(unknown_filesystem_root.iterdir()), [])

            mutated_mode_root = root / "mutated-mode"
            mutated_mode_root.mkdir(mode=0o700)
            mutated_mode_call = arguments(mutated_mode_root)
            original_fchmod = executor.os.fchmod

            def writable_fchmod(descriptor: int, _mode: int) -> None:
                original_fchmod(descriptor, 0o600)

            with mock.patch.object(
                executor.os,
                "fchmod",
                side_effect=writable_fchmod,
            ):
                with self.assertRaisesRegex(
                    executor.ExecutorContractError,
                    "file owner or mode drifted",
                ):
                    executor._write_peercred_failure_diagnostic(
                        **mutated_mode_call
                    )
            mutated_path = (
                mutated_mode_root / "so_peercred_failure.plate_number.json"
            )
            mutated_payload = mutated_path.read_bytes()
            self.assertGreater(len(mutated_payload), 17)
            self.assertNotEqual(
                stat.S_IMODE(mutated_path.stat().st_mode),
                0o400,
            )
            with self.assertRaisesRegex(
                executor.ExecutorContractError,
                "cannot persist SO_PEERCRED failure diagnostic",
            ):
                executor._write_peercred_failure_diagnostic(**mutated_mode_call)
            self.assertEqual(mutated_path.read_bytes(), mutated_payload)

            reseal_root = root / "durable-readback-drift"
            reseal_root.mkdir(mode=0o700)
            reseal_call = arguments(reseal_root)
            reseal_path = (
                reseal_root / "so_peercred_failure.plate_number.json"
            )
            original_read = executor.os.read
            read_count = 0

            def corrupted_readback(descriptor: int, count: int) -> bytes:
                nonlocal read_count
                read_count += 1
                if read_count == 1:
                    reseal_path.chmod(0o600)
                    with reseal_path.open("r+b") as stream:
                        first = stream.read(1)
                        self.assertEqual(len(first), 1)
                        stream.seek(0)
                        stream.write(bytes([first[0] ^ 1]))
                        stream.flush()
                        os.fsync(stream.fileno())
                return original_read(descriptor, count)

            with mock.patch.object(
                executor.os,
                "read",
                side_effect=corrupted_readback,
            ):
                with self.assertRaisesRegex(
                    executor.ExecutorContractError,
                    "durable readback drifted",
                ):
                    executor._write_peercred_failure_diagnostic(**reseal_call)
            reseal_payload = reseal_path.read_bytes()
            self.assertGreater(len(reseal_payload), 17)
            with self.assertRaisesRegex(
                executor.ExecutorContractError,
                "cannot persist SO_PEERCRED failure diagnostic",
            ):
                executor._write_peercred_failure_diagnostic(**reseal_call)
            self.assertEqual(reseal_path.read_bytes(), reseal_payload)

            partial_root = root / "partial-write"
            partial_root.mkdir(mode=0o700)
            partial_call = arguments(partial_root)
            original_write = executor.os.write
            write_count = 0

            def interrupted_write(descriptor: int, payload: object) -> int:
                nonlocal write_count
                write_count += 1
                if write_count == 1:
                    return original_write(descriptor, bytes(payload[:17]))
                raise OSError(errno.EIO, "synthetic partial diagnostic write")

            with mock.patch.object(
                executor.os,
                "write",
                side_effect=interrupted_write,
            ):
                with self.assertRaisesRegex(
                    executor.ExecutorContractError,
                    "cannot persist SO_PEERCRED failure diagnostic",
                ):
                    executor._write_peercred_failure_diagnostic(**partial_call)
            partial_path = partial_root / "so_peercred_failure.plate_number.json"
            partial_payload = partial_path.read_bytes()
            self.assertEqual(len(partial_payload), 17)
            with self.assertRaisesRegex(
                executor.ExecutorContractError,
                "cannot persist SO_PEERCRED failure diagnostic",
            ):
                executor._write_peercred_failure_diagnostic(**partial_call)
            self.assertEqual(partial_path.read_bytes(), partial_payload)
            observed = partial_path.stat()
            self.assertEqual(observed.st_nlink, 1)
            if os.name == "posix":
                self.assertEqual(stat.S_IMODE(observed.st_mode), 0o400)

            if os.name == "posix":
                collision_root = root / "symlink-collision"
                collision_root.mkdir(mode=0o700)
                collision_call = arguments(collision_root)
                target = root / "preserved-target"
                target.write_bytes(b"preserved")
                collision_path = (
                    collision_root / "so_peercred_failure.plate_number.json"
                )
                collision_path.symlink_to(target)
                with self.assertRaisesRegex(
                    executor.ExecutorContractError,
                    "cannot persist SO_PEERCRED failure diagnostic",
                ):
                    executor._write_peercred_failure_diagnostic(**collision_call)
                self.assertTrue(collision_path.is_symlink())
                self.assertEqual(target.read_bytes(), b"preserved")

    @unittest.skipUnless(os.name == "posix", "native SO_PEERCRED diagnostic path")
    def test_peercred_diagnostic_four_branch_failure_and_diagnostic_only_stop_cleanup(
        self,
    ) -> None:
        requests: list[dict[str, object]] = []
        payload_map: dict[str, bytes] = {}
        bindings: dict[str, dict[str, object]] = {}
        sources: dict[str, Path] = {}
        engines: dict[str, Path] = {}
        identities: dict[str, executor.FileIdentity] = {}
        descriptors: dict[str, dict[str, object]] = {}
        for branch in pilot.BRANCHES:
            source_sha = hashlib.sha256(f"source:{branch}".encode()).hexdigest()
            sources[branch] = Path(f"/private/{branch}.onnx")
            engines[branch] = Path(f"/private/{branch}.engine")
            identities[branch] = executor.FileIdentity(1, source_sha)
            bindings[branch] = {
                "worker_id": f"vast.{branch}.tensorrt",
                "branch": branch,
                "model_id": f"{branch}_model",
                "source_path": f"/run/vast/models/{branch}.onnx",
                "source_model_sha256": source_sha,
                "engine_path": f"/run/vast/models/{branch}.engine",
                "model_artifact_sha256": hashlib.sha256(
                    f"engine:{branch}".encode()
                ).hexdigest(),
                "input": {
                    "name": "data",
                    "dtype": "float32",
                    "layout": "NCHW",
                    "shape": [1, 3, 224, 224],
                },
                "preprocessing_contract_sha256": "4" * 64,
                "output_contract_sha256": "5" * 64,
            }
            descriptors[branch] = {
                "path": f"bindings/{branch}.tensorrt_cuda.json"
            }
            for codec in pilot.CODECS:
                request_id = f"{branch}-{codec}"
                payload_map[request_id] = b"p"
                requests.append(
                    {
                        "request_id": request_id,
                        "sample_id": f"sample.{branch}.{codec}",
                        "branch": branch,
                        "codec": codec,
                        "tensor": {
                            "offset_bytes": 0,
                            "dtype": "float32",
                            "layout": "NCHW",
                            "shape": [1, 3, 224, 224],
                            "segment_sha256": hashlib.sha256(b"p").hexdigest(),
                            "preprocessing_contract_sha256": "4" * 64,
                        },
                    }
                )
        inventory = executor.BindingInventory(
            bindings=bindings,
            source_paths=sources,
            engine_paths=engines,
            source_identities=identities,
            engine_identities=identities,
            manifest_identity_sha256="6" * 64,
            execution_config_identity_sha256="7" * 64,
        )
        payloads = executor.TensorInventory(
            payloads=payload_map,
            bundle_observations=[],
        )
        plan = {
            "role": "secondary",
            "pilot_plan_sha256": "1" * 64,
            "matrix_identity_sha256": "2" * 64,
            "decision": {"decision_sha256": "3" * 64},
            "candidate": {
                "receipt": {
                    "sha256": "4" * 64,
                    "candidate_receipt_sha256": "5" * 64,
                }
            },
        }
        endpoint = types.ModuleType("analytics_execution_endpoint")

        def capability_builder(**kwargs: object) -> dict[str, object]:
            binding = kwargs["binding"]
            return {
                field: binding[field]
                for field in (
                    "worker_id",
                    "model_id",
                    "source_model_sha256",
                    "model_artifact_sha256",
                    "output_contract_sha256",
                )
            }

        endpoint.expected_capability_from_binding_and_probe = capability_builder
        worker = types.ModuleType("analytics_execution_worker")
        original_open = executor._open_ipc_listener

        def run_case(
            *,
            case: str,
            peer_values: Mapping[str, tuple[int, int, int]],
            diagnostic_only: bool,
            peer_identity_mode: str = executor.PEER_IDENTITY_MODE_NATIVE_VISIBLE,
            writer: object = executor._write_peercred_failure_diagnostic,
            expect_success: bool = False,
            expect_handshakes_on_failure: bool = False,
            expect_diagnostics_on_failure: bool = True,
            platform_drift_at_barrier: bool = False,
            daemon_drift_at_barrier: bool = False,
        ) -> tuple[list[dict[str, object]] | None, Path]:
            barrier = threading.Barrier(4)
            documents: dict[str, dict[str, object]] = {}
            container_by_branch: dict[str, str] = {}
            closed: list[str] = []
            cleaned: list[str] = []
            handshakes: list[str] = []
            inferred: list[str] = []
            lock = threading.Lock()

            class Connection:
                def __init__(self, branch: str) -> None:
                    self.branch = branch

                def settimeout(self, value: float) -> None:
                    self.assert_timeout = value
                    self_test.assertEqual(value, 180.0)

                def getsockopt(
                    self,
                    level: int,
                    option: int,
                    size: int,
                ) -> bytes:
                    self_test.assertEqual(
                        (level, option, size),
                        (
                            socket.SOL_SOCKET,
                            socket.SO_PEERCRED,
                            struct.calcsize("3i"),
                        ),
                    )
                    return struct.pack("3i", *peer_values[self.branch])

                def close(self) -> None:
                    with lock:
                        closed.append(self.branch)

            class Listener:
                def __init__(self, branch: str, inner: socket.socket) -> None:
                    self.branch = branch
                    self.inner = inner

                def accept(self) -> tuple[Connection, None]:
                    return Connection(self.branch), None

                def close(self) -> None:
                    self.inner.close()

            class Client:
                def __init__(
                    self,
                    connection: Connection,
                    *,
                    expected_capability: Mapping[str, object],
                ) -> None:
                    self.connection = connection
                    self.capability = dict(expected_capability)

                def handshake(self) -> dict[str, object]:
                    with lock:
                        handshakes.append(self.connection.branch)
                    return self.capability

                def infer(
                    self,
                    request: Mapping[str, object],
                    tensor: bytes,
                ) -> tuple[dict[str, object], bytes]:
                    self_test.assertEqual(tensor, b"p")
                    with lock:
                        self_test.assertEqual(
                            set(handshakes),
                            set(pilot.BRANCHES),
                            "an inference began before all four handshakes",
                        )
                        inferred.append(str(request["request_id"]))
                    return {"request_id": request["request_id"]}, b"o" * 4000

            worker.ExecutionClient = Client

            class Runner:
                def run(
                    self,
                    argv: list[str],
                    *,
                    timeout_seconds: float,
                    stdout_limit: int,
                    stderr_limit: int,
                ) -> executor.CommandCapture:
                    del timeout_seconds, stdout_limit, stderr_limit
                    command = tuple(argv)
                    if "info" in command:
                        info = self_test._peercred_daemon_info_document()
                        if daemon_drift_at_barrier:
                            info["DefaultRuntime"] = "crun"
                        return executor.CommandCapture(
                            0,
                            executor.canonical_line(info),
                            b"",
                        )
                    if "version" in command:
                        return executor.CommandCapture(
                            0,
                            executor.canonical_line(
                                {
                                    "Version": "29.7.2",
                                    "ApiVersion": "1.55",
                                    "Os": "linux",
                                    "Arch": "amd64",
                                }
                            ),
                            b"",
                        )
                    self_test.assertIn("inspect", command)
                    container_id = command[-1]
                    with lock:
                        document = documents[container_id]
                    return executor.CommandCapture(
                        0,
                        executor.canonical_line(document),
                        b"",
                    )

            def open_listener(namespace: object, branch: str) -> Listener:
                return Listener(branch, original_open(namespace, branch))

            def transaction_runner(**kwargs: object) -> dict[str, object]:
                branch = str(kwargs["labels"][executor.BRANCH_LABEL])
                container_id = hashlib.sha256(
                    f"{case}:{branch}".encode("ascii")
                ).hexdigest()
                document = self._container_document(
                    container_id=container_id,
                    name=str(kwargs["container_name"]),
                    labels=dict(kwargs["labels"]),
                    state="running",
                    mounts=dict(kwargs["expected_mounts"]),
                    daemon_injected_labels=(
                        {
                            executor._DOCKER_DESKTOP_WSL_DISTRO_LABEL:
                            executor._DOCKER_DESKTOP_WSL_DISTRO_VALUE
                        }
                        if peer_identity_mode
                        == executor.PEER_IDENTITY_MODE_DOCKER_DESKTOP_WSL2_PID0
                        else None
                    ),
                )
                binding_destination = next(
                    destination
                    for destination in kwargs["expected_mounts"]
                    if str(destination).startswith("/run/vast/bindings/")
                )
                document["Config"]["Cmd"] = [
                    "--binding",
                    binding_destination,
                    "--socket",
                    f"/run/vast/analytics/{branch}.sock",
                    "--max-requests",
                    "2",
                    "--gpu-device-index",
                    "0",
                ]
                with lock:
                    documents[container_id] = document
                    container_by_branch[branch] = container_id
                barrier.wait(timeout=10)
                try:
                    action = kwargs["after_start"](container_id)
                    return {
                        "container_id": container_id,
                        "action": action,
                        "stdout": b"",
                        "stderr": b"",
                        "preinspect_sha256": "8" * 64,
                        "running_inspect_sha256": "9" * 64,
                        "postinspect_sha256": "a" * 64,
                    }
                finally:
                    with lock:
                        cleaned.append(branch)

            def stage(
                run_root: Path,
                source: executor.BindingInventory,
            ) -> tuple[executor.BindingInventory, tuple[Path, ...], Path]:
                model_root = run_root / "model_staging"
                model_root.mkdir()
                staged = replace(
                    source,
                    source_paths={
                        branch: model_root / source.source_paths[branch].name
                        for branch in pilot.BRANCHES
                    },
                    engine_paths={
                        branch: model_root / source.engine_paths[branch].name
                        for branch in pilot.BRANCHES
                    },
                )
                return staged, (), model_root

            with tempfile.TemporaryDirectory(dir=ROOT) as raw:
                run_root = Path(raw) / "runs" / "nonpublication" / case
                run_root.mkdir(mode=0o700, parents=True)
                bindings_root = run_root / "bindings"
                bindings_root.mkdir()
                for branch in pilot.BRANCHES:
                    executor._write_new(
                        bindings_root / f"{branch}.tensorrt_cuda.json",
                        b"{}\n",
                    )
                run_identity = hashlib.sha256(
                    f"{raw}:{case}".encode("utf-8")
                ).hexdigest()
                expected_ipc = executor._ipc_runtime_path(run_identity)
                self.assertFalse(expected_ipc.exists())
                caught: BaseException | None = None
                observations: list[dict[str, object]] | None = None
                self_test = self
                runtime_daemon = self._peercred_daemon()
                platform_observation = (
                    executor._build_peercred_pid0_platform_observation(
                        b"6.6.87.2-microsoft-standard-WSL2\n",
                        runtime_daemon,
                    )
                    if peer_identity_mode
                    == executor.PEER_IDENTITY_MODE_DOCKER_DESKTOP_WSL2_PID0
                    else None
                )

                def observe_platform_at_barrier(
                    _daemon: Mapping[str, object],
                ) -> dict[str, object]:
                    self.assertIsNotNone(platform_observation)
                    observed = dict(platform_observation or {})
                    if platform_drift_at_barrier:
                        observed["observation_sha256"] = "0" * 64
                    return observed

                forbidden_native_platform_observer = mock.Mock(
                    side_effect=AssertionError(
                        "native peer mode must not observe the WSL2 pid0 platform"
                    )
                )

                with self._native_run_lease(
                    run_identity
                ) as run_lease, mock.patch.dict(
                    sys.modules,
                    {
                        "analytics_execution_endpoint": endpoint,
                        "analytics_execution_worker": worker,
                    },
                ), mock.patch.object(
                    executor,
                    "_open_ipc_listener",
                    side_effect=open_listener,
                ):
                    try:
                        observations = executor._run_tensor_workers(
                            project_root=Path(raw),
                            run_root=run_root,
                            logical_run_root=f"runs/nonpublication/{case}",
                            run_identity=run_identity,
                            plan=plan,
                            requests=requests,
                            bindings=inventory,
                            payloads=payloads,
                            binding_descriptors=descriptors,
                            runtime_probe={"validated_runtime_probe": {}},
                            runtime_image={"labels": dict(executor.IMAGE_LABELS)},
                            runtime_daemon=runtime_daemon,
                            docker_cli_identity=executor.FileIdentity(1, "d" * 64),
                            command_runner=Runner(),
                            cleanup_mutex=executor._NullCleanupMutex(),
                            container_registry=executor._OwnedContainerRegistry(
                                run_identity
                            ),
                            progress=executor._ExecutionProgressLedger(
                                run_root=run_root,
                                run_id="synthetic-peer-mode-worker",
                                run_identity=run_identity,
                                role="secondary",
                                requests=requests,
                            ),
                            run_lease=run_lease,
                            peercred_diagnostic_only=diagnostic_only,
                            peer_identity_mode=peer_identity_mode,
                            peercred_platform_observation=platform_observation,
                            peercred_platform_observer=(
                                observe_platform_at_barrier
                                if platform_observation is not None
                                else forbidden_native_platform_observer
                            ),
                            _transaction_runner=transaction_runner,
                            _stage_inventory=stage,
                            _peercred_diagnostic_writer=writer,
                            _executor_source_observer=lambda _path: executor.FileIdentity(
                                123, "e" * 64
                            ),
                        )
                    except BaseException as error:
                        caught = error
                self.assertEqual(set(cleaned), set(pilot.BRANCHES))
                self.assertEqual(set(closed), set(pilot.BRANCHES))
                self.assertFalse(expected_ipc.exists())
                self.assertFalse((run_root / "model_staging").exists())
                if platform_observation is None:
                    forbidden_native_platform_observer.assert_not_called()
                diagnostic_files = sorted(run_root.glob("so_peercred_*.json"))
                if expect_success:
                    self.assertIsNone(caught)
                    self.assertIsNotNone(observations)
                    self.assertEqual(len(observations or []), 8)
                    self.assertEqual(set(handshakes), set(pilot.BRANCHES))
                    self.assertEqual(len(inferred), 8)
                    self.assertEqual(diagnostic_files, [])
                    for item in observations or []:
                        peer_identity = item["peer_identity"]
                        self.assertEqual(
                            peer_identity["peer_identity_mode"],
                            peer_identity_mode,
                        )
                        self.assertIs(
                            peer_identity[
                                "global_four_worker_handshake_barrier_attested"
                            ],
                            True,
                        )
                else:
                    self.assertIsInstance(
                        caught,
                        executor.ExecutorContractError,
                    )
                    self.assertIsNone(observations)
                    self.assertEqual(
                        set(handshakes),
                        (
                            set(pilot.BRANCHES)
                            if expect_handshakes_on_failure
                            else set()
                        ),
                    )
                    self.assertEqual(inferred, [])
                    if (
                        expect_diagnostics_on_failure
                        and writer is executor._write_peercred_failure_diagnostic
                    ):
                        expected_prefix = (
                            "so_peercred_diagnostic"
                            if diagnostic_only
                            else "so_peercred_failure"
                        )
                        self.assertEqual(
                            [path.name for path in diagnostic_files],
                            sorted(
                                f"{expected_prefix}.{branch}.json"
                                for branch in pilot.BRANCHES
                            ),
                            repr(
                                {
                                    "caught": caught,
                                    "primary": getattr(caught, "primary", None),
                                    "primary_inner": getattr(
                                        getattr(caught, "primary", None),
                                        "primary",
                                        None,
                                    ),
                                    "supplemental": [
                                        {
                                            "scope": item.scope,
                                            "branch": item.branch,
                                            "error": item.error,
                                            "inner": getattr(
                                                item.error,
                                                "primary",
                                                None,
                                            ),
                                        }
                                        for item in getattr(
                                            caught,
                                            "supplemental_failures",
                                            (),
                                        )
                                    ],
                                }
                            ),
                        )
                        for path in diagnostic_files:
                            document = json.loads(path.read_bytes())
                            self.assertEqual(
                                document["container"]["container_id"],
                                container_by_branch[document["branch"]],
                            )
                            self.assertIs(
                                document["stages"][
                                    "peer_credentials_accepted_for_inference"
                                ],
                                False,
                            )
                            self.assertIn(
                                document["filesystem_custody"],
                                (
                                    {
                                        "statfs_magic": executor._LINUX_EXT_FILESYSTEM_MAGIC,
                                        "statfs_magic_hex": "0x0000ef53",
                                        "filesystem_type": "linux_ext_native",
                                        "mount_observation": "native_ext_mode_enforcement",
                                        "run_root_effective_mode": "0700",
                                        "requested_file_mode": "0400",
                                        "file_effective_mode": "0400",
                                    },
                                    {
                                        "statfs_magic": executor._LINUX_V9FS_MAGIC,
                                        "statfs_magic_hex": "0x01021997",
                                        "filesystem_type": (
                                            "drvfs_9p_without_metadata_observed"
                                        ),
                                        "mount_observation": (
                                            "drvfs_9p_effective_mode_projection"
                                        ),
                                        "run_root_effective_mode": "0777",
                                        "requested_file_mode": "0400",
                                        "file_effective_mode": "0555",
                                    },
                                ),
                            )
                            self.assertIs(
                                document["confidentiality_attested"],
                                False,
                            )
                            self.assertIs(
                                document["filesystem_acl_attested"],
                                False,
                            )
                            self.assertIs(
                                document["windows_acl_attested"],
                                False,
                            )
                            self.assertIs(document["inference_performed"], False)
                            for field in executor.FALSE_CLAIM_FIELDS:
                                self.assertIs(document[field], False)
                    else:
                        self.assertEqual(diagnostic_files, [])
                return observations, run_root

        exact = (4321, executor.CONTAINER_UID, executor.CONTAINER_GID)
        run_case(
            case="normal-mismatch",
            peer_values={
                "plate_number": (0, executor.CONTAINER_UID, executor.CONTAINER_GID),
                "vehicle_type": (4321, 0, executor.CONTAINER_GID),
                "damage": (4321, executor.CONTAINER_UID, 0),
                "foreign_object": (-1, executor.CONTAINER_UID, executor.CONTAINER_GID),
            },
            diagnostic_only=False,
        )
        run_case(
            case="diagnostic-only-exact",
            peer_values={branch: exact for branch in pilot.BRANCHES},
            diagnostic_only=True,
        )
        run_case(
            case="normal-exact",
            peer_values={branch: exact for branch in pilot.BRANCHES},
            diagnostic_only=False,
            expect_success=True,
        )
        run_case(
            case="normal-exact",
            peer_values={
                branch: (0, executor.CONTAINER_UID, executor.CONTAINER_GID)
                for branch in pilot.BRANCHES
            },
            diagnostic_only=False,
            peer_identity_mode=(
                executor.PEER_IDENTITY_MODE_DOCKER_DESKTOP_WSL2_PID0
            ),
            expect_success=True,
        )
        run_case(
            case="hidden-platform-drift-at-barrier",
            peer_values={
                branch: (0, executor.CONTAINER_UID, executor.CONTAINER_GID)
                for branch in pilot.BRANCHES
            },
            diagnostic_only=False,
            peer_identity_mode=(
                executor.PEER_IDENTITY_MODE_DOCKER_DESKTOP_WSL2_PID0
            ),
            expect_handshakes_on_failure=True,
            expect_diagnostics_on_failure=False,
            platform_drift_at_barrier=True,
        )
        run_case(
            case="native-daemon-drift-at-barrier",
            peer_values={branch: exact for branch in pilot.BRANCHES},
            diagnostic_only=False,
            expect_handshakes_on_failure=True,
            expect_diagnostics_on_failure=False,
            daemon_drift_at_barrier=True,
        )
        run_case(
            case="diagnostic-only-pid0",
            peer_values={
                branch: (0, executor.CONTAINER_UID, executor.CONTAINER_GID)
                for branch in pilot.BRANCHES
            },
            diagnostic_only=True,
        )

        def failed_writer(**_kwargs: object) -> Path:
            raise executor.ExecutorContractError("synthetic diagnostic writer failure")

        run_case(
            case="diagnostic-writer-failure",
            peer_values={branch: exact for branch in pilot.BRANCHES},
            diagnostic_only=True,
            writer=failed_writer,
        )

    def test_four_branch_partial_baseexception_cleans_native_ipc_and_model_runtime(self) -> None:
        class PartialFailure(BaseException):
            pass

        requests: list[dict[str, object]] = []
        bindings: dict[str, dict[str, object]] = {}
        sources: dict[str, Path] = {}
        engines: dict[str, Path] = {}
        identities: dict[str, executor.FileIdentity] = {}
        descriptors: dict[str, dict[str, object]] = {}
        for branch in pilot.BRANCHES:
            sources[branch] = Path(f"/private/{branch}.onnx")
            engines[branch] = Path(f"/private/{branch}.engine")
            identities[branch] = executor.FileIdentity(1, hashlib.sha256(branch.encode()).hexdigest())
            bindings[branch] = {
                "source_path": f"/run/vast/models/{branch}.onnx",
                "engine_path": f"/run/vast/models/{branch}.engine",
            }
            descriptors[branch] = {"path": f"bindings/{branch}.tensorrt_cuda.json"}
            for codec in pilot.CODECS:
                requests.append(
                    {
                        "request_id": f"{branch}-{codec}",
                        "branch": branch,
                        "codec": codec,
                    }
                )
        inventory = executor.BindingInventory(
            bindings=bindings,
            source_paths=sources,
            engine_paths=engines,
            source_identities=identities,
            engine_identities=identities,
            manifest_identity_sha256="1" * 64,
            execution_config_identity_sha256="2" * 64,
        )
        barrier = threading.Barrier(4)
        reached: list[str] = []
        destroyed: list[Path] = []

        def transaction_runner(**kwargs: object) -> dict[str, object]:
            branch = str(kwargs["labels"][executor.BRANCH_LABEL])
            reached.append(branch)
            barrier.wait(timeout=5)
            if branch == "damage":
                raise PartialFailure()
            return {
                "container_id": "8" * 64,
                "action": [{}, {}],
                "stdout": b"",
                "stderr": b"",
                "preinspect_sha256": "9" * 64,
                "running_inspect_sha256": "a" * 64,
                "postinspect_sha256": "b" * 64,
            }

        def session_factory(**_kwargs: object) -> tuple[object, dict[str, object]]:
            return object(), {}

        def stage(run_root: Path, source: executor.BindingInventory):
            model_root = run_root / "model_staging"
            model_root.mkdir()
            return source, (), model_root

        with tempfile.TemporaryDirectory() as raw:
            run_root = Path(raw) / "simulated-drvfs-run"
            run_root.mkdir(mode=0o700)
            bindings_root = run_root / "bindings"
            bindings_root.mkdir()
            native_parent = Path(raw) / "native-posix-runtime"
            native_parent.mkdir()
            ipc_path = native_parent / "held-ipc"

            @dataclass
            class SyntheticIpcNamespace:
                path: Path

            def create_ipc(_run_identity: str) -> SyntheticIpcNamespace:
                os.mkdir(ipc_path, 0o700)
                return SyntheticIpcNamespace(ipc_path)

            def destroy_ipc(namespace: SyntheticIpcNamespace) -> None:
                self.assertEqual(namespace.path, ipc_path)
                self.assertEqual(list(namespace.path.iterdir()), [])
                destroyed.append(namespace.path)
                namespace.path.rmdir()

            with self.assertRaises(executor._ExecutionFailureBundle) as raised:
                executor._run_tensor_workers(
                    project_root=Path(raw),
                    run_root=run_root,
                    logical_run_root="runs/nonpublication/synthetic-partial",
                    run_identity="c" * 64,
                    plan={},
                    requests=requests,
                    bindings=inventory,
                    payloads=executor.TensorInventory(payloads={}, bundle_observations=[]),
                    binding_descriptors=descriptors,
                    runtime_probe={"validated_runtime_probe": {"synthetic": True}},
                    runtime_image={"labels": dict(executor.IMAGE_LABELS)},
                    runtime_daemon={"synthetic": True},
                    docker_cli_identity=executor.FileIdentity(1, "d" * 64),
                    command_runner=mock.Mock(),
                    cleanup_mutex=executor._NullCleanupMutex(),
                    container_registry=executor._OwnedContainerRegistry("c" * 64),
                    progress=executor._ExecutionProgressLedger(
                        run_root=run_root,
                        run_id="synthetic-partial-worker",
                        run_identity="c" * 64,
                        role="secondary",
                        requests=requests,
                    ),
                    _session_factory=session_factory,
                    _transaction_runner=transaction_runner,
                    _stage_inventory=stage,
                    _ipc_namespace_factory=create_ipc,
                    _ipc_namespace_destroyer=destroy_ipc,
                )
            failures = [
                raised.exception.primary,
                *(item.error for item in raised.exception.supplemental_failures),
            ]
            self.assertTrue(any(isinstance(item, PartialFailure) for item in failures))
            self.assertEqual(set(reached), set(pilot.BRANCHES))
            self.assertEqual(destroyed, [ipc_path])
            self.assertFalse(ipc_path.exists())
            self.assertFalse((run_root / "model_staging").exists())
            self.assertFalse((run_root / "ipc").exists())

    @unittest.skipUnless(os.name == "posix", "real native IPC four-branch cleanup")
    def test_real_watchdog_closes_four_listeners_when_accept_raises_baseexception(self) -> None:
        class AcceptFailure(BaseException):
            pass

        requests: list[dict[str, object]] = []
        bindings: dict[str, dict[str, object]] = {}
        sources: dict[str, Path] = {}
        engines: dict[str, Path] = {}
        identities: dict[str, executor.FileIdentity] = {}
        descriptors: dict[str, dict[str, object]] = {}
        for branch in pilot.BRANCHES:
            sources[branch] = Path(f"/private/{branch}.onnx")
            engines[branch] = Path(f"/private/{branch}.engine")
            identities[branch] = executor.FileIdentity(
                1,
                hashlib.sha256(branch.encode("ascii")).hexdigest(),
            )
            bindings[branch] = {
                "source_path": f"/run/vast/models/{branch}.onnx",
                "engine_path": f"/run/vast/models/{branch}.engine",
            }
            descriptors[branch] = {"path": f"bindings/{branch}.tensorrt_cuda.json"}
            for codec in pilot.CODECS:
                requests.append(
                    {
                        "request_id": f"{branch}-{codec}",
                        "branch": branch,
                        "codec": codec,
                    }
                )
        inventory = executor.BindingInventory(
            bindings=bindings,
            source_paths=sources,
            engine_paths=engines,
            source_identities=identities,
            engine_identities=identities,
            manifest_identity_sha256="1" * 64,
            execution_config_identity_sha256="2" * 64,
        )
        barrier = threading.Barrier(4)
        reached: list[str] = []
        closed: list[str] = []
        original_open = executor._open_ipc_listener

        class FailingListener:
            def __init__(self, branch: str, inner: socket.socket) -> None:
                self.branch = branch
                self.inner = inner

            def accept(self):
                raise AcceptFailure()

            def close(self) -> None:
                self.inner.close()
                closed.append(self.branch)

        def failing_open(namespace: object, branch: str) -> FailingListener:
            return FailingListener(branch, original_open(namespace, branch))

        def transaction_runner(**kwargs: object) -> dict[str, object]:
            branch = str(kwargs["labels"][executor.BRANCH_LABEL])
            reached.append(branch)
            barrier.wait(timeout=5)
            return kwargs["after_start"]("8" * 64)

        def stage(run_root: Path, source: executor.BindingInventory):
            self.assertTrue(expected_ipc.is_dir())
            self.assertEqual(expected_ipc.parent, executor.IPC_RUNTIME_PARENT)
            model_root = run_root / "model_staging"
            model_root.mkdir()
            return source, (), model_root

        endpoint = types.ModuleType("analytics_execution_endpoint")
        endpoint.expected_capability_from_binding_and_probe = lambda **_kwargs: {}
        worker = types.ModuleType("analytics_execution_worker")
        worker.ExecutionClient = object
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_root = Path(raw) / "simulated-drvfs-run"
            run_root.mkdir(mode=0o700)
            if str(ROOT).startswith("/mnt/"):
                run_root_fd = os.open(
                    run_root,
                    os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
                )
                try:
                    self.assertNotEqual(
                        executor._linux_fstatfs_magic(run_root_fd),
                        executor._LINUX_EXT_FILESYSTEM_MAGIC,
                    )
                finally:
                    os.close(run_root_fd)
            bindings_root = run_root / "bindings"
            bindings_root.mkdir()
            for branch in pilot.BRANCHES:
                executor._write_new(
                    bindings_root / f"{branch}.tensorrt_cuda.json",
                    b"{}\n",
                )
            run_identity = hashlib.sha256(os.fsencode(run_root)).hexdigest()
            expected_ipc = executor._ipc_runtime_path(run_identity)
            self.assertFalse(expected_ipc.exists())
            with self._native_run_lease(
                run_identity
            ) as run_lease, mock.patch.dict(
                sys.modules,
                {
                    "analytics_execution_endpoint": endpoint,
                    "analytics_execution_worker": worker,
                },
            ), mock.patch.object(
                executor,
                "_open_ipc_listener",
                side_effect=failing_open,
            ):
                with self.assertRaises(
                    executor._ExecutionFailureBundle
                ) as raised:
                    executor._run_tensor_workers(
                        project_root=Path(raw),
                        run_root=run_root,
                        logical_run_root="runs/nonpublication/synthetic-accept-failure",
                        run_identity=run_identity,
                        plan={},
                        requests=requests,
                        bindings=inventory,
                        payloads=executor.TensorInventory(
                            payloads={},
                            bundle_observations=[],
                        ),
                        binding_descriptors=descriptors,
                        runtime_probe={"validated_runtime_probe": {}},
                        runtime_image={"labels": dict(executor.IMAGE_LABELS)},
                        runtime_daemon=self._peercred_daemon(),
                        docker_cli_identity=executor.FileIdentity(1, "d" * 64),
                        command_runner=mock.Mock(),
                        cleanup_mutex=executor._NullCleanupMutex(),
                        container_registry=executor._OwnedContainerRegistry(
                            run_identity
                        ),
                        progress=executor._ExecutionProgressLedger(
                            run_root=run_root,
                            run_id="synthetic-accept-failure-worker",
                            run_identity=run_identity,
                            role="secondary",
                            requests=requests,
                        ),
                        run_lease=run_lease,
                        _transaction_runner=transaction_runner,
                        _stage_inventory=stage,
                    )
            failures = [
                raised.exception.primary,
                *(item.error for item in raised.exception.supplemental_failures),
            ]
            self.assertEqual(
                sum(isinstance(item, AcceptFailure) for item in failures),
                4,
            )
            self.assertEqual(set(reached), set(pilot.BRANCHES))
            self.assertEqual(set(closed), set(pilot.BRANCHES))
            self.assertEqual(len(closed), 4)
            self.assertFalse(expected_ipc.exists())
            self.assertFalse((run_root / "model_staging").exists())

    def test_owned_container_baseexception_cleanup_uses_exact_id_and_verifies_absence(self) -> None:
        container_id = "c" * 64
        name = "vast-kpp-v2-np-0123456789abcdef-probe"
        labels = {
            executor.OWNER_LABEL: executor.OWNER_VALUE,
            executor.RUN_LABEL: "d" * 64,
            executor.BRANCH_LABEL: "runtime_probe",
        }
        calls: list[tuple[str, ...]] = []
        inspect_count = 0
        created_flag = False
        removed = False

        class Cancellation(BaseException):
            pass

        class Runner:
            def run(
                runner_self,
                argv: list[str],
                *,
                timeout_seconds: float,
                stdout_limit: int,
                stderr_limit: int,
            ) -> executor.CommandCapture:
                nonlocal inspect_count, created_flag, removed
                del timeout_seconds, stdout_limit, stderr_limit, runner_self
                command = tuple(argv)
                calls.append(command)
                if "create" in command:
                    created_flag = True
                    return executor.CommandCapture(0, (container_id + "\n").encode(), b"")
                if "ls" in command:
                    return executor.CommandCapture(0, b"", b"")
                if "inspect" in command:
                    inspect_count += 1
                    reference = command[-1]
                    if not created_flag or removed:
                        return executor.CommandCapture(
                            1,
                            b"",
                            f"Error: No such container: {reference}\n".encode("ascii"),
                        )
                    if inspect_count == 2:
                        value = self._container_document(
                            container_id=container_id,
                            name=name,
                            labels=labels,
                            state="created",
                            daemon_injected_labels={
                                "desktop.docker.io/wsl-distro": "Ubuntu"
                            },
                        )
                        return executor.CommandCapture(0, executor.canonical_line(value), b"")
                    if inspect_count in {3, 4}:
                        value = self._container_document(
                            container_id=container_id,
                            name=name,
                            labels=labels,
                            state="running",
                            daemon_injected_labels={
                                "desktop.docker.io/wsl-distro": "Ubuntu"
                            },
                        )
                        return executor.CommandCapture(0, executor.canonical_line(value), b"")
                    raise AssertionError((inspect_count, command))
                if "start" in command:
                    return executor.CommandCapture(0, (container_id + "\n").encode(), b"")
                if "rm" in command:
                    self.assertEqual(command[-1], container_id)
                    removed = True
                    return executor.CommandCapture(0, (container_id + "\n").encode(), b"")
                raise AssertionError(command)

        create_command = executor._build_probe_create_command(
            container_name=name,
            labels=labels,
        )
        with self.assertRaises(Cancellation):
            executor._run_owned_container_transaction(
                runner=Runner(),
                create_command=create_command,
                container_name=name,
                labels=labels,
                expected_mounts={},
                after_start=lambda _container_id: (_ for _ in ()).throw(Cancellation()),
                cleanup_mutex=executor._NullCleanupMutex(),
            )

        self.assertTrue(any("rm" in command for command in calls))
        self.assertEqual(inspect_count, 5)
        self.assertFalse(any(command[-1] == name for command in calls if "rm" in command))

    def test_resume_reaper_removes_only_exact_owned_deterministic_container_id(self) -> None:
        run_identity = "d" * 64
        run_id = "resume-reaper-run"
        container_id = "e" * 64
        name = f"vast-kpp-v2-np-{run_identity[:16]}-probe"
        labels = {
            executor.OWNER_LABEL: executor.OWNER_VALUE,
            executor.RUN_LABEL: run_identity,
            executor.BRANCH_LABEL: "runtime_probe",
        }
        removed = False
        document = self._container_document(
            container_id=container_id,
            name=name,
            labels=labels,
            state="created",
            daemon_injected_labels={
                "desktop.docker.io/wsl-distro": "Ubuntu"
            },
        )

        class Runner:
            def run(
                runner_self,
                argv: list[str],
                *,
                timeout_seconds: float,
                stdout_limit: int,
                stderr_limit: int,
            ) -> executor.CommandCapture:
                nonlocal removed
                del runner_self, timeout_seconds, stdout_limit, stderr_limit
                command = tuple(argv)
                if "inspect" in command:
                    reference = command[-1]
                    if not removed and reference in {name, container_id}:
                        return executor.CommandCapture(0, executor.canonical_line(document), b"")
                    return executor.CommandCapture(
                        1,
                        b"",
                        f"Error: No such container: {reference}\n".encode("ascii"),
                    )
                if "ls" in command:
                    if removed:
                        return executor.CommandCapture(0, b"", b"")
                    return executor.CommandCapture(
                        0,
                        executor.canonical_line({"ID": container_id, "Names": name}),
                        b"",
                    )
                if "rm" in command:
                    self.assertEqual(command[-1], container_id)
                    removed = True
                    return executor.CommandCapture(0, (container_id + "\n").encode(), b"")
                raise AssertionError(command)

        bindings = {}
        source_paths = {}
        engine_paths = {}
        identities = {}
        for branch in pilot.BRANCHES:
            bindings[branch] = {
                "source_path": f"/run/vast/models/{branch}.onnx",
                "engine_path": f"/run/vast/models/{branch}.engine",
            }
            source_paths[branch] = Path(f"/source/{branch}.onnx")
            engine_paths[branch] = Path(f"/engine/{branch}.engine")
            identities[branch] = executor.FileIdentity(1, hashlib.sha256(branch.encode()).hexdigest())
        inventory = executor.BindingInventory(
            bindings=bindings,
            source_paths=source_paths,
            engine_paths=engine_paths,
            source_identities=identities,
            engine_identities=identities,
            manifest_identity_sha256="1" * 64,
            execution_config_identity_sha256="2" * 64,
        )
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "runs" / "nonpublication" / run_id).mkdir(parents=True)
            reaped, existed = executor._reap_stale_execution(
                runner=Runner(),
                project_root=root,
                run_id=run_id,
                run_identity=run_identity,
                bindings=inventory,
                cleanup_mutex=executor._NullCleanupMutex(),
                expected_image_labels=executor.IMAGE_LABELS,
            )
        self.assertTrue(existed)
        self.assertTrue(removed)
        self.assertEqual(reaped, [hashlib.sha256(container_id.encode()).hexdigest()])

    @unittest.skipUnless(os.name == "posix", "exact WSL stale-recovery ordering")
    def test_same_v2_existing_run_recovers_exact_four_docker29_workers_before_block(
        self,
    ) -> None:
        documents: dict[str, dict[str, object]] = {}
        expected_image_labels: dict[str, str] | None = None
        bindings: dict[str, dict[str, object]] = {}
        source_paths: dict[str, Path] = {}
        engine_paths: dict[str, Path] = {}
        identities: dict[str, executor.FileIdentity] = {}
        for branch in pilot.BRANCHES:
            document, mounts, image_labels = self._v2_mount_fixture(branch)
            documents[branch] = document
            if expected_image_labels is None:
                expected_image_labels = image_labels
            else:
                self.assertEqual(expected_image_labels, image_labels)
            source_destination = next(
                destination for destination in mounts if destination.endswith(".onnx")
            )
            engine_destination = next(
                destination for destination in mounts if destination.endswith(".engine")
            )
            bindings[branch] = {
                "source_path": source_destination,
                "engine_path": engine_destination,
            }
            source_paths[branch] = Path("/source") / PurePosixPath(
                source_destination
            ).name
            engine_paths[branch] = Path("/engine") / PurePosixPath(
                engine_destination
            ).name
            identities[branch] = executor.FileIdentity(
                1, hashlib.sha256(branch.encode("ascii")).hexdigest()
            )
        self.assertIsNotNone(expected_image_labels)
        inventory = executor.BindingInventory(
            bindings=bindings,
            source_paths=source_paths,
            engine_paths=engine_paths,
            source_identities=identities,
            engine_identities=identities,
            manifest_identity_sha256="1" * 64,
            execution_config_identity_sha256="2" * 64,
        )
        remaining = {
            str(document["Name"])[1:]: document for document in documents.values()
        }
        calls: list[tuple[str, ...]] = []

        class Runner:
            def run(
                runner_self,
                argv: list[str],
                *,
                timeout_seconds: float,
                stdout_limit: int,
                stderr_limit: int,
            ) -> executor.CommandCapture:
                del runner_self, timeout_seconds, stdout_limit, stderr_limit
                command = tuple(argv)
                calls.append(command)
                if "inspect" in command:
                    reference = command[-1]
                    for name, document in remaining.items():
                        if reference in {name, f"/{name}", document["Id"]}:
                            return executor.CommandCapture(
                                0, executor.canonical_line(document), b""
                            )
                    return executor.CommandCapture(
                        1,
                        b"\n",
                        f"Error response from daemon: No such container: {reference}\n".encode(
                            "ascii"
                        ),
                    )
                if "ls" in command:
                    rows = b"".join(
                        executor.canonical_line(
                            {"ID": document["Id"], "Names": name}
                        )
                        for name, document in sorted(remaining.items())
                    )
                    return executor.CommandCapture(0, rows, b"")
                if "rm" in command:
                    container_id = command[-1]
                    matches = [
                        name
                        for name, document in remaining.items()
                        if document["Id"] == container_id
                    ]
                    self.assertEqual(len(matches), 1)
                    del remaining[matches[0]]
                    return executor.CommandCapture(
                        0, (container_id + "\n").encode("ascii"), b""
                    )
                raise AssertionError(command)

        gpu_probe = mock.Mock(
            side_effect=AssertionError("existing-v2 recovery must not start GPU probe")
        )
        worker_runner = mock.Mock(
            side_effect=AssertionError("existing-v2 recovery must not start workers")
        )
        dependencies = executor._ExecutorDependencies(
            platform_name="posix",
            environment={},
            observe_docker_cli=mock.Mock(),
            command_runner=Runner(),
            planner_builder=mock.Mock(),
            gpu_probe=gpu_probe,
            observe_file=mock.Mock(),
            worker_runner=worker_runner,
            stale_reaper=executor._reap_stale_execution,
        )
        attempt_requests = [
            {
                "request_id": f"recovery-{branch}-{codec}",
                "branch": branch,
                "codec": codec,
            }
            for branch in pilot.BRANCHES
            for codec in pilot.CODECS
        ]
        artifact, status = executor._execute_mutating_phase(
            dependencies=dependencies,
            image={"labels": expected_image_labels},
            daemon={},
            cli=executor.FileIdentity(44_986_088, "3" * 64),
            run_identity=V2_RUN_IDENTITY,
            role="secondary",
            project_root=ROOT,
            run_id=V2_RUN_ID,
            plan={},
            requests=attempt_requests,
            bindings=inventory,
            payloads=executor.TensorInventory(payloads={}, bundle_observations=[]),
            model_file_observations={},
            expected_daemon_id="unused",
            expected_daemon_server_version="unused",
            expected_daemon_api_version="unused",
            cleanup_mutex=executor._NullCleanupMutex(),
            run_lease=executor._NullRunLease(),
            container_registry=executor._OwnedContainerRegistry(
                V2_RUN_IDENTITY
            ),
            attempt_context=executor._ExecutionAttemptContext(
                run_id=V2_RUN_ID,
                run_identity=V2_RUN_IDENTITY,
                role="secondary",
                requests=attempt_requests,
            ),
        )
        self.assertEqual(status, 78)
        self.assertEqual(
            artifact["status"], "blocked_existing_nonpublication_run_namespace"
        )
        self.assertEqual(remaining, {})
        self.assertEqual(
            artifact["runtime_preflight"]["reaped_container_id_sha256s"],
            sorted(
                hashlib.sha256(container_id.encode("ascii")).hexdigest()
                for container_id, _sha256, _size in V2_CONTAINER_FIXTURES.values()
            ),
        )
        self.assertFalse(
            any("create" in command or "start" in command for command in calls)
        )
        gpu_probe.assert_not_called()
        worker_runner.assert_not_called()

    def test_gpu_probe_is_daemon_owned_uuid_bound_and_removed(self) -> None:
        container_id = "e" * 64
        run_identity = "f" * 64
        name = f"vast-kpp-v2-np-{run_identity[:16]}-probe"
        labels = {
            executor.OWNER_LABEL: executor.OWNER_VALUE,
            executor.RUN_LABEL: run_identity,
            executor.BRANCH_LABEL: "runtime_probe",
        }
        probe = {
            "schema_version": 1,
            "artifact_kind": "vast_analytics_execution_worker_runtime_probe",
            "protocol_identity_sha256": executor.PROTOCOL_IDENTITY_SHA256,
            "engine": "tensorrt_cuda",
            "runtime_name": "TensorRT",
            "runtime_version": "8.6.1.6",
            "device_api": "NVIDIA_CUDA",
            "device_id": executor.TENSORRT_GPU_UUID,
            "native_inference_api": "nvinfer1::IExecutionContext::enqueueV3",
            "execution_path": "tensorrt_cuda_native",
            "worker_implementation_sha256": executor.TENSORRT_WORKER_IMPLEMENTATION_SHA256,
            "socket_seqpacket": True,
            "scm_rights": True,
            "memfd_sealing": True,
            "model_loaded": False,
            "inference_performed": False,
        }
        inspect_states = iter(("created", "exited", "exited", "exited"))
        removed = False
        created_flag = False

        class Runner:
            def run(
                runner_self,
                argv: list[str],
                *,
                timeout_seconds: float,
                stdout_limit: int,
                stderr_limit: int,
            ) -> executor.CommandCapture:
                nonlocal removed, created_flag
                del timeout_seconds, stdout_limit, stderr_limit, runner_self
                command = tuple(argv)
                if "create" in command:
                    created_flag = True
                    return executor.CommandCapture(0, (container_id + "\n").encode(), b"")
                if "ls" in command:
                    return executor.CommandCapture(0, b"", b"")
                if "inspect" in command:
                    reference = command[-1]
                    if not created_flag or removed:
                        return executor.CommandCapture(
                            1,
                            b"",
                            f"Error: No such container: {reference}\n".encode("ascii"),
                        )
                    state = next(inspect_states)
                    document = self._container_document(
                        container_id=container_id,
                        name=name,
                        labels=labels,
                        state=state,
                        daemon_injected_labels={
                            "desktop.docker.io/wsl-distro": "Ubuntu"
                        },
                    )
                    return executor.CommandCapture(0, executor.canonical_line(document), b"")
                if "start" in command:
                    return executor.CommandCapture(0, (container_id + "\n").encode(), b"")
                if "wait" in command:
                    return executor.CommandCapture(0, b"0\n", b"")
                if "logs" in command:
                    return executor.CommandCapture(0, executor.canonical_line(probe), b"")
                if "rm" in command:
                    removed = True
                    return executor.CommandCapture(0, (container_id + "\n").encode(), b"")
                raise AssertionError(command)

        observation = executor._probe_exact_gpu(
            runner=Runner(),
            run_identity=run_identity,
            cleanup_mutex=executor._NullCleanupMutex(),
            container_registry=executor._OwnedContainerRegistry(run_identity),
        )
        self.assertEqual(observation["device_id"], executor.TENSORRT_GPU_UUID)
        self.assertEqual(
            observation["worker_implementation_sha256"],
            executor.TENSORRT_WORKER_IMPLEMENTATION_SHA256,
        )
        self.assertTrue(removed)

    def test_exact_eight_request_synthetic_execution_writes_only_nonpublication_assessment(self) -> None:
        payloads: dict[str, bytes] = {}
        requests: list[dict[str, object]] = []
        for branch in pilot.BRANCHES:
            for codec, ordinal in (("h264", 0), ("h265", 1)):
                request_id = f"kpp-v2-nonpublication-{branch}-{codec}-calibration-smoke-v1"
                payload = hashlib.sha256(request_id.encode("ascii")).digest() * (
                    pilot.TENSOR_SEGMENT_BYTES // 32
                )
                payloads[request_id] = payload
                requests.append(
                    {
                        "request_id": request_id,
                        "sample_id": f"kpp-v2-candidate.{branch}.calibration.{codec}.{ordinal:02d}",
                        "branch": branch,
                        "codec": codec,
                        "corpus_role": "calibration",
                        "source_role": pilot.BRANCH_BINDINGS[branch]["source_role"],
                        "tensor": {
                            "path": f"staging/synthetic/tensor_{codec}_{pilot.BRANCH_BINDINGS[branch]['source_role']}.f32.bin",
                            "size_bytes": 30 * pilot.TENSOR_SEGMENT_BYTES,
                            "sha256": "3" * 64,
                            "offset_bytes": ordinal * pilot.TENSOR_SEGMENT_BYTES,
                            "segment_size_bytes": pilot.TENSOR_SEGMENT_BYTES,
                            "segment_sha256": hashlib.sha256(payload).hexdigest(),
                            "encoding": "raw_f32_le_c_contiguous_v1",
                            "dtype": "float32",
                            "shape": [1, 3, 224, 224],
                            "layout": "NCHW",
                            "preprocessing_contract_sha256": "4" * 64,
                        },
                        "model": dict(pilot.TENSORRT_ENGINE_PINS[branch]),
                    }
                )
        plan = {
            "schema_version": 1,
            "artifact_kind": pilot.PLAN_ARTIFACT_KIND,
            "claim_status": "planning_only_nonpublication_not_execution",
            "role": "secondary",
            "matrix_identity_sha256": "5" * 64,
            "decision": {"decision_sha256": "6" * 64},
            "candidate": {
                "root": "staging/synthetic",
                "receipt": {
                    "path": f"staging/synthetic/{pilot.RECEIPT_NAME}",
                    "size_bytes": 1,
                    "sha256": "7" * 64,
                    "candidate_receipt_sha256": "8" * 64,
                },
                "dataset_aggregate_sha256": "9" * 64,
                "sampling_rule_sha256": "a" * 64,
                "corpora": [
                    {
                        "role": f"{branch}/{corpus_role} corpus candidate",
                        "path": f"staging/synthetic/corpus_{branch}_{corpus_role}.json",
                        "size_bytes": 1,
                        "sha256": hashlib.sha256(
                            f"{branch}:{corpus_role}".encode("ascii")
                        ).hexdigest(),
                    }
                    for branch in pilot.BRANCHES
                    for corpus_role in pilot.CORPUS_ROLES
                ],
            },
            "runtime": {
                "engine": "tensorrt_cuda",
                "worker_image": pilot.TENSORRT_IMAGE,
                "worker_image_id": pilot.TENSORRT_IMAGE_ID,
                "base_image_id": pilot.TENSORRT_BASE_IMAGE_ID,
                "entrypoint": pilot.TENSORRT_ENTRYPOINT,
                "gpu_uuid": pilot.TENSORRT_GPU_UUID,
                "gpu_device_index": 0,
                "pull_policy": "never",
                "network": "none",
                "read_only_project_mount_required": True,
                "max_requests_per_worker": 2,
                "image_availability_source": "external_caller_assertion_only",
            },
            "request_count": 8,
            "requests": requests,
            "claims": {"semantic_claim": "topology_load_proxy_candidate_only"},
            "pilot_plan_sha256": "b" * 64,
        }
        runner = ScriptedRunner(image_present=True)
        worker_calls: list[tuple[int, int, bool, str]] = []
        platform_observer_calls: list[str] = []
        file_observations: dict[str, executor.FileIdentity] = {}

        def load_bindings(**_kwargs: object) -> executor.BindingInventory:
            bindings: dict[str, dict[str, object]] = {}
            sources: dict[str, Path] = {}
            engines: dict[str, Path] = {}
            source_identities: dict[str, executor.FileIdentity] = {}
            engine_identities: dict[str, executor.FileIdentity] = {}
            for branch in pilot.BRANCHES:
                model = pilot.TENSORRT_ENGINE_PINS[branch]
                sources[branch] = Path(f"/synthetic/{model['source_ref']}.onnx")
                engines[branch] = Path(f"/synthetic/{Path(str(model['engine_path'])).name}")
                source_identity = executor.FileIdentity(
                    123,
                    hashlib.sha256(branch.encode()).hexdigest(),
                )
                engine_identity = executor.FileIdentity(
                    int(model["size_bytes"]), str(model["engine_sha256"])
                )
                source_identities[branch] = source_identity
                engine_identities[branch] = engine_identity
                file_observations[str(sources[branch])] = source_identity
                file_observations[str(engines[branch])] = engine_identity
                bindings[branch] = {
                    "schema_version": 1,
                    "artifact_kind": "vast_tensorrt_execution_worker_binding",
                    "worker_id": f"vast.{branch}.tensorrt",
                    "branch": branch,
                    "model_id": model["model_id"],
                    "source_path": f"/run/vast/models/{model['source_ref']}.onnx",
                    "source_model_sha256": hashlib.sha256(branch.encode()).hexdigest(),
                    "engine_path": f"/run/vast/models/{Path(str(model['engine_path'])).name}",
                    "model_artifact_sha256": model["engine_sha256"],
                    "input": {"name": "data", "dtype": "float32", "layout": "NCHW", "shape": [1, 3, 224, 224]},
                    "preprocessing_contract_sha256": "4" * 64,
                    "output_contract_sha256": "c" * 64,
                    "outputs": [{"name": "logits", "dtype": "float32", "shape": [1, 1000]}],
                    "worker_image_id": pilot.TENSORRT_IMAGE_ID,
                    "gpu_device_index": 0,
                    "gpu_uuid": pilot.TENSORRT_GPU_UUID,
                }
            return executor.BindingInventory(
                bindings=bindings,
                source_paths=sources,
                engine_paths=engines,
                source_identities=source_identities,
                engine_identities=engine_identities,
                manifest_identity_sha256="d" * 64,
                execution_config_identity_sha256="e" * 64,
            )

        def run_workers(**kwargs: object) -> list[dict[str, object]]:
            worker_calls.append(
                (
                    len(kwargs["bindings"].bindings),
                    len(kwargs["payloads"].payloads),
                    kwargs["peercred_diagnostic_only"],
                    kwargs["run_identity"],
                )
            )
            hidden = (
                kwargs["peer_identity_mode"]
                == executor.PEER_IDENTITY_MODE_DOCKER_DESKTOP_WSL2_PID0
            )
            selected_peer_identity = executor._select_peer_identity(
                    selected_mode=kwargs["peer_identity_mode"],
                    peer_raw=struct.pack(
                        "3i",
                        0 if hidden else 4321,
                        executor.CONTAINER_UID,
                        executor.CONTAINER_GID,
                    ),
                    docker_state_pid=4321,
                    runtime_daemon=kwargs["runtime_daemon"],
                    runtime_platform=kwargs["peercred_platform_observation"],
                    runtime_custody=self._peer_runtime_custody(
                        desktop_label=hidden
                    ),
                )
            peer_identity = executor._complete_peer_identity_after_handshake(
                selected_peer_identity
            )
            progress = kwargs["progress"]
            self.assertIsInstance(progress, executor._ExecutionProgressLedger)
            registry = kwargs["container_registry"]
            self.assertIsInstance(registry, executor._OwnedContainerRegistry)
            for ordinal, name in enumerate(registry.expected_names):
                registry.record(name, f"{ordinal + 1:064x}")
            peer_sha = hashlib.sha256(
                executor._canonical_json(selected_peer_identity)
            ).hexdigest()
            for branch in pilot.BRANCHES:
                progress.record_handshake(
                    branch=branch,
                    capability_sha256="f" * 64,
                    peer_identity_sha256=peer_sha,
                )
            progress.record_barrier_released()
            for request in requests:
                request_id = str(request["request_id"])
                request_ordinal = list(pilot.CODECS).index(request["codec"])
                response_sha = hashlib.sha256(
                    f"response:{request_id}".encode()
                ).hexdigest()
                output_sha = hashlib.sha256(
                    f"output:{request_id}".encode()
                ).hexdigest()
                progress.record_infer_dispatched(
                    branch=str(request["branch"]),
                    request_id=request_id,
                    request_ordinal=request_ordinal,
                    capability_sha256="f" * 64,
                    peer_identity_sha256=peer_sha,
                )
                progress.record_client_returned(
                    branch=str(request["branch"]),
                    request_id=request_id,
                    request_ordinal=request_ordinal,
                    response_is_dict=True,
                    output_is_bytes=True,
                    output_size_bytes=4000,
                )
                progress.record_infer_response(
                    branch=str(request["branch"]),
                    request_id=request_id,
                    request_ordinal=request_ordinal,
                    response_sha256=response_sha,
                    output_sha256=output_sha,
                    output_size_bytes=4000,
                    capability_sha256="f" * 64,
                    peer_identity_sha256=peer_sha,
                )
            return [
                {
                    "request_id": request["request_id"],
                    "branch": request["branch"],
                    "codec": request["codec"],
                    "response_sha256": hashlib.sha256(
                        f"response:{request['request_id']}".encode()
                    ).hexdigest(),
                    "output_sha256": hashlib.sha256(
                        f"output:{request['request_id']}".encode()
                    ).hexdigest(),
                    "output_size_bytes": 4000,
                    "worker_capability_sha256": "f" * 64,
                    "terminal_status": "completed",
                    "container_id_sha256": "1" * 64,
                    "container_preinspect_sha256": "2" * 64,
                    "container_running_inspect_sha256": "3" * 64,
                    "container_postinspect_sha256": "4" * 64,
                    "container_stdout_sha256": hashlib.sha256(b"").hexdigest(),
                    "container_stdout_size_bytes": 0,
                    "container_stderr_sha256": hashlib.sha256(b"").hexdigest(),
                    "container_stderr_size_bytes": 0,
                    "peer_identity": dict(peer_identity),
                }
                for request in requests
            ]

        def observe_platform(
            daemon: Mapping[str, object],
        ) -> dict[str, object]:
            platform_observer_calls.append(str(daemon["observation_sha256"]))
            return executor._build_peercred_pid0_platform_observation(
                b"6.6.87.2-microsoft-standard-WSL2\n",
                daemon,
            )

        dependencies = executor._ExecutorDependencies(
            platform_name="posix",
            environment={},
            observe_docker_cli=lambda: executor.FileIdentity(
                44_986_088,
                "fb7b1ca4b4c579d4a0dbecca8ab6ec9a1045a8bffb984f07347edf7593a3927d",
            ),
            command_runner=runner,
            planner_builder=lambda **_kwargs: plan,
            gpu_probe=lambda **_kwargs: {
                "device_id": pilot.TENSORRT_GPU_UUID,
                "worker_implementation_sha256": executor.TENSORRT_WORKER_IMPLEMENTATION_SHA256,
                "observation_sha256": "1" * 64,
            },
            observe_file=lambda path: file_observations[str(path)],
            binding_loader=load_bindings,
            tensor_reader=lambda **_kwargs: executor.TensorInventory(
                payloads=payloads,
                bundle_observations=list(
                    {
                        str(request["tensor"]["path"]): {
                            "path": request["tensor"]["path"],
                            "size_bytes": request["tensor"]["size_bytes"],
                            "sha256": request["tensor"]["sha256"],
                        }
                        for request in requests
                    }.values()
                ),
            ),
            worker_runner=run_workers,
            run_lock_factory=lambda _run_identity: executor._NullRunLease(),
            cleanup_mutex_factory=lambda _run_identity: executor._NullCleanupMutex(),
            progress_factory=executor._ExecutionProgressLedger,
            peercred_platform_observer=observe_platform,
        )

        docker29_error = (
            b"cannot decode []container.Summary: json: cannot unmarshal object "
            b"into Go value of type []container.Summary\n"
        )

        def fail_after_eight_in_cleanup(
            **kwargs: object,
        ) -> list[dict[str, object]]:
            prior_calls = len(worker_calls)
            run_workers(**kwargs)
            del worker_calls[prior_calls:]
            docker_error = executor._DockerOperationError(
                "local Docker container inventory failed",
                stage="cleanup_inventory_after_remove",
                command_class="container_inventory",
                capture=executor.CommandCapture(1, b"", docker29_error),
            )
            raise executor._ExecutionFailureBundle(
                primary=docker_error,
                primary_phase="final_cleanup",
                primary_stage="cleanup_inventory_after_remove",
                primary_branch="damage",
                supplemental_failures=[],
            )

        def persist_synthetic_failure(
            run_root_target: object,
            artifact: Mapping[str, object],
        ) -> dict[str, object]:
            run_root = (
                run_root_target.path
                if isinstance(run_root_target, executor._RunRootCustody)
                else Path(run_root_target)
            )
            payload = executor.canonical_line(dict(artifact))
            destination = (
                run_root / executor.EXECUTION_FAILURE_DIAGNOSTIC_NAME
            )
            with destination.open("xb") as stream:
                self.assertEqual(stream.write(payload), len(payload))
                stream.flush()
                os.fsync(stream.fileno())
            return {
                "size_bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }

        cleanup_failure_dependencies = replace(
            dependencies,
            command_runner=ScriptedRunner(image_present=True),
            worker_runner=fail_after_eight_in_cleanup,
            failure_diagnostic_writer=(
                executor._persist_execution_failure_diagnostic
                if os.name == "posix"
                else persist_synthetic_failure
            ),
        )
        cleanup_stdout = io.BytesIO()
        with tempfile.TemporaryDirectory() as cleanup_raw:
            cleanup_status = executor.main(
                [
                    "--project-root", cleanup_raw,
                    "--decision-path", "configs/synthetic.json",
                    "--candidate-root", "staging/synthetic",
                    "--role", "secondary",
                    "--expected-receipt-file-sha256", "7" * 64,
                    "--expected-receipt-self-sha256", "8" * 64,
                    "--run-id", "synthetic-after8-cleanup-failure",
                    "--expected-docker-cli-size-bytes", "44986088",
                    "--expected-docker-cli-sha256", (
                        "fb7b1ca4b4c579d4a0dbecca8ab6ec9a1045a8bffb984f07347edf7593a3927d"
                    ),
                    "--expected-daemon-id", "1e493309-3767-45fb-9078-05b838bdfd80",
                    "--expected-daemon-server-version", "29.5.3",
                    "--expected-daemon-api-version", "1.54",
                ],
                _dependencies=cleanup_failure_dependencies,
                _stdout=cleanup_stdout,
            )
            cleanup_artifact = json.loads(cleanup_stdout.getvalue())
            cleanup_run_root = (
                Path(cleanup_raw)
                / "runs"
                / "nonpublication"
                / "synthetic-after8-cleanup-failure"
            )
            failure_leaf = (
                cleanup_run_root
                / executor.EXECUTION_FAILURE_DIAGNOSTIC_NAME
            )
            self.assertEqual(
                failure_leaf.read_bytes(),
                cleanup_stdout.getvalue(),
                (
                    cleanup_artifact.get("failure"),
                    cleanup_artifact.get("supplemental_failures"),
                    cleanup_artifact.get("diagnostic_persistence"),
                ),
            )
            self.assertFalse(
                (cleanup_run_root / executor.ASSESSMENT_NAME).exists()
            )
        self.assertEqual(cleanup_status, 78)
        self.assertEqual(
            cleanup_stdout.getvalue(),
            executor.canonical_line(cleanup_artifact),
        )
        cleanup_failure = cleanup_artifact["failure"]
        self.assertEqual(cleanup_failure["phase"], "final_cleanup")
        self.assertEqual(
            cleanup_failure["stage"], "cleanup_inventory_after_remove"
        )
        self.assertEqual(cleanup_failure["branch"], "damage")
        self.assertEqual(
            cleanup_failure["code"], "docker_command_contract_error"
        )
        command_facts = cleanup_failure["docker_command"]
        self.assertEqual(command_facts["command_class"], "container_inventory")
        self.assertEqual(command_facts["returncode"], 1)
        self.assertEqual(command_facts["stdout"]["size_bytes"], 0)
        self.assertEqual(
            command_facts["stderr"],
            {
                "size_bytes": len(docker29_error),
                "sha256": hashlib.sha256(docker29_error).hexdigest(),
                "safe_bounded_text": docker29_error.decode("ascii"),
            },
        )
        self.assertEqual(
            cleanup_artifact["progress"]["validated_checkpoint_count"], 8
        )
        self.assertIs(cleanup_artifact["inference_performed"], True)
        self.assertIs(cleanup_artifact["inference_performed_attested"], True)
        self.assertIs(cleanup_artifact["all_inferences_completed"], True)
        runtime_cleanup = cleanup_artifact["runtime_cleanup"]
        self.assertIs(runtime_cleanup["attempted"], True)
        self.assertIs(
            runtime_cleanup["docker_observation_available"], True
        )
        self.assertIs(
            runtime_cleanup["unresolved_operation_observation_available"],
            False,
        )
        self.assertIs(runtime_cleanup["complete_attestation"], False)
        self.assertIs(
            runtime_cleanup["docker"]["registry_coverage_complete"],
            False,
        )
        self.assertEqual(
            runtime_cleanup["docker"]["recorded_container_count"], 0
        )
        self.assertEqual(
            len(runtime_cleanup["docker"]["absence_inspects"]), 5
        )
        self.assertIs(
            runtime_cleanup["docker"]["final_catalog"][
                "exact_empty_observed"
            ],
            True,
        )
        self.assertIsNone(runtime_cleanup["unresolved_operations"])
        self.assertEqual(
            cleanup_artifact["diagnostic_persistence"]["state"],
            "self_commit_unattested",
        )
        self.assertIs(
            cleanup_artifact["diagnostic_persistence"]["commit_attested"],
            False,
        )
        self.assertEqual(
            cleanup_artifact["threat_model_boundary"],
            {
                "concurrent_project_tree_writer_excluded": True,
                "concurrent_same_uid_project_tree_writer_excluded": True,
                "concurrent_other_uid_wsl_project_tree_writer_excluded": True,
                "concurrent_windows_side_project_writer_excluded": True,
                "concurrent_same_uid_runtime_state_writer_excluded": True,
                "filesystem_acl_attested": False,
            },
        )
        self.assertNotEqual(
            cleanup_artifact["claim_status"],
            "blocked_nonpublication_preflight_not_execution",
        )

        lease_release_calls: list[str] = []

        class FailingLease:
            contract: Mapping[str, object] = {"synthetic_test_only": True}

            def release(self) -> None:
                lease_release_calls.append("release")
                raise executor.ExecutorContractError(
                    "synthetic post-assessment lease release failed"
                )

        def lease_workers(**kwargs: object) -> list[dict[str, object]]:
            prior_calls = len(worker_calls)
            try:
                return run_workers(**kwargs)
            finally:
                del worker_calls[prior_calls:]

        lease_failure_dependencies = replace(
            dependencies,
            command_runner=ScriptedRunner(image_present=True),
            worker_runner=lease_workers,
            run_lock_factory=lambda _run_identity: FailingLease(),
            failure_diagnostic_writer=(
                executor._persist_execution_failure_diagnostic
                if os.name == "posix"
                else persist_synthetic_failure
            ),
        )
        lease_stdout = io.BytesIO()
        with tempfile.TemporaryDirectory() as lease_raw:
            lease_status = executor.main(
                [
                    "--project-root", lease_raw,
                    "--decision-path", "configs/synthetic.json",
                    "--candidate-root", "staging/synthetic",
                    "--role", "secondary",
                    "--expected-receipt-file-sha256", "7" * 64,
                    "--expected-receipt-self-sha256", "8" * 64,
                    "--run-id", "synthetic-post-assessment-lease-failure",
                    "--expected-docker-cli-size-bytes", "44986088",
                    "--expected-docker-cli-sha256", (
                        "fb7b1ca4b4c579d4a0dbecca8ab6ec9a1045a8bffb984f07347edf7593a3927d"
                    ),
                    "--expected-daemon-id", "1e493309-3767-45fb-9078-05b838bdfd80",
                    "--expected-daemon-server-version", "29.5.3",
                    "--expected-daemon-api-version", "1.54",
                ],
                _dependencies=lease_failure_dependencies,
                _stdout=lease_stdout,
            )
            lease_artifact = json.loads(lease_stdout.getvalue())
            lease_run_root = (
                Path(lease_raw)
                / "runs"
                / "nonpublication"
                / "synthetic-post-assessment-lease-failure"
            )
            self.assertTrue(
                (lease_run_root / executor.ASSESSMENT_NAME).is_file()
            )
            self.assertEqual(
                (
                    lease_run_root
                    / executor.EXECUTION_FAILURE_DIAGNOSTIC_NAME
                ).read_bytes(),
                lease_stdout.getvalue(),
            )
        self.assertEqual(lease_status, 78)
        self.assertEqual(lease_release_calls, ["release"])
        self.assertEqual(
            lease_artifact["failure"]["stage"],
            "run_lease_release",
        )
        self.assertEqual(
            lease_artifact["assessment_persistence"],
            {
                "attempted": True,
                "write_returned": True,
                "commit_attested": False,
                "state": "write_returned_commit_unattested",
            },
        )
        self.assertEqual(
            lease_artifact["diagnostic_persistence"]["state"],
            "self_commit_unattested",
        )
        self.assertIs(lease_artifact["inference_performed"], True)
        self.assertEqual(
            lease_artifact["progress"]["validated_checkpoint_count"],
            8,
        )

        mutex_close_calls: list[str] = []

        faulty_mutex = executor._NullCleanupMutex()

        def fail_second_mutex_close() -> None:
            mutex_close_calls.append("close")
            if len(mutex_close_calls) == 2:
                raise executor.ExecutorContractError(
                    "synthetic outer cleanup mutex close failed"
                )

        faulty_mutex.close = fail_second_mutex_close  # type: ignore[method-assign]

        mutex_failure_dependencies = replace(
            dependencies,
            command_runner=ScriptedRunner(image_present=True),
            worker_runner=lease_workers,
            cleanup_mutex_factory=lambda _run_identity: faulty_mutex,
            failure_diagnostic_writer=(
                executor._persist_execution_failure_diagnostic
                if os.name == "posix"
                else persist_synthetic_failure
            ),
        )
        mutex_stdout = io.BytesIO()
        with tempfile.TemporaryDirectory() as mutex_raw:
            mutex_status = executor.main(
                [
                    "--project-root", mutex_raw,
                    "--decision-path", "configs/synthetic.json",
                    "--candidate-root", "staging/synthetic",
                    "--role", "secondary",
                    "--expected-receipt-file-sha256", "7" * 64,
                    "--expected-receipt-self-sha256", "8" * 64,
                    "--run-id", "synthetic-post-assessment-mutex-failure",
                    "--expected-docker-cli-size-bytes", "44986088",
                    "--expected-docker-cli-sha256", (
                        "fb7b1ca4b4c579d4a0dbecca8ab6ec9a1045a8bffb984f07347edf7593a3927d"
                    ),
                    "--expected-daemon-id", "1e493309-3767-45fb-9078-05b838bdfd80",
                    "--expected-daemon-server-version", "29.5.3",
                    "--expected-daemon-api-version", "1.54",
                ],
                _dependencies=mutex_failure_dependencies,
                _stdout=mutex_stdout,
            )
            mutex_artifact = json.loads(mutex_stdout.getvalue())
            mutex_run_root = (
                Path(mutex_raw)
                / "runs"
                / "nonpublication"
                / "synthetic-post-assessment-mutex-failure"
            )
            self.assertTrue(
                (mutex_run_root / executor.ASSESSMENT_NAME).is_file(),
                (
                    mutex_artifact.get("failure"),
                    mutex_artifact.get("supplemental_failures"),
                    mutex_artifact.get("assessment_persistence"),
                ),
            )
            self.assertEqual(
                (
                    mutex_run_root
                    / executor.EXECUTION_FAILURE_DIAGNOSTIC_NAME
                ).read_bytes(),
                mutex_stdout.getvalue(),
            )
        self.assertEqual(mutex_status, 78)
        self.assertEqual(mutex_close_calls, ["close", "close"])
        self.assertEqual(
            mutex_artifact["failure"]["stage"],
            "cleanup_mutex_close",
        )
        self.assertEqual(
            mutex_artifact["diagnostic_persistence"]["state"],
            "self_commit_unattested",
        )
        self.assertIs(mutex_artifact["inference_performed"], True)
        self.assertEqual(
            mutex_artifact["progress"]["validated_checkpoint_count"],
            8,
        )

        progress_close_calls: list[str] = []

        def failing_progress_factory(
            **kwargs: object,
        ) -> executor._ExecutionProgressLedger:
            ledger = executor._ExecutionProgressLedger(**kwargs)

            def fail_close() -> None:
                progress_close_calls.append("close")
                raise executor.ExecutorContractError(
                    "synthetic progress final fsync failed"
                )

            ledger.close = fail_close  # type: ignore[method-assign]
            return ledger

        def workers_without_count(
            **kwargs: object,
        ) -> list[dict[str, object]]:
            prior_calls = len(worker_calls)
            try:
                return run_workers(**kwargs)
            finally:
                del worker_calls[prior_calls:]

        progress_failure_dependencies = replace(
            dependencies,
            command_runner=ScriptedRunner(image_present=True),
            worker_runner=workers_without_count,
            progress_factory=failing_progress_factory,
            failure_diagnostic_writer=(
                executor._persist_execution_failure_diagnostic
                if os.name == "posix"
                else persist_synthetic_failure
            ),
        )
        progress_stdout = io.BytesIO()
        with tempfile.TemporaryDirectory() as progress_raw:
            progress_status = executor.main(
                [
                    "--project-root", progress_raw,
                    "--decision-path", "configs/synthetic.json",
                    "--candidate-root", "staging/synthetic",
                    "--role", "secondary",
                    "--expected-receipt-file-sha256", "7" * 64,
                    "--expected-receipt-self-sha256", "8" * 64,
                    "--run-id", "synthetic-progress-close-failure",
                    "--expected-docker-cli-size-bytes", "44986088",
                    "--expected-docker-cli-sha256", (
                        "fb7b1ca4b4c579d4a0dbecca8ab6ec9a1045a8bffb984f07347edf7593a3927d"
                    ),
                    "--expected-daemon-id", "1e493309-3767-45fb-9078-05b838bdfd80",
                    "--expected-daemon-server-version", "29.5.3",
                    "--expected-daemon-api-version", "1.54",
                ],
                _dependencies=progress_failure_dependencies,
                _stdout=progress_stdout,
            )
            progress_artifact = json.loads(progress_stdout.getvalue())
        self.assertEqual(progress_status, 78)
        self.assertEqual(progress_close_calls, ["close"])
        self.assertEqual(
            progress_artifact["failure"]["stage"], "progress_finalization"
        )
        self.assertEqual(
            progress_artifact["progress"]["validated_checkpoint_count"], 8
        )
        self.assertIs(progress_artifact["inference_performed"], True)
        self.assertIs(
            progress_artifact["progress"]["persistence"][
                "integrity_attested"
            ],
            False,
        )
        self.assertRegex(
            progress_artifact["progress"]["persistence"][
                "closure_error_sha256"
            ],
            r"^[0-9a-f]{64}$",
        )
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            artifact, status = executor.execute_nonpublication_pilot(
                project_root=root,
                decision_path="configs/synthetic.json",
                candidate_root="staging/synthetic",
                role="secondary",
                expected_receipt_file_sha256="7" * 64,
                expected_receipt_self_sha256="8" * 64,
                run_id="synthetic-eight-request-run",
                expected_docker_cli_size_bytes=44_986_088,
                expected_docker_cli_sha256="fb7b1ca4b4c579d4a0dbecca8ab6ec9a1045a8bffb984f07347edf7593a3927d",
                expected_daemon_id="1e493309-3767-45fb-9078-05b838bdfd80",
                expected_daemon_server_version="29.5.3",
                expected_daemon_api_version="1.54",
                _dependencies=dependencies,
            )
            run_root = root / "runs" / "nonpublication" / "synthetic-eight-request-run"
            files = sorted(
                path.relative_to(run_root).as_posix()
                for path in run_root.rglob("*")
                if path.is_file()
            )
            persisted = (run_root / executor.ASSESSMENT_NAME).read_bytes()
        self.assertEqual(platform_observer_calls, [])

        with tempfile.TemporaryDirectory() as hidden_raw:
            hidden_artifact, hidden_status = executor.execute_nonpublication_pilot(
                project_root=Path(hidden_raw),
                decision_path="configs/synthetic.json",
                candidate_root="staging/synthetic",
                role="secondary",
                expected_receipt_file_sha256="7" * 64,
                expected_receipt_self_sha256="8" * 64,
                run_id="synthetic-eight-request-hidden-run",
                expected_docker_cli_size_bytes=44_986_088,
                expected_docker_cli_sha256="fb7b1ca4b4c579d4a0dbecca8ab6ec9a1045a8bffb984f07347edf7593a3927d",
                expected_daemon_id="1e493309-3767-45fb-9078-05b838bdfd80",
                expected_daemon_server_version="29.5.3",
                expected_daemon_api_version="1.54",
                peer_identity_mode=(
                    executor.PEER_IDENTITY_MODE_DOCKER_DESKTOP_WSL2_PID0
                ),
                _dependencies=dependencies,
            )

        drift_observer_calls: list[dict[str, object]] = []

        def observe_platform_with_commit_drift(
            daemon: Mapping[str, object],
        ) -> dict[str, object]:
            observed = executor._build_peercred_pid0_platform_observation(
                b"6.6.87.2-microsoft-standard-WSL2\n",
                daemon,
            )
            drift_observer_calls.append(observed)
            if len(drift_observer_calls) == 2:
                return {**observed, "observation_sha256": "0" * 64}
            return observed

        drift_dependencies = replace(
            dependencies,
            peercred_platform_observer=observe_platform_with_commit_drift,
        )
        with tempfile.TemporaryDirectory() as drift_raw:
            drift_root = Path(drift_raw)
            drift_artifact, drift_status = executor.execute_nonpublication_pilot(
                project_root=drift_root,
                decision_path="configs/synthetic.json",
                candidate_root="staging/synthetic",
                role="secondary",
                expected_receipt_file_sha256="7" * 64,
                expected_receipt_self_sha256="8" * 64,
                run_id="synthetic-eight-request-hidden-commit-drift",
                expected_docker_cli_size_bytes=44_986_088,
                expected_docker_cli_sha256="fb7b1ca4b4c579d4a0dbecca8ab6ec9a1045a8bffb984f07347edf7593a3927d",
                expected_daemon_id="1e493309-3767-45fb-9078-05b838bdfd80",
                expected_daemon_server_version="29.5.3",
                expected_daemon_api_version="1.54",
                peer_identity_mode=(
                    executor.PEER_IDENTITY_MODE_DOCKER_DESKTOP_WSL2_PID0
                ),
                _dependencies=drift_dependencies,
            )
            self.assertEqual(drift_status, 78)
            self.assertEqual(
                drift_artifact["failure"]["stage"], "platform_revalidation"
            )
            self.assertIs(drift_artifact["inference_performed"], True)
            self.assertEqual(
                drift_artifact["progress"]["validated_checkpoint_count"], 8
            )
            drift_run_root = (
                drift_root
                / "runs"
                / "nonpublication"
                / "synthetic-eight-request-hidden-commit-drift"
            )
            self.assertTrue(drift_run_root.is_dir())
            self.assertFalse(
                (drift_run_root / executor.ASSESSMENT_NAME).exists()
            )
        self.assertEqual(len(drift_observer_calls), 2)

        test_case = self

        class CommitDaemonDriftRunner(ScriptedRunner):
            def __post_init__(runner_self) -> None:
                super().__post_init__()
                runner_self.info_count = 0

            def run(
                runner_self,
                argv: list[str],
                *,
                timeout_seconds: float,
                stdout_limit: int,
                stderr_limit: int,
            ) -> executor.CommandCapture:
                command = tuple(argv)
                if "info" in command:
                    runner_self.info_count += 1
                    if runner_self.info_count == 2:
                        runner_self.calls.append(command)
                        info = test_case._daemon_info_document(
                            test_case._peercred_daemon(
                                daemon_id=(
                                    "1e493309-3767-45fb-9078-05b838bdfd80"
                                ),
                                server_version="29.5.3",
                                api_version="1.54",
                            )
                        )
                        info["DefaultRuntime"] = "crun"
                        return executor.CommandCapture(
                            0,
                            executor.canonical_line(info),
                            b"",
                        )
                return super().run(
                    argv,
                    timeout_seconds=timeout_seconds,
                    stdout_limit=stdout_limit,
                    stderr_limit=stderr_limit,
                )

        daemon_drift_platform_calls: list[str] = []

        def observe_platform_before_daemon_drift(
            daemon: Mapping[str, object],
        ) -> dict[str, object]:
            daemon_drift_platform_calls.append(str(daemon["observation_sha256"]))
            return executor._build_peercred_pid0_platform_observation(
                b"6.6.87.2-microsoft-standard-WSL2\n",
                daemon,
            )

        daemon_drift_dependencies = replace(
            dependencies,
            command_runner=CommitDaemonDriftRunner(image_present=True),
            peercred_platform_observer=observe_platform_before_daemon_drift,
        )
        with tempfile.TemporaryDirectory() as daemon_drift_raw:
            daemon_drift_root = Path(daemon_drift_raw)
            daemon_drift_artifact, daemon_drift_status = (
                executor.execute_nonpublication_pilot(
                    project_root=daemon_drift_root,
                    decision_path="configs/synthetic.json",
                    candidate_root="staging/synthetic",
                    role="secondary",
                    expected_receipt_file_sha256="7" * 64,
                    expected_receipt_self_sha256="8" * 64,
                    run_id="synthetic-eight-request-hidden-daemon-drift",
                    expected_docker_cli_size_bytes=44_986_088,
                    expected_docker_cli_sha256="fb7b1ca4b4c579d4a0dbecca8ab6ec9a1045a8bffb984f07347edf7593a3927d",
                    expected_daemon_id="1e493309-3767-45fb-9078-05b838bdfd80",
                    expected_daemon_server_version="29.5.3",
                    expected_daemon_api_version="1.54",
                    peer_identity_mode=(
                        executor.PEER_IDENTITY_MODE_DOCKER_DESKTOP_WSL2_PID0
                    ),
                    _dependencies=daemon_drift_dependencies,
                )
            )
            self.assertEqual(daemon_drift_status, 78)
            self.assertEqual(
                daemon_drift_artifact["failure"]["stage"],
                "daemon_revalidation",
            )
            self.assertIs(
                daemon_drift_artifact["inference_performed"], True
            )
            self.assertEqual(
                daemon_drift_artifact["progress"][
                    "validated_checkpoint_count"
                ],
                8,
            )
            daemon_drift_run_root = (
                daemon_drift_root
                / "runs"
                / "nonpublication"
                / "synthetic-eight-request-hidden-daemon-drift"
            )
            self.assertTrue(daemon_drift_run_root.is_dir())
            self.assertFalse(
                (daemon_drift_run_root / executor.ASSESSMENT_NAME).exists()
            )
        self.assertEqual(len(daemon_drift_platform_calls), 1)

        with tempfile.TemporaryDirectory() as diagnostic_raw:
            with self.assertRaisesRegex(
                executor.ExecutorContractError,
                "diagnostic-only worker unexpectedly returned observations",
            ):
                executor.execute_nonpublication_pilot(
                    project_root=Path(diagnostic_raw),
                    decision_path="configs/synthetic.json",
                    candidate_root="staging/synthetic",
                    role="secondary",
                    expected_receipt_file_sha256="7" * 64,
                    expected_receipt_self_sha256="8" * 64,
                    run_id="kpp-v2-secondary-peercred-diagnostic-20260822-v1",
                    expected_docker_cli_size_bytes=44_986_088,
                    expected_docker_cli_sha256="fb7b1ca4b4c579d4a0dbecca8ab6ec9a1045a8bffb984f07347edf7593a3927d",
                    expected_daemon_id="1e493309-3767-45fb-9078-05b838bdfd80",
                    expected_daemon_server_version="29.5.3",
                    expected_daemon_api_version="1.54",
                    diagnostic_so_peercred_only=True,
                    _dependencies=dependencies,
                )
            diagnostic_run_root = (
                Path(diagnostic_raw)
                / "runs"
                / "nonpublication"
                / "kpp-v2-secondary-peercred-diagnostic-20260822-v1"
            )
            self.assertTrue(diagnostic_run_root.is_dir())
            self.assertFalse(
                (diagnostic_run_root / executor.ASSESSMENT_NAME).exists()
            )

        diagnostic_stdout = io.BytesIO()
        with tempfile.TemporaryDirectory() as diagnostic_cli_raw:
            diagnostic_status = executor.main(
                [
                    "--project-root", diagnostic_cli_raw,
                    "--decision-path", "configs/synthetic.json",
                    "--candidate-root", "staging/synthetic",
                    "--role", "secondary",
                    "--expected-receipt-file-sha256", "7" * 64,
                    "--expected-receipt-self-sha256", "8" * 64,
                    "--run-id", "kpp-v2-secondary-peercred-diagnostic-20260822-v1",
                    "--expected-docker-cli-size-bytes", "44986088",
                    "--expected-docker-cli-sha256", "fb7b1ca4b4c579d4a0dbecca8ab6ec9a1045a8bffb984f07347edf7593a3927d",
                    "--expected-daemon-id", "1e493309-3767-45fb-9078-05b838bdfd80",
                    "--expected-daemon-server-version", "29.5.3",
                    "--expected-daemon-api-version", "1.54",
                    "--diagnostic-so-peercred-only",
                ],
                _dependencies=dependencies,
                _stdout=diagnostic_stdout,
            )
        diagnostic_artifact = json.loads(diagnostic_stdout.getvalue())
        self.assertEqual(diagnostic_status, 78)
        self.assertEqual(
            diagnostic_stdout.getvalue(),
            executor.canonical_line(diagnostic_artifact),
        )
        self.assertEqual(
            diagnostic_artifact["status"],
            "blocked_executor_contract_error",
        )
        self.assertEqual(
            diagnostic_artifact["claim_status"],
            "diagnostic_only_blocked_nonpublication_not_evidence",
        )
        self.assertEqual(
            diagnostic_artifact["runtime_preflight"],
            {
                "diagnostic_so_peercred_only": True,
                "capability_handshake_performed": False,
                "peer_credentials_accepted_for_inference": False,
                "inference_performed": False,
            },
        )
        self.assertIs(diagnostic_artifact["inference_performed"], False)
        for field in executor.FALSE_CLAIM_FIELDS:
            self.assertIs(diagnostic_artifact[field], False)

        self.assertEqual(status, 0, artifact)
        self.assertEqual(artifact["status"], "completed_nonpublication_pilot")
        self.assertEqual(artifact["request_count"], 8)
        self.assertEqual(
            artifact["threat_model_boundary"],
            {
                "concurrent_project_tree_writer_excluded": True,
                "concurrent_same_uid_socket_connector_excluded": True,
                "concurrent_same_uid_project_tree_writer_excluded": True,
                "concurrent_other_uid_wsl_project_tree_writer_excluded": True,
                "concurrent_windows_side_project_writer_excluded": True,
                "concurrent_same_uid_runtime_state_writer_excluded": True,
                "filesystem_acl_attested": False,
                "peer_identity_by_pid_unavailable_is_not_represented_as_attested": True,
            },
        )
        native_claims = artifact["peer_identity_claims"]
        self.assertEqual(
            native_claims["peer_identity_mode"],
            executor.PEER_IDENTITY_MODE_NATIVE_VISIBLE,
        )
        self.assertIs(native_claims["peer_uid_gid_exact"], True)
        self.assertIs(native_claims["container_state_pid_positive"], True)
        self.assertIs(native_claims["peer_pid_visible_in_controller_namespace"], True)
        self.assertIs(native_claims["peer_pid_state_pid_equality_attested"], True)
        self.assertIs(native_claims["peer_identity_by_pid_attested"], True)
        self.assertIs(native_claims["socket_to_container_pid_binding_attested"], True)
        self.assertIsNone(native_claims["platform_observation_sha256"])
        invocation_action_claims = {
            key: value
            for key, value in artifact["runtime_preflight"].items()
            if key.endswith("_performed_during_executor_invocation")
        }
        self.assertEqual(
            invocation_action_claims,
            {
                "network_or_pull_performed_during_executor_invocation": False,
                "docker_build_performed_during_executor_invocation": False,
                "offline_image_load_performed_during_executor_invocation": False,
            },
        )
        self.assertFalse(
            {
                "network_or_pull_performed",
                "docker_build_performed",
                "offline_image_load_performed",
            }
            & set(artifact["runtime_preflight"])
        )
        self.assertEqual(hidden_status, 0)
        hidden_claims = hidden_artifact["peer_identity_claims"]
        self.assertEqual(
            hidden_claims["peer_identity_mode"],
            executor.PEER_IDENTITY_MODE_DOCKER_DESKTOP_WSL2_PID0,
        )
        self.assertIs(hidden_claims["peer_uid_gid_exact"], True)
        self.assertIs(hidden_claims["container_state_pid_positive"], True)
        self.assertIs(hidden_claims["peer_pid_visible_in_controller_namespace"], False)
        self.assertIs(hidden_claims["peer_pid_state_pid_equality_attested"], False)
        self.assertIs(hidden_claims["peer_identity_by_pid_attested"], False)
        self.assertIs(hidden_claims["socket_to_container_pid_binding_attested"], False)
        self.assertIs(hidden_claims["protocol_nonce_capability_handshake_performed"], True)
        self.assertIs(
            hidden_claims["global_four_worker_handshake_before_inference_attested"],
            True,
        )
        self.assertEqual(
            hidden_claims["platform_observation_sha256"],
            hidden_artifact["runtime_preflight"][
                "peercred_pid0_platform_observation"
            ]["observation_sha256"],
        )
        self.assertEqual(len(platform_observer_calls), 2)
        self.assertEqual(platform_observer_calls[0], platform_observer_calls[1])
        for field in executor.FALSE_CLAIM_FIELDS:
            self.assertIs(hidden_artifact[field], False)

        self.assertEqual(len(worker_calls), 6)
        self.assertEqual(worker_calls[0][:3], (4, 8, False))
        self.assertEqual(worker_calls[1][:3], (4, 8, False))
        self.assertEqual(worker_calls[2][:3], (4, 8, False))
        self.assertEqual(worker_calls[3][:3], (4, 8, False))
        self.assertEqual(worker_calls[4][:3], (4, 8, True))
        self.assertEqual(worker_calls[5][:3], (4, 8, True))
        self.assertNotEqual(worker_calls[0][3], worker_calls[1][3])
        self.assertNotEqual(worker_calls[0][3], worker_calls[2][3])
        self.assertNotEqual(worker_calls[1][3], worker_calls[2][3])
        self.assertNotEqual(worker_calls[2][3], worker_calls[3][3])
        self.assertEqual(worker_calls[4][3], worker_calls[5][3])
        self.assertEqual(persisted, executor.canonical_line(artifact))
        progress_files = (
            [f"runtime_progress/{index:04d}.json" for index in range(1, 30)]
            if os.name == "posix"
            else []
        )
        self.assertEqual(
            files,
            sorted([
                executor.ASSESSMENT_NAME,
                *[
                    f"bindings/{branch}.tensorrt_cuda.json"
                    for branch in pilot.BRANCHES
                ],
                *progress_files,
            ]),
        )
        self.assertEqual(
            artifact["execution_progress"]["persistence"]["mode"],
            (
                "durable_o_excl_fsync"
                if os.name == "posix"
                else "synthetic_in_memory"
            ),
        )
        self.assertFalse(any("evidence" in item or "receipt" in item for item in files))
        for field in executor.FALSE_CLAIM_FIELDS:
            self.assertIs(artifact[field], False)


if __name__ == "__main__":
    unittest.main()
