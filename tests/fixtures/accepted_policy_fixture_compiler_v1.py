"""Fixed, bounded compiler support for the artificial custody engine only."""
import json
import math
import hashlib
import os
from pathlib import Path
import re
import struct
import socket
import stat
import time
import signal
from urllib.parse import quote

from publication_operational_request_domain_v1 import canonical_json_v1

SOURCE_LIMIT = 8 * 1024 * 1024
STRING_LIMIT = 1024 * 1024
TABLE_LIMIT = 4096


class FixtureCompilerError(RuntimeError):
    def __init__(self, *causes):
        self.causes = list(causes)
        super().__init__(", ".join(self.causes))


def _export_member_open(path):
    """Fresh exclusive member file; the 2.10 C6 runner alone may replace this."""
    return path.open("xb")


def capture_export_v1(read, output_dir):
    """Keep originals in fresh files. Passing capture never accepts an ELF."""
    output = Path(output_dir)
    if output.resolve(strict=True) != output or not output.is_dir():
        raise FixtureCompilerError("export_output_not_physical")
    causes, members, header_prefix = [], {}, bytearray()
    header_written = False
    facts = {"complete": False, "header": None, "members": members,
             "client_stdout_eof": False, "observed_bytes": 0}
    def fail(cause):
        if cause not in causes:
            causes.append(cause)
    def exact(count):
        blocks, used = [], 0
        while used < count:
            block = read(min(65536, count-used))
            if type(block) is not bytes or len(block) > min(65536, count-used):
                raise FixtureCompilerError("export_read_contract")
            facts["observed_bytes"] += len(block)
            if not block:
                raise FixtureCompilerError("export_truncated")
            if len(block) > 65536 - len(header_prefix):
                raise FixtureCompilerError("export_metadata_bound")
            header_prefix.extend(block)
            blocks.append(block)
            used += len(block)
        return b"".join(blocks)
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise FixtureCompilerError("export_duplicate_key")
            result[key] = value
        return result
    def descriptor(value, limit):
        if (type(value) is not dict or type(value.get("size_bytes")) is not int
                or not 0 <= value["size_bytes"] <= limit
                or type(value.get("sha256")) is not str
                or re.fullmatch("[0-9a-f]{64}", value["sha256"]) is None):
            raise FixtureCompilerError("export_member_bound")
        return value["size_bytes"]
    try:
        prefix = exact(12)
        if prefix[:8] != b"VASTCE1\n":
            raise FixtureCompilerError("export_magic")
        length = struct.unpack(">I", prefix[8:])[0]
        if not 1 <= length <= 65524:
            raise FixtureCompilerError("export_metadata_bound")
        raw = exact(length)
        header_file = (output / "export.header.original").open("xb")
        try:
            with header_file as file:
                try:
                    if file.write(prefix + raw) != 12 + length:
                        raise FixtureCompilerError("export_header_short_write")
                    file.flush()
                    os.fsync(file.fileno())
                    header_written = True
                except BaseException as error:
                    for code in (error.causes if isinstance(error, FixtureCompilerError)
                                 else ["export_" + type(error).__name__]):
                        fail(code)
            facts["header_close_completed"] = True
        except BaseException as error:
            facts["header_close_completed"] = False
            fail("export_close_" + type(error).__name__)
        if causes:
            raise FixtureCompilerError(*causes)
        header = json.loads(raw.decode("ascii"), object_pairs_hook=unique)
        if (type(header) is not dict or header.get("schema_version") != 1
                or type(header.get("schema_version")) is not int
                or header.get("artifact_kind") != "vast_fixture_compiler_export_v1"
                or json.dumps(header, ensure_ascii=True, sort_keys=True,
                    separators=(",", ":"), allow_nan=False).encode("ascii") != raw):
            raise FixtureCompilerError("export_header")
        source, child, elf = header.get("source"), header.get("compiler"), header.get("elf")
        descriptor(source, SOURCE_LIMIT)
        if type(child) is not dict or type(elf) is not dict:
            raise FixtureCompilerError("export_header")
        specs = (("stdout", child.get("stdout"), 1048576, "compiler.stdout.original"),
                 ("stderr", child.get("stderr"), 1048576, "compiler.stderr.original"),
                 ("elf", elf, 16777216, "engine.unaccepted"))
        if sum(descriptor(value, limit) for _, value, limit, _ in specs) + length + 12 > 18939904:
            raise FixtureCompilerError("export_total_bound")
        facts["header"] = header
        for name, value, _, filename in specs:
            row = {"size_bytes": 0, "persisted": False, "complete": False, "sha256": None,
                   "observed_bytes": 0, "observed_sha256": None, "close_completed": False}
            members[name] = row
            digest, observed, remaining = hashlib.sha256(), hashlib.sha256(), value["size_bytes"]
            file = _export_member_open(output / filename)
            interrupted, extent_known = False, True
            try:
                with file:
                    try:
                        while remaining:
                            block = read(min(65536, remaining))
                            if type(block) is not bytes or len(block) > min(65536, remaining):
                                raise FixtureCompilerError("export_read_contract")
                            facts["observed_bytes"] += len(block)
                            if not block:
                                raise FixtureCompilerError("export_truncated")
                            row["observed_bytes"] += len(block)
                            observed.update(block)
                            try:
                                written = file.write(block)
                            except BaseException:
                                extent_known = False
                                raise
                            if type(written) is not int or not 0 <= written <= len(block):
                                extent_known = False
                                raise FixtureCompilerError("export_member_write_extent_unknown")
                            row["size_bytes"] += written
                            digest.update(memoryview(block)[:written])
                            if written != len(block):
                                raise FixtureCompilerError("export_member_short_write")
                            remaining -= len(block)
                    except BaseException as error:
                        interrupted = True
                        for code in (error.causes if isinstance(error, FixtureCompilerError)
                                     else ["export_" + type(error).__name__]):
                            fail(code)
                    finally:
                        row["observed_sha256"] = observed.hexdigest()
                        row["sha256"] = digest.hexdigest() if extent_known else None
                        if not extent_known:
                            row["size_bytes"] = None
                        try:
                            file.flush()
                            os.fsync(file.fileno())
                            row["persisted"] = extent_known
                        except BaseException as error:
                            interrupted = True
                            fail("export_persistence_" + type(error).__name__)
                row["close_completed"] = True
            except BaseException as error:
                interrupted = True
                fail("export_close_" + type(error).__name__)
            if interrupted:
                raise FixtureCompilerError(*causes)
            row["complete"] = True
            if row["sha256"] != value["sha256"]:
                fail("export_" + name + "_hash")
        trailing = read(1)
        facts["observed_bytes"] += len(trailing)
        facts["client_stdout_eof"] = trailing == b""
        if trailing != b"":
            fail("export_trailing_bytes")
        facts["complete"] = not causes
    except FixtureCompilerError as error:
        for cause in error.causes:
            fail(cause)
    except (OSError, ValueError, TypeError, RecursionError) as error:
        fail("export_" + type(error).__name__)
    if not header_written and header_prefix:
        facts["header_prefix_persisted"] = False
        facts["header_prefix_close_completed"] = False
        try:
            with (output / "export.prefix.original").open("xb") as file:
                try:
                    if file.write(header_prefix) != len(header_prefix):
                        raise OSError("short prefix write")
                    file.flush()
                    os.fsync(file.fileno())
                    facts["header_prefix_persisted"] = True
                except BaseException as error:
                    fail("export_prefix_persistence_" + type(error).__name__)
            facts["header_prefix_close_completed"] = True
        except BaseException as error:
            fail("export_prefix_close_" + type(error).__name__)
    if causes:
        error = FixtureCompilerError(*causes)
        error.facts = facts
        raise error
    return facts


def _json_bound(value, *, depth=0, ancestors=None, nodes=None):
    """Count before serialization; reject cycles, huge scalars and fanout first."""
    if ancestors is None:
        ancestors, nodes = set(), [0]
    nodes[0] += 1
    if depth > 32 or nodes[0] > 65536:
        raise ValueError("fixture JSON depth/node bound exceeded")
    if type(value) is str:
        if len(value) > STRING_LIMIT:
            raise ValueError("fixture JSON string bound exceeded")
        size = 2
        for char in value:
            point = ord(char)
            size += (2 if char in '\\"\b\f\n\r\t' else
                     6 if point < 32 or 127 <= point <= 65535 else 12 if point > 65535 else 1)
            if size > SOURCE_LIMIT:
                raise ValueError("fixture JSON byte bound exceeded")
        return size
    if value is None or type(value) is bool:
        return 5
    if type(value) is int:
        if value.bit_length() > 64:
            raise ValueError("fixture JSON integer bound exceeded")
        return 21
    if type(value) is float and math.isfinite(value):
        return 32
    if type(value) not in (dict, list) or len(value) > TABLE_LIMIT or id(value) in ancestors:
        raise ValueError("fixture JSON type/container bound exceeded")
    ancestors.add(id(value))
    try:
        size = 2
        items = value.items() if type(value) is dict else ((None, item) for item in value)
        for key, item in items:
            if type(value) is dict:
                if type(key) is not str:
                    raise ValueError("fixture JSON requires string keys")
                size += _json_bound(key, depth=depth+1, ancestors=ancestors, nodes=nodes) + 1
            size += _json_bound(item, depth=depth+1, ancestors=ancestors, nodes=nodes) + 1
            if size > SOURCE_LIMIT:
                raise ValueError("fixture JSON byte bound exceeded")
        return size
    finally:
        ancestors.remove(id(value))


def _table_bound(name, mapping, inspection):
    if name not in ("image_replies", "probe_replies"):
        raise ValueError("fixed fixture reply table required")
    if mapping is None:
        return 128
    if type(mapping) is not dict or len(mapping) > TABLE_LIMIT:
        raise ValueError("fixture reply table count/type bound exceeded")
    size = 128
    for key, value in mapping.items():
        if type(key) is not str or len(key) > 4096 or not key.isascii() or type(value) is not dict:
            raise ValueError("fixture reply key/object bound exceeded")
        # JSON-in-C escapes each JSON quote/backslash once more. This upper
        # bound is reserved before canonical JSON or C string construction.
        size += 64 + 2 * (_json_bound(key) + _json_bound(value) + (2 if inspection else 0))
        if size > SOURCE_LIMIT:
            raise ValueError("fixture source byte bound exceeded")
    return size


def _reply_table(name, mapping, *, inspection):
    _table_bound(name, mapping, inspection)
    rows = []
    used = 128
    for key, value in sorted((mapping or {}).items()):
        if type(key) is not str or not key.isascii() or type(value) is not dict:
            raise ValueError("fixture image/probe reply requires ASCII key and object")
        raw = canonical_json_v1([value] if inspection else value).decode("ascii")
        key_literal, raw_literal = json.dumps(key), json.dumps(raw)
        row_size = 9 + len(key_literal) + len(raw_literal)
        if used + row_size > SOURCE_LIMIT:
            raise ValueError("fixture source byte bound exceeded")
        rows.append("    {" + key_literal + ", " + raw_literal + "},")
        used += row_size
    return "static const struct reply " + name + "[] = {\n" + "\n".join(rows) + "\n    {NULL, NULL}\n};"


def build_fixture_source_v1(template, state_path, image_inspections=None, device_probes=None):
    """Validate both tables before any canonicalization or output allocation."""
    if type(template) is not str or len(template) > STRING_LIMIT or not template.isascii() or template.count("/* FIXTURE_REPLY_TABLES */") != 1:
        raise ValueError("fixed bounded ASCII fixture template required")
    path = str(state_path)
    if not path.isascii() or len(path) > 4096 or "\0" in path:
        raise ValueError("fixture STATE_FILE bound exceeded")
    upper = len(template) + 2 * _json_bound(path) + 128
    upper += _table_bound("image_replies", image_inspections, True)
    upper += _table_bound("probe_replies", device_probes, False)
    if upper > SOURCE_LIMIT:
        raise ValueError("combined fixture source byte bound exceeded")
    parts, used = [], 0
    def append(text):
        nonlocal used
        if len(text) > SOURCE_LIMIT - used:
            raise ValueError("fixture source append bound exceeded")
        parts.append(text.encode("ascii"))
        used += len(text)
    append("#define STATE_FILE " + json.dumps(path) + "\n")
    append("#define DAEMON_ID " + json.dumps('"fixture-daemon-1"') + "\n")
    before, after = template.split("/* FIXTURE_REPLY_TABLES */")
    append(before)
    append(_reply_table("image_replies", image_inspections, inspection=True))
    append("\n")
    append(_reply_table("probe_replies", device_probes, inspection=False))
    append(after)
    return b"".join(parts)


class _DockerClientV1:
    """One fixed Linux Unix-socket transport; no retry or container lifecycle.

    Metadata charges each wire byte AND its retained raw-file copy (2x). This
    is not a Python heap accounting claim. Upgraded data belongs to the caller's
    separately bounded export/mux capture, not the HTTP metadata budget.
    Injected sockets/clocks are controlled-test seams, never runtime evidence.
    The root owner binds the finite endpoint inventory and actual engine ID.
    written_bytes is only a confirmed write-return prefix; persisted_bytes is
    its fsync-confirmed lower bound. A write exception leaves any unreturned
    extent explicitly unknown, even if final flush/close subsequently succeeds.
    """
    LIMIT = 262144
    ORDINARY_LIMIT = 196608
    HEADER_LIMIT = 8192
    RPC_LIMIT = 23
    API_VERSION = "1.55"

    def __init__(self, output_dir, absolute_deadline_ns, *, socket_factory=None, clock=None):
        self.output = Path(output_dir)
        if self.output.resolve(strict=True) != self.output or not self.output.is_dir():
            raise FixtureCompilerError("docker_output_not_physical")
        if type(absolute_deadline_ns) is not int or absolute_deadline_ns <= 0:
            raise FixtureCompilerError("docker_deadline")
        self.deadline = absolute_deadline_ns
        self.clock = clock if clock is not None else time.monotonic_ns
        self.factory = socket_factory if socket_factory is not None else self._socket
        self.last_clock = None
        self.causes = []
        self.facts = {"attempts": 0, "metadata_bytes": 0, "rpc": [],
                      "controlled_socket": socket_factory is not None,
                      "controlled_clock": clock is not None,
                      "metadata_definition": "serialized_request_observed_reply_plus_original_copy_2x",
                      "runtime_acceptance": False}

    @staticmethod
    def _socket():
        return socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)

    def _observe_endpoint(self):
        rows = []
        for path in ("/", "/run", "/run/docker.sock"):
            info = os.lstat(path)
            kind = stat.S_ISSOCK if path == "/run/docker.sock" else stat.S_ISDIR
            if not kind(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o002:
                raise FixtureCompilerError("docker_socket_metadata")
            # Parent replacement also requires write; group write is refused
            # for ancestors. The socket's intended docker-group write is kept.
            if path != "/run/docker.sock" and info.st_mode & 0o020:
                raise FixtureCompilerError("docker_socket_metadata")
            rows.append((info.st_dev, info.st_ino, info.st_uid, info.st_gid,
                         info.st_mode, info.st_ctime_ns if path.endswith(".sock") else None))
        return tuple(rows)

    def _cause(self, code):
        if code not in self.causes:
            self.causes.append(code)

    def _error(self, code):
        self._cause(code)
        error = FixtureCompilerError(*self.causes)
        error.facts = self.facts
        return error

    def _remaining(self, deadline, sock=None):
        now = self.clock()
        if (type(now) is not int or now < 0 or
                self.last_clock is not None and now < self.last_clock):
            raise self._error("docker_clock")
        self.last_clock = now
        if now >= deadline:
            raise self._error("docker_deadline")
        remaining = (deadline - now) / 1_000_000_000
        if sock is not None:
            sock.settimeout(remaining)
        return remaining

    def request(self, method, path, body=None, deadline_ns=None, upgrade=False, *, cleanup=False):
        """Return strict JSON, None for 204, or an owned attach Duplex.

        A failed ordinary call permanently blocks more ordinary work. Only
        explicitly marked owner-approved containment/inspection can use the
        reserved 64KiB, still within the same 256KiB/23-call/absolute bounds.
        Every returned Duplex must be closed by its owning caller.
        """
        if (method not in ("GET", "POST") or type(method) is not str or
                type(path) is not str or not path.startswith("/") or path.startswith("//") or
                len(path) > 8192 or not path.isascii() or
                any(ord(char) < 33 or ord(char) > 126 for char in path) or
                "#" in path or "\\" in path or path.startswith("/v1.") or
                type(upgrade) is not bool or type(cleanup) is not bool):
            raise self._error("docker_request")
        if deadline_ns is not None and (type(deadline_ns) is not int or deadline_ns <= 0):
            raise self._error("docker_deadline")
        deadline = min(self.deadline, deadline_ns) if deadline_ns is not None else self.deadline
        if self.causes and not cleanup:
            raise self._error("docker_sticky_failure")
        if self.facts["attempts"] >= self.RPC_LIMIT:
            raise self._error("docker_rpc_cap")
        self.facts["attempts"] += 1
        number = self.facts["attempts"]
        row = {"number": number, "complete": False, "status": None,
               "request_persisted": False, "reply_persisted": False,
               "request_close_completed": False, "reply_close_completed": False,
               "request_bytes": 0, "reply_observed_bytes": 0,
               "request_send_complete": False, "causes": [],
               "request_written_bytes": 0, "request_persisted_bytes": 0,
               "reply_written_bytes": 0, "reply_persisted_bytes": 0,
               "request_write_extent_unknown": False, "reply_write_extent_unknown": False,
               "request_persistence_failed": False, "reply_persistence_failed": False,
               "reply_retained_bytes": 0, "reply_eof": False,
               "peer": None, "epoch_before": None, "epoch_after": None,
               "socket_closed": False, "upgraded": False}
        self.facts["rpc"].append(row)
        cap = self.LIMIT if cleanup else self.ORDINARY_LIMIT
        sock = request_file = reply_file = duplex = None
        failed = False
        epoch = None

        def charge(data):
            if len(data) * 2 > cap - self.facts["metadata_bytes"]:
                raise self._error("docker_metadata_cap")
            self.facts["metadata_bytes"] += 2 * len(data)

        def sync(file, key):
            role = key.split("_", 1)[0]
            if row[role + "_persistence_failed"]:
                return  # A failed persistence operation is never retried/recovered.
            for operation, invoke in (("flush", file.flush),
                                      ("fsync", lambda: os.fsync(file.fileno()))):
                try:
                    invoke()
                except (OSError, ValueError, TypeError) as error:
                    row[key] = False
                    row[role + "_persistence_failed"] = True
                    raise self._error("docker_" + role + "_" + operation + "_" + type(error).__name__) from error
            row[role + "_persisted_bytes"] = row[role + "_written_bytes"]
            row[key] = not row[role + "_write_extent_unknown"]

        def write(file, data, role):
            row[role + "_persisted"] = False
            try:
                written = file.write(data)
            except (OSError, ValueError, TypeError) as error:
                row[role + "_write_extent_unknown"] = True
                raise self._error("docker_" + role + "_write_" + type(error).__name__) from error
            if type(written) is not int or not 0 <= written <= len(data):
                row[role + "_write_extent_unknown"] = True
                raise self._error("docker_" + role + "_write_contract")
            row[role + "_written_bytes"] += written
            if role == "reply":
                row["reply_retained_bytes"] = row["reply_written_bytes"]
            if written != len(data):
                raise self._error("docker_" + role + "_short_write")

        def receive(count):
            if count * 2 > cap - self.facts["metadata_bytes"]:
                raise self._error("docker_metadata_cap")
            self._remaining(deadline, sock)
            block = sock.recv(count)
            if type(block) is not bytes or len(block) > count:
                raise self._error("docker_read_contract")
            row["reply_observed_bytes"] += len(block)
            if not block:
                row["reply_eof"] = True
                self._remaining(deadline)
                return block
            charge(block)
            write(reply_file, block, "reply")
            self._remaining(deadline)
            return block

        def exact(count):
            if count * 2 > cap - self.facts["metadata_bytes"]:
                raise self._error("docker_metadata_cap")
            blocks, used = [], 0
            while used < count:
                block = receive(min(65536, count - used))
                if not block:
                    raise self._error("docker_http_truncated")
                blocks.append(block)
                used += len(block)
            return b"".join(blocks)

        def line(limit):
            data = bytearray()
            while not data.endswith(b"\r\n"):
                if len(data) >= limit:
                    raise self._error("docker_http_chunk")
                block = receive(1)
                if not block:
                    raise self._error("docker_http_truncated")
                data.extend(block)
            sync(reply_file, "reply_persisted")
            return bytes(data)

        try:
            self._remaining(deadline)
            upper = _json_bound(body) if body is not None else 0
            # Reserve the whole HTTP head (including decimal length) BEFORE
            # allocating canonical JSON or the concatenated request bytes.
            if 2 * (upper + len(method) + len(path) + 256) > cap - self.facts["metadata_bytes"]:
                raise self._error("docker_metadata_cap")
            if body is not None:
                encoded = json.dumps(body, ensure_ascii=True, sort_keys=True,
                                     separators=(",", ":"), allow_nan=False).encode("ascii")
            else:
                encoded = b""
            connection = b"Upgrade\r\nUpgrade: tcp" if upgrade else b"close"
            request = (method.encode("ascii") + b" /v1.55" + path.encode("ascii") +
                       b" HTTP/1.1\r\nHost: localhost\r\nConnection: " + connection +
                       b"\r\nContent-Length: " + str(len(encoded)).encode("ascii") + b"\r\n" +
                       (b"Content-Type: application/json\r\n" if body is not None else b"") +
                       b"\r\n" + encoded)
            charge(request)
            request_file = (self.output / ("RPC%02d.request.original" % number)).open("xb")
            row["request_bytes"] = len(request)
            write(request_file, request, "request")
            sync(request_file, "request_persisted")
            reply_file = (self.output / ("RPC%02d.reply.original" % number)).open("xb")
            epoch = self._observe_endpoint()
            row["epoch_before"] = epoch
            sock = self.factory()
            self._remaining(deadline, sock)
            sock.connect("/run/docker.sock")
            self._remaining(deadline, sock)
            peer = sock.getsockopt(socket.SOL_SOCKET, 17, 12)  # Linux SO_PEERCRED
            if type(peer) is not bytes or len(peer) != 12:
                raise self._error("docker_peer")
            pid, uid, gid = struct.unpack("3i", peer)
            row["peer"] = {"pid": pid, "uid": uid, "gid": gid}
            if pid <= 0 or uid != 0 or gid < 0:
                raise self._error("docker_peer")
            self._remaining(deadline, sock)
            sock.sendall(request)
            row["request_send_complete"] = True
            self._remaining(deadline)
            header = bytearray()
            # Byte reads prevent consuming attach stream bytes before upgrade
            # ownership transfers. Retention is capped before each read/append.
            while not header.endswith(b"\r\n\r\n"):
                if len(header) >= self.HEADER_LIMIT:
                    raise self._error("docker_http_header_cap")
                block = receive(1)
                if not block:
                    raise self._error("docker_http_truncated")
                header.extend(block)
            sync(reply_file, "reply_persisted")
            lines = bytes(header[:-4]).split(b"\r\n")
            match = re.fullmatch(rb"HTTP/1\.1 ([0-9]{3}) [ -~]*", lines[0])
            fields = {}
            if match is None:
                raise self._error("docker_http_headers")
            status = int(match[1])
            row["status"] = status
            for item in lines[1:]:
                name, colon, value = item.partition(b":")
                if (not colon or not re.fullmatch(rb"[!#$%&'*+.^_`|~0-9A-Za-z-]+", name) or
                        any(char < 32 or char > 126 for char in value)):
                    raise self._error("docker_http_headers")
                key = name.decode("ascii").lower()
                if key in fields:
                    raise self._error("docker_http_headers")
                fields[key] = value.strip(b" ").decode("ascii")
            if ("content-encoding" in fields or
                    "content-length" in fields and "transfer-encoding" in fields):
                raise self._error("docker_http_headers")
            if upgrade and status == 101:
                if (fields.get("connection", "").lower() != "upgrade" or
                        fields.get("upgrade", "").lower() != "tcp" or
                        "content-length" in fields or "transfer-encoding" in fields):
                    raise self._error("docker_http_upgrade")
                row["epoch_after"] = self._observe_endpoint()
                if row["epoch_after"] != epoch:
                    raise self._error("docker_socket_drift")
                self._remaining(deadline)
                duplex = self.Duplex(self, sock, deadline, row, epoch)
                row["upgraded"] = True
                result = duplex
            else:
                if "transfer-encoding" in fields:
                    if fields["transfer-encoding"].lower() != "chunked":
                        raise self._error("docker_http_headers")
                    chunks = []
                    while True:
                        raw_size = line(128)
                        if not re.fullmatch(rb"[0-9A-Fa-f]{1,16}\r\n", raw_size):
                            raise self._error("docker_http_chunk")
                        size = int(raw_size[:-2], 16)
                        if size == 0:
                            if line(2) != b"\r\n":
                                raise self._error("docker_http_chunk")
                            break
                        chunks.append(exact(size))
                        if exact(2) != b"\r\n":
                            raise self._error("docker_http_chunk")
                    data = b"".join(chunks)
                elif "content-length" in fields:
                    length = fields["content-length"]
                    if not re.fullmatch("[0-9]{1,10}", length):
                        raise self._error("docker_http_headers")
                    data = exact(int(length))
                elif status == 204:
                    data = b""
                else:
                    raise self._error("docker_http_headers")
                if receive(1):
                    raise self._error("docker_http_extra")
                sync(reply_file, "reply_persisted")
                row["epoch_after"] = self._observe_endpoint()
                if row["epoch_after"] != epoch:
                    raise self._error("docker_socket_drift")
                if upgrade:
                    raise self._error("docker_http_upgrade")
                if not 200 <= status <= 299:
                    raise self._error("docker_http_status")
                def unique(pairs):
                    value = {}
                    for key, item in pairs:
                        if key in value:
                            raise ValueError("duplicate JSON field")
                        value[key] = item
                    return value
                try:
                    result = None if status == 204 and not data else json.loads(
                        data.decode("utf-8"), object_pairs_hook=unique,
                        parse_constant=lambda value: (_ for _ in ()).throw(ValueError("nonfinite")))
                    if result is not None and type(result) not in (dict, list):
                        raise ValueError("Docker object/list required")
                except (ValueError, UnicodeError, RecursionError) as error:
                    raise self._error("docker_http_json") from error
                self._remaining(deadline)
        except FixtureCompilerError as error:
            failed = True
            for cause in error.causes:
                self._cause(cause)
                if cause not in row["causes"]:
                    row["causes"].append(cause)
        except (OSError, ValueError, TypeError, RecursionError, OverflowError) as error:
            failed = True
            self._cause("docker_io_" + type(error).__name__)
            row["causes"].append("docker_io_" + type(error).__name__)
        finally:
            for file, key in ((request_file, "request_persisted"), (reply_file, "reply_persisted")):
                if file is not None:
                    role = key.split("_", 1)[0]
                    try:
                        sync(file, key)
                    except FixtureCompilerError as error:
                        failed = True
                        for code in error.causes:
                            self._cause(code)
                            if code not in row["causes"]:
                                row["causes"].append(code)
                    except (OSError, ValueError) as error:
                        failed = True
                        code = "docker_" + role + "_persistence_" + type(error).__name__
                        self._cause(code)
                        row["causes"].append(code)
                    try:
                        file.close()
                        row[role + "_close_completed"] = True
                    except (OSError, ValueError, TypeError) as error:
                        failed = True
                        code = "docker_" + role + "_close_" + type(error).__name__
                        self._cause(code)
                        row["causes"].append(code)
            if sock is not None and (duplex is None or failed):
                try:
                    sock.close()
                    row["socket_closed"] = True
                except (OSError, ValueError, TypeError) as error:
                    failed = True
                    self._cause("docker_socket_close_" + type(error).__name__)
                    row["causes"].append("docker_socket_close_" + type(error).__name__)
            try:
                self._remaining(deadline)
            except FixtureCompilerError as error:
                failed = True
                for code in error.causes:
                    self._cause(code)
                    if code not in row["causes"]:
                        row["causes"].append(code)
        # Cleanup success does not erase a previous initiating cause. Only
        # failures added during this call prevent returning its own evidence.
        if not row["epoch_after"] or not row["request_persisted"] or not row["reply_persisted"]:
            raise self._error(self.causes[0] if self.causes else "docker_incomplete")
        if duplex is None and not row["socket_closed"]:
            raise self._error(self.causes[0] if self.causes else "docker_incomplete")
        if failed or self.causes and not cleanup:
            raise self._error(self.causes[0])
        row["complete"] = True
        return result

    class Duplex:
        """Owned upgraded socket; caller captures mux data and owns closure."""
        def __init__(self, owner, sock, deadline, row, epoch):
            self.owner, self.sock = owner, sock
            self.handshake_deadline, self.deadline = deadline, None
            self.row, self.epoch = row, epoch
            self.deferred_error = None
            self.facts = {"sent_bytes": 0, "received_bytes": 0,
                          "write_shutdown": False, "read_eof": False, "closed": False,
                          "data_deadline_ns": None, "data_started": False}

        def arm_data_deadline(self, absolute_ns):
            """Owner supplies start+fixed-work-window, never a renewed duration.

            The handshake deadline remains historical. Only this single arm
            can select the subsequent data phase, within the ORIGINAL owner
            deadline; the fixed orchestrator proves its actual start binding.
            """
            if (type(absolute_ns) is not int or absolute_ns <= 0 or
                    absolute_ns > self.owner.deadline or self.deadline is not None or
                    self.facts["data_started"] or self.facts["closed"]):
                raise self.owner._error("docker_attach_deadline_arm")
            self.owner._remaining(absolute_ns)
            self.deadline = absolute_ns
            self.facts["data_deadline_ns"] = absolute_ns

        def _ready(self):
            if self.deferred_error is not None:
                raise self.owner._error(self.deferred_error.causes[0])
            if self.facts["closed"]:
                raise self.owner._error("docker_attach_closed")
            if self.deadline is None:
                raise self.owner._error("docker_attach_unarmed")
            self.owner._remaining(self.deadline, self.sock)
            self.facts["data_started"] = True

        def sendall(self, data):
            if (type(data) is not bytes or self.facts["write_shutdown"] or
                    len(data) > SOURCE_LIMIT + 65536 - self.facts["sent_bytes"]):
                raise self.owner._error("docker_attach_input")
            try:
                self._ready()
                self.sock.sendall(data)
                self.facts["sent_bytes"] += len(data)
                self.owner._remaining(self.deadline)
            except OSError as error:
                raise self.owner._error("docker_attach_" + type(error).__name__) from error

        def shutdown_write(self):
            try:
                self._ready()
                if self.facts["write_shutdown"]:
                    raise self.owner._error("docker_attach_shutdown")
                self.sock.shutdown(socket.SHUT_WR)
                self.facts["write_shutdown"] = True
                self.owner._remaining(self.deadline)
            except OSError as error:
                raise self.owner._error("docker_attach_" + type(error).__name__) from error

        def read(self, count):
            if type(count) is not int or not 1 <= count <= 65536:
                raise self.owner._error("docker_attach_read_bound")
            try:
                self._ready()
                data = self.sock.recv(count)
                if type(data) is not bytes or len(data) > count:
                    raise self.owner._error("docker_read_contract")
                self.facts["received_bytes"] += len(data)
                self.facts["read_eof"] = not data
                try:
                    self.owner._remaining(self.deadline)
                except FixtureCompilerError as error:
                    self.deferred_error = error
                    if not data:
                        raise
                    # Bytes already returned by recv MUST reach the caller's
                    # bounded original-prefix writer once. No later operation
                    # or close can suppress the sticky late/clock failure.
                return data
            except OSError as error:
                raise self.owner._error("docker_attach_" + type(error).__name__) from error

        def close(self):
            if self.facts["closed"]:
                return
            failure = self.deferred_error
            try:
                self.owner._remaining(self.deadline if self.deadline is not None else self.owner.deadline)
                if self.owner._observe_endpoint() != self.epoch:
                    failure = self.owner._error("docker_socket_drift")
            except (OSError, FixtureCompilerError) as error:
                failure = (error if isinstance(error, FixtureCompilerError) else
                           self.owner._error("docker_attach_epoch_" + type(error).__name__))
            try:
                self.sock.close()
                self.facts["closed"] = self.row["socket_closed"] = True
            except OSError as error:
                self.owner._cause("docker_socket_close_" + type(error).__name__)
                failure = self.owner._error("docker_socket_close_" + type(error).__name__)
            try:
                self.owner._remaining(self.deadline if self.deadline is not None else self.owner.deadline)
            except FixtureCompilerError as error:
                failure = failure or error
            if failure is not None:
                raise self.owner._error(failure.causes[0])


class _CompilerAttachV1:
    """Bounded Docker stdcopy reader; transport owns its single data deadline.

    No frame payload is allocated from its declaration. A read may return a
    prefix before a later error; the error stays sticky through close. These
    capture facts never accept the compiler export or its ELF.
    """
    STDOUT_LIMIT = 18939904
    STDERR_LIMIT = 1048576
    HEADER_LIMIT = 65536

    def __init__(self, duplex, output_dir):
        self.duplex = duplex
        self.causes = []
        self.files = {}
        self.current = None
        self.closed = False
        self.facts = {"complete": False, "wire_complete": False,
            "stdout_eof": False, "stderr_eof": False, "closed": False,
            "frames": 0, "causes": self.causes, "files": {},
            "headers_observed_bytes": 0, "headers_retained_bytes": 0,
            "header_remainder_unknown": False, "write_shutdown": False,
            "duplex_close_attempted": False, "duplex_close_completed": False,
            "duplex_closed": None, "stdout": self._channel(),
            "stderr": self._channel()}
        try:
            output = Path(output_dir)
            if output.resolve(strict=True) != output or not output.is_dir():
                raise FixtureCompilerError("attach_output_not_physical")
            for name in ("attach.headers.original", "client.stderr.original"):
                record = {"open_completed": False, "written_bytes": 0, "persisted_bytes": 0,
                    "write_extent_unknown": False, "flush_completed": False,
                    "fsync_completed": False, "close_completed": False,
                    "size_bytes": None, "sha256": None}
                self.facts["files"][name] = record
                file = (output / name).open("xb", buffering=0)
                self.files[name] = (file, record, hashlib.sha256())
                record.update(open_completed=True, size_bytes=0,
                              sha256=hashlib.sha256(b"").hexdigest())
        except BaseException as error:
            self._fail_error(error, "attach_prefix_open")
            try:
                self.close()
            except FixtureCompilerError:
                pass
            raise self._error() from error

    @staticmethod
    def _channel():
        return {"declared_bytes": 0, "observed_bytes": 0,
                "retained_bytes": 0, "discarded_bytes": None,
                "remainder_unknown": True}

    def _fail(self, code):
        if code not in self.causes:
            self.causes.append(code)

    def _fail_error(self, error, fallback):
        if isinstance(error, FixtureCompilerError):
            for code in error.causes:
                self._fail(code)
        else:
            self._fail(fallback)

    def _error(self):
        error = FixtureCompilerError(*self.causes)
        error.facts = self.facts
        return error

    def _write_prefix(self, name, data):
        file, record, digest = self.files[name]
        try:
            count = file.write(data)
        except BaseException:
            record["write_extent_unknown"] = True
            record["size_bytes"] = record["sha256"] = None
            raise FixtureCompilerError("attach_prefix_write")
        if type(count) is not int or not 0 <= count <= len(data):
            record["write_extent_unknown"] = True
            record["size_bytes"] = record["sha256"] = None
            raise FixtureCompilerError("attach_prefix_write_contract")
        digest.update(data[:count])
        record["written_bytes"] += count
        record["confirmed_prefix_sha256"] = digest.hexdigest()
        if not record["write_extent_unknown"]:
            record["size_bytes"] = record["written_bytes"]
            record["sha256"] = digest.hexdigest()
        if count != len(data):
            raise FixtureCompilerError("attach_prefix_short_write")

    def _retain(self, name, data):
        """Write a retained prefix; its summary follows only confirmed bytes."""
        record = self.files[name][1]
        try:
            self._write_prefix(name, data)
        finally:
            retained = None if record["write_extent_unknown"] else record["written_bytes"]
            if name == "attach.headers.original":
                self.facts["headers_retained_bytes"] = retained
            else:
                self.facts["stderr"]["retained_bytes"] = retained

    def _raw(self, count):
        block = self.duplex.read(count)
        if type(block) is not bytes or len(block) > count:
            raise FixtureCompilerError("attach_read_contract")
        return block

    def _header(self):
        remaining = self.HEADER_LIMIT - self.facts["headers_retained_bytes"]
        if not remaining:
            extra = self._raw(1)
            self.facts["headers_observed_bytes"] += len(extra)
            if extra:
                self.facts["header_remainder_unknown"] = True
                raise FixtureCompilerError("attach_headers_overflow")
            self._wire_eof()
            return
        header = bytearray()
        while len(header) < 8:
            block = self._raw(8 - len(header))
            if not block:
                if not header:
                    self._wire_eof()
                    return
                raise FixtureCompilerError("attach_header_truncated")
            self.facts["headers_observed_bytes"] += len(block)
            # Header capacity is a multiple of eight, including partial frames.
            self._retain("attach.headers.original", block)
            header.extend(block)
        if header[0] not in (1, 2) or header[1:4] != b"\0\0\0":
            raise FixtureCompilerError("attach_header_invalid")
        channel = "stdout" if header[0] == 1 else "stderr"
        length = struct.unpack("!I", header[4:])[0]
        row = self.facts[channel]
        row["declared_bytes"] += length
        self.facts["frames"] += 1
        limit = self.STDOUT_LIMIT if channel == "stdout" else self.STDERR_LIMIT
        if length > limit:
            raise FixtureCompilerError("attach_frame_declaration_bound")
        self.current = [channel, length]

    def _wire_eof(self):
        self.facts["wire_complete"] = True
        self.facts["stdout_eof"] = self.facts["stderr_eof"] = True
        for channel in ("stdout", "stderr"):
            row = self.facts[channel]
            row["discarded_bytes"] = row["observed_bytes"] - row["retained_bytes"]
            row["remainder_unknown"] = False

    def read(self, count):
        if type(count) is not int or not 1 <= count <= 65536:
            self._fail("attach_read_count")
        if self.closed:
            self._fail("attach_closed")
        if self.causes:
            raise self._error()
        result = bytearray()
        try:
            while len(result) < count and not self.facts["wire_complete"]:
                if self.current is None:
                    self._header()
                    if self.current is None:
                        continue
                channel, remaining = self.current
                if not remaining:
                    self.current = None
                    continue
                row = self.facts[channel]
                limit = self.STDOUT_LIMIT if channel == "stdout" else self.STDERR_LIMIT
                capacity = limit - row["retained_bytes"]
                request = min(65536, remaining, capacity + 1)
                if channel == "stdout":
                    request = min(request, count - len(result))
                block = self._raw(request)
                if not block:
                    raise FixtureCompilerError("attach_payload_truncated")
                row["observed_bytes"] += len(block)
                self.current[1] -= len(block)
                kept = block[:capacity]
                if channel == "stdout":
                    result.extend(kept)
                    row["retained_bytes"] += len(kept)
                else:
                    self._retain("client.stderr.original", kept)
                if len(block) > capacity:
                    raise FixtureCompilerError("attach_" + channel + "_overflow")
        except BaseException as error:
            self._fail_error(error, "attach_read")
            if not result:
                raise self._error() from error
        return bytes(result)

    def sendall(self, data):
        if self.closed or self.causes:
            if self.closed:
                self._fail("attach_closed")
            raise self._error()
        try:
            return self.duplex.sendall(data)
        except BaseException as error:
            self._fail_error(error, "attach_send")
            raise self._error() from error

    def shutdown_write(self):
        if self.closed or self.causes:
            if self.closed:
                self._fail("attach_closed")
            raise self._error()
        try:
            self.duplex.shutdown_write()
            self.facts["write_shutdown"] = True
        except BaseException as error:
            self._fail_error(error, "attach_shutdown")
            raise self._error() from error

    def close(self):
        if not self.closed:
            self.closed = True
            if not self.facts["wire_complete"]:
                self._fail("attach_incomplete")
            for file, record, digest in self.files.values():
                try:
                    file.flush()
                    record["flush_completed"] = True
                except BaseException:
                    self._fail("attach_prefix_flush")
                try:
                    os.fsync(file.fileno())
                    record["fsync_completed"] = True
                    record["persisted_bytes"] = record["written_bytes"]
                except BaseException:
                    self._fail("attach_prefix_fsync")
                try:
                    file.close()
                    record["close_completed"] = True
                except BaseException:
                    self._fail("attach_prefix_close")
            self.facts["duplex_close_attempted"] = True
            try:
                self.duplex.close()
                self.facts["duplex_close_completed"] = True
                self.facts["duplex_closed"] = True
            except BaseException as error:
                self._fail_error(error, "attach_duplex_close")
                if getattr(self.duplex, "facts", {}).get("closed") is True:
                    self.facts["duplex_closed"] = True
            self.facts["closed"] = True
            self.facts["complete"] = self.facts["wire_complete"] and not self.causes
        if self.causes:
            raise self._error()


PROVIDER = "nvcr.io/nvidia/deepstream@sha256:c11befa808af8270e8ea0d0d7cc7cabbda08a2f496ee30b95f7acba5dce81759"
# Docker29's containerd image ID is the selected index/manifest identity.
# The config-blob digest and linux/amd64 manifest are distinct pinned objects.
PROVIDER_ID = "sha256:c11befa808af8270e8ea0d0d7cc7cabbda08a2f496ee30b95f7acba5dce81759"
PROVIDER_CONFIG_DIGEST = "sha256:fcdeffe3fbac262b2f2760eba8dcc3243a5edf9bdb09b490dd5a00ac1ea56121"
PROVIDER_PLATFORM_MANIFEST = "sha256:34e56b46f00a2c79acb42bfd4f3a977753607a99179520744389ce40ce96eb59"
PROFILE_SHA256 = "ee45f10961781d812e88d185659b74e893031a4bd4e90d3cce0857d5308ba8cf"


def compiler_container_config_v1(image, *, environment_keys, publisher_path,
        profile_raw, nonce, source_sha256):
    """Build only the selected provider recipe, with gates BEFORE create."""
    if (type(image) is not dict or image.get("Id") != PROVIDER_ID
            or image.get("Os") != "linux" or image.get("Architecture") != "amd64"
            or type(image.get("Config")) is not dict):
        raise FixtureCompilerError("compiler_provider_drift")
    config = image["Config"]
    if config.get("Volumes") is not None and config.get("Volumes") != {}:
        raise FixtureCompilerError("compiler_implicit_image_volumes")
    env = config.get("Env")
    if type(env) is not list or len(env) > 256:
        raise FixtureCompilerError("compiler_image_environment")
    keys = []
    for entry in env:
        if (type(entry) is not str or len(entry) > 8192 or "=" not in entry
                or re.fullmatch("[A-Za-z_][A-Za-z0-9_]{0,127}", entry.split("=", 1)[0]) is None):
            raise FixtureCompilerError("compiler_image_environment")
        keys.append(entry.split("=", 1)[0])
    if (len(set(keys)) != len(keys) or type(environment_keys) is not list
            or not all(type(key) is str for key in environment_keys)
            or sorted(keys) != environment_keys):
        raise FixtureCompilerError("compiler_environment_drift")
    if (type(profile_raw) is not bytes or len(profile_raw) != 31921
            or hashlib.sha256(profile_raw).hexdigest() != PROFILE_SHA256):
        raise FixtureCompilerError("compiler_profile_drift")
    path = str(publisher_path)
    if (not path.startswith("/") or len(path) > 4096 or not path.isascii()
            or any(part in ("", ".", "..") for part in path.split("/")[1:])
            or "\0" in path or type(nonce) is not str
            or re.fullmatch("[0-9a-f]{32}", nonce) is None
            or type(source_sha256) is not str or re.fullmatch("[0-9a-f]{64}", source_sha256) is None):
        raise FixtureCompilerError("compiler_fixed_binding")
    initial_env = dict.fromkeys(keys, "")
    initial_env.update(PATH="/usr/bin:/bin", HOME="/work", LANG="C", LC_ALL="C",
        TMPDIR="/work", TMP="/work", TEMP="/work", PYTHONDONTWRITEBYTECODE="1",
        PYTHONNOUSERSITE="1", PYTHONHASHSEED="0")
    return {"Image": PROVIDER_ID, "User": "1000:1000", "WorkingDir": "/work",
        "Entrypoint": ["/usr/bin/python3", "-I", "-S", "-B", "/fixture/compiler.py"],
        "Cmd": [], "Env": [key + "=" + initial_env[key] for key in sorted(initial_env)],
        "Hostname": "vast-fixture-compiler", "Domainname": "", "NetworkDisabled": True,
        "AttachStdin": True, "AttachStdout": True, "AttachStderr": True,
        "OpenStdin": True, "StdinOnce": True, "Tty": False, "StopSignal": "SIGTERM",
        "Healthcheck": {"Test": ["NONE"]}, "Volumes": {},
        "Labels": {"org.vast.fixture-compiler.nonce": nonce,
            "org.vast.fixture-compiler.purpose": "fresh-artificial-engine-v1",
            "org.vast.fixture-compiler.source-sha256": source_sha256},
        "HostConfig": {"Runtime": "runc", "Init": False, "ReadonlyRootfs": True,
            "Memory": 536870912, "MemorySwap": 536870912, "PidsLimit": 32,
            "NanoCpus": 1000000000, "NetworkMode": "none", "IpcMode": "none",
            "PidMode": "", "CgroupnsMode": "private", "Privileged": False,
            "CapDrop": ["ALL"], "CapAdd": [], "Devices": [], "DeviceRequests": [],
            "VolumesFrom": [], "Binds": [], "ShmSize": 1048576,
            "Mounts": [{"Type": "bind", "Source": path, "Target": "/fixture/compiler.py",
                "ReadOnly": True, "BindOptions": {"Propagation": "rprivate"}}],
            "Tmpfs": {"/work": "rw,nosuid,nodev,size=134217728,nr_inodes=4096,uid=1000,gid=1000,mode=0700"},
            "Ulimits": [{"Name": "core", "Soft": 1, "Hard": 1},
                {"Name": "fsize", "Soft": 16777216, "Hard": 16777216}],
            "SecurityOpt": ["no-new-privileges:true", "seccomp=" + json.dumps(
                json.loads(profile_raw), sort_keys=True, separators=(",", ":"), ensure_ascii=True)],
            "LogConfig": {"Type": "none", "Config": {}},
            "RestartPolicy": {"Name": "no", "MaximumRetryCount": 0}}}


_COMPILER_ENGINE_V1 = "1e493309-3767-45fb-9078-05b838bdfd80"


def _compiler_json_v1(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("ascii")


def _compiler_read_v1(path, limit):
    """Bounded nonfollowing read, held-object before/after identity join."""
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    file = os.fdopen(os.open(path, flags), "rb")
    try:
        before = os.fstat(file.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
            raise FixtureCompilerError("owner_input_kind_bound")
        raw = file.read(limit + 1)
        after = os.fstat(file.fileno())
        identity = lambda row: (row.st_dev, row.st_ino, row.st_size, row.st_mtime_ns, row.st_ctime_ns)
        if len(raw) > limit or len(raw) != before.st_size or identity(before) != identity(after):
            raise FixtureCompilerError("owner_input_drift")
        return raw
    finally:
        file.close()


def _compiler_physical_v1(path, root, *, fresh=False):
    path, root = Path(path), Path(root)
    if not path.is_absolute() or not root.is_absolute() or root.resolve(strict=True) != root:
        raise FixtureCompilerError("owner_path")
    try:
        relative = path.relative_to(root)
    except ValueError:
        raise FixtureCompilerError("owner_path") from None
    if not relative.parts or any(part in (".", "..") for part in relative.parts):
        raise FixtureCompilerError("owner_path")
    parent = path.parent if fresh else path
    if parent.resolve(strict=True) != parent or (fresh and os.path.lexists(path)):
        raise FixtureCompilerError("owner_path")
    return path


def _compiler_sealed_v1(descriptor, root):
    if (type(descriptor) is not dict or set(descriptor) != {"path", "size_bytes", "sha256"}
            or type(descriptor["path"]) is not str or type(descriptor["size_bytes"]) is not int
            or not 1 <= descriptor["size_bytes"] <= 4096
            or type(descriptor["sha256"]) is not str
            or re.fullmatch("[0-9a-f]{64}", descriptor["sha256"]) is None):
        raise FixtureCompilerError("owner_sealed_descriptor")
    path = _compiler_physical_v1(descriptor["path"], root)
    raw = _compiler_read_v1(path, 4096)
    if len(raw) != descriptor["size_bytes"] or hashlib.sha256(raw).hexdigest() != descriptor["sha256"]:
        raise FixtureCompilerError("owner_sealed_binding")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate")
            result[key] = value
        return result
    value = json.loads(raw.decode("ascii"), object_pairs_hook=unique,
                       parse_constant=lambda value: (_ for _ in ()).throw(ValueError("nonfinite")))
    if type(value) is not dict or _compiler_json_v1(value) != raw:
        raise FixtureCompilerError("owner_sealed_canonical")
    return value, len(raw)


def _compiler_self_identity_v1():
    """Linux-only reader; never invoked by missing-authority/default paths."""
    raw = _compiler_proc_read_v1("/proc/self/stat", 4096)
    end = raw.rfind(b") ")
    fields = raw[end + 2:].split()
    if end < 1 or len(fields) < 20:
        raise FixtureCompilerError("owner_self_identity")
    return {"pid": os.getpid(), "start_ticks": int(fields[19]),
            "boot_id": _compiler_proc_read_v1("/proc/sys/kernel/random/boot_id", 64).decode("ascii").strip(),
            "kernel": os.uname().release, "machine": os.uname().machine}


def _compiler_proc_read_v1(path, limit):
    # proc/cgroup pseudo files usually report size zero; this explicit bounded
    # reader cannot be replaced by the regular-input size-equality reader.
    with open(path, "rb", buffering=0) as file:
        raw = file.read(limit + 1)
    if len(raw) > limit:
        raise FixtureCompilerError("owner_native_fact_cap")
    return raw


def _compiler_floor_facts_v1(project):
    def free(path):
        row = os.statvfs(path)
        return row.f_bavail * row.f_frsize
    return {"c_free": free("/mnt/c"), "project_free": free(project)}


def _compiler_source_mount_v1(path):
    value = str(path)
    if not value.startswith("/") or "\\" in value:
        raise FixtureCompilerError("owner_native_source_path")
    return value


def _compiler_directory_sync_v1(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _compiler_install_handlers_v1(received, previous):
    # Caller owns each previous entry BEFORE the fallible replacement.
    def handler(number, frame):
        if received[0] is None:
            received[0] = "owner_signal_term" if number == signal.SIGTERM else "owner_signal_int"
    for number in (signal.SIGTERM, signal.SIGINT):
        previous.append((number, signal.getsignal(number)))
        signal.signal(number, handler)


def _compiler_restore_handlers_v1(previous):
    causes = []
    for number, handler in reversed(previous):
        try:
            signal.signal(number, handler)
        except (OSError, ValueError, TypeError) as error:
            code = "owner_signal_restore_" + type(error).__name__
            if code not in causes:
                causes.append(code)
    return causes


def _compiler_process_facts_v1(pid, cid):
    """Finite actual init/proc/cgroup observations, not global-empty proof."""
    if type(pid) is not int or not 1 <= pid <= 4194304 or re.fullmatch("[0-9a-f]{64}", cid) is None:
        raise FixtureCompilerError("owner_native_identity")
    base = "/proc/" + str(pid)
    before = _compiler_proc_read_v1(base + "/stat", 4096)
    end = before.rfind(b") ")
    fields = before[end + 2:].split()
    if end < 1 or len(fields) < 20 or int(before[:before.find(b" ")]) != pid:
        raise FixtureCompilerError("owner_native_identity")
    start = int(fields[19])
    status = _compiler_proc_read_v1(base + "/status", 8192)
    uid = [line.split()[1:] for line in status.splitlines() if line.startswith(b"Uid:")]
    nspid = [line.split()[1:] for line in status.splitlines() if line.startswith(b"NSpid:")]
    if uid != [[b"1000"] * 4] or len(nspid) != 1 or len(nspid[0]) < 2 or nspid[0][-1] != b"1":
        raise FixtureCompilerError("owner_native_namespace")
    namespace = os.stat(base + "/ns/pid")
    own_namespace = os.stat("/proc/self/ns/pid")
    if (namespace.st_dev, namespace.st_ino) == (own_namespace.st_dev, own_namespace.st_ino):
        raise FixtureCompilerError("owner_native_namespace")
    cgroup = _compiler_proc_read_v1(base + "/cgroup", 4096).decode("ascii").splitlines()
    if len(cgroup) != 1 or not cgroup[0].startswith("0::/"):
        raise FixtureCompilerError("owner_native_cgroup")
    relative = cgroup[0][3:]
    parts = relative.split("/")[1:]
    if (not parts or any(re.fullmatch("[A-Za-z0-9_.:-]{1,128}", part) is None or part in (".", "..") for part in parts)
            or not any(part in (cid, "docker-" + cid + ".scope") for part in parts)):
        raise FixtureCompilerError("owner_native_cgroup")
    group = "/sys/fs/cgroup" + relative
    procs = [int(value) for value in _compiler_proc_read_v1(group + "/cgroup.procs", 1024).split()]
    events = dict(line.split() for line in _compiler_proc_read_v1(group + "/cgroup.events", 1024).splitlines())
    if not 1 <= len(procs) <= 32 or pid not in procs or events.get(b"populated") != b"1":
        raise FixtureCompilerError("owner_native_cgroup")
    mounts = []
    for line in _compiler_proc_read_v1(base + "/mountinfo", 65536).decode("ascii").splitlines():
        left, separator, right = line.partition(" - ")
        head, tail = left.split(), right.split()
        if not separator or len(head) < 6 or len(tail) != 3 or len(mounts) >= 128:
            raise FixtureCompilerError("owner_native_mounts")
        if "rw" in head[5].split(","):
            mounts.append([head[4], tail[0], head[5], tail[2]])
    after = _compiler_proc_read_v1(base + "/stat", 4096)
    end_after = after.rfind(b") ")
    if end_after < 1 or after[end_after + 2:].split()[19] != str(start).encode("ascii"):
        raise FixtureCompilerError("owner_native_identity_drift")
    return {"pid": pid, "start_ticks": start, "boot_id": _compiler_self_identity_v1()["boot_id"],
            "pid_namespace": [namespace.st_dev, namespace.st_ino], "cgroup_path": relative,
            "mounts_sha256": hashlib.sha256(_compiler_json_v1(sorted(mounts))).hexdigest(),
            "populated": 1, "procs": procs}


def _compiler_closed_facts_v1(live, cid):
    if (type(live) is not dict or live.get("boot_id") != _compiler_self_identity_v1()["boot_id"]
            or type(live.get("cgroup_path")) is not str
            or cid not in live["cgroup_path"]):
        raise FixtureCompilerError("owner_native_closure_binding")
    try:
        _compiler_proc_read_v1("/proc/" + str(live["pid"]) + "/stat", 4096)
    except FileNotFoundError:
        absent = True
    else:
        raise FixtureCompilerError("owner_native_init_not_absent")
    group = "/sys/fs/cgroup" + live["cgroup_path"]
    try:
        procs = [int(value) for value in _compiler_proc_read_v1(group + "/cgroup.procs", 1024).split()]
        events = dict(line.split() for line in _compiler_proc_read_v1(group + "/cgroup.events", 1024).splitlines())
        populated = int(events[b"populated"])
    except FileNotFoundError:
        if os.path.lexists(group):
            raise FixtureCompilerError("owner_native_cgroup_incomplete")
        procs, populated = [], 0
    if procs or populated != 0:
        raise FixtureCompilerError("owner_native_cgroup_not_empty")
    return {"closed": True, "populated": populated, "procs": procs, "init_absent": absent}


def compile_fixture_engine_v1(*, project_root, source_path, executable_path,
                              qualification=None, admission=None, absolute_deadline_ns=None):
    """Usable fixture gate. Sealed pins are authenticated by the outer caller.

    This module checks their exact bytes/bindings, not GitHub review authenticity.
    The enclosing reviewed recipe must supply its independently authenticated
    pins before first module parse. An unqualified/component-only descriptor
    never authorizes this usable-output entry point.
    """
    return _compile_fixture_owned_v1(project_root=project_root, source_path=source_path,
        executable_path=executable_path, qualification=qualification, admission=admission,
        absolute_deadline_ns=absolute_deadline_ns, usable=True)


def _compile_fixture_component_v1(*, project_root, source_path, executable_path,
                                admission, qualification=None, absolute_deadline_ns=None):
    """Private initial component only: physical admission required; never promote."""
    return _compile_fixture_owned_v1(project_root=project_root, source_path=source_path,
        executable_path=executable_path, qualification=qualification, admission=admission,
        absolute_deadline_ns=absolute_deadline_ns, usable=False)


def _compile_fixture_owned_v1(*, project_root, source_path, executable_path,
                            qualification, admission, absolute_deadline_ns, usable):
    causes, facts = [], {"accepted": False, "normal_closed": False, "own_completion": None,
                         "cid": None, "creation_unknown": False, "forced": False,
                         "receipt_persisted": False, "promotion": None, "rpc": None,
                         "start_attempted": False, "start_unknown": False}
    def fail(code):
        if code not in causes:
            causes.append(code)
    def require(condition, code):
        if not condition:
            raise FixtureCompilerError(code)
    def keys(value, names, code):
        require(type(value) is dict and set(value) == set(names.split()), code)
    def sha(value):
        return type(value) is str and re.fullmatch("[0-9a-f]{64}", value) is not None
    start_time = time.monotonic_ns()
    require(type(start_time) is int and start_time >= 0, "owner_clock")
    require(absolute_deadline_ns is None or type(absolute_deadline_ns) is int, "owner_deadline")
    deadline = min(start_time + 150_000_000_000, absolute_deadline_ns) if absolute_deadline_ns is not None else start_time + 150_000_000_000
    require(deadline - start_time > 80_000_000_000, "owner_containment_room")
    prestart_end = min(start_time + 10_000_000_000, deadline - 80_000_000_000)
    root = Path(project_root)
    require(root.is_absolute() and root.resolve(strict=True) == root and root.is_dir(), "owner_project")
    # All missing/invalid authority refusals occur BEFORE transport construction.
    admitted, admission_bytes = _compiler_sealed_v1(admission, root)
    keys(admitted, "schema_version artifact_kind scope review recipe_sha256 component_seed bindings project_root source executable_relative physical_plan_sha256 whole_chain_admission_sha256 expires_unix_ns boot_id metadata_upper_bytes retained_upper_bytes additional_disk_upper_bytes filesystem_floors", "owner_admission_schema")
    require(type(admitted["schema_version"]) is int and admitted["schema_version"] == 1 and
            admitted["artifact_kind"] == "vast_fixture_compiler_admission_v1" and admitted["project_root"] == str(root), "owner_admission_schema")
    if usable:
        require(admitted["scope"] == "whole_chain_task1_5" and sha(admitted["whole_chain_admission_sha256"])
                and admitted["component_seed"] is None, "owner_whole_admission")
        recipe, recipe_bytes = _compiler_sealed_v1(qualification, root)
        require(admitted["recipe_sha256"] == qualification["sha256"], "owner_qualification_binding")
    else:
        require(admitted["scope"] == "component_only" and admitted["whole_chain_admission_sha256"] is None, "owner_component_admission")
        if qualification is None:
            recipe, recipe_bytes = admitted["component_seed"], 0
            require(admitted["recipe_sha256"] == hashlib.sha256(_compiler_json_v1(recipe)).hexdigest(), "owner_seed_binding")
        else:
            recipe, recipe_bytes = _compiler_sealed_v1(qualification, root)
            require(admitted["recipe_sha256"] == qualification["sha256"], "owner_seed_binding")
    keys(recipe, "schema_version artifact_kind review bindings engine provider environment_keys mounts_sha256 proofs", "owner_recipe_schema")
    require(type(recipe["schema_version"]) is int and recipe["schema_version"] == 1 and
            recipe["artifact_kind"] == ("vast_fixture_compiler_qualification_v1" if usable else "vast_fixture_compiler_component_seed_v1"), "owner_recipe_schema")
    for review in (admitted["review"], recipe["review"]):
        keys(review, "commit approval_reference evidence_sha256", "owner_review_binding")
        require(type(review["commit"]) is str and re.fullmatch("[0-9a-f]{40}", review["commit"]) is not None
                and sha(review["evidence_sha256"]) and type(review["approval_reference"]) is str
                and 1 <= len(review["approval_reference"]) <= 512, "owner_review_binding")
    bindings = recipe["bindings"]
    keys(bindings, "host_sha256 publisher_sha256 profile_sha256", "owner_source_manifest")
    require(all(sha(value) for value in bindings.values()) and bindings == admitted["bindings"] and
            bindings["profile_sha256"] == PROFILE_SHA256, "owner_source_manifest")
    keys(recipe["engine"], "driver cgroup_driver security_options runtimes_sha256", "owner_engine_manifest")
    keys(recipe["provider"], "rootfs_sha256 size_bytes", "owner_provider_manifest")
    keys(recipe["proofs"], "baseline toolchain abi limits closure", "owner_capability_manifest")
    require(sha(recipe["mounts_sha256"]) and sha(recipe["provider"]["rootfs_sha256"]) and
            type(recipe["provider"]["size_bytes"]) is int and recipe["provider"]["size_bytes"] >= 0 and
            sha(recipe["engine"]["runtimes_sha256"]), "owner_capability_manifest")
    require(all(sha(value) for value in recipe["proofs"].values()) if usable else
            all(value is None or sha(value) for value in recipe["proofs"].values()), "owner_capability_manifest")
    require(type(admitted["expires_unix_ns"]) is int and time.time_ns() < admitted["expires_unix_ns"] <= time.time_ns() + 60_000_000_000
            and sha(admitted["physical_plan_sha256"]), "owner_physical_admission")
    for name in ("metadata_upper_bytes", "retained_upper_bytes", "additional_disk_upper_bytes"):
        require(type(admitted[name]) is int and 0 < admitted[name] <= 1 << 50, "owner_physical_admission")
    require(admitted["metadata_upper_bytes"] <= 262144 and
            admitted["additional_disk_upper_bytes"] >= admitted["retained_upper_bytes"], "owner_physical_admission")
    keys(admitted["filesystem_floors"], "c_bytes project_bytes", "owner_floor_manifest")
    floors = admitted["filesystem_floors"]
    require(type(floors["c_bytes"]) is int and floors["c_bytes"] >= 42949672960 and
            type(floors["project_bytes"]) is int and floors["project_bytes"] > 0, "owner_floor_manifest")
    source = _compiler_physical_v1(source_path, root)
    executable = _compiler_physical_v1(executable_path, root, fresh=True)
    keys(admitted["source"], "relative_path size_bytes sha256", "owner_source_binding")
    require(type(admitted["source"]["size_bytes"]) is int and 0 < admitted["source"]["size_bytes"] <= SOURCE_LIMIT and
            sha(admitted["source"]["sha256"]) and str(source.relative_to(root)) == admitted["source"]["relative_path"] and
            str(executable.relative_to(root)) == admitted["executable_relative"], "owner_source_binding")
    publisher = _compiler_physical_v1(root / "tests/fixtures/accepted_policy_fixture_compiler_publisher_v1.py", root)
    profile = _compiler_physical_v1(root / "tests/fixtures/accepted_policy_fixture_compiler_seccomp_v1.json", root)
    publisher_raw, profile_raw = _compiler_read_v1(publisher, 65536), _compiler_read_v1(profile, 65536)
    host_path = Path(__file__).resolve(strict=True)
    host_raw = _compiler_read_v1(host_path, 262144)
    require(hashlib.sha256(host_raw).hexdigest() == bindings["host_sha256"] and
            hashlib.sha256(publisher_raw).hexdigest() == bindings["publisher_sha256"] and
            hashlib.sha256(profile_raw).hexdigest() == PROFILE_SHA256, "owner_helper_drift")
    source_file = open(source, "rb")
    client = attach = None
    output = None
    source_raw = None
    guards = []
    previous_handlers, received_signal = [], [None]
    normal_deadline = None
    wait_reply = None
    live, final, captured, config, name, cid = None, None, None, None, None, None
    started = False
    control_bytes = admission_bytes + recipe_bytes
    last_clock = start_time
    def now(*, allow_failure=False):
        nonlocal last_clock
        value = time.monotonic_ns()
        require(type(value) is int and last_clock <= value < deadline, "owner_deadline")
        require(allow_failure or received_signal[0] is None, received_signal[0] or "owner_signal")
        if normal_deadline is not None and not causes:
            require(value < normal_deadline, "owner_normal_close_deadline")
        last_clock = value
        return value
    def record(filename, value, cap):
        nonlocal control_bytes
        require(_json_bound(value) <= cap, "owner_control_cap")
        raw = _compiler_json_v1(value)
        require(len(raw) <= cap and 2 * len(raw) <= 32768 - control_bytes, "owner_control_cap")
        control_bytes += 2 * len(raw)
        file = None
        primary = None
        try:
            file = (output / filename).open("xb")
            require(file.write(raw) == len(raw), "owner_control_short_write")
            file.flush()
            os.fsync(file.fileno())
            now(allow_failure=bool(causes))
        except (FixtureCompilerError, OSError, ValueError, TypeError) as error:
            primary = error
            for code in error.causes if isinstance(error, FixtureCompilerError) else ["owner_control_" + type(error).__name__]:
                fail(code)
        finally:
            if file is not None:
                try:
                    file.close()
                    now(allow_failure=bool(causes))
                except (OSError, ValueError, TypeError) as error:
                    fail("owner_control_close_" + type(error).__name__)
                    primary = primary or error
        if primary is not None:
            raise FixtureCompilerError(*causes)
    def rpc(method, path, body=None, *, phase, cleanup=False, upgrade=False):
        current = now(allow_failure=cleanup)
        until = min(phase, deadline, current + (30_000_000_000 if "/wait?" in path else 10_000_000_000))
        require(current < until, "owner_phase_deadline")
        return client.request(method, path, body, deadline_ns=until, cleanup=cleanup, upgrade=upgrade)
    def summary(phase, *, cleanup=False):
        filters = {"name": ["^/" + name + "$"], "label": ["org.vast.fixture-compiler.nonce=" + nonce,
            "org.vast.fixture-compiler.source-sha256=" + admitted["source"]["sha256"]], "ancestor": [PROVIDER_ID]}
        rows = rpc("GET", "/containers/json?all=1&filters=" + quote(_compiler_json_v1(filters).decode("ascii"), safe=""), phase=phase, cleanup=cleanup)
        require(type(rows) is list and len(rows) == 1, "owner_identity_unknown")
        row = rows[0]
        require(type(row) is dict and type(row.get("Id")) is str and re.fullmatch("[0-9a-f]{64}", row["Id"]) is not None
                and row.get("ImageID") == PROVIDER_ID and row.get("Names") == ["/" + name]
                and type(row.get("Labels")) is dict and all(row["Labels"].get(key) == value for key, value in config["Labels"].items()), "owner_identity_unknown")
        if cid is not None:
            require(row["Id"] == cid, "owner_identity_drift")
        return row["Id"]
    def inspect_owned(phase, *, cleanup=False):
        row = rpc("GET", "/containers/" + cid + "/json", phase=phase, cleanup=cleanup)
        require(type(row) is dict and row.get("Id") == cid and row.get("Name") == "/" + name
                and row.get("Image") == PROVIDER_ID and type(row.get("Config")) is dict
                and type(row.get("HostConfig")) is dict and type(row.get("State")) is dict, "owner_inspect_identity")
        for key, value in config.items():
            if key not in ("Image", "HostConfig"):
                require(row["Config"].get(key) == value, "owner_effective_config")
        for key, value in config["HostConfig"].items():
            require(row["HostConfig"].get(key) == value, "owner_effective_config")
        return row
    try:
        before = os.fstat(source_file.fileno())
        require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_size == admitted["source"]["size_bytes"], "owner_source_binding")
        source_raw = source_file.read(SOURCE_LIMIT + 1)
        require(len(source_raw) == before.st_size and source_raw.isascii() and b"\0" not in source_raw and
                hashlib.sha256(source_raw).hexdigest() == admitted["source"]["sha256"] and
                source_raw.startswith(b"#define STATE_FILE ") and b"\n#define DAEMON_ID " in source_raw[:8192], "owner_source_binding")
        for path, raw, limit in ((publisher, publisher_raw, 65536), (profile, profile_raw, 65536), (host_path, host_raw, 262144)):
            entry = {"path": path, "file": None, "identity": None, "raw": raw, "limit": limit}
            guards.append(entry)
            entry["file"] = path.open("rb")
            held = os.fstat(entry["file"].fileno())
            require(stat.S_ISREG(held.st_mode) and held.st_nlink == 1 and held.st_size == len(raw), "owner_guard_kind")
            entry["identity"] = (held.st_dev, held.st_ino, held.st_size, held.st_mtime_ns, held.st_ctime_ns)
            require(entry["file"].read(limit + 1) == raw, "owner_guard_drift")
        require(admitted["retained_upper_bytes"] >= 3 * 16777216 + len(source_raw) + 2 * 1048576 + 262144, "owner_retention_quote")
        identity = _compiler_self_identity_v1()
        require(type(identity) is dict and identity.get("boot_id") == admitted["boot_id"] and identity.get("machine") == "x86_64"
                and identity.get("kernel") == "6.6.87.2-microsoft-standard-WSL2", "owner_runtime_binding")
        free = _compiler_floor_facts_v1(root)
        require(type(free) is dict and type(free.get("c_free")) is int and type(free.get("project_free")) is int and
                free["c_free"] >= floors["c_bytes"] + admitted["additional_disk_upper_bytes"] and
                free["project_free"] >= floors["project_bytes"] + admitted["additional_disk_upper_bytes"], "owner_fresh_floor")
        now()
        nonce = os.urandom(16).hex()
        name = "vast-fixture-compiler-" + nonce
        intent = {"kind": "vast_fixture_compiler_intent_v1", "name": name, "nonce": nonce,
            "engine": _COMPILER_ENGINE_V1, "provider": PROVIDER_ID, "source": admitted["source"],
            "client": identity, "bindings": bindings, "owner_deadline_ns": deadline,
            "prestart_deadline_ns": prestart_end, "qualification_sha256": admitted["recipe_sha256"],
            "admission_sha256": admission["sha256"]}
        pending = _compiler_physical_v1(executable.parent / ("." + executable.name + ".pending-" + nonce), root, fresh=True)
        intent["pending_relative"] = str(pending.relative_to(root))
        require(control_bytes + 2 * (len(_compiler_json_v1(intent)) + 1024 + 8192) <= 32768, "owner_control_quote")
        output = _compiler_physical_v1(executable.parent / (executable.name + ".compiler-originals"), root, fresh=True)
        output.mkdir(mode=0o700)
        client = _DockerClientV1(output, deadline)
        client.LIMIT, client.ORDINARY_LIMIT = 229376, 163840
        intent["socket_path"] = "/run/docker.sock"
        intent["socket_epoch"] = [list(row) for row in client._observe_endpoint()]
        require(control_bytes + 2 * (len(_compiler_json_v1(intent)) + 1024 + 8192) <= 32768, "owner_control_quote")
        record("owner.intent.original.json", intent, 4096)
        _compiler_install_handlers_v1(received_signal, previous_handlers)
        version = rpc("GET", "/version", phase=prestart_end)
        def api_version(value):
            require(type(value) is str and re.fullmatch("[0-9]{1,2}\\.[0-9]{1,2}", value) is not None, "owner_docker_version")
            return tuple(int(part) for part in value.split("."))
        require(type(version) is dict and version.get("Version") == "29.7.2" and
                api_version(version.get("MinAPIVersion")) <= (1, 55) <= api_version(version.get("ApiVersion")), "owner_docker_version")
        info = rpc("GET", "/info", phase=prestart_end)
        require(type(info) is dict and info.get("ID") == _COMPILER_ENGINE_V1 and info.get("DockerRootDir") == "/var/lib/docker"
                and info.get("Driver") == recipe["engine"]["driver"] and info.get("CgroupDriver") == recipe["engine"]["cgroup_driver"]
                and info.get("CgroupVersion") == "2" and info.get("SecurityOptions") == recipe["engine"]["security_options"]
                and "name=seccomp,profile=builtin" in info["SecurityOptions"] and
                hashlib.sha256(_compiler_json_v1(info.get("Runtimes"))).hexdigest() == recipe["engine"]["runtimes_sha256"], "owner_engine_drift")
        image = rpc("GET", "/images/" + quote(PROVIDER, safe="") + "/json", phase=prestart_end)
        require(type(image) is dict and image.get("Id") == PROVIDER_ID and PROVIDER in image.get("RepoDigests", []) and
                type(image.get("Size")) is int and image["Size"] == recipe["provider"]["size_bytes"] and
                hashlib.sha256(_compiler_json_v1(image.get("RootFS"))).hexdigest() == recipe["provider"]["rootfs_sha256"], "owner_provider_drift")
        config = compiler_container_config_v1(image, environment_keys=recipe["environment_keys"],
            publisher_path=_compiler_source_mount_v1(publisher), profile_raw=profile_raw, nonce=nonce, source_sha256=admitted["source"]["sha256"])
        try:
            created = rpc("POST", "/containers/create?name=" + name, config, phase=prestart_end)
            require(type(created) is dict and type(created.get("Id")) is str and
                    re.fullmatch("[0-9a-f]{64}", created["Id"]) is not None and created.get("Warnings") in (None, []), "owner_create_reply")
            cid = created["Id"]
        except (FixtureCompilerError, OSError, ValueError) as error:
            facts["creation_unknown"] = True
            for code in error.causes if isinstance(error, FixtureCompilerError) else ["owner_create_" + type(error).__name__]:
                fail(code)
            cid = summary(min(deadline, now() + 10_000_000_000), cleanup=True)
            facts["cid"] = cid
            record("owner.cid.original.json", {"cid": cid, "name": name, "reconciled": True}, 1024)
            reconciled = inspect_owned(min(deadline, now() + 10_000_000_000), cleanup=True)
            require(reconciled["State"].get("Running") is False and reconciled["State"].get("Pid") == 0, "owner_lost_create_state")
            facts["creation_unknown"] = False
            raise FixtureCompilerError(*causes)
        facts["cid"] = cid
        record("owner.cid.original.json", {"cid": cid, "name": name, "reconciled": False}, 1024)
        summary(prestart_end)
        duplex = rpc("POST", "/containers/" + cid + "/attach?stream=1&stdin=1&stdout=1&stderr=1", phase=prestart_end, upgrade=True)
        attach = _CompilerAttachV1(duplex, output)
        # A lost start reply leaves the container possibly running: contain it.
        facts["start_attempted"] = facts["start_unknown"] = True
        rpc("POST", "/containers/" + cid + "/start", phase=prestart_end)
        facts["start_unknown"] = False
        started = True
        started_at = now()
        require(started_at < prestart_end, "owner_late_start")
        work_end = min(started_at + 60_000_000_000, deadline - 80_000_000_000)
        require(started_at < work_end, "owner_work_room")
        duplex.arm_data_deadline(work_end)
        actual = inspect_owned(min(work_end, now() + 10_000_000_000))
        state = actual["State"]
        require(state.get("Running") is True and state.get("Restarting") is False and
                state.get("Paused") is False and state.get("Dead") is False and
                type(state.get("Pid")) is int and state["Pid"] > 0 and type(actual.get("RestartCount")) is int and actual["RestartCount"] == 0, "owner_live_state")
        live = _compiler_process_facts_v1(state["Pid"], cid)
        require(live.get("mounts_sha256") == recipe["mounts_sha256"] and live.get("boot_id") == identity["boot_id"], "owner_live_native_binding")
        facts["live"] = live
        request = _compiler_json_v1({"source_size": len(source_raw), "source_sha256": admitted["source"]["sha256"]})
        attach.sendall(b"VASTCC1\n" + struct.pack(">I", len(request)) + request)
        for offset in range(0, len(source_raw), 65536):
            now()
            attach.sendall(source_raw[offset:offset + 65536])
        attach.shutdown_write()
        captured = capture_export_v1(attach.read, output)
        facts["export"] = captured
        closing, attach = attach, None
        closing.close()
        now()
        normal_end = min(deadline - 70_000_000_000, started_at + 70_000_000_000, now() + 10_000_000_000)
        normal_deadline = normal_end
        summary(normal_end, cleanup=True)
        waited = wait_reply = rpc("POST", "/containers/" + cid + "/wait?condition=not-running", phase=normal_end, cleanup=True)
        require(type(waited) is dict and type(waited.get("StatusCode")) is int and waited["StatusCode"] == 0
                and waited.get("Error") in (None, {}), "owner_wait_status")
        final = inspect_owned(normal_end, cleanup=True)
        state = final["State"]
        require(state.get("Running") is False and state.get("Restarting") is False and state.get("Paused") is False and
                state.get("Dead") is False and type(state.get("Pid")) is int and state["Pid"] == 0 and
                type(state.get("ExitCode")) is int and state["ExitCode"] == 0 and state.get("OOMKilled") is False and
                state.get("Error") == "" and type(final.get("RestartCount")) is int and final["RestartCount"] == 0, "owner_container_status")
        closed = _compiler_closed_facts_v1(live, cid)
        require(closed.get("closed") is True and type(closed.get("populated")) is int and closed["populated"] == 0 and closed.get("procs") == [] and
                closed.get("init_absent") is True, "owner_native_closure_unknown")
        facts["closed"] = closed
        header = captured["header"]
        require(type(header) is dict, "owner_publisher_status")
        child, runtime = header.get("compiler"), header.get("runtime")
        require(type(child) is dict and type(runtime) is dict, "owner_publisher_status")
        require(header.get("source") == {"size_bytes": len(source_raw), "sha256": admitted["source"]["sha256"]} and
                header.get("causes") == [] and header.get("descendants_reaped") is True and
                child.get("started") is True and child.get("reaped") is True and type(child.get("returncode")) is int and
                child["returncode"] == 0 and type(runtime.get("pid")) is int and runtime["pid"] == 1 and
                type(runtime.get("core")) is list and all(type(number) is int for number in runtime["core"]) and runtime["core"] == [1, 1] and
                type(runtime.get("fsize")) is list and all(type(number) is int for number in runtime["fsize"]) and runtime["fsize"] == [16777216, 16777216] and runtime.get("interpreter_elf64_amd64") is True and
                runtime.get("compiler_elf64_amd64") is True, "owner_publisher_status")
        for channel in ("stdout", "stderr"):
            row = child.get(channel)
            require(type(row) is dict, "owner_compiler_channel")
            require(row.get("eof") is True and type(row.get("observed_bytes")) is int and
                    row.get("observed_bytes") == row.get("size_bytes") and type(row.get("discarded_bytes")) is int and row["discarded_bytes"] == 0, "owner_compiler_channel")
        elf = _compiler_read_v1(output / "engine.unaccepted", 16777216)
        require(len(elf) >= 64 and elf[:7] == b"\x7fELF\x02\x01\x01" and int.from_bytes(elf[18:20], "little") == 62 and
                int.from_bytes(elf[16:18], "little") in (2, 3) and int.from_bytes(elf[20:24], "little") == 1, "owner_elf_abi")
        exported = captured["members"].get("elf")
        require(type(exported) is dict and exported.get("complete") is True and exported.get("size_bytes") == len(elf) and
                exported.get("sha256") == hashlib.sha256(elf).hexdigest(), "owner_elf_export_binding")
        now()
        facts["normal_closed"] = True
    except (Exception, KeyboardInterrupt, SystemExit) as error:
        for code in error.causes if isinstance(error, FixtureCompilerError) else ["owner_" + type(error).__name__]:
            fail(code)
        if isinstance(error, FixtureCompilerError) and hasattr(error, "facts"):
            facts["failed_operation"] = error.facts
        # Containment starts from the latest observed state, never from an
        # unset `final`: an inspect wins, else an integer wait status means
        # not-running. Signalling an exited container only adds 409 noise.
        if type(final) is dict and type(final.get("State")) is dict:
            observed_stopped = final["State"].get("Running") is False and final["State"].get("Pid") == 0
            already_stopped = observed_stopped
        else:
            observed_stopped = type(wait_reply) is dict and type(wait_reply.get("StatusCode")) is int
            already_stopped = False
        contain = (client is not None and cid is not None and facts["start_attempted"]
                   and not facts["normal_closed"] and not already_stopped)
        if contain and not observed_stopped:
            # Spend only what remains of the normal-close phase; no phase reset.
            try:
                current = now(allow_failure=True)
                bound = normal_deadline if normal_deadline is not None else min(
                    current + 10_000_000_000, deadline - 70_000_000_000)
                if bound > current:
                    facts["containment_close_wait"] = True
                    summary(bound, cleanup=True)
                    reply = rpc("POST", "/containers/" + cid + "/wait?condition=not-running", phase=bound, cleanup=True)
                    observed_stopped = type(reply) is dict and type(reply.get("StatusCode")) is int
            except BaseException as secondary:
                for code in secondary.causes if isinstance(secondary, FixtureCompilerError) else ["owner_containment_" + type(secondary).__name__]:
                    fail(code)
        if contain:
            for signal_name in ("SIGTERM", "SIGKILL") if not observed_stopped else ():
                try:
                    end = min(deadline - 10_000_000_000, now(allow_failure=True) + 30_000_000_000)
                    summary(end, cleanup=True)
                    rpc("POST", "/containers/" + cid + "/kill?signal=" + signal_name, phase=end, cleanup=True)
                    facts["forced"] = True
                    summary(end, cleanup=True)
                    reply = rpc("POST", "/containers/" + cid + "/wait?condition=not-running", phase=end, cleanup=True)
                    if type(reply) is dict and type(reply.get("StatusCode")) is int:
                        break
                except BaseException as secondary:
                    for code in secondary.causes if isinstance(secondary, FixtureCompilerError) else ["owner_containment_" + type(secondary).__name__]:
                        fail(code)
            try:
                end = min(deadline, now(allow_failure=True) + 10_000_000_000)
                summary(end, cleanup=True)
                final = inspect_owned(end, cleanup=True)
                facts["containment_state"] = final["State"]
                if live is not None:
                    facts["containment_native"] = _compiler_closed_facts_v1(live, cid)
            except BaseException as secondary:
                for code in secondary.causes if isinstance(secondary, FixtureCompilerError) else ["owner_final_" + type(secondary).__name__]:
                    fail(code)
    finally:
        if attach is not None:
            try:
                attach.close()
            except (FixtureCompilerError, OSError, ValueError, TypeError) as error:
                for code in error.causes if isinstance(error, FixtureCompilerError) else ["owner_attach_close_" + type(error).__name__]:
                    fail(code)
        for entry in guards:
            file = entry["file"]
            if file is None:
                continue
            try:
                file.seek(0)
                held = os.fstat(file.fileno())
                identity_after = (held.st_dev, held.st_ino, held.st_size, held.st_mtime_ns, held.st_ctime_ns)
                current = os.stat(entry["path"], follow_symlinks=False)
                require(entry["identity"] == identity_after and (current.st_dev, current.st_ino) == identity_after[:2] and
                        file.read(entry["limit"] + 1) == entry["raw"], "owner_guard_post_drift")
            except (FixtureCompilerError, OSError, ValueError, TypeError) as error:
                for code in error.causes if isinstance(error, FixtureCompilerError) else ["owner_guard_post_" + type(error).__name__]:
                    fail(code)
            try:
                file.close()
            except (OSError, ValueError, TypeError) as error:
                fail("owner_guard_close_" + type(error).__name__)
        try:
            source_file.seek(0)
            after_raw = source_file.read(SOURCE_LIMIT + 1)
            after = os.fstat(source_file.fileno())
            require(source_raw is not None and after_raw == source_raw and before.st_dev == after.st_dev and
                    before.st_ino == after.st_ino and before.st_mtime_ns == after.st_mtime_ns and
                    before.st_ctime_ns == after.st_ctime_ns and source == source.resolve(strict=True), "owner_source_post_drift")
            require(_compiler_read_v1(publisher, 65536) == publisher_raw and _compiler_read_v1(profile, 65536) == profile_raw and
                    _compiler_read_v1(host_path, 262144) == host_raw, "owner_helper_post_drift")
        except (FixtureCompilerError, OSError, ValueError, TypeError) as error:
            for code in error.causes if isinstance(error, FixtureCompilerError) else ["owner_source_post_" + type(error).__name__]:
                fail(code)
        try:
            source_file.close()
        except (OSError, ValueError, TypeError) as error:
            fail("owner_source_close_" + type(error).__name__)
        for code in _compiler_restore_handlers_v1(previous_handlers):
            fail(code)
        facts["signal_handlers_restored"] = not any(code.startswith("owner_signal_restore_") for code in causes)
    if client is not None:
        facts["rpc"] = client.facts
        for code in client.causes:
            fail(code)
        if client.facts["metadata_bytes"] + control_bytes > 262144:
            fail("owner_metadata_total")
    facts["causes"], facts["control_bytes_before_receipt"] = causes, control_bytes
    if output is not None:
        # The inner record never claims its own completed persistence or future
        # promotion. The returned result/enclosing owner supplies those facts.
        receipt = {key: value for key, value in facts.items() if key not in ("rpc", "failed_operation", "export")}
        receipt["rpc_summary"] = None if client is None else {"attempts": client.facts["attempts"],
            "metadata_bytes": client.facts["metadata_bytes"], "rows": [[row.get("number"), row.get("status"),
            row.get("complete"), row.get("reply_observed_bytes"), row.get("reply_written_bytes"),
            row.get("reply_persisted_bytes"), row.get("reply_write_extent_unknown"), row.get("causes")]
            for row in client.facts["rpc"]]}
        receipt["export_binding"] = None if captured is None else {"header_sha256": hashlib.sha256(_compiler_json_v1(captured["header"])).hexdigest(),
            "members": captured["members"], "complete": captured["complete"]}
        try:
            record("owner.result.original.json", receipt, 8192)
            facts["receipt_persisted"] = True
        except (FixtureCompilerError, OSError, ValueError, TypeError) as error:
            for code in error.causes if isinstance(error, FixtureCompilerError) else ["owner_receipt_" + type(error).__name__]:
                fail(code)
    if not causes and facts["normal_closed"] and facts["receipt_persisted"] and usable:
        promotion = {"written_bytes": 0, "extent_unknown": False, "persisted": False, "closed": False}
        facts["promotion"] = promotion
        file = None
        try:
            file = pending.open("xb")
            for offset in range(0, len(elf), 65536):
                now()
                block = elf[offset:offset + 65536]
                try:
                    written = file.write(block)
                except (OSError, ValueError, TypeError):
                    promotion["extent_unknown"] = True
                    raise
                require(type(written) is int and 0 <= written <= len(block), "owner_promotion_write_contract")
                promotion["written_bytes"] += written
                require(written == len(block), "owner_promotion_short_write")
            file.flush()
            os.fsync(file.fileno())
            promotion["persisted"] = True
        except (FixtureCompilerError, OSError, ValueError, TypeError) as error:
            for code in error.causes if isinstance(error, FixtureCompilerError) else ["owner_promotion_" + type(error).__name__]:
                fail(code)
        finally:
            if file is not None:
                try:
                    file.close()
                    promotion["closed"] = True
                except (OSError, ValueError, TypeError) as error:
                    fail("owner_promotion_close_" + type(error).__name__)
        if not causes:
            try:
                require(_compiler_read_v1(pending, 16777216) == elf, "owner_promotion_readback")
                pending.chmod(0o700)
                require(not os.path.lexists(executable), "owner_promotion_destination_exists")
                now()
                # link() never replaces a destination; external same-UID/root
                # mutation remains the trusted boundary.
                os.link(pending, executable)
                promotion["published"] = True
                _compiler_directory_sync_v1(executable.parent)
                promotion["directory_persisted"] = True
                os.unlink(pending)
                _compiler_directory_sync_v1(executable.parent)
                now()
                facts["accepted"] = True
            except BaseException as error:
                # Handlers are already restored: an interrupt here still withdraws.
                for code in error.causes if isinstance(error, FixtureCompilerError) else ["owner_publication_" + type(error).__name__]:
                    fail(code)
                facts["accepted"] = False
                if promotion.get("published"):
                    try:
                        os.unlink(executable)
                        promotion["published"] = False
                        promotion["withdrawn"] = True
                        _compiler_directory_sync_v1(executable.parent)
                        promotion["withdrawal_persisted"] = True
                    except BaseException as withdraw:
                        fail("owner_publication_withdraw_" + type(withdraw).__name__)
                if not isinstance(error, Exception):
                    raise
    if causes or not facts["normal_closed"] or not facts["receipt_persisted"]:
        error = FixtureCompilerError(*(causes or ["owner_incomplete"]))
        error.facts = facts
        raise error
    return facts
