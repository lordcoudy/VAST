"""V8 F2: one finite read-only recovery from the retained stopped B1 container.

No file from a tar is extracted. Controlled sockets, clocks and measurements
are test seams and never physical qualification. The caller authenticates the
review/packet and reserves this helper's entire 8 MiB liability before entry.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import time
from urllib.parse import quote

from tests.fixtures import accepted_policy_fixture_compiler_v1 as compiler


CID = "4df593e12ca362e69f0594b2035197335f335d3ceae3c71894b31db9f197a09f"
ENGINE_ID = "1e493309-3767-45fb-9078-05b838bdfd80"
PROVIDER_ID = compiler.PROVIDER_ID
TOTAL_LIMIT = 8 * 1024 * 1024
RAW_LIMIT = 6 * 1024 * 1024
RECORD_LIMIT = 256 * 1024
TAR_LIMIT = 4_226_048
FLOOR_BYTES = 43_620_761_600
ENTRY_METADATA_UPPER_BYTES = 4096
MINIMUM_OUTSIDE_COPY_RESERVE = 2 * 3 * (4096 + ENTRY_METADATA_UPPER_BYTES)
MEMBERS = (
    ("/usr/lib/x86_64-linux-gnu/Scrt1.o", 1656, 12288, True),
    ("/usr/lib/gcc/x86_64-linux-gnu/11/crtbeginS.o", 2752, 13312, True),
    ("/usr/lib/gcc/x86_64-linux-gnu/11/crtendS.o", 1168, 11776, True),
    ("/lib/x86_64-linux-gnu/libc.so.6", 2220400, 2230784, True),
    ("/usr/lib/gcc/x86_64-linux-gnu/11/liblto_plugin.so", 89120, 99840, True),
    ("/lib/x86_64-linux-gnu/libgcc_s.so.1", 125488, 136192, True),
    ("/usr/lib/x86_64-linux-gnu/libc.so", 283, 10752, False),
    ("/usr/lib/gcc/x86_64-linux-gnu/11/libgcc_s.so", 132, 10752, False),
    ("/var/lib/dpkg/status", 869316, 879616, False),
    ("/var/lib/dpkg/info/gcc-11.md5sums", 2804, 13312, False),
    ("/var/lib/dpkg/info/cpp-11.md5sums", 287, 10752, False),
    ("/var/lib/dpkg/info/libc6:amd64.md5sums", 21606, 32256, False),
    ("/usr/lib/gcc/x86_64-linux-gnu/11/lto-wrapper", 753768, 764416, True),
)
IDENTITY_PATHS = ("/version", "/info", "/containers/" + CID + "/json?size=1")
ARCHIVE_PATHS = tuple("/containers/" + CID + "/archive?path=" + quote(row[0], safe="") for row in MEMBERS)
SEQUENCE = IDENTITY_PATHS + ARCHIVE_PATHS + IDENTITY_PATHS
B1_ORIGINAL_SHA256 = {
    "report": "4f7dfcabe66e93326b454bb8a4ff0a38136b698da8de042086740b8486d10e90",
    "inspect": "9d515b0717a579df4da87f3193e60eb5c8540e0ec1f52769470354f56ac5584b",
    "provider": "1a0607c6220c3088154be1b3089a6e17ae2fe7561543e937ecaae6ae58501275",
}
SCRIPT_SHA256 = {
    MEMBERS[6][0]: "fe2a4ce2930fc6b3966aa987fae808375446c8d3823b8c21792e991aad9c75df",
    MEMBERS[7][0]: "69a56a9993b7729b29b274e65016031c81f2397f176ed5ad44d59bd50425e0bd",
}


def _fail(cause):
    raise compiler.FixtureCompilerError("f2_" + cause)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


class _DeadlineV1:
    """One sticky absolute clock; synchronous kernel calls are non-preemptible.

    Every returned native operation is checked. A late return never accepts,
    earns another write window, or permits a new failure-record attempt.
    """
    def __init__(self, clock):
        self.clock = clock
        self.last = clock()
        if type(self.last) is not int or self.last < 0:
            _fail("clock")
        self.deadline = self.last + 90_000_000_000
        self.exhausted = False
        self.cause = None

    def check(self):
        if self.exhausted:
            _fail(self.cause)
        value = self.clock()
        if type(value) is not int or value < self.last:
            self.exhausted, self.cause = True, "clock"
        elif value >= self.deadline:
            self.exhausted, self.cause = True, "deadline"
        if self.exhausted:
            _fail(self.cause)
        self.last = value
        return value


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _fail("duplicate_field")
        result[key] = value
    return result


def _json(raw):
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_unique,
                          parse_constant=lambda value: _fail("nonfinite"))
    except (ValueError, UnicodeError, RecursionError) as error:
        raise compiler.FixtureCompilerError("f2_json") from error


def _path_stat(fields, name, size):
    if type(fields) is str:
        if not fields.startswith("X-Docker-Container-Path-Stat: ") or not fields.endswith("\r\n"):
            _fail("archive_stat")
        encoded = fields[len("X-Docker-Container-Path-Stat: "):-2]
    else:
        encoded = fields.get("x-docker-container-path-stat")
    if type(encoded) is not str or not 1 <= len(encoded) <= 8192:
        _fail("archive_stat")
    try:
        value = _json(base64.b64decode(encoded, validate=True))
    except (ValueError, UnicodeError) as error:
        raise compiler.FixtureCompilerError("f2_archive_stat") from error
    # Moby PathStat.Mode is Go os.FileMode, not POSIX st_mode:
    # https://pkg.go.dev/github.com/moby/moby/api/types/container#PathStat
    # https://go.dev/src/io/fs/fs.go: IsRegular means (mode & ModeType) == 0.
    mode_type = sum(1 << bit for bit in (31, 27, 26, 25, 24, 21, 19))
    if (type(value) is not dict or set(value) != {"name", "size", "mode", "mtime", "linkTarget"}
            or value["name"] != name or type(value["size"]) is not int or value["size"] != size
            or type(value["mode"]) is not int or not 0 <= value["mode"] <= 0xffffffff
            or value["mode"] & mode_type or value["linkTarget"] != ""
            or type(value["mtime"]) is not str or not 1 <= len(value["mtime"]) <= 64):
        _fail("archive_stat")
    return value


class _ArchiveClientV1(compiler._DockerClientV1):
    LIMIT = ORDINARY_LIMIT = 12 * 1024 * 1024
    RPC_LIMIT = 19

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.decoded_tar_bytes = 0
        self.sequence_epoch = None
        self.archive_stats = {}

    def _reply_body_limit(self, method, path, status, fields):
        if path not in ARCHIVE_PATHS:
            return None
        if status != 200:
            raise self._error("f2_archive_status")
        name, size, cap, _ = MEMBERS[ARCHIVE_PATHS.index(path)]
        try:
            self.archive_stats[path] = _path_stat(fields, Path(name).name, size)
        except compiler.FixtureCompilerError as error:
            raise self._error(error.causes[0]) from error
        return min(cap, TAR_LIMIT - self.decoded_tar_bytes)

    def _decode_reply(self, status, data, *, method, path, fields):
        if path in ARCHIVE_PATHS:
            if status != 200:
                raise self._error("f2_archive_status")
            return data
        return super()._decode_reply(status, data, method=method, path=path, fields=fields)

    def request(self, method, path, body=None, deadline_ns=None, upgrade=False, *, cleanup=False):
        index = self.facts["attempts"]
        if (index >= len(SEQUENCE) or method != "GET" or path != SEQUENCE[index]
                or body is not None or upgrade or cleanup or deadline_ns is not None):
            raise self._error("f2_rpc_inventory")
        self._remaining(self.deadline)
        epoch = self._observe_endpoint()
        if self.sequence_epoch is None:
            self.sequence_epoch = epoch  # Fresh sequence epoch; never the historical B1 boot's inode.
        if epoch != self.sequence_epoch:
            raise self._error("f2_socket_epoch")
        result = super().request("GET", path, deadline_ns=min(self.deadline, self.last_clock + 5_000_000_000))
        row = self.facts["rpc"][-1]
        if row["epoch_before"] != self.sequence_epoch or row["epoch_after"] != self.sequence_epoch:
            raise self._error("f2_socket_epoch")
        if row["request_bytes"] > 2048 or self.facts["metadata_bytes"] > 2 * RAW_LIMIT:
            raise self._error("f2_raw_bound")
        if path in ARCHIVE_PATHS:
            self.decoded_tar_bytes += len(result)
        return result


def _tar_member(raw, name, size, elf):
    if type(raw) is not bytes or not raw or len(raw) % 512:
        _fail("tar_shape")
    offset, found, pax = 0, None, None
    while offset + 512 <= len(raw):
        header = raw[offset:offset+512]
        if not any(header):
            if found is None or len(raw)-offset < 1024 or any(raw[offset:]):
                _fail("tar_trailing")
            return {"size_bytes": size, "sha256": _sha(found), "elf64_amd64": bool(elf), "_data": found}
        if found is not None:
            _fail("tar_extra_member")
        try:
            checksum = int(header[148:156].strip(b" \0"), 8)
            length_field = header[124:136].strip(b" \0")
            if not re.fullmatch(rb"[0-7]{1,11}", length_field):
                _fail("tar_size")
            length = int(length_field, 8)
            member_name = header[:100].split(b"\0", 1)[0].decode("ascii")
        except (ValueError, UnicodeError) as error:
            raise compiler.FixtureCompilerError("f2_tar_header") from error
        if (checksum != sum(header[:148]) + 8*32 + sum(header[156:])
                or header[257:262] != b"ustar" or any(header[345:500])):
            _fail("tar_header")
        begin, end = offset+512, offset+512+length
        padded = ((end+511)//512)*512
        if padded > len(raw) or any(raw[end:padded]):
            _fail("tar_truncated")
        kind = header[156:157]
        if kind == b"x":
            if pax is not None or length > 4096:
                _fail("tar_pax")
            pax, at = {}, begin
            while at < end:
                space = raw.find(b" ", at, min(end, at+8))
                digits = raw[at:space] if space >= 0 else b""
                if not re.fullmatch(rb"[1-9][0-9]{0,5}", digits):
                    _fail("tar_pax")
                last = at+int(digits)
                if last > end or last <= space+2 or raw[last-1:last] != b"\n":
                    _fail("tar_pax")
                key, equals, value = raw[space+1:last-1].partition(b"=")
                if not equals or key in pax or key not in (b"path", b"mtime", b"atime", b"ctime"):
                    _fail("tar_pax")
                if key == b"path":
                    if value != name.encode("ascii"):
                        _fail("tar_pax")
                elif not re.fullmatch(rb"-?[0-9]{1,20}(\.[0-9]{1,20})?", value):
                    _fail("tar_pax")
                pax[key] = value
                at = last
        elif kind in (b"0", b"\0"):
            if member_name != name or "/" in member_name or length != size or any(header[157:257]):
                _fail("tar_member")
            found = raw[begin:end]
            if elf and (len(found) < 20 or found[:6] != b"\x7fELF\x02\x01" or found[18:20] != b"\x3e\0"):
                _fail("elf_abi")
        else:
            _fail("tar_member_type")
        offset = padded
    _fail("tar_truncated")


def _packages(raw):
    selected = {}
    for stanza in raw.decode("utf-8").split("\n\n"):
        fields = {}
        for line in stanza.splitlines():
            if not line or line[0] in " \t":
                continue
            key, colon, value = line.partition(":")
            if not colon or not re.fullmatch("[A-Za-z0-9-]+", key) or value and not value.startswith(" "):
                _fail("package_field")
            value = value[1:] if value.startswith(" ") else value
            if key in ("Package", "Version", "Architecture", "Status"):
                if key in fields or len(value) > 512:
                    _fail("package_field")
                fields[key] = value
        if fields.get("Status") == "install ok installed":
            if set(fields) != {"Package", "Version", "Architecture", "Status"} or not fields["Version"]:
                _fail("package_field")
            key = fields["Package"]+":"+fields["Architecture"]
            if key in selected or not re.fullmatch(r"[a-z0-9][a-z0-9+.-]*:[a-z0-9][a-z0-9-]*", key):
                _fail("package_duplicate")
            selected[key] = fields["Version"]
    return selected


def _md5_associations(raw):
    result = {}
    for line in raw.splitlines():
        match = re.fullmatch(rb"([0-9a-f]{32})  ([ -~]{1,4096})", line)
        if match is None:
            _fail("md5_metadata")
        path = match[2].decode("ascii")
        if path.startswith("/") or any(part in ("", ".", "..") for part in path.split("/")):
            _fail("md5_path")
        path = "/"+path
        if path in result:
            _fail("md5_duplicate")
        result[path] = match[1].decode("ascii")
    return result


def _linker_references(path, raw):
    if _sha(raw) != SCRIPT_SHA256.get(path):
        _fail("linker_script_hash")
    if path == MEMBERS[6][0]:
        refs = ["/lib/x86_64-linux-gnu/libc.so.6", "/usr/lib/x86_64-linux-gnu/libc_nonshared.a", "/lib64/ld-linux-x86-64.so.2"]
    else:
        refs = ["libgcc_s.so.1", "-lgcc"]
    # The exact B1 hash authenticates the script before these fixed references
    # are interpreted; this never discovers or fetches additional paths.
    text = raw.decode("ascii")
    if any(item not in text for item in refs):
        _fail("linker_reference")
    return refs


def _read_bounded(path, limit=RAW_LIMIT, *, deadline_check=None):
    if deadline_check is not None:
        deadline_check()
    path = Path(path)
    info = path.lstat()
    if not path.is_absolute() or not stat.S_ISREG(info.st_mode) or path.resolve(strict=True) != path or info.st_size > limit:
        _fail("original_file")
    with path.open("rb") as file:
        if deadline_check is not None:
            deadline_check()
        raw = file.read(limit+1)
        after = os.fstat(file.fileno())
        if deadline_check is not None:
            deadline_check()
    if deadline_check is not None:
        deadline_check()
    before_id = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
    if len(raw) > limit or len(raw) != info.st_size or before_id != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
        _fail("original_drift")
    return raw


def _descriptor(path, root=None, *, deadline_check=None):
    path = Path(path)
    raw = _read_bounded(path, deadline_check=deadline_check)
    key = "relative_path" if root is not None else "path"
    return {key: path.relative_to(root).as_posix() if root is not None else str(path),
            "size_bytes": len(raw), "sha256": _sha(raw)}


def _record_bound(value, depth=0, ancestors=None, nodes=None):
    if ancestors is None:
        ancestors, nodes = set(), [0]
    nodes[0] += 1
    if depth > 32 or nodes[0] > 32768:
        _fail("record_bound")
    if type(value) not in (dict, list, tuple):
        size = compiler._json_bound(value)
        if size > RECORD_LIMIT:
            _fail("record_bound")
        return size
    if len(value) > 4096 or id(value) in ancestors:
        _fail("record_bound")
    ancestors.add(id(value))
    try:
        size = 2
        for key, item in value.items() if type(value) is dict else ((None, item) for item in value):
            if type(value) is dict:
                if type(key) is not str:
                    _fail("record_bound")
                size += _record_bound(key, depth+1, ancestors, nodes)+1
            size += _record_bound(item, depth+1, ancestors, nodes)+1
            if size > RECORD_LIMIT:
                _fail("record_bound")
        return size
    finally:
        ancestors.remove(id(value))


def _write_json(path, value, *, deadline_check=None):
    file, causes = None, []
    facts = {"path": str(path), "complete": False, "open_completed": False,
             "written_bytes": 0, "persisted_bytes": 0, "write_extent_unknown": False,
             "flush_completed": False, "fsync_completed": False, "close_completed": False,
             "deadline_failed": False}
    def check():
        if deadline_check is not None:
            try:
                deadline_check()
            except compiler.FixtureCompilerError:
                facts["deadline_failed"] = True
                raise
    try:
        check()
        if _record_bound(value) > RECORD_LIMIT:
            _fail("record_bound")
        check()
        raw = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("ascii")
        check()
        if len(raw) > RECORD_LIMIT:
            _fail("record_bound")
        file = Path(path).open("xb")
        facts["open_completed"] = True
        check()
        try:
            written = file.write(raw)
        except (OSError, ValueError, TypeError):
            facts["write_extent_unknown"] = True
            raise
        if type(written) is not int or not 0 <= written <= len(raw):
            facts["write_extent_unknown"] = True
            _fail("record_write_extent_unknown")
        facts["written_bytes"] = written
        check()
        if written != len(raw):
            _fail("record_short_write")
        file.flush()
        facts["flush_completed"] = True
        check()
        os.fsync(file.fileno())
        facts["fsync_completed"] = True
        facts["persisted_bytes"] = written
        check()
    except compiler.FixtureCompilerError as error:
        causes.extend(error.causes)
    except (OSError, ValueError, TypeError, RecursionError) as error:
        causes.append("f2_record_" + type(error).__name__)
    finally:
        if file is not None:
            try:
                file.close()
                facts["close_completed"] = True
            except (OSError, ValueError, TypeError) as error:
                causes.append("f2_record_close_"+type(error).__name__)
            try:
                check()
            except compiler.FixtureCompilerError as error:
                causes.extend(code for code in error.causes if code not in causes)
    if causes:
        error = compiler.FixtureCompilerError(*causes)
        error.facts = facts
        raise error
    try:
        descriptor = _descriptor(Path(path), Path(path).parent, deadline_check=deadline_check)
        check()
    except (compiler.FixtureCompilerError, OSError, ValueError, TypeError) as error:
        failure = compiler.FixtureCompilerError(*(error.causes if isinstance(error, compiler.FixtureCompilerError)
                                               else ["f2_record_"+type(error).__name__]))
        facts["deadline_failed"] = isinstance(error, compiler.FixtureCompilerError) and any(
            code in ("f2_clock", "f2_deadline") for code in error.causes)
        failure.facts = facts
        raise failure from error
    facts["complete"] = True
    return descriptor


def _http_original(raw, body_limit=RAW_LIMIT):
    if type(raw) is not bytes or len(raw) > RAW_LIMIT:
        _fail("sealed_http")
    header, marker, body = raw.partition(b"\r\n\r\n")
    if (not marker or len(header)+4 > 8192
            or not re.fullmatch(rb"HTTP/1\.1 200 [ -~]*", header.split(b"\r\n")[0])):
        _fail("sealed_http")
    fields = {}
    for line in header.split(b"\r\n")[1:]:
        key, colon, value = line.partition(b":")
        if (not colon or not re.fullmatch(rb"[!#$%&'*+.^_`|~0-9A-Za-z-]+", key)
                or any(point < 32 or point > 126 for point in value)):
            _fail("sealed_http")
        key = key.decode("ascii").lower()
        if key in fields:
            _fail("sealed_http")
        fields[key] = value.strip(b" ").decode("ascii")
    if "content-encoding" in fields:
        _fail("sealed_http")
    if "transfer-encoding" in fields:
        if fields["transfer-encoding"].lower() != "chunked" or "content-length" in fields:
            _fail("sealed_http")
        blocks, at, used = [], 0, 0
        while True:
            end = body.find(b"\r\n", at, at+128)
            digits = body[at:end] if end >= 0 else b""
            if not re.fullmatch(rb"[0-9a-fA-F]{1,16}", digits):
                _fail("sealed_http")
            size, at = int(digits, 16), end+2
            if size > body_limit-used:
                _fail("sealed_http_bound")
            if size == 0:
                if body[at:] != b"\r\n":
                    _fail("sealed_http")
                break
            if at+size+2 > len(body) or body[at+size:at+size+2] != b"\r\n":
                _fail("sealed_http")
            blocks.append(body[at:at+size])
            used += size
            at += size+2
        body = b"".join(blocks)
    else:
        length = fields.get("content-length", "")
        if not re.fullmatch("[0-9]{1,10}", length) or int(length) != len(body) or len(body) > body_limit:
            _fail("sealed_http")
    return fields, body


def _http_json(raw):
    return _json(_http_original(raw)[1])


def _measurement():
    root, host = os.statvfs("/"), os.statvfs("/mnt/c")
    return {"ext4_used_bytes": (root.f_blocks-root.f_bfree)*root.f_frsize,
            "c_free_bytes": host.f_bavail*host.f_frsize, "fragment_bytes": root.f_frsize}


def _output_filesystem_v1(parent):
    parent = Path(parent)
    if (not parent.is_absolute() or parent.resolve(strict=True) != parent
            or parent.stat().st_dev != Path("/").stat().st_dev
            or os.statvfs(parent).f_frsize != 4096):
        _fail("output_filesystem")


def _outside_copy_lower_bound(output):
    """Two possible report/Git copies of each derived control, never raw HTTP."""
    total = 0
    for name in ("f2.originals.v1.json", "f2.supplement.v1.json", "f2.final-accounting.v1.json", "f2.failure.v1.json"):
        path = output/name
        if path.exists():
            size = path.stat().st_size
            if not 0 <= size <= RECORD_LIMIT:
                _fail("record_copy_bound")
            total += 2*(((size+4095)//4096)*4096+ENTRY_METADATA_UPPER_BYTES)
    return total


def _identity(version, info, inspected, sealed):
    if (type(version) is not dict or version.get("Version") != "29.7.2"
            or version.get("ApiVersion") != "1.55" or version.get("Os") != "linux" or version.get("Arch") != "amd64"
            or type(info) is not dict or info.get("ID") != ENGINE_ID
            or info.get("KernelVersion") != "6.6.87.2-microsoft-standard-WSL2"
            or info.get("SecurityOptions") != ["name=seccomp,profile=builtin", "name=cgroupns"]
            or _sha(json.dumps(info.get("Runtimes"), sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode())
            != "b480bc9619d585079ca9926e520ee190fc971f2e7c2c6c01b5256ac058c4a5d1"):
        _fail("engine_identity")
    if (type(inspected) is not dict or inspected.get("Id") != CID or inspected.get("Image") != PROVIDER_ID
            or (inspected.get("Config") or {}).get("Image") != PROVIDER_ID
            or (inspected.get("HostConfig") or {}).get("ReadonlyRootfs") is not True):
        _fail("source_identity")
    state = inspected.get("State") or {}
    if (state.get("Status") != "exited" or state.get("Pid") != 0 or state.get("ExitCode") != 0
            or state.get("Error") != "" or inspected.get("RestartCount") != 0
            or any(state.get(key) is not False for key in ("Running", "Paused", "Restarting", "OOMKilled", "Dead"))):
        _fail("source_state")
    keys = ("Id", "Image", "Path", "Args", "Config", "HostConfig", "Mounts", "State", "RestartCount",
            "Driver", "Platform", "ImageManifestDescriptor", "SizeRw", "SizeRootFs")
    selected = {key: inspected.get(key) for key in keys}
    if selected != {key: sealed.get(key) for key in keys}:
        _fail("source_drift")
    return {"engine_id": ENGINE_ID, "version": "29.7.2", "source_sha256": _sha(
            json.dumps(selected, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode())}


def _package_facts(raws, report):
    packages = _packages(raws[MEMBERS[8][0]])
    keys = ("gcc-11:amd64", "cpp-11:amd64", "libc6:amd64", "libgcc-s1:amd64")
    if any(key not in packages for key in keys):
        _fail("package_missing")
    associations = {}
    for index in (9, 10, 11):
        rows = _md5_associations(raws[MEMBERS[index][0]])
        associations[Path(MEMBERS[index][0]).name] = {path: digest for path, digest in rows.items()
                if path in raws or path in {value.get("resolved", {}).get("realpath")
                for value in report["report"]["toolchain"]["helpers"].values()}}
    scripts = {path: _linker_references(path, raws[path]) for path in SCRIPT_SHA256}
    return {"kind": "package_metadata_not_authenticity_or_direct_version",
            "installed_versions": {key: packages[key] for key in keys},
            "md5_associations": associations, "linker_references": scripts,
            "libc_banner": {"kind": "embedded_bytes_not_execution", "text": next((
                value.decode("ascii") for value in re.findall(rb"GNU C Library[^\0\n]{1,256}", raws[MEMBERS[3][0]])), None)}}


def recover_stopped_b1_v1(*, output_dir, review, b1_originals, remaining_seal_bytes,
                          retained_elsewhere_upper_bytes=512*1024, clock=None, socket_factory=None, measure=None):
    """Recover once after external packet approval; failure never retries or cleans."""
    clock_fn = clock if clock is not None else time.monotonic_ns
    measure_fn = measure if measure is not None else _measurement
    timer = _DeadlineV1(clock_fn)
    if (type(review) is not dict or set(review) != {"commit", "approval_reference", "physical_plan_sha256"}
            or not re.fullmatch("[0-9a-f]{40}", review.get("commit", ""))
            or not re.fullmatch("[0-9a-f]{64}", review.get("physical_plan_sha256", ""))
            or type(review.get("approval_reference")) is not str or not 1 <= len(review["approval_reference"]) <= 512
            or type(remaining_seal_bytes) is not int or remaining_seal_bytes < TOTAL_LIMIT
            or type(retained_elsewhere_upper_bytes) is not int or not MINIMUM_OUTSIDE_COPY_RESERVE <= retained_elsewhere_upper_bytes <= 512*1024
            or type(b1_originals) is not dict or set(b1_originals) != set(B1_ORIGINAL_SHA256)):
        _fail("binding_or_reserve")
    # This fresh operation interval includes authority reads and every new F2
    # form. Approved B charges remain fixed; idle time is not a B3 anchor.
    baseline = measure_fn()
    timer.check()
    if (type(baseline) is not dict or any(type(baseline.get(key)) is not int or baseline[key] < 0
            for key in ("ext4_used_bytes", "c_free_bytes")) or baseline["c_free_bytes"] < FLOOR_BYTES+TOTAL_LIMIT
            or baseline.get("fragment_bytes", 4096 if measure is not None else None) != 4096):
        _fail("measurement_or_floor")
    original_descriptors, originals = {}, {}
    for key, expected in B1_ORIGINAL_SHA256.items():
        timer.check()
        path = Path(b1_originals[key])
        descriptor = _descriptor(path, deadline_check=timer.check)
        if descriptor["sha256"] != expected:
            _fail("sealed_original_hash")
        original_descriptors[key], originals[key] = descriptor, _read_bounded(path, deadline_check=timer.check)
        if _sha(originals[key]) != expected:
            _fail("sealed_original_hash")
    report, sealed = _json(originals["report"]), _http_json(originals["inspect"])
    provider = _http_json(originals["provider"])
    if (provider.get("Id") != PROVIDER_ID or _sha(json.dumps(provider.get("RootFS"), sort_keys=True,
            separators=(",", ":"), ensure_ascii=True).encode()) != "1e0fe0c49e48962dc125b19e5b1936c564f1c6a3e00006d5e5cca7dc7ebfd981"):
        _fail("sealed_provider")
    output = Path(output_dir)
    timer.check()
    if not output.is_absolute() or output.exists() or output.parent.resolve(strict=True) != output.parent:
        _fail("output_not_fresh")
    _output_filesystem_v1(output.parent)
    timer.check()
    output.mkdir(mode=0o700)
    client = _ArchiveClientV1(output, timer.deadline, clock=timer.check, socket_factory=socket_factory)
    client.facts["controlled_clock"] = clock is not None
    facts = {"schema_version": 1, "artifact_kind": "vast_fixture_compiler_toolchain_recovery_v1",
             "complete": False, "causes": [], "controlled": clock is not None or socket_factory is not None or measure is not None,
             "review": dict(review), "cid": CID, "provider_id": PROVIDER_ID, "b1_originals": original_descriptors,
             "members": [], "identity": {}, "transport": client.facts, "accounting": {"baseline": baseline,
             "retained_elsewhere_upper_bytes": retained_elsewhere_upper_bytes},
             "cc1_direct_version": {"available": False, "source_sha256": B1_ORIGINAL_SHA256["report"],
                                    "observation": "B1 actual --version stdout/stderr empty; package version is separate"}}

    budget_failed = False
    def _account(final=False):
        nonlocal budget_failed
        timer.check()

        observed = measure_fn()
        if type(observed) is not dict or any(type(observed.get(key)) is not int or observed[key] < 0
                for key in ("ext4_used_bytes", "c_free_bytes")) or observed.get("fragment_bytes", 4096 if measure is not None else None) != 4096:
            _fail("measurement_unknown")
        raw_names = {"RPC%02d.%s.original" % (number, role) for number in range(1, 20) for role in ("request", "reply")}
        control_names = {"f2.originals.v1.json", "f2.supplement.v1.json", "f2.final-accounting.v1.json", "f2.failure.v1.json"}
        entries = [output]
        for path in output.iterdir():
            if len(entries) >= 43 or path.name not in raw_names | control_names or not stat.S_ISREG(path.lstat().st_mode):
                _fail("output_inventory")
            entries.append(path)
        data_allocated = 0
        for path in entries:
            info = path.lstat()
            if not hasattr(info, "st_blocks"):
                _fail("allocation_unknown")
            data_allocated += info.st_blocks*512
        metadata_upper = len(entries)*ENTRY_METADATA_UPPER_BYTES
        allocated = data_allocated+metadata_upper
        raw_bytes = sum(path.stat().st_size for path in output.glob("RPC*.original"))
        charge = max(allocated, observed["ext4_used_bytes"]-baseline["ext4_used_bytes"],
                     baseline["c_free_bytes"]-observed["c_free_bytes"], 0)+retained_elsewhere_upper_bytes
        present = {path.name for path in entries[1:]}
        remaining_controls = len(control_names-present)*RECORD_LIMIT
        remaining_raw = max(0, RAW_LIMIT-raw_bytes) if client.facts["attempts"] < 19 else 0
        rounding = (len(raw_names-present) + len(control_names-present))*4096
        metadata_reserve = (len(raw_names-present)+len(control_names-present))*ENTRY_METADATA_UPPER_BYTES
        liability = remaining_raw+remaining_controls+rounding+metadata_reserve
        copy_lower = _outside_copy_lower_bound(output)
        facts["accounting"].update({"last": observed, "raw_originals_bytes": raw_bytes,
                                   "retained_allocated_bytes": allocated, "physical_charge_bytes": charge,
                                   "retained_data_allocated_bytes": data_allocated, "retained_metadata_upper_bytes": metadata_upper,
                                   "reserved_control_bytes": remaining_controls,
                                   "reserved_raw_bytes": remaining_raw, "reserved_rounding_bytes": rounding,
                                   "reserved_metadata_bytes": metadata_reserve,
                                   "retained_elsewhere_lower_bytes": copy_lower})
        if (observed["c_free_bytes"] < FLOOR_BYTES+liability or raw_bytes > RAW_LIMIT
                or charge+liability > TOTAL_LIMIT or retained_elsewhere_upper_bytes < copy_lower):
            budget_failed = True
            _fail("physical_or_logical_bound")
        timer.check()

    def account(final=False):
        nonlocal budget_failed
        try:
            _account(final)
        except (compiler.FixtureCompilerError, OSError, ValueError, TypeError):
            budget_failed = True
            raise

    try:
        account()
        def identity_calls():
            replies = []
            for path in IDENTITY_PATHS:
                account()
                replies.append(client.request("GET", path))
            return replies
        first = identity_calls()
        facts["identity"]["before"] = _identity(*first, sealed)
        raws = {}
        for spec, path in zip(MEMBERS, ARCHIVE_PATHS):
            account()
            # Recheck the already-authenticated stopped-source binding before
            # each GET; there is deliberately no extra RPC or mutable path set.
            _identity(*first, sealed)
            data = client.request("GET", path)
            name, size, _, elf = spec
            member = _tar_member(data, Path(name).name, size, elf)
            raws[name] = member.pop("_data")
            if name in SCRIPT_SHA256:
                _linker_references(name, raws[name])
            number = client.facts["attempts"]
            member.update({"path": name, "stat": client.archive_stats[path], "originals": [
                _descriptor(output/("RPC%02d.%s.original" % (number, role)), output,
                            deadline_check=timer.check) for role in ("request", "reply")]})
            facts["members"].append(member)
            account()
        last = identity_calls()
        facts["identity"]["after"] = _identity(*last, sealed)
        if facts["identity"]["before"] != facts["identity"]["after"] or client.facts["attempts"] != 19:
            _fail("final_identity")
        facts["package_facts"] = _package_facts(raws, report)
        index = {"schema_version": 1, "originals": [_descriptor(path, output, deadline_check=timer.check)
                            for path in sorted(output.glob("RPC*.original"))]}
        account()
        facts["originals_index"] = _write_json(output/"f2.originals.v1.json", index, deadline_check=timer.check)
        account()
        facts["complete"] = True
        descriptor = _write_json(output/"f2.supplement.v1.json", facts, deadline_check=timer.check)
        account(final=True)
        # A separate bounded footer records the post-supplement measurement;
        # its entire upper bound was reserved before the preceding write.
        finalization = _write_json(output/"f2.final-accounting.v1.json", {
            "schema_version": 1, "supplement": descriptor, "accounting": facts["accounting"]}, deadline_check=timer.check)
        account(final=True)
        saved = _json(_read_bounded(output/"f2.supplement.v1.json", RECORD_LIMIT, deadline_check=timer.check))
        timer.check()
        return {"supplement": saved,
                "supplement_descriptor": descriptor, "final_accounting_descriptor": finalization}
    except (compiler.FixtureCompilerError, OSError, ValueError, TypeError, RecursionError, OverflowError) as error:
        facts["complete"] = False
        facts["causes"] = list(error.causes) if isinstance(error, compiler.FixtureCompilerError) else ["f2_"+type(error).__name__]
        if hasattr(error, "facts") and error.facts is not client.facts:
            facts["failed_record"] = error.facts
        failure_reserved = False
        if not budget_failed and not timer.exhausted:
            try:
                account()
                timer.check()
                failure_reserved = True
            except (compiler.FixtureCompilerError, OSError, ValueError, TypeError) as reservation:
                for code in reservation.causes if isinstance(reservation, compiler.FixtureCompilerError) else ["f2_reservation_"+type(reservation).__name__]:
                    if code not in facts["causes"]:
                        facts["causes"].append(code)
        if failure_reserved:
            try:
                _write_json(output/"f2.failure.v1.json", facts, deadline_check=timer.check)
            except compiler.FixtureCompilerError as persistence:
                facts["causes"].extend(code for code in persistence.causes if code not in facts["causes"])
                facts["failure_record"] = getattr(persistence, "facts", None)
        else:
            facts["failure_record_not_started"] = "deadline_exhausted" if timer.exhausted else "reservation_unavailable"
        failure = compiler.FixtureCompilerError(*facts["causes"])
        failure.facts = facts
        raise failure from error


def validate_supplement_v1(*, output_dir, supplement):
    """Independently reread F2 evidence only; no socket/process/container action.

    External packet review binds these files. This validator checks captured
    bytes and recorded facts; it cannot reconstruct unrecorded past events.
    """
    try:
        output = Path(output_dir)
        if not output.is_absolute() or output.resolve(strict=True) != output or not output.is_dir():
            _fail("validation_root")
        _output_filesystem_v1(output)
        raw_supplement = _read_bounded(output/"f2.supplement.v1.json", RECORD_LIMIT)
        if (type(supplement) is not dict or _json(raw_supplement) != supplement
                or supplement.get("schema_version") != 1
                or supplement.get("artifact_kind") != "vast_fixture_compiler_toolchain_recovery_v1"
                or supplement.get("complete") is not True or supplement.get("causes") != []
                or supplement.get("controlled") is not False or supplement.get("cid") != CID
                or supplement.get("provider_id") != PROVIDER_ID):
            _fail("validation_supplement")
        if supplement.get("cc1_direct_version") != {"available": False,
                "source_sha256": B1_ORIGINAL_SHA256["report"],
                "observation": "B1 actual --version stdout/stderr empty; package version is separate"}:
            _fail("validation_direct_version")
        source = supplement.get("b1_originals")
        if type(source) is not dict or set(source) != set(B1_ORIGINAL_SHA256):
            _fail("validation_originals")
        originals = {}
        for key, expected in B1_ORIGINAL_SHA256.items():
            descriptor = source[key]
            if type(descriptor) is not dict or descriptor != _descriptor(Path(descriptor["path"])) or descriptor["sha256"] != expected:
                _fail("validation_originals")
            originals[key] = _read_bounded(Path(descriptor["path"]))
            if _sha(originals[key]) != expected:
                _fail("validation_originals")
        sealed, report = _http_json(originals["inspect"]), _json(originals["report"])
        expected_files = {"f2.supplement.v1.json", "f2.originals.v1.json", "f2.final-accounting.v1.json"}
        expected_files.update("RPC%02d.%s.original" % (number, role)
                              for number in range(1, 20) for role in ("request", "reply"))
        if {path.name for path in output.iterdir()} != expected_files:
            _fail("validation_inventory")
        actual_index = {"schema_version": 1, "originals": [_descriptor(path, output)
                        for path in sorted(output.glob("RPC*.original"))]}
        if (sum(row["size_bytes"] for row in actual_index["originals"]) > RAW_LIMIT
                or _json(_read_bounded(output/"f2.originals.v1.json", RECORD_LIMIT)) != actual_index
                or supplement.get("originals_index") != _descriptor(output/"f2.originals.v1.json", output)):
            _fail("validation_index")
        transport = supplement.get("transport")
        if (type(transport) is not dict or transport.get("attempts") != 19
                or transport.get("controlled_socket") is not False or transport.get("controlled_clock") is not False
                or transport.get("metadata_bytes") != 2*sum(row["size_bytes"] for row in actual_index["originals"])
                or type(transport.get("rpc")) is not list or len(transport["rpc"]) != 19):
            _fail("validation_transport")
        raws, decoded, epoch, identity = {}, 0, None, []
        members = supplement.get("members")
        if type(members) is not list or len(members) != 13:
            _fail("validation_members")
        for number, path in enumerate(SEQUENCE, 1):
            request_path, reply_path = (output/("RPC%02d.%s.original" % (number, role)) for role in ("request", "reply"))
            request = _read_bounded(request_path, 2048)
            expected = ("GET /v1.55%s HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\nContent-Length: 0\r\n\r\n" % path).encode("ascii")
            if request != expected:
                _fail("validation_request")
            row = transport["rpc"][number-1]
            if (type(row) is not dict or row.get("number") != number or row.get("status") != 200 or row.get("causes") != []
                    or any(row.get(key) is not True for key in ("complete", "request_persisted", "reply_persisted",
                        "request_close_completed", "reply_close_completed", "request_send_complete", "reply_eof", "socket_closed"))
                    or any(row.get(key) is not False for key in ("request_write_extent_unknown", "reply_write_extent_unknown",
                        "request_persistence_failed", "reply_persistence_failed", "upgraded"))
                    or type(row.get("peer")) is not dict or row["peer"].get("uid") != 0
                    or type(row["peer"].get("pid")) is not int or row["peer"]["pid"] <= 0
                    or type(row["peer"].get("gid")) is not int or row["peer"]["gid"] < 0):
                _fail("validation_transport")
            if epoch is None:
                epoch = row.get("epoch_before")
            if not epoch or row.get("epoch_before") != epoch or row.get("epoch_after") != epoch:
                _fail("validation_epoch")
            wire = _read_bounded(reply_path)
            if (row.get("request_bytes") != len(request) or row.get("request_written_bytes") != len(request)
                    or row.get("request_persisted_bytes") != len(request)
                    or any(row.get(key) != len(wire) for key in ("reply_observed_bytes", "reply_written_bytes",
                        "reply_persisted_bytes", "reply_retained_bytes"))):
                _fail("validation_counts")
            if path in ARCHIVE_PATHS:
                index = ARCHIVE_PATHS.index(path)
                name, size, cap, elf = MEMBERS[index]
                fields, data = _http_original(wire, min(cap, TAR_LIMIT-decoded))
                observed = _tar_member(data, Path(name).name, size, elf)
                raws[name] = observed.pop("_data")
                observed.update({"path": name, "stat": _path_stat(fields, Path(name).name, size),
                                 "originals": [_descriptor(item, output) for item in (request_path, reply_path)]})
                if observed != members[index]:
                    _fail("validation_member")
                decoded += len(data)
            else:
                identity.append(_http_json(wire))
        before, after = _identity(*identity[:3], sealed), _identity(*identity[3:], sealed)
        if before != after or supplement.get("identity") != {"before": before, "after": after}:
            _fail("validation_identity")
        if supplement.get("package_facts") != _package_facts(raws, report):
            _fail("validation_package")
        footer = _json(_read_bounded(output/"f2.final-accounting.v1.json", RECORD_LIMIT))
        account = footer.get("accounting") if type(footer) is dict else None
        if (type(footer) is not dict or footer.get("schema_version") != 1
                or footer.get("supplement") != _descriptor(output/"f2.supplement.v1.json", output)
                or type(account) is not dict or any(type(account.get(key)) is not int or account[key] < 0 for key in
                    ("physical_charge_bytes", "retained_allocated_bytes", "retained_elsewhere_upper_bytes", "reserved_control_bytes",
                     "retained_data_allocated_bytes", "retained_metadata_upper_bytes", "retained_elsewhere_lower_bytes"))
                or account["reserved_control_bytes"] != 2*RECORD_LIMIT
                or account.get("reserved_raw_bytes") != 0 or account.get("reserved_rounding_bytes") != 2*4096
                or account.get("reserved_metadata_bytes") != 2*ENTRY_METADATA_UPPER_BYTES
                or account["retained_metadata_upper_bytes"] != 41*ENTRY_METADATA_UPPER_BYTES
                or account["retained_allocated_bytes"] != account["retained_data_allocated_bytes"]+account["retained_metadata_upper_bytes"]
                or account["physical_charge_bytes"]+account["reserved_control_bytes"]+4*4096 > TOTAL_LIMIT
                or account.get("raw_originals_bytes") != sum(item["size_bytes"] for item in actual_index["originals"])
                or (account.get("last") or {}).get("c_free_bytes", -1) < FLOOR_BYTES+2*RECORD_LIMIT+4*4096
                or sum(path.lstat().st_blocks*512+ENTRY_METADATA_UPPER_BYTES for path in [output]+list(output.iterdir()))
                    + account["retained_elsewhere_upper_bytes"] > account["physical_charge_bytes"]+2*RECORD_LIMIT+4*4096
                or not account["retained_elsewhere_lower_bytes"] <= _outside_copy_lower_bound(output) <= account["retained_elsewhere_upper_bytes"]):
            _fail("validation_accounting")
        for phase in ("baseline", "last"):
            if type(account.get(phase)) is not dict or any(type(account[phase].get(key)) is not int or account[phase][key] < 0
                    for key in ("ext4_used_bytes", "c_free_bytes")):
                _fail("validation_accounting")
        computed = max(account["retained_allocated_bytes"],
                account["last"]["ext4_used_bytes"]-account["baseline"]["ext4_used_bytes"],
                account["baseline"]["c_free_bytes"]-account["last"]["c_free_bytes"], 0)+account["retained_elsewhere_upper_bytes"]
        if computed != account["physical_charge_bytes"] or not 0 <= account["retained_elsewhere_upper_bytes"] <= 512*1024:
            _fail("validation_accounting")
        return {"complete": True, "members": 13, "decoded_tar_bytes": decoded,
                "supplement": _descriptor(output/"f2.supplement.v1.json", output),
                "final_accounting": _descriptor(output/"f2.final-accounting.v1.json", output)}
    except compiler.FixtureCompilerError:
        raise
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError, OverflowError) as error:
        raise compiler.FixtureCompilerError("f2_validation_"+type(error).__name__) from error
