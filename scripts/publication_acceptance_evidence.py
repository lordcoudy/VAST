#!/usr/bin/env python3
"""Canonical accepted-arm evidence file sets for frozen publication policies."""
from __future__ import annotations

from typing import Any


FROZEN_POLICY_DECISIONS_JSONL = "publication_policy_decisions.jsonl"
FROZEN_POLICY_FEEDBACK_JSONL = "publication_policy_feedback.jsonl"
FROZEN_PUBLICATION_FEEDBACK_POLICIES = frozenset({"adaptive_weights"})
BASE_ACCEPTANCE_EVIDENCE_FILES = (
    "frames.csv",
    "frame_events.csv",
    "resource_events.csv",
    "policy_decisions.csv",
    "drop_counters.csv",
    "topology_events.csv",
    "ingress_ledger.csv",
    "branch_terminals.csv",
    "stage_contracts.csv",
    "reset_evidence.csv",
)
FULL_RESOURCE_EVIDENCE_FILES = (
    "resource_intervals.csv",
    "hardware_resource_samples.csv",
    "fanout_work_counters.csv",
)


def frozen_policy_requires_feedback(policy: Any) -> bool:
    """Only adaptive_weights has feedback in the frozen seven-policy contract."""

    return str(policy).strip().lower() in FROZEN_PUBLICATION_FEEDBACK_POLICIES


def pre_finalization_acceptance_evidence_files(policy: Any) -> tuple[str, ...]:
    """Return the exact evidence committed before resource-v2 finalization."""

    files = [*BASE_ACCEPTANCE_EVIDENCE_FILES, FROZEN_POLICY_DECISIONS_JSONL]
    if frozen_policy_requires_feedback(policy):
        files.append(FROZEN_POLICY_FEEDBACK_JSONL)
    return tuple(files)


def accepted_arm_evidence_files(
    policy: Any,
    *,
    full_resource: bool,
) -> tuple[str, ...]:
    """Return the exact policy-aware accepted-arm evidence set."""

    files = list(pre_finalization_acceptance_evidence_files(policy))
    if full_resource:
        files.extend(FULL_RESOURCE_EVIDENCE_FILES)
    return tuple(files)
