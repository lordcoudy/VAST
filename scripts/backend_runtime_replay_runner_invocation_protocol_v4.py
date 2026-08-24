#!/usr/bin/env python3
"""Immutable, non-authorizing Windows native-broker replay protocol v4."""
from __future__ import annotations

import copy
import hashlib
import json
import re
from typing import Any


SCHEMA_VERSION = 4
ARTIFACT_KIND = "vast_backend_runtime_replay_runner_invocation_protocol_v4"
CONCRETE_INVOCATION_SCHEMA_VERSION = 4
CONCRETE_INVOCATION_KIND = (
    "vast_backend_runtime_replay_runner_invocation_contract_v4"
)
NATIVE_BROKER_ABI_KIND = "vast_backend_runtime_replay_native_broker_abi_v4"
CHILD_HANDLE_MAP_ABI_KIND = (
    "vast_backend_runtime_replay_inherited_handle_map_abi_v4"
)
CHALLENGE_CHANNEL_ABI_KIND = (
    "vast_backend_runtime_replay_challenge_channel_abi_v4"
)
ACKNOWLEDGEMENT_ABI_KIND = (
    "vast_backend_runtime_replay_acknowledgement_abi_v4"
)
RUNNER_AUTHORITY_SCHEMA_VERSION = 3
RUNNER_AUTHORITY_KIND = "vast_backend_runtime_replay_runner_authority_v3"
VALIDATOR_AUTHORITY_SCHEMA_VERSION = 1
VALIDATOR_AUTHORITY_KIND = "vast_backend_runtime_validator_authority_q4"
REQUEST_SCHEMA_VERSION = 2
REQUEST_KIND = "vast_backend_runtime_validation_replay_request_v2"
RECORD_SCHEMA_VERSION = 2
RECORD_KIND = "vast_backend_runtime_cell_validation_record_v2"

_PROTOCOL_DOMAIN = (
    b"VAST:backend-runtime-replay-runner-invocation-protocol:v4\0"
)
_SHA_RE = re.compile(r"[0-9a-f]{64}")
_TOP_FIELDS = frozenset({
    "schema_version", "artifact_kind", "status", "supported_host_os",
    "supported_host_architecture", "concrete_invocation_header",
    "semantic_identity_roles", "placeholder_roles", "native_broker_abi",
    "child_handle_map_abi", "challenge_channel_abi",
    "acknowledgement_abi", "argv_template", "process_contract_template",
    "parent_only_expected_record_policy", "hash_domains",
    "exact_false_claims", "protocol_sha256",
})

_HANDLE_ROLES = (
    "runner_entrypoint_read",
    "runner_authority_read",
    "validator_authority_read",
    "validation_request_read",
    "raw_evidence_read",
    "runtime_closure_bundle_read",
    "challenge_read",
    "stdin_eof_read",
    "record_stdout_write",
    "acknowledgement_stderr_write",
)
_HANDLE_MAP_GRAMMAR = (
    "hmap4;runner_entrypoint_read={u64};runner_authority_read={u64};"
    "validator_authority_read={u64};validation_request_read={u64};"
    "raw_evidence_read={u64};runtime_closure_bundle_read={u64};"
    "challenge_read={u64};stdin_eof_read={u64};"
    "record_stdout_write={u64};acknowledgement_stderr_write={u64}"
)
_ARGV_TEMPLATE = [
    "vast-replay-native-runner-v4",
    "--protocol-sha256", "{protocol_sha256}",
    "--project-root-identity-sha256", "{project_root_identity_sha256}",
    "--session-id", "{session_id}",
    "--lease-id", "{lease_id}",
    "--cell-index", "{cell_index_decimal}",
    "--attempt-ordinal", "{attempt_ordinal_decimal}",
    "--runner-authority-sha256", "{runner_authority_sha256}",
    "--validator-authority-sha256", "{validator_authority_sha256}",
    "--request-sha256", "{request_sha256}",
    "--handle-map", "{handle_map_descriptor}",
]
_ACK_TEMPLATE = (
    "VAST_REPLAY_ACK_V4 {session_id} {lease_id} "
    "{cell_index_decimal} {attempt_ordinal_decimal} "
    "{nonce_sha256} {stdout_sha256} {protocol_sha256}\n"
)


class ReplayRunnerInvocationProtocolV4Error(ValueError):
    """The replay invocation protocol v4 or its external pin is invalid."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ReplayRunnerInvocationProtocolV4Error(message)


def _strict_json(
    value: Any, *, active: set[int] | None = None, depth: int = 0,
) -> None:
    _require(depth <= 32, "replay protocol v4 JSON nesting is excessive")
    value_type = type(value)
    if value_type not in (dict, list):
        _require(
            value_type in (str, int, bool),
            "replay protocol v4 contains a non-contract JSON type",
        )
        return
    identities = set() if active is None else active
    identity = id(value)
    _require(identity not in identities,
             "replay protocol v4 contains a JSON cycle")
    identities.add(identity)
    try:
        items = value.items() if value_type is dict else enumerate(value)
        for key, item in items:
            if value_type is dict:
                _require(type(key) is str,
                         "replay protocol v4 has a non-string JSON key")
            _strict_json(item, active=identities, depth=depth + 1)
    finally:
        identities.remove(identity)


def _canonical_bytes(value: object) -> bytes:
    _strict_json(value)
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as error:
        raise ReplayRunnerInvocationProtocolV4Error(
            "replay protocol v4 is not canonical JSON"
        ) from error


def _protocol_sha(value: object) -> str:
    return hashlib.sha256(_PROTOCOL_DOMAIN + _canonical_bytes(value)).hexdigest()


def _sha(value: Any, label: str) -> str:
    _require(type(value) is str and _SHA_RE.fullmatch(value) is not None,
             f"{label} is not a lowercase SHA-256 identity")
    return value


def _exact_type_skeleton(value: Any, expected: Any, *, path: str = "$") -> None:
    _require(type(value) is type(expected),
             f"replay protocol v4 type drifted at {path}")
    if type(expected) is dict:
        _require(set(value) == set(expected),
                 f"replay protocol v4 fields drifted at {path}")
        for key in expected:
            _exact_type_skeleton(value[key], expected[key], path=f"{path}.{key}")
    elif type(expected) is list:
        _require(len(value) == len(expected),
                 f"replay protocol v4 list drifted at {path}")
        for position, (item, expected_item) in enumerate(zip(value, expected)):
            _exact_type_skeleton(
                item, expected_item, path=f"{path}[{position}]",
            )


def _semantic_identity_roles() -> dict[str, dict[str, Any]]:
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
    }


def _placeholder_roles() -> dict[str, dict[str, str]]:
    roles = {
        name: {"json_type": "string", "constraint": "lowercase_sha256"}
        for name in (
            "protocol_sha256", "project_root_identity_sha256",
            "runner_authority_sha256", "validator_authority_sha256",
            "request_sha256",
        )
    }
    for name in ("session_id", "lease_id"):
        roles[name] = {
            "json_type": "string", "constraint": "safe_token_1_to_128",
        }
    roles["cell_index_decimal"] = {
        "json_type": "string",
        "constraint": "canonical_decimal_strict_integer_0_to_559",
    }
    roles["attempt_ordinal_decimal"] = {
        "json_type": "string",
        "constraint": "canonical_decimal_strict_integer_0_to_1",
    }
    roles["handle_map_descriptor"] = {
        "json_type": "string",
        "constraint": "exact_ephemeral_child_handle_map_abi_v4_grammar",
    }
    return roles


def _external_pin_policy() -> dict[str, Any]:
    return {
        "source": "mandatory_external_pin",
        "identity_type": "lowercase_sha256",
        "accepted_artifact_schema": "not_declared_by_protocol_v4",
        "required_binding_scopes": ["concrete_invocation", "session_lease"],
        "inferred_from_protocol": False,
        "child_exposure": "forbidden",
    }


def _native_broker_abi() -> dict[str, Any]:
    external_pins = {
        name: _external_pin_policy()
        for name in (
            "broker_authority_semantic_sha256", "handle_abi_sha256",
            "wfp_policy_sha256", "filesystem_minifilter_policy_sha256",
        )
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": NATIVE_BROKER_ABI_KIND,
        "host_os": "nt",
        "host_architecture": "amd64",
        "process_creation": {
            "api": "CreateProcessW",
            "creation_flags": [
                "CREATE_SUSPENDED", "EXTENDED_STARTUPINFO_PRESENT",
            ],
            "bInheritHandles": True,
            "attribute_handle_allowlist": (
                "exact_PROC_THREAD_ATTRIBUTE_HANDLE_LIST"
            ),
            "attribute_handle_allowlist_members": (
                "exactly_all_ten_ordered_handle_map_roles"
            ),
            "standard_handle_binding": {
                "STARTF_USESTDHANDLES": True,
                "hStdInput": "stdin_eof_read",
                "hStdOutput": "record_stdout_write",
                "hStdError": "acknowledgement_stderr_write",
            },
            "ambient_inheritable_handles": "forbidden",
            "native_image": {
                "lpApplicationName_custody": "parent_private",
                "selection_authority": (
                    "future_externally_pinned_broker_runner_authority_only"
                ),
                "logical_argv0_is_authority": False,
                "child_argv_contains_native_image_path": False,
            },
        },
        "normative_states": [
            "PREPARED", "SEALED", "CHILD_CREATED_SUSPENDED",
            "CHALLENGE_WRITTEN", "RUNNING", "COLLECTED", "PARENT_VERIFIED",
        ],
        "normative_transitions": [
            "PREPARED_TO_SEALED",
            "SEALED_TO_CHILD_CREATED_SUSPENDED",
            "CHILD_CREATED_SUSPENDED_TO_CHALLENGE_WRITTEN",
            "CHALLENGE_WRITTEN_TO_RUNNING",
            "RUNNING_TO_COLLECTED",
            "COLLECTED_TO_PARENT_VERIFIED",
        ],
        "sealed_state": {
            "child_inputs": "preopened_verified_and_handle_bound",
            "child_input_mutation": "forbidden",
            "child_path_reopen_after_sealed": "forbidden",
            "project_root_child_visibility": "semantic_identity_sha256_only",
            "project_root_path_or_directory_handle_child_visibility": (
                "forbidden"
            ),
            "runtime_closure_visibility": (
                "single_immutable_bundle_read_handle_only"
            ),
        },
        "mandatory_parent_only_external_identity_pins": external_pins,
        "pure_protocol_scope": {
            "implements_broker": False,
            "accepts_concrete_external_pin_values": False,
            "confers_authority": False,
        },
    }


def _handle_role(role: str) -> dict[str, str]:
    objects = {
        "runner_entrypoint_read": "sealed_native_runner_entrypoint_artifact",
        "runner_authority_read": "sealed_runner_authority_artifact",
        "validator_authority_read": "sealed_validator_authority_artifact",
        "validation_request_read": "sealed_validation_request_artifact",
        "raw_evidence_read": "sealed_raw_evidence_artifact",
        "runtime_closure_bundle_read": (
            "single_immutable_broker_validated_bundle_artifact"
        ),
        "challenge_read": "one_shot_anonymous_pipe_read_endpoint",
        "stdin_eof_read": "anonymous_pipe_read_endpoint_for_immediate_eof",
        "record_stdout_write": (
            "anonymous_pipe_write_endpoint_for_exact_record_bytes"
        ),
        "acknowledgement_stderr_write": (
            "anonymous_pipe_write_endpoint_for_exact_acknowledgement_line"
        ),
    }
    access = (
        "write_only" if role in {
            "record_stdout_write", "acknowledgement_stderr_write",
        } else "read_only"
    )
    return {
        "role": role,
        "access": access,
        "object": objects[role],
        "namespace_semantics": (
            "not_a_namespace" if role == "runtime_closure_bundle_read"
            else "no_path_namespace"
        ),
        "custody": "broker_created_or_broker_validated_inherited_handle",
    }


def _child_handle_map_abi() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": CHILD_HANDLE_MAP_ABI_KIND,
        "ordered_roles": [_handle_role(role) for role in _HANDLE_ROLES],
        "runtime_representation": {
            "grammar_template": _HANDLE_MAP_GRAMMAR,
            "exact_role_count": 10,
            "number_encoding": "canonical_unsigned_decimal_u64",
            "minimum": 1,
            "maximum": 18446744073709551615,
            "pseudo_handles": "forbidden",
            "pairwise_distinct": True,
            "process_local_only": True,
            "persisted": False,
            "semantic_hash_input": False,
            "logging": "forbidden",
        },
        "inheritance": {
            "allowlist_api": "PROC_THREAD_ATTRIBUTE_HANDLE_LIST",
            "input_handle_allowlist": "exactly_all_ten_ordered_roles",
            "ambient_handle_inheritance": "forbidden",
            "prepared_before_state": "SEALED",
            "child_path_reopen": "forbidden",
        },
        "standard_handle_mapping": {
            "STARTF_USESTDHANDLES": True,
            "hStdInput": "stdin_eof_read",
            "hStdOutput": "record_stdout_write",
            "hStdError": "acknowledgement_stderr_write",
            "stdin_eof_parent_action": (
                "close_parent_private_complementary_writer_before_resume"
            ),
            "stdin_child_observation": "immediate_eof",
        },
        "parent_private_complementary_handles": [
            "challenge_write", "stdin_eof_write", "record_stdout_read",
            "acknowledgement_stderr_read",
        ],
        "parent_private_complementary_handle_inheritance": "forbidden",
        "parent_private_complementary_handle_map_membership": "forbidden",
        "protocol_persistence": {
            "stores_role_order": True,
            "stores_grammar": True,
            "stores_constraints": True,
            "stores_process_local_handle_numbers": False,
        },
    }


def validate_replay_runner_child_handle_map_v4_descriptor(
    value: Any,
) -> dict[str, int]:
    """Validate one ephemeral exact-role handle-map argv token."""
    _require(type(value) is str,
             "replay protocol v4 handle map must be a string")
    fields = value.split(";")
    _require(len(fields) == len(_HANDLE_ROLES) + 1 and fields[0] == "hmap4",
             "replay protocol v4 handle map framing drifted")
    observed: dict[str, int] = {}
    for position, role in enumerate(_HANDLE_ROLES, start=1):
        field = fields[position]
        expected_prefix = f"{role}="
        _require(field.startswith(expected_prefix),
                 "replay protocol v4 handle role/order drifted")
        rendered = field[len(expected_prefix):]
        _require(
            re.fullmatch(r"[1-9][0-9]{0,19}", rendered) is not None,
            "replay protocol v4 handle is not canonical nonzero u64",
        )
        number = int(rendered)
        _require(number <= 18446744073709551615,
                 "replay protocol v4 handle exceeds u64")
        _require(number not in {
            18446744073709551612, 18446744073709551613,
            18446744073709551614, 18446744073709551615,
        }, "replay protocol v4 pseudo handle is forbidden")
        _require(number not in observed.values(),
                 "replay protocol v4 handles are not pairwise distinct")
        observed[role] = number
    _require(len(observed) == 10,
             "replay protocol v4 handle role count drifted")
    return copy.deepcopy(observed)


def _challenge_channel_abi() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": CHALLENGE_CHANNEL_ABI_KIND,
        "transport": "one_shot_anonymous_pipe",
        "child_handle_role": "challenge_read",
        "raw_nonce_bytes": 32,
        "nonce_generation_state": "CHILD_CREATED_SUSPENDED",
        "write_completion_state": "CHALLENGE_WRITTEN",
        "resume_allowed_after": "CHALLENGE_WRITTEN",
        "parent_writer_action": "write_exact_32_bytes_then_close",
        "child_reader_action": "read_exact_32_bytes_then_require_eof",
        "raw_nonce_in_argv": False,
        "raw_nonce_in_environment": False,
        "raw_nonce_persisted": False,
        "raw_nonce_logged": False,
        "commitment_output": (
            "nonce_sha256_equals_"
            "sha256_domain_prefix_then_exact_bytes"
        ),
    }


def _acknowledgement_abi() -> dict[str, Any]:
    computation = {
        "nonce_sha256": {
            "hash_domain": "nonce_commitment",
            "algorithm": "sha256_domain_prefix_then_exact_bytes",
            "input": "exact_32_raw_nonce_bytes",
        },
        "stdout_sha256": {
            "hash_domain": "stdout_commitment",
            "algorithm": "sha256_domain_prefix_then_exact_bytes",
            "input": "exact_collected_stdout_bytes",
        },
        "protocol_sha256": {
            "hash_domain": "protocol_identity",
            "algorithm": "sha256_domain_prefix_then_canonical_json_utf8",
            "input": "unsigned_protocol_contract",
        },
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": ACKNOWLEDGEMENT_ABI_KIND,
        "channel": "dedicated_broker_captured_acknowledgement_stream",
        "framing": "exact_utf8_line",
        "template": _ACK_TEMPLATE,
        "diagnostics_allowed": False,
        "producer_computation": copy.deepcopy(computation),
        "parent_verification": copy.deepcopy(computation),
        "parent_verification_mode": (
            "independently_recompute_exact_producer_computation"
        ),
        "accepted_only_after_state": "COLLECTED",
        "transcript_domain": "VAST_REPLAY_ACK_V4",
    }


def _process_contract() -> dict[str, Any]:
    return {
        "argv_source": "exact_protocol_argv_template",
        "logical_argv0_semantics": "identifier_only_not_execution_authority",
        "native_image_selection": "parent_private_future_authority_binding",
        "working_directory": "broker_private_non_project_sandbox_root",
        "working_directory_is_semantic_input": False,
        "environment": {},
        "stdin": {
            "mode": "inherited_pipe_read_immediate_eof",
            "child_handle_role": "stdin_eof_read",
            "parent_action": (
                "close_parent_private_complementary_writer_before_resume"
            ),
        },
        "stdout": {
            "channel": "broker_owned_pipe",
            "child_handle_role": "record_stdout_write",
            "parent_private_complementary_handle": "record_stdout_read",
            "mode": "exact_bytes",
            "purpose": "exact_canonical_validation_record_bytes_only",
            "max_bytes": 16 * 1024 * 1024,
        },
        "acknowledgement": {
            "channel": "broker_owned_pipe",
            "child_handle_role": "acknowledgement_stderr_write",
            "parent_private_complementary_handle": (
                "acknowledgement_stderr_read"
            ),
            "mode": "exact_utf8_line",
            "purpose": "acknowledgement_abi_v4_frame_only",
            "diagnostics_allowed": False,
            "max_bytes": 512,
        },
        "shell": False,
        "check": False,
        "close_fds": True,
        "accepted_exit_codes": [0],
        "timeout_ms": 120000,
        "exit_code_handling": "parent_validates_after_collection",
        "failure_diagnostics_routing": "parent_private_metadata_only",
    }


def _parent_only_expected_record_policy() -> dict[str, Any]:
    return {
        "artifact_schema_version": RECORD_SCHEMA_VERSION,
        "artifact_kind": RECORD_KIND,
        "custody": "parent_only",
        "child_visibility": "forbidden",
        "parent_required_material": [
            "typed_expected_record_ref", "expected_record_semantic_sha256",
            "expected_record_file_sha256", "held_expected_record_bytes",
        ],
        "parent_precondition": (
            "opened_verified_and_held_before_child_creation"
        ),
        "forbidden_child_material": [
            "expected_record_path", "expected_record_ref",
            "expected_record_semantic_sha256", "expected_record_file_sha256",
            "expected_record_handle", "expected_record_bytes",
        ],
        "forbidden_child_surfaces": [
            "argv", "environment", "semantic_identity_roles",
            "inherited_handle_map", "acknowledgement_inputs",
        ],
        "comparison": "byte_for_byte_against_exact_collected_stdout",
        "comparison_state": "PARENT_VERIFIED",
        "comparison_preconditions": [
            "accepted_exit_code", "exact_acknowledgement_verified",
            "stdout_sha256_independently_verified",
        ],
        "comparison_result_authorizes_execution": False,
    }


def _hash_domains() -> dict[str, dict[str, str]]:
    return {
        "protocol_identity": {
            "domain_prefix_ascii": (
                "VAST:backend-runtime-replay-runner-invocation-protocol:v4"
            ),
            "domain_separator_hex": "00",
            "prefix_byte_encoding": "strict_ascii_then_single_nul",
            "algorithm": "sha256_domain_prefix_then_canonical_json_utf8",
            "input": "unsigned_protocol_contract",
        },
        "project_root_identity": {
            "domain_prefix_ascii": (
                "VAST:backend-runtime-replay-project-root-identity:v4"
            ),
            "domain_separator_hex": "00",
            "prefix_byte_encoding": "strict_ascii_then_single_nul",
            "algorithm": "sha256_domain_prefix_then_exact_bytes",
            "input": "exact_parent_private_project_root_identity_bytes",
        },
        "nonce_commitment": {
            "domain_prefix_ascii": (
                "VAST:backend-runtime-replay-nonce-commitment:v4"
            ),
            "domain_separator_hex": "00",
            "prefix_byte_encoding": "strict_ascii_then_single_nul",
            "algorithm": "sha256_domain_prefix_then_exact_bytes",
            "input": "exact_32_raw_nonce_bytes",
        },
        "stdout_commitment": {
            "domain_prefix_ascii": (
                "VAST:backend-runtime-replay-stdout-commitment:v4"
            ),
            "domain_separator_hex": "00",
            "prefix_byte_encoding": "strict_ascii_then_single_nul",
            "algorithm": "sha256_domain_prefix_then_exact_bytes",
            "input": "exact_collected_stdout_bytes",
        },
        "acknowledgement_transcript": {
            "frame_prefix_ascii": "VAST_REPLAY_ACK_V4",
            "frame_prefix_byte_encoding": "strict_ascii",
            "algorithm": "exact_space_delimited_utf8_line",
            "input": "acknowledgement_abi_v4_ordered_fields",
        },
    }


def _false_claims() -> dict[str, bool]:
    return {
        "atomic_runtime_closure_snapshot_validated": False,
        "inherited_handle_allowlist_validated": False,
        "standard_handle_mapping_validated": False,
        "handle_sealing_validated": False,
        "child_path_reopen_prevented": False,
        "native_broker_implemented": False,
        "broker_state_machine_enforced": False,
        "challenge_delivery_validated": False,
        "challenge_freshness_validated": False,
        "stdout_integrity_validated": False,
        "lease_enforcement_validated": False,
        "sandbox_enforcement_validated": False,
        "process_executed": False,
        "validation_records_authenticated": False,
        "execution_authorized": False,
        "expected_record_parent_isolation_validated": False,
        "native_image_handle_binding_validated": False,
        "filesystem_write_policy_enforced": False,
        "network_policy_enforced": False,
    }


def _material() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": ARTIFACT_KIND,
        "status": "immutable_protocol_contract",
        "supported_host_os": ["nt"],
        "supported_host_architecture": ["amd64"],
        "concrete_invocation_header": {
            "schema_version": CONCRETE_INVOCATION_SCHEMA_VERSION,
            "artifact_kind": CONCRETE_INVOCATION_KIND,
            "status": "declarative_native_broker_invocation_candidate",
        },
        "semantic_identity_roles": _semantic_identity_roles(),
        "placeholder_roles": _placeholder_roles(),
        "native_broker_abi": _native_broker_abi(),
        "child_handle_map_abi": _child_handle_map_abi(),
        "challenge_channel_abi": _challenge_channel_abi(),
        "acknowledgement_abi": _acknowledgement_abi(),
        "argv_template": list(_ARGV_TEMPLATE),
        "process_contract_template": _process_contract(),
        "parent_only_expected_record_policy": (
            _parent_only_expected_record_policy()
        ),
        "hash_domains": _hash_domains(),
        "exact_false_claims": _false_claims(),
    }


def replay_runner_invocation_protocol_v4_contract() -> dict[str, Any]:
    """Return a fresh copy of the pure, non-authorizing protocol contract."""
    value = _material()
    value["protocol_sha256"] = _protocol_sha(value)
    return copy.deepcopy(value)


def validate_replay_runner_invocation_protocol_v4_contract(
    value: Any, *, expected_protocol_sha256: str,
) -> dict[str, Any]:
    """Validate exact protocol material against a mandatory external pin."""
    pin = _sha(expected_protocol_sha256, "expected replay protocol v4")
    _strict_json(value)
    _require(type(value) is dict and set(value) == _TOP_FIELDS,
             "replay protocol v4 fields drifted")
    expected = replay_runner_invocation_protocol_v4_contract()
    _exact_type_skeleton(value, expected)
    observed = _sha(value.get("protocol_sha256"), "replay protocol v4")
    unsigned = {
        key: copy.deepcopy(item) for key, item in value.items()
        if key != "protocol_sha256"
    }
    expected_unsigned = {
        key: copy.deepcopy(item) for key, item in expected.items()
        if key != "protocol_sha256"
    }
    actual_unsigned_sha = _protocol_sha(unsigned)
    _require(actual_unsigned_sha == _protocol_sha(expected_unsigned),
             "replay protocol v4 material drifted")
    _require(observed == actual_unsigned_sha == pin,
             "replay protocol v4 semantic identity drifted")
    return copy.deepcopy(value)


__all__ = [
    "SCHEMA_VERSION", "ARTIFACT_KIND",
    "CONCRETE_INVOCATION_SCHEMA_VERSION", "CONCRETE_INVOCATION_KIND",
    "NATIVE_BROKER_ABI_KIND", "CHILD_HANDLE_MAP_ABI_KIND",
    "CHALLENGE_CHANNEL_ABI_KIND", "ACKNOWLEDGEMENT_ABI_KIND",
    "RUNNER_AUTHORITY_SCHEMA_VERSION", "RUNNER_AUTHORITY_KIND",
    "VALIDATOR_AUTHORITY_SCHEMA_VERSION", "VALIDATOR_AUTHORITY_KIND",
    "REQUEST_SCHEMA_VERSION", "REQUEST_KIND", "RECORD_SCHEMA_VERSION",
    "RECORD_KIND", "ReplayRunnerInvocationProtocolV4Error",
    "replay_runner_invocation_protocol_v4_contract",
    "validate_replay_runner_child_handle_map_v4_descriptor",
    "validate_replay_runner_invocation_protocol_v4_contract",
]
