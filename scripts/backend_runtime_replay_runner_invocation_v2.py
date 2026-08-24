#!/usr/bin/env python3
"""Pure declarative challenge-bound replay runner invocation candidate."""
from __future__ import annotations

import copy
import hashlib
import json
import re
from typing import Any, Mapping


SCHEMA_VERSION = 2
ARTIFACT_KIND = "vast_backend_runtime_replay_runner_invocation_contract_v2"
RUNNER_AUTHORITY_SCHEMA_VERSION = 1
RUNNER_AUTHORITY_KIND = "vast_backend_runtime_validation_runner_authority"
REQUEST_SCHEMA_VERSION = 2
REQUEST_KIND = "vast_backend_runtime_validation_replay_request_v2"
RECORD_SCHEMA_VERSION = 2
RECORD_KIND = "vast_backend_runtime_cell_validation_record_v2"
MAX_STDOUT_BYTES = 16 * 1024 * 1024
MAX_ACK_BYTES = 512
TIMEOUT_MS = 120000

_SHA_PATTERN = r"[0-9a-f]{64}"
_TOKEN_PATTERN = r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}"
_RESERVED = frozenset({
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
})
_DESCRIPTOR_FIELDS = frozenset({"path", "size_bytes", "sha256"})
_TYPED_REF_FIELDS = frozenset({
    "artifact_schema_version", "artifact_kind", "descriptor",
    "content_identity_sha256",
})
_STDIN_FIELDS = frozenset({"mode"})
_STDOUT_FIELDS = frozenset({"channel", "mode", "purpose", "max_bytes"})
_STDERR_FIELDS = frozenset({
    "channel", "mode", "purpose", "framing", "expected_frame",
    "diagnostics_allowed", "max_bytes",
})
_PROCESS_FIELDS = frozenset({
    "argv", "cwd", "cwd_semantics", "env", "stdin", "stdout", "stderr",
    "shell", "check", "close_fds", "accepted_exit_codes", "timeout_ms",
    "exit_code_handling", "failure_diagnostics_routing",
})
_TOP_FIELDS = frozenset({
    "schema_version", "artifact_kind", "status", "project_root",
    "interpreter_path", "runner_path", "runner_authority_ref",
    "runner_authority_sha256", "request_ref", "request_sha256",
    "expected_record_ref", "expected_record_sha256", "session_id",
    "lease_id", "cell_index", "attempt_ordinal", "challenge",
    "process_contract", "process_executed", "execution_authorized",
    "challenge_freshness_validated", "lease_enforcement_validated",
    "sandbox_enforcement_validated", "invocation_sha256",
})


class ReplayRunnerInvocationV2Error(ValueError):
    """The declarative replay invocation or an external pin is invalid."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ReplayRunnerInvocationV2Error(message)


def _strict_json(
    value: Any, label: str, *, active: set[int] | None = None,
    depth: int = 0,
) -> None:
    _require(depth <= 32, f"{label} JSON nesting is excessive")
    value_type = type(value)
    if value_type not in (dict, list):
        _require(value_type in (str, int, bool),
                 f"{label} contains a non-contract JSON type")
        return
    identities = set() if active is None else active
    identity = id(value)
    _require(identity not in identities, f"{label} contains a JSON cycle")
    identities.add(identity)
    try:
        items = value.items() if value_type is dict else enumerate(value)
        for key, item in items:
            if value_type is dict:
                _require(type(key) is str, f"{label} has a non-string JSON key")
            _strict_json(item, label, active=identities, depth=depth + 1)
    finally:
        identities.remove(identity)


def canonical_identity(value: object) -> str:
    _strict_json(value, "replay invocation v2 canonical value")
    try:
        payload = json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as error:
        raise ReplayRunnerInvocationV2Error(
            "replay invocation v2 is not canonical JSON"
        ) from error
    return hashlib.sha256(payload).hexdigest()


def _sha(value: Any, label: str) -> str:
    _require(type(value) is str
             and re.fullmatch(_SHA_PATTERN, value) is not None,
             f"{label} is not a SHA-256 identity")
    return value


def _path(value: Any, label: str, *, absolute: bool) -> str:
    _require(type(value) is str and bool(value) and "\x00" not in value
             and "\\" not in value and not value.endswith("/")
             and "//" not in value, f"{label} path is unsafe")
    if absolute:
        _require(re.fullmatch(r"[A-Za-z]:/[A-Za-z0-9._/ -]+", value) is not None,
                 f"{label} must be a canonical absolute Windows path")
        parts = value[3:].split("/")
    else:
        _require(not value.startswith("/") and ":" not in value,
                 f"{label} must be project-relative")
        parts = value.split("/")
    _require(all(
        part not in ("", ".", "..") and not part.endswith((".", " "))
        and not any(ord(character) < 32 for character in part)
        and part.split(".", 1)[0].upper() not in _RESERVED
        for part in parts
    ), f"{label} path is unsafe")
    return value


def _descriptor(value: Any, label: str) -> dict[str, Any]:
    _require(type(value) is dict and set(value) == _DESCRIPTOR_FIELDS,
             f"{label} descriptor fields drifted")
    size = value.get("size_bytes")
    _require(type(size) is int and 0 < size <= 8 * 1024 * 1024 * 1024,
             f"{label} size is invalid")
    return {
        "path": _path(value.get("path"), label, absolute=False),
        "size_bytes": size,
        "sha256": _sha(value.get("sha256"), f"{label} file"),
    }


def _typed_ref(
    value: Any, pin: Any, label: str, *, schema_version: int,
    artifact_kind: str,
) -> tuple[dict[str, Any], str]:
    _require(type(value) is dict and set(value) == _TYPED_REF_FIELDS,
             f"{label} typed reference fields drifted")
    _require(type(value.get("artifact_schema_version")) is int
             and value.get("artifact_schema_version") == schema_version,
             f"{label} schema version drifted")
    _require(type(value.get("artifact_kind")) is str
             and value.get("artifact_kind") == artifact_kind,
             f"{label} kind drifted")
    identity = _sha(pin, label)
    checked = {
        "artifact_schema_version": schema_version,
        "artifact_kind": artifact_kind,
        "descriptor": _descriptor(value.get("descriptor"), label),
        "content_identity_sha256": _sha(
            value.get("content_identity_sha256"), f"{label} semantic"
        ),
    }
    _require(checked["content_identity_sha256"] == identity,
             f"{label} semantic pin drifted")
    return checked, identity


def _token(value: Any, label: str) -> str:
    _require(type(value) is str
             and re.fullmatch(_TOKEN_PATTERN, value) is not None,
             f"{label} token is unsafe")
    return value


def _ordinal(value: Any, label: str, *, lower: int, upper: int) -> int:
    _require(type(value) is int and lower <= value <= upper,
             f"{label} is invalid")
    return value


def _argv(
    *, project_root: str, interpreter_path: str, runner_path: str,
    runner_ref: Mapping[str, Any], runner_sha: str,
    request_ref: Mapping[str, Any], request_sha: str,
    record_ref: Mapping[str, Any], record_sha: str,
    session_id: str, lease_id: str, cell_index: int,
    attempt_ordinal: int, challenge: str,
) -> list[str]:
    return [
        interpreter_path, "-I", "-S", "-B", "-X", "utf8", runner_path,
        "--project-root", project_root,
        "--session-id", session_id, "--lease-id", lease_id,
        "--cell-index", str(cell_index),
        "--attempt-ordinal", str(attempt_ordinal), "--challenge", challenge,
        "--runner-authority", runner_ref["descriptor"]["path"],
        "--runner-authority-file-sha256",
        runner_ref["descriptor"]["sha256"],
        "--runner-authority-sha256", runner_sha,
        "--request", request_ref["descriptor"]["path"],
        "--request-file-sha256", request_ref["descriptor"]["sha256"],
        "--request-sha256", request_sha,
        "--expected-record", record_ref["descriptor"]["path"],
        "--expected-record-file-sha256", record_ref["descriptor"]["sha256"],
        "--expected-record-sha256", record_sha,
    ]


def _expected_ack(
    session_id: str, lease_id: str, cell_index: int,
    attempt_ordinal: int, challenge: str,
) -> str:
    return (
        f"VAST_REPLAY_CHALLENGE_ACK_V2 {session_id} {lease_id} "
        f"{cell_index} {attempt_ordinal} {challenge}\n"
    )


def _material(
    *, project_root: Any, interpreter_path: Any, runner_path: Any,
    runner_authority_ref: Any, runner_authority_sha256: Any,
    request_ref: Any, request_sha256: Any, expected_record_ref: Any,
    expected_record_sha256: Any, session_id: Any, lease_id: Any,
    cell_index: Any, attempt_ordinal: Any, challenge: Any,
) -> dict[str, Any]:
    root = _path(project_root, "project root", absolute=True)
    interpreter = _path(interpreter_path, "interpreter", absolute=False)
    runner = _path(runner_path, "runner", absolute=False)
    runner_ref, runner_sha = _typed_ref(
        runner_authority_ref, runner_authority_sha256, "runner authority",
        schema_version=RUNNER_AUTHORITY_SCHEMA_VERSION,
        artifact_kind=RUNNER_AUTHORITY_KIND,
    )
    request_checked, request_sha = _typed_ref(
        request_ref, request_sha256, "validation request",
        schema_version=REQUEST_SCHEMA_VERSION, artifact_kind=REQUEST_KIND,
    )
    record_ref, record_sha = _typed_ref(
        expected_record_ref, expected_record_sha256, "expected record",
        schema_version=RECORD_SCHEMA_VERSION, artifact_kind=RECORD_KIND,
    )
    references = (runner_ref, request_checked, record_ref)
    role_paths = (
        interpreter, runner,
        *(reference["descriptor"]["path"] for reference in references),
    )
    _require(len({path.casefold() for path in role_paths}) == len(role_paths),
             "replay invocation v2 role paths collide")
    _require(len({
        reference["descriptor"]["sha256"] for reference in references
    }) == len(references), "replay invocation v2 reference files collide")
    _require(len({
        reference["content_identity_sha256"] for reference in references
    }) == len(references), "replay invocation v2 reference contents collide")
    session = _token(session_id, "session id")
    lease = _token(lease_id, "lease id")
    cell = _ordinal(cell_index, "cell index", lower=0, upper=559)
    attempt = _ordinal(attempt_ordinal, "attempt ordinal", lower=0, upper=1)
    challenge_sha = _sha(challenge, "challenge commitment")
    argv = _argv(
        project_root=root, interpreter_path=interpreter, runner_path=runner,
        runner_ref=runner_ref, runner_sha=runner_sha,
        request_ref=request_checked, request_sha=request_sha,
        record_ref=record_ref, record_sha=record_sha,
        session_id=session, lease_id=lease, cell_index=cell,
        attempt_ordinal=attempt, challenge=challenge_sha,
    )
    return {
        "schema_version": SCHEMA_VERSION, "artifact_kind": ARTIFACT_KIND,
        "status": "declarative_replay_invocation_candidate",
        "project_root": root, "interpreter_path": interpreter,
        "runner_path": runner, "runner_authority_ref": runner_ref,
        "runner_authority_sha256": runner_sha,
        "request_ref": request_checked, "request_sha256": request_sha,
        "expected_record_ref": record_ref,
        "expected_record_sha256": record_sha,
        "session_id": session, "lease_id": lease, "cell_index": cell,
        "attempt_ordinal": attempt, "challenge": challenge_sha,
        "process_contract": {
            "argv": argv, "cwd": root,
            "cwd_semantics": "caller_supplied_canonical_project_root",
            "env": {}, "stdin": {"mode": "devnull"},
            "stdout": {
                "channel": "stdout", "mode": "pipe",
                "purpose": "exact_canonical_validation_record_bytes_only",
                "max_bytes": MAX_STDOUT_BYTES,
            },
            "stderr": {
                "channel": "stderr", "mode": "pipe",
                "purpose": "challenge_acknowledgement_only",
                "framing": "exact_utf8_line",
                "expected_frame": _expected_ack(
                    session, lease, cell, attempt, challenge_sha
                ),
                "diagnostics_allowed": False, "max_bytes": MAX_ACK_BYTES,
            },
            "shell": False, "check": False, "close_fds": True,
            "accepted_exit_codes": [0], "timeout_ms": TIMEOUT_MS,
            "exit_code_handling": (
                "parent_process_metadata_validates_accepted_exit_codes"
            ),
            "failure_diagnostics_routing": "parent_process_metadata_only",
        },
        "process_executed": False, "execution_authorized": False,
        "challenge_freshness_validated": False,
        "lease_enforcement_validated": False,
        "sandbox_enforcement_validated": False,
    }


def build_backend_runtime_replay_runner_invocation_v2(
    *, project_root: str, interpreter_path: str, runner_path: str,
    runner_authority_ref: Mapping[str, Any], runner_authority_sha256: str,
    request_ref: Mapping[str, Any], request_sha256: str,
    expected_record_ref: Mapping[str, Any], expected_record_sha256: str,
    session_id: str, lease_id: str, cell_index: int, attempt_ordinal: int,
    challenge: str, expected_semantic_sha256: str,
) -> dict[str, Any]:
    value = _material(
        project_root=project_root, interpreter_path=interpreter_path,
        runner_path=runner_path, runner_authority_ref=runner_authority_ref,
        runner_authority_sha256=runner_authority_sha256,
        request_ref=request_ref, request_sha256=request_sha256,
        expected_record_ref=expected_record_ref,
        expected_record_sha256=expected_record_sha256,
        session_id=session_id, lease_id=lease_id, cell_index=cell_index,
        attempt_ordinal=attempt_ordinal, challenge=challenge,
    )
    value["invocation_sha256"] = canonical_identity(value)
    return validate_backend_runtime_replay_runner_invocation_v2(
        value, expected_semantic_sha256=expected_semantic_sha256,
        expected_project_root=project_root,
        expected_interpreter_path=interpreter_path,
        expected_runner_path=runner_path,
        expected_runner_authority_ref=runner_authority_ref,
        expected_runner_authority_sha256=runner_authority_sha256,
        expected_request_ref=request_ref,
        expected_request_sha256=request_sha256,
        expected_record_ref=expected_record_ref,
        expected_record_sha256=expected_record_sha256,
        expected_session_id=session_id, expected_lease_id=lease_id,
        expected_cell_index=cell_index,
        expected_attempt_ordinal=attempt_ordinal,
        expected_challenge=challenge,
    )


def validate_backend_runtime_replay_runner_invocation_v2(
    value: Any, *, expected_semantic_sha256: str,
    expected_project_root: str, expected_interpreter_path: str,
    expected_runner_path: str,
    expected_runner_authority_ref: Mapping[str, Any],
    expected_runner_authority_sha256: str,
    expected_request_ref: Mapping[str, Any], expected_request_sha256: str,
    expected_record_ref: Mapping[str, Any],
    expected_record_sha256: str,
    expected_session_id: str, expected_lease_id: str,
    expected_cell_index: int, expected_attempt_ordinal: int,
    expected_challenge: str,
) -> dict[str, Any]:
    _strict_json(value, "replay invocation v2")
    _require(type(value) is dict and set(value) == _TOP_FIELDS,
             "replay invocation v2 fields drifted")
    expected = _material(
        project_root=expected_project_root,
        interpreter_path=expected_interpreter_path,
        runner_path=expected_runner_path,
        runner_authority_ref=expected_runner_authority_ref,
        runner_authority_sha256=expected_runner_authority_sha256,
        request_ref=expected_request_ref,
        request_sha256=expected_request_sha256,
        expected_record_ref=expected_record_ref,
        expected_record_sha256=expected_record_sha256,
        session_id=expected_session_id, lease_id=expected_lease_id,
        cell_index=expected_cell_index,
        attempt_ordinal=expected_attempt_ordinal,
        challenge=expected_challenge,
    )
    actual = _material(
        project_root=value.get("project_root"),
        interpreter_path=value.get("interpreter_path"),
        runner_path=value.get("runner_path"),
        runner_authority_ref=value.get("runner_authority_ref"),
        runner_authority_sha256=value.get("runner_authority_sha256"),
        request_ref=value.get("request_ref"),
        request_sha256=value.get("request_sha256"),
        expected_record_ref=value.get("expected_record_ref"),
        expected_record_sha256=value.get("expected_record_sha256"),
        session_id=value.get("session_id"), lease_id=value.get("lease_id"),
        cell_index=value.get("cell_index"),
        attempt_ordinal=value.get("attempt_ordinal"),
        challenge=value.get("challenge"),
    )
    _require(type(value.get("schema_version")) is int
             and value.get("schema_version") == SCHEMA_VERSION
             and type(value.get("artifact_kind")) is str
             and value.get("artifact_kind") == ARTIFACT_KIND
             and type(value.get("status")) is str and value.get("status")
             == "declarative_replay_invocation_candidate",
             "replay invocation v2 header drifted")
    for field in (
        "process_executed", "execution_authorized",
        "challenge_freshness_validated", "lease_enforcement_validated",
        "sandbox_enforcement_validated",
    ):
        _require(value.get(field) is False,
                 f"replay invocation v2 {field} claim drifted")
    process = value.get("process_contract")
    _require(type(process) is dict and set(process) == _PROCESS_FIELDS,
             "replay invocation v2 process fields drifted")
    stdin = process.get("stdin")
    stdout = process.get("stdout")
    stderr = process.get("stderr")
    _require(type(stdin) is dict and set(stdin) == _STDIN_FIELDS,
             "replay invocation v2 stdin fields drifted")
    _require(type(stdout) is dict and set(stdout) == _STDOUT_FIELDS,
             "replay invocation v2 stdout fields drifted")
    _require(type(stderr) is dict and set(stderr) == _STDERR_FIELDS,
             "replay invocation v2 stderr fields drifted")
    _require(canonical_identity(actual) == canonical_identity(expected),
             "replay invocation v2 external pin drifted")
    actual_fields = {
        field: copy.deepcopy(value.get(field)) for field in actual
    }
    _require(canonical_identity(actual_fields) == canonical_identity(actual),
             "replay invocation v2 declarative material drifted")
    identity = _sha(value.get("invocation_sha256"), "replay invocation v2")
    unsigned = {field: copy.deepcopy(item) for field, item in value.items()
                if field != "invocation_sha256"}
    _require(identity == canonical_identity(unsigned)
             == _sha(expected_semantic_sha256,
                     "expected replay invocation v2"),
             "replay invocation v2 semantic identity drifted")
    reference_identities = {
        value["runner_authority_ref"]["content_identity_sha256"],
        value["request_ref"]["content_identity_sha256"],
        value["expected_record_ref"]["content_identity_sha256"],
    }
    _require(len(reference_identities) == 3 and identity not in reference_identities,
             "replay invocation v2 reference identity cycle/collision")
    return copy.deepcopy(value)


__all__ = [
    "SCHEMA_VERSION", "ARTIFACT_KIND", "RUNNER_AUTHORITY_SCHEMA_VERSION",
    "RUNNER_AUTHORITY_KIND", "REQUEST_SCHEMA_VERSION", "REQUEST_KIND",
    "RECORD_SCHEMA_VERSION", "RECORD_KIND", "MAX_STDOUT_BYTES",
    "MAX_ACK_BYTES", "TIMEOUT_MS", "ReplayRunnerInvocationV2Error",
    "canonical_identity",
    "build_backend_runtime_replay_runner_invocation_v2",
    "validate_backend_runtime_replay_runner_invocation_v2",
]
