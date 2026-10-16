"""Task 2.10 component recipe: fixed C sources, stage-D bytes, sealed descriptors.

Approved by the 2.10 component admission plan (V5, efa59e92; C5 per V6). This
module performs no Docker, compiler or process action. It only builds the fixed
inputs whose bytes are pinned here and the sealed JSON descriptors the 2.9
owner's component path validates. Component success never admits task 1.5.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import time
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
    """Return the pinned source bytes, refusing any drift from the reviewed recipe."""
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
    """Write one fresh canonical sealed descriptor no larger than the owner's 4 KiB cap."""
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
    """Gate-2 component seed with the owner's exact recipe schema (component kind)."""
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
    """Component-only admission with the plan's fixed values; sealed just before use."""
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
