"""Task 2.10 fixed component inputs and owner 2.9 sealed descriptors (V5
efa59e92; C5 V6). No Docker/compiler/process action or task 1.5 admission.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import time
from types import MappingProxyType
from typing import Any, Mapping


SOURCE_LIMIT = 8 * 1024 * 1024
SEALED_LIMIT = 4096
D_COMMAND = b"VAST-C1-COMMAND-V1\n"
D_REPLY = b"VAST-C1-REPLY-V1 vast-component-c1\n"
D_STATE_FILE = "engine.state"

# Fixed admission values (plan section 4, gate 1 item 4).
C_BYTES = 43_486_543_872              # 40 GiB + 512 MiB
ADDITIONAL_DISK_UPPER_BYTES = 134_217_728
RETAINED_UPPER_BYTES = 67_108_864     # owner quote 61,079,552
METADATA_UPPER_BYTES = 262_144
PROJECT_BYTES = 1_073_741_824         # virtual ext4 statvfs; documented non-binding
ADMISSION_LIFETIME_NS = 55_000_000_000  # owner requires expiry within 60 s

# One pure authority is importable by both Windows operators and Linux helpers.
TOTAL_F2_LIMIT_V1 = 8_388_608
OLD_F2_PROOF_UPPER_V1 = 393_216
ACTIVE_F2_LIMIT_V1 = TOTAL_F2_LIMIT_V1 - OLD_F2_PROOF_UPPER_V1
F2_FOOTER_LIMIT_V1 = 16_384
F2_CONTROL_CAPS_V1 = MappingProxyType({
    "f2.originals.v1.json": 262_144, "f2.supplement.v1.json": 262_144,
    "f2.failure.v1.json": 262_144, "f2.final-accounting.v1.json": F2_FOOTER_LIMIT_V1})
PRIOR_CARRY_BYTES_V1 = 6_291_456
CURRENT_CODE_FORMS_V1 = 524_288
RESUME_CODE_FORMS_V1 = 1_032_192
RESUME_INDEX_REL_V1 = ("openspec/changes/fix-accepted-policy-preprocessing/evidence/"
                       "compiler-component-01/gate2-p0-465-retention.v1.json")
PRIOR_OWNED_CAP_V1 = 2_162_688
RETENTION_INDEX_REL_V1 = ("openspec/changes/fix-accepted-policy-preprocessing/evidence/"
                          "compiler-component-01/gate2-f2-c75a-retention.v1.json")
RETENTION_INDEX_SHA256_V1 = "8925428192e339d52d2bcc7a2f99587303765796dc0769f47dcf192ce40ce006"
RETENTION_INDEX_SIZE_V1 = 9637
OLD_CODE_COMMIT_V1 = "c75ad950ee542621a365725db627fdd03d2363e8"
_FIXTURE_PREFIX_V1 = "tests/fixtures/accepted_policy_fixture_compiler"
_OLD_SOURCE_NAMES_V1 = ("_gate2_c_v1.py", "_component_v1.py", "_v1.py", "_publisher_v1.py",
    "_seccomp_v1.json", "@script", "_recovery_v1.py", "_gate2_p0_v1.py", "_gate2_d_v1.py",
    "_gate2_d_child_v1.py", "@v8", "_gate2_setup_v1.py", "_gate2_capture_v1.py")
REVIEW_REPO_ROOT_LINUX_V1 = Path("/mnt/c/Users/s-a-balashov/.codex/worktrees/fix-accepted-policy-preprocessing/VAST")
_OLD_ROOT_V1 = Path("/home/s-a-balashov/work/vast-fixture-compiler-gate2-" + OLD_CODE_COMMIT_V1 + "-01")
_F2_OLD_FILES_V1 = ("RPC01.reply.original", "RPC01.request.original", "RPC02.reply.original",
    "RPC02.request.original", "RPC03.reply.original", "RPC03.request.original", "f2.failure.v1.json")
_AUX_OLD_FILES_V1 = ("export.stderr.original", "export.stdout.original", "operator.authority.original.json",
                     "operator.command.original.json")


def _retention_read_v1(path, cap, *, _allocation=False):
    path = Path(path)
    if not path.is_absolute() or path.resolve(strict=True) != path:
        raise ComponentRecipeError("retention physical path")
    expected = path.lstat()
    if not stat.S_ISREG(expected.st_mode) or expected.st_nlink != 1 or not 0 <= expected.st_size <= cap:
        raise ComponentRecipeError("retention preopen kind/link/bound")
    epoch = lambda s, crossing=False: (s.st_dev, s.st_ino, s.st_mode, s.st_nlink, s.st_size, s.st_mtime_ns,
        getattr(s, "st_birthtime_ns", None), None if crossing and os.name == "nt" else s.st_ctime_ns,
        getattr(s, "st_blocks", None))
    flags = (os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0) |
             getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_BINARY", 0))
    fd = os.open(path, flags)
    stream, failure, secondary, closed, raw, phase = None, None, [], False, b"", "fdopen"
    try:
        stream = os.fdopen(fd, "rb", buffering=0)
        phase = "read"
        before = os.fstat(stream.fileno())
        if epoch(before, True) != epoch(expected, True):
            raise ComponentRecipeError("retention open identity")
        allocated = _resume_fd_allocation_v1(stream.fileno(), before) if _allocation else None
        if _allocation and (type(allocated) is not int or not 0 <= allocated < 2 ** 63):
            raise ComponentRecipeError("resume unknown allocation")
        raw = stream.read(cap + 1)
        while 0 < len(raw) < before.st_size:
            part = stream.read(before.st_size - len(raw))
            if not part:
                break
            raw += part
        after = os.fstat(stream.fileno())
        if _allocation:
            actual_allocation = _resume_fd_allocation_v1(stream.fileno(), after)
            if type(actual_allocation) is not int or actual_allocation != allocated:
                raise ComponentRecipeError("resume allocation drift")
        if len(raw) != before.st_size or epoch(before) != epoch(after) or epoch(path.lstat()) != epoch(expected):
            raise ComponentRecipeError("retention file drift")
    except BaseException as error:
        failure = error
    finally:
        try:
            os.close(fd) if stream is None else stream.close()
            closed = True
        except BaseException as error:
            if failure is None:
                failure, phase = error, "close"
            else:
                secondary.append("retention_close_" + type(error).__name__)
    if failure is not None:
        error = ComponentRecipeError(str(failure) if isinstance(failure, ComponentRecipeError) else
            "retention_" + phase + "_" + type(failure).__name__)
        error.cause, error.causes = str(error), [str(error)] + secondary
        error.facts = {"path": str(path), "cause": error.cause, "causes": error.causes, "close_completed": closed,
            "unknown_closure": not closed, "read_bytes": len(raw), "read_sha256": hashlib.sha256(raw).hexdigest(),
            "omitted_or_unknown": True}
        raise error from failure
    return (raw, before, allocated) if _allocation else (raw, before)


def _resume_fd_allocation_v1(fd, observed):
    if os.name != "nt":
        blocks = _retention_blocks_v1(observed)
        return blocks * 512 if type(blocks) is int and 0 <= blocks < 2 ** 54 else None
    import ctypes
    import msvcrt
    from ctypes import wintypes
    class Standard(ctypes.Structure):
        _fields_ = [("allocation", ctypes.c_longlong), ("size", ctypes.c_longlong),
                    ("links", wintypes.DWORD), ("pending", ctypes.c_ubyte), ("directory", ctypes.c_ubyte)]
    call = ctypes.WinDLL("kernel32", use_last_error=True).GetFileInformationByHandleEx
    call.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    call.restype = wintypes.BOOL
    value = Standard()
    if (not call(msvcrt.get_osfhandle(fd), 1, ctypes.byref(value), ctypes.sizeof(value)) or
            value.size != observed.st_size or value.links != 1 or value.pending or value.directory):
        raise ComponentRecipeError("resume FileStandardInfo")
    return value.allocation


def _resume_read_v1(path, cap):
    return _retention_read_v1(path, cap, _allocation=True)


def _resume_descriptor_v1(raw, descriptor):
    actual = {"size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
              "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}
    if (type(descriptor) is not dict or set(descriptor) != set(actual) or
            type(descriptor["size_bytes"]) is not int or not raw or descriptor != actual):
        raise ComponentRecipeError("resume descriptor identity")


def _resume_index_v1(repo_root, descriptor):
    raw, _, allocation = _resume_read_v1(Path(repo_root) / RESUME_INDEX_REL_V1, 12288)
    _resume_descriptor_v1(raw, descriptor)
    if max(allocation, (len(raw) + 4095) // 4096 * 4096) + (len(raw) + 4095) // 4096 * 4096 + 8192 > 32768:
        raise ComponentRecipeError("resume index forms bound")
    try:
        value = json.loads(raw.decode("ascii"))
        if canonical_json_v1(value) + b"\n" != raw:
            raise ValueError("canonical")
    except (ValueError, UnicodeError, TypeError, RecursionError) as error:
        raise ComponentRecipeError("resume index encoding") from error
    from tests.fixtures import accepted_policy_fixture_compiler_gate2_resume_v1 as resume
    from tests.fixtures import accepted_policy_fixture_compiler_gate2_c_v1 as stage
    try:
        stage.validate_resume_retention_index_v1(value, retained_source_bindings_v1(repo_root)["sources"])
    except (resume.ResumeRefusal, ValueError, TypeError, KeyError, IndexError) as error:
        raise ComponentRecipeError("resume index schema") from error
    return value


def resume_code_forms_quote_v1(repo_root, *, code, plan, operator, index_descriptor):
    index = _resume_index_v1(repo_root, index_descriptor)
    slots, rows = index["source_slots"], index["source_versions"]
    if type(code) is not dict or set(code) != set(slots[:10]):
        raise ComponentRecipeError("resume code paths")
    baseline = {rows[n][0]: rows[n][1:] for n in index["historical_bindings"][0][1]}
    source_slots, git, working, helpers = set(index["source_form_slots"]), {}, 0, 0
    for slot, blob, size, digest in rows:
        if slot in source_slots and [blob, size, digest] != baseline.get(slot):
            git[(blob, size, digest)] = size
    for slot, relative in enumerate(slots):
        cap = {0: 131072, 1: 32768, 10: 40960, 13: 32768}.get(slot, 262144)
        raw, _, allocation = _resume_read_v1(Path(repo_root) / relative, cap)
        binding = index["current_bindings"][slot]
        desc = (code[relative] if slot < 10 else plan if slot == 10 else operator if slot == 13 else
                dict(zip(("git_blob", "size_bytes", "sha256"), rows[binding][1:])))
        _resume_descriptor_v1(raw, desc)
        identity = [desc["git_blob"], len(raw), desc["sha256"]]
        if binding is not None and identity != rows[binding][1:]:
            raise ComponentRecipeError("resume fixed source drift")
        rounded = (len(raw) + 4095) // 4096 * 4096
        quote = max(allocation, rounded) + 4096
        if slot in source_slots and identity != baseline.get(slot):
            working += quote
            git[tuple(identity)] = len(raw)
        elif slot in index["outside_helper_slots"]:
            helpers += quote + rounded + 4096
        elif quote > rounded + 4096:
            raise ComponentRecipeError("resume unchanged source allocation")
    total = working + sum((size + 4095) // 4096 * 4096 + 4096 for size in git.values())
    if total > RESUME_CODE_FORMS_V1 or helpers > 204800:
        raise ComponentRecipeError("resume forms bound")
    return total


def verify_resume_retention_v1(repo_root, *, git_observation, index_descriptor):
    index = _resume_index_v1(repo_root, index_descriptor)
    prior = verify_prior_retention_v1(repo_root, git_observation=git_observation)
    from tests.fixtures import accepted_policy_fixture_compiler_gate2_resume_v1 as resume
    try:
        native = resume.verify_retained_v1(repo_root, index=index)
    except resume.ResumeRefusal as error:
        raise ComponentRecipeError("resume retained forms") from error
    caps = {"node_count": 70, "native_code_quote_bytes": 586240, "parent_growth_bytes": 8192,
            "f2_quote_bytes": 4372992, "aux_quote_bytes": 39424,
            "windows_capture_quote_bytes": 32768, "diagnostic_quote_bytes": 16384}
    hashes = {"diagnostic_sha256": index["refs"][3][3], "manifest_sha256": index["refs"][4][3]}
    if (type(native) is not dict or set(native) != set(caps) | set(hashes) | {"physical_acceptance"} or
            native["physical_acceptance"] is not False or any(native[k] != v for k, v in hashes.items()) or
            any(type(native[k]) is not int or not 0 <= native[k] <= v for k, v in caps.items()) or
            native["node_count"] != 70):
        raise ComponentRecipeError("resume native receipt")
    return {"schema": "vast_gate2_resume_retention_receipt_v1", "index_sha256": index_descriptor["sha256"],
            "source_versions_sha256": hashlib.sha256(canonical_json_v1(index["source_versions"])).hexdigest(),
            "prior": prior, "native": native, "physical_acceptance": False}


def _retention_index_v1(repo_root):
    raw, _ = _retention_read_v1(Path(repo_root) / RETENTION_INDEX_REL_V1, 12288)
    if len(raw) != RETENTION_INDEX_SIZE_V1 or hashlib.sha256(raw).hexdigest() != RETENTION_INDEX_SHA256_V1:
        raise ComponentRecipeError("retention index identity")
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ComponentRecipeError("retention duplicate key")
            value[key] = item
        return value
    value = json.loads(raw.decode("ascii"), object_pairs_hook=unique,
        parse_constant=lambda _: (_ for _ in ()).throw(ComponentRecipeError("retention nonfinite")))
    if (type(value) is not dict or canonical_json_v1(value) + b"\n" != raw or
            value.get("schema") != "vast_gate2_f2_c75_retention_v1" or value.get("commit") != OLD_CODE_COMMIT_V1 or
            value.get("physical_acceptance") is not False or
            [row[0] for row in value.get("src", [])] != list(_OLD_SOURCE_NAMES_V1)):
        raise ComponentRecipeError("retention index schema")
    return value


def retained_source_bindings_v1(repo_root):
    value = _retention_index_v1(repo_root)
    sources = []
    for name, blob, size, digest in value["src"]:
        path = ("scripts/publication_operational_request_domain_v1.py" if name == "@script" else
                RETENTION_INDEX_REL_V1.rsplit("/", 1)[0] + "/component-admission-plan.v8.md" if name == "@v8" else
                _FIXTURE_PREFIX_V1 + name)
        if (type(size) is not int or not 0 < size <= 262144 or not _sha(digest) or
                type(blob) is not str or re.fullmatch("[0-9a-f]{40}", blob) is None):
            raise ComponentRecipeError("retention source binding")
        sources.append({"path": path, "size_bytes": size, "sha256": digest, "git_blob": blob})
    return {"index": {"size_bytes": RETENTION_INDEX_SIZE_V1, "sha256": RETENTION_INDEX_SHA256_V1},
            "sources": sources, "source_rows_sha256": hashlib.sha256(canonical_json_v1(sources)).hexdigest()}


def current_code_forms_quote_v1(repo_root, *, code, plan):
    old = retained_source_bindings_v1(repo_root)["sources"][:11]
    if type(code) is not dict or set(code) != {row["path"] for row in old[:10]}:
        raise ComponentRecipeError("current code paths")
    total = 0
    for number, row in enumerate(old):
        descriptor = code[row["path"]] if number < 10 else plan
        if (type(descriptor) is not dict or set(descriptor) != {"size_bytes", "sha256", "git_blob"} or
                type(descriptor["size_bytes"]) is not int or not 0 < descriptor["size_bytes"] <= 262144 or
                not _sha(descriptor["sha256"]) or type(descriptor["git_blob"]) is not str or
                re.fullmatch("[0-9a-f]{40}", descriptor["git_blob"]) is None):
            raise ComponentRecipeError("current code descriptor")
        raw, observed = _retention_read_v1(Path(repo_root) / row["path"], 262144)
        actual = {"size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw).hexdigest()}
        if actual != descriptor:
            raise ComponentRecipeError("current code working identity")
        rounded = ((len(raw) + 4095) // 4096) * 4096
        blocks = _retention_blocks_v1(observed)
        if blocks is None and os.name == "nt":
            working = rounded + 4096
        elif type(blocks) is int and 0 <= blocks < 2 ** 63:
            working = max(blocks * 512, rounded) + 4096
        else:
            raise ComponentRecipeError("current code unknown allocation")
        if actual != {key: row[key] for key in actual}:
            total += working + rounded + 4096
        elif working > ((row["size_bytes"] + 4095) // 4096) * 4096 + 4096:
            raise ComponentRecipeError("current unchanged working allocation")
        if total > CURRENT_CODE_FORMS_V1:
            raise ComponentRecipeError("current code forms bound")
    return total


def _old_windows_paths_v1(repo_root):
    temp = Path("/mnt/c/Users/s-a-balashov/AppData/Local/Temp")
    prefix = "vast-gate2-setup-" + OLD_CODE_COMMIT_V1
    return (temp / (prefix + ".driver.stdout.original"), temp / (prefix + ".driver.stderr.original"),
            Path(repo_root) / RETENTION_INDEX_REL_V1.rsplit("/", 1)[0] / "gate2-setup-c75a.outer-tool.original.json")


def _old_transcript_path_v1():
    return Path("/mnt/c/Users/s-a-balashov/AppData/Local/Temp/"
                "vast-gate2-c75a-postfailure-cb39fb.held-tool-return.transcript.json")


def _retention_blocks_v1(observation):
    return getattr(observation, "st_blocks", None)


def _retention_allocation_v1(observation, metadata=256):
    blocks = _retention_blocks_v1(observation)
    if type(blocks) is not int or not 0 <= blocks < 2 ** 63:
        raise ComponentRecipeError("retention unknown allocation")
    rounded = ((observation.st_size + 4095) // 4096) * 4096
    return max(blocks * 512, 4096 if stat.S_ISDIR(observation.st_mode) else rounded) + metadata


def validate_prior_retention_receipt_v1(receipt, *, source_rows_sha256):
    bounds = {"node_count": 28, "native_quote_bytes": 633856, "windows_quote_bytes": 32768,
              "transcript_quote_bytes": 12288, "owned_upper_bytes": 2102272, "old_f2_upper_bytes": 333056}
    if (type(receipt) is not dict or set(receipt) != set(bounds) | {
            "index_sha256", "source_rows_sha256", "physical_acceptance"} or
            receipt["index_sha256"] != RETENTION_INDEX_SHA256_V1 or
            not _sha(source_rows_sha256) or receipt["source_rows_sha256"] != source_rows_sha256 or
            receipt["physical_acceptance"] is not False):
        raise ComponentRecipeError("retention native receipt")
    for name, limit in bounds.items():
        value = receipt[name]
        if type(value) is not int or not 0 <= value <= limit:
            raise ComponentRecipeError("retention native receipt bound")
    if (receipt["node_count"] != 28 or receipt["owned_upper_bytes"] != 2102272 or
            receipt["old_f2_upper_bytes"] != 333056 or receipt["owned_upper_bytes"] > PRIOR_OWNED_CAP_V1 or
            receipt["old_f2_upper_bytes"] > OLD_F2_PROOF_UPPER_V1):
        raise ComponentRecipeError("retention carried bounds")
    return dict(receipt)


def verify_prior_retention_v1(repo_root, *, git_observation):
    """Fresh fixed-file/native-block check; Git provenance comes from external review.

    The Windows caller must actually read all 13 old Git blobs before allocation.
    Later C authenticates that observation through the externally reviewed packet
    and enclosing operator authority. No Linux Git/interop fallback is exposed.
    Caller checks the original deadline before and after these trusted reads.
    """
    bindings = retained_source_bindings_v1(repo_root)
    index = _retention_index_v1(repo_root)
    if (type(git_observation) is not dict or set(git_observation) != {"component", "index", "old_git_sha256"} or
            git_observation["old_git_sha256"] != bindings["source_rows_sha256"]):
        raise ComponentRecipeError("retention Git observation")
    for name, relative, cap in (("component", _FIXTURE_PREFIX_V1 + "_component_v1.py", 262144),
                                ("index", RETENTION_INDEX_REL_V1, 12288)):
        descriptor = git_observation[name]
        if type(descriptor) is not dict or set(descriptor) != {"size_bytes", "sha256", "git_blob"}:
            raise ComponentRecipeError("retention bootstrap descriptor")
        raw, observed = _retention_read_v1(Path(repo_root) / relative, cap)
        if (type(descriptor["size_bytes"]) is not int or len(raw) != descriptor["size_bytes"] or
                hashlib.sha256(raw).hexdigest() != descriptor["sha256"] or
                hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw).hexdigest() != descriptor["git_blob"]):
            raise ComponentRecipeError("retention bootstrap identity")
        if name == "index" and 2 * _retention_allocation_v1(observed, 4096) > 32768:
            raise ComponentRecipeError("retention index forms")
    expected = {}
    categories = {}
    for relative in ("", "scripts", "tests", "tests/fixtures"):
        expected[_OLD_ROOT_V1 / relative] = None
    for number, source in enumerate(bindings["sources"][:11]):
        relative = "physical-plan.v8.md" if number == 10 else source["path"]
        expected[_OLD_ROOT_V1 / relative] = (source["size_bytes"], source["sha256"])
    roots = [_OLD_ROOT_V1]
    for category, suffix, names in (("F2", ".f2", _F2_OLD_FILES_V1), ("AUX", ".operator-originals", _AUX_OLD_FILES_V1)):
        folder = Path(str(_OLD_ROOT_V1) + suffix)
        roots.append(folder)
        expected[folder] = None
        categories[folder] = category
        rows = index["retained"][category]["files"]
        if [row[0] for row in rows] != list(names):
            raise ComponentRecipeError("retention fixed inventory")
        for name, row in zip(names, rows):
            expected[folder / name] = (row[1], row[3])
            categories[folder / name] = category
    observed_paths = set()
    for root in roots:
        if root.resolve(strict=True) != root:
            raise ComponentRecipeError("retention root alias")
        observed_paths.add(root)
    # Scan only the six fixed directories. Reject the first unknown entry;
    # os.walk would allocate an unbounded per-directory list before our check.
    for directory, binding in expected.items():
        if binding is not None:
            continue
        if directory.resolve(strict=True) != directory or not stat.S_ISDIR(directory.lstat().st_mode):
            raise ComponentRecipeError("retention scan directory kind/alias")
        children = {path for path in expected if path.parent == directory}
        seen = set()
        with os.scandir(directory) as entries:
            for entry in entries:
                path = directory / entry.name
                if path not in children or path in seen:
                    raise ComponentRecipeError("retention extra inventory")
                seen.add(path)
                observed_paths.add(path)
        if seen != children:
            raise ComponentRecipeError("retention missing inventory")
    if observed_paths != set(expected) or len(expected) != 28:
        raise ComponentRecipeError("retention missing/extra inventory")
    native_quote = 0
    category_quote = {"code": 0, "F2": 0, "AUX": 0}
    for path, binding in expected.items():
        if path.resolve(strict=True) != path:
            raise ComponentRecipeError("retention native alias")
        observed = path.lstat()
        if binding is None:
            if not stat.S_ISDIR(observed.st_mode):
                raise ComponentRecipeError("retention directory kind")
        else:
            raw, observed = _retention_read_v1(path, binding[0])
            if len(raw) != binding[0] or hashlib.sha256(raw).hexdigest() != binding[1]:
                raise ComponentRecipeError("retention original identity")
        quote = _retention_allocation_v1(observed)
        native_quote += quote
        category_quote[categories.get(path, "code")] += quote
    for name, cap in (("code", 540416), ("F2", 75776), ("AUX", 17664)):
        if category_quote[name] > cap:
            raise ComponentRecipeError("retention category allocation")
    windows_quote = 0
    for path, row in zip(_old_windows_paths_v1(repo_root), index["retained"]["win"]):
        raw, observed = _retention_read_v1(path, row[1])
        if len(raw) != row[1] or hashlib.sha256(raw).hexdigest() != row[3]:
            raise ComponentRecipeError("retention Windows original identity")
        windows_quote += _retention_allocation_v1(observed, 4096)
    row = index["retained"]["transcript"]
    raw, observed = _retention_read_v1(_old_transcript_path_v1(), row[1])
    if len(raw) != row[1] or hashlib.sha256(raw).hexdigest() != row[2]:
        raise ComponentRecipeError("retention held transcript identity")
    receipt = {"index_sha256": RETENTION_INDEX_SHA256_V1, "source_rows_sha256": bindings["source_rows_sha256"],
        "node_count": len(expected), "native_quote_bytes": native_quote, "windows_quote_bytes": windows_quote,
        "transcript_quote_bytes": _retention_allocation_v1(observed, 4096), "owned_upper_bytes": 2102272,
        "old_f2_upper_bytes": 333056, "physical_acceptance": False}
    return validate_prior_retention_receipt_v1(receipt, source_rows_sha256=bindings["source_rows_sha256"])


def _header(name: str) -> str:
    return '#define STATE_FILE "%s"\n#define DAEMON_ID "vast-component-%s"\n' % (D_STATE_FILE, name)


def _c1() -> str:
    return _header("c1") + r'''#include <stdio.h>
#include <string.h>

int main(void) {
    static const char command[] = "VAST-C1-COMMAND-V1\n";
    char buffer[64];
    size_t size = fread(buffer, 1, sizeof buffer, stdin);
    if (size != sizeof command - 1 || memcmp(buffer, command, size) != 0) {
        return 2;
    }
    FILE *state = fopen(STATE_FILE, "wx");
    if (state == NULL || fputs("ok\n", state) == EOF || fclose(state) != 0) {
        return 3;
    }
    if (fputs("VAST-C1-REPLY-V1 " DAEMON_ID "\n", stdout) == EOF || fflush(stdout) != 0) {
        return 4;
    }
    return 0;
}
'''


def _c2() -> str:
    # Missing semicolon: a deterministic syntax error.
    return _header("c2") + "int main(void) { return 0 }\n"


def _c3() -> str:
    # A non-zero initializer keeps 20 MiB in .rodata, so `as` crosses FSIZE.
    return _header("c3") + ("static const char vast_c3_payload[20 << 20] = {1};\n"
                            "int main(void) { return vast_c3_payload[0]; }\n")


def _c4() -> str:
    # About 1.4 MiB of source and several MiB of diagnostics; no main.
    return _header("c4") + "".join("#warning vast-c4-diagnostic-%05d\n" % index for index in range(40000))


def _c5() -> str:
    # cc's stdout is the publisher's capture pipe, which no process writes, so
    # reading it as an include blocks memory-flat until the publisher deadline.
    return _header("c5") + '#include "/proc/self/fd/1"\nint main(void) { return 0; }\n'


_BUILDERS = {"c1": _c1, "c2": _c2, "c3": _c3, "c4": _c4, "c5": _c5}
SOURCE_SHA256 = {
    "c1": "482f7cd36b3be914a9655ef772e73f0b988e2b3aea843ac121a941ce09cd2e4b",
    "c2": "8431b4390a1420cf85d59df5d529a140b9049bc4dd7c9c289ed59f647659db92",
    "c3": "081630318481dfc432b0ba08c0e065a47eda9edd55b698eca7d0905dd86a140c",
    "c4": "721ec53dc37ad7d02c9e3409512f6e864c49b3518aa6906a5693ac1d062b5928",
    "c5": "e1393ff2e793adee3ace004442d2010cb40abd8d57840edd7580bf37450d6ac0",
}
D_COMMAND_SHA256 = hashlib.sha256(D_COMMAND).hexdigest()
D_REPLY_SHA256 = hashlib.sha256(D_REPLY).hexdigest()


class ComponentRecipeError(ValueError):
    pass


def component_source_v1(name: str) -> bytes:
    if name not in _BUILDERS:
        raise ComponentRecipeError("unknown component source")
    raw = _BUILDERS[name]().encode("ascii")
    if (not 0 < len(raw) <= SOURCE_LIMIT or b"\0" in raw or not raw.startswith(b"#define STATE_FILE ")
            or b"\n#define DAEMON_ID " not in raw[:8192]):
        raise ComponentRecipeError("component source shape")
    if hashlib.sha256(raw).hexdigest() != SOURCE_SHA256[name]:
        raise ComponentRecipeError("component source drift")
    return raw


def canonical_json_v1(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("ascii")


def _sha(value: Any) -> bool:
    return type(value) is str and re.fullmatch("[0-9a-f]{64}", value) is not None


def seal_json_v1(path: Path, value: Mapping[str, Any]) -> dict[str, Any]:
    raw = canonical_json_v1(dict(value))
    if not 1 <= len(raw) <= SEALED_LIMIT:
        raise ComponentRecipeError("sealed descriptor bound")
    path = Path(path)
    if not path.is_absolute() or path.parent.resolve(strict=True) != path.parent:
        raise ComponentRecipeError("sealed descriptor path")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
                 | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_BINARY", 0), 0o600)
    try:
        if os.write(fd, raw) != len(raw):
            raise ComponentRecipeError("sealed descriptor short write")
        os.fsync(fd)
    finally:
        os.close(fd)
    return {"path": str(path), "size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def _review(review: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(review, Mapping) or set(review) != {"commit", "approval_reference", "evidence_sha256"}:
        raise ComponentRecipeError("review binding")
    if (type(review["commit"]) is not str or re.fullmatch("[0-9a-f]{40}", review["commit"]) is None
            or not _sha(review["evidence_sha256"]) or type(review["approval_reference"]) is not str
            or not 1 <= len(review["approval_reference"]) <= 512):
        raise ComponentRecipeError("review binding")
    return dict(review)


def component_seed_v1(*, review: Mapping[str, Any], bindings: Mapping[str, str], engine: Mapping[str, Any],
                      provider: Mapping[str, Any], environment_keys: list[str], mounts_sha256: str,
                      proofs: Mapping[str, str | None]) -> dict[str, Any]:
    if set(bindings) != {"host_sha256", "publisher_sha256", "profile_sha256"} or not all(map(_sha, bindings.values())):
        raise ComponentRecipeError("seed bindings")
    if set(engine) != {"driver", "cgroup_driver", "security_options", "runtimes_sha256"} or not _sha(engine["runtimes_sha256"]):
        raise ComponentRecipeError("seed engine")
    if (set(provider) != {"rootfs_sha256", "size_bytes"} or not _sha(provider["rootfs_sha256"])
            or type(provider["size_bytes"]) is not int or provider["size_bytes"] < 0):
        raise ComponentRecipeError("seed provider")
    if (type(environment_keys) is not list or environment_keys != sorted(set(environment_keys))
            or not all(type(key) is str for key in environment_keys)):
        raise ComponentRecipeError("seed environment keys")
    if not _sha(mounts_sha256):
        raise ComponentRecipeError("seed mounts")
    if set(proofs) != {"baseline", "toolchain", "abi", "limits", "closure"} or not all(
            value is None or _sha(value) for value in proofs.values()):
        raise ComponentRecipeError("seed proofs")
    return {"schema_version": 1, "artifact_kind": "vast_fixture_compiler_component_seed_v1",
            "review": _review(review), "bindings": dict(bindings), "engine": dict(engine),
            "provider": dict(provider), "environment_keys": list(environment_keys),
            "mounts_sha256": mounts_sha256, "proofs": dict(proofs)}


def component_admission_v1(*, project_root: Path, review: Mapping[str, Any], seed_sha256: str,
                           bindings: Mapping[str, str], source_relative: str, source: bytes,
                           executable_relative: str, physical_plan_sha256: str, boot_id: str,
                           now_unix_ns: int | None = None) -> dict[str, Any]:
    if not _sha(seed_sha256) or not _sha(physical_plan_sha256):
        raise ComponentRecipeError("admission bindings")
    if type(source) is not bytes or not 0 < len(source) <= SOURCE_LIMIT:
        raise ComponentRecipeError("admission source")
    now = time.time_ns() if now_unix_ns is None else now_unix_ns
    return {"schema_version": 1, "artifact_kind": "vast_fixture_compiler_admission_v1",
            "scope": "component_only", "review": _review(review), "recipe_sha256": seed_sha256,
            "component_seed": None, "bindings": dict(bindings), "project_root": str(project_root),
            "source": {"relative_path": source_relative, "size_bytes": len(source),
                       "sha256": hashlib.sha256(source).hexdigest()},
            "executable_relative": executable_relative, "physical_plan_sha256": physical_plan_sha256,
            "whole_chain_admission_sha256": None, "expires_unix_ns": now + ADMISSION_LIFETIME_NS,
            "boot_id": boot_id, "metadata_upper_bytes": METADATA_UPPER_BYTES,
            "retained_upper_bytes": RETAINED_UPPER_BYTES,
            "additional_disk_upper_bytes": ADDITIONAL_DISK_UPPER_BYTES,
            "filesystem_floors": {"c_bytes": C_BYTES, "project_bytes": PROJECT_BYTES}}
