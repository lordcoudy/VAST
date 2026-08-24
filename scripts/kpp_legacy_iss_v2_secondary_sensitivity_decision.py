#!/usr/bin/env python3
"""Validate the PI-scoped KPP legacy ISS v2 secondary/sensitivity decision."""

from __future__ import annotations

import copy
import hashlib
import json
import re
import stat
from collections.abc import Mapping
from pathlib import Path
from typing import Any


DECISION_PATH = Path(
    "configs/kpp_legacy_iss_v2_secondary_sensitivity_decision.json"
)
DECISION_DOMAIN = (
    b"VAST:kpp-legacy-iss-v2-secondary-sensitivity-decision:v1\0"
)
DECISION_ARTIFACT_KIND = (
    "vast_kpp_legacy_iss_v2_secondary_sensitivity_decision"
)
EXPECTED_DECISION_FILE_SHA256 = (
    "b6d551eda006897d24e76946ed7d6be3e2b7b04eeb4341770dad79264408af72"
)
_MAX_DECISION_BYTES = 64 * 1024
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")


class DecisionError(RuntimeError):
    """The checked decision is absent, ambiguous, or broader than approved."""


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")


def _unsigned_expected_decision() -> dict[str, object]:
    sampling_rule: dict[str, object] = {
        "schema_version": 1,
        "rule_id": "kpp_v2_midpoint_60_interleaved_codec_corpus_v1",
        "source_roles": ["front_gate", "underbody"],
        "branch_source_role": {
            "plate_number": "front_gate",
            "vehicle_type": "front_gate",
            "damage": "front_gate",
            "foreign_object": "underbody",
        },
        "strata_per_source_role": 60,
        "index_formula": "floor((2*j+1)*N/(2*60));j=0..59",
        "assignment_by_j_modulo_4": {
            "0": {"corpus_role": "calibration", "codec": "h264"},
            "1": {"corpus_role": "evaluation", "codec": "h264"},
            "2": {"corpus_role": "calibration", "codec": "h265"},
            "3": {"corpus_role": "evaluation", "codec": "h265"},
        },
        "selection_inputs": ["frame_count"],
        "content_inspection_used_for_selection": False,
        "event_or_label_selection_used": False,
        "performance_or_outcome_selection_used": False,
        "identical_relative_strata_across_front_branches": True,
        "codec_frame_count_equality_required_per_source_role": True,
    }
    return {
        "schema_version": 1,
        "artifact_kind": DECISION_ARTIFACT_KIND,
        "decision_id": (
            "kpp-legacy-iss-v2-secondary-sensitivity-topology-load-pilot-v1"
        ),
        "recorded_date": "2026-08-21",
        "decision_source": {
            "kind": "explicit_user_pi_instruction_in_active_codex_task",
            "cryptographic_signature_attested": False,
            "external_identity_attested": False,
        },
        "approval_status": (
            "approved_for_secondary_sensitivity_topology_load_pilot_only"
        ),
        "dataset_generation": "kpp_legacy_iss_v2",
        "authorized_dataset_roles": ["secondary", "sensitivity"],
        "primary_scope": {
            "existing_primary_matrix_unchanged": True,
            "silent_primary_replacement_authorized": False,
            "new_matrix_identity_required": True,
            "new_run_root_required": True,
        },
        "branch_source_role": copy.deepcopy(sampling_rule["branch_source_role"]),
        "sampling_rule": sampling_rule,
        "sampling_allocation": {
            "samples_per_branch": 60,
            "calibration": {"total": 30, "h264": 15, "h265": 15},
            "evaluation": {"total": 30, "h264": 15, "h265": 15},
        },
        "shared_front_frames": {
            "allowed": True,
            "use": "topology_load_proxy_only",
            "accuracy_claim_authorized": False,
            "representativeness_claim_authorized": False,
            "statistical_independence_claimed": False,
        },
        "pilot_authorization": {
            "authorized": True,
            "environments": ["wsl", "docker", "gpu"],
            "nonpublication_only": True,
            "accepted_evidence_authorized": False,
            "publication_readiness_elevation_authorized": False,
            "network_download_authorized": False,
            "cloud_upload_authorized": False,
        },
        "claims": {
            "semantic_claim": "topology_load_proxy_only",
            "accuracy": False,
            "representative": False,
            "statistical_independence": False,
            "production_semantics": False,
            "model_acceptance": False,
            "runtime_acceptance": False,
            "publishable": False,
            "publication_authorized": False,
            "primary_replacement_authorized": False,
        },
    }


def expected_decision() -> dict[str, object]:
    result = _unsigned_expected_decision()
    result["decision_sha256"] = hashlib.sha256(
        DECISION_DOMAIN + canonical_bytes(result)
    ).hexdigest()
    return result


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DecisionError(f"duplicate decision key: {key}")
        result[key] = value
    return result


def _snapshot(path: Path) -> tuple[int, int, int, int, int, int]:
    try:
        observed = path.lstat()
    except OSError as exc:
        raise DecisionError(f"could not inspect decision artifact: {exc}") from exc
    if not stat.S_ISREG(observed.st_mode) or observed.st_nlink != 1:
        raise DecisionError("decision artifact must be one regular nonlinked file")
    if observed.st_size <= 0 or observed.st_size > _MAX_DECISION_BYTES:
        raise DecisionError("decision artifact size is invalid")
    return (
        int(observed.st_dev),
        int(observed.st_ino),
        int(observed.st_mode),
        int(observed.st_nlink),
        int(observed.st_size),
        int(observed.st_mtime_ns),
    )


def load_decision(path: Path) -> dict[str, object]:
    candidate = path.absolute()
    before = _snapshot(candidate)
    try:
        payload = candidate.read_bytes()
    except OSError as exc:
        raise DecisionError(f"could not read decision artifact: {exc}") from exc
    after = _snapshot(candidate)
    if after != before or len(payload) != before[4]:
        raise DecisionError("decision artifact changed while reading")
    try:
        parsed = json.loads(
            payload.decode("ascii"), object_pairs_hook=_unique_object
        )
    except DecisionError:
        raise
    except (UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise DecisionError(f"decision artifact is not strict JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise DecisionError("decision artifact root must be an object")
    if payload != canonical_bytes(parsed) + b"\n":
        raise DecisionError("decision artifact does not use canonical bytes")
    declared = parsed.get("decision_sha256")
    if not isinstance(declared, str) or _SHA256_RE.fullmatch(declared) is None:
        raise DecisionError("decision self SHA-256 is invalid")
    unsigned = copy.deepcopy(parsed)
    unsigned.pop("decision_sha256", None)
    computed = hashlib.sha256(
        DECISION_DOMAIN + canonical_bytes(unsigned)
    ).hexdigest()
    if declared != computed:
        raise DecisionError("decision self SHA-256 does not match canonical content")
    if canonical_bytes(parsed) != canonical_bytes(expected_decision()):
        raise DecisionError("decision contract differs from the PI-approved scope")
    return copy.deepcopy(parsed)


def load_checked_in_decision(project_root: Path) -> dict[str, object]:
    path = project_root.absolute() / DECISION_PATH
    loaded = load_decision(path)
    observed = hashlib.sha256(path.read_bytes()).hexdigest()
    if observed != EXPECTED_DECISION_FILE_SHA256:
        raise DecisionError("checked-in decision file SHA-256 drifted")
    return loaded


__all__ = [
    "DECISION_ARTIFACT_KIND",
    "DECISION_DOMAIN",
    "DECISION_PATH",
    "DecisionError",
    "EXPECTED_DECISION_FILE_SHA256",
    "canonical_bytes",
    "expected_decision",
    "load_checked_in_decision",
    "load_decision",
]
