from __future__ import annotations

import copy
import hashlib
import json
import os
import socket
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import checkpoint_gstreamer_analytics_sidecar as authority  # noqa: E402
from checkpoint_gstreamer_analytics_sidecar import SidecarError  # noqa: E402


OSRELEASE_RAW = b"6.6.87.2-microsoft-standard-WSL2\n"
DOCKER_INFO = {
    "Name": "docker-desktop",
    "OperatingSystem": "Docker Desktop",
    "KernelVersion": "6.6.87.2-microsoft-standard-WSL2",
    "ServerVersion": "29.7.2",
    "OSType": "linux",
    "Driver": "overlayfs",
    "DriverStatus": [["driver-type", "io.containerd.snapshotter.v1"]],
    "DefaultRuntime": "runc",
    "ContainerdCommit": {
        "ID": "e53c7c1516c3b2bff98eb76f1f4117477e6f4e66"
    },
    "Runtimes": {
        "io.containerd.runc.v2": {"path": "runc"},
        "runc": {"path": "runc"},
        "nvidia": {"path": "nvidia-container-runtime"},
    },
}


@unittest.skipUnless(
    os.name == "posix" and hasattr(socket, "SO_PEERCRED"),
    "Linux SO_PEERCRED is required",
)
class AnalyticsPeerIdentityAuthorityTests(unittest.TestCase):
    def _current_platform(self) -> dict[str, object]:
        info = copy.deepcopy(DOCKER_INFO)
        info["ContainerdCommit"]["ID"] = "aad11006b869517fcd3009450b6f82da282e1a9b"
        return authority._build_peercred_pid0_platform_observation(OSRELEASE_RAW, info)

    def test_observed_containerd_profile_preserves_actual_commit_and_roundtrips(self) -> None:
        observed = self._current_platform()
        self.assertEqual(observed["docker_info"]["containerd_commit"], {
            "ID": "aad11006b869517fcd3009450b6f82da282e1a9b",
        })
        self.assertNotEqual(observed["observation_sha256"], self._platform()["observation_sha256"])
        self.assertEqual(authority._validate_peercred_pid0_platform_observation(observed), observed)

    def test_observed_containerd_profile_rejects_unknown_commit_and_platform_drift(self) -> None:
        for field, replacement in (
            ("ContainerdCommit", {"ID": "f" * 40}),
            ("ContainerdCommit", {"ID": ["aad11006b869517fcd3009450b6f82da282e1a9b"]}),
            ("ServerVersion", "29.7.3"),
            ("KernelVersion", "6.6.88.1-microsoft-standard-WSL2"),
            ("Driver", "overlay2"),
            ("DefaultRuntime", "crun"),
            ("Runtimes", {"runc": {}}),
        ):
            info = copy.deepcopy(DOCKER_INFO)
            info["ContainerdCommit"]["ID"] = "aad11006b869517fcd3009450b6f82da282e1a9b"
            info[field] = replacement
            with self.subTest(field=field, replacement=replacement), self.assertRaises(SidecarError):
                authority._build_peercred_pid0_platform_observation(OSRELEASE_RAW, info)

    def test_observed_containerd_profile_rejects_rehashed_platform_tampering(self) -> None:
        for field, replacement in (
            ("containerd_commit", {"ID": "f" * 40}),
            ("containerd_commit", {"ID": "aad11006b869517fcd3009450b6f82da282e1a9b", "extra": True}),
            ("server_version", "29.7.3"),
            ("kernel_version", "6.6.88.1-microsoft-standard-WSL2"),
            ("default_runtime", "crun"),
        ):
            observed = self._current_platform()
            observed["docker_info"][field] = replacement
            observed["docker_info_sha256"] = authority.canonical_sha256(observed["docker_info"])
            core = {key: value for key, value in observed.items() if key != "observation_sha256"}
            observed["observation_sha256"] = hashlib.sha256(
                authority.PEERCRED_PLATFORM_DOMAIN + authority.canonical_json_bytes(core) + b"\n"
            ).hexdigest()
            with self.subTest(field=field), self.assertRaises(SidecarError):
                authority._validate_peercred_pid0_platform_observation(observed)

    def test_observed_containerd_profile_cannot_replace_old_profile_without_rehash(self) -> None:
        current = self._current_platform()
        old = self._platform()
        for source, target in ((current, old), (old, current)):
            tampered = copy.deepcopy(target)
            tampered["docker_info"]["containerd_commit"] = source["docker_info"]["containerd_commit"]
            with self.assertRaises(SidecarError):
                authority._validate_peercred_pid0_platform_observation(tampered)

    def _platform(self) -> dict[str, object]:
        return authority._build_peercred_pid0_platform_observation(
            OSRELEASE_RAW,
            DOCKER_INFO,
        )

    def _private_socket(self) -> tuple[Path, Path, socket.socket]:
        directory = Path(
            tempfile.mkdtemp(
                prefix=f"vast-peer-identity-{os.getpid()}-{time.monotonic_ns()}-",
                dir="/var/tmp",
            )
        )
        directory.chmod(0o700)
        path = directory / "worker.sock"
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        listener.bind(str(path))
        listener.listen(1)
        return directory, path, listener

    def test_actual_platform_fixture_has_exact_raw_bytes_and_compact_hashes(self) -> None:
        observed = self._platform()

        self.assertEqual(
            observed["wsl_osrelease"],
            {
                "path": "/proc/sys/kernel/osrelease",
                "raw_ascii": "6.6.87.2-microsoft-standard-WSL2\n",
                "size_bytes": 33,
                "sha256": "ccd199c039f7944eb5289351597af34c9388338a60b6531c0d2fe55e8425019a",
                "marker": "-microsoft-standard-WSL2",
                "marker_present": True,
            },
        )
        self.assertEqual(
            observed["docker_info"],
            {
                "name": "docker-desktop",
                "operating_system": "Docker Desktop",
                "kernel_version": "6.6.87.2-microsoft-standard-WSL2",
                "server_version": "29.7.2",
                "os_type": "linux",
                "driver": "overlayfs",
                "driver_status": [
                    ["driver-type", "io.containerd.snapshotter.v1"]
                ],
                "default_runtime": "runc",
                "containerd_commit": {
                    "ID": "e53c7c1516c3b2bff98eb76f1f4117477e6f4e66"
                },
                "required_runtimes": [
                    "io.containerd.runc.v2",
                    "nvidia",
                    "runc",
                ],
            },
        )
        self.assertEqual(
            observed["docker_info_sha256"],
            "0b71cb54285a74d73f57fc527d4541a2a9304622fb70815528c5a8251d20ae67",
        )
        self.assertEqual(
            observed["observation_sha256"],
            "71f91ee6ec24a494d2103c06da1656a234b10510243a70bec7b39f1440ee961a",
        )
        self.assertEqual(
            authority.canonical_json_bytes(observed) + b"\n",
            (
                b'{"artifact_kind":"vast_analytics_peercred_pid0_platform_observation",'
                b'"docker_info":{"containerd_commit":{"ID":"e53c7c1516c3b2bff98eb76f1f4117477e6f4e66"},'
                b'"default_runtime":"runc","driver":"overlayfs","driver_status":'
                b'[["driver-type","io.containerd.snapshotter.v1"]],"kernel_version":'
                b'"6.6.87.2-microsoft-standard-WSL2","name":"docker-desktop",'
                b'"operating_system":"Docker Desktop","os_type":"linux",'
                b'"required_runtimes":["io.containerd.runc.v2","nvidia","runc"],'
                b'"server_version":"29.7.2"},"docker_info_sha256":'
                b'"0b71cb54285a74d73f57fc527d4541a2a9304622fb70815528c5a8251d20ae67",'
                b'"observation_sha256":"71f91ee6ec24a494d2103c06da1656a234b10510243a70bec7b39f1440ee961a",'
                b'"schema_version":1,"wsl_osrelease":{"marker":"-microsoft-standard-WSL2",'
                b'"marker_present":true,"path":"/proc/sys/kernel/osrelease",'
                b'"raw_ascii":"6.6.87.2-microsoft-standard-WSL2\\n","sha256":'
                b'"ccd199c039f7944eb5289351597af34c9388338a60b6531c0d2fe55e8425019a",'
                b'"size_bytes":33}}\n'
            ),
        )
        self.assertEqual(
            authority._validate_peercred_pid0_platform_observation(observed),
            observed,
        )

    def test_platform_observation_rejects_backend_and_hash_drift(self) -> None:
        observed = self._platform()
        for path, replacement in (
            (("docker_info", "name"), "desktop-linux"),
            (("docker_info", "server_version"), "29.7.3"),
            (("docker_info", "driver"), "overlay2"),
            (("docker_info", "default_runtime"), "crun"),
            (("wsl_osrelease", "raw_ascii"), "6.6.87.2-linux\n"),
            (("observation_sha256",), "0" * 64),
        ):
            tampered = copy.deepcopy(observed)
            target = tampered
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = replacement
            with self.subTest(path=path):
                with self.assertRaises(SidecarError):
                    authority._validate_peercred_pid0_platform_observation(tampered)
        for field, replacement in (
            ("Name", "desktop-linux"),
            ("OperatingSystem", "Docker Engine"),
            ("ServerVersion", "29.7.3"),
            ("Driver", "overlay2"),
            ("DefaultRuntime", "crun"),
        ):
            docker_info = copy.deepcopy(DOCKER_INFO)
            docker_info[field] = replacement
            with self.subTest(docker_info_field=field):
                with self.assertRaises(SidecarError):
                    authority._build_peercred_pid0_platform_observation(
                        OSRELEASE_RAW,
                        docker_info,
                    )

    def test_platform_projection_ignores_unclaimed_docker_info_bulk(self) -> None:
        expanded = copy.deepcopy(DOCKER_INFO)
        expanded["DriverStatus"].append(["Backing Filesystem", "extfs"])
        expanded["ContainerdCommit"]["Expected"] = "unprojected"
        expanded["Runtimes"]["diagnostic-runtime"] = {"path": "diagnostic"}
        expanded["Labels"] = ["com.docker.desktop.address=unix:///example"]

        self.assertEqual(
            authority._build_peercred_pid0_platform_observation(
                OSRELEASE_RAW,
                expanded,
            ),
            self._platform(),
        )

    def test_observer_reads_exact_proc_file_and_small_docker_projection(self) -> None:
        calls: list[list[str]] = []

        def runner(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            calls.append(list(argv))
            self.assertEqual(
                kwargs,
                {
                    "check": True,
                    "capture_output": True,
                    "text": True,
                    "timeout": 30,
                },
            )
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout=json.dumps(DOCKER_INFO),
                stderr="",
            )

        observed = authority._observe_peercred_pid0_platform_observation(
            command_runner=runner
        )

        self.assertEqual(calls, [["docker", "info", "--format={{json .}}"]])
        self.assertEqual(observed, self._platform())

    def test_native_ext4_private_socket_custody_is_hash_bound(self) -> None:
        directory, path, listener = self._private_socket()
        try:
            custody = authority._native_ext4_private_socket_custody(
                directory,
                path,
            )
            self.assertEqual(custody["filesystem_magic"], "0x0000ef53")
            self.assertEqual(custody["directory_mode"], "0700")
            self.assertEqual(custody["directory_uid"], os.getuid())
            self.assertEqual(custody["directory_gid"], os.getgid())
            self.assertTrue(custody["native_ext4_private_socket_attested"])
            self.assertEqual(
                authority.canonical_sha256(
                    {
                        key: value
                        for key, value in custody.items()
                        if key != "identity_sha256"
                    }
                ),
                custody["identity_sha256"],
            )
        finally:
            listener.close()
            if os.path.lexists(path):
                path.unlink()
            directory.rmdir()

    def test_pid0_identity_is_never_represented_as_pid_attested(self) -> None:
        directory, path, listener = self._private_socket()
        try:
            custody = authority._native_ext4_private_socket_custody(directory, path)
            raw = struct.pack("3i", 0, os.getuid(), os.getgid())
            identity = authority._select_peer_identity(
                peer_raw=raw,
                docker_state_pid=7821,
                runtime_platform=self._platform(),
                runtime_custody=custody,
            )

            self.assertEqual(identity["peer_raw_hex"], raw.hex())
            if (os.getuid(), os.getgid()) == (1000, 1000):
                self.assertEqual(
                    identity["peer_raw_hex"],
                    "00000000e8030000e8030000",
                )
                self.assertEqual(
                    identity["peer_raw_sha256"],
                    "07613361b79150c7248c7c9a4c66843286648dbac919b1a4644c41d02fb2e3b3",
                )
            self.assertEqual(
                identity["peer_identity_mode"],
                authority.PEER_IDENTITY_MODE_DOCKER_DESKTOP_WSL2_PID0,
            )
            for field in (
                "pid_positive",
                "pid_matches_container_state_pid",
                "peer_pid_visible_in_controller_namespace",
                "peer_pid_state_pid_equality_attested",
                "peer_identity_by_pid_attested",
                "peer_socket_to_container_pid_binding_attested",
            ):
                self.assertIs(identity[field], False)
            self.assertIs(identity["container_state_pid_positive"], True)
            self.assertIs(identity["docker_desktop_containerd_backend_attested"], True)
            self.assertIs(identity["wsl2_platform_attested"], True)
            self.assertIs(identity["native_ext4_private_socket_attested"], True)
            self.assertIs(
                identity["protocol_nonce_capability_handshake_performed"], False
            )

            completed = authority._complete_peer_identity_after_handshake(identity)
            self.assertIs(
                completed["protocol_nonce_capability_handshake_performed"], True
            )
            self.assertIs(completed["global_eight_worker_handshake_barrier_attested"], True)
            self.assertIs(
                completed["peer_identity_by_protocol_capability_attested"], True
            )
            self.assertIs(completed["peer_identity_by_pid_attested"], False)
        finally:
            listener.close()
            if os.path.lexists(path):
                path.unlink()
            directory.rmdir()

    def test_visible_pid_mode_remains_exact_pid_attestation(self) -> None:
        raw = struct.pack("3i", 4242, os.getuid(), os.getgid())

        identity = authority._select_peer_identity(
            peer_raw=raw,
            docker_state_pid=4242,
            runtime_platform=None,
            runtime_custody=None,
        )

        self.assertEqual(
            identity["peer_identity_mode"],
            authority.PEER_IDENTITY_MODE_NATIVE_VISIBLE,
        )
        self.assertIs(identity["peer_pid_visible_in_controller_namespace"], True)
        self.assertIs(identity["peer_identity_by_pid_attested"], True)
        self.assertIs(identity["peer_socket_to_container_pid_binding_attested"], True)
        self.assertIs(identity["wsl2_platform_attested"], False)
        self.assertIs(identity["native_ext4_private_socket_attested"], False)

    def test_arbitrary_pid_uid_gid_and_platform_combinations_fail_closed(self) -> None:
        directory, path, listener = self._private_socket()
        try:
            custody = authority._native_ext4_private_socket_custody(directory, path)
            platform = self._platform()
            calls = (
                {
                    "peer_raw": b"\x00" * 11,
                    "docker_state_pid": 4242,
                    "runtime_platform": None,
                    "runtime_custody": None,
                },
                {
                    "peer_raw": struct.pack("3i", -1, os.getuid(), os.getgid()),
                    "docker_state_pid": 4242,
                    "runtime_platform": platform,
                    "runtime_custody": custody,
                },
                {
                    "peer_raw": struct.pack("3i", 4243, os.getuid(), os.getgid()),
                    "docker_state_pid": 4242,
                    "runtime_platform": None,
                    "runtime_custody": None,
                },
                {
                    "peer_raw": struct.pack("3i", 0, os.getuid() + 1, os.getgid()),
                    "docker_state_pid": 4242,
                    "runtime_platform": platform,
                    "runtime_custody": custody,
                },
                {
                    "peer_raw": struct.pack("3i", 0, os.getuid(), os.getgid() + 1),
                    "docker_state_pid": 4242,
                    "runtime_platform": platform,
                    "runtime_custody": custody,
                },
                {
                    "peer_raw": struct.pack("3i", 0, os.getuid(), os.getgid()),
                    "docker_state_pid": 0,
                    "runtime_platform": platform,
                    "runtime_custody": custody,
                },
                {
                    "peer_raw": struct.pack("3i", 0, os.getuid(), os.getgid()),
                    "docker_state_pid": 4242,
                    "runtime_platform": None,
                    "runtime_custody": custody,
                },
            )
            for call in calls:
                with self.subTest(call=call):
                    with self.assertRaises(SidecarError):
                        authority._select_peer_identity(**call)
        finally:
            listener.close()
            if os.path.lexists(path):
                path.unlink()
            directory.rmdir()

    def test_materializer_and_sidecar_complete_only_after_global_handshake(self) -> None:
        materializer_source = (
            ROOT / "scripts" / "checkpoint_model_parity_materializer.py"
        ).read_text(encoding="utf-8")
        sidecar_source = (
            ROOT / "scripts" / "checkpoint_gstreamer_analytics_sidecar.py"
        ).read_text(encoding="utf-8")

        self.assertIn("_attest_worker_peer_identity", materializer_source)
        self.assertIn("_complete_peer_identity_after_handshake", materializer_source)
        self.assertIn("peer_identities", materializer_source)
        self.assertIn("_attest_worker_peer_identity", sidecar_source)
        self.assertIn("_complete_peer_identity_after_handshake", sidecar_source)
        self.assertIn('"peer_identity":', sidecar_source)


if __name__ == "__main__":
    unittest.main()
