#!/usr/bin/env python3
"""Pure, closed, non-authorizing publication launcher invocation ABI v3."""
from __future__ import annotations

import copy
import hashlib
import json
from typing import Any


SCHEMA_VERSION = 3
ARTIFACT_KIND = "vast_backend_publication_launcher_invocation_v3"
INVOCATION_SCHEMA_VERSION = SCHEMA_VERSION
INVOCATION_KIND = ARTIFACT_KIND
PUBLICATION_LAUNCHER_INVOCATION_V3_SCHEMA_VERSION = SCHEMA_VERSION
PUBLICATION_LAUNCHER_INVOCATION_V3_KIND = ARTIFACT_KIND
RUNTIME_KIND = "python3_caller_bound_argv_v3"
INPUT_PROTOCOL_DOMAIN = "vast-full-publication-arm-contract-json-v3"
OUTPUT_PROTOCOL_DOMAIN = "vast-full-publication-arm-output-receipt-json-v3"
INPUT_PROTOCOL_IDENTITY_SHA256 = hashlib.sha256(
    INPUT_PROTOCOL_DOMAIN.encode("ascii")
).hexdigest()
OUTPUT_PROTOCOL_IDENTITY_SHA256 = hashlib.sha256(
    OUTPUT_PROTOCOL_DOMAIN.encode("ascii")
).hexdigest()
PROCESS_TIMEOUT_MS = 600000
MAX_STDOUT_BYTES = 1024 * 1024
MAX_STDERR_BYTES = 1024 * 1024
ARGV_TEMPLATE = (
    "{python_executable}",
    "{launcher_path}",
    "--project-root",
    "{project_root}",
    "--arm-contract",
    "{arm_contract_path}",
    "--arm-contract-sha256",
    "{arm_contract_file_sha256}",
    "--output-dir",
    "{output_dir}",
)
REQUIRED_ENV_KEYS: tuple[str, ...] = ()
_PROCESS_FIELDS = frozenset({
    "shell", "check", "environment", "cwd_source", "stdin", "stdout",
    "stderr", "close_fds", "accepted_exit_codes",
    "accepted_exit_code_semantics", "timeout_ms", "max_stdout_bytes",
    "max_stderr_bytes",
})
_INVOCATION_FIELDS = frozenset({
    "schema_version", "artifact_kind", "runtime_kind", "argv_template",
    "required_env_keys", "process_contract",
    "input_protocol_identity_sha256", "output_protocol_identity_sha256",
    "execution_authorized", "invocation_sha256",
})


class BackendPublicationLauncherInvocationV3Error(ValueError):
    """The declarative publication launcher ABI v3 is not exact."""


def _canonical_sha(value: object) -> str:
    try:
        payload = json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as error:
        raise BackendPublicationLauncherInvocationV3Error(
            "publication launcher invocation v3 is not canonical JSON"
        ) from error
    return hashlib.sha256(payload).hexdigest()


def publication_launcher_invocation_v3_contract() -> dict[str, Any]:
    """Return the one declarative, caller-bound publication launcher ABI v3."""

    value: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": ARTIFACT_KIND,
        "runtime_kind": RUNTIME_KIND,
        "argv_template": list(ARGV_TEMPLATE),
        "required_env_keys": list(REQUIRED_ENV_KEYS),
        "process_contract": {
            "shell": False,
            "check": False,
            "environment": {},
            "cwd_source": "caller_supplied_canonical_project_root",
            "stdin": "DEVNULL",
            "stdout": "bounded_capture_pipe",
            "stderr": "bounded_capture_pipe",
            "close_fds": True,
            "accepted_exit_codes": [0],
            "accepted_exit_code_semantics": (
                "launcher_success_only_receipt_finalization_is_separate"
            ),
            "timeout_ms": PROCESS_TIMEOUT_MS,
            "max_stdout_bytes": MAX_STDOUT_BYTES,
            "max_stderr_bytes": MAX_STDERR_BYTES,
        },
        "input_protocol_identity_sha256": INPUT_PROTOCOL_IDENTITY_SHA256,
        "output_protocol_identity_sha256": OUTPUT_PROTOCOL_IDENTITY_SHA256,
        "execution_authorized": False,
    }
    value["invocation_sha256"] = _canonical_sha(value)
    return value


def validate_publication_launcher_invocation_v3(value: Any) -> dict[str, Any]:
    """Accept only the exact v3 ABI; a valid declaration authorizes nothing."""

    if type(value) is not dict or set(value) != _INVOCATION_FIELDS:
        raise BackendPublicationLauncherInvocationV3Error(
            "publication launcher invocation v3 fields drifted"
        )
    process = value.get("process_contract")
    if type(process) is not dict or set(process) != _PROCESS_FIELDS:
        raise BackendPublicationLauncherInvocationV3Error(
            "publication launcher invocation v3 process fields drifted"
        )
    if (
        type(value.get("schema_version")) is not int
        or type(value.get("artifact_kind")) is not str
        or type(value.get("runtime_kind")) is not str
        or type(value.get("argv_template")) is not list
        or any(type(item) is not str for item in value["argv_template"])
        or type(value.get("required_env_keys")) is not list
        or any(type(item) is not str for item in value["required_env_keys"])
        or type(value.get("input_protocol_identity_sha256")) is not str
        or type(value.get("output_protocol_identity_sha256")) is not str
        or type(value.get("execution_authorized")) is not bool
        or type(value.get("invocation_sha256")) is not str
        or type(process.get("shell")) is not bool
        or type(process.get("check")) is not bool
        or type(process.get("environment")) is not dict
        or any(
            type(key) is not str or type(item) is not str
            for key, item in process["environment"].items()
        )
        or type(process.get("cwd_source")) is not str
        or type(process.get("stdin")) is not str
        or type(process.get("stdout")) is not str
        or type(process.get("stderr")) is not str
        or type(process.get("close_fds")) is not bool
        or type(process.get("accepted_exit_codes")) is not list
        or any(type(item) is not int for item in process["accepted_exit_codes"])
        or type(process.get("accepted_exit_code_semantics")) is not str
        or type(process.get("timeout_ms")) is not int
        or type(process.get("max_stdout_bytes")) is not int
        or type(process.get("max_stderr_bytes")) is not int
    ):
        raise BackendPublicationLauncherInvocationV3Error(
            "publication launcher invocation v3 JSON types drifted"
        )
    expected = publication_launcher_invocation_v3_contract()
    unsigned = {key: item for key, item in value.items()
                if key != "invocation_sha256"}
    if value["invocation_sha256"] != _canonical_sha(unsigned) or value != expected:
        raise BackendPublicationLauncherInvocationV3Error(
            "publication launcher invocation v3 contract drifted"
        )
    return copy.deepcopy(expected)


__all__ = [
    "ARTIFACT_KIND",
    "ARGV_TEMPLATE",
    "BackendPublicationLauncherInvocationV3Error",
    "INPUT_PROTOCOL_DOMAIN",
    "INPUT_PROTOCOL_IDENTITY_SHA256",
    "INVOCATION_KIND",
    "INVOCATION_SCHEMA_VERSION",
    "MAX_STDERR_BYTES",
    "MAX_STDOUT_BYTES",
    "OUTPUT_PROTOCOL_DOMAIN",
    "OUTPUT_PROTOCOL_IDENTITY_SHA256",
    "PROCESS_TIMEOUT_MS",
    "PUBLICATION_LAUNCHER_INVOCATION_V3_KIND",
    "PUBLICATION_LAUNCHER_INVOCATION_V3_SCHEMA_VERSION",
    "REQUIRED_ENV_KEYS",
    "RUNTIME_KIND",
    "SCHEMA_VERSION",
    "publication_launcher_invocation_v3_contract",
    "validate_publication_launcher_invocation_v3",
]
