"""Fixed, bounded compiler support for the artificial custody engine only."""
import json
import math
import hashlib
import os
from pathlib import Path
import re
import struct

from publication_operational_request_domain_v1 import canonical_json_v1

SOURCE_LIMIT = 8 * 1024 * 1024
STRING_LIMIT = 1024 * 1024
TABLE_LIMIT = 4096


class FixtureCompilerError(RuntimeError):
    def __init__(self, *causes):
        self.causes = list(causes)
        super().__init__(", ".join(self.causes))


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
        with (output / "export.header.original").open("xb") as file:
            if file.write(prefix + raw) != 12 + length:
                raise FixtureCompilerError("export_header_short_write")
            file.flush()
            os.fsync(file.fileno())
        header_written = True
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
            row = {"size_bytes": 0, "persisted": False, "complete": False, "sha256": None}
            members[name] = row
            digest, remaining = hashlib.sha256(), value["size_bytes"]
            with (output / filename).open("xb") as file:
                interrupted = False
                try:
                    while remaining:
                        block = read(min(65536, remaining))
                        if type(block) is not bytes or len(block) > min(65536, remaining):
                            raise FixtureCompilerError("export_read_contract")
                        facts["observed_bytes"] += len(block)
                        if not block:
                            raise FixtureCompilerError("export_truncated")
                        digest.update(block)
                        if file.write(block) != len(block):
                            raise FixtureCompilerError("export_member_short_write")
                        row["size_bytes"] += len(block)
                        remaining -= len(block)
                except BaseException as error:
                    interrupted = True
                    for cause in (error.causes if isinstance(error, FixtureCompilerError)
                                  else ["export_" + type(error).__name__]):
                        fail(cause)
                finally:
                    row["sha256"] = digest.hexdigest()
                    try:
                        file.flush()
                        os.fsync(file.fileno())
                        row["persisted"] = True
                    except BaseException as error:
                        interrupted = True
                        fail("export_persistence_" + type(error).__name__)
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
        try:
            with (output / "export.prefix.original").open("xb") as file:
                if file.write(header_prefix) != len(header_prefix):
                    raise OSError("short prefix write")
                file.flush()
                os.fsync(file.fileno())
            facts["header_prefix_persisted"] = True
        except OSError as error:
            facts["header_prefix_persisted"] = False
            fail("export_prefix_persistence_" + type(error).__name__)
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
                     6 if point < 32 or 127 < point <= 65535 else 12 if point > 65535 else 1)
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
