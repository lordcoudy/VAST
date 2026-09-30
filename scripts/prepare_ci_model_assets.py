"""Acquire the eight frozen CI files, without model execution or cache repair.

The CLI fixes its repository/manifest/metadata inputs. Each network object runs
in an original child, inheriting the caller's process group so the CI driver's
outer killpg deadline also covers blocked DNS. Tests inject only local responses.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import math
import os
import re
import stat
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
METADATA_PATH = ".ci/model-assets.v1.json"
MANIFEST_PATH = "configs/checkpoint_analytics_models_openvino.yaml"
CHUNK_BYTES = 64 * 1024
METADATA_BYTES = 1024 * 1024
NAMESPACE_BYTES = 24 * 1024 * 1024
RECORD_BYTES = 16 * 1024
OBJECT_SECONDS = 120.0
TOTAL_SECONDS = 600.0
TEARDOWN_SECONDS = 10.0
SOCKET_SECONDS = 15.0
MODELS = {
    "damage": "person-vehicle-bike-detection-2002",
    "foreign_object": "person-vehicle-bike-detection-crossroad-1016",
    "plate_number": "vehicle-license-plate-detection-barrier-0106",
    "vehicle_type": "vehicle-detection-0202",
}
ORIGIN = "https://storage.openvinotoolkit.org/repositories/open_model_zoo/2023.0/models_bin/1/"


class AssetPreparationError(RuntimeError):
    pass


def _require(condition, message):
    if not condition:
        raise AssetPreparationError(message)


def _epoch(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _unique(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, "duplicate metadata or manifest key")
        result[key] = value
    return result


class _Yaml(yaml.SafeLoader):
    pass


def _yaml_mapping(loader, node):
    return _unique((loader.construct_object(key), loader.construct_object(value))
                   for key, value in node.value)


_Yaml.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _yaml_mapping)


def _json(raw):
    return json.loads(raw, object_pairs_hook=_unique,
        parse_constant=lambda value: (_ for _ in ()).throw(AssetPreparationError("nonfinite metadata")))


def _relative(value):
    _require(type(value) is str and value and "\\" not in value and "\x00" not in value,
             "noncanonical destination path")
    parts = value.split("/")
    _require(not value.startswith("/") and all(part not in {"", ".", ".."} for part in parts),
             "destination path escapes its physical root")
    return parts


class _Directory:
    """An anchored directory FD; sibling writes do not invalidate its identity."""
    def __init__(self, root, relative="", *, create=False, exclusive=False):
        self.root, self.chain = root, []
        self.fd = os.dup(root.fd)
        try:
            parts = _relative(relative) if relative else []
            for position, name in enumerate(parts):
                if create:
                    try:
                        os.mkdir(name, 0o700, dir_fd=self.fd)
                    except FileExistsError:
                        _require(not (exclusive and position == len(parts) - 1), "output namespace is occupied")
                parent = self.fd
                child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                info = os.fstat(child)
                named = os.stat(name, dir_fd=parent, follow_symlinks=False)
                _require(stat.S_ISDIR(info.st_mode) and _epoch(info)[:3] == _epoch(named)[:3],
                         "directory is not physical or was replaced")
                self.chain.append((parent, name, _epoch(info)[:3]))
                self.fd = child
        except BaseException:
            self.close()
            raise

    def check(self):
        self.root.check()
        for parent, name, identity in self.chain:
            _require(_epoch(os.stat(name, dir_fd=parent, follow_symlinks=False))[:3] == identity,
                     "physical directory changed or became a symlink")

    def close(self):
        for descriptor in set([self.fd] + [parent for parent, _, _ in self.chain]):
            with contextlib.suppress(OSError):
                os.close(descriptor)


class _Root:
    def __init__(self, path):
        self.path = Path(path).absolute()
        _require(self.path.resolve(strict=True) == self.path, "project root is not physical")
        self.fd = os.open(self.path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        self.identity = _epoch(os.fstat(self.fd))[:3]

    def check(self):
        _require(self.path.resolve(strict=True) == self.path and
                 _epoch(self.path.lstat())[:3] == self.identity and
                 _epoch(os.fstat(self.fd))[:3] == self.identity, "physical root changed or became an alias")

    def close(self):
        os.close(self.fd)


class _Input:
    def __init__(self, root, relative, maximum):
        self.relative = relative
        parts = _relative(relative)
        self.directory = _Directory(root, "/".join(parts[:-1]))
        self.name = parts[-1]
        try:
            self.fd = os.open(self.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=self.directory.fd)
            self.info = _epoch(os.fstat(self.fd))
            _require(stat.S_ISREG(self.info[2]) and self.info[3] == 1,
                     "input must be a regular single-link file")
            _require(0 < self.info[4] <= maximum, "input exceeds its byte bound")
            self.raw = os.read(self.fd, maximum + 1)
            _require(len(self.raw) == self.info[4], "input size changed while reading")
            self.sha = hashlib.sha256(self.raw).hexdigest()
            self.check()
        except BaseException:
            self.close()
            raise

    def check(self):
        self.directory.check()
        _require(_epoch(os.fstat(self.fd)) == self.info and
                 _epoch(os.stat(self.name, dir_fd=self.directory.fd, follow_symlinks=False)) == self.info,
                 "input changed or was replaced")

    def descriptor(self):
        return {"path": self.relative, "size_bytes": self.info[4], "sha256": self.sha,
                "epoch": list(self.info)}

    def close(self):
        if hasattr(self, "fd"):
            os.close(self.fd)
        self.directory.close()


def _inventory(root, stack):
    metadata = stack.enter_context(contextlib.closing(_Input(root, METADATA_PATH, 64 * 1024)))
    manifest = stack.enter_context(contextlib.closing(_Input(root, MANIFEST_PATH, 64 * 1024)))
    value = _json(metadata.raw)
    _require(type(value) is dict and set(value) == {"schema_version", "artifact_kind", "manifest", "assets"}
        and type(value["schema_version"]) is int and value["schema_version"] == 1
        and value["artifact_kind"] == "vast_ci_frozen_model_assets_v1", "frozen asset metadata schema drifted")
    _require(value["manifest"] == {"path": MANIFEST_PATH, "size_bytes": manifest.info[4], "sha256": manifest.sha},
             "frozen manifest pin differs from its original bytes")
    source = yaml.load(manifest.raw, Loader=_Yaml)
    _require(type(source) is dict and source.get("schema_version") == 2
        and source.get("artifact_kind") == "checkpoint_analytics_model_bindings"
        and type(source.get("branches")) is dict and set(source["branches"]) == set(MODELS),
        "model manifest branch or version domain drifted")
    rows, coordinates = value["assets"], set()
    _require(type(rows) is list and len(rows) == 8, "frozen asset domain must contain exactly eight objects")
    for row in rows:
        _require(type(row) is dict and set(row) == {"branch", "role", "path", "url", "size_bytes", "sha256", "sha384"},
                 "frozen asset row fields drifted")
        branch, role = row["branch"], row["role"]
        _require(branch in MODELS and role in {"xml", "bin"} and (branch, role) not in coordinates,
                 "duplicate or foreign asset coordinate")
        coordinates.add((branch, role))
        name = MODELS[branch]
        destination = f"models/openvino/public/intel/{name}/FP16/{name}.{role}"
        _relative(row["path"])
        _require(row["path"] == destination, "noncanonical model destination")
        prefix = "model" if role == "xml" else "weights"
        raw = source["branches"][branch]
        _require(raw.get(prefix + "_path") == "../" + destination and
                 row["url"] == raw.get(prefix + "_source_url") == ORIGIN + f"{name}/FP16/{name}.{role}",
                 "manifest asset path or original HTTPS URL drifted")
        for algorithm, length, key in (("sha256", 64, prefix + "_sha256"),
                                        ("sha384", 96, prefix + "_source_sha384")):
            _require(type(row[algorithm]) is str and re.fullmatch("[0-9a-f]{%d}" % length, row[algorithm])
                     and row[algorithm] == raw.get(key), "manifest asset digest drifted")
        _require(type(row["size_bytes"]) is int and row["size_bytes"] > 0, "asset size is invalid")
    _require(sum(row["size_bytes"] for row in rows) + max(row["size_bytes"] for row in rows)
             + METADATA_BYTES <= NAMESPACE_BYTES, "owned acquisition namespace exceeds its finite budget")
    return rows, (metadata, manifest)


def _observation_output(stack, path, *, fresh):
    """Hold a separate physical output anchor; repository destinations stay fixed."""
    destination = Path(path).absolute()
    ancestor = destination.parent
    while not ancestor.exists():
        ancestor = ancestor.parent
    try:
        anchor = stack.enter_context(contextlib.closing(_Root(ancestor)))
        relative = destination.relative_to(anchor.path).as_posix()
        output = stack.enter_context(contextlib.closing(_Directory(anchor, relative,
            create=fresh, exclusive=fresh)))
    except OSError as error:
        raise AssetPreparationError("observation output is not physical or became an alias") from error
    output.path = destination
    return output


def _write_json(directory, name, value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode() + b"\n"
    _require(len(raw) <= RECORD_BYTES, "acquisition metadata record exceeds its byte bound")
    directory.check()
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o400, dir_fd=directory.fd)
    try:
        with os.fdopen(fd, "wb", closefd=False) as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(fd)
        _require(os.fstat(fd).st_nlink == 1, "new acquisition record became an alias")
        directory.check()
        os.fsync(directory.fd)
    finally:
        os.close(fd)


def _existing(root, row):
    parts = _relative(row["path"])
    with contextlib.closing(_Directory(root, "/".join(parts[:-1]), create=True)) as directory:
        try:
            fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory.fd)
        except FileNotFoundError:
            return False
        with os.fdopen(fd, "rb") as stream:
            before = _epoch(os.fstat(fd))
            _require(stat.S_ISREG(before[2]) and before[3] == 1, "existing target must be regular single-link bytes")
            _require(before[4] == row["size_bytes"], "existing model size differs; cache is not repaired")
            digests = {key: hashlib.new(key) for key in ("sha256", "sha384")}
            received = 0
            while True:
                block = stream.read(min(CHUNK_BYTES, row["size_bytes"] - received + 1))
                if not block:
                    break
                received += len(block)
                _require(received <= row["size_bytes"], "existing model grew beyond its exact size cap")
                for digest in digests.values():
                    digest.update(block)
            _require(received == row["size_bytes"], "existing model became short during verification")
            _require(all(digests[key].hexdigest() == row[key] for key in digests), "existing model digest differs; cache is not repaired")
            _require(_epoch(os.fstat(fd)) == before and
                     _epoch(os.stat(parts[-1], dir_fd=directory.fd, follow_symlinks=False)) == before,
                     "existing target changed during verification")
            directory.check()
        return True


def _remaining(clock, deadline):
    remaining = deadline - clock()
    _require(math.isfinite(remaining) and remaining > 0, "original asset deadline exceeded")
    return remaining


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def _network_open(request, *, timeout):
    return urllib.request.build_opener(_NoRedirect()).open(request, timeout=timeout)


def _bounded_text(value, maximum):
    text = str(value)
    low, high = 0, len(text)
    while low < high:
        middle = (low + high + 1) // 2
        if len(json.dumps(text[:middle], ensure_ascii=True).encode()) <= maximum:
            low = middle
        else:
            high = middle - 1
    return text[:low], low != len(text)


def _response_facts(response):
    observed = response.geturl()
    url = urllib.parse.urlsplit(observed)
    safe = urllib.parse.urlunsplit((url.scheme, url.hostname or "", url.path, "", ""))
    headers, shortened_headers = {}, []
    for key in ("Content-Length", "Content-Type", "ETag", "Last-Modified"):
        value = response.headers.get(key)
        if value is not None:
            headers[key], shortened = _bounded_text(value, 256)
            if shortened:
                shortened_headers.append(key)
    location = response.headers.get("Location")
    if location is not None:
        parsed = urllib.parse.urlsplit(location)
        headers["Location"], shortened = _bounded_text(urllib.parse.urlunsplit(
            (parsed.scheme, parsed.hostname or "", parsed.path, "", "")), 1024)
        if shortened:
            shortened_headers.append("Location")
    safe, shortened = _bounded_text(safe, 1024)
    return {"http_status": response.status, "observed_url": safe,
            "observed_url_truncated": shortened,
            "observed_url_redacted": safe != observed, "response_headers": headers,
            "response_headers_truncated": shortened_headers}


def _read_timeout(response, seconds):
    # CPython 3.12 urllib returns HTTPResponse; its fp is None at proven EOF.
    if response.fp is not None:
        response.fp.raw._sock.settimeout(seconds)


def _download(root, row, index, output, staging, inputs, *, opener, clock, deadline):
    record = {"index": index, "asset": row, "status": "started", "request_url": row["url"],
              "received_bytes": 0, "hashed_prefix_bytes": 0, "completed_write_bytes": 0,
              "original_file_observed_bytes": None, "started_monotonic": clock(),
              "partial_path": str(root.path / staging / (f"asset-{index:02d}.part"))}
    hashes = {key: hashlib.new(key) for key in ("sha256", "sha384")}
    source = target = None
    partial_fd = None
    original_error = None
    try:
        source = _Directory(root, staging)
        partial = f"asset-{index:02d}.part"
        partial_fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o600, dir_fd=source.fd)
        parts = _relative(row["path"])
        target = _Directory(root, "/".join(parts[:-1]))
        request = urllib.request.Request(row["url"], headers={"Accept-Encoding": "identity"})
        response = opener(request, timeout=min(SOCKET_SECONDS, _remaining(clock, deadline)))
        with contextlib.closing(response):
            record.update(_response_facts(response))
            _require(response.status == 200, "original HTTP status is not 200")
            _require(response.geturl() == row["url"], "unexpected original URL or redirect")
            length = response.headers.get("Content-Length")
            _require(length is None or (str(length).isdigit() and int(length) == row["size_bytes"]),
                     "HTTP declared size differs from frozen object")
            while True:
                remaining = _remaining(clock, deadline)
                if opener is _network_open:
                    _read_timeout(response, min(SOCKET_SECONDS, remaining))
                limit = min(CHUNK_BYTES, row["size_bytes"] - record["received_bytes"] + 1)
                block = response.read(limit)
                _require(type(block) is bytes and len(block) <= limit, "response violated bounded read size")
                if not block:
                    break
                record["received_bytes"] += len(block)
                _require(record["received_bytes"] <= row["size_bytes"], "oversize original model body")
                for digest in hashes.values():
                    digest.update(block)
                record["hashed_prefix_bytes"] += len(block)
                with os.fdopen(partial_fd, "wb", closefd=False) as stream:
                    _require(stream.write(block) == len(block), "short original partial write")
                    stream.flush()
                record["completed_write_bytes"] += len(block)
            _require(record["received_bytes"] == row["size_bytes"], "short original model body size")
            _require(all(hashes[key].hexdigest() == row[key] for key in hashes), "original model body digest differs")
        _remaining(clock, deadline)
        for pin in inputs:
            pin.check()
        source.check()
        target.check()
        os.fsync(partial_fd)
        _require(os.fstat(partial_fd).st_nlink == 1, "owned partial became an alias")
        os.fchmod(partial_fd, 0o444)
        _require(_epoch(os.stat(partial, dir_fd=source.fd, follow_symlinks=False)) ==
                 _epoch(os.fstat(partial_fd)), "original partial name was replaced before publication")
        try:
            record["publication_attempted"] = True
            os.link(partial, parts[-1], src_dir_fd=source.fd, dst_dir_fd=target.fd, follow_symlinks=False)
        except FileExistsError as error:
            raise AssetPreparationError("target became occupied; replacement is forbidden") from error
        record["publication_observed"] = True
        published = _epoch(os.fstat(partial_fd))
        _require(published[3] == 2 and
                 _epoch(os.stat(partial, dir_fd=source.fd, follow_symlinks=False)) == published and
                 _epoch(os.stat(parts[-1], dir_fd=target.fd, follow_symlinks=False)) == published,
                 "published target does not retain the original partial inode")
        os.unlink(partial, dir_fd=source.fd)
        record["partial_path"] = None
        os.fsync(target.fd)
        os.fsync(source.fd)
        target.check()
        for pin in inputs:
            pin.check()
        _require(_existing(root, row), "published object is missing")
        _remaining(clock, deadline)
        record["status"] = "downloaded"
        record["partial_path"] = None
    except BaseException as error:
        original_error = error
        if isinstance(error, urllib.error.HTTPError):
            record.update(_response_facts(error))
            record["redirect_rejected"] = 300 <= error.code < 400
            error.close()
        record["status"] = "failed"
        message, shortened = _bounded_text(error, 2048)
        trace, trace_shortened = _bounded_text(traceback.format_exc(limit=6), 4096)
        record["error"] = {"type": type(error).__name__, "message": message,
                           "message_truncated": shortened,
                           "traceback": trace, "traceback_truncated": trace_shortened}
    finally:
        if partial_fd is not None:
            observed = os.fstat(partial_fd)
            record["original_file_observed_bytes"] = observed.st_size
            record["original_file_epoch"] = list(_epoch(observed))
            record["partial_path_matches_original_fd"] = None
            if record["partial_path"] is not None:
                try:
                    record["partial_path_matches_original_fd"] = (
                        _epoch(os.stat(partial, dir_fd=source.fd, follow_symlinks=False)) == _epoch(observed))
                except OSError:
                    record["partial_path_matches_original_fd"] = False
            with contextlib.suppress(OSError):
                os.fchmod(partial_fd, 0o444)
            os.close(partial_fd)
        for directory in (source, target):
            if directory is not None:
                directory.close()
        record["elapsed_s"] = max(0, clock() - record["started_monotonic"])
        record["received_prefix_sha256"] = hashes["sha256"].hexdigest()
        record["received_prefix_sha384"] = hashes["sha384"].hexdigest()
        _write_json(output, f"asset-{index:02d}.json", record)
    if original_error is not None:
        raise AssetPreparationError("original asset acquisition failed: " + str(original_error)[:2048]) from original_error
    return record


def _worker_command(index, output, staging, deadline):
    return [sys.executable, "-I", "-B", str(Path(__file__).resolve()), "--output-dir", str(output),
            "--_asset", str(index), "--_staging", staging, "--_deadline", repr(deadline)]


def _dispatch(index, output, staging, inputs, root, *, clock, deadline):
    argv = _worker_command(index, output.path, staging, deadline)
    _write_json(output, f"asset-{index:02d}.dispatch.json", {"argv": argv,
                "started_monotonic": clock(), "deadline_monotonic": deadline,
                "inputs": [pin.descriptor() for pin in inputs]})
    begun, timed_out = clock(), False
    stdout = os.open(f"asset-{index:02d}.stdout", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=output.fd)
    stderr = os.open(f"asset-{index:02d}.stderr", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=output.fd)
    process = None
    try:
        # Inherit the original outer group: do not detach a DNS/network child.
        process = subprocess.Popen(argv, cwd=root.path, stdin=subprocess.DEVNULL,
            stdout=stdout, stderr=stderr, start_new_session=False)
        owner = {"pid": process.pid, "outer_pgid": os.getpgrp(), "child_pgid": None,
                 "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
                 "controller_uid": os.getuid(), "controller_gid": os.getgid(),
                 "child_proc_stat": None}
        try:
            owner["child_pgid"] = os.getpgid(process.pid)
            owner["child_proc_stat"] = Path(f"/proc/{process.pid}/stat").read_text()
        except ProcessLookupError:
            pass
        except FileNotFoundError:
            pass
        try:
            process.wait(timeout=_remaining(clock, deadline))
        except subprocess.TimeoutExpired:
            timed_out = True
            process.kill()
            process.wait(timeout=TEARDOWN_SECONDS)
        terminal = {**owner, "returncode": process.returncode, "timed_out": timed_out,
                    "elapsed_s": clock() - begun,
                    "child_inherits_original_group": owner["child_pgid"] == owner["outer_pgid"]
                        if owner["child_pgid"] is not None else None}
        for name, fd in (("stdout", stdout), ("stderr", stderr)):
            size = os.fstat(fd).st_size
            terminal[name + "_bytes"] = size
            _require(size <= RECORD_BYTES, "original worker output exceeds metadata cap")
            os.fsync(fd)
        _write_json(output, f"asset-{index:02d}.terminal.json", terminal)
        _require(not timed_out, "original model worker timeout")
        if process.returncode:
            try:
                with os.fdopen(os.open(f"asset-{index:02d}.json", os.O_RDONLY | os.O_NOFOLLOW,
                                       dir_fd=output.fd), "rb") as stream:
                    detail = _json(stream.read(RECORD_BYTES + 1))["error"]["message"]
            except (OSError, KeyError, ValueError):
                detail = "original model worker returned nonzero without a complete asset observation"
            raise AssetPreparationError(detail)
        with os.fdopen(os.open(f"asset-{index:02d}.json", os.O_RDONLY | os.O_NOFOLLOW,
                               dir_fd=output.fd), "rb") as stream:
            result = _json(stream.read(RECORD_BYTES + 1))
        _require(result["status"] == "downloaded" and result["index"] == index,
                 "original worker observation is incomplete")
        return result
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait(timeout=TEARDOWN_SECONDS)
        os.close(stdout)
        os.close(stderr)


def prepare_ci_model_assets(*, project_root, output_dir, opener=None, clock=None):
    """Prepare the fixed domain. An injected opener is a local unit-test seam."""
    clock = clock or time.monotonic
    _require(os.name == "posix", "physical CI acquisition requires POSIX directory descriptors")
    started = clock()
    root = _Root(project_root)
    try:
        with contextlib.ExitStack() as stack:
            rows, inputs = _inventory(root, stack)
            try:
                reused = [_existing(root, row) for row in rows]
            except OSError as error:
                raise AssetPreparationError("model path is not physical or became a symlink/alias") from error
            output = _observation_output(stack, output_dir, fresh=True)
            staging = "models/.ci-acquisition-" + uuid.uuid4().hex[:16]
            stage = stack.enter_context(contextlib.closing(_Directory(root, staging, create=True, exclusive=True)))
            results = []
            try:
                for index, row in enumerate(rows):
                    remaining = _remaining(clock, started + TOTAL_SECONDS)
                    if reused[index]:
                        _require(_existing(root, row), "verified existing object disappeared")
                        record = {"index": index, "asset": row, "status": "reused"}
                        _write_json(output, f"asset-{index:02d}.json", record)
                    else:
                        _require(remaining > TEARDOWN_SECONDS, "overall acquisition deadline lacks teardown reserve")
                        deadline = min(clock() + OBJECT_SECONDS - TEARDOWN_SECONDS,
                                       started + TOTAL_SECONDS - TEARDOWN_SECONDS)
                        if opener is not None:
                            record = _download(root, row, index, output, staging, inputs,
                                opener=opener, clock=clock, deadline=deadline)
                        else:
                            record = _dispatch(index, output, staging, inputs, root, clock=clock, deadline=deadline)
                    results.append({"index": index, "path": row["path"], "status": record["status"],
                                    "size_bytes": row["size_bytes"], "sha256": row["sha256"], "sha384": row["sha384"]})
                for pin in inputs:
                    pin.check()
                root.check()
                _remaining(clock, started + TOTAL_SECONDS)
                report = {"schema_version": 1, "status": "complete", "hardware_acceptance": False,
                          "requires_original_exit_zero": True,
                          "assets": results, "inputs": [pin.descriptor() for pin in inputs],
                          "elapsed_s": clock() - started}
                _write_json(output, "report.json", report)
                _remaining(clock, started + TOTAL_SECONDS)
                return report
            except BaseException as error:
                message, shortened = _bounded_text(error, 2048)
                _write_json(output, "failed.json", {"status": "failed", "hardware_acceptance": False,
                    "completed_assets": results, "elapsed_s": clock() - started,
                    "error_type": type(error).__name__, "error": message, "error_truncated": shortened})
                raise
    finally:
        root.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--_asset", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--_staging", help=argparse.SUPPRESS)
    parser.add_argument("--_deadline", type=float, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        if args._asset is None:
            _require(args._staging is None and args._deadline is None, "internal asset arguments are incomplete")
            report = prepare_ci_model_assets(project_root=ROOT, output_dir=args.output_dir)
            print(json.dumps({"status": report["status"], "assets": len(report["assets"])}))
        else:
            _require(0 <= args._asset < 8 and type(args._staging) is str and
                re.fullmatch(r"models/\.ci-acquisition-[0-9a-f]{16}", args._staging) and
                args._deadline is not None and math.isfinite(args._deadline) and
                0 < args._deadline - time.monotonic() <= OBJECT_SECONDS, "internal original asset bounds drifted")
            with contextlib.ExitStack() as stack:
                root = stack.enter_context(contextlib.closing(_Root(ROOT)))
                rows, inputs = _inventory(root, stack)
                output = _observation_output(stack, args.output_dir, fresh=False)
                result = _download(root, rows[args._asset], args._asset, output, args._staging, inputs,
                                   opener=_network_open, clock=time.monotonic, deadline=args._deadline)
                print(json.dumps({"status": result["status"], "index": args._asset}))
        return 0
    except Exception as error:
        message, shortened = _bounded_text(error, 2048)
        print(json.dumps({"status": "failed", "error_type": type(error).__name__,
                          "error": message, "error_truncated": shortened}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
