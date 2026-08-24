from __future__ import annotations

import ast
import copy
import errno
import hashlib
import inspect
import json
import os
import re
import signal
import struct
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import checkpoint_source_runtime_closure_authority_v1 as source_authority  # noqa: E402
from checkpoint_source_runtime_closure_authority_v1 import (  # noqa: E402
    ASSESSMENT_KIND,
    AUTHORITY_KIND,
    BUILD_PROVENANCE_KIND,
    CLOSURE_SET_KIND,
    ENVIRONMENT_POLICY_KIND,
    GST_REGISTRY_CATALOG_KIND,
    INVOCATION_CONTRACT_KIND,
    MANIFEST_KIND,
    CheckpointSourceRuntimeClosureAuthorityV1Error,
    assess_checkpoint_source_runtime_closure_authority_v1,
    build_checkpoint_source_runtime_closure_authority_v1,
    validate_checkpoint_source_runtime_closure_authority_v1,
    validate_checkpoint_source_runtime_closure_manifest_v1,
)


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")


def canonical_sha(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def sha(label: str) -> str:
    return hashlib.sha256(label.encode("ascii")).hexdigest()


def forbidden_capabilities(source: str) -> list[str]:
    """Resolve import/call aliases and report process, discovery, or write APIs."""
    tree = ast.parse(source)
    aliases: dict[str, str] = {"open": "builtins.open"}
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name.split(".", 1)[0]
                aliases[local] = alias.name
                if alias.name == "subprocess":
                    violations.append("import subprocess")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                local = alias.asname or alias.name
                aliases[local] = f"{module}.{alias.name}".strip(".")
                if module == "subprocess":
                    violations.append(f"from subprocess import {alias.name}")

    def qualified(node: ast.AST) -> str | None:
        if isinstance(node, ast.Name):
            return aliases.get(node.id, node.id)
        if isinstance(node, ast.Attribute):
            base = qualified(node.value)
            return f"{base}.{node.attr}" if base else None
        return None

    pending: dict[str, ast.AST] = {}
    for node in ast.walk(tree):
        if (isinstance(node, (ast.Assign, ast.AnnAssign))
                and isinstance(node.value, (ast.Name, ast.Attribute))):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    pending[target.id] = node.value

    def root_name(node: ast.AST) -> str | None:
        while isinstance(node, ast.Attribute):
            node = node.value
        return node.id if isinstance(node, ast.Name) else None

    while pending:
        progress = False
        for target, value in tuple(pending.items()):
            root = root_name(value)
            if root in pending and root not in aliases:
                continue
            resolved = qualified(value)
            if resolved is not None and target not in resolved.split("."):
                aliases[target] = resolved
            pending.pop(target)
            progress = True
        if not progress:
            violations.append("assignment alias cycle")
            break

    process_exact = {
        "subprocess.run", "subprocess.Popen", "subprocess.call",
        "subprocess.check_call", "subprocess.check_output",
        "subprocess.getoutput", "subprocess.getstatusoutput",
        "os.system", "os.popen", "os.fork", "os.forkpty",
        "os.posix_spawn", "os.posix_spawnp",
    }
    write_exact = {
        "os.remove", "os.unlink", "os.rename", "os.replace", "os.mkdir",
        "os.makedirs", "os.rmdir", "os.removedirs", "os.link",
        "os.symlink", "os.truncate", "os.chmod", "os.chown",
        "os.write", "os.pwrite", "os.writev", "os.pwritev",
    }
    discovery_exact = {
        "glob.glob", "glob.iglob", "os.walk", "os.listdir", "os.scandir",
    }
    write_methods = {
        "write_text", "write_bytes", "mkdir", "unlink", "rename", "replace",
        "touch", "symlink_to", "hardlink_to", "rmdir",
    }
    discovery_methods = {"glob", "rglob", "iterdir", "walk"}
    write_flags = {"O_WRONLY", "O_RDWR", "O_CREAT", "O_TRUNC", "O_APPEND"}

    def referenced_write_flags(node: ast.AST) -> set[str]:
        result: set[str] = set()
        for candidate in ast.walk(node):
            if isinstance(candidate, (ast.Name, ast.Attribute)):
                name = qualified(candidate) or ""
                leaf = name.rsplit(".", 1)[-1]
                if leaf in write_flags:
                    result.add(name)
        return result

    for node in ast.walk(tree):
        if isinstance(node, (ast.Name, ast.Attribute)):
            name = qualified(node) or ""
            if name.rsplit(".", 1)[-1] in write_flags:
                violations.append(name)
        if not isinstance(node, ast.Call):
            continue
        name = qualified(node.func) or ""
        leaf = (node.func.attr if isinstance(node.func, ast.Attribute)
                else name.rsplit(".", 1)[-1])
        if (name in process_exact or name.startswith("os.exec")
                or name.startswith("os.spawn")):
            violations.append(name)
        if name in write_exact or leaf in write_methods:
            violations.append(name)
        if name == "os.open":
            flags_node = (node.args[1] if len(node.args) > 1 else next(
                (item.value for item in node.keywords if item.arg == "flags"), None
            ))
            if flags_node is not None and referenced_write_flags(flags_node):
                violations.append("os.open:write-flags")
        if name in discovery_exact or leaf in discovery_methods:
            violations.append(name)
        if name in {"builtins.open", "pathlib.Path.open"} or (
            leaf == "open" and name != "os.open"
        ):
            mode_node = (node.args[1] if len(node.args) > 1 else next(
                (item.value for item in node.keywords if item.arg == "mode"), None
            ))
            if mode_node is not None:
                if not isinstance(mode_node, ast.Constant) or not isinstance(
                    mode_node.value, str
                ) or any(marker in mode_node.value for marker in "wax+"):
                    violations.append(f"{name}:write-mode")
    return sorted(set(violations))


def align(value: int, boundary: int = 8) -> int:
    return (value + boundary - 1) & ~(boundary - 1)


def minimal_elf(
    *, build_id: str, soname: str | None, needed: tuple[str, ...] = (),
    interpreter: str | None = None, machine: int = 62,
    rpath: str | None = None, runpath: str | None = None,
    extra_dynamic_segment: bool = False,
    terminal_dynamic_tag: int = 0,
    extra_dynamic_null: bool = False,
) -> bytes:
    """Construct a dependency-free ELF64-LE fixture with dynamic metadata."""
    strings = bytearray(b"\0")
    offsets: dict[str, int] = {}
    for value in (*needed, *((soname,) if soname else ()),
                  *((rpath,) if rpath else ()), *((runpath,) if runpath else ())):
        if value not in offsets:
            offsets[value] = len(strings)
            strings.extend(value.encode("ascii") + b"\0")
    phnum = (4 if interpreter is not None else 3) + int(extra_dynamic_segment)
    cursor = align(64 + phnum * 56)
    interp_offset = cursor
    interp_bytes = (interpreter.encode("ascii") + b"\0") if interpreter else b""
    cursor = align(cursor + len(interp_bytes))
    dynamic_offset = cursor
    dynamic_count = (len(needed) + 3 + int(soname is not None)
                     + int(rpath is not None) + int(runpath is not None)
                     + int(extra_dynamic_null))
    dynamic_size = dynamic_count * 16
    cursor = align(cursor + dynamic_size)
    extra_dynamic_offset = cursor
    extra_dynamic = ((0x6FFFFFFF, 0), (0, 0)) if extra_dynamic_segment else ()
    extra_dynamic_size = len(extra_dynamic) * 16
    cursor = align(cursor + extra_dynamic_size)
    strings_offset = cursor
    cursor = align(cursor + len(strings))
    note_offset = cursor
    note = struct.pack("<III", 4, 20, 3) + b"GNU\0" + bytes.fromhex(build_id)
    cursor = align(cursor + len(note))
    size = cursor
    base = 0x400000
    dynamic: list[tuple[int, int]] = [(1, offsets[item]) for item in needed]
    dynamic.extend(((5, base + strings_offset), (10, len(strings))))
    if soname is not None:
        dynamic.append((14, offsets[soname]))
    if rpath is not None:
        dynamic.append((15, offsets[rpath]))
    if runpath is not None:
        dynamic.append((29, offsets[runpath]))
    dynamic.append((terminal_dynamic_tag, 0))
    if extra_dynamic_null:
        dynamic.append((0, 0))
    self_check = len(dynamic) * 16
    if self_check != dynamic_size:
        raise AssertionError((self_check, dynamic_size))
    data = bytearray(size)
    ident = b"\x7fELF" + bytes((2, 1, 1, 0, 0)) + b"\0" * 7
    struct.pack_into(
        "<16sHHIQQQIHHHHHH", data, 0, ident, 3, machine, 1, 0,
        64, 0, 0, 64, 56, phnum, 0, 0, 0,
    )
    phdrs = [(1, 5, 0, base, base, size, size, 0x1000)]
    if interpreter is not None:
        phdrs.append((3, 4, interp_offset, base + interp_offset,
                      base + interp_offset, len(interp_bytes), len(interp_bytes), 1))
    phdrs.extend((
        (2, 6, dynamic_offset, base + dynamic_offset, base + dynamic_offset,
         dynamic_size, dynamic_size, 8),
    ))
    if extra_dynamic_segment:
        phdrs.append((
            2, 6, extra_dynamic_offset, base + extra_dynamic_offset,
            base + extra_dynamic_offset, extra_dynamic_size,
            extra_dynamic_size, 8,
        ))
    phdrs.append((4, 4, note_offset, base + note_offset, base + note_offset,
                  len(note), len(note), 4))
    for index, record in enumerate(phdrs):
        struct.pack_into("<IIQQQQQQ", data, 64 + index * 56, *record)
    data[interp_offset:interp_offset + len(interp_bytes)] = interp_bytes
    for index, record in enumerate(dynamic):
        struct.pack_into("<QQ", data, dynamic_offset + index * 16, *record)
    for index, record in enumerate(extra_dynamic):
        struct.pack_into("<QQ", data, extra_dynamic_offset + index * 16, *record)
    data[strings_offset:strings_offset + len(strings)] = strings
    data[note_offset:note_offset + len(note)] = note
    return bytes(data)


def elf_metadata(
    *, build_id: str, soname: str | None, needed: tuple[str, ...] = (),
    interpreter: str | None = None,
) -> dict[str, object]:
    return {
        "elf_type": "ET_DYN", "machine": "x86_64",
        "pt_interp": interpreter, "build_id_sha1": build_id,
        "soname": soname, "needed": list(needed),
        "rpath": None, "runpath": None,
    }


class StagedClosureFixture:
    stage = "runtime/checkpoint_source/v1"
    built_interp = "/lib64/ld-linux-x86-64.so.2"

    def __init__(self, root: Path, *, physical_elf_overrides: dict[str, object] | None = None,
                 noncanonical_document: str | None = None) -> None:
        self.root = root
        self.physical_elf_overrides = physical_elf_overrides or {}
        self.noncanonical_document = noncanonical_document
        self.documents: dict[str, dict[str, object]] = {}
        self.runtime_artifacts: list[dict[str, object]] = []
        self._prepare_files()
        self.authority, self.expected = self._prepare_authority()

    def write(self, relative: str, payload: bytes) -> dict[str, object]:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        return {
            "path": relative, "size_bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }

    def write_json(self, relative: str, value: dict[str, object], label: str) -> dict[str, object]:
        payload = canonical_bytes(value) + b"\n"
        if self.noncanonical_document == label:
            payload = json.dumps(value, indent=2, sort_keys=True).encode("ascii") + b"\n"
        return self.write(relative, payload)

    @staticmethod
    def self_hash(value: dict[str, object], field: str) -> dict[str, object]:
        value[field] = canonical_sha(value)
        return value

    def artifact(self, artifact_id: str, artifact_class: str, relative: str,
                 payload: bytes, elf: dict[str, object] | None,
                 content_identity: str | None = None) -> dict[str, object]:
        return {
            "artifact_id": artifact_id, "artifact_class": artifact_class,
            "descriptor": self.write(relative, payload),
            "content_identity_sha256": content_identity or hashlib.sha256(payload).hexdigest(),
            "elf": elf,
        }

    def plain_artifact(self, artifact_id: str, artifact_class: str,
                       relative: str, payload: bytes) -> dict[str, object]:
        descriptor = self.write(relative, payload)
        return {
            "artifact_id": artifact_id, "artifact_class": artifact_class,
            "descriptor": descriptor,
            "content_identity_sha256": descriptor["sha256"],
        }

    def physical_elf(self, artifact_id: str, *, build_id: str, soname: str | None,
                     needed: tuple[str, ...] = (), interpreter: str | None = None) -> bytes:
        values: dict[str, object] = {
            "build_id": build_id, "soname": soname, "needed": needed,
            "interpreter": interpreter, "machine": 62,
        }
        if artifact_id == "checkpoint_source":
            values.update(self.physical_elf_overrides)
        return minimal_elf(**values)  # type: ignore[arg-type]

    def _prepare_files(self) -> None:
        source_build_id = "1" * 40
        libc_id = "2" * 40
        interpreter_id = "3" * 40
        scanner_id = "4" * 40
        specs = [
            ("checkpoint_source", "source_executable", "bin/vast_checkpoint_source",
             source_build_id, None, ("libc.so.6",), self.built_interp),
            ("elf_interpreter", "elf_interpreter", "lib/ld-linux-x86-64.so.2",
             interpreter_id, "ld-linux-x86-64.so.2", (), None),
            ("gst_plugin_scanner", "gst_plugin_scanner",
             "libexec/gstreamer-1.0/gst-plugin-scanner", scanner_id, None,
             ("libc.so.6",), self.built_interp),
            ("libc", "shared_object", "lib/libc.so.6", libc_id, "libc.so.6", (), None),
            ("gst_app", "gst_plugin_module", "plugins/libgstapp.so", "5" * 40,
             "libgstapp_fixture.so", ("libc.so.6",), None),
            ("gst_coreelements", "gst_plugin_module", "plugins/libgstcoreelements.so",
             "6" * 40, "libgstcoreelements_fixture.so", ("libc.so.6",), None),
            ("gst_isomp4", "gst_plugin_module", "plugins/libgstisomp4.so", "7" * 40,
             "libgstisomp4_fixture.so", ("libc.so.6",), None),
            ("gst_videoparsersbad", "gst_plugin_module",
             "plugins/libgstvideoparsersbad.so", "8" * 40,
             "libgstvideoparsersbad_fixture.so", ("libc.so.6",), None),
        ]
        for artifact_id, artifact_class, suffix, build_id, soname, needed, interp in specs:
            declared = elf_metadata(
                build_id=build_id, soname=soname, needed=needed, interpreter=interp,
            )
            payload = self.physical_elf(
                artifact_id, build_id=build_id, soname=soname,
                needed=needed, interpreter=interp,
            )
            self.runtime_artifacts.append(self.artifact(
                artifact_id, artifact_class, f"{self.stage}/{suffix}", payload, declared,
            ))

        registry_seed = self.artifact(
            "gst_registry_seed", "gst_registry_seed", f"{self.stage}/registry/registry.bin",
            b"opaque-gstreamer-registry-seed-v1\n", None,
        )
        self.runtime_artifacts.append(registry_seed)
        self.registry_catalog = self.self_hash({
            "schema_version": 1, "artifact_kind": GST_REGISTRY_CATALOG_KIND,
            "gstreamer_api_version": "1.0", "gstreamer_version": "1.24.2",
            "registry_seed_artifact_id": "gst_registry_seed",
            "factories": [
                {"factory_name": "appsink", "feature_kind": "element_factory",
                 "plugin_name": "app", "plugin_version": "1.24.2",
                 "plugin_artifact_id": "gst_app"},
                {"factory_name": "filesrc", "feature_kind": "element_factory",
                 "plugin_name": "coreelements", "plugin_version": "1.24.2",
                 "plugin_artifact_id": "gst_coreelements"},
                {"factory_name": "h264parse", "feature_kind": "element_factory",
                 "plugin_name": "videoparsersbad", "plugin_version": "1.24.2",
                 "plugin_artifact_id": "gst_videoparsersbad"},
                {"factory_name": "h265parse", "feature_kind": "element_factory",
                 "plugin_name": "videoparsersbad", "plugin_version": "1.24.2",
                 "plugin_artifact_id": "gst_videoparsersbad"},
                {"factory_name": "qtdemux", "feature_kind": "element_factory",
                 "plugin_name": "isomp4", "plugin_version": "1.24.2",
                 "plugin_artifact_id": "gst_isomp4"},
            ],
        }, "gst_registry_catalog_sha256")
        catalog_payload = canonical_bytes(self.registry_catalog) + b"\n"
        if self.noncanonical_document == "registry_catalog":
            catalog_payload = json.dumps(self.registry_catalog, indent=2, sort_keys=True).encode("ascii") + b"\n"
        self.runtime_artifacts.append(self.artifact(
            "gst_registry_catalog", "gst_registry_catalog",
            f"{self.stage}/authority/gst-registry-catalog.json", catalog_payload, None,
            str(self.registry_catalog["gst_registry_catalog_sha256"]),
        ))

        self.environment_policy = self.self_hash({
            "schema_version": 1, "artifact_kind": ENVIRONMENT_POLICY_KIND,
            "inherit_parent_environment": False,
            "static_environment": [
                {"name": "GST_PLUGIN_SYSTEM_PATH_1_0", "value": "${STAGE_ROOT}/plugins"},
                {"name": "GST_PLUGIN_PATH_1_0", "value": ""},
                {"name": "GST_PLUGIN_SCANNER_1_0", "value": "${STAGE_ROOT}/libexec/gstreamer-1.0/gst-plugin-scanner"},
                {"name": "GST_REGISTRY_1_0", "value": "${LEASE_ROOT}/gstreamer/registry.bin"},
                {"name": "GST_REGISTRY_UPDATE", "value": "no"},
                {"name": "GST_REGISTRY_FORK", "value": "no"},
                {"name": "HOME", "value": "${LEASE_ROOT}/home"},
                {"name": "LANG", "value": "C"},
                {"name": "LC_ALL", "value": "C"},
                {"name": "TZ", "value": "UTC"},
                {"name": "XDG_CACHE_HOME", "value": "${LEASE_ROOT}/xdg/cache"},
                {"name": "XDG_CONFIG_HOME", "value": "${LEASE_ROOT}/xdg/config"},
                {"name": "XDG_DATA_HOME", "value": "${LEASE_ROOT}/xdg/data"},
                {"name": "XDG_RUNTIME_DIR", "value": "${LEASE_ROOT}/xdg/runtime"},
            ],
            "forced_unset_environment": [
                "GIO_EXTRA_MODULES", "GST_DEBUG", "GST_PLUGIN_FEATURE_RANK",
                "GST_PLUGIN_PATH", "GST_PLUGIN_SCANNER", "GST_PLUGIN_SYSTEM_PATH",
                "GST_REGISTRY", "LD_AUDIT", "LD_DEBUG", "LD_LIBRARY_PATH", "LD_PRELOAD",
            ],
            "dynamic_environment": [
                {"name": "VAST_CHECKPOINT_WORKER_ID", "value_kind": "lowercase_identifier"},
                {"name": "VAST_CHECKPOINT_RUN_ID", "value_kind": "nonempty_ascii"},
                {"name": "VAST_CHECKPOINT_DATASET_ID", "value_kind": "lowercase_identifier"},
                {"name": "VAST_CHECKPOINT_SOURCE_SHA256", "value_kind": "lowercase_sha256"},
                {"name": "VAST_CHECKPOINT_STREAM_ID", "value_kind": "nonnegative_int32"},
                {"name": "VAST_CHECKPOINT_SOURCE_CONTAINER", "value_kind": "literal_mp4"},
                {"name": "VAST_CHECKPOINT_SOURCE_CODEC", "value_kind": "h264_or_h265"},
                {"name": "VAST_CHECKPOINT_SOURCE_DURATION_NS", "value_kind": "positive_uint64"},
                {"name": "VAST_CHECKPOINT_PLAYBACK_TIMESTAMP_SCALE", "value_kind": "positive_uint64"},
                {"name": "VAST_CHECKPOINT_SOURCE_REPLAY", "value_kind": "literal_continuous"},
                {"name": "VAST_CHECKPOINT_ADMISSION_MODE", "value_kind": "literal_native_common_source_coordinator"},
                {"name": "VAST_CHECKPOINT_ADMISSION_EVENT_FD", "value_kind": "decimal_fd"},
                {"name": "VAST_CHECKPOINT_ADMISSION_ACK_FD", "value_kind": "decimal_fd"},
                {"name": "VAST_CHECKPOINT_CONTROL_FD", "value_kind": "decimal_fd"},
                {"name": "VAST_CHECKPOINT_STATUS_FD", "value_kind": "decimal_fd"},
                {"name": "VAST_CHECKPOINT_ADMISSION_CONSUMER_FDS_JSON", "value_kind": "canonical_consumer_fd_map"},
            ],
            "inherited_fd_bindings": [
                {"environment_name": "VAST_CHECKPOINT_ADMISSION_EVENT_FD", "role": "admission_event_write", "direction": "write", "multiplicity": "one"},
                {"environment_name": "VAST_CHECKPOINT_ADMISSION_ACK_FD", "role": "admission_ack_read", "direction": "read", "multiplicity": "one"},
                {"environment_name": "VAST_CHECKPOINT_CONTROL_FD", "role": "lifecycle_control_read", "direction": "read", "multiplicity": "one"},
                {"environment_name": "VAST_CHECKPOINT_STATUS_FD", "role": "lifecycle_status_write", "direction": "write", "multiplicity": "one"},
                {"environment_name": "VAST_CHECKPOINT_ADMISSION_CONSUMER_FDS_JSON", "role": "compressed_access_unit_write", "direction": "write", "multiplicity": "one_or_more"},
            ],
        }, "environment_policy_sha256")
        environment_path = f"{self.stage}/authority/environment-policy.json"
        environment_descriptor = self.write_json(
            environment_path, self.environment_policy, "environment_policy",
        )
        self.environment_ref = {
            "descriptor": environment_descriptor,
            "content_identity_sha256": self.environment_policy["environment_policy_sha256"],
        }

        self.source_inputs = [
            self.plain_artifact("cmake_project_file", "cmake_project_file",
                                f"{self.stage}/build-inputs/CMakeLists.txt", b"cmake-minimum-v1\n"),
            self.plain_artifact("coordinator_translation_unit", "coordinator_translation_unit",
                                f"{self.stage}/build-inputs/checkpoint_source_coordinator.cpp", b"coordinator-v1\n"),
            self.plain_artifact("admission_transport_header", "admission_transport_header",
                                f"{self.stage}/build-inputs/checkpoint_admission_transport.hpp", b"transport-v1\n"),
        ]
        self.source_object = self.plain_artifact(
            "coordinator_object", "coordinator_object",
            f"{self.stage}/build-outputs/checkpoint_source_coordinator.cpp.o",
            b"coordinator-object-v1\n",
        )
        self.tool_artifacts = [
            self.plain_artifact("cmake_tool", "cmake", f"{self.stage}/toolchain/bin/cmake", b"cmake-tool-v1\n"),
            self.plain_artifact("cxx_compiler_tool", "cxx_compiler", f"{self.stage}/toolchain/bin/cxx", b"cxx-tool-v1\n"),
            self.plain_artifact("pkg_config_tool", "pkg_config", f"{self.stage}/toolchain/bin/pkg-config", b"pkg-config-tool-v1\n"),
            self.plain_artifact("build_tool", "build_tool", f"{self.stage}/toolchain/bin/build-tool", b"build-tool-v1\n"),
        ]
        source_tree_identity = canonical_sha({
            "schema_version": 1,
            "artifact_kind": "vast_checkpoint_source_tree_identity_v1",
            "source_inputs": self.source_inputs,
        })
        compile_argv = [
            "${CXX}", "-O2", "-fstack-protector-strong", "-D_FORTIFY_SOURCE=3",
            "-fPIE", "-fcf-protection=full", "-std=gnu++17", "-pthread", "-c",
            "${SOURCE_ROOT}/deploy/native_gst_probe/checkpoint_source_coordinator.cpp",
            "-o", "${BUILD_ROOT}/checkpoint_source_coordinator.cpp.o",
        ]
        link_argv = [
            "${CXX}", "${BUILD_ROOT}/checkpoint_source_coordinator.cpp.o",
            "-Wl,-z,relro", "-Wl,-z,now", "-Wl,-z,noexecstack", "-pie",
            "-o", "${STAGE_ROOT}/bin/vast_checkpoint_source",
        ]
        commands = [
            ["${CMAKE}", "-S", "${SOURCE_ROOT}", "-B", "${BUILD_ROOT}",
             "-DCMAKE_BUILD_TYPE=Release", "-DVAST_BUILD_NATIVE_GST_PROBE=ON"],
            ["${CMAKE}", "--build", "${BUILD_ROOT}", "--target", "vast_checkpoint_source"],
            compile_argv, link_argv,
        ]
        command_names = ("configure", "build", "compile", "link")
        self.build_provenance = self.self_hash({
            "schema_version": 1, "artifact_kind": BUILD_PROVENANCE_KIND,
            "target_name": "vast_checkpoint_source", "build_configuration": "Release",
            "source_inputs": self.source_inputs,
            "source_tree_identity_sha256": source_tree_identity,
            "source_object": self.source_object,
            "tool_artifacts": self.tool_artifacts,
            "tool_versions": [
                {"tool_class": "cmake", "version": "3.28.3"},
                {"tool_class": "cxx_compiler", "version": "13.3.0"},
                {"tool_class": "pkg_config", "version": "1.8.1"},
                {"tool_class": "build_tool", "version": "4.3"},
            ],
            "pkg_config_modules": [
                {"name": name, "version": "1.24.2"} for name in (
                    "gstreamer-1.0", "gstreamer-app-1.0",
                    "gstreamer-rtp-1.0", "gstreamer-video-1.0",
                )
            ],
            "commands": [
                {"name": name, "argv": argv, "argv_sha256": canonical_sha(argv)}
                for name, argv in zip(command_names, commands)
            ],
            "required_compile_hardening_flags": [
                "-O2", "-fstack-protector-strong", "-D_FORTIFY_SOURCE=3",
                "-fPIE", "-fcf-protection=full",
            ],
            "required_link_hardening_flags": [
                "-Wl,-z,relro", "-Wl,-z,now", "-Wl,-z,noexecstack", "-pie",
            ],
            "reproducibility_observation": {
                "observation_kind": "two_clean_builds_byte_identical_candidate",
                "build_count": 2,
                "source_executable_sha256": self.runtime_artifacts[0]["descriptor"]["sha256"],
                "source_executable_size_bytes": self.runtime_artifacts[0]["descriptor"]["size_bytes"],
                "source_executable_build_id_sha1": source_build_id,
                "source_object_sha256": self.source_object["descriptor"]["sha256"],
                "independently_attested": False,
            },
            "toolchain_closure_complete": False,
        }, "build_provenance_sha256")
        build_path = f"{self.stage}/authority/build-provenance.json"
        build_descriptor = self.write_json(build_path, self.build_provenance, "build_provenance")
        self.build_ref = {
            "descriptor": build_descriptor,
            "content_identity_sha256": self.build_provenance["build_provenance_sha256"],
        }

        self.invocation_contract = self.self_hash({
            "schema_version": 1, "artifact_kind": INVOCATION_CONTRACT_KIND,
            "loader_mode": "explicit_staged_interpreter",
            "interpreter_artifact_id": "elf_interpreter",
            "source_executable_artifact_id": "checkpoint_source",
            "fixed_loader_argv": [
                "${INTERPRETER}", "--library-path", "${STAGE_ROOT}/lib",
                "${SOURCE_EXECUTABLE}",
            ],
            "argv_fields": [
                {"flag": "--source-path", "value_kind": "absolute_dataset_path"},
                {"flag": "--dataset-id", "value_kind": "lowercase_identifier"},
                {"flag": "--source-sha256", "value_kind": "lowercase_sha256"},
                {"flag": "--checkpoint-container", "value_kind": "literal_mp4"},
                {"flag": "--checkpoint-codec", "value_kind": "h264_or_h265"},
                {"flag": "--source-duration-ns", "value_kind": "positive_uint64"},
                {"flag": "--playback-timestamp-scale", "value_kind": "positive_uint64"},
                {"flag": "--source-replay", "value_kind": "literal_continuous"},
                {"flag": "--logical-stream-id", "value_kind": "nonnegative_int32"},
            ],
            "control_lines": [
                {"version": "1", "command": "START", "value_kinds": [
                    "future_monotonic_ns", "window_start_ms", "window_end_ms",
                    "drain_end_ms",
                ]},
                {"version": "1", "command": "STOP", "value_kinds": ["window_end_ms"]},
            ],
            "status_states": [
                "READY", "STARTED", "ADMISSION_STOPPED", "DRAINED", "CENSORED",
            ],
            "admission_event_fields": [
                "protocol_version", "source_process_id", "sequence", "run_id",
                "dataset_id", "stream_id", "admission_id", "input_frame_key",
                "source_sha256", "source_cycle", "access_unit_pts_ns",
                "payload_sha256", "payload_size_bytes", "schedule_offset_ns",
                "admission_timestamp_ms", "event_provenance",
            ],
            "ack_line": {"version": "1", "command": "ACK", "value_kinds": ["sequence"]},
            "transport_contract_version": 1,
        }, "invocation_contract_sha256")
        invocation_path = f"{self.stage}/authority/invocation-contract.json"
        invocation_descriptor = self.write_json(
            invocation_path, self.invocation_contract, "invocation_contract",
        )
        self.invocation_ref = {
            "descriptor": invocation_descriptor,
            "content_identity_sha256": self.invocation_contract["invocation_contract_sha256"],
        }

    @staticmethod
    def loader_graph(artifacts: list[dict[str, object]]) -> dict[str, object]:
        by_soname = {
            item["elf"]["soname"]: item["artifact_id"]
            for item in artifacts if item["elf"] is not None and item["elf"]["soname"]
        }
        roots = [item["artifact_id"] for item in artifacts
                 if item["artifact_class"] in (
                     "source_executable", "elf_interpreter",
                     "gst_plugin_scanner", "gst_plugin_module",
                 )]
        edges = []
        for item in artifacts:
            if item["elf"] is None:
                continue
            for index, soname in enumerate(item["elf"]["needed"]):
                edges.append({
                    "from_artifact_id": item["artifact_id"], "needed_index": index,
                    "needed_soname": soname, "to_artifact_id": by_soname[soname],
                })
        return {
            "loader_mode": "explicit_staged_interpreter",
            "built_pt_interp": StagedClosureFixture.built_interp,
            "elf_interpreter_artifact_id": "elf_interpreter",
            "root_artifact_ids": roots, "edges": edges,
        }

    def _prepare_authority(self) -> tuple[dict[str, object], dict[str, object]]:
        gstreamer = {
            "api_version": "1.0", "scanner_artifact_id": "gst_plugin_scanner",
            "registry_seed_artifact_id": "gst_registry_seed",
            "registry_catalog_artifact_id": "gst_registry_catalog",
            "registry_catalog_content": self.registry_catalog,
            "required_factory_bindings": self.registry_catalog["factories"],
        }
        target = {
            "target_name": "vast_checkpoint_source", "operating_system": "linux",
            "architecture": "x86_64", "binary_format": "ELF64",
            "byte_order": "little_endian", "abi_family": "gnu",
            "build_configuration": "Release",
        }
        manifest: dict[str, object] = {
            "schema_version": 1, "artifact_kind": MANIFEST_KIND,
            "target": target, "runtime_artifacts": self.runtime_artifacts,
            "elf_loader_graph": self.loader_graph(self.runtime_artifacts),
            "gstreamer": gstreamer,
            "environment_policy": self.environment_ref,
            "environment_policy_content": self.environment_policy,
            "build_provenance": self.build_ref,
            "build_provenance_content": self.build_provenance,
            "invocation_contract": self.invocation_ref,
            "invocation_contract_content": self.invocation_contract,
        }
        closure_set = {
            "schema_version": 1, "artifact_kind": CLOSURE_SET_KIND,
            "target": target, "runtime_artifacts": self.runtime_artifacts,
            "elf_loader_graph": manifest["elf_loader_graph"], "gstreamer": gstreamer,
            "environment_policy": self.environment_ref,
            "environment_policy_content": self.environment_policy,
            "invocation_contract": self.invocation_ref,
            "invocation_contract_content": self.invocation_contract,
        }
        manifest["runtime_closure_set_sha256"] = canonical_sha(closure_set)
        manifest["checkpoint_source_runtime_closure_manifest_sha256"] = canonical_sha(manifest)
        manifest_path = f"{self.stage}/authority/runtime-closure-manifest.json"
        manifest_descriptor = self.write_json(manifest_path, manifest, "manifest")
        authority: dict[str, object] = {
            "schema_version": 1, "artifact_kind": AUTHORITY_KIND,
            "runtime_closure_manifest": {
                "descriptor": manifest_descriptor,
                "content_identity_sha256": manifest[
                    "checkpoint_source_runtime_closure_manifest_sha256"
                ],
            },
            "runtime_closure_manifest_content": manifest,
            "runtime_closure_set_sha256": manifest["runtime_closure_set_sha256"],
            "environment_policy_sha256": self.environment_policy["environment_policy_sha256"],
            "build_provenance_sha256": self.build_provenance["build_provenance_sha256"],
            "invocation_contract_sha256": self.invocation_contract["invocation_contract_sha256"],
            "source_executable_sha256": self.runtime_artifacts[0]["descriptor"]["sha256"],
            "source_executable_size_bytes": self.runtime_artifacts[0]["descriptor"]["size_bytes"],
            "source_executable_build_id_sha1": self.runtime_artifacts[0]["elf"]["build_id_sha1"],
            "cmake_file_sha256": self.source_inputs[0]["descriptor"]["sha256"],
            "coordinator_source_sha256": self.source_inputs[1]["descriptor"]["sha256"],
            "transport_header_sha256": self.source_inputs[2]["descriptor"]["sha256"],
            "source_object_sha256": self.source_object["descriptor"]["sha256"],
        }
        authority["checkpoint_source_runtime_closure_authority_sha256"] = canonical_sha(authority)
        expected = {
            "expected_authority_sha256": authority[
                "checkpoint_source_runtime_closure_authority_sha256"
            ],
            "expected_manifest_sha256": manifest[
                "checkpoint_source_runtime_closure_manifest_sha256"
            ],
            "expected_runtime_closure_set_sha256": manifest["runtime_closure_set_sha256"],
            "expected_environment_policy_sha256": self.environment_policy[
                "environment_policy_sha256"
            ],
            "expected_build_provenance_sha256": self.build_provenance[
                "build_provenance_sha256"
            ],
            "expected_invocation_contract_sha256": self.invocation_contract[
                "invocation_contract_sha256"
            ],
            "expected_source_executable_sha256": self.runtime_artifacts[0]["descriptor"]["sha256"],
            "expected_source_executable_size_bytes": self.runtime_artifacts[0]["descriptor"]["size_bytes"],
            "expected_source_executable_build_id_sha1": self.runtime_artifacts[0]["elf"]["build_id_sha1"],
            "expected_cmake_file_sha256": self.source_inputs[0]["descriptor"]["sha256"],
            "expected_coordinator_source_sha256": self.source_inputs[1]["descriptor"]["sha256"],
            "expected_transport_header_sha256": self.source_inputs[2]["descriptor"]["sha256"],
            "expected_source_object_sha256": self.source_object["descriptor"]["sha256"],
        }
        self.manifest_path = manifest_path
        return authority, expected

    def manifest_expected(self) -> dict[str, object]:
        return {key: value for key, value in self.expected.items()
                if key != "expected_authority_sha256"}

    def reseal_manifest(self, manifest: dict[str, object]) -> dict[str, object]:
        closure_set = {
            "schema_version": 1, "artifact_kind": CLOSURE_SET_KIND,
            "target": manifest["target"], "runtime_artifacts": manifest["runtime_artifacts"],
            "elf_loader_graph": manifest["elf_loader_graph"], "gstreamer": manifest["gstreamer"],
            "environment_policy": manifest["environment_policy"],
            "environment_policy_content": manifest["environment_policy_content"],
            "invocation_contract": manifest["invocation_contract"],
            "invocation_contract_content": manifest["invocation_contract_content"],
        }
        manifest["runtime_closure_set_sha256"] = canonical_sha(closure_set)
        manifest.pop("checkpoint_source_runtime_closure_manifest_sha256", None)
        manifest["checkpoint_source_runtime_closure_manifest_sha256"] = canonical_sha(manifest)
        return manifest


class CheckpointSourceRuntimeClosureAuthorityV1Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.fixture = StagedClosureFixture(self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_validate_assess_and_build_candidate_without_authorization(self) -> None:
        manifest = validate_checkpoint_source_runtime_closure_manifest_v1(
            self.fixture.authority["runtime_closure_manifest_content"],
            **self.fixture.manifest_expected(),
        )
        self.assertEqual(manifest, self.fixture.authority["runtime_closure_manifest_content"])
        validated = validate_checkpoint_source_runtime_closure_authority_v1(
            self.fixture.authority, **self.fixture.expected,
        )
        self.assertEqual(validated, self.fixture.authority)
        assessment = assess_checkpoint_source_runtime_closure_authority_v1(
            validated, project_root=self.root, **self.fixture.expected,
        )
        self.assertEqual(assessment["artifact_kind"], ASSESSMENT_KIND)
        self.assertEqual(assessment["status"], "physically_valid_candidate")
        self.assertEqual(assessment["blockers"], [])
        self.assertEqual(assessment["checked_artifact_count"], 22)
        for field in (
            "authority_pin_validated", "manifest_and_external_pins_validated",
            "staged_artifact_bytes_reconstructed", "individual_artifact_reads_handle_bound",
            "all_artifact_physical_identities_distinct", "elf_metadata_physically_reconstructed",
            "ordered_dt_needed_graph_reconstructed",
            "declared_gstreamer_factory_coverage_validated",
            "environment_build_invocation_bytes_crossbound",
        ):
            self.assertIs(assessment[field], True, field)
        false_claims = [key for key, value in assessment.items()
                        if key.endswith(("_validated", "_enforced", "_authorized", "_attested"))
                        and key not in {
                            "authority_pin_validated", "manifest_and_external_pins_validated",
                            "all_artifact_physical_identities_distinct",
                            "elf_metadata_physically_reconstructed",
                            "ordered_dt_needed_graph_reconstructed",
                            "declared_gstreamer_factory_coverage_validated",
                        }]
        for field in false_claims:
            if field not in {"staged_artifact_bytes_reconstructed",
                              "environment_build_invocation_bytes_crossbound",
                              "individual_artifact_reads_handle_bound"}:
                self.assertIs(assessment[field], False, field)
        built = build_checkpoint_source_runtime_closure_authority_v1(
            project_root=self.root,
            runtime_closure_manifest_path=self.fixture.manifest_path,
            **self.fixture.expected,
        )
        self.assertEqual(built, self.fixture.authority)

    def test_external_pins_are_mandatory_strict_and_checked_before_content(self) -> None:
        signature = inspect.signature(validate_checkpoint_source_runtime_closure_manifest_v1)
        for name, parameter in signature.parameters.items():
            if name != "value":
                self.assertEqual(parameter.kind, inspect.Parameter.KEYWORD_ONLY, name)
                self.assertEqual(parameter.default, inspect.Parameter.empty, name)
        for key, bad in (
            ("expected_manifest_sha256", "A" * 64),
            ("expected_runtime_closure_set_sha256", "0" * 63),
            ("expected_environment_policy_sha256", True),
            ("expected_build_provenance_sha256", "g" * 64),
            ("expected_invocation_contract_sha256", None),
            ("expected_source_executable_sha256", "f" * 65),
            ("expected_source_executable_size_bytes", True),
            ("expected_source_executable_build_id_sha1", "f" * 39),
            ("expected_cmake_file_sha256", "A" * 64),
            ("expected_coordinator_source_sha256", "0" * 63),
            ("expected_transport_header_sha256", True),
            ("expected_source_object_sha256", "g" * 64),
        ):
            expected = dict(self.fixture.manifest_expected())
            expected[key] = bad
            with self.subTest(key=key), self.assertRaises(
                CheckpointSourceRuntimeClosureAuthorityV1Error
            ):
                validate_checkpoint_source_runtime_closure_manifest_v1(None, **expected)
        aliased = dict(self.fixture.manifest_expected())
        aliased["expected_environment_policy_sha256"] = aliased["expected_build_provenance_sha256"]
        with self.assertRaises(CheckpointSourceRuntimeClosureAuthorityV1Error):
            validate_checkpoint_source_runtime_closure_manifest_v1(None, **aliased)

    def test_closed_schema_self_hash_and_new_only_kinds(self) -> None:
        for mutator in (
            lambda value: value.update({"publication_ready": False}),
            lambda value: value.update({"schema_version": 2}),
            lambda value: value.update({"artifact_kind": "vast_backend_publication_runtime_authority_v2"}),
        ):
            changed = copy.deepcopy(self.fixture.authority)
            mutator(changed)
            with self.assertRaises(CheckpointSourceRuntimeClosureAuthorityV1Error):
                validate_checkpoint_source_runtime_closure_authority_v1(
                    changed, **self.fixture.expected,
                )
        manifest = copy.deepcopy(self.fixture.authority["runtime_closure_manifest_content"])
        manifest["target"]["architecture"] = "aarch64"
        with self.assertRaisesRegex(CheckpointSourceRuntimeClosureAuthorityV1Error, "target identity"):
            validate_checkpoint_source_runtime_closure_manifest_v1(
                manifest, **self.fixture.manifest_expected(),
            )
        manifest = copy.deepcopy(self.fixture.authority["runtime_closure_manifest_content"])
        manifest["checkpoint_source_runtime_closure_manifest_sha256"] = "f" * 64
        with self.assertRaisesRegex(CheckpointSourceRuntimeClosureAuthorityV1Error, "manifest identity"):
            validate_checkpoint_source_runtime_closure_manifest_v1(
                manifest, **self.fixture.manifest_expected(),
            )
        source = Path(source_authority.__file__).read_text(encoding="utf-8")
        self.assertNotIn('"source_protocol"', source)
        self.assertNotIn('"source_plan"', source)

    def test_json_scalar_types_are_exact_and_never_accept_bool_or_float(self) -> None:
        base = self.fixture.authority["runtime_closure_manifest_content"]
        mutations: tuple[tuple[str | None, callable], ...] = (
            (None, lambda value: value.update({"schema_version": True})),
            ("environment_policy_content", lambda value: value[
                "environment_policy_content"
            ].update({"schema_version": True})),
            ("build_provenance_content", lambda value: value[
                "build_provenance_content"
            ].update({"schema_version": 1.0})),
            ("build_provenance_content", lambda value: value[
                "build_provenance_content"
            ]["reproducibility_observation"].update({"build_count": 2.0})),
            ("build_provenance_content", lambda value: value[
                "build_provenance_content"
            ]["reproducibility_observation"].update({
                "source_executable_size_bytes": float(value[
                    "build_provenance_content"
                ]["reproducibility_observation"][
                    "source_executable_size_bytes"
                ])
            })),
            ("invocation_contract_content", lambda value: value[
                "invocation_contract_content"
            ].update({"transport_contract_version": True})),
            ("registry_catalog_content", lambda value: value["gstreamer"][
                "registry_catalog_content"
            ].update({"schema_version": 1.0})),
            (None, lambda value: value["elf_loader_graph"]["edges"][0].update(
                {"needed_index": False}
            )),
            (None, lambda value: value["runtime_artifacts"][0][
                "descriptor"
            ].update({"size_bytes": 440.0})),
        )
        fields = {
            "environment_policy_content": "environment_policy_sha256",
            "build_provenance_content": "build_provenance_sha256",
            "invocation_contract_content": "invocation_contract_sha256",
            "registry_catalog_content": "gst_registry_catalog_sha256",
        }
        for index, (section, mutate) in enumerate(mutations):
            changed = copy.deepcopy(base)
            mutate(changed)
            if section == "registry_catalog_content":
                content = changed["gstreamer"]["registry_catalog_content"]
                field = fields[section]
                content.pop(field)
                content[field] = canonical_sha(content)
                catalog = next(item for item in changed["runtime_artifacts"]
                               if item["artifact_class"] == "gst_registry_catalog")
                catalog["content_identity_sha256"] = content[field]
            elif section is not None:
                content = changed[section]
                field = fields[section]
                content.pop(field)
                content[field] = canonical_sha(content)
                changed[section.removesuffix("_content")][
                    "content_identity_sha256"
                ] = content[field]
            changed = self.fixture.reseal_manifest(changed)
            expected = dict(self.fixture.manifest_expected())
            expected.update({
                "expected_manifest_sha256": changed[
                    "checkpoint_source_runtime_closure_manifest_sha256"
                ],
                "expected_runtime_closure_set_sha256": changed[
                    "runtime_closure_set_sha256"
                ],
            })
            if section in {
                "environment_policy_content", "build_provenance_content",
                "invocation_contract_content",
            }:
                expected[{
                    "environment_policy_content": "expected_environment_policy_sha256",
                    "build_provenance_content": "expected_build_provenance_sha256",
                    "invocation_contract_content": "expected_invocation_contract_sha256",
                }[section]] = changed[section][fields[section]]
            with self.subTest(index=index), self.assertRaises(
                CheckpointSourceRuntimeClosureAuthorityV1Error
            ):
                validate_checkpoint_source_runtime_closure_manifest_v1(
                    changed, **expected
                )

        authority = copy.deepcopy(self.fixture.authority)
        authority["schema_version"] = True
        with self.assertRaises(CheckpointSourceRuntimeClosureAuthorityV1Error):
            validate_checkpoint_source_runtime_closure_authority_v1(
                authority, **self.fixture.expected
            )

        authority = copy.deepcopy(self.fixture.authority)
        authority["source_executable_size_bytes"] = float(
            authority["source_executable_size_bytes"]
        )
        authority.pop("checkpoint_source_runtime_closure_authority_sha256")
        authority["checkpoint_source_runtime_closure_authority_sha256"] = (
            canonical_sha(authority)
        )
        expected = dict(self.fixture.expected)
        expected["expected_authority_sha256"] = authority[
            "checkpoint_source_runtime_closure_authority_sha256"
        ]
        with self.assertRaises(CheckpointSourceRuntimeClosureAuthorityV1Error):
            validate_checkpoint_source_runtime_closure_authority_v1(
                authority, **expected
            )

    def test_exact_runtime_order_cardinality_and_global_alias_rejection(self) -> None:
        base = self.fixture.authority["runtime_closure_manifest_content"]
        cases = []
        reordered = copy.deepcopy(base)
        reordered["runtime_artifacts"][0], reordered["runtime_artifacts"][1] = (
            reordered["runtime_artifacts"][1], reordered["runtime_artifacts"][0]
        )
        cases.append(reordered)
        missing = copy.deepcopy(base)
        missing["runtime_artifacts"] = [item for item in missing["runtime_artifacts"]
                                        if item["artifact_class"] != "gst_plugin_scanner"]
        cases.append(missing)
        duplicate_id = copy.deepcopy(base)
        duplicate_id["runtime_artifacts"][1]["artifact_id"] = "checkpoint_source"
        cases.append(duplicate_id)
        casefold_path = copy.deepcopy(base)
        casefold_path["runtime_artifacts"][1]["descriptor"]["path"] = (
            casefold_path["runtime_artifacts"][0]["descriptor"]["path"].upper()
        )
        cases.append(casefold_path)
        content_alias = copy.deepcopy(base)
        content_alias["runtime_artifacts"][1]["descriptor"]["sha256"] = (
            content_alias["runtime_artifacts"][0]["descriptor"]["sha256"]
        )
        content_alias["runtime_artifacts"][1]["content_identity_sha256"] = (
            content_alias["runtime_artifacts"][0]["content_identity_sha256"]
        )
        cases.append(content_alias)
        oversized_component = copy.deepcopy(base)
        oversized_component["runtime_artifacts"][0]["descriptor"]["path"] = (
            f"{self.fixture.stage}/bin/{'a' * 256}"
        )
        cases.append(oversized_component)
        for changed in cases:
            changed = self.fixture.reseal_manifest(changed)
            expected = dict(self.fixture.manifest_expected())
            expected["expected_manifest_sha256"] = changed[
                "checkpoint_source_runtime_closure_manifest_sha256"
            ]
            expected["expected_runtime_closure_set_sha256"] = changed[
                "runtime_closure_set_sha256"
            ]
            with self.subTest(index=cases.index(changed) if changed in cases else -1), self.assertRaises(
                CheckpointSourceRuntimeClosureAuthorityV1Error
            ):
                validate_checkpoint_source_runtime_closure_manifest_v1(changed, **expected)

    def test_paths_content_identities_and_semantic_domains_are_globally_unique(self) -> None:
        base = self.fixture.authority["runtime_closure_manifest_content"]
        mutations = []

        noncanonical_path = copy.deepcopy(base)
        noncanonical_path["runtime_artifacts"][3]["descriptor"]["path"] = (
            f"{self.fixture.stage}//lib/libc.so.6"
        )
        mutations.append(noncanonical_path)

        semantic_alias = copy.deepcopy(base)
        catalog = next(
            item for item in semantic_alias["runtime_artifacts"]
            if item["artifact_class"] == "gst_registry_catalog"
        )
        catalog["content_identity_sha256"] = semantic_alias[
            "environment_policy"
        ]["content_identity_sha256"]
        semantic_alias["gstreamer"]["registry_catalog_content"][
            "gst_registry_catalog_sha256"
        ] = catalog["content_identity_sha256"]
        mutations.append(semantic_alias)

        reserved_cycle = copy.deepcopy(base)
        catalog = next(
            item for item in reserved_cycle["runtime_artifacts"]
            if item["artifact_class"] == "gst_registry_catalog"
        )
        catalog["content_identity_sha256"] = reserved_cycle[
            "checkpoint_source_runtime_closure_manifest_sha256"
        ]
        reserved_cycle["gstreamer"]["registry_catalog_content"][
            "gst_registry_catalog_sha256"
        ] = catalog["content_identity_sha256"]
        mutations.append(reserved_cycle)

        for index, changed in enumerate(mutations):
            changed = self.fixture.reseal_manifest(changed)
            expected = dict(self.fixture.manifest_expected())
            expected.update({
                "expected_manifest_sha256": changed[
                    "checkpoint_source_runtime_closure_manifest_sha256"
                ],
                "expected_runtime_closure_set_sha256": changed[
                    "runtime_closure_set_sha256"
                ],
            })
            with self.subTest(index=index), self.assertRaises(
                CheckpointSourceRuntimeClosureAuthorityV1Error
            ):
                validate_checkpoint_source_runtime_closure_manifest_v1(
                    changed, **expected
                )

        raw = copy.deepcopy(base)
        canonical_path = raw["runtime_artifacts"][3]["descriptor"]["path"]
        raw["runtime_artifacts"][3]["descriptor"]["path"] = canonical_path.replace(
            "/lib/", "//lib/"
        )
        normalized = copy.deepcopy(raw)
        normalized["runtime_artifacts"][3]["descriptor"]["path"] = canonical_path
        normalized = self.fixture.reseal_manifest(normalized)
        raw["runtime_closure_set_sha256"] = normalized[
            "runtime_closure_set_sha256"
        ]
        raw["checkpoint_source_runtime_closure_manifest_sha256"] = normalized[
            "checkpoint_source_runtime_closure_manifest_sha256"
        ]
        expected = dict(self.fixture.manifest_expected())
        expected.update({
            "expected_manifest_sha256": raw[
                "checkpoint_source_runtime_closure_manifest_sha256"
            ],
            "expected_runtime_closure_set_sha256": raw[
                "runtime_closure_set_sha256"
            ],
        })
        with self.assertRaises(CheckpointSourceRuntimeClosureAuthorityV1Error):
            validate_checkpoint_source_runtime_closure_manifest_v1(raw, **expected)

        authority_alias = copy.deepcopy(self.fixture.authority)
        authority_alias["runtime_closure_manifest"]["descriptor"] = copy.deepcopy(
            base["runtime_artifacts"][0]["descriptor"]
        )
        authority_alias.pop("checkpoint_source_runtime_closure_authority_sha256")
        authority_alias["checkpoint_source_runtime_closure_authority_sha256"] = (
            canonical_sha(authority_alias)
        )
        expected = dict(self.fixture.expected)
        expected["expected_authority_sha256"] = authority_alias[
            "checkpoint_source_runtime_closure_authority_sha256"
        ]
        with self.assertRaises(CheckpointSourceRuntimeClosureAuthorityV1Error):
            validate_checkpoint_source_runtime_closure_authority_v1(
                authority_alias, **expected
            )

    def test_exact_factory_set_and_plugin_binding(self) -> None:
        for mutation in ("missing", "reordered", "wrong_plugin"):
            changed = copy.deepcopy(self.fixture.authority["runtime_closure_manifest_content"])
            catalog = changed["gstreamer"]["registry_catalog_content"]
            if mutation == "missing":
                catalog["factories"].pop()
            elif mutation == "reordered":
                catalog["factories"][0], catalog["factories"][1] = (
                    catalog["factories"][1], catalog["factories"][0]
                )
            else:
                catalog["factories"][0]["plugin_artifact_id"] = "libc"
            catalog.pop("gst_registry_catalog_sha256")
            catalog["gst_registry_catalog_sha256"] = canonical_sha(catalog)
            changed["gstreamer"]["required_factory_bindings"] = catalog["factories"]
            catalog_artifact = next(item for item in changed["runtime_artifacts"]
                                    if item["artifact_class"] == "gst_registry_catalog")
            catalog_artifact["content_identity_sha256"] = catalog["gst_registry_catalog_sha256"]
            changed = self.fixture.reseal_manifest(changed)
            expected = dict(self.fixture.manifest_expected())
            expected["expected_manifest_sha256"] = changed[
                "checkpoint_source_runtime_closure_manifest_sha256"
            ]
            expected["expected_runtime_closure_set_sha256"] = changed["runtime_closure_set_sha256"]
            with self.subTest(mutation=mutation), self.assertRaises(
                CheckpointSourceRuntimeClosureAuthorityV1Error
            ):
                validate_checkpoint_source_runtime_closure_manifest_v1(changed, **expected)

        changed = copy.deepcopy(self.fixture.authority["runtime_closure_manifest_content"])
        extra = copy.deepcopy(next(
            item for item in changed["runtime_artifacts"]
            if item["artifact_id"] == "gst_app"
        ))
        extra.update({"artifact_id": "gst_ambient"})
        extra["descriptor"] = copy.deepcopy(extra["descriptor"])
        extra["descriptor"].update({
            "path": f"{self.fixture.stage}/plugins/libgstambient.so",
            "sha256": sha("ambient-plugin"),
        })
        extra["content_identity_sha256"] = extra["descriptor"]["sha256"]
        extra["elf"] = copy.deepcopy(extra["elf"])
        extra["elf"].update({
            "build_id_sha1": "9" * 40,
            "soname": "libgstambient_fixture.so",
        })
        changed["runtime_artifacts"].insert(4, extra)
        changed["elf_loader_graph"] = self.fixture.loader_graph(
            changed["runtime_artifacts"]
        )
        changed = self.fixture.reseal_manifest(changed)
        expected = dict(self.fixture.manifest_expected())
        expected.update({
            "expected_manifest_sha256": changed[
                "checkpoint_source_runtime_closure_manifest_sha256"
            ],
            "expected_runtime_closure_set_sha256": changed[
                "runtime_closure_set_sha256"
            ],
        })
        with self.assertRaises(CheckpointSourceRuntimeClosureAuthorityV1Error):
            validate_checkpoint_source_runtime_closure_manifest_v1(
                changed, **expected
            )

    def test_loader_graph_requires_exact_needed_order_targets_and_reachability(self) -> None:
        mutations = (
            lambda graph: graph["edges"].pop(),
            lambda graph: graph["edges"].append(copy.deepcopy(graph["edges"][0])),
            lambda graph: graph["edges"].reverse(),
            lambda graph: graph["edges"][0].update({"to_artifact_id": "elf_interpreter"}),
            lambda graph: graph["root_artifact_ids"].pop(),
            lambda graph: graph.update({"built_pt_interp": "/ambient/ld.so"}),
        )
        for index, mutate in enumerate(mutations):
            changed = copy.deepcopy(self.fixture.authority["runtime_closure_manifest_content"])
            mutate(changed["elf_loader_graph"])
            changed = self.fixture.reseal_manifest(changed)
            expected = dict(self.fixture.manifest_expected())
            expected.update({
                "expected_manifest_sha256": changed[
                    "checkpoint_source_runtime_closure_manifest_sha256"
                ],
                "expected_runtime_closure_set_sha256": changed["runtime_closure_set_sha256"],
            })
            with self.subTest(index=index), self.assertRaises(
                CheckpointSourceRuntimeClosureAuthorityV1Error
            ):
                validate_checkpoint_source_runtime_closure_manifest_v1(changed, **expected)

        unreachable = copy.deepcopy(self.fixture.authority["runtime_closure_manifest_content"])
        extra = copy.deepcopy(next(item for item in unreachable["runtime_artifacts"]
                                   if item["artifact_class"] == "shared_object"))
        extra.update({"artifact_id": "unreachable_dso"})
        extra["descriptor"] = copy.deepcopy(extra["descriptor"])
        extra["descriptor"]["path"] = f"{self.fixture.stage}/lib/libunreachable.so"
        extra["descriptor"]["sha256"] = sha("unreachable-dso")
        extra["content_identity_sha256"] = sha("unreachable-dso")
        unreachable["runtime_artifacts"].insert(4, extra)
        unreachable = self.fixture.reseal_manifest(unreachable)
        expected = dict(self.fixture.manifest_expected())
        expected.update({
            "expected_manifest_sha256": unreachable[
                "checkpoint_source_runtime_closure_manifest_sha256"
            ],
            "expected_runtime_closure_set_sha256": unreachable["runtime_closure_set_sha256"],
        })
        with self.assertRaises(CheckpointSourceRuntimeClosureAuthorityV1Error):
            validate_checkpoint_source_runtime_closure_manifest_v1(unreachable, **expected)

        mismatched_interpreter = copy.deepcopy(
            self.fixture.authority["runtime_closure_manifest_content"]
        )
        for item in mismatched_interpreter["runtime_artifacts"]:
            if item["artifact_class"] in {"source_executable", "gst_plugin_scanner"}:
                item["elf"]["pt_interp"] = "/ambient/unbound-loader.so"
        mismatched_interpreter["elf_loader_graph"]["built_pt_interp"] = (
            "/ambient/unbound-loader.so"
        )
        mismatched_interpreter = self.fixture.reseal_manifest(mismatched_interpreter)
        expected = dict(self.fixture.manifest_expected())
        expected.update({
            "expected_manifest_sha256": mismatched_interpreter[
                "checkpoint_source_runtime_closure_manifest_sha256"
            ],
            "expected_runtime_closure_set_sha256": mismatched_interpreter[
                "runtime_closure_set_sha256"
            ],
        })
        with self.assertRaises(CheckpointSourceRuntimeClosureAuthorityV1Error):
            validate_checkpoint_source_runtime_closure_manifest_v1(
                mismatched_interpreter, **expected
            )

    def test_loader_roots_include_the_staged_elf_interpreter(self) -> None:
        roots = self.fixture.authority["runtime_closure_manifest_content"][
            "elf_loader_graph"
        ]["root_artifact_ids"]
        self.assertEqual(roots[:3], [
            "checkpoint_source", "elf_interpreter", "gst_plugin_scanner",
        ])

    def test_needed_targets_are_direct_lib_shared_objects_named_by_soname(self) -> None:
        cases = []
        outside_lib = copy.deepcopy(
            self.fixture.authority["runtime_closure_manifest_content"]
        )
        libc = next(item for item in outside_lib["runtime_artifacts"]
                    if item["artifact_id"] == "libc")
        libc["descriptor"]["path"] = f"{self.fixture.stage}/alternate/libc.so.6"
        cases.append(outside_lib)

        wrong_basename = copy.deepcopy(
            self.fixture.authority["runtime_closure_manifest_content"]
        )
        libc = next(item for item in wrong_basename["runtime_artifacts"]
                    if item["artifact_id"] == "libc")
        libc["descriptor"]["path"] = f"{self.fixture.stage}/lib/libc-staged.so.6"
        cases.append(wrong_basename)

        plugin_target = copy.deepcopy(
            self.fixture.authority["runtime_closure_manifest_content"]
        )
        libc = next(item for item in plugin_target["runtime_artifacts"]
                    if item["artifact_id"] == "libc")
        gst_app = next(item for item in plugin_target["runtime_artifacts"]
                       if item["artifact_id"] == "gst_app")
        libc["elf"]["soname"] = "libprivate.so"
        gst_app["elf"]["soname"] = "libc.so.6"
        gst_app["elf"]["needed"] = ["libprivate.so"]
        plugin_target["elf_loader_graph"] = self.fixture.loader_graph(
            plugin_target["runtime_artifacts"]
        )
        cases.append(plugin_target)

        for index, changed in enumerate(cases):
            changed = self.fixture.reseal_manifest(changed)
            expected = dict(self.fixture.manifest_expected())
            expected.update({
                "expected_manifest_sha256": changed[
                    "checkpoint_source_runtime_closure_manifest_sha256"
                ],
                "expected_runtime_closure_set_sha256": changed[
                    "runtime_closure_set_sha256"
                ],
            })
            with self.subTest(index=index), self.assertRaises(
                CheckpointSourceRuntimeClosureAuthorityV1Error
            ):
                validate_checkpoint_source_runtime_closure_manifest_v1(
                    changed, **expected
                )

    def test_environment_invocation_and_provenance_are_exact(self) -> None:
        cases: list[tuple[str, callable]] = [
            ("environment_policy_content", lambda value: value["static_environment"].pop()),
            ("environment_policy_content", lambda value: value.update({"inherit_parent_environment": True})),
            ("environment_policy_content", lambda value: value["forced_unset_environment"].remove("LD_PRELOAD")),
            ("environment_policy_content", lambda value: value["dynamic_environment"].reverse()),
            ("environment_policy_content", lambda value: value["inherited_fd_bindings"][0].update({"direction": "read"})),
            ("invocation_contract_content", lambda value: value["argv_fields"].pop()),
            ("invocation_contract_content", lambda value: value["fixed_loader_argv"].append("--ambient")),
            ("invocation_contract_content", lambda value: value["admission_event_fields"].reverse()),
            ("build_provenance_content", lambda value: value["source_inputs"].reverse()),
            ("build_provenance_content", lambda value: value["pkg_config_modules"].pop()),
            ("build_provenance_content", lambda value: value["commands"][0]["argv"].append("/tmp/ambient")),
            ("build_provenance_content", lambda value: value.update({"toolchain_closure_complete": True})),
            ("build_provenance_content", lambda value: value["reproducibility_observation"].update({"independently_attested": True})),
        ]
        hash_field = {
            "environment_policy_content": "environment_policy_sha256",
            "invocation_contract_content": "invocation_contract_sha256",
            "build_provenance_content": "build_provenance_sha256",
        }
        external_key = {
            "environment_policy_content": "expected_environment_policy_sha256",
            "invocation_contract_content": "expected_invocation_contract_sha256",
            "build_provenance_content": "expected_build_provenance_sha256",
        }
        for index, (section, mutate) in enumerate(cases):
            changed = copy.deepcopy(self.fixture.authority["runtime_closure_manifest_content"])
            content = changed[section]
            mutate(content)
            field = hash_field[section]
            content.pop(field)
            content[field] = canonical_sha(content)
            reference = section.removesuffix("_content")
            changed[reference]["content_identity_sha256"] = content[field]
            changed = self.fixture.reseal_manifest(changed)
            expected = dict(self.fixture.manifest_expected())
            expected.update({
                external_key[section]: content[field],
                "expected_manifest_sha256": changed[
                    "checkpoint_source_runtime_closure_manifest_sha256"
                ],
                "expected_runtime_closure_set_sha256": changed["runtime_closure_set_sha256"],
            })
            with self.subTest(index=index, section=section), self.assertRaises(
                CheckpointSourceRuntimeClosureAuthorityV1Error
            ):
                validate_checkpoint_source_runtime_closure_manifest_v1(changed, **expected)

    def test_physical_tamper_canonical_documents_and_elf_drift_block(self) -> None:
        binary_path = self.root / self.fixture.runtime_artifacts[0]["descriptor"]["path"]
        binary_path.write_bytes(binary_path.read_bytes() + b"x")
        assessment = assess_checkpoint_source_runtime_closure_authority_v1(
            self.fixture.authority, project_root=self.root, **self.fixture.expected,
        )
        self.assertEqual(assessment["status"], "blocked")
        self.assertFalse(assessment["staged_artifact_bytes_reconstructed"])

        for label in ("manifest", "environment_policy", "build_provenance",
                      "invocation_contract", "registry_catalog"):
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                fixture = StagedClosureFixture(root, noncanonical_document=label)
                assessment = assess_checkpoint_source_runtime_closure_authority_v1(
                    fixture.authority, project_root=root, **fixture.expected,
                )
                self.assertEqual(assessment["status"], "blocked")

    def test_elf_dynamic_segment_and_null_cardinality_fail_closed(self) -> None:
        for overrides in (
            {"extra_dynamic_segment": True},
            {"terminal_dynamic_tag": 0x6FFFFFFF},
            {"extra_dynamic_null": True},
        ):
            with self.subTest(overrides=overrides), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                fixture = StagedClosureFixture(root, physical_elf_overrides=overrides)
                assessment = assess_checkpoint_source_runtime_closure_authority_v1(
                    fixture.authority, project_root=root, **fixture.expected,
                )
                self.assertEqual(assessment["status"], "blocked")

        for overrides in (
            {"machine": 183}, {"interpreter": "/ambient/ld.so"},
            {"build_id": "9" * 40}, {"needed": ()}, {"rpath": "/ambient"},
            {"runpath": "/ambient"},
        ):
            with self.subTest(overrides=overrides), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                fixture = StagedClosureFixture(root, physical_elf_overrides=overrides)
                assessment = assess_checkpoint_source_runtime_closure_authority_v1(
                    fixture.authority, project_root=root, **fixture.expected,
                )
                self.assertEqual(assessment["status"], "blocked")

    @unittest.skipUnless(hasattr(os, "link"), "hard links unavailable")
    def test_physical_hardlink_alias_is_rejected(self) -> None:
        first = self.root / self.fixture.runtime_artifacts[3]["descriptor"]["path"]
        second = self.root / self.fixture.runtime_artifacts[4]["descriptor"]["path"]
        second.unlink()
        os.link(first, second)
        assessment = assess_checkpoint_source_runtime_closure_authority_v1(
            self.fixture.authority, project_root=self.root, **self.fixture.expected,
        )
        self.assertEqual(assessment["status"], "blocked")
        self.assertFalse(assessment["all_artifact_physical_identities_distinct"])

    def test_physical_reader_is_handle_relative_and_revalidates_root_parent_final(self) -> None:
        source = Path(source_authority.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
        dir_fd_opens = [
            node for node in calls
            if isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "os" and node.func.attr == "open"
            and any(item.arg == "dir_fd" for item in node.keywords)
        ]
        if os.name == "nt":
            self.assertTrue(
                all(hasattr(source_authority, name) for name in (
                    "_win_open_handle", "_win_query_handle", "_win_close_handle",
                ))
            )
        else:
            self.assertGreaterEqual(source.count("_posix_open_beneath("), 4)
            self.assertIn("O_DIRECTORY", source)
            self.assertIn("O_NOFOLLOW", source)

    def test_posix_reader_requires_openat2_beneath_no_xdev(self) -> None:
        source = Path(source_authority.__file__).read_text(encoding="utf-8")
        self.assertIn("_POSIX_RESOLVE_BENEATH", source)
        self.assertIn("_POSIX_RESOLVE_NO_XDEV", source)
        self.assertGreaterEqual(source.count("_posix_open_beneath("), 4)
        reader = inspect.getsource(source_authority._physical_read_posix)
        self.assertIn("O_NONBLOCK", reader)
        self.assertIn("os.fstat(descriptor_fd)", reader)
        self.assertIn("_read_payload(descriptor_fd)", reader)
        self.assertLess(
            reader.index("os.fstat(descriptor_fd)"),
            reader.index("_read_payload(descriptor_fd)"),
        )

    @unittest.skipIf(os.name == "nt", "POSIX FIFO semantics only")
    @unittest.skipUnless(hasattr(os, "mkfifo") and hasattr(signal, "SIGALRM"),
                         "POSIX FIFO/alarm unavailable")
    def test_posix_fifo_is_rejected_before_any_blocking_read(self) -> None:
        target = self.root / self.fixture.runtime_artifacts[0]["descriptor"]["path"]
        target.unlink()
        os.mkfifo(target)

        class BlockingFifoRead(BaseException):
            pass

        def alarm_handler(_signum: int, _frame: object) -> None:
            raise BlockingFifoRead("FIFO read blocked")

        previous = signal.signal(signal.SIGALRM, alarm_handler)
        signal.setitimer(signal.ITIMER_REAL, 0.5)
        try:
            assessment = assess_checkpoint_source_runtime_closure_authority_v1(
                self.fixture.authority,
                project_root=self.root,
                **self.fixture.expected,
            )
        except BlockingFifoRead as error:
            self.fail(str(error))
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous)
        self.assertEqual(assessment["status"], "blocked")

    @unittest.skipIf(os.name == "nt", "POSIX openat2 semantics only")
    def test_posix_bind_mount_escape_signal_is_fail_closed(self) -> None:
        with mock.patch.object(
            source_authority, "_posix_open_beneath", create=True,
            side_effect=OSError(errno.EXDEV, "injected bind mount crossing"),
        ) as opener:
            assessment = assess_checkpoint_source_runtime_closure_authority_v1(
                self.fixture.authority,
                project_root=self.root,
                **self.fixture.expected,
            )
        self.assertTrue(opener.called)
        self.assertEqual(assessment["status"], "blocked")

    @unittest.skipIf(os.name == "nt", "POSIX descriptor-relative traversal only")
    def test_posix_root_parent_and_final_rewalk_swaps_are_fail_closed(self) -> None:
        targets = (
            self.root,
            self.root / "runtime/checkpoint_source/v1/plugins",
            self.root / self.fixture.runtime_artifacts[0]["descriptor"]["path"],
        )
        for target in targets:
            with self.subTest(target=target), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                fixture = StagedClosureFixture(root)
                mapped = root if target == self.root else root / target.relative_to(self.root)
                original_open = source_authority.os.open
                original_beneath = source_authority._posix_open_beneath
                counts: Counter[str] = Counter()
                swapped = False

                def drifting_open(path: object, flags: int, *args: object,
                                  **kwargs: object) -> int:
                    nonlocal swapped
                    descriptor = original_open(path, flags, *args, **kwargs)
                    key = os.path.normcase(str(path))
                    counts[key] += 1
                    expected = os.path.normcase(
                        str(mapped if kwargs.get("dir_fd") is None else mapped.name)
                    )
                    if key == expected and counts[key] == 2:
                        swapped = True
                        os.close(descriptor)
                        raise OSError("injected path swap during rewalk")
                    return descriptor

                def drifting_beneath(parent_fd: int, name: str,
                                     flags: int) -> int:
                    nonlocal swapped
                    descriptor = original_beneath(parent_fd, name, flags)
                    counts[name] += 1
                    if name == mapped.name and counts[name] == 2:
                        swapped = True
                        os.close(descriptor)
                        raise OSError("injected relative path swap during rewalk")
                    return descriptor

                patcher = (mock.patch.object(
                    source_authority.os, "open", side_effect=drifting_open,
                ) if mapped == root else mock.patch.object(
                    source_authority, "_posix_open_beneath",
                    side_effect=drifting_beneath,
                ))
                with patcher:
                    assessment = assess_checkpoint_source_runtime_closure_authority_v1(
                        fixture.authority, project_root=root, **fixture.expected,
                    )
                self.assertTrue(swapped, target)
                self.assertEqual(assessment["status"], "blocked")

    @unittest.skipUnless(os.name == "nt", "Windows handle semantics only")
    def test_windows_root_parent_final_reparse_and_rewalk_drift_are_fail_closed(self) -> None:
        original_open = source_authority._win_open_handle
        original_relative_open = source_authority._win_open_relative_handle
        original_query = source_authority._win_query_handle
        for mutation in ("root_reparse", "parent_reparse", "final_reparse", "rewalk_id"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                fixture = StagedClosureFixture(root)
                handle_paths: dict[int, Path] = {}
                counts: Counter[str] = Counter()
                parent_paths: dict[int, Path] = {}

                def tracking_open(path: Path, *, directory: bool,
                                  read_data: bool = False) -> int:
                    handle = original_open(
                        path, directory=directory, read_data=read_data,
                    )
                    handle_paths[int(handle)] = Path(path)
                    parent_paths[int(handle)] = Path(path)
                    counts[os.path.normcase(str(path))] += 1
                    return handle

                def tracking_relative_open(
                    parent_handle: int, name: str, *, directory: bool,
                    read_data: bool = False,
                ) -> int:
                    handle = original_relative_open(
                        parent_handle, name, directory=directory,
                        read_data=read_data,
                    )
                    path = parent_paths[int(parent_handle)] / name
                    handle_paths[int(handle)] = path
                    parent_paths[int(handle)] = path
                    counts[os.path.normcase(str(path))] += 1
                    return handle

                def drifting_query(handle: int) -> dict[str, object]:
                    info = dict(original_query(handle))
                    path = handle_paths[int(handle)]
                    relative = path.relative_to(root) if path != root else Path()
                    if mutation == "root_reparse" and path == root:
                        info["file_attributes"] = int(info["file_attributes"]) | 0x400
                    elif mutation == "parent_reparse" and relative.as_posix() == "runtime":
                        info["file_attributes"] = int(info["file_attributes"]) | 0x400
                    elif mutation == "final_reparse" and path.name == "runtime-closure-manifest.json":
                        info["file_attributes"] = int(info["file_attributes"]) | 0x400
                    elif (mutation == "rewalk_id" and path == root
                          and counts[os.path.normcase(str(path))] >= 2):
                        changed = bytearray(info["file_id"])
                        changed[0] ^= 0xFF
                        info["file_id"] = bytes(changed)
                    return info

                with (
                    mock.patch.object(source_authority, "_win_open_handle",
                                      side_effect=tracking_open),
                    mock.patch.object(source_authority, "_win_open_relative_handle",
                                      side_effect=tracking_relative_open),
                    mock.patch.object(source_authority, "_win_query_handle",
                                      side_effect=drifting_query),
                ):
                    assessment = assess_checkpoint_source_runtime_closure_authority_v1(
                        fixture.authority, project_root=root, **fixture.expected,
                    )
                self.assertEqual(assessment["status"], "blocked")

    @unittest.skipUnless(os.name == "nt", "Windows handle semantics only")
    def test_windows_oversized_component_is_rejected_before_ntcreatefile(self) -> None:
        with mock.patch.object(
            source_authority, "_WIN_NT_CREATE_FILE", return_value=-1,
        ) as native_open:
            with self.assertRaises(CheckpointSourceRuntimeClosureAuthorityV1Error):
                source_authority._win_open_relative_handle(
                    1, "a" * 256, directory=False,
                )
        native_open.assert_not_called()

    @unittest.skipUnless(os.name == "nt", "Windows handle semantics only")
    def test_windows_verification_handle_cleanup_failure_is_fail_closed(self) -> None:
        real_close = source_authority._win_close_handle
        calls = 0

        def failing_once(handle: int) -> None:
            nonlocal calls
            calls += 1
            real_close(handle)
            if calls == 1:
                raise OSError("injected verification-handle cleanup failure")

        with mock.patch.object(
            source_authority, "_win_close_handle", side_effect=failing_once,
        ):
            assessment = assess_checkpoint_source_runtime_closure_authority_v1(
                self.fixture.authority,
                project_root=self.root,
                **self.fixture.expected,
            )
        self.assertGreater(calls, 1)
        self.assertEqual(assessment["status"], "blocked")

    def test_capability_guard_resolves_import_and_assignment_aliases(self) -> None:
        probes = (
            "from subprocess import run as execute\nexecute(['x'])\n",
            "import subprocess as sp\nexecute = sp.Popen\nexecute(['x'])\n",
            "import os as operating\nlaunch = operating.spawnv\nlaunch(0, 'x', [])\n",
            "from pathlib import Path\nPath('x').write_text('x')\n",
            "writer = open\nwriter('x', 'wb')\n",
            "import os\nopener = os.open\nopener('x', os.O_CREAT | os.O_WRONLY)\n",
            "import os as operating\noperating.open('x', operating.O_TRUNC | operating.O_RDWR)\n",
            "import os\nwriter = os.pwrite\nwriter(1, b'x', 0)\n",
            "import os\nos.writev(1, [b'x'])\n",
        )
        for probe in probes:
            with self.subTest(probe=probe):
                self.assertTrue(forbidden_capabilities(probe))

    def test_no_process_write_discovery_consumer_or_readiness_surface(self) -> None:
        path = Path(source_authority.__file__)
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        self.assertEqual(forbidden_capabilities(source), [])
        for token in (
            "Popen", "subprocess.run", "os.exec", "spawn", "write_text", "write_bytes",
            "mkdir", "unlink", "replace", "rename", "publication_ready",
            "accepted", "grant", "source_protocol", "source_plan", "/tmp/",
        ):
            self.assertNotIn(token, source, token)
        consumers = []
        production_roots = tuple(
            directory for directory in ROOT.iterdir()
            if directory.is_dir() and directory.name not in {
                ".git", "build", "data", "models", "registration", "runs",
                "tests", "__pycache__",
            }
        )
        text_suffixes = {
            ".py", ".pyi", ".cpp", ".cc", ".c", ".hpp", ".h", ".cmake",
            ".txt", ".md", ".sh", ".ps1", ".json", ".yaml", ".yml",
            ".toml", ".ini", ".cfg", ".xml", ".js", ".jsx", ".mjs",
            ".cjs", ".ts", ".tsx", ".java", ".kt", ".kts", ".go",
            ".rs", ".cs", ".fs", ".fsx", ".rb", ".php", ".pl",
            ".lua", ".swift", ".scala", ".html", ".htm", ".css",
            ".scss", ".less", ".bat", ".cmd",
        }
        for production_root in production_roots:
            for candidate in production_root.rglob("*"):
                if (not candidate.is_file() or candidate == path
                        or "__pycache__" in candidate.parts
                        or (candidate.suffix.casefold() not in text_suffixes
                            and candidate.name != "CMakeLists.txt"
                            and not candidate.name.startswith("Dockerfile"))):
                    continue
                try:
                    content = candidate.read_text(encoding="utf-8")
                except (UnicodeError, OSError):
                    continue
                if path.stem in content:
                    consumers.append(candidate.relative_to(ROOT).as_posix())
        for candidate in ROOT.iterdir():
            if (not candidate.is_file() or candidate == path
                    or (candidate.suffix.casefold() not in text_suffixes
                        and candidate.name != "CMakeLists.txt"
                        and not candidate.name.startswith("Dockerfile"))):
                continue
            try:
                content = candidate.read_text(encoding="utf-8")
            except (UnicodeError, OSError):
                continue
            if path.stem in content:
                consumers.append(candidate.relative_to(ROOT).as_posix())
        self.assertEqual(consumers, [])


if __name__ == "__main__":
    unittest.main()
