#!/usr/bin/env python3
"""Commit image-bound qualification candidate/bootstrap inputs as one receipt-last transaction.

The transaction is deliberately nonauthorizing.  It revalidates the physical
image patch and model-parity acceptance before and after materializing the four
system fragments, the fragment-only candidate index, and the bootstrap
calibrations.  The transaction receipt is created exclusively and last.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from dataclasses import dataclass
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from publication_physical_io_v1 import (
    PhysicalRootCustodyV1,
    PublicationPhysicalIoV1Error,
)
from publication_policy_qualification_transaction_validation_v2 import (
    BOOTSTRAP_DIRNAME,
    BOOTSTRAP_RECEIPT_FILENAME,
    CALIBRATION_FILENAME,
    CANDIDATE_DIRNAME,
    CANDIDATE_MANIFEST_FILENAME,
    CANDIDATE_RECEIPT_FILENAME,
    CELL_COUNT,
    FRAGMENTS_DIRNAME,
    HARDWARE_RESOURCE_COLLECTOR_PATH,
    INDEX_FILENAME,
    MAPPING_FILENAME,
    PATCH_KIND,
    QualificationTransactionV2Error,
    REFRESH_ONLY_BLOCKERS,
    SCHEMA_VERSION,
    SYSTEMS,
    TRANSACTION_KIND,
    TRANSACTION_RECEIPT_FILENAME,
    V3_PARITY_BINDING_KIND,
    V4_PARITY_BINDING_KIND,
    _ACTIVE_CUSTODY,
    _IMAGE,
    _IMMUTABLE_OUTPUT_MODES,
    _SHA,
    _canonical,
    _cold_validate_committed_transaction,
    _custody,
    _default_load_identity_patch,
    _default_load_parity_acceptance,
    _descriptor_matches,
    _is_link,
    _physical_directory,
    _physical_file,
    _read_json,
    _require,
    _root,
    _self_sha,
    _sha256_file,
    _under_root,
    _validate_committed_receipt,
    file_descriptor,
)


def _safe_output_root(root: Path, value: Path | str) -> Path:
    output = _under_root(root, value, label="output_root")
    _require(output != root, "output_root cannot be project_root")
    parent = output.parent
    _physical_directory(root, parent, label="output_root parent")
    if output.exists() or os.path.lexists(output):
        return _physical_directory(root, output, label="output_root")
    held = _custody(root)
    if held is not None:
        try:
            return held.ensure_directory(output, label="output_root")
        except PublicationPhysicalIoV1Error as error:
            raise QualificationTransactionV2Error(
                f"output_root custody failed: {error}"
            ) from error
    output.mkdir(mode=0o755)
    _require(
        output.resolve(strict=True) == output and not _is_link(output),
        "created output_root is unsafe",
    )
    _fsync_directory(parent)
    return output


def _fsync_directory(path: Path) -> None:
    descriptor: int | None = None
    try:
        descriptor = os.open(path, os.O_RDONLY | int(getattr(os, "O_DIRECTORY", 0)))
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _mkdir_phase(root: Path, path: Path, *, label: str) -> Path:
    if path.exists() or os.path.lexists(path):
        return _physical_directory(root, path, label=label)
    held = _custody(root)
    if held is not None:
        try:
            return held.ensure_directory(path, label=label)
        except PublicationPhysicalIoV1Error as error:
            raise QualificationTransactionV2Error(
                f"{label} custody failed: {error}"
            ) from error
    path.mkdir(mode=0o755)
    _require(path.resolve(strict=True) == path and not _is_link(path), f"{label} is unsafe")
    _fsync_directory(path.parent)
    return path


def _commit_receipt_atomic(
    path: Path,
    payload: bytes,
    *,
    after_physical_commit_step: Callable[[str, Path], None] | None = None,
) -> None:
    held = _ACTIVE_CUSTODY.get()
    _require(held is not None, "transaction receipt commit lacks physical custody")
    relative = path.relative_to(held.root).as_posix()
    expected = {
        "path": relative,
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }

    def physical_step(step: str) -> None:
        if after_physical_commit_step is not None:
            after_physical_commit_step(step, path)

    try:
        observed, identity, disposition = held.commit_or_adopt_exact_identity(
            relative,
            payload,
            label="qualification transaction receipt",
            mode=0o444,
            create_parents=False,
            after_publish_step=physical_step,
        )
        mode, stat_identity = held.stat_regular_identity(
            relative, label="qualification transaction receipt mode"
        )
        cold, cold_payload, cold_identity = held.read_descriptor_identity(
            relative,
            label="qualification transaction receipt cold identity",
            maximum=len(payload),
            capture=True,
        )
    except PublicationPhysicalIoV1Error as error:
        raise QualificationTransactionV2Error(
            f"transaction receipt atomic commit/adoption failed: {error}"
        ) from error
    _require(
        disposition in {"published", "adopted"}
        and observed == expected
        and cold == expected
        and cold_payload == payload
        and cold_identity == identity == stat_identity
        and mode in _IMMUTABLE_OUTPUT_MODES,
        "transaction receipt atomic identity drifted",
    )


def _default_materialize_fragments(**kwargs: Any) -> Mapping[str, Path]:
    from publication_policy_qualification_fragments_from_authority_v2 import (
        materialize_publication_policy_qualification_fragments_from_authority_v2,
    )

    return materialize_publication_policy_qualification_fragments_from_authority_v2(**kwargs)


def _default_validate_fragments(**kwargs: Any) -> Mapping[str, dict[str, Any]]:
    from publication_policy_qualification_fragments_from_authority_v2 import (
        validate_publication_policy_qualification_fragments_from_authority_v2,
    )

    return validate_publication_policy_qualification_fragments_from_authority_v2(**kwargs)


def _default_build_index(**kwargs: Any) -> Mapping[str, Path]:
    from publication_policy_qualification_index_v2 import build_policy_qualification_index_v2
    from publication_policy_qualification_fragments_from_authority_v2 import (
        validate_publication_policy_qualification_fragment_from_authority_v2,
    )

    return build_policy_qualification_index_v2(
        **kwargs,
        fragment_validator=(
            validate_publication_policy_qualification_fragment_from_authority_v2
        ),
    )


def _default_build_bootstrap(**kwargs: Any) -> Mapping[str, Any]:
    from publication_policy_qualification_bootstrap_v2 import (
        build_qualification_bootstrap_calibration_v2,
    )

    return build_qualification_bootstrap_calibration_v2(**kwargs)


def _default_validate_complete(**kwargs: Any) -> Any:
    from publication_policy_qualification_pilot_executor_v2 import _load_qualification_inputs

    return _load_qualification_inputs(**kwargs)


@dataclass(frozen=True)
class TransactionDependencies:
    load_identity_patch: Callable[..., dict[str, Any]] = _default_load_identity_patch
    load_parity_acceptance: Callable[..., dict[str, Any]] = _default_load_parity_acceptance
    materialize_fragments: Callable[..., Mapping[str, Path]] = _default_materialize_fragments
    validate_fragments: Callable[..., Mapping[str, dict[str, Any]]] = _default_validate_fragments
    build_index: Callable[..., Mapping[str, Path]] = _default_build_index
    build_bootstrap: Callable[..., Mapping[str, Any]] = _default_build_bootstrap
    validate_complete: Callable[..., Any] = _default_validate_complete


DEFAULT_DEPENDENCIES = TransactionDependencies()


def _load_authorities(
    *,
    root: Path,
    identity_patch_path: Path | str,
    accepted_model_parity_manifest_path: Path | str,
    accepted_model_parity_assessment_path: Path | str,
    accepted_model_parity_receipt_path: Path | str,
    dependencies: TransactionDependencies,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, dict[str, Any]]]:
    patch_path = _physical_file(root, identity_patch_path, label="image identity patch")
    manifest_path = _physical_file(
        root, accepted_model_parity_manifest_path, label="accepted parity manifest"
    )
    assessment_path = _physical_file(
        root, accepted_model_parity_assessment_path, label="accepted parity assessment"
    )
    receipt_path = _physical_file(
        root, accepted_model_parity_receipt_path, label="accepted parity receipt"
    )
    hardware_collector_path = _physical_file(
        root,
        HARDWARE_RESOURCE_COLLECTOR_PATH,
        label="hardware resource collector",
    )
    try:
        patch = dependencies.load_identity_patch(
            project_root=root,
            patch_path=patch_path,
            require_candidate_eligible=False,
        )
        parity = dependencies.load_parity_acceptance(
            project_root=root,
            receipt_path=receipt_path,
        )
    except QualificationTransactionV2Error:
        raise
    except Exception as error:
        raise QualificationTransactionV2Error(
            f"qualification authority preflight failed closed: {error}"
        ) from error
    _require(type(patch) is dict, "image identity patch loader returned invalid data")
    _require(
        patch.get("artifact_kind") == PATCH_KIND
        and type(patch.get("candidate_binding_eligible")) is bool
        and type(patch.get("blockers")) is list
        and type(patch.get("patch_sha256")) is str
        and _SHA.fullmatch(patch["patch_sha256"]) is not None,
        "image identity patch is not candidate-binding eligible",
    )
    _require(
        type(patch.get("systems")) is dict
        and set(patch["systems"]) == set(SYSTEMS)
        and type(patch.get("workers")) is dict
        and set(patch["workers"]) == {"cpu", "gpu"},
        "image identity patch coverage drifted",
    )
    for resource in ("cpu", "gpu"):
        worker = patch["workers"][resource]
        _require(
            type(worker) is dict
            and _IMAGE.fullmatch(str(worker.get("image_id", ""))) is not None,
            f"{resource} worker freeze identity is invalid",
        )
    descriptors = {
        "hardware_resource_collector": file_descriptor(
            root, hardware_collector_path
        ),
        "image_identity_patch": file_descriptor(root, patch_path),
        "accepted_model_parity_manifest": file_descriptor(root, manifest_path),
        "accepted_model_parity_assessment": file_descriptor(root, assessment_path),
        "accepted_model_parity_receipt": file_descriptor(root, receipt_path),
    }
    _require(
        type(parity) is dict
        and _SHA.fullmatch(str(parity.get("binding_sha256", ""))) is not None
        and parity.get("accepted_manifest")
        == descriptors["accepted_model_parity_manifest"]
        and parity.get("accepted_assessment")
        == descriptors["accepted_model_parity_assessment"]
        and parity.get("receipt") == descriptors["accepted_model_parity_receipt"],
        "model-parity acceptance loader returned an unbound primary artifact",
    )
    eligible = patch["candidate_binding_eligible"] is True
    if eligible:
        _require(
            patch["blockers"] == []
            and parity.get("schema_version") == 2
            and parity.get("artifact_kind") == V3_PARITY_BINDING_KIND,
            "eligible image patch requires the exact unchanged v3 parity authority",
        )
    else:
        _require(
            patch["blockers"] == list(REFRESH_ONLY_BLOCKERS)
            and parity.get("schema_version") == 4
            and parity.get("artifact_kind") == V4_PARITY_BINDING_KIND,
            "ineligible image patch is not resolved by exact patch-bound v4 parity",
        )
        refresh = parity.get("refresh_authority")
        patch_binding = (
            refresh.get("image_identity_patch")
            if type(refresh) is dict
            else None
        )
        workers = refresh.get("workers") if type(refresh) is dict else None
        _require(
            type(patch_binding) is dict
            and {
                key: patch_binding.get(key)
                for key in ("path", "size_bytes", "sha256")
            }
            == descriptors["image_identity_patch"]
            and patch_binding.get("patch_sha256") == patch["patch_sha256"]
            and patch_binding.get("refresh_blockers")
            == list(REFRESH_ONLY_BLOCKERS)
            and patch_binding.get("resolved_blockers") == []
            and type(workers) is dict
            and set(workers) == {"cpu", "gpu"},
            "v4 parity refresh is stale or cross-bound to another image patch",
        )
        for resource in ("cpu", "gpu"):
            _require(
                type(workers[resource]) is dict
                and workers[resource].get("image_id")
                == patch["workers"][resource].get("image_id"),
                f"v4 {resource} worker refresh is cross-bound",
            )
    return patch, parity, descriptors


def _phase_paths(output: Path) -> dict[str, Any]:
    fragments_root = output / FRAGMENTS_DIRNAME
    candidate_root = output / CANDIDATE_DIRNAME
    bootstrap_root = output / BOOTSTRAP_DIRNAME
    return {
        "fragments_root": fragments_root,
        "fragment_paths": {
            system: fragments_root / system / "qualification_fragment.json"
            for system in SYSTEMS
        },
        "candidate_root": candidate_root,
        "candidate_index": candidate_root / INDEX_FILENAME,
        "candidate_manifest": candidate_root / CANDIDATE_MANIFEST_FILENAME,
        "candidate_receipt": candidate_root / CANDIDATE_RECEIPT_FILENAME,
        "bootstrap_root": bootstrap_root,
        "bootstrap_mapping": bootstrap_root / MAPPING_FILENAME,
        "bootstrap_receipt": bootstrap_root / BOOTSTRAP_RECEIPT_FILENAME,
        "bootstrap_calibrations": {
            system: bootstrap_root / CALIBRATION_FILENAME.format(system=system)
            for system in SYSTEMS
        },
        "transaction_receipt": output / TRANSACTION_RECEIPT_FILENAME,
    }


def _exact_existing(paths: Sequence[Path], *, label: str) -> bool:
    existing = [path.exists() or os.path.lexists(path) for path in paths]
    _require(all(existing) or not any(existing), f"partial {label} phase is prohibited")
    return all(existing)


def _candidate_complete_or_resumable(paths: Sequence[Path]) -> bool:
    """Accept only prefixes produced by the candidate receipt-last commit order."""
    _require(len(paths) == 3, "candidate phase path contract is invalid")
    existing = tuple(path.exists() or os.path.lexists(path) for path in paths)
    if existing == (True, True, True):
        return True
    _require(
        existing in {
            (False, False, False),
            (True, False, False),
            (True, True, False),
        },
        "partial candidate phase is not a valid receipt-last prefix",
    )
    return False


def _validate_complete(
    *, root: Path, paths: Mapping[str, Any], dependencies: TransactionDependencies
) -> None:
    try:
        dependencies.validate_complete(
            project_root=root,
            candidate_index_path=paths["candidate_index"],
            candidate_manifest_path=paths["candidate_manifest"],
            candidate_receipt_path=paths["candidate_receipt"],
            bootstrap_mapping_path=paths["bootstrap_mapping"],
            bootstrap_receipt_path=paths["bootstrap_receipt"],
            bootstrap_dir=paths["bootstrap_root"],
        )
    except QualificationTransactionV2Error:
        raise
    except Exception as error:
        raise QualificationTransactionV2Error(
            f"candidate/bootstrap validation failed closed: {error}"
        ) from error


def _validated_fragment_descriptors(
    *,
    root: Path,
    fragment_paths: Mapping[str, Path],
    patch: Mapping[str, Any],
    identity_patch_path: Path | str,
    parity_paths: Mapping[str, Path | str],
    dependencies: TransactionDependencies,
) -> dict[str, dict[str, Any]]:
    _require(set(fragment_paths) == set(SYSTEMS), "fragment system coverage drifted")
    try:
        result = dependencies.validate_fragments(
            project_root=root,
            fragment_paths=fragment_paths,
            identity_patch=patch,
            identity_patch_path=identity_patch_path,
            accepted_model_parity_manifest_path=parity_paths["manifest"],
            accepted_model_parity_assessment_path=parity_paths["assessment"],
            accepted_model_parity_receipt_path=parity_paths["receipt"],
        )
    except QualificationTransactionV2Error:
        raise
    except Exception as error:
        raise QualificationTransactionV2Error(
            f"qualification fragment validation failed closed: {error}"
        ) from error
    _require(
        type(result) is dict and set(result) == set(SYSTEMS),
        "qualification fragment validator coverage drifted",
    )
    normalized: dict[str, dict[str, Any]] = {}
    for system in SYSTEMS:
        observed = file_descriptor(root, fragment_paths[system])
        _require(result[system] == observed, f"{system} fragment descriptor drifted")
        normalized[system] = observed
    return normalized


def _result(paths: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "fragment_paths": {system: paths["fragment_paths"][system] for system in SYSTEMS},
        "candidate_index_path": paths["candidate_index"],
        "candidate_manifest_path": paths["candidate_manifest"],
        "candidate_receipt_path": paths["candidate_receipt"],
        "bootstrap_mapping_path": paths["bootstrap_mapping"],
        "bootstrap_receipt_path": paths["bootstrap_receipt"],
        "bootstrap_dir": paths["bootstrap_root"],
        "transaction_receipt_path": paths["transaction_receipt"],
    }


def _receipt_value(
    *,
    root: Path,
    paths: Mapping[str, Any],
    authorities: Mapping[str, dict[str, Any]],
    patch: Mapping[str, Any],
    parity: Mapping[str, Any],
    fragments: Mapping[str, dict[str, Any]],
) -> dict[str, Any]:
    receipt: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": TRANSACTION_KIND,
        "status": "qualification_inputs_materialized_nonaccepted",
        "scope": "forced_resource_qualification_pilots_only",
        "accepted": False,
        "publication_ready": False,
        "authorization_eligible": False,
        "systems": list(SYSTEMS),
        "cell_count": CELL_COUNT,
        "hardware_resource_collector": authorities[
            "hardware_resource_collector"
        ],
        "image_identity_patch": authorities["image_identity_patch"],
        "image_identity_patch_sha256": patch["patch_sha256"],
        "accepted_model_parity_manifest": authorities[
            "accepted_model_parity_manifest"
        ],
        "accepted_model_parity_assessment": authorities[
            "accepted_model_parity_assessment"
        ],
        "accepted_model_parity_receipt": authorities[
            "accepted_model_parity_receipt"
        ],
        "model_parity_acceptance_binding_sha256": parity["binding_sha256"],
        "model_parity_acceptance_schema_version": parity["schema_version"],
        "image_patch_resolution": {
            "candidate_binding_eligible": patch["candidate_binding_eligible"],
            "resolved_blockers": (
                []
                if patch["candidate_binding_eligible"]
                else list(REFRESH_ONLY_BLOCKERS)
            ),
            "resolution": (
                "unchanged_v3_parity"
                if patch["candidate_binding_eligible"]
                else "physical_patch_bound_v4_parity_refresh"
            ),
        },
        "fragments": {system: fragments[system] for system in SYSTEMS},
        "candidate": {
            "index": file_descriptor(root, paths["candidate_index"]),
            "manifest": file_descriptor(root, paths["candidate_manifest"]),
            "receipt": file_descriptor(root, paths["candidate_receipt"]),
        },
        "bootstrap": {
            "mapping": file_descriptor(root, paths["bootstrap_mapping"]),
            "calibrations": {
                system: file_descriptor(
                    root, paths["bootstrap_calibrations"][system]
                )
                for system in SYSTEMS
            },
            "receipt": file_descriptor(root, paths["bootstrap_receipt"]),
        },
        "blockers": [
            "transaction_is_not_policy_qualification_acceptance",
            "transaction_is_not_full_publication_authority",
            "transaction_requires_exact_32_physical_pilots",
        ],
    }
    receipt["receipt_sha256"] = _self_sha(receipt, "receipt_sha256")
    return receipt


def _materialize_publication_policy_qualification_transaction_v2_held(
    *,
    project_root: Path | str,
    identity_patch_path: Path | str,
    accepted_model_parity_manifest_path: Path | str,
    accepted_model_parity_assessment_path: Path | str,
    accepted_model_parity_receipt_path: Path | str,
    output_root: Path | str,
    docker: str = "docker",
    dependencies: TransactionDependencies = DEFAULT_DEPENDENCIES,
    after_physical_commit_step: Callable[[str, Path], None] | None = None,
) -> dict[str, Any]:
    """Materialize/resume the nonaccepted qualification input transaction."""

    root = _root(project_root)
    _require(type(dependencies) is TransactionDependencies, "dependencies are invalid")
    _require(type(docker) is str and bool(docker) and "\x00" not in docker, "docker is invalid")
    patch, parity, authorities = _load_authorities(
        root=root,
        identity_patch_path=identity_patch_path,
        accepted_model_parity_manifest_path=accepted_model_parity_manifest_path,
        accepted_model_parity_assessment_path=accepted_model_parity_assessment_path,
        accepted_model_parity_receipt_path=accepted_model_parity_receipt_path,
        dependencies=dependencies,
    )
    output = _under_root(root, output_root, label="output_root")
    prospective_receipt = output / TRANSACTION_RECEIPT_FILENAME
    parity_paths = {
        "manifest": accepted_model_parity_manifest_path,
        "assessment": accepted_model_parity_assessment_path,
        "receipt": accepted_model_parity_receipt_path,
    }
    if prospective_receipt.exists() or os.path.lexists(prospective_receipt):
        output = _physical_directory(root, output, label="output_root")
        paths = _phase_paths(output)
        fragments = _validated_fragment_descriptors(
            root=root,
            fragment_paths=paths["fragment_paths"],
            patch=patch,
            identity_patch_path=identity_patch_path,
            parity_paths=parity_paths,
            dependencies=dependencies,
        )
        _validate_complete(root=root, paths=paths, dependencies=dependencies)
        expected = _receipt_value(
            root=root,
            paths=paths,
            authorities=authorities,
            patch=patch,
            parity=parity,
            fragments=fragments,
        )
        _validate_committed_receipt(root=root, paths=paths, expected=expected)
        return _result(paths)

    output = _safe_output_root(root, output)
    paths = _phase_paths(output)
    fragments_root = _mkdir_phase(
        root, paths["fragments_root"], label="fragments root"
    )
    fragment_files = [paths["fragment_paths"][system] for system in SYSTEMS]
    if not _exact_existing(fragment_files, label="fragment"):
        try:
            produced = dependencies.materialize_fragments(
                project_root=root,
                fragments_root=fragments_root,
                identity_patch_path=identity_patch_path,
                accepted_model_parity_manifest_path=(
                    accepted_model_parity_manifest_path
                ),
                accepted_model_parity_assessment_path=(
                    accepted_model_parity_assessment_path
                ),
                accepted_model_parity_receipt_path=(
                    accepted_model_parity_receipt_path
                ),
                docker=docker,
            )
        except QualificationTransactionV2Error:
            raise
        except Exception as error:
            raise QualificationTransactionV2Error(
                f"qualification fragment materialization failed closed: {error}"
            ) from error
        _require(
            type(produced) is dict
            and set(produced) == set(SYSTEMS)
            and all(Path(produced[system]) == paths["fragment_paths"][system] for system in SYSTEMS),
            "fragment materializer returned unexpected paths",
        )
    fragments = _validated_fragment_descriptors(
        root=root,
        fragment_paths=paths["fragment_paths"],
        patch=patch,
        identity_patch_path=identity_patch_path,
        parity_paths=parity_paths,
        dependencies=dependencies,
    )

    candidate_files = [
        paths["candidate_index"],
        paths["candidate_manifest"],
        paths["candidate_receipt"],
    ]
    if not _candidate_complete_or_resumable(candidate_files):
        try:
            candidate = dependencies.build_index(
                project_root=root,
                fragment_paths=paths["fragment_paths"],
                pilot_root=None,
                output_dir=paths["candidate_root"],
            )
        except Exception as error:
            raise QualificationTransactionV2Error(
                f"qualification candidate materialization failed closed: {error}"
            ) from error
        _require(
            type(candidate) is dict
            and candidate.get("index_path") == paths["candidate_index"]
            and candidate.get("candidate_manifest_path") == paths["candidate_manifest"]
            and candidate.get("candidate_receipt_path") == paths["candidate_receipt"],
            "candidate producer returned unexpected paths",
        )

    bootstrap_files = [
        paths["bootstrap_mapping"],
        paths["bootstrap_receipt"],
        *(paths["bootstrap_calibrations"][system] for system in SYSTEMS),
    ]
    if not _exact_existing(bootstrap_files, label="bootstrap"):
        try:
            bootstrap = dependencies.build_bootstrap(
                project_root=root,
                candidate_manifest_path=paths["candidate_manifest"],
                candidate_receipt_path=paths["candidate_receipt"],
                accepted_model_parity_manifest_path=(
                    accepted_model_parity_manifest_path
                ),
                accepted_model_parity_assessment_path=(
                    accepted_model_parity_assessment_path
                ),
                accepted_model_parity_receipt_path=(
                    accepted_model_parity_receipt_path
                ),
                output_dir=paths["bootstrap_root"],
            )
        except Exception as error:
            raise QualificationTransactionV2Error(
                f"qualification bootstrap materialization failed closed: {error}"
            ) from error
        _require(
            type(bootstrap) is dict
            and bootstrap.get("mapping_path") == paths["bootstrap_mapping"]
            and bootstrap.get("receipt_path") == paths["bootstrap_receipt"]
            and bootstrap.get("calibration_paths") == paths["bootstrap_calibrations"],
            "bootstrap producer returned unexpected paths",
        )
    _validate_complete(root=root, paths=paths, dependencies=dependencies)

    second_patch, second_parity, second_authorities = _load_authorities(
        root=root,
        identity_patch_path=identity_patch_path,
        accepted_model_parity_manifest_path=accepted_model_parity_manifest_path,
        accepted_model_parity_assessment_path=accepted_model_parity_assessment_path,
        accepted_model_parity_receipt_path=accepted_model_parity_receipt_path,
        dependencies=dependencies,
    )
    _require(
        second_patch == patch
        and second_parity == parity
        and second_authorities == authorities,
        "qualification authorities changed before receipt commit",
    )
    second_fragments = _validated_fragment_descriptors(
        root=root,
        fragment_paths=paths["fragment_paths"],
        patch=second_patch,
        identity_patch_path=identity_patch_path,
        parity_paths=parity_paths,
        dependencies=dependencies,
    )
    _require(second_fragments == fragments, "qualification fragments changed before receipt commit")
    _validate_complete(root=root, paths=paths, dependencies=dependencies)
    receipt = _receipt_value(
        root=root,
        paths=paths,
        authorities=authorities,
        patch=patch,
        parity=parity,
        fragments=fragments,
    )
    _commit_receipt_atomic(
        paths["transaction_receipt"],
        _canonical(receipt),
        after_physical_commit_step=after_physical_commit_step,
    )
    _validate_committed_receipt(root=root, paths=paths, expected=receipt)
    return _result(paths)


@wraps(_materialize_publication_policy_qualification_transaction_v2_held)
def materialize_publication_policy_qualification_transaction_v2(
    *args: Any, **kwargs: Any
) -> dict[str, Any]:
    """Materialize under held custody, then reopen and cold-validate the commit."""

    _require(not args, "qualification transaction accepts keyword arguments only")
    root = _root(kwargs.get("project_root"))
    try:
        with PhysicalRootCustodyV1.open(
            root, label="qualification transaction project_root"
        ) as held:
            token = _ACTIVE_CUSTODY.set(held)
            try:
                result = _materialize_publication_policy_qualification_transaction_v2_held(
                    **kwargs
                )
                held.verify()
            finally:
                _ACTIVE_CUSTODY.reset(token)
        receipt_path = Path(result["transaction_receipt_path"])
        with PhysicalRootCustodyV1.open(
            root, label="qualification transaction cold project_root"
        ) as cold:
            token = _ACTIVE_CUSTODY.set(cold)
            try:
                _cold_validate_committed_transaction(
                    root=root, receipt_path=receipt_path
                )
                cold.verify()
            finally:
                _ACTIVE_CUSTODY.reset(token)
        return result
    except QualificationTransactionV2Error:
        raise
    except PublicationPhysicalIoV1Error as error:
        raise QualificationTransactionV2Error(
            f"qualification transaction physical custody failed: {error}"
        ) from error


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--identity-patch", type=Path, required=True)
    parser.add_argument("--accepted-model-parity-manifest", type=Path, required=True)
    parser.add_argument("--accepted-model-parity-assessment", type=Path, required=True)
    parser.add_argument("--accepted-model-parity-receipt", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--docker", default="docker")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        result = materialize_publication_policy_qualification_transaction_v2(
            project_root=args.project_root,
            identity_patch_path=args.identity_patch,
            accepted_model_parity_manifest_path=args.accepted_model_parity_manifest,
            accepted_model_parity_assessment_path=args.accepted_model_parity_assessment,
            accepted_model_parity_receipt_path=args.accepted_model_parity_receipt,
            output_root=args.output_root,
            docker=args.docker,
        )
    except (OSError, QualificationTransactionV2Error) as error:
        print(f"qualification input transaction blocked: {error}", file=os.sys.stderr)
        return 78
    print(
        json.dumps(
            {
                key: (
                    {name: str(path) for name, path in value.items()}
                    if type(value) is dict
                    else str(value)
                )
                for key, value in result.items()
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DEFAULT_DEPENDENCIES",
    "HARDWARE_RESOURCE_COLLECTOR_PATH",
    "PATCH_KIND",
    "QualificationTransactionV2Error",
    "SYSTEMS",
    "TRANSACTION_KIND",
    "TRANSACTION_RECEIPT_FILENAME",
    "TransactionDependencies",
    "file_descriptor",
    "materialize_publication_policy_qualification_transaction_v2",
]
