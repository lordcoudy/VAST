#!/usr/bin/env python3
"""Immutable, Windows-scoped protocol for future replay invocation v3."""
from __future__ import annotations

import copy
import hashlib
import json
import re
from typing import Any


SCHEMA_VERSION = 3
ARTIFACT_KIND = "vast_backend_runtime_replay_runner_invocation_protocol_v3"
CONCRETE_INVOCATION_SCHEMA_VERSION = 3
CONCRETE_INVOCATION_KIND = (
    "vast_backend_runtime_replay_runner_invocation_contract_v3"
)
RUNNER_AUTHORITY_SCHEMA_VERSION = 2
RUNNER_AUTHORITY_KIND = "vast_backend_runtime_replay_runner_authority_v2"
VALIDATOR_AUTHORITY_SCHEMA_VERSION = 1
VALIDATOR_AUTHORITY_KIND = "vast_backend_runtime_validator_authority_q4"
REQUEST_SCHEMA_VERSION = 2
REQUEST_KIND = "vast_backend_runtime_validation_replay_request_v2"
RECORD_SCHEMA_VERSION = 2
RECORD_KIND = "vast_backend_runtime_cell_validation_record_v2"
SESSION_LEASE_CHALLENGE_ABI_KIND = (
    "vast_backend_runtime_replay_session_lease_challenge_abi_v3"
)

_SHA_RE = re.compile(r"[0-9a-f]{64}")
_TOP_FIELDS = frozenset({
    "schema_version", "artifact_kind", "status", "supported_host_os",
    "concrete_invocation_header", "typed_reference_roles",
    "placeholder_roles", "session_lease_challenge_abi", "argv_template",
    "process_contract_template", "exact_false_claims", "protocol_sha256",
})

_ARGV_TEMPLATE = [
    "{interpreter_path}", "-I", "-S", "-B", "-X", "utf8",
    "{runner_path}", "--project-root", "{project_root}",
    "--session-id", "{session_id}", "--lease-id", "{lease_id}",
    "--cell-index", "{cell_index_decimal}", "--attempt-ordinal",
    "{attempt_ordinal_decimal}", "--challenge", "{challenge_sha256}",
    "--runner-authority", "{runner_authority_path}",
    "--runner-authority-file-sha256", "{runner_authority_file_sha256}",
    "--runner-authority-sha256", "{runner_authority_sha256}",
    "--validator-authority", "{validator_authority_path}",
    "--validator-authority-file-sha256", "{validator_authority_file_sha256}",
    "--validator-authority-sha256", "{validator_authority_sha256}",
    "--request", "{request_path}", "--request-file-sha256",
    "{request_file_sha256}", "--request-sha256", "{request_sha256}",
    "--expected-record", "{expected_record_path}",
    "--expected-record-file-sha256", "{expected_record_file_sha256}",
    "--expected-record-sha256", "{expected_record_sha256}",
]


class ReplayRunnerInvocationProtocolV3Error(ValueError):
    """The immutable replay invocation v3 protocol or its pin is invalid."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ReplayRunnerInvocationProtocolV3Error(message)


def _strict_json(value: Any, *, active: set[int] | None = None,
                 depth: int = 0) -> None:
    _require(depth <= 32, "replay invocation protocol JSON nesting is excessive")
    value_type = type(value)
    if value_type not in (dict, list):
        _require(value_type in (str, int, bool),
                 "replay invocation protocol contains a non-contract JSON type")
        return
    identities = set() if active is None else active
    identity = id(value)
    _require(identity not in identities,
             "replay invocation protocol contains a JSON cycle")
    identities.add(identity)
    try:
        items = value.items() if value_type is dict else enumerate(value)
        for key, item in items:
            if value_type is dict:
                _require(type(key) is str,
                         "replay invocation protocol has a non-string JSON key")
            _strict_json(item, active=identities, depth=depth + 1)
    finally:
        identities.remove(identity)


def _canonical_sha(value: object) -> str:
    _strict_json(value)
    try:
        encoded = json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as error:
        raise ReplayRunnerInvocationProtocolV3Error(
            "replay invocation protocol is not canonical JSON"
        ) from error
    return hashlib.sha256(encoded).hexdigest()


def _sha(value: Any, label: str) -> str:
    _require(type(value) is str and _SHA_RE.fullmatch(value) is not None,
             f"{label} is not a SHA-256 identity")
    return value


def _exact_type_skeleton(value: Any, expected: Any, *, path: str = "$") -> None:
    _require(type(value) is type(expected),
             f"replay invocation protocol type drifted at {path}")
    if type(expected) is dict:
        _require(set(value) == set(expected),
                 f"replay invocation protocol fields drifted at {path}")
        for key in expected:
            _exact_type_skeleton(value[key], expected[key], path=f"{path}.{key}")
    elif type(expected) is list:
        _require(len(value) == len(expected),
                 f"replay invocation protocol list drifted at {path}")
        for position, (item, expected_item) in enumerate(zip(value, expected)):
            _exact_type_skeleton(
                item, expected_item, path=f"{path}[{position}]",
            )


def _reference_roles() -> dict[str, dict[str, Any]]:
    return {
        "runner_authority": {
            "artifact_schema_version": RUNNER_AUTHORITY_SCHEMA_VERSION,
            "artifact_kind": RUNNER_AUTHORITY_KIND,
        },
        "validator_authority": {
            "artifact_schema_version": VALIDATOR_AUTHORITY_SCHEMA_VERSION,
            "artifact_kind": VALIDATOR_AUTHORITY_KIND,
        },
        "request": {
            "artifact_schema_version": REQUEST_SCHEMA_VERSION,
            "artifact_kind": REQUEST_KIND,
        },
        "expected_record": {
            "artifact_schema_version": RECORD_SCHEMA_VERSION,
            "artifact_kind": RECORD_KIND,
        },
    }


def _placeholder_roles() -> dict[str, dict[str, str]]:
    roles: dict[str, dict[str, str]] = {
        name: {"json_type": "string", "constraint": "lowercase_sha256"}
        for name in (
            "challenge_sha256", "runner_authority_file_sha256",
            "runner_authority_sha256", "validator_authority_file_sha256",
            "validator_authority_sha256", "request_file_sha256",
            "request_sha256", "expected_record_file_sha256",
            "expected_record_sha256",
        )
    }
    for name in (
        "interpreter_path", "runner_path", "runner_authority_path",
        "validator_authority_path", "request_path", "expected_record_path",
    ):
        roles[name] = {
            "json_type": "string",
            "constraint": "canonical_project_relative_path",
        }
    roles["project_root"] = {
        "json_type": "string",
        "constraint": "windows_canonical_absolute_path_v2",
    }
    for name in ("session_id", "lease_id"):
        roles[name] = {
            "json_type": "string", "constraint": "safe_token_1_to_128",
        }
    roles["cell_index_decimal"] = {
        "json_type": "string",
        "constraint": "canonical_decimal_rendering_of_strict_integer_0_to_559",
    }
    roles["attempt_ordinal_decimal"] = {
        "json_type": "string",
        "constraint": "canonical_decimal_rendering_of_strict_integer_0_to_1",
    }
    return roles


def _ack_template() -> str:
    return (
        "VAST_REPLAY_CHALLENGE_ACK_V3 {session_id} {lease_id} "
        "{cell_index_decimal} {attempt_ordinal_decimal} {challenge_sha256}\n"
    )


def _session_abi() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": SESSION_LEASE_CHALLENGE_ABI_KIND,
        "session_id": {
            "json_type": "string", "constraint": "safe_token_1_to_128",
        },
        "lease_id": {
            "json_type": "string", "constraint": "safe_token_1_to_128",
        },
        "cell_index": {
            "json_type": "strict_integer", "minimum": 0, "maximum": 559,
            "argv_rendering": "canonical_decimal",
        },
        "attempt_ordinal": {
            "json_type": "strict_integer", "minimum": 0, "maximum": 1,
            "argv_rendering": "canonical_decimal",
        },
        "challenge": {
            "json_type": "string", "constraint": "lowercase_sha256",
        },
        "acknowledgement": {
            "channel": "stderr", "framing": "exact_utf8_line",
            "template": _ack_template(), "diagnostics_allowed": False,
        },
    }


def _process_contract() -> dict[str, Any]:
    return {
        "argv_source": "exact_protocol_argv_template",
        "cwd": "{project_root}",
        "cwd_semantics": "caller_supplied_canonical_project_root",
        "env": {}, "stdin": {"mode": "devnull"},
        "stdout": {
            "channel": "stdout", "mode": "pipe",
            "purpose": "exact_canonical_validation_record_bytes_only",
            "max_bytes": 16 * 1024 * 1024,
        },
        "stderr": {
            "channel": "stderr", "mode": "pipe",
            "purpose": "challenge_acknowledgement_only",
            "framing": "exact_utf8_line",
            "expected_frame_template": _ack_template(),
            "diagnostics_allowed": False, "max_bytes": 512,
        },
        "shell": False, "check": False, "close_fds": True,
        "accepted_exit_codes": [0], "timeout_ms": 120000,
        "exit_code_handling": (
            "parent_process_metadata_validates_accepted_exit_codes"
        ),
        "failure_diagnostics_routing": "parent_process_metadata_only",
    }


def _material() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": ARTIFACT_KIND,
        "status": "immutable_protocol_contract",
        "supported_host_os": ["nt"],
        "concrete_invocation_header": {
            "schema_version": CONCRETE_INVOCATION_SCHEMA_VERSION,
            "artifact_kind": CONCRETE_INVOCATION_KIND,
            "status": "declarative_replay_invocation_candidate",
        },
        "typed_reference_roles": _reference_roles(),
        "placeholder_roles": _placeholder_roles(),
        "session_lease_challenge_abi": _session_abi(),
        "argv_template": list(_ARGV_TEMPLATE),
        "process_contract_template": _process_contract(),
        "exact_false_claims": {
            "atomic_runtime_closure_snapshot_validated": False,
            "lease_enforcement_validated": False,
            "sandbox_enforcement_validated": False,
            "challenge_freshness_validated": False,
            "process_executed": False,
            "validation_records_authenticated": False,
            "execution_authorized": False,
        },
    }


def replay_runner_invocation_protocol_v3_contract() -> dict[str, Any]:
    """Return a fresh copy of the immutable, non-authorizing protocol."""
    value = _material()
    value["protocol_sha256"] = _canonical_sha(value)
    return copy.deepcopy(value)


def validate_replay_runner_invocation_protocol_v3_contract(
    value: Any, *, expected_protocol_sha256: str,
) -> dict[str, Any]:
    """Validate exact protocol material against a mandatory external pin."""
    pin = _sha(expected_protocol_sha256, "expected replay protocol v3")
    _strict_json(value)
    _require(type(value) is dict and set(value) == _TOP_FIELDS,
             "replay invocation protocol fields drifted")
    expected = replay_runner_invocation_protocol_v3_contract()
    _exact_type_skeleton(value, expected)
    observed = _sha(value.get("protocol_sha256"), "replay protocol v3")
    unsigned = {key: copy.deepcopy(item) for key, item in value.items()
                if key != "protocol_sha256"}
    expected_unsigned = {
        key: copy.deepcopy(item) for key, item in expected.items()
        if key != "protocol_sha256"
    }
    _require(_canonical_sha(unsigned) == _canonical_sha(expected_unsigned),
             "replay invocation protocol material drifted")
    _require(observed == _canonical_sha(unsigned) == pin,
             "replay invocation protocol semantic identity drifted")
    return copy.deepcopy(value)


__all__ = [
    "SCHEMA_VERSION", "ARTIFACT_KIND", "CONCRETE_INVOCATION_SCHEMA_VERSION",
    "CONCRETE_INVOCATION_KIND", "RUNNER_AUTHORITY_SCHEMA_VERSION",
    "RUNNER_AUTHORITY_KIND", "VALIDATOR_AUTHORITY_SCHEMA_VERSION",
    "VALIDATOR_AUTHORITY_KIND", "REQUEST_SCHEMA_VERSION", "REQUEST_KIND",
    "RECORD_SCHEMA_VERSION", "RECORD_KIND",
    "SESSION_LEASE_CHALLENGE_ABI_KIND",
    "ReplayRunnerInvocationProtocolV3Error",
    "replay_runner_invocation_protocol_v3_contract",
    "validate_replay_runner_invocation_protocol_v3_contract",
]
