from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
import signal
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import kpp_legacy_iss_v2_offline_image_intake as intake


class _RetryingWindowsTemporaryDirectory(tempfile.TemporaryDirectory):
    """Retry only the observed transient Windows directory-not-empty cleanup."""

    def cleanup(self) -> None:
        deadline = time.monotonic() + 2.0
        while True:
            try:
                super().cleanup()
                return
            except OSError as error:
                if (
                    os.name != "nt"
                    or getattr(error, "winerror", None) != 145
                    or time.monotonic() >= deadline
                ):
                    raise
                time.sleep(0.02)


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")


def _add_regular(
    archive: tarfile.TarFile,
    name: str,
    payload: bytes,
    *,
    mtime: int = 0,
    pax_headers: dict[str, str] | None = None,
) -> None:
    member = tarfile.TarInfo(name)
    member.size = len(payload)
    member.mode = 0o444
    member.uid = 0
    member.gid = 0
    member.mtime = mtime
    if pax_headers is not None:
        member.pax_headers = pax_headers
    archive.addfile(member, io.BytesIO(payload))


def _reseal_ustar_header(header: bytearray, *, canonical: bool = True) -> bytes:
    header[148:156] = b" " * 8
    checksum = sum(header)
    header[148:156] = (
        f"{checksum:06o}".encode("ascii") + b"\0 "
        if canonical
        else f"{checksum:07o}".encode("ascii") + b"\0"
    )
    return bytes(header)


def _layer_tar() -> bytes:
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        _add_regular(archive, "synthetic-layer-file", b"synthetic-layer-payload")
    return stream.getvalue()


_ABSENT = object()


def _docker_save_hybrid(
    *,
    extra_tag: bool = False,
    extra_blob: bool = False,
    hardlink: bool = False,
    corrupt_diff_id: bool = False,
    omit_oci_layout: bool = False,
    gzip_layer: bool = False,
    reverse_member_order: bool = False,
    metadata_mtime: int = 0,
    pax_member: bool = False,
    duplicate_member: bool = False,
    regular_trailing_slash: bool = False,
    manifest_media_mismatch: bool = False,
    descriptor_media_type_confusion: bool = False,
    concatenated_archive: bool = False,
    float_schema_versions: bool = False,
    layer_annotations: object = _ABSENT,
    config_annotations: object = _ABSENT,
) -> tuple[bytes, str]:
    uncompressed_layer = _layer_tar()
    layer = (
        gzip.compress(uncompressed_layer, compresslevel=6, mtime=0)
        if gzip_layer
        else uncompressed_layer
    )
    layer_hex = hashlib.sha256(layer).hexdigest()
    diff_hex = hashlib.sha256(uncompressed_layer).hexdigest()
    config = {
        "architecture": "amd64",
        "config": {
            "Entrypoint": [intake.TENSORRT_ENTRYPOINT],
            "Labels": dict(intake.IMAGE_LABELS),
        },
        "os": "linux",
        "rootfs": {
            "type": "layers",
            "diff_ids": [
                "sha256:" + ("f" * 64 if corrupt_diff_id else diff_hex)
            ],
        },
    }
    config_payload = _canonical(config)
    config_hex = hashlib.sha256(config_payload).hexdigest()
    config_digest = "sha256:" + config_hex
    config_descriptor: dict[str, object] = {
        "mediaType": "application/vnd.oci.image.config.v1+json",
        "digest": config_digest,
        "size": len(config_payload),
    }
    if config_annotations is not _ABSENT:
        config_descriptor["annotations"] = config_annotations
    layer_descriptor: dict[str, object] = {
        "mediaType": (
            []
            if descriptor_media_type_confusion
            else (
                "application/vnd.oci.image.layer.v1.tar+gzip"
                if gzip_layer
                else "application/vnd.oci.image.layer.v1.tar"
            )
        ),
        "digest": "sha256:" + layer_hex,
        "size": len(layer),
    }
    if layer_annotations is not _ABSENT:
        layer_descriptor["annotations"] = layer_annotations
    manifest = {
        "schemaVersion": 2.0 if float_schema_versions else 2,
        "mediaType": "application/vnd.oci.image.manifest.v1+json",
        "config": config_descriptor,
        "layers": [layer_descriptor],
    }
    manifest_payload = _canonical(manifest)
    manifest_hex = hashlib.sha256(manifest_payload).hexdigest()
    image_id = "sha256:" + manifest_hex
    index = {
        "schemaVersion": 2.0 if float_schema_versions else 2,
        "manifests": [
            {
                "mediaType": "application/vnd.oci.image.manifest.v1+json",
                "digest": "sha256:" + manifest_hex,
                "size": len(manifest_payload),
                "platform": {"architecture": "amd64", "os": "linux"},
            }
        ],
    }
    if manifest_media_mismatch:
        index["manifests"][0]["mediaType"] = (
            "application/vnd.docker.distribution.manifest.v2+json"
        )
    docker_manifest = [
        {
            "Config": f"blobs/sha256/{config_hex}",
            "RepoTags": [intake.TENSORRT_IMAGE] if extra_tag else None,
            "Layers": [f"blobs/sha256/{layer_hex}"],
        }
    ]
    files = {
        "index.json": _canonical(index),
        "manifest.json": _canonical(docker_manifest),
        "repositories": _canonical(
            {"vast/analytics-tensorrt-worker": {"v2": config_hex}}
            if extra_tag
            else {}
        ),
        f"blobs/sha256/{manifest_hex}": manifest_payload,
        f"blobs/sha256/{config_hex}": config_payload,
        f"blobs/sha256/{layer_hex}": layer,
    }
    if not omit_oci_layout:
        files["oci-layout"] = _canonical({"imageLayoutVersion": "1.0.0"})
    if extra_blob:
        files["blobs/sha256/" + "e" * 64] = b"unreferenced"
    stream = io.BytesIO()
    archive_format = tarfile.PAX_FORMAT if pax_member else tarfile.USTAR_FORMAT
    with tarfile.open(fileobj=stream, mode="w", format=archive_format) as archive:
        items = sorted(files.items(), reverse=reverse_member_order)
        for name, payload in items:
            stored_name = "manifest.json/" if regular_trailing_slash and name == "manifest.json" else name
            _add_regular(
                archive,
                stored_name,
                payload,
                mtime=metadata_mtime,
                pax_headers={"comment": "forbidden"} if pax_member and name == "index.json" else None,
            )
        if duplicate_member:
            _add_regular(archive, "index.json", files["index.json"])
        if hardlink:
            member = tarfile.TarInfo("hardlink")
            member.type = tarfile.LNKTYPE
            member.linkname = "manifest.json"
            archive.addfile(member)
    payload = stream.getvalue()
    if concatenated_archive:
        trailing = io.BytesIO()
        with tarfile.open(fileobj=trailing, mode="w", format=tarfile.USTAR_FORMAT) as archive:
            _add_regular(archive, "evil", b"unexpected trailing archive")
        payload += trailing.getvalue()
    return payload, image_id


class _ArchiveSession:
    def __init__(self, *, size_bytes: int, sha256: str) -> None:
        self.identity = intake.FileIdentity(size_bytes=size_bytes, sha256=sha256)
        self.normalized_identity = intake.FileIdentity(
            size_bytes=size_bytes + 512,
            sha256="d" * 64,
        )
        self.inventory = {
            "format": "docker_save_oci_hybrid_v1",
            "outer_tar_profile": "closed_ustar_regular_directory_only_v1",
            "image_id": intake.TENSORRT_IMAGE_ID,
            "platform": {"os": "linux", "architecture": "amd64"},
            "repo_tags": [],
            "repo_digests": [],
            "layer_count": 1,
            "inventory_sha256": "b" * 64,
        }
        self.load_input = "/proc/self/fd/91"
        self.pass_fds = (91,)
        self.revalidations = 0

    def __enter__(self) -> "_ArchiveSession":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def revalidate(self) -> None:
        self.revalidations += 1


class _HeldDockerCli:
    def __init__(self) -> None:
        self.identity = intake.FileIdentity(44_986_088, "a" * 64)
        self.executable = "/proc/self/fd/77"
        self.pass_fds = (77,)
        self.revalidations = 0

    def __enter__(self) -> "_HeldDockerCli":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def revalidate(self) -> None:
        self.revalidations += 1


class _HeldDaemonLease:
    pass_fds = (88,)

    def __enter__(self) -> "_HeldDaemonLease":
        return self

    def __exit__(self, *_args: object) -> None:
        return None


class _FailingOutputNamespace:
    def __init__(self, inner, *, fail_method: str) -> None:
        self._inner = inner
        self._fail_method = fail_method

    def __enter__(self):
        self._inner.__enter__()
        return self

    def __exit__(self, *args: object) -> None:
        return self._inner.__exit__(*args)

    def __getattr__(self, name: str):
        return getattr(self._inner, name)

    def create_fence(self, value) -> None:
        if self._fail_method == "create_fence":
            raise intake.IntakeContractError("synthetic crash before fence commit")
        self._inner.create_fence(value)

    def create_receipt(self, value) -> None:
        if self._fail_method == "create_receipt":
            raise intake.IntakeContractError("synthetic receipt durability failure")
        self._inner.create_receipt(value)

    def create_attempt(self, value) -> None:
        if self._fail_method == "create_attempt":
            raise intake.IntakeContractError("synthetic attempt durability outcome unknown")
        self._inner.create_attempt(value)


class _PathBackedPosixNamespaceOps:
    """Exercise the POSIX dirfd state machine without claiming Windows syscalls."""

    def __init__(self, project_root: Path) -> None:
        self._project_root = project_root
        self._next_descriptor = 10_000
        self._paths: dict[int, Path] = {}
        self.fail_temporary_fsync_once = False
        self.fail_parent_fsync_after_rename_once = False
        self._rename_completed = False

    def _allocate(self, path: Path) -> int:
        descriptor = self._next_descriptor
        self._next_descriptor += 1
        self._paths[descriptor] = path
        return descriptor

    def _path(self, descriptor: int) -> Path:
        return self._paths[descriptor]

    @staticmethod
    def _stable_stat(path: Path):
        observed = path.stat(follow_symlinks=False)
        return SimpleNamespace(
            st_dev=observed.st_dev,
            st_ino=observed.st_ino,
            st_mode=observed.st_mode,
            st_nlink=observed.st_nlink,
            st_size=observed.st_size,
            st_mtime_ns=0,
            st_ctime_ns=0,
            st_uid=observed.st_uid,
            st_gid=observed.st_gid,
        )

    def open_project(self, path: Path) -> int:
        if path != self._project_root or not path.is_dir() or path.is_symlink():
            raise intake.IntakeContractError("synthetic project root custody failed")
        return self._allocate(path)

    def fstat(self, descriptor: int):
        return self._stable_stat(self._path(descriptor))

    def stat_at(self, directory_fd: int, name: str):
        return self._stable_stat(self._path(directory_fd) / name)

    def open_directory_at(self, directory_fd: int, name: str) -> int:
        path = self._path(directory_fd) / name
        if not path.is_dir() or path.is_symlink():
            raise intake.IntakeContractError("synthetic no-follow directory open failed")
        return self._allocate(path)

    def close(self, descriptor: int) -> None:
        self._paths.pop(descriptor)

    def listdir(self, descriptor: int) -> list[str]:
        return sorted(item.name for item in self._path(descriptor).iterdir())

    def mkdir_at(self, directory_fd: int, name: str, mode: int) -> None:
        self._path(directory_fd).joinpath(name).mkdir(mode=mode)

    def fsync(self, descriptor: int) -> None:
        path = self._path(descriptor)
        if self.fail_temporary_fsync_once and path.name.endswith(".pending"):
            self.fail_temporary_fsync_once = False
            raise OSError("synthetic pre-rename fsync failure")
        if self.fail_parent_fsync_after_rename_once and self._rename_completed:
            self.fail_parent_fsync_after_rename_once = False
            raise OSError("synthetic post-rename fsync failure")

    def unlink_at(self, directory_fd: int, name: str) -> None:
        (self._path(directory_fd) / name).unlink()

    def rmdir_at(self, directory_fd: int, name: str) -> None:
        (self._path(directory_fd) / name).rmdir()

    def rename_noreplace(
        self,
        source_directory_fd: int,
        source_name: str,
        target_directory_fd: int,
        target_name: str,
    ) -> None:
        source = self._path(source_directory_fd) / source_name
        target = self._path(target_directory_fd) / target_name
        if target.exists():
            raise intake.IntakeContractError("synthetic no-replace collision")
        source.rename(target)
        for descriptor, path in tuple(self._paths.items()):
            if path == source or path.is_relative_to(source):
                self._paths[descriptor] = target / path.relative_to(source)
        self._rename_completed = True

    def write_private_file(self, directory_fd: int, name: str, payload: bytes) -> None:
        value = json.loads(payload.decode("ascii"))
        intake._write_create_new(self._path(directory_fd) / name, value)

    def read_artifact(
        self,
        directory_fd: int,
        name: str,
        *,
        domain: bytes,
        hash_field: str,
    ) -> dict[str, object]:
        return intake._read_artifact(
            self._path(directory_fd) / name,
            domain=domain,
            hash_field=hash_field,
        )

    def current_uid(self) -> int:
        return self._project_root.stat().st_uid

    def replace_name_binding(self, directory_fd: int, name: str) -> None:
        original = self._path(directory_fd) / name
        displaced = self._path(directory_fd) / (name + ".displaced")
        original.rename(displaced)
        for descriptor, path in tuple(self._paths.items()):
            if path == original or path.is_relative_to(original):
                self._paths[descriptor] = displaced / path.relative_to(original)
        original.mkdir(mode=0o700)


class _FakeDocker:
    def __init__(
        self,
        *,
        preexisting: bool = False,
        load_returncode: int = 0,
        visible_after_failure: bool = False,
        extra_after_load: bool = False,
        preexisting_other: bool = False,
        mutate_preexisting_after_load: bool = False,
        add_container_after_load: bool = False,
        target_tag_after_load: bool = False,
        raise_after_load_mutation: bool = False,
        timed_out_after_load: bool = False,
        containerd_snapshotter: bool = True,
        load_stdout: bytes | None = None,
        load_stderr: bytes | None = None,
    ) -> None:
        self.loaded = preexisting
        self.load_returncode = load_returncode
        self.visible_after_failure = visible_after_failure
        self.extra_after_load = extra_after_load
        self.preexisting_other = preexisting_other
        self.mutate_preexisting_after_load = mutate_preexisting_after_load
        self.add_container_after_load = add_container_after_load
        self.target_tag_after_load = target_tag_after_load
        self.raise_after_load_mutation = raise_after_load_mutation
        self.timed_out_after_load = timed_out_after_load
        self.containerd_snapshotter = containerd_snapshotter
        self.load_stdout = load_stdout
        self.load_stderr = load_stderr
        self.load_attempted = False
        self.calls: list[tuple[tuple[str, ...], tuple[int, ...]]] = []
        self.executable_overrides: list[str | None] = []

    @staticmethod
    def _document(
        image_id: str,
        *,
        repo_tags: list[str] | None = None,
        repo_digests: list[str] | None = None,
    ) -> dict[str, object]:
        return {
            "Id": image_id,
            "Os": "linux",
            "Architecture": "amd64",
            "RepoTags": repo_tags,
            "RepoDigests": repo_digests,
            "Config": {
                "Entrypoint": [intake.TENSORRT_ENTRYPOINT],
                "Labels": dict(intake.IMAGE_LABELS),
            },
        }

    def run(
        self,
        argv: list[str],
        *,
        timeout_seconds: float,
        stdout_limit: int,
        stderr_limit: int,
        pass_fds: tuple[int, ...] = (),
        executable_override: str | None = None,
    ) -> intake.CommandCapture:
        del timeout_seconds, stdout_limit, stderr_limit
        command = tuple(argv)
        self.calls.append((command, pass_fds))
        self.executable_overrides.append(executable_override)
        if "info" in command:
            return intake.CommandCapture(
                0,
                intake.canonical_line(
                    {
                        "ID": "1e493309-3767-45fb-9078-05b838bdfd80",
                        "ServerVersion": "29.5.3",
                        "OSType": "linux",
                        "Architecture": "x86_64",
                        "Name": "synthetic",
                        "Driver": (
                            "overlayfs" if self.containerd_snapshotter else "overlay2"
                        ),
                        "DriverStatus": (
                            [["driver-type", "io.containerd.snapshotter.v1"]]
                            if self.containerd_snapshotter
                            else None
                        ),
                    }
                ),
                b"",
            )
        if "version" in command:
            return intake.CommandCapture(
                0,
                b'{"Version":"29.5.3","ApiVersion":"1.54",'
                b'"Os":"linux","Arch":"amd64"}\n',
                b"",
            )
        if command[3:8] == ("image", "ls", "--all", "--no-trunc", "--quiet"):
            values: list[str] = []
            if self.loaded:
                values.append(intake.TENSORRT_IMAGE_ID)
            if self.extra_after_load and self.loaded:
                values.append("sha256:" + "c" * 64)
            if self.preexisting_other:
                values.append("sha256:" + "9" * 64)
            payload = "".join(value + "\n" for value in values).encode("ascii")
            return intake.CommandCapture(0, payload, b"")
        if command[3:8] == ("container", "ls", "--all", "--no-trunc", "--quiet"):
            payload = (
                ("8" * 64 + "\n").encode("ascii")
                if self.add_container_after_load and self.load_attempted
                else b""
            )
            return intake.CommandCapture(0, payload, b"")
        if command[3:5] == ("image", "inspect"):
            reference = command[-1]
            visible = self.loaded or (
                self.load_attempted
                and self.load_returncode != 0
                and self.visible_after_failure
            )
            if reference == intake.TENSORRT_IMAGE_ID and visible:
                return intake.CommandCapture(
                    0,
                    intake.canonical_line(
                        self._document(
                            reference,
                            repo_tags=[intake.TENSORRT_IMAGE]
                            if self.target_tag_after_load and self.load_attempted
                            else None,
                        )
                    ),
                    b"",
                )
            if reference == "sha256:" + "c" * 64 and self.extra_after_load:
                return intake.CommandCapture(
                    0,
                    intake.canonical_line(self._document(reference)),
                    b"",
                )
            if reference == "sha256:" + "9" * 64 and self.preexisting_other:
                mutated = self.mutate_preexisting_after_load and self.load_attempted
                return intake.CommandCapture(
                    0,
                    intake.canonical_line(
                        self._document(
                            reference,
                            repo_tags=["synthetic/drift:latest"] if mutated else None,
                            repo_digests=["synthetic/drift@sha256:" + "7" * 64]
                            if mutated
                            else None,
                        )
                    ),
                    b"",
                )
            return intake.CommandCapture(
                1,
                b"",
                f"Error: No such image: {reference}\n".encode("ascii"),
            )
        if command[3:5] == ("image", "load"):
            self.load_attempted = True
            if self.load_returncode == 0 or self.visible_after_failure:
                self.loaded = True
            if self.raise_after_load_mutation:
                raise OSError("synthetic runner loss after daemon mutation")
            return intake.CommandCapture(
                self.load_returncode,
                (
                    self.load_stdout
                    if self.load_stdout is not None
                    else (
                        b""
                        if self.load_returncode == 0
                        else b"synthetic partial load\n"
                    )
                ),
                (
                    self.load_stderr
                    if self.load_stderr is not None
                    else (
                        b""
                        if self.load_returncode == 0
                        else b"synthetic load failure\n"
                    )
                ),
                timed_out=self.timed_out_after_load,
            )
        raise AssertionError(command)


class OfflineImageIntakeTests(unittest.TestCase):
    _DAEMON_ID = "1e493309-3767-45fb-9078-05b838bdfd80"

    @classmethod
    def setUpClass(cls) -> None:
        cls._original_temporary_directory = tempfile.TemporaryDirectory
        tempfile.TemporaryDirectory = _RetryingWindowsTemporaryDirectory

    @classmethod
    def tearDownClass(cls) -> None:
        tempfile.TemporaryDirectory = cls._original_temporary_directory

    @classmethod
    def _output(cls, root: Path) -> Path:
        return (
            root
            / "runs"
            / "nonpublication"
            / "offline_image_intake"
            / intake._durable_operation_namespace_id(cls._DAEMON_ID)
        )

    def _dependencies(
        self,
        runner: _FakeDocker,
        *,
        project_root: Path,
        archive_size: int,
        archive_sha: str,
        lifecycle_hook=None,
        archive_opener=None,
        output_namespace_factory=None,
        canonical_project_root: Path | None = None,
    ) -> intake._IntakeDependencies:
        return intake._IntakeDependencies(
            platform_name="posix",
            environment={},
            observe_docker_cli=lambda: intake.FileIdentity(44_986_088, "a" * 64),
            command_runner=runner,
            archive_opener=(
                archive_opener
                or (
                    lambda **_kwargs: _ArchiveSession(
                        size_bytes=archive_size,
                        sha256=archive_sha,
                    )
                )
            ),
            canonical_project_root=(
                project_root
                if canonical_project_root is None
                else canonical_project_root
            ),
            local_runtime_guard=lambda: None,
            daemon_lock_factory=lambda _daemon_id: nullcontext(),
            output_namespace_factory=(
                output_namespace_factory
                or (
                    lambda selected_project_root, namespace: intake._open_output_namespace(
                        selected_project_root,
                        namespace,
                    )
                )
            ),
            lifecycle_hook=lifecycle_hook,
        )

    def _invoke(
        self,
        root: Path,
        archive: Path,
        runner: _FakeDocker,
        *,
        lifecycle_hook=None,
        archive_opener=None,
        output_namespace_factory=None,
        intake_id: str = "synthetic-intake-v1",
        canonical_project_root: Path | None = None,
    ) -> tuple[dict[str, object], int]:
        payload = archive.read_bytes()
        return intake.intake_offline_image(
            project_root=root,
            archive_path=archive,
            expected_archive_size_bytes=len(payload),
            expected_archive_sha256=hashlib.sha256(payload).hexdigest(),
            intake_id=intake_id,
            expected_docker_cli_size_bytes=44_986_088,
            expected_docker_cli_sha256="a" * 64,
            expected_daemon_id=self._DAEMON_ID,
            expected_daemon_server_version="29.5.3",
            expected_daemon_api_version="1.54",
            _dependencies=self._dependencies(
                runner,
                project_root=root,
                archive_size=len(payload),
                archive_sha=hashlib.sha256(payload).hexdigest(),
                lifecycle_hook=lifecycle_hook,
                archive_opener=archive_opener,
                output_namespace_factory=output_namespace_factory,
                canonical_project_root=canonical_project_root,
            ),
        )

    def test_intake_security_boundary_owns_exact_target_literals(self) -> None:
        import kpp_legacy_iss_v2_secondary_sensitivity_pilot as planner

        expected = {
            "image": "vast/analytics-tensorrt-worker:v2",
            "image_id": "sha256:29ad51f4057f5aa77eb18e572c5055ed465fac39d49365d8eb5ffafe4fe8001f",
            "base_image_id": "sha256:277bb99b1b23b5b763332041703905242a1238c3faeb72533aa6045c9d2d7489",
            "entrypoint": "/opt/vast/bin/vast_tensorrt_worker",
        }
        self.assertEqual(
            {
                "image": intake.TENSORRT_IMAGE,
                "image_id": intake.TENSORRT_IMAGE_ID,
                "base_image_id": intake.TENSORRT_BASE_IMAGE_ID,
                "entrypoint": intake.TENSORRT_ENTRYPOINT,
            },
            expected,
        )
        with mock.patch.object(planner, "TENSORRT_IMAGE_ID", "sha256:" + "f" * 64):
            self.assertEqual(intake.TENSORRT_IMAGE_ID, expected["image_id"])
        source = Path(intake.__file__).read_text("utf-8")
        self.assertNotIn(
            "from kpp_legacy_iss_v2_secondary_sensitivity_pilot import",
            source,
        )

    def test_default_contract_self_binds_project_and_per_user_global_state(self) -> None:
        dependencies = intake._default_dependencies()
        self.assertEqual(dependencies.canonical_project_root, intake._CANONICAL_PROJECT_ROOT)
        self.assertIs(dependencies.output_namespace_factory, intake._open_global_output_namespace)
        with tempfile.TemporaryDirectory() as raw, mock.patch.object(
            intake,
            "_default_user_state_root",
            return_value=Path(raw),
        ):
            output = intake._open_global_output_namespace(
                Path(raw) / "ignored-project",
                "target-" + "f" * 64,
            )
            self.assertEqual(output._project_root, Path(raw))
            self.assertEqual(output._components, intake._GLOBAL_STATE_COMPONENTS)
            self.assertTrue(output._require_non_owner_writable)

    @unittest.skipUnless(os.name == "nt", "bounded cleanup retry targets WinError 145")
    def test_windows_temporary_directory_cleanup_retries_only_directory_not_empty(self) -> None:
        class FlakyCleanup(_RetryingWindowsTemporaryDirectory):
            attempts = 0

            @classmethod
            def _rmtree(cls, name, ignore_errors=False, repeated=False):
                cls.attempts += 1
                if cls.attempts == 1:
                    error = OSError("synthetic directory-not-empty race")
                    error.winerror = 145
                    raise error
                return super()._rmtree(
                    name,
                    ignore_errors=ignore_errors,
                    repeated=repeated,
                )

        with FlakyCleanup() as raw:
            Path(raw, "payload").write_bytes(b"synthetic")
        self.assertEqual(FlakyCleanup.attempts, 2)

    def test_project_root_self_binding_precedes_archive_daemon_and_output(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            canonical_root = base / "canonical"
            alternate_root = base / "alternate"
            canonical_root.mkdir()
            alternate_root.mkdir()
            archive = alternate_root / "image.tar"
            archive.write_bytes(b"synthetic pinned archive")
            runner = _FakeDocker()
            result, code = self._invoke(
                alternate_root,
                archive,
                runner,
                canonical_project_root=canonical_root,
            )
            self.assertEqual((code, result["status"]), (78, "blocked_contract_violation"))
            self.assertEqual(runner.calls, [])
            self.assertFalse((alternate_root / "runs").exists())

    @staticmethod
    def _synthetic_namespace_artifacts():
        fence = intake._seal(
            {"schema_version": 1, "artifact_kind": "synthetic-fence"},
            domain=intake._FENCE_DOMAIN,
            hash_field="fence_sha256",
        )
        attempt = intake._seal(
            {"schema_version": 1, "artifact_kind": "synthetic-attempt"},
            domain=intake._ATTEMPT_DOMAIN,
            hash_field="attempt_sha256",
        )
        receipt = intake._seal(
            {"schema_version": 1, "artifact_kind": "synthetic-receipt"},
            domain=intake._RECEIPT_DOMAIN,
            hash_field="receipt_sha256",
        )
        return fence, attempt, receipt

    def test_posix_namespace_state_machine_via_path_backed_syscall_adapter(self) -> None:
        fence, attempt, receipt = self._synthetic_namespace_artifacts()
        namespace = "target-" + "a" * 64
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            ops = _PathBackedPosixNamespaceOps(root)
            with intake._PosixOutputNamespace(root, namespace, _ops=ops) as output:
                output.create_fence(fence)
                output.create_attempt(attempt)
                output.create_receipt(receipt)
                self.assertEqual(output.read_fence(), fence)
                self.assertEqual(output.read_attempt(), attempt)
                self.assertEqual(output.read_receipt(), receipt)
                with self.assertRaises(intake.IntakeContractError):
                    output.create_attempt(attempt)
                with self.assertRaises(intake.IntakeContractError):
                    output.create_receipt(receipt)
                ops.replace_name_binding(output._nodes[-2].descriptor, namespace)
                with self.assertRaises(intake.IntakeContractError):
                    output.revalidate()

    def test_per_user_global_component_chain_uses_same_dirfd_no_replace_state_machine(self) -> None:
        fence, attempt, _receipt = self._synthetic_namespace_artifacts()
        namespace = "target-" + "1" * 64
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            ops = _PathBackedPosixNamespaceOps(root)
            with intake._PosixOutputNamespace(
                root,
                namespace,
                _ops=ops,
                _components=intake._GLOBAL_STATE_COMPONENTS,
            ) as output:
                output.create_fence(fence)
                output.create_attempt(attempt)
                self.assertEqual(output.read_fence(), fence)
                self.assertEqual(output.read_attempt(), attempt)
            expected = root.joinpath(*intake._GLOBAL_STATE_COMPONENTS, namespace)
            self.assertTrue((expected / intake.FENCE_NAME).is_file())
            self.assertTrue((expected / intake.ATTEMPT_NAME).is_file())

    def test_posix_namespace_adapter_covers_fence_collision_and_fsync_crash_boundaries(self) -> None:
        fence, _attempt, _receipt = self._synthetic_namespace_artifacts()
        namespace = "target-" + "b" * 64
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            ops = _PathBackedPosixNamespaceOps(root)
            with intake._PosixOutputNamespace(root, namespace, _ops=ops) as output:
                parent = output._ensure_intake_parent()
                (ops._path(parent.descriptor) / namespace).mkdir(mode=0o700)
                with self.assertRaises(intake.IntakeContractError):
                    output.create_fence(fence)
            target = root / "runs/nonpublication/offline_image_intake" / namespace
            self.assertTrue(target.is_dir())
            self.assertFalse((target / intake.FENCE_NAME).exists())
            self.assertFalse(
                any(item.name.endswith(".pending") for item in target.parent.iterdir())
            )

        for boundary in ("before_rename", "after_rename"):
            with self.subTest(boundary=boundary), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                ops = _PathBackedPosixNamespaceOps(root)
                if boundary == "before_rename":
                    ops.fail_temporary_fsync_once = True
                else:
                    ops.fail_parent_fsync_after_rename_once = True
                with intake._PosixOutputNamespace(root, namespace, _ops=ops) as output:
                    with self.assertRaises(OSError):
                        output.create_fence(fence)
                target = root / "runs/nonpublication/offline_image_intake" / namespace
                if boundary == "before_rename":
                    self.assertFalse(target.exists())
                else:
                    self.assertTrue((target / intake.FENCE_NAME).is_file())
                    with intake._PosixOutputNamespace(root, namespace, _ops=ops) as reopened:
                        self.assertEqual(reopened.read_fence(), fence)

    def test_posix_namespace_enter_rejects_foreign_entry_and_closes_every_held_handle(self) -> None:
        namespace = "target-" + "d" * 64
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            output = root / "runs/nonpublication/offline_image_intake" / namespace
            output.mkdir(parents=True, mode=0o700)
            (output / "foreign-entry").write_bytes(b"foreign")
            ops = _PathBackedPosixNamespaceOps(root)
            with self.assertRaises(intake.IntakeContractError):
                with intake._PosixOutputNamespace(root, namespace, _ops=ops):
                    self.fail("foreign output entry must fail during namespace entry")
            self.assertEqual(ops._paths, {})

    def test_posix_namespace_owned_parent_open_failure_closes_unadopted_child_handle(self) -> None:
        class FailingChildStatOps(_PathBackedPosixNamespaceOps):
            def fstat(self, descriptor: int):
                if self._path(descriptor).name == "runs":
                    raise intake.IntakeContractError("synthetic child fstat failure")
                return super().fstat(descriptor)

        namespace = "target-" + "e" * 64
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            ops = FailingChildStatOps(root)
            with self.assertRaises(intake.IntakeContractError):
                with intake._PosixOutputNamespace(root, namespace, _ops=ops) as output:
                    output._ensure_intake_parent()
            self.assertEqual(ops._paths, {})

    @unittest.skipUnless(
        os.name == "posix" and sys.platform.startswith("linux"),
        "real relative renameat2 custody requires Linux",
    )
    def test_real_posix_namespace_fence_attempt_receipt_and_no_replace(self) -> None:
        fence, attempt, receipt = self._synthetic_namespace_artifacts()
        namespace = "target-" + "c" * 64
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            with intake._PosixOutputNamespace(root, namespace) as output:
                output.create_fence(fence)
                output.create_attempt(attempt)
                output.create_receipt(receipt)
                self.assertEqual(output.read_fence(), fence)
                self.assertEqual(output.read_attempt(), attempt)
                self.assertEqual(output.read_receipt(), receipt)
                with self.assertRaises(intake.IntakeContractError):
                    output.create_attempt(attempt)
                with self.assertRaises(intake.IntakeContractError):
                    output.create_receipt(receipt)

    def test_docker29_hybrid_inventory_accepts_exact_graph(self) -> None:
        payload, image_id = _docker_save_hybrid()
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "image.tar"
            path.write_bytes(payload)
            descriptor = os.open(path, os.O_RDONLY)
            try:
                observed = intake._validate_docker_save_hybrid(
                    descriptor,
                    expected_image_id=image_id,
                    expected_entrypoint=intake.TENSORRT_ENTRYPOINT,
                    expected_labels=intake.IMAGE_LABELS,
                )
            finally:
                os.close(descriptor)
        self.assertEqual(observed["image_id"], image_id)
        self.assertEqual(
            observed["outer_tar_profile"],
            "closed_ustar_regular_directory_only_v1",
        )
        self.assertEqual(observed["repo_tags"], [])
        self.assertEqual(observed["layer_count"], 1)
        self.assertEqual(observed["manifest_digest"], image_id)
        self.assertNotEqual(observed["config_digest"], image_id)

    def test_docker29_real_graph_semantics_accept_exact_rewrite_annotation(self) -> None:
        payload, image_id = _docker_save_hybrid(
            gzip_layer=True,
            layer_annotations={"buildkit/rewritten-timestamp": "0"},
        )
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "image.tar"
            path.write_bytes(payload)
            descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0))
            try:
                observed = intake._validate_docker_save_hybrid(
                    descriptor,
                    expected_image_id=image_id,
                    expected_entrypoint=intake.TENSORRT_ENTRYPOINT,
                    expected_labels=intake.IMAGE_LABELS,
                )
            finally:
                os.close(descriptor)
        self.assertEqual(observed["image_id"], image_id)
        self.assertEqual(observed["manifest_digest"], image_id)
        self.assertNotEqual(observed["config_digest"], image_id)
        self.assertEqual(observed["layer_count"], 1)

    def test_docker29_layer_annotations_are_absent_or_exact_and_nowhere_else(self) -> None:
        invalid_layer_annotations: tuple[object, ...] = (
            {},
            {"buildkit/rewritten-timestamp": "1"},
            {"unexpected": "0"},
            {"buildkit/rewritten-timestamp": "0", "unexpected": "0"},
            [],
            "0",
            0,
        )
        for annotation in invalid_layer_annotations:
            with self.subTest(annotation=annotation), tempfile.TemporaryDirectory() as raw:
                payload, image_id = _docker_save_hybrid(layer_annotations=annotation)
                path = Path(raw) / "image.tar"
                path.write_bytes(payload)
                descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0))
                try:
                    with self.assertRaises(intake.IntakeContractError):
                        intake._validate_docker_save_hybrid(
                            descriptor,
                            expected_image_id=image_id,
                            expected_entrypoint=intake.TENSORRT_ENTRYPOINT,
                            expected_labels=intake.IMAGE_LABELS,
                        )
                finally:
                    os.close(descriptor)

        payload, image_id = _docker_save_hybrid(
            config_annotations={"buildkit/rewritten-timestamp": "0"},
        )
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "image.tar"
            path.write_bytes(payload)
            descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0))
            try:
                with self.assertRaises(intake.IntakeContractError):
                    intake._validate_docker_save_hybrid(
                        descriptor,
                        expected_image_id=image_id,
                        expected_entrypoint=intake.TENSORRT_ENTRYPOINT,
                        expected_labels=intake.IMAGE_LABELS,
                    )
            finally:
                os.close(descriptor)

    def test_docker29_expected_image_id_binds_the_manifest_not_the_config(self) -> None:
        payload, image_id = _docker_save_hybrid()
        wrong_image_id = "sha256:" + ("0" * 64)
        self.assertNotEqual(image_id, wrong_image_id)
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "image.tar"
            path.write_bytes(payload)
            descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0))
            try:
                with self.assertRaises(intake.IntakeContractError):
                    intake._validate_docker_save_hybrid(
                        descriptor,
                        expected_image_id=wrong_image_id,
                        expected_entrypoint=intake.TENSORRT_ENTRYPOINT,
                        expected_labels=intake.IMAGE_LABELS,
                    )
            finally:
                os.close(descriptor)

    def test_cli_argument_failure_is_one_canonical_assessment_line_and_exit78(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "-B",
                str(SCRIPTS / "kpp_legacy_iss_v2_offline_image_intake.py"),
            ],
            shell=False,
            env={},
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
            check=False,
        )
        self.assertEqual(completed.returncode, 78)
        self.assertEqual(completed.stderr, b"")
        self.assertEqual(completed.stdout.count(b"\n"), 1)
        assessment = json.loads(completed.stdout.decode("ascii"))
        self.assertEqual(assessment["status"], "blocked_contract_violation")
        self.assertTrue(assessment["load_command_start_possible_historically"])
        self.assertFalse(assessment["historical_load_command_outcome_known"])
        for field in intake.FALSE_CLAIM_FIELDS:
            self.assertIs(assessment[field], False)

    def test_hybrid_inventory_streams_gzip_blob_digest_and_uncompressed_diff_id(self) -> None:
        payload, image_id = _docker_save_hybrid(gzip_layer=True)
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "image.tar"
            path.write_bytes(payload)
            descriptor = os.open(path, os.O_RDONLY)
            try:
                observed = intake._validate_docker_save_hybrid(
                    descriptor,
                    expected_image_id=image_id,
                    expected_entrypoint=intake.TENSORRT_ENTRYPOINT,
                    expected_labels=intake.IMAGE_LABELS,
                )
            finally:
                os.close(descriptor)
        self.assertEqual(observed["layer_count"], 1)
        self.assertEqual(
            observed["layer_media_types"],
            ["application/vnd.oci.image.layer.v1.tar+gzip"],
        )

    def test_hybrid_inventory_rejects_tag_extra_blob_link_diffid_and_generic_oci(self) -> None:
        mutations = {
            "tag": {"extra_tag": True},
            "extra_blob": {"extra_blob": True},
            "hardlink": {"hardlink": True},
            "diff_id": {"corrupt_diff_id": True},
            "generic_oci": {"omit_oci_layout": True},
            "pax": {"pax_member": True},
            "duplicate": {"duplicate_member": True},
            "regular_trailing_slash": {"regular_trailing_slash": True},
            "manifest_media_mismatch": {"manifest_media_mismatch": True},
            "descriptor_type_confusion": {"descriptor_media_type_confusion": True},
            "concatenated_archive": {"concatenated_archive": True},
            "float_schema_versions": {"float_schema_versions": True},
        }
        for label, options in mutations.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as raw:
                payload, image_id = _docker_save_hybrid(**options)
                path = Path(raw) / "image.tar"
                path.write_bytes(payload)
                descriptor = os.open(path, os.O_RDONLY)
                try:
                    with self.assertRaises(intake.IntakeContractError):
                        intake._validate_docker_save_hybrid(
                            descriptor,
                            expected_image_id=image_id,
                            expected_entrypoint=intake.TENSORRT_ENTRYPOINT,
                            expected_labels=intake.IMAGE_LABELS,
                        )
                finally:
                    os.close(descriptor)

    def test_huge_declared_extended_header_is_rejected_before_tarfile_parser(self) -> None:
        extended = tarfile.TarInfo("synthetic-pax")
        extended.type = tarfile.XHDTYPE
        extended.size = 4 * 1024 * 1024 * 1024
        payload = extended.tobuf(format=tarfile.USTAR_FORMAT) + b"\0" * 1024
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "hostile.tar"
            path.write_bytes(payload)
            descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0))
            try:
                with mock.patch.object(
                    intake.tarfile,
                    "open",
                    side_effect=AssertionError("tarfile parser must not see extended headers"),
                ), self.assertRaises(intake.IntakeContractError):
                    intake._validate_docker_save_hybrid(
                        descriptor,
                        expected_image_id=intake.TENSORRT_IMAGE_ID,
                        expected_entrypoint=intake.TENSORRT_ENTRYPOINT,
                        expected_labels=intake.IMAGE_LABELS,
                    )
            finally:
                os.close(descriptor)

    def test_raw_ustar_preflight_rejects_checksum_base256_and_truncated_payload(self) -> None:
        regular = tarfile.TarInfo("index.json")
        regular.size = 0
        clean_header = bytearray(regular.tobuf(format=tarfile.USTAR_FORMAT))
        bad_checksum = bytearray(clean_header)
        bad_checksum[100] ^= 1
        base256 = bytearray(clean_header)
        base256[124:136] = b"\x80" + b"\0" * 11
        truncated = tarfile.TarInfo("blobs/sha256/" + "a" * 64)
        truncated.size = 4 * 1024 * 1024 * 1024
        payloads = {
            "checksum": bytes(bad_checksum) + b"\0" * 1024,
            "base256": _reseal_ustar_header(base256) + b"\0" * 1024,
            "truncated": truncated.tobuf(format=tarfile.USTAR_FORMAT) + b"\0" * 1024,
        }
        for label, payload in payloads.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as raw:
                path = Path(raw) / "hostile.tar"
                path.write_bytes(payload)
                descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0))
                try:
                    with mock.patch.object(
                        intake.tarfile,
                        "open",
                        side_effect=AssertionError("tarfile parser must follow raw USTAR acceptance"),
                    ), self.assertRaises(intake.IntakeContractError):
                        intake._validate_docker_save_hybrid(
                            descriptor,
                            expected_image_id=intake.TENSORRT_IMAGE_ID,
                            expected_entrypoint=intake.TENSORRT_ENTRYPOINT,
                            expected_labels=intake.IMAGE_LABELS,
                        )
                finally:
                    os.close(descriptor)

    def test_raw_ustar_preflight_rejects_nonzero_member_padding_before_tarfile_parser(self) -> None:
        payload, image_id = _docker_save_hybrid()
        mutated = bytearray(payload)
        offset = 0
        while mutated[offset : offset + tarfile.BLOCKSIZE] != b"\0" * tarfile.BLOCKSIZE:
            header = mutated[offset : offset + tarfile.BLOCKSIZE]
            size = int(header[124:135], 8)
            if size % tarfile.BLOCKSIZE:
                padding_offset = offset + tarfile.BLOCKSIZE + size
                mutated[padding_offset] = 1
                break
            offset += tarfile.BLOCKSIZE + (
                (size + tarfile.BLOCKSIZE - 1) // tarfile.BLOCKSIZE
            ) * tarfile.BLOCKSIZE
        else:
            self.fail("synthetic archive has no member padding to mutate")

        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "nonzero-padding.tar"
            path.write_bytes(mutated)
            descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0))
            try:
                with mock.patch.object(
                    intake.tarfile,
                    "open",
                    side_effect=AssertionError("tarfile parser must not see nonzero padding"),
                ), self.assertRaises(intake.IntakeContractError):
                    intake._validate_docker_save_hybrid(
                        descriptor,
                        expected_image_id=image_id,
                        expected_entrypoint=intake.TENSORRT_ENTRYPOINT,
                        expected_labels=intake.IMAGE_LABELS,
                    )
            finally:
                os.close(descriptor)

    def test_raw_ustar_preflight_rejects_noncanonical_numeric_device_and_checksum_fields(self) -> None:
        regular = tarfile.TarInfo("index.json")
        regular.size = 0
        clean_header = bytearray(regular.tobuf(format=tarfile.USTAR_FORMAT))

        noncanonical_mode = bytearray(clean_header)
        noncanonical_mode[100:108] = b" 000644\0"
        nonzero_device = bytearray(clean_header)
        nonzero_device[329:337] = b"0000001\0"
        noncanonical_checksum = bytearray(clean_header)
        payloads = {
            "space_padded_mode": _reseal_ustar_header(noncanonical_mode),
            "nonzero_device_major": _reseal_ustar_header(nonzero_device),
            "noncanonical_checksum": _reseal_ustar_header(
                noncanonical_checksum,
                canonical=False,
            ),
        }
        for label, header in payloads.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as raw:
                path = Path(raw) / "noncanonical.tar"
                path.write_bytes(header + b"\0" * 1024)
                descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0))
                try:
                    with mock.patch.object(
                        intake.tarfile,
                        "open",
                        side_effect=AssertionError("tarfile parser must not see noncanonical USTAR"),
                    ), self.assertRaises(intake.IntakeContractError):
                        intake._validate_docker_save_hybrid(
                            descriptor,
                            expected_image_id=intake.TENSORRT_IMAGE_ID,
                            expected_entrypoint=intake.TENSORRT_ENTRYPOINT,
                            expected_labels=intake.IMAGE_LABELS,
                        )
                finally:
                    os.close(descriptor)

    def test_raw_ustar_preflight_rejects_duplicate_logical_names_before_tarfile_parser(self) -> None:
        payload, image_id = _docker_save_hybrid(duplicate_member=True)
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "duplicate.tar"
            path.write_bytes(payload)
            descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0))
            try:
                with mock.patch.object(
                    intake.tarfile,
                    "open",
                    side_effect=AssertionError("tarfile parser must not see duplicate names"),
                ), self.assertRaises(intake.IntakeContractError):
                    intake._validate_docker_save_hybrid(
                        descriptor,
                        expected_image_id=image_id,
                        expected_entrypoint=intake.TENSORRT_ENTRYPOINT,
                        expected_labels=intake.IMAGE_LABELS,
                    )
            finally:
                os.close(descriptor)

    def test_normalized_ustar_is_deterministic_and_has_only_fixed_metadata(self) -> None:
        identities: list[intake.FileIdentity] = []
        for reverse, mtime in ((False, 0), (True, 1_700_000_000)):
            payload, image_id = _docker_save_hybrid(
                reverse_member_order=reverse,
                metadata_mtime=mtime,
                gzip_layer=True,
            )
            with tempfile.TemporaryDirectory() as raw:
                path = Path(raw) / "image.tar"
                path.write_bytes(payload)
                descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0))
                try:
                    _inventory, graph = intake._parse_docker_save_hybrid(
                        descriptor,
                        expected_image_id=image_id,
                        expected_entrypoint=intake.TENSORRT_ENTRYPOINT,
                        expected_labels=intake.IMAGE_LABELS,
                    )
                    normalized, identity = intake._normalize_archive(descriptor, graph)
                    try:
                        normalized.seek(0)
                        with tarfile.open(fileobj=normalized, mode="r:") as archive:
                            members = archive.getmembers()
                            self.assertFalse(archive.pax_headers)
                            self.assertEqual(
                                {member.name.rstrip("/") for member in members},
                                {
                                    "blobs",
                                    "blobs/sha256",
                                    "oci-layout",
                                    "index.json",
                                    "manifest.json",
                                    "repositories",
                                    *graph.blob_names,
                                },
                            )
                            for member in members:
                                self.assertEqual((member.uid, member.gid, member.mtime), (0, 0, 0))
                                self.assertEqual(member.pax_headers, {})
                                self.assertEqual(member.mode, 0o555 if member.isdir() else 0o444)
                    finally:
                        normalized.close()
                    identities.append(identity)
                finally:
                    os.close(descriptor)
        self.assertEqual(identities[0], identities[1])

    @unittest.skipUnless(os.name == "posix", "read-only anonymous fd is a POSIX runtime contract")
    def test_normalized_fd_inherited_by_docker_is_read_only(self) -> None:
        payload, image_id = _docker_save_hybrid()
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "image.tar"
            path.write_bytes(payload)
            descriptor = os.open(path, os.O_RDONLY)
            try:
                _inventory, graph = intake._parse_docker_save_hybrid(
                    descriptor,
                    expected_image_id=image_id,
                    expected_entrypoint=intake.TENSORRT_ENTRYPOINT,
                    expected_labels=intake.IMAGE_LABELS,
                )
                normalized, _identity = intake._normalize_archive(descriptor, graph)
                try:
                    with self.assertRaises(OSError):
                        os.write(normalized.fileno(), b"forbidden")
                finally:
                    normalized.close()
            finally:
                os.close(descriptor)

    def test_gzip_diff_hash_enforces_the_remaining_aggregate_budget_during_inflate(self) -> None:
        compressed = gzip.compress(b"x" * 4096, mtime=0)
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode="w", format=tarfile.USTAR_FORMAT) as archive:
            _add_regular(archive, "layer", compressed)
        stream.seek(0)
        with tarfile.open(fileobj=stream, mode="r:") as archive:
            member = archive.getmember("layer")
            with self.assertRaises(intake.IntakeContractError):
                intake._layer_diff_id(
                    archive,
                    member,
                    "application/vnd.oci.image.layer.v1.tar+gzip",
                    remaining_uncompressed_budget=1024,
                )

    def test_archive_identity_mismatch_precedes_every_docker_call_and_output_write(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            archive = root / "image.tar"
            payload = b"synthetic pinned archive"
            archive.write_bytes(payload)
            runner = _FakeDocker()
            dependencies = intake._IntakeDependencies(
                platform_name="posix",
                environment={},
                observe_docker_cli=lambda: intake.FileIdentity(44_986_088, "a" * 64),
                command_runner=runner,
                archive_opener=lambda **_kwargs: _ArchiveSession(
                    size_bytes=len(payload),
                    sha256="f" * 64,
                ),
                canonical_project_root=root,
                local_runtime_guard=lambda: None,
                daemon_lock_factory=lambda _daemon_id: nullcontext(),
            )
            result, code = intake.intake_offline_image(
                project_root=root,
                archive_path=archive,
                expected_archive_size_bytes=len(payload),
                expected_archive_sha256=hashlib.sha256(payload).hexdigest(),
                intake_id="synthetic-intake-v1",
                expected_docker_cli_size_bytes=44_986_088,
                expected_docker_cli_sha256="a" * 64,
                expected_daemon_id="1e493309-3767-45fb-9078-05b838bdfd80",
                expected_daemon_server_version="29.5.3",
                expected_daemon_api_version="1.54",
                _dependencies=dependencies,
            )
            self.assertEqual((code, result["status"]), (78, "blocked_contract_violation"))
            self.assertEqual(runner.calls, [])
            self.assertFalse((root / "runs").exists())

    def test_every_docker_exec_uses_the_same_held_verified_cli_fd(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            archive = root / "image.tar"
            payload = b"synthetic pinned archive"
            archive.write_bytes(payload)
            runner = _FakeDocker()
            cli = _HeldDockerCli()
            dependencies = intake._IntakeDependencies(
                platform_name="posix",
                environment={},
                observe_docker_cli=lambda: cli,
                command_runner=runner,
                archive_opener=lambda **_kwargs: _ArchiveSession(
                    size_bytes=len(payload),
                    sha256=hashlib.sha256(payload).hexdigest(),
                ),
                canonical_project_root=root,
                local_runtime_guard=lambda: None,
                daemon_lock_factory=lambda _daemon_id: _HeldDaemonLease(),
            )
            result, code = intake.intake_offline_image(
                project_root=root,
                archive_path=archive,
                expected_archive_size_bytes=len(payload),
                expected_archive_sha256=hashlib.sha256(payload).hexdigest(),
                intake_id="synthetic-intake-v1",
                expected_docker_cli_size_bytes=44_986_088,
                expected_docker_cli_sha256="a" * 64,
                expected_daemon_id="1e493309-3767-45fb-9078-05b838bdfd80",
                expected_daemon_server_version="29.5.3",
                expected_daemon_api_version="1.54",
                _dependencies=dependencies,
            )
            self.assertEqual((code, result["status"]), (0, "loaded_exact_offline_image"))
            self.assertGreaterEqual(cli.revalidations, 3)
            self.assertTrue(runner.calls)
            self.assertEqual(len(runner.calls), len(runner.executable_overrides))
            for (command, inherited), executable_override in zip(
                runner.calls,
                runner.executable_overrides,
                strict=True,
            ):
                self.assertEqual(command[0], intake.DOCKER_CLI)
                self.assertEqual(executable_override, cli.executable)
                self.assertIn(77, inherited)
            load = next(
                (command, inherited)
                for command, inherited in runner.calls
                if command[3:5] == ("image", "load")
            )
            self.assertEqual(load[1], (77, 91, 88))

    @unittest.skipUnless(
        os.name == "posix"
        and sys.platform.startswith("linux")
        and hasattr(os, "pidfd_open")
        and hasattr(signal, "pidfd_send_signal"),
        "real controller-death daemon-lease proof requires Linux pidfds",
    )
    def test_controller_sigkill_leaves_load_child_holding_the_daemon_lease(self) -> None:
        controller_source = r"""
import sys
sys.path.insert(0, sys.argv[1])
import kpp_legacy_iss_v2_offline_image_intake as intake

child_source = r'''import os, sys, time
descriptor = os.open(sys.argv[1], os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
try:
    os.write(descriptor, str(os.getpid()).encode("ascii"))
    os.fsync(descriptor)
finally:
    os.close(descriptor)
while True:
    time.sleep(60)
'''

with intake._DaemonLock(sys.argv[2]) as lease:
    intake._BoundedCommandRunner().run(
        [sys.executable, "-B", "-c", child_source, sys.argv[3]],
        timeout_seconds=600,
        stdout_limit=1024,
        stderr_limit=1024,
        pass_fds=lease.pass_fds,
    )
"""
        daemon_id = "synthetic-controller-death-daemon"
        with tempfile.TemporaryDirectory() as raw:
            marker = Path(raw) / "load-child.pid"
            controller = subprocess.Popen(
                [
                    sys.executable,
                    "-B",
                    "-c",
                    controller_source,
                    str(SCRIPTS),
                    daemon_id,
                    str(marker),
                ],
                shell=False,
                env={},
                cwd="/",
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                close_fds=True,
                start_new_session=True,
            )
            child_pidfd: int | None = None
            try:
                deadline = time.monotonic() + 10
                while not marker.exists() and time.monotonic() < deadline:
                    if controller.poll() is not None:
                        break
                    time.sleep(0.02)
                if not marker.exists():
                    controller.kill()
                    _stdout, stderr = controller.communicate(timeout=5)
                    self.fail(
                        "synthetic load child did not arm its inherited daemon lease: "
                        + stderr.decode("utf-8", "replace")
                    )
                child_pid = int(marker.read_text("ascii"))
                child_pidfd = os.pidfd_open(child_pid, 0)

                controller.kill()
                controller.wait(timeout=5)
                with self.assertRaises(intake.IntakeContractError):
                    with intake._DaemonLock(daemon_id):
                        pass

                signal.pidfd_send_signal(child_pidfd, signal.SIGKILL)
                lease_released = False
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    try:
                        with intake._DaemonLock(daemon_id):
                            lease_released = True
                        break
                    except intake.IntakeContractError:
                        time.sleep(0.02)
                self.assertTrue(
                    lease_released,
                    "daemon lease remained held after the exact load child died",
                )
            finally:
                if controller.poll() is None:
                    controller.kill()
                try:
                    controller.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    controller.kill()
                    controller.communicate(timeout=5)
                if child_pidfd is not None:
                    try:
                        signal.pidfd_send_signal(child_pidfd, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    os.close(child_pidfd)

    def test_legacy_image_store_is_rejected_before_catalog_or_load(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            archive = root / "image.tar"
            archive.write_bytes(b"synthetic pinned archive")
            runner = _FakeDocker(containerd_snapshotter=False)
            result, code = self._invoke(root, archive, runner)
            self.assertEqual((code, result["status"]), (78, "blocked_contract_violation"))
            self.assertIn("containerd snapshotter", result["message"])
            self.assertFalse(runner.load_attempted)
            self.assertFalse(
                any(
                    command[3:8]
                    == ("image", "ls", "--all", "--no-trunc", "--quiet")
                    for command, _fds in runner.calls
                )
            )
            self.assertFalse((root / "runs").exists())

    def test_preexisting_exact_image_is_classified_without_load_or_writes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            archive = root / "image.tar"
            archive.write_bytes(b"synthetic pinned archive")
            runner = _FakeDocker(preexisting=True)
            result, code = self._invoke(root, archive, runner)
            self.assertEqual((code, result["status"]), (78, "blocked_preexisting_exact_image"))
            self.assertFalse(any(command[3:5] == ("image", "load") for command, _fds in runner.calls))
            self.assertFalse((root / "runs").exists())

    def test_success_uses_only_exact_load_command_and_writes_fence_then_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            archive = root / "image.tar"
            archive.write_bytes(b"synthetic pinned archive")
            runner = _FakeDocker()
            result, code = self._invoke(root, archive, runner)
            self.assertEqual((code, result["status"]), (0, "loaded_exact_offline_image"))
            self.assertEqual(
                result["request"]["daemon"]["image_store_driver_type"],
                "io.containerd.snapshotter.v1",
            )
            load_calls = [item for item in runner.calls if item[0][3:5] == ("image", "load")]
            self.assertEqual(
                load_calls,
                [
                    (
                        (
                            intake.DOCKER_CLI,
                            intake.DOCKER_HOST_FLAG,
                            intake.DOCKER_HOST_VALUE,
                            "image",
                            "load",
                            "--quiet",
                            "--platform=linux/amd64",
                            "--input",
                            "/proc/self/fd/91",
                        ),
                        (91,),
                    )
                ],
            )
            self.assertTrue(
                all(str(archive) not in token for command, _fds in load_calls for token in command)
            )
            output = self._output(root)
            self.assertTrue((output / intake.FENCE_NAME).is_file())
            self.assertTrue((output / intake.ATTEMPT_NAME).is_file())
            self.assertTrue((output / intake.RECEIPT_NAME).is_file())
            attempt = json.loads((output / intake.ATTEMPT_NAME).read_text("ascii"))
            self.assertTrue(attempt["marker_committed_before_load_command_invocation"])
            self.assertTrue(
                attempt["absence_of_matching_receipt_requires_load_outcome_unknown"]
            )
            for field in intake.LOAD_FACT_FIELDS:
                self.assertNotIn(field, attempt)
            receipt = json.loads((output / intake.RECEIPT_NAME).read_text("ascii"))
            for field in intake.FALSE_CLAIM_FIELDS:
                self.assertIs(receipt[field], False)
            self.assertTrue(receipt["load_command_start_possible_historically"])
            self.assertTrue(receipt["load_command_start_observed_during_this_invocation"])
            self.assertTrue(receipt["load_command_return_observed_during_this_invocation"])
            self.assertTrue(receipt["exact_expected_image_effect_observed"])
            self.assertTrue(receipt["historical_load_command_outcome_known"])
            self.assertTrue(receipt["bounded_command_and_exact_effect_correlation_observed"])
            self.assertFalse(receipt["effect_causally_attributed_to_this_intake"])
            self.assertNotIn("docker_image_load_performed", receipt)
            self.assertNotIn("recovered_exact_image_after_interrupted_attempt", receipt)
            self.assertNotIn("prior_successful_return_attested", receipt)
            self.assertFalse(receipt["network_performed"])
            self.assertFalse(receipt["docker_pull_performed"])
            self.assertFalse(receipt["docker_build_performed"])
            self.assertFalse(receipt["docker_import_performed"])

    def test_docker29_tagless_loaded_image_id_line_is_exact_success_output(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            archive = root / "image.tar"
            archive.write_bytes(b"synthetic pinned archive")
            load_stdout = (
                f"Loaded image ID: {intake.TENSORRT_IMAGE_ID}\n".encode("ascii")
            )
            runner = _FakeDocker(load_stdout=load_stdout)
            result, code = self._invoke(root, archive, runner)
            self.assertEqual((code, result["status"]), (0, "loaded_exact_offline_image"))
            self.assertTrue(runner.load_attempted)
            self.assertTrue((self._output(root) / intake.RECEIPT_NAME).is_file())

    def test_unexpected_load_capture_is_hashed_and_sanitized_on_failure(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            archive = root / "image.tar"
            archive.write_bytes(b"synthetic pinned archive")
            load_stdout = b"synthetic unexpected load output\n"
            load_stderr = b"synthetic warning\n"
            runner = _FakeDocker(
                load_stdout=load_stdout,
                load_stderr=load_stderr,
            )
            result, code = self._invoke(root, archive, runner)
            self.assertEqual(
                (code, result["status"]),
                (78, "blocked_load_failed_with_daemon_mutation"),
            )
            self.assertEqual(
                result["load_capture"],
                {
                    "capture_observed": True,
                    "runner_error_type": None,
                    "returncode": 0,
                    "timed_out": False,
                    "stdout_overflow": False,
                    "stderr_overflow": False,
                    "stdout_size_bytes": len(load_stdout),
                    "stdout_sha256": hashlib.sha256(load_stdout).hexdigest(),
                    "stdout_sanitized_ascii": "synthetic unexpected load output\\n",
                    "stdout_sanitized_ascii_omitted": False,
                    "stderr_size_bytes": len(load_stderr),
                    "stderr_sha256": hashlib.sha256(load_stderr).hexdigest(),
                    "stderr_sanitized_ascii": "synthetic warning\\n",
                    "stderr_sanitized_ascii_omitted": False,
                },
            )
            output = self._output(root)
            fence = json.loads((output / intake.FENCE_NAME).read_text("ascii"))
            attempt = json.loads((output / intake.ATTEMPT_NAME).read_text("ascii"))
            self.assertEqual(result["fence_sha256"], fence["fence_sha256"])
            self.assertEqual(result["attempt_sha256"], attempt["attempt_sha256"])

    def test_load_capture_diagnostics_omit_nonascii_large_or_partial_text(self) -> None:
        captures = (
            intake.CommandCapture(1, b"\x00", b""),
            intake.CommandCapture(
                1,
                b"a" * (intake._MAX_SANITIZED_CAPTURE_BYTES + 1),
                b"",
            ),
            intake.CommandCapture(1, b"partial", b"", stdout_overflow=True),
        )
        for capture in captures:
            with self.subTest(capture=capture):
                facts = intake._load_capture_facts(capture, None)
                self.assertTrue(facts["capture_observed"])
                self.assertIsNone(facts["stdout_sanitized_ascii"])
                self.assertTrue(facts["stdout_sanitized_ascii_omitted"])
                self.assertEqual(facts["stdout_size_bytes"], len(capture.stdout))
                self.assertEqual(
                    facts["stdout_sha256"],
                    hashlib.sha256(capture.stdout).hexdigest(),
                )
        no_capture = intake._load_capture_facts(None, OSError("synthetic"))
        self.assertEqual(
            no_capture,
            {
                "capture_observed": False,
                "runner_error_type": "OSError",
                "returncode": None,
                "timed_out": None,
                "stdout_overflow": None,
                "stderr_overflow": None,
                "stdout_size_bytes": None,
                "stdout_sha256": None,
                "stdout_sanitized_ascii": None,
                "stdout_sanitized_ascii_omitted": True,
                "stderr_size_bytes": None,
                "stderr_sha256": None,
                "stderr_sanitized_ascii": None,
                "stderr_sanitized_ascii_omitted": True,
            },
        )
        with self.assertRaises(intake.IntakeContractError):
            intake._load_capture_facts(
                intake.CommandCapture(False, b"", b""),
                None,
            )

    def test_docker29_load_confirmation_near_misses_are_never_success(self) -> None:
        exact = f"Loaded image ID: {intake.TENSORRT_IMAGE_ID}\n".encode("ascii")
        wrong_id = "sha256:" + ("0" * 64)
        near_misses = (
            f"Loaded image ID: {wrong_id}\n".encode("ascii"),
            f"Loaded image: {intake.TENSORRT_IMAGE_ID}\n".encode("ascii"),
            exact + b"unexpected\n",
            exact[:-1] + b"\r\n",
            exact[:-1],
            b" " + exact,
        )
        for load_stdout in near_misses:
            with self.subTest(load_stdout=load_stdout), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                archive = root / "image.tar"
                archive.write_bytes(b"synthetic pinned archive")
                runner = _FakeDocker(load_stdout=load_stdout)
                result, code = self._invoke(root, archive, runner)
                self.assertEqual(
                    (code, result["status"]),
                    (78, "blocked_load_failed_with_daemon_mutation"),
                )
                self.assertTrue(runner.load_attempted)
                self.assertFalse(
                    (self._output(root) / intake.RECEIPT_NAME).exists()
                )

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            archive = root / "image.tar"
            archive.write_bytes(b"synthetic pinned archive")
            runner = _FakeDocker(load_stdout=exact, load_stderr=b"warning\n")
            result, code = self._invoke(root, archive, runner)
            self.assertEqual(
                (code, result["status"]),
                (78, "blocked_load_failed_with_daemon_mutation"),
            )

    def test_fence_namespace_and_artifacts_publish_without_hardlink_crash_windows(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            path = root / "artifact.json"
            with mock.patch.object(os, "link", side_effect=AssertionError("hardlink forbidden")):
                intake._write_create_new(path, {"synthetic": True})
            self.assertEqual(path.read_bytes(), intake.canonical_line({"synthetic": True}))

            archive = root / "image.tar"
            archive.write_bytes(b"synthetic pinned archive")
            runner = _FakeDocker()
            result, code = self._invoke(
                root,
                archive,
                runner,
                output_namespace_factory=lambda project, namespace: _FailingOutputNamespace(
                    intake._open_output_namespace(project, namespace),
                    fail_method="create_fence",
                ),
            )
            self.assertEqual((code, result["status"]), (78, "blocked_contract_violation"))
            output = self._output(root)
            self.assertFalse(output.exists())
            self.assertFalse(any(command[3:5] == ("image", "load") for command, _fds in runner.calls))

    def test_post_load_receipt_failure_retains_exact_rc0_operational_facts(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            archive = root / "image.tar"
            archive.write_bytes(b"synthetic pinned archive")
            runner = _FakeDocker()
            result, code = self._invoke(
                root,
                archive,
                runner,
                output_namespace_factory=lambda project, namespace: _FailingOutputNamespace(
                    intake._open_output_namespace(project, namespace),
                    fail_method="create_receipt",
                ),
            )
            self.assertEqual((code, result["status"]), (78, "blocked_contract_violation"))
            self.assertTrue(result["load_command_start_possible_historically"])
            self.assertTrue(result["load_command_start_observed_during_this_invocation"])
            self.assertTrue(result["load_command_return_observed_during_this_invocation"])
            self.assertTrue(result["exact_expected_image_effect_observed"])
            self.assertTrue(result["historical_load_command_outcome_known"])
            self.assertTrue(result["bounded_command_and_exact_effect_correlation_observed"])
            self.assertFalse(result["effect_causally_attributed_to_this_intake"])

    def test_attempt_commit_failure_never_claims_load_start_impossible(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            archive = root / "image.tar"
            archive.write_bytes(b"synthetic pinned archive")
            runner = _FakeDocker()
            result, code = self._invoke(
                root,
                archive,
                runner,
                output_namespace_factory=lambda project, namespace: _FailingOutputNamespace(
                    intake._open_output_namespace(project, namespace),
                    fail_method="create_attempt",
                ),
            )
            self.assertEqual((code, result["status"]), (78, "blocked_contract_violation"))
            self.assertTrue(result["load_command_start_possible_historically"])
            self.assertFalse(result["load_command_start_observed_during_this_invocation"])
            self.assertFalse(result["load_command_return_observed_during_this_invocation"])
            self.assertFalse(result["historical_load_command_outcome_known"])
            self.assertFalse(any(command[3:5] == ("image", "load") for command, _fds in runner.calls))

    def test_unreadable_global_ledger_uses_conservative_historical_load_facts(self) -> None:
        class UnreadableLedger:
            def __enter__(self):
                raise intake.IntakeContractError("synthetic unreadable global ledger")

            def __exit__(self, *_args: object) -> None:
                return None

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            archive = root / "image.tar"
            archive.write_bytes(b"synthetic pinned archive")
            runner = _FakeDocker()
            result, code = self._invoke(
                root,
                archive,
                runner,
                output_namespace_factory=lambda _project, _namespace: UnreadableLedger(),
            )
            self.assertEqual((code, result["status"]), (78, "blocked_contract_violation"))
            self.assertTrue(result["load_command_start_possible_historically"])
            self.assertFalse(result["historical_load_command_outcome_known"])
            self.assertEqual(runner.calls, [])

    def test_nonzero_load_with_visible_image_is_partial_and_never_receipted(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            archive = root / "image.tar"
            archive.write_bytes(b"synthetic pinned archive")
            runner = _FakeDocker(load_returncode=1, visible_after_failure=True)
            result, code = self._invoke(root, archive, runner)
            self.assertEqual(
                (code, result["status"]),
                (78, "blocked_load_failed_with_daemon_mutation"),
            )
            output = self._output(root)
            self.assertTrue((output / intake.FENCE_NAME).is_file())
            self.assertFalse((output / intake.RECEIPT_NAME).exists())

    def test_success_return_with_unexpected_extra_image_is_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            archive = root / "image.tar"
            archive.write_bytes(b"synthetic pinned archive")
            runner = _FakeDocker(extra_after_load=True)
            result, code = self._invoke(root, archive, runner)
            self.assertEqual(
                (code, result["status"]),
                (78, "blocked_unexpected_daemon_image_delta"),
            )
            output = self._output(root)
            self.assertTrue((output / intake.FENCE_NAME).is_file())
            self.assertFalse((output / intake.RECEIPT_NAME).exists())

    def test_preexisting_projection_container_and_loaded_tag_drift_are_each_blocked(self) -> None:
        scenarios = {
            "preexisting_projection": _FakeDocker(
                preexisting_other=True,
                mutate_preexisting_after_load=True,
            ),
            "container": _FakeDocker(add_container_after_load=True),
            "loaded_tag": _FakeDocker(target_tag_after_load=True),
        }
        for label, runner in scenarios.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                archive = root / "image.tar"
                archive.write_bytes(b"synthetic pinned archive")
                result, code = self._invoke(root, archive, runner)
                self.assertEqual(
                    (code, result["status"]),
                    (78, "blocked_unexpected_daemon_image_delta"),
                )
                receipt = self._output(root) / intake.RECEIPT_NAME
                self.assertFalse(receipt.exists())

    def test_daemon_catalog_count_bound_precedes_fence_and_load(self) -> None:
        class TooManyImages(_FakeDocker):
            def run(self, argv, **kwargs):
                command = tuple(argv)
                if command[3:8] == ("image", "ls", "--all", "--no-trunc", "--quiet"):
                    self.calls.append((command, kwargs.get("pass_fds", ())))
                    payload = b"".join(
                        ("sha256:" + f"{index:064x}" + "\n").encode("ascii")
                        for index in range(intake._MAX_DAEMON_IMAGES + 1)
                    )
                    return intake.CommandCapture(0, payload, b"")
                return super().run(argv, **kwargs)

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            archive = root / "image.tar"
            archive.write_bytes(b"synthetic pinned archive")
            runner = TooManyImages()
            result, code = self._invoke(root, archive, runner)
            self.assertEqual((code, result["status"]), (78, "blocked_contract_violation"))
            self.assertFalse((root / "runs").exists())
            self.assertFalse(any(command[3:5] == ("image", "load") for command, _fds in runner.calls))

    def test_worst_case_loaded_receipt_size_is_bounded_before_load(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            archive = root / "image.tar"
            payload = b"synthetic pinned archive"
            archive.write_bytes(payload)
            session = _ArchiveSession(
                size_bytes=len(payload),
                sha256=hashlib.sha256(payload).hexdigest(),
            )
            daemon = {
                "daemon_id": "1e493309-3767-45fb-9078-05b838bdfd80",
                "server_version": "29.5.3",
                "api_version": "1.54",
                "os": "linux",
                "architecture": "amd64",
            }
            request = intake._request_core(
                intake_id="synthetic-intake-v1",
                durable_namespace_id=intake._durable_operation_namespace_id(
                    self._DAEMON_ID
                ),
                archive_path=archive,
                session=session,
                docker_cli=intake.FileIdentity(44_986_088, "a" * 64),
                daemon=daemon,
            )
            request_sha = intake._identity(intake._OPERATION_DOMAIN, request)
            baseline_core = {"images": [], "container_ids": []}
            baseline = {
                **baseline_core,
                "catalog_sha256": intake._identity(
                    intake._CATALOG_DOMAIN,
                    baseline_core,
                ),
            }
            operation_sha = intake._identity(
                intake._OPERATION_DOMAIN,
                {
                    "request_sha256": request_sha,
                    "baseline_catalog_sha256": baseline["catalog_sha256"],
                },
            )
            fence = intake._seal(
                {
                    "schema_version": 1,
                    "artifact_kind": "kpp_legacy_iss_v2_offline_image_intake_fence",
                    "state": "prepared",
                    "request": request,
                    "request_sha256": request_sha,
                    "operation_sha256": operation_sha,
                    "baseline_catalog": baseline,
                },
                domain=intake._FENCE_DOMAIN,
                hash_field="fence_sha256",
            )
            post = intake._project_exact_post_catalog(baseline)
            loaded_initial = intake._receipt(
                status="loaded_exact_offline_image",
                request=request,
                request_sha256=request_sha,
                operation_sha256=operation_sha,
                fence_sha256=fence["fence_sha256"],
                baseline=baseline,
                post_catalog=post,
                attempt_sha256="0" * 64,
            )
            loaded_retry = intake._receipt(
                status="loaded_exact_offline_image_after_matching_fence_retry",
                request=request,
                request_sha256=request_sha,
                operation_sha256=operation_sha,
                fence_sha256=fence["fence_sha256"],
                baseline=baseline,
                post_catalog=post,
                attempt_sha256="0" * 64,
            )
            initial_size = len(intake.canonical_line(loaded_initial))
            self.assertGreater(len(intake.canonical_line(loaded_retry)), initial_size)
            runner = _FakeDocker()
            class SyntheticCrash(BaseException):
                pass

            def crash_after_fence(stage: str) -> None:
                if stage == "after_fence_before_load":
                    raise SyntheticCrash(stage)

            with self.assertRaises(SyntheticCrash):
                self._invoke(
                    root,
                    archive,
                    runner,
                    lifecycle_hook=crash_after_fence,
                )
            self.assertFalse(runner.load_attempted)
            with mock.patch.object(intake, "_MAX_JSON_BYTES", initial_size):
                result, code = self._invoke(root, archive, runner)
            self.assertEqual((code, result["status"]), (78, "blocked_contract_violation"))
            self.assertFalse(runner.load_attempted)
            self.assertFalse(
                (
                    self._output(root)
                    / intake.RECEIPT_NAME
                ).exists()
            )

    def test_runner_loss_after_daemon_mutation_is_recoverable_but_not_successful(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            archive = root / "image.tar"
            archive.write_bytes(b"synthetic pinned archive")
            runner = _FakeDocker(raise_after_load_mutation=True)
            first, first_code = self._invoke(root, archive, runner)
            self.assertEqual(
                (first_code, first["status"]),
                (78, "blocked_load_failed_with_daemon_mutation"),
            )
            self.assertTrue(first["load_command_start_possible_historically"])
            self.assertFalse(first["load_command_start_observed_during_this_invocation"])
            self.assertFalse(first["load_command_return_observed_during_this_invocation"])
            self.assertTrue(first["exact_expected_image_effect_observed"])
            self.assertFalse(first["historical_load_command_outcome_known"])
            self.assertFalse(first["effect_causally_attributed_to_this_intake"])
            runner.raise_after_load_mutation = False
            second, second_code = self._invoke(root, archive, runner)
            self.assertEqual(
                (second_code, second["status"]),
                (
                    78,
                    "blocked_exact_image_observed_after_prior_load_attempt_without_receipted_success",
                ),
            )

    def test_timeout_after_visible_mutation_never_receipts_on_that_invocation(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            archive = root / "image.tar"
            archive.write_bytes(b"synthetic pinned archive")
            runner = _FakeDocker(timed_out_after_load=True)
            result, code = self._invoke(root, archive, runner)
            self.assertEqual(
                (code, result["status"]),
                (78, "blocked_load_failed_with_daemon_mutation"),
            )
            receipt = (
                self._output(root)
                / intake.RECEIPT_NAME
            )
            self.assertFalse(receipt.exists())

    def test_timeout_without_visible_mutation_keeps_load_outcome_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            archive = root / "image.tar"
            archive.write_bytes(b"synthetic pinned archive")
            runner = _FakeDocker(load_returncode=1, timed_out_after_load=True)
            result, code = self._invoke(root, archive, runner)
            self.assertEqual(
                (code, result["status"]),
                (78, "blocked_docker_image_load_failed_without_visible_image"),
            )
            self.assertTrue(result["load_command_start_possible_historically"])
            self.assertTrue(result["load_command_start_observed_during_this_invocation"])
            self.assertTrue(result["load_command_return_observed_during_this_invocation"])
            self.assertFalse(result["exact_expected_image_effect_observed"])
            self.assertFalse(result["historical_load_command_outcome_known"])
            self.assertFalse(result["effect_causally_attributed_to_this_intake"])

    def test_started_attempt_with_unchanged_catalog_refuses_automatic_second_load(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            archive = root / "image.tar"
            archive.write_bytes(b"synthetic pinned archive")
            runner = _FakeDocker(load_returncode=1)
            first, first_code = self._invoke(root, archive, runner)
            self.assertEqual(
                (first_code, first["status"]),
                (78, "blocked_docker_image_load_failed_without_visible_image"),
            )
            self.assertFalse(first["historical_load_command_outcome_known"])
            runner.load_returncode = 0
            second, second_code = self._invoke(root, archive, runner)
            self.assertEqual(
                (second_code, second["status"]),
                (78, "blocked_prior_load_attempt_outcome_unknown"),
            )
            self.assertTrue(second["load_command_start_possible_historically"])
            self.assertFalse(second["load_command_start_observed_during_this_invocation"])
            self.assertFalse(second["load_command_return_observed_during_this_invocation"])
            self.assertFalse(second["historical_load_command_outcome_known"])
            load_calls = [
                command
                for command, _fds in runner.calls
                if command[3:5] == ("image", "load")
            ]
            self.assertEqual(len(load_calls), 1)

    def test_changed_intake_id_and_archive_cannot_bypass_global_target_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            first_archive = root / "first-image.tar"
            first_archive.write_bytes(b"synthetic pinned archive A")
            runner = _FakeDocker(load_returncode=1)
            first, first_code = self._invoke(
                root,
                first_archive,
                runner,
                intake_id="caller-label-a",
            )
            self.assertEqual(
                (first_code, first["status"]),
                (78, "blocked_docker_image_load_failed_without_visible_image"),
            )
            second_archive = root / "second-image.tar"
            second_archive.write_bytes(b"synthetic pinned archive B")
            runner.load_returncode = 0
            second, second_code = self._invoke(
                root,
                second_archive,
                runner,
                intake_id="caller-label-b",
            )
            self.assertEqual(
                (second_code, second["status"]),
                (78, "blocked_contract_violation"),
            )
            self.assertTrue(second["load_command_start_possible_historically"])
            self.assertFalse(second["historical_load_command_outcome_known"])
            load_calls = [
                command
                for command, _fds in runner.calls
                if command[3:5] == ("image", "load")
            ]
            self.assertEqual(len(load_calls), 1)

    def test_archive_validation_failure_conservatively_preserves_prior_global_attempt_facts(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            archive = root / "image.tar"
            archive.write_bytes(b"synthetic pinned archive")
            runner = _FakeDocker(load_returncode=1)
            first, first_code = self._invoke(root, archive, runner)
            self.assertEqual(
                (first_code, first["status"]),
                (78, "blocked_docker_image_load_failed_without_visible_image"),
            )

            def reject_archive(**_kwargs):
                raise intake.IntakeContractError("synthetic archive parser rejection")

            second, second_code = self._invoke(
                root,
                archive,
                runner,
                archive_opener=reject_archive,
            )
            self.assertEqual(
                (second_code, second["status"]),
                (78, "blocked_contract_violation"),
            )
            self.assertTrue(second["load_command_start_possible_historically"])
            self.assertFalse(second["historical_load_command_outcome_known"])
            load_calls = [
                command
                for command, _fds in runner.calls
                if command[3:5] == ("image", "load")
            ]
            self.assertEqual(len(load_calls), 1)

    def test_changed_project_root_cannot_bypass_global_target_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            first_root = base / "project-a"
            second_root = base / "project-b"
            state_root = base / "per-user-state"
            first_root.mkdir()
            second_root.mkdir()
            state_root.mkdir()
            global_namespace_factory = (
                lambda _selected_project_root, namespace: intake._PathOutputNamespace(
                    state_root,
                    namespace,
                )
            )
            archive = base / "image.tar"
            archive.write_bytes(b"synthetic pinned archive")
            runner = _FakeDocker(load_returncode=1)
            first, first_code = self._invoke(
                first_root,
                archive,
                runner,
                output_namespace_factory=global_namespace_factory,
                canonical_project_root=first_root,
            )
            self.assertEqual(
                (first_code, first["status"]),
                (78, "blocked_docker_image_load_failed_without_visible_image"),
            )
            runner.load_returncode = 0
            second, second_code = self._invoke(
                second_root,
                archive,
                runner,
                output_namespace_factory=global_namespace_factory,
                canonical_project_root=second_root,
            )
            self.assertEqual(
                (second_code, second["status"]),
                (78, "blocked_prior_load_attempt_outcome_unknown"),
            )
            load_calls = [
                command
                for command, _fds in runner.calls
                if command[3:5] == ("image", "load")
            ]
            self.assertEqual(len(load_calls), 1)

    def test_matching_fence_observes_exact_image_but_never_adopts_it_as_intake_success(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            archive = root / "image.tar"
            archive.write_bytes(b"synthetic pinned archive")
            runner = _FakeDocker(load_returncode=1, visible_after_failure=True)
            first, first_code = self._invoke(root, archive, runner)
            self.assertEqual(
                (first_code, first["status"]),
                (78, "blocked_load_failed_with_daemon_mutation"),
            )
            before = sum(
                command[3:5] == ("image", "load")
                for command, _fds in runner.calls
            )
            second, second_code = self._invoke(root, archive, runner)
            self.assertEqual(
                (second_code, second["status"]),
                (
                    78,
                    "blocked_exact_image_observed_after_prior_load_attempt_without_receipted_success",
                ),
            )
            after = sum(
                command[3:5] == ("image", "load")
                for command, _fds in runner.calls
            )
            self.assertEqual(after, before)
            self.assertTrue(second["load_command_start_possible_historically"])
            self.assertFalse(second["load_command_start_observed_during_this_invocation"])
            self.assertFalse(second["load_command_return_observed_during_this_invocation"])
            self.assertTrue(second["exact_expected_image_effect_observed"])
            self.assertFalse(second["historical_load_command_outcome_known"])
            self.assertFalse(second["effect_causally_attributed_to_this_intake"])
            self.assertFalse(second["docker_image_remove_performed"])
            self.assertFalse(second["daemon_cleanup_performed"])
            self.assertFalse(second["rollback_performed"])

    def test_exact_image_fail_closed_revalidation_uses_noncausal_classification_wording(self) -> None:
        class DriftOnSecondFenceRead:
            def __init__(self, inner) -> None:
                self._inner = inner
                self._reads = 0

            def __enter__(self):
                self._inner.__enter__()
                return self

            def __exit__(self, *args: object) -> None:
                return self._inner.__exit__(*args)

            def __getattr__(self, name: str):
                return getattr(self._inner, name)

            def read_fence(self):
                value = self._inner.read_fence()
                self._reads += 1
                if self._reads == 2:
                    return {**value, "state": "synthetic-drift"}
                return value

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            archive = root / "image.tar"
            archive.write_bytes(b"synthetic pinned archive")
            runner = _FakeDocker(load_returncode=1, visible_after_failure=True)
            first, first_code = self._invoke(root, archive, runner)
            self.assertEqual(
                (first_code, first["status"]),
                (78, "blocked_load_failed_with_daemon_mutation"),
            )
            load_calls_before = sum(
                command[3:5] == ("image", "load")
                for command, _fds in runner.calls
            )
            second, second_code = self._invoke(
                root,
                archive,
                runner,
                output_namespace_factory=lambda project, namespace: DriftOnSecondFenceRead(
                    intake._open_output_namespace(project, namespace)
                ),
            )
            self.assertEqual(
                (second_code, second["status"]),
                (78, "blocked_contract_violation"),
            )
            self.assertEqual(
                second["message"],
                "durable fence or load-attempt marker drifted before fail-closed exact-image classification",
            )
            self.assertEqual(
                sum(
                    command[3:5] == ("image", "load")
                    for command, _fds in runner.calls
                ),
                load_calls_before,
            )

    def test_fence_only_external_exact_image_is_observed_but_not_adopted(self) -> None:
        class SyntheticCrash(BaseException):
            pass

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            archive = root / "image.tar"
            archive.write_bytes(b"synthetic pinned archive")
            runner = _FakeDocker()

            def crash_after_fence(stage: str) -> None:
                if stage == "after_fence_before_load":
                    raise SyntheticCrash(stage)

            with self.assertRaises(SyntheticCrash):
                self._invoke(root, archive, runner, lifecycle_hook=crash_after_fence)
            runner.loaded = True
            before = sum(
                command[3:5] == ("image", "load")
                for command, _fds in runner.calls
            )
            result, code = self._invoke(root, archive, runner)
            after = sum(
                command[3:5] == ("image", "load")
                for command, _fds in runner.calls
            )
            self.assertEqual(
                (code, result["status"]),
                (
                    78,
                    "blocked_exact_image_observed_after_prepared_fence_without_load_causality",
                ),
            )
            self.assertEqual(after, before)
            self.assertIsNone(result["load_attempt_sha256"])
            self.assertFalse(result["load_command_start_possible_historically"])
            self.assertFalse(result["load_command_start_observed_during_this_invocation"])
            self.assertFalse(result["load_command_return_observed_during_this_invocation"])
            self.assertTrue(result["exact_expected_image_effect_observed"])
            self.assertFalse(result["historical_load_command_outcome_known"])
            self.assertFalse(result["effect_causally_attributed_to_this_intake"])
            self.assertFalse((self._output(root) / intake.RECEIPT_NAME).exists())

    def test_matching_receipt_is_idempotent_read_only_success(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            archive = root / "image.tar"
            archive.write_bytes(b"synthetic pinned archive")
            runner = _FakeDocker()
            first, first_code = self._invoke(root, archive, runner)
            self.assertEqual(first_code, 0)
            before = len(runner.calls)
            second, second_code = self._invoke(root, archive, runner)
            self.assertEqual(
                (second_code, second["status"]),
                (0, "already_loaded_by_matching_offline_intake_receipt"),
            )
            replay_calls = runner.calls[before:]
            self.assertFalse(
                any(command[3:5] == ("image", "load") for command, _fds in replay_calls)
            )

    def test_three_crash_boundaries_converge_without_an_unowned_second_load(self) -> None:
        class SyntheticCrash(BaseException):
            pass

        for stage in (
            "after_fence_before_load",
            "after_attempt_before_load",
            "after_load_before_postflight",
            "after_postflight_before_receipt",
        ):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                archive = root / "image.tar"
                archive.write_bytes(b"synthetic pinned archive")
                runner = _FakeDocker()

                def crash(observed: str) -> None:
                    if observed == stage:
                        raise SyntheticCrash(stage)

                with self.assertRaises(SyntheticCrash):
                    self._invoke(root, archive, runner, lifecycle_hook=crash)
                output = (
                    self._output(root)
                )
                self.assertTrue((output / intake.FENCE_NAME).is_file())
                self.assertFalse((output / intake.RECEIPT_NAME).exists())
                load_count_before = sum(
                    command[3:5] == ("image", "load")
                    for command, _fds in runner.calls
                )
                result, code = self._invoke(root, archive, runner)
                load_count_after = sum(
                    command[3:5] == ("image", "load")
                    for command, _fds in runner.calls
                )
                if stage == "after_fence_before_load":
                    self.assertEqual(code, 0)
                    self.assertEqual(result["status"], "loaded_exact_offline_image_after_matching_fence_retry")
                    self.assertEqual((load_count_before, load_count_after), (0, 1))
                elif stage == "after_attempt_before_load":
                    self.assertEqual(code, 78)
                    self.assertEqual(result["status"], "blocked_prior_load_attempt_outcome_unknown")
                    self.assertEqual((load_count_before, load_count_after), (0, 0))
                else:
                    self.assertEqual(code, 78)
                    self.assertEqual(
                        result["status"],
                        "blocked_exact_image_observed_after_prior_load_attempt_without_receipted_success",
                    )
                    self.assertEqual(load_count_after, load_count_before)

    def test_tampered_receipt_blocks_idempotent_replay(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            archive = root / "image.tar"
            archive.write_bytes(b"synthetic pinned archive")
            runner = _FakeDocker()
            _result, code = self._invoke(root, archive, runner)
            self.assertEqual(code, 0)
            receipt_path = (
                self._output(root)
                / intake.RECEIPT_NAME
            )
            receipt = json.loads(receipt_path.read_text("ascii"))
            receipt["status"] = "forged-success"
            receipt_path.write_bytes(_canonical(receipt) + b"\n")
            replay, replay_code = self._invoke(root, archive, runner)
            self.assertEqual(
                (replay_code, replay["status"]),
                (78, "blocked_contract_violation"),
            )

    def test_resealed_receipt_cross_binding_drift_is_rejected(self) -> None:
        mutations = {
            "baseline": lambda receipt: receipt.__setitem__(
                "baseline_catalog", receipt["post_catalog"]
            ),
            "archive_hash": lambda receipt: receipt.__setitem__(
                "archive_inventory_sha256", "e" * 64
            ),
            "status_flags": lambda receipt: receipt.__setitem__(
                "status", "recovered_exact_image_after_interrupted_attempt"
            ),
            "schema_float": lambda receipt: receipt.__setitem__(
                "schema_version", 1.0
            ),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                archive = root / "image.tar"
                archive.write_bytes(b"synthetic pinned archive")
                runner = _FakeDocker()
                _result, code = self._invoke(root, archive, runner)
                self.assertEqual(code, 0)
                receipt_path = (
                    self._output(root)
                    / intake.RECEIPT_NAME
                )
                receipt = json.loads(receipt_path.read_text("ascii"))
                mutate(receipt)
                receipt.pop("receipt_sha256")
                receipt["receipt_sha256"] = intake._identity(
                    intake._RECEIPT_DOMAIN,
                    receipt,
                )
                receipt_path.write_bytes(intake.canonical_line(receipt))
                replay, replay_code = self._invoke(root, archive, runner)
                self.assertEqual(
                    (replay_code, replay["status"]),
                    (78, "blocked_contract_violation"),
                )


if __name__ == "__main__":
    unittest.main()
