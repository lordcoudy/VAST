"""Preparation admission around the frozen V1 executor; no execution owner.

The reviewed outer recipe authenticates this gate and its callers before parse.
Its narrow repeated checks preserve V1's historical full-source identity. Only
the unchanged public V1 entry can execute, publish, clean up or accept a compile.
"""
import hashlib
import os
from pathlib import Path
import re
import time

from tests.fixtures import accepted_policy_fixture_compiler_v1 as executor


FROZEN_EXECUTOR_SIZE = 103925
FROZEN_EXECUTOR_SHA256 = "1e40d4786fd03543ac43df7fe0e42a4349d55bad9288ead28f5d2a6ad87bcb03"


def _compiler_preparation_clock_v1(absolute_deadline_ns):
    """Check the caller's original window; never supply or renew a deadline."""
    now = time.monotonic_ns()
    if (type(absolute_deadline_ns) is not int or type(now) is not int or now < 0
            or not 0 < absolute_deadline_ns - now <= 150_000_000_000):
        raise executor.FixtureCompilerError("owner_preparation_deadline")
    return now


def _check_fixture_preparation_v1(*, project_root, source_path, source_bytes,
        executable_path, qualification, admission, absolute_deadline_ns, prospective):
    """The one current policy for RAM preflight and written-source handoff.

    These are deliberately repeated, not extracted from or substituted for the
    frozen owner's checks. There is no component-only or cached-success path.
    """
    def require(condition, code):
        if not condition:
            raise executor.FixtureCompilerError(code)

    def keys(value, names, code):
        require(type(value) is dict and set(value) == set(names.split()), code)

    def sha(value):
        return type(value) is str and re.fullmatch("[0-9a-f]{64}", value) is not None

    start = _compiler_preparation_clock_v1(absolute_deadline_ns)
    require(absolute_deadline_ns - start > 80_000_000_000, "owner_containment_room")
    root = Path(project_root)
    require(root.is_absolute() and root.resolve(strict=True) == root and root.is_dir(), "owner_project")
    admitted, _ = executor._compiler_sealed_v1(admission, root)
    keys(admitted, "schema_version artifact_kind scope review recipe_sha256 component_seed bindings project_root source executable_relative physical_plan_sha256 whole_chain_admission_sha256 expires_unix_ns boot_id metadata_upper_bytes retained_upper_bytes additional_disk_upper_bytes filesystem_floors", "owner_admission_schema")
    require(type(admitted["schema_version"]) is int and admitted["schema_version"] == 1
            and admitted["artifact_kind"] == "vast_fixture_compiler_admission_v1"
            and admitted["project_root"] == str(root), "owner_admission_schema")
    require(admitted["scope"] == "whole_chain_task1_5" and sha(admitted["whole_chain_admission_sha256"])
            and admitted["component_seed"] is None, "owner_whole_admission")
    recipe, _ = executor._compiler_sealed_v1(qualification, root)
    require(admitted["recipe_sha256"] == qualification["sha256"], "owner_qualification_binding")
    keys(recipe, "schema_version artifact_kind review bindings engine provider environment_keys mounts_sha256 proofs", "owner_recipe_schema")
    require(type(recipe["schema_version"]) is int and recipe["schema_version"] == 1
            and recipe["artifact_kind"] == "vast_fixture_compiler_qualification_v1", "owner_recipe_schema")
    for review in (admitted["review"], recipe["review"]):
        keys(review, "commit approval_reference evidence_sha256", "owner_review_binding")
        require(type(review["commit"]) is str and re.fullmatch("[0-9a-f]{40}", review["commit"]) is not None
                and sha(review["evidence_sha256"]) and type(review["approval_reference"]) is str
                and 1 <= len(review["approval_reference"]) <= 512, "owner_review_binding")
    bindings = recipe["bindings"]
    keys(bindings, "host_sha256 publisher_sha256 profile_sha256", "owner_source_manifest")
    require(all(sha(value) for value in bindings.values()) and bindings == admitted["bindings"]
            and bindings["profile_sha256"] == executor.PROFILE_SHA256, "owner_source_manifest")
    keys(recipe["engine"], "driver cgroup_driver security_options runtimes_sha256", "owner_engine_manifest")
    keys(recipe["provider"], "rootfs_sha256 size_bytes", "owner_provider_manifest")
    keys(recipe["proofs"], "baseline toolchain abi limits closure", "owner_capability_manifest")
    require(sha(recipe["mounts_sha256"]) and sha(recipe["provider"]["rootfs_sha256"])
            and type(recipe["provider"]["size_bytes"]) is int and recipe["provider"]["size_bytes"] >= 0
            and sha(recipe["engine"]["runtimes_sha256"])
            and all(sha(value) for value in recipe["proofs"].values()), "owner_capability_manifest")
    require(type(admitted["expires_unix_ns"]) is int
            and time.time_ns() < admitted["expires_unix_ns"] <= time.time_ns() + 60_000_000_000
            and sha(admitted["physical_plan_sha256"]), "owner_physical_admission")
    for name in ("metadata_upper_bytes", "retained_upper_bytes", "additional_disk_upper_bytes"):
        require(type(admitted[name]) is int and 0 < admitted[name] <= 1 << 50, "owner_physical_admission")
    require(admitted["metadata_upper_bytes"] <= 262144
            and admitted["additional_disk_upper_bytes"] >= admitted["retained_upper_bytes"], "owner_physical_admission")
    floors = admitted["filesystem_floors"]
    keys(floors, "c_bytes project_bytes", "owner_floor_manifest")
    require(type(floors["c_bytes"]) is int and floors["c_bytes"] >= 42949672960
            and type(floors["project_bytes"]) is int and floors["project_bytes"] > 0, "owner_floor_manifest")

    if prospective:
        source, executable = Path(source_path), Path(executable_path)
        for path in (source, executable):
            require(path.is_absolute() and path.is_relative_to(root) and path != root
                    and path.resolve(strict=False) == path and not os.path.lexists(path), "owner_path")
    else:
        source = executor._compiler_physical_v1(source_path, root)
        executable = executor._compiler_physical_v1(executable_path, root, fresh=True)
    entry = admitted["source"]
    keys(entry, "relative_path size_bytes sha256", "owner_source_binding")
    require(type(entry["size_bytes"]) is int and 0 < entry["size_bytes"] <= executor.SOURCE_LIMIT
            and sha(entry["sha256"]) and str(source.relative_to(root)) == entry["relative_path"]
            and str(executable.relative_to(root)) == admitted["executable_relative"], "owner_source_binding")
    raw = source_bytes if prospective else executor._compiler_read_v1(source, executor.SOURCE_LIMIT)
    require(type(raw) is bytes and len(raw) == entry["size_bytes"] and raw.isascii() and b"\0" not in raw
            and hashlib.sha256(raw).hexdigest() == entry["sha256"]
            and raw.startswith(b"#define STATE_FILE ") and b"\n#define DAEMON_ID " in raw[:8192], "owner_source_binding")

    publisher = executor._compiler_physical_v1(root / "tests/fixtures/accepted_policy_fixture_compiler_publisher_v1.py", root)
    profile = executor._compiler_physical_v1(root / "tests/fixtures/accepted_policy_fixture_compiler_seccomp_v1.json", root)
    publisher_raw = executor._compiler_read_v1(publisher, 65536)
    profile_raw = executor._compiler_read_v1(profile, 65536)
    # host_sha256 has always named the actual executor, never this upstream gate.
    host_raw = executor._compiler_read_v1(Path(executor.__file__).resolve(strict=True), 262144)
    require(len(host_raw) == FROZEN_EXECUTOR_SIZE
            and hashlib.sha256(host_raw).hexdigest() == FROZEN_EXECUTOR_SHA256 == bindings["host_sha256"]
            and hashlib.sha256(publisher_raw).hexdigest() == bindings["publisher_sha256"]
            and hashlib.sha256(profile_raw).hexdigest() == executor.PROFILE_SHA256, "owner_helper_drift")
    require(admitted["retained_upper_bytes"] >= 3 * 16777216 + len(raw) + 2 * 1048576 + 262144,
            "owner_retention_quote")
    identity = executor._compiler_self_identity_v1()
    require(type(identity) is dict and identity.get("boot_id") == admitted["boot_id"]
            and identity.get("machine") == "x86_64"
            and identity.get("kernel") == "6.6.87.2-microsoft-standard-WSL2", "owner_runtime_binding")
    free = executor._compiler_floor_facts_v1(root)
    require(type(free) is dict and type(free.get("c_free")) is int and type(free.get("project_free")) is int
            and free["c_free"] >= floors["c_bytes"] + admitted["additional_disk_upper_bytes"]
            and free["project_free"] >= floors["project_bytes"] + admitted["additional_disk_upper_bytes"], "owner_fresh_floor")
    # Reads above may consume the remaining wall-clock admission interval even
    # while the original monotonic preparation window still has ample room.
    require(time.time_ns() < admitted["expires_unix_ns"] <= time.time_ns() + 60_000_000_000,
            "owner_physical_admission")
    now = time.monotonic_ns()
    require(type(now) is int and start <= now < absolute_deadline_ns
            and absolute_deadline_ns - now > 80_000_000_000, "owner_containment_room")


def preflight_fixture_engine_v1(*, project_root, source_path, source_bytes, executable_path,
        qualification=None, admission=None, absolute_deadline_ns=None):
    """Check prospective bytes without allocating anything or granting acceptance."""
    _check_fixture_preparation_v1(project_root=project_root, source_path=source_path,
        source_bytes=source_bytes, executable_path=executable_path, qualification=qualification,
        admission=admission, absolute_deadline_ns=absolute_deadline_ns, prospective=True)


def compile_admitted_fixture_engine_v1(*, project_root, source_path, executable_path,
        qualification=None, admission=None, absolute_deadline_ns=None):
    """Freshly check the written source, then return the public owner's outcome."""
    _check_fixture_preparation_v1(project_root=project_root, source_path=source_path,
        source_bytes=None, executable_path=executable_path, qualification=qualification,
        admission=admission, absolute_deadline_ns=absolute_deadline_ns, prospective=False)
    return executor.compile_fixture_engine_v1(project_root=project_root, source_path=source_path,
        executable_path=executable_path, qualification=qualification, admission=admission,
        absolute_deadline_ns=absolute_deadline_ns)
