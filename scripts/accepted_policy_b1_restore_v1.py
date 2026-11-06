"""B1 restore: export the pinned DeepStream base from Docker Desktop and import it
into native containerd, exactly as reviewed in B1-assessment.md and design.md
("B1 restore", split engine route).

One invocation, one absolute deadline, no retry. Desktop is only read. Nothing
is pruned, removed or overwritten; on any refusal or failure the partial state
(archive, ingest, record) is retained and the run stops. Run as root, under the
containment guard:

    accepted_policy_containment_guard_v1.py --phase b1-restore --record R1 -- \
        python3 accepted_policy_b1_restore_v1.py --record R2

A later attempt after a consumed one may reuse the retained archive instead of
saving again (``--reuse-archive-sha256 HEX --reuse-archive-size BYTES``): only the
save is skipped; the archive is opened read-only, must be the only entry in the
archive directory, must match the recorded size and sha256, and is re-verified in
full. Read-only snapshots of containerd's active ingests and leases are recorded
in preflight and again immediately before the import.

Exit codes: 0 restored and verified; 3 refused or failed (see the record);
4 the record could not be written (it is emitted on stderr).
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import signal
import socket
import stat as stat_mod
import subprocess
import sys
import tarfile
import threading
import time
from typing import Any, Callable, Sequence

GIB = 1024 ** 3
CHANNEL_LIMIT = 1024 * 1024  # bytes kept per captured stdout/stderr
SMALL_JSON_LIMIT = 64 * 1024  # oci-layout, index.json, manifest.json and the metadata blobs
MAX_MEMBERS = 64  # 50 blobs + 2 directories + 3 top-level files expected (55)
KILL_GRACE_SECONDS = 5.0
INTERRUPT_GRACE_SECONDS = 0.5  # the guard escalates to SIGKILL 2 s after SIGTERM
TRAILING_LIMIT = 1024 * 1024  # bytes allowed after the tar end-of-archive marker
SOURCE_ANNOTATION_PREFIX = "containerd.io/distribution.source."
CHUNK = 1024 * 1024


@dataclass(frozen=True)
class Pins:
    """Everything the restore checks. PRODUCTION holds the reviewed values."""

    provider: str  # repository@digest reference
    base_name: str
    provider_id: str  # sha256:<index>
    index_size: int
    manifest_digest: str  # amd64 platform manifest
    manifest_size: int
    config_digest: str
    config_size: int
    layer_count: int
    blob_count: int
    content_bytes: int  # sum of every blob: layers + config + manifest + index
    archive_ceiling: int  # pre-write ceiling for the saved archive
    desktop_host: str
    desktop_engine_id: str
    desktop_version: str
    native_engine_id: str
    native_version: str
    containerd_address: str
    containerd_version: str
    containerd_revision: str
    namespace: str
    native_size: int
    rootfs_sha256: str
    env_keys_sha256: str
    unpacked_bytes: int
    archive_dir: str
    archive_name: str
    deadline_seconds: float
    chain_id: str = ""
    docker: str = "/usr/bin/docker"
    ctr: str = "/usr/bin/ctr"
    require_root: bool = True


PRODUCTION = Pins(
    provider="nvcr.io/nvidia/deepstream@sha256:c11befa808af8270e8ea0d0d7cc7cabbda08a2f496ee30b95f7acba5dce81759",
    base_name="nvcr.io/nvidia/deepstream",
    provider_id="sha256:c11befa808af8270e8ea0d0d7cc7cabbda08a2f496ee30b95f7acba5dce81759",
    index_size=745,
    manifest_digest="sha256:34e56b46f00a2c79acb42bfd4f3a977753607a99179520744389ce40ce96eb59",
    manifest_size=10184,
    config_digest="sha256:fcdeffe3fbac262b2f2760eba8dcc3243a5edf9bdb09b490dd5a00ac1ea56121",
    config_size=47088,
    layer_count=47,
    blob_count=50,
    content_bytes=10_469_582_904,
    archive_ceiling=10 * GIB,
    desktop_host="unix:///run/vast-pr9-desktop-api.sock",
    desktop_engine_id="aa8f3d33-e1dc-4ed2-ad06-488b46b332d0",
    desktop_version="29.8.2",
    native_engine_id="1e493309-3767-45fb-9078-05b838bdfd80",
    native_version="29.7.2",
    containerd_address="/run/containerd/containerd.sock",
    containerd_version="v2.3.3",
    containerd_revision="aad11006b869517fcd3009450b6f82da282e1a9b",
    namespace="moby",
    native_size=10_469_582_904,
    rootfs_sha256="1e0fe0c49e48962dc125b19e5b1936c564f1c6a3e00006d5e5cca7dc7ebfd981",
    env_keys_sha256="6785bc7c38e52df3c99c3856d0619875fc1a1f44aab077baa550da820b8f1db9",
    unpacked_bytes=18_930_790_400,
    archive_dir="/var/lib/vast-pr9-b1",
    archive_name="deepstream-c11befa8.docker-save.tar",
    deadline_seconds=5400.0,
    chain_id="sha256:583abc9004877e79fd0f5d47e4c7cff085b8538fdcbff0c070e044bdb0b43c1a",
)

INDEX_TYPES = ("application/vnd.oci.image.index.v1+json",
               "application/vnd.docker.distribution.manifest.list.v2+json")
_MEMBER = re.compile(r"(oci-layout|index\.json|manifest\.json|blobs|blobs/sha256|blobs/sha256/[0-9a-f]{64})")
_DIRS = {"blobs", "blobs/sha256"}


class B1Refusal(RuntimeError):
    """The restore stopped; ``cause`` names the first failed check."""

    def __init__(self, cause: str, **facts: Any) -> None:
        super().__init__(cause)
        self.cause, self.facts = cause, facts


class Interrupted(BaseException):
    """A signal asked the restore to stop."""


def canonical_json_v1(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("ascii")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def chain_id(diff_ids: Any) -> str | None:
    """OCI chain ID of an ordered diff ID list (None when the list is not well formed)."""
    if not (isinstance(diff_ids, list) and diff_ids and all(isinstance(d, str) for d in diff_ids)):
        return None
    chain = diff_ids[0]
    for diff in diff_ids[1:]:
        chain = "sha256:" + _sha256(f"{chain} {diff}".encode())
    return chain


# --- bounded child processes -------------------------------------------------
@dataclass
class Completed:
    argv: list
    rc: int | None
    stdout: bytes = b""
    stderr: bytes = b""
    stdout_overflow: bool = False
    stderr_overflow: bool = False
    timed_out: bool = False
    ceiling_exceeded: bool = False
    written: int = 0
    seconds: float = 0.0
    write_error: str | None = None

    def summary(self) -> dict:
        return {"argv": self.argv, "rc": self.rc, "timed_out": self.timed_out,
                "stdout_bytes": len(self.stdout), "stdout_overflow": self.stdout_overflow,
                "stderr": self.stderr.decode("utf-8", "replace")[-4096:], "stderr_overflow": self.stderr_overflow,
                "ceiling_exceeded": self.ceiling_exceeded, "written": self.written, "write_error": self.write_error,
                "seconds": round(self.seconds, 3)}


def _capture(stream, box: dict, key: str, limit: int) -> None:
    kept = bytearray()
    while True:
        chunk = stream.read(65536)
        if not chunk:
            break
        room = limit - len(kept)
        if len(chunk) > room:
            box[key + "_overflow"] = True  # the rest is drained, not kept
        kept.extend(chunk[:max(room, 0)])
    box[key] = bytes(kept)


def _copy_to_fd(stream, fd: int, ceiling: int, box: dict, on_ceiling: Callable[[], None]) -> None:
    """Copy stream to fd (a private duplicate, closed here) without ever passing ceiling."""
    written = 0
    try:
        while True:
            chunk = stream.read(CHUNK)
            if not chunk:
                break
            if written + len(chunk) > ceiling:
                box["ceiling_exceeded"] = True
                on_ceiling()
                while stream.read(CHUNK):  # drain without writing so the child can exit
                    pass
                break
            view = memoryview(chunk)
            while view:
                view = view[os.write(fd, view):]
            written += len(chunk)
    except OSError as exc:
        box["write_error"] = f"{type(exc).__name__}: {exc}"
        on_ceiling()
    finally:
        box["written"] = written
        os.close(fd)


def run_bounded(argv: Sequence[str], deadline: float, *, out_fd: int | None = None,
                ceiling: int = 0, clock: Callable[[], float] = time.monotonic) -> Completed:
    """Run argv until the absolute deadline. stdout goes to out_fd (bounded by
    ceiling) or to a bounded capture; stderr is always a bounded capture."""
    start = clock()
    if deadline - start <= 0:
        return Completed(list(argv), None, timed_out=True)
    # same process group as the helper on purpose: the containment guard signals the whole group
    child = subprocess.Popen(list(argv), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE)
    box: dict = {}

    def stop_child() -> None:
        try:
            child.kill()
        except OSError:
            pass

    readers = [threading.Thread(target=_capture, args=(child.stderr, box, "stderr", CHANNEL_LIMIT), daemon=True)]
    if out_fd is not None:
        readers.append(threading.Thread(target=_copy_to_fd, args=(child.stdout, os.dup(out_fd), ceiling, box, stop_child),
                                        daemon=True))
    else:
        readers.append(threading.Thread(target=_capture, args=(child.stdout, box, "stdout", CHANNEL_LIMIT),
                                        daemon=True))
    for reader in readers:
        reader.start()
    timed_out = False
    try:
        child.wait(timeout=max(0.0, deadline - clock()))
    except subprocess.TimeoutExpired:
        timed_out = True
        stop_child()
        try:
            child.wait(timeout=KILL_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            pass
    except BaseException:
        stop_child()  # an interrupt never leaves the child running unobserved
        try:
            child.wait(timeout=INTERRUPT_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            pass
        for reader in readers:
            reader.join(INTERRUPT_GRACE_SECONDS)
        raise
    for reader in readers:
        reader.join(KILL_GRACE_SECONDS)
    if out_fd is not None and readers[1].is_alive():
        # the child has exited but its last bytes are still being written: wait, up to the deadline
        readers[1].join(max(0.0, deadline - clock()))
        if readers[1].is_alive():
            timed_out = True
    if not any(reader.is_alive() for reader in readers):
        for stream in (child.stdout, child.stderr):
            stream.close()
    return Completed(list(argv), child.returncode, box.get("stdout", b""), box.get("stderr", b""),
                     bool(box.get("stdout_overflow")), bool(box.get("stderr_overflow")), timed_out,
                     bool(box.get("ceiling_exceeded")), box.get("written", 0), clock() - start,
                     box.get("write_error"))


# --- Docker Engine API over the native unix socket ---------------------------
class _UnixConnection(http.client.HTTPConnection):
    def __init__(self, path: str, timeout: float) -> None:
        super().__init__("localhost", timeout=timeout)
        self._path = path

    def connect(self) -> None:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        sock.connect(self._path)
        self.sock = sock


def unix_api_get(socket_path: str, path: str, timeout: float, limit: int = 4 * 1024 * 1024) -> tuple[int, Any]:
    """GET path from the Docker API on socket_path; returns (status, parsed JSON or None)."""
    conn = _UnixConnection(socket_path, timeout)
    try:
        conn.request("GET", path, headers={"Host": "docker"})
        response = conn.getresponse()
        body = response.read(limit + 1)
        if len(body) > limit:
            raise B1Refusal("api_reply_too_large", path=path)
        try:
            return response.status, json.loads(body) if body else None
        except ValueError:
            return response.status, None
    finally:
        conn.close()


# --- archive membership --------------------------------------------------------
def verify_archive(fd: int, pins: Pins, deadline: float | None = None,
                   clock: Callable[[], float] = time.monotonic) -> dict:
    """Stream the saved archive once and prove its complete membership before any
    import: only the expected names and types, every blob hashed against its
    name, exactly the pinned blob set with pinned sizes, and unchanged metadata."""
    st = os.fstat(fd)
    if not stat_mod.S_ISREG(st.st_mode):
        raise B1Refusal("archive_not_regular")
    if st.st_size > pins.archive_ceiling:
        raise B1Refusal("archive_ceiling", size=st.st_size)
    whole = hashlib.sha256()
    names: list[str] = []
    blobs: dict[str, int] = {}
    small: dict[str, bytes] = {}
    keep = {pins.provider_id, pins.manifest_digest, pins.config_digest}
    os.lseek(fd, 0, os.SEEK_SET)
    raw = os.fdopen(os.dup(fd), "rb", buffering=0)

    class Hashing:
        def read(self, size: int = -1) -> bytes:
            if deadline is not None and clock() >= deadline:
                raise B1Refusal("deadline", stage="verify")
            data = raw.read(size)
            whole.update(data)
            return data

    try:
        with tarfile.open(fileobj=Hashing(), mode="r|") as archive:
            for member in archive:
                name = member.name.rstrip("/")
                names.append(name)
                if len(names) > MAX_MEMBERS:
                    raise B1Refusal("archive_too_many_members")
                if names.count(name) > 1:
                    raise B1Refusal("archive_duplicate_member", member=name)
                if not _MEMBER.fullmatch(name):
                    raise B1Refusal("archive_unexpected_member", member=name)
                if name in _DIRS:
                    if not member.isdir():
                        raise B1Refusal("archive_member_type", member=name)
                    continue
                if not member.isreg():
                    raise B1Refusal("archive_member_type", member=name)
                handle = archive.extractfile(member)
                digest, size, kept = hashlib.sha256(), 0, bytearray()
                is_blob = name.startswith("blobs/sha256/")
                retain = (not is_blob) or ("sha256:" + name[13:]) in keep
                while True:
                    chunk = handle.read(CHUNK)
                    if not chunk:
                        break
                    digest.update(chunk)
                    size += len(chunk)
                    if retain:
                        if len(kept) + len(chunk) > SMALL_JSON_LIMIT:
                            raise B1Refusal("archive_metadata_too_large", member=name)
                        kept.extend(chunk)
                if size != member.size:
                    raise B1Refusal("archive_member_truncated", member=name)
                if is_blob:
                    if digest.hexdigest() != name[13:]:
                        raise B1Refusal("archive_blob_hash", member=name)
                    blobs["sha256:" + name[13:]] = size
                if retain:
                    small[name if not is_blob else "sha256:" + name[13:]] = bytes(kept)
            trailing = 0
            while True:  # tar padding after the end marker only; never read unbounded into memory
                chunk = raw.read(65536)
                if not chunk:
                    break
                trailing += len(chunk)
                if trailing > TRAILING_LIMIT:
                    raise B1Refusal("archive_trailing_data")
                whole.update(chunk)
    except tarfile.TarError as exc:
        raise B1Refusal("archive_unreadable", error=str(exc)) from exc
    finally:
        raw.close()

    def load(key: str, cause: str) -> Any:
        try:
            return json.loads(small[key])
        except (KeyError, ValueError) as exc:
            raise B1Refusal(cause) from exc

    if load("oci-layout", "archive_oci_layout") != {"imageLayoutVersion": "1.0.0"}:
        raise B1Refusal("archive_oci_layout")
    index_json = load("index.json", "archive_index_json")
    children = index_json.get("manifests") if isinstance(index_json, dict) else None
    if not (isinstance(children, list) and len(children) == 1 and isinstance(children[0], dict)):
        raise B1Refusal("archive_index_json")
    child = children[0]
    if (child.get("digest"), child.get("size"), child.get("mediaType") in INDEX_TYPES) != \
            (pins.provider_id, pins.index_size, True):
        raise B1Refusal("archive_index_child", child=child)
    annotations = child.get("annotations") or {}
    # ctr names imported images from io.containerd.image.name (or a ref name): the
    # reviewed archive is anonymous, carrying only Docker's distribution-source labels.
    if not (isinstance(annotations, dict) and all(isinstance(k, str) and k.startswith(SOURCE_ANNOTATION_PREFIX)
                                                  for k in annotations)):
        raise B1Refusal("archive_index_annotations", annotations=annotations)
    provider_index = load(pins.provider_id, "archive_provider_index")
    platforms = [m for m in provider_index.get("manifests") or [] if isinstance(m, dict)
                 and m.get("digest") == pins.manifest_digest]
    if not (len(platforms) == 1 and platforms[0].get("size") == pins.manifest_size
            and (platforms[0].get("platform") or {}).get("architecture") == "amd64"
            and (platforms[0].get("platform") or {}).get("os") == "linux"):
        raise B1Refusal("archive_provider_index")
    manifest = load(pins.manifest_digest, "archive_manifest")
    config_desc = manifest.get("config") or {}
    layers = manifest.get("layers") or []
    if (config_desc.get("digest"), config_desc.get("size"), len(layers)) != \
            (pins.config_digest, pins.config_size, pins.layer_count):
        raise B1Refusal("archive_manifest")
    config = load(pins.config_digest, "archive_config")
    if (config.get("architecture"), config.get("os"), len((config.get("rootfs") or {}).get("diff_ids") or [])) != \
            ("amd64", "linux", pins.layer_count):
        raise B1Refusal("archive_config")
    expected = {pins.provider_id: pins.index_size, pins.manifest_digest: pins.manifest_size,
                pins.config_digest: pins.config_size}
    for layer in layers:
        expected[layer.get("digest")] = layer.get("size")
    if len(expected) != pins.blob_count or blobs != expected:
        raise B1Refusal("archive_blob_set", missing=sorted(set(expected) - set(blobs)),
                        extra=sorted(set(blobs) - set(expected)),
                        size_mismatch=sorted(d for d in set(blobs) & set(expected) if blobs[d] != expected[d]))
    if sum(blobs.values()) != pins.content_bytes:
        raise B1Refusal("archive_content_bytes", total=sum(blobs.values()))
    # Docker's compatibility manifest is always written by the reviewed exporter: anonymous, same config and layers
    legacy = load("manifest.json", "archive_legacy_manifest")
    want_layers = ["blobs/sha256/" + layer["digest"][7:] for layer in layers]
    if not (isinstance(legacy, list) and len(legacy) == 1 and isinstance(legacy[0], dict)
            and legacy[0].get("Config") == "blobs/sha256/" + pins.config_digest[7:]
            and legacy[0].get("Layers") == want_layers and not legacy[0].get("RepoTags")):
        raise B1Refusal("archive_legacy_manifest")
    return {"size": st.st_size, "sha256": whole.hexdigest(), "members": len(names), "blobs": len(blobs),
            "content_bytes": sum(blobs.values()), "index_annotations": child.get("annotations") or {}}


# --- the restore ---------------------------------------------------------------
@dataclass
class Restore:
    pins: Pins
    api_get: Callable[[str, float], "tuple[int, Any]"]
    desktop_api_get: Callable[[str, float], "tuple[int, Any]"]
    runner: Callable[..., Completed] = run_bounded
    clock: Callable[[], float] = time.monotonic
    record: dict = field(default_factory=dict)
    reuse: "tuple[str, int] | None" = None  # (sha256, size) recorded by the consumed earlier attempt

    def _stage(self, name: str, **facts: Any) -> None:
        self.record.setdefault("stages", []).append({"stage": name, "at": round(self.clock() - self._start, 3), **facts})

    def _run(self, argv: Sequence[str], **kw: Any) -> Completed:
        done = self.runner(list(argv), self._deadline, **kw)
        self.record.setdefault("commands", []).append(done.summary())
        if done.timed_out:
            raise B1Refusal("deadline", argv=list(argv))
        return done

    def _api(self, path: str, desktop: bool = False) -> tuple[int, Any]:
        remaining = self._deadline - self.clock()
        if remaining <= 0:
            raise B1Refusal("deadline", path=path)
        try:
            return (self.desktop_api_get if desktop else self.api_get)(path, min(remaining, 120.0))
        except B1Refusal:
            raise
        except Exception as exc:  # noqa: BLE001 - an unreachable engine is a refusal, never a pass
            raise B1Refusal("desktop_api_unavailable" if desktop else "native_api_unavailable", path=path,
                            error=f"{type(exc).__name__}: {exc}") from exc

    def _ok(self, argv: Sequence[str], cause: str) -> str:
        done = self._run(argv)
        if done.rc != 0 or done.stdout_overflow:
            raise B1Refusal(cause, rc=done.rc)
        return done.stdout.decode("utf-8", "replace").strip()

    def _native_containers(self) -> list:
        status, rows = self._api("/v1.55/containers/json?all=1")
        if status != 200 or not isinstance(rows, list):
            raise B1Refusal("native_containers_unreadable", status=status)
        return sorted((r.get("Id"), r.get("State")) for r in rows if isinstance(r, dict))

    def _ctr(self, *args: str) -> list:
        p = self.pins
        return [p.ctr, "--address", p.containerd_address, "--namespace", p.namespace, *args]

    def _remnants(self, key: str) -> None:
        """Read-only record of containerd's active ingests and leases (left as they are)."""
        snapshot: dict = {}
        for name, args in (("ingests", ("content", "active")), ("leases", ("leases", "ls"))):
            lines = self._ok(self._ctr(*args), "containerd_unreachable").splitlines()
            snapshot[name] = lines[:64]
            snapshot[name + "_truncated"] = len(lines) > 64
        self.record[key] = snapshot

    # stage 1: identities, no writes
    def preflight(self) -> None:
        p = self.pins
        if p.require_root and os.geteuid() != 0:
            raise B1Refusal("not_root")
        desktop = [p.docker, "-H", p.desktop_host]
        if self._ok([*desktop, "version", "--format", "{{.Server.Version}}"], "desktop_unreachable") != p.desktop_version:
            raise B1Refusal("desktop_version")
        if self._ok([*desktop, "info", "--format", "{{.ID}}"], "desktop_unreachable") != p.desktop_engine_id:
            raise B1Refusal("desktop_engine_identity")
        source = self._ok([*desktop, "image", "inspect", p.provider, "--format", "{{json .Id}} {{json .RepoDigests}}"],
                          "desktop_source_missing")
        try:
            source_id, digests = source.split(" ", 1)
            source_ok = json.loads(source_id) == p.provider_id and p.provider in json.loads(digests)
        except ValueError:
            source_ok = False
        if not source_ok:
            raise B1Refusal("desktop_source_identity", observed=source[:512])
        # read-only: the save exports every available platform and referrer, so anything
        # beyond the amd64 manifest would surface as extra blobs only after a 10 GB write
        status, image = self._api(f"/v1.55/images/{p.provider_id}/json?manifests=1", desktop=True)
        rows = image.get("Manifests") if status == 200 and isinstance(image, dict) else None
        if not isinstance(rows, list) or image.get("Id") != p.provider_id:
            raise B1Refusal("desktop_manifests_unreadable", status=status)
        available = sorted((m.get("ID"), m.get("Kind")) for m in rows if isinstance(m, dict) and m.get("Available"))
        if available != [(p.manifest_digest, "image")]:
            raise B1Refusal("desktop_extra_content", available=available)
        status, version = self._api("/v1.55/version")
        if status != 200 or not isinstance(version, dict) or version.get("Version") != p.native_version:
            raise B1Refusal("native_version", status=status)
        status, info = self._api("/v1.55/info")
        if status != 200 or not isinstance(info, dict) or info.get("ID") != p.native_engine_id:
            raise B1Refusal("native_engine_identity", status=status)
        status, _ = self._api(f"/v1.55/images/{p.provider_id}/json")
        if status != 404:
            raise B1Refusal("native_image_present", status=status)  # nothing is overwritten or re-imported
        ctr_version = self._ok([p.ctr, "--address", p.containerd_address, "version"], "containerd_unreachable")
        # with --local the import runs inside the ctr client, so the client and the server are both pinned
        client, _, server = ctr_version.partition("Server:")

        def pinned(section: str) -> bool:
            return bool(re.search(rf"Version:\s+{re.escape(p.containerd_version)}\s", section + "\n")
                        and re.search(rf"Revision:\s+{re.escape(p.containerd_revision)}\s", section + "\n"))

        if not (server and pinned(client) and pinned(server)):
            raise B1Refusal("containerd_version", observed=ctr_version[-512:])
        refs = self._ok(self._ctr("images", "ls", "-q"), "containerd_unreachable").split()
        if p.provider in refs:
            raise B1Refusal("native_reference_present")
        self.record["native_references_before"] = sorted(refs)
        self.record["native_containers_before"] = self._native_containers()
        self._remnants("remnants_preflight")
        self._stage("preflight", desktop_engine=p.desktop_engine_id, native_engine=p.native_engine_id)

    # stage 2: archive directory and pre-write-bounded save
    def save(self) -> int:
        p = self.pins
        directory = Path(p.archive_dir)
        if directory.is_symlink():
            raise B1Refusal("archive_dir_symlink")
        if not directory.exists():
            directory.mkdir(mode=0o700)
            self._stage("archive_dir_created", path=p.archive_dir)
        dir_fd = os.open(p.archive_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            st = os.fstat(dir_fd)
            if p.require_root and (st.st_uid != 0 or st.st_mode & 0o022):
                raise B1Refusal("archive_dir_ownership")
            if os.listdir(dir_fd):
                raise B1Refusal("archive_dir_not_empty", entries=sorted(os.listdir(dir_fd))[:16])
            fd = os.open(p.archive_name, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=dir_fd)
            self._stage("archive_created", path=os.path.join(p.archive_dir, p.archive_name))
            try:
                done = self._run([p.docker, "-H", p.desktop_host, "image", "save", p.provider],
                                 out_fd=fd, ceiling=p.archive_ceiling)
                os.fsync(fd)
                os.fsync(dir_fd)
                if done.ceiling_exceeded:
                    raise B1Refusal("archive_ceiling", written=done.written)
                if done.write_error:
                    raise B1Refusal("archive_write_failed", error=done.write_error, written=done.written)
                if done.rc != 0:
                    raise B1Refusal("save_failed", rc=done.rc)
            except BaseException:
                os.close(fd)  # the partial archive stays on disk
                raise
        finally:
            os.close(dir_fd)
        self._stage("saved", bytes=done.written)
        return fd

    # stage 2 (reuse): the retained archive of a consumed attempt, read-only
    def open_retained(self) -> int:
        p = self.pins
        expected_sha, expected_size = self.reuse
        if Path(p.archive_dir).is_symlink():
            raise B1Refusal("archive_dir_symlink")
        try:
            dir_fd = os.open(p.archive_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        except OSError as exc:
            raise B1Refusal("reuse_archive_dir_unusable", error=type(exc).__name__) from exc
        try:
            st = os.fstat(dir_fd)
            if p.require_root and (st.st_uid != 0 or st.st_mode & 0o022):
                raise B1Refusal("archive_dir_ownership")
            entries = sorted(os.listdir(dir_fd))
            if entries != [p.archive_name]:
                raise B1Refusal("reuse_archive_dir_contents", entries=entries[:16])
            try:  # O_NONBLOCK: a FIFO or device planted under the name cannot block the open
                fd = os.open(p.archive_name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dir_fd)
            except OSError as exc:
                raise B1Refusal("reuse_archive_unreadable", error=type(exc).__name__) from exc
        finally:
            os.close(dir_fd)
        st = os.fstat(fd)
        try:
            if not stat_mod.S_ISREG(st.st_mode):
                raise B1Refusal("reuse_archive_not_regular")
            if st.st_nlink != 1 or st.st_mode & 0o022 or (p.require_root and st.st_uid != 0):
                raise B1Refusal("reuse_archive_ownership", uid=st.st_uid, mode=oct(st.st_mode & 0o7777),
                                links=st.st_nlink)
            if st.st_size != expected_size:
                raise B1Refusal("reuse_archive_size", size=st.st_size, expected=expected_size)
        except B1Refusal:
            os.close(fd)
            raise
        self._stage("archive_reused", path=os.path.join(p.archive_dir, p.archive_name), expected_sha256=expected_sha)
        return fd

    # stage 3: complete membership, then pin the file identity for the import
    def verify(self, fd: int) -> tuple:
        facts = verify_archive(fd, self.pins, self._deadline, self.clock)
        self.record["archive"] = facts
        if self.reuse is not None and (facts["sha256"], facts["size"]) != self.reuse:
            raise B1Refusal("reuse_archive_sha256", observed=facts["sha256"], expected=self.reuse[0])
        st = os.fstat(fd)
        self._stage("verified", **{k: facts[k] for k in ("size", "sha256", "members", "blobs")})
        return st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns

    def _archive_identity(self) -> tuple | None:
        try:
            st = os.stat(os.path.join(self.pins.archive_dir, self.pins.archive_name), follow_symlinks=False)
        except OSError:
            return None
        if not stat_mod.S_ISREG(st.st_mode):
            return None
        return st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns

    # stage 4: the one reviewed import
    def import_archive(self, identity: tuple) -> None:
        p = self.pins
        path = os.path.join(p.archive_dir, p.archive_name)
        self._remnants("remnants_before_import")
        if self._archive_identity() != identity:
            raise B1Refusal("archive_changed_before_import")
        self.record["import_started"] = True
        done = self._run(self._ctr("images", "import", "--local", "--base-name", p.base_name, "--digests",
                                   "--platform", "linux/amd64", "--snapshotter", "overlayfs", "--sync-fs", path))
        if self._archive_identity() != identity:
            raise B1Refusal("archive_changed_during_import")
        if done.rc != 0:
            raise B1Refusal("import_failed", rc=done.rc)
        self._stage("imported")

    # stage 5: the native provider contract
    def verify_native(self) -> None:
        p = self.pins
        status, image = self._api(f"/v1.55/images/{p.provider_id}/json?manifests=1")
        if status != 200 or not isinstance(image, dict):
            raise B1Refusal("native_image_missing_after_import", status=status)
        env = (image.get("Config") or {}).get("Env") or []
        keys = sorted(v.split("=", 1)[0] for v in env if isinstance(v, str))
        amd64 = [m for m in image.get("Manifests") or [] if isinstance(m, dict) and m.get("ID") == p.manifest_digest]
        unpacked = ((amd64[0].get("ImageData") or {}).get("Size") or {}).get("Unpacked") \
            if len(amd64) == 1 and amd64[0].get("Available") is True else None
        observed = {"id": image.get("Id"), "repo_digests": image.get("RepoDigests"),
                    "repo_tags": image.get("RepoTags"), "size": image.get("Size"),
                    "rootfs_sha256": _sha256(canonical_json_v1(image.get("RootFS"))),
                    "env_keys_sha256": _sha256(canonical_json_v1(keys)), "unpacked_bytes": unpacked,
                    "chain_id": chain_id((image.get("RootFS") or {}).get("Layers"))}
        # Docker 29.7.2 lists the one digested name under both RepoTags and RepoDigests
        expected = {"id": p.provider_id, "repo_digests": [p.provider], "repo_tags": [p.provider],
                    "size": p.native_size,
                    "rootfs_sha256": p.rootfs_sha256, "env_keys_sha256": p.env_keys_sha256,
                    "unpacked_bytes": p.unpacked_bytes, "chain_id": p.chain_id}
        self.record["native_image"] = observed
        if observed != expected:
            raise B1Refusal("post_import_drift", drift={k: [observed[k], expected[k]] for k in expected
                                                           if observed[k] != expected[k]})
        refs = self._ok(self._ctr("images", "ls", "-q"), "containerd_unreachable").split()
        if p.provider not in refs:
            raise B1Refusal("native_reference_missing_after_import")
        self.record["native_references_after"] = sorted(refs)
        if sorted(refs) != sorted(self.record["native_references_before"] + [p.provider]):
            # exactly one new reference name; an existing name cannot be retargeted because only an
            # anonymous archive (no image-name annotation) reaches the import
            raise B1Refusal("native_references_changed")
        after = self._native_containers()
        self.record["native_containers_after"] = after
        if after != self.record["native_containers_before"]:
            raise B1Refusal("native_containers_changed")
        self._stage("native_verified")

    def run(self) -> dict:
        self._start = self.clock()
        self._deadline = self._start + self.pins.deadline_seconds
        self.record.update(schema="vast.pr9.b1-restore.v1", provider=self.pins.provider, outcome=None,
                           mode="reuse" if self.reuse is not None else "save",
                           retained=("the archive and this record are retained; the helper never prunes, removes, "
                                     "overwrites or retries (containerd may release a failed import's unreferenced "
                                     "content when ctr's lease ends)"))
        try:
            self.preflight()
            fd = self.open_retained() if self.reuse is not None else self.save()
            try:
                identity = self.verify(fd)
            finally:
                os.close(fd)
            self.import_archive(identity)
            self.verify_native()
            self.record["outcome"] = "restored"
        except B1Refusal as exc:
            self.record.update(outcome="refused", cause=exc.cause, facts=exc.facts)
        except Interrupted as exc:
            self.record.update(outcome="refused", cause="interrupted", facts={"signal": str(exc)})
        except Exception as exc:  # noqa: BLE001 - recorded, never lost
            self.record.update(outcome="refused", cause="internal_error", facts={"error": f"{type(exc).__name__}: {exc}"})
        try:
            if self.record.get("import_started") and self.record["outcome"] != "restored":
                self.record["native_state"] = ("unknown: the import began; containerd may have kept, still be "
                                               "processing, or later release partial content")
            self.record["seconds"] = round(self.clock() - self._start, 3)
        except Interrupted as exc:  # bookkeeping only: the outcome above stands
            self.record.setdefault("late_signals_in_run", []).append(str(exc))
        return self.record


def write_record(path: Path, record: dict) -> None:
    data = (json.dumps(record, indent=2, sort_keys=True, default=str) + "\n").encode("utf-8")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
    try:
        view = memoryview(data)
        while view:
            view = view[os.write(fd, view):]
        os.fsync(fd)
    finally:
        os.close(fd)


def _interrupt(signum, _frame):
    raise Interrupted(signal.Signals(signum).name)


def main(argv: Sequence[str] | None = None, *, pins: Pins = PRODUCTION,
         api_get: Callable[[str, float], "tuple[int, Any]"] | None = None,
         desktop_api_get: Callable[[str, float], "tuple[int, Any]"] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--record", required=True, type=Path)
    parser.add_argument("--reuse-archive-sha256")
    parser.add_argument("--reuse-archive-size", type=int)
    args = parser.parse_args(argv)
    if (args.reuse_archive_sha256 is None) != (args.reuse_archive_size is None):
        parser.error("--reuse-archive-sha256 and --reuse-archive-size go together")
    if args.reuse_archive_sha256 is not None and not re.fullmatch("[0-9a-f]{64}", args.reuse_archive_sha256):
        parser.error("--reuse-archive-sha256 must be 64 lowercase hex characters")
    if args.reuse_archive_size is not None and not 0 < args.reuse_archive_size <= pins.archive_ceiling:
        parser.error("--reuse-archive-size must be positive and within the archive ceiling")
    reuse = None if args.reuse_archive_sha256 is None else (args.reuse_archive_sha256, args.reuse_archive_size)
    if args.record.exists() or args.record.is_symlink():
        parser.error("record path already exists")
    if not args.record.parent.is_dir():
        parser.error("record directory missing")
    if api_get is None:
        native_socket = "/run/docker.sock"
        api_get = lambda path, timeout: unix_api_get(native_socket, path, timeout)  # noqa: E731
    if desktop_api_get is None:
        if not pins.desktop_host.startswith("unix://"):
            parser.error("desktop host must be a unix socket")
        desktop_socket = pins.desktop_host[len("unix://"):]
        desktop_api_get = lambda path, timeout: unix_api_get(desktop_socket, path, timeout)  # noqa: E731
    signals = (signal.SIGTERM, signal.SIGHUP, signal.SIGINT)
    previous = {s: signal.signal(s, _interrupt) for s in signals}
    late: list = []
    try:
        restore = Restore(pins, api_get, desktop_api_get, reuse=reuse)
        try:
            try:
                restore.run()
            except Interrupted as exc:  # arrived after run() had finished its own handling
                if restore.record.get("outcome") is None:
                    restore.record.update(outcome="refused", cause="interrupted", facts={"signal": str(exc)})
                late.append(str(exc))
            record = restore.record
        finally:
            for s in signals:  # from here a signal is noted, never fatal: the record must be written
                signal.signal(s, lambda signum, _frame: late.append(signal.Signals(signum).name))
        record["late_signals"] = late
        try:
            write_record(args.record, record)
        except OSError as exc:
            os.write(2, f"b1 restore: record write failed ({type(exc).__name__}); record follows\n".encode()
                     + json.dumps(record, sort_keys=True, default=str).encode() + b"\n")
            return 4
    finally:
        for s, handler in previous.items():
            signal.signal(s, handler)
    return 0 if record["outcome"] == "restored" else 3


if __name__ == "__main__":
    sys.exit(main())
