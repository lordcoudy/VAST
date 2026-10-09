#!/usr/bin/env python3
"""Q1 steps 14-15 on qualification transaction v2 outputs (Amendment 8).

Runs the stock policy/resource index builders, promotions and assessments with
the authority-v2 fragment validator that transaction v2 itself uses.  Before
any stock function runs, the exact transaction receipt, its fragments, the
index and the execution closure must bind to one another.  Host-only: not
imported by the execution code closure and not part of any image.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import full_resource_qualification as resource_qualification
import full_resource_qualification_index_v1 as resource_index
import publication_policy_qualification as policy_qualification
import publication_policy_qualification_fragments_from_authority_v2 as fragments_v2
import publication_policy_qualification_index_v2 as policy_index
import publication_policy_qualification_transaction_v2 as transaction_v2


SYSTEMS = transaction_v2.SYSTEMS
# Same exit code as other refused qualification gates (EX_CONFIG).
ASSESSMENT_BLOCKED_EXIT = 78


class PromotionV2Error(RuntimeError):
    """The transaction, fragments, index and closure do not bind exactly."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise PromotionV2Error(message)


def _fragment_validator(system: str, fragment_path: Path, project_root: Path) -> dict[str, Any]:
    return fragments_v2.validate_publication_policy_qualification_fragment_from_authority_v2(
        system, fragment_path, project_root
    )


def _descriptor(root: Path, value: Path | str, label: str) -> dict[str, Any]:
    try:
        return transaction_v2.file_descriptor(root, value)
    except (OSError, transaction_v2.QualificationTransactionV2Error) as error:
        raise PromotionV2Error(f"{label} is not one physical file under project_root: {error}") from error


def _read_json(root: Path, value: Path | str, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    descriptor = _descriptor(root, value, label)
    try:
        parsed = json.loads((root / descriptor["path"]).read_bytes())
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise PromotionV2Error(f"{label} is not JSON") from error
    _require(type(parsed) is dict, f"{label} is not a JSON object")
    return descriptor, parsed


def _transaction(
    project_root: Path, receipt_path: Path, fragment_paths: Mapping[str, Path]
) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    """Exact cold-validated transaction v2 whose fragments are the given files."""
    try:
        root = transaction_v2._root(project_root)
        path, receipt = transaction_v2._read_json(root, receipt_path, label="qualification transaction receipt")
        transaction_v2._require(
            receipt.get("schema_version") == transaction_v2.SCHEMA_VERSION
            and receipt.get("artifact_kind") == transaction_v2.TRANSACTION_KIND
            and receipt.get("receipt_sha256")
            == transaction_v2._self_sha(receipt, "receipt_sha256"),
            "qualification transaction receipt kind/self-hash drifted",
        )
        transaction_v2._cold_validate_committed_transaction(root=root, receipt_path=path)
    except (OSError, transaction_v2.QualificationTransactionV2Error) as error:
        raise PromotionV2Error(f"qualification transaction v2 refused: {error}") from error
    fragments = receipt.get("fragments")
    _require(
        type(fragments) is dict and set(fragments) == set(SYSTEMS) and set(fragment_paths) == set(SYSTEMS),
        "qualification transaction fragment coverage drifted",
    )
    for system in SYSTEMS:
        _require(
            _descriptor(root, fragment_paths[system], f"{system} fragment") == fragments[system],
            f"{system} fragment is not the transaction fragment",
        )
    return root, _descriptor(root, path, "qualification transaction receipt"), receipt


def _require_closure_transaction(
    root: Path,
    closure: Path | str,
    receipt_descriptor: Mapping[str, Any],
    receipt: Mapping[str, Any],
    *,
    expected_descriptor: Mapping[str, Any] | None = None,
) -> None:
    descriptor, value = _read_json(root, closure, "qualification execution closure receipt")
    if expected_descriptor is not None:
        _require(descriptor == dict(expected_descriptor), "index execution closure descriptor drifted")
    transaction = value.get("qualification_input_transaction")
    _require(
        type(transaction) is dict
        and transaction.get("receipt") == dict(receipt_descriptor)
        and transaction.get("receipt_sha256") == receipt["receipt_sha256"]
        and transaction.get("fragments") == receipt["fragments"],
        "execution closure does not bind this qualification transaction",
    )


def _index(root: Path, index_path: Path, label: str) -> dict[str, Any]:
    _descriptor_value, index = _read_json(root, index_path, label)
    closure = index.get("qualification_execution_closure")
    _require(type(closure) is dict and type(closure.get("path")) is str, f"{label} has no execution closure")
    _require(type(index.get("bindings")) is list and bool(index["bindings"]), f"{label} has no bindings")
    return index


def _require_policy_index(root: Path, index_path: Path, receipt_descriptor, receipt) -> None:
    index = _index(root, index_path, "policy qualification index")
    seen: set[str] = set()
    for row in index["bindings"]:
        system = row.get("system") if type(row) is dict else None
        _require(system in SYSTEMS, "policy index binding system drifted")
        _require(
            row.get("fragment_artifact") == receipt["fragments"][system],
            f"policy index {system} fragment_artifact is not the transaction fragment",
        )
        seen.add(system)
    _require(seen == set(SYSTEMS), "policy index fragment coverage drifted")
    _require_closure_transaction(
        root, index["qualification_execution_closure"]["path"], receipt_descriptor, receipt,
        expected_descriptor=index["qualification_execution_closure"],
    )


def _require_resource_index(
    root: Path, index_path: Path, fragment_paths: Mapping[str, Path], receipt_descriptor, receipt
) -> None:
    # Resource rows carry no fragment descriptor; each implementation artifact must be
    # exactly the binding file the (transaction-bound) fragment lists for it.
    expected: dict[tuple[str, str], dict[str, Any]] = {}
    for system in SYSTEMS:
        _descriptor_value, fragment = _read_json(root, fragment_paths[system], f"{system} fragment")
        for row in fragment.get("resource_bindings") or []:
            expected[(system, str(row.get("resource")))] = {
                "path": row.get("path"), "size_bytes": row.get("size"), "sha256": row.get("sha256"),
            }
    index = _index(root, index_path, "full-resource qualification index")
    seen: set[tuple[str, str]] = set()
    for row in index["bindings"]:
        key = (str(row.get("system")), str(row.get("resource"))) if type(row) is dict else ("", "")
        _require(
            key in expected and row.get("implementation_artifact") == expected[key],
            f"resource index binding {key} is not the transaction fragment binding",
        )
        seen.add(key)
    _require(seen == set(expected) and len(seen) == 8, "resource index fragment coverage drifted")
    _require_closure_transaction(
        root, index["qualification_execution_closure"]["path"], receipt_descriptor, receipt,
        expected_descriptor=index["qualification_execution_closure"],
    )


def _fragments(args: argparse.Namespace) -> dict[str, Path]:
    return {system: getattr(args, f"{system}_fragment") for system in SYSTEMS}


def _print(value: Any) -> None:
    print(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str))


def _run(args: argparse.Namespace) -> int:
    fragment_paths = _fragments(args)
    root, receipt_descriptor, receipt = _transaction(
        args.project_root, args.qualification_transaction_receipt, fragment_paths
    )
    command = args.command
    if command in {"policy-index", "resource-index"}:
        _require_closure_transaction(root, args.execution_closure_receipt, receipt_descriptor, receipt)
        common = dict(
            project_root=root,
            fragment_paths=fragment_paths,
            pilot_root=args.pilot_root,
            fragment_validator=_fragment_validator,
            execution_closure_receipt_path=args.execution_closure_receipt,
        )
        if command == "policy-index":
            result = policy_index.build_policy_qualification_index_v2(output_dir=args.output_dir, **common)
            _print({key: str(value) for key, value in result.items()})
        else:
            _print(str(resource_index.build_full_resource_qualification_index_v1(output_path=args.output_path, **common)))
        return 0

    if command.startswith("policy-"):
        _require_policy_index(root, args.index_path, receipt_descriptor, receipt)
    else:
        _require_resource_index(root, args.index_path, fragment_paths, receipt_descriptor, receipt)
    if command == "policy-promote":
        _print(policy_qualification.promote_policy_qualification(
            project_root=root, index_path=args.index_path, output_dir=args.output_dir,
            fragment_validator=_fragment_validator,
        ))
        return 0
    if command == "resource-promote":
        _print(resource_qualification.promote_full_resource_qualification(
            project_root=root, index_path=args.index_path, output_dir=args.output_dir,
        ))
        return 0
    if command == "policy-assess":
        assessment = policy_qualification.assess_policy_qualification(
            project_root=root, index_path=args.index_path, fragment_validator=_fragment_validator,
        )
    else:
        assessment = resource_qualification.assess_full_resource_qualification(
            project_root=root, index_path=args.index_path,
        )
    _print(assessment)
    return 0 if type(assessment) is dict and assessment.get("passed") is True else ASSESSMENT_BLOCKED_EXIT


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    def command(name: str) -> argparse.ArgumentParser:
        sub = commands.add_parser(name)
        sub.add_argument("--project-root", type=Path, required=True)
        sub.add_argument("--qualification-transaction-receipt", type=Path, required=True)
        for system in SYSTEMS:
            sub.add_argument(
                f"--{system.replace('_', '-')}-fragment", dest=f"{system}_fragment", type=Path, required=True
            )
        return sub

    for name, output in (("policy-index", "--output-dir"), ("resource-index", "--output-path")):
        sub = command(name)
        sub.add_argument("--pilot-root", type=Path, required=True)
        sub.add_argument("--execution-closure-receipt", type=Path, required=True)
        sub.add_argument(output, type=Path, required=True)
    for name in ("policy-promote", "resource-promote"):
        sub = command(name)
        sub.add_argument("--index-path", type=Path, required=True)
        sub.add_argument("--output-dir", type=Path, required=True)
    for name in ("policy-assess", "resource-assess"):
        command(name).add_argument("--index-path", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    return _run(_parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["ASSESSMENT_BLOCKED_EXIT", "PromotionV2Error", "main"]
