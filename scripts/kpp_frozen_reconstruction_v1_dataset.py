#!/usr/bin/env python3
"""Fail-closed catalog and filesystem gate for KPP reconstruction v1."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from pathlib import Path, PurePosixPath

from freeze_kpp_frozen_reconstruction_v1 import (
    AUTHORIZATION_BASIS_ID,
    AUTHORIZATION_RECEIPT_DOMAIN,
    AUTHORIZATION_RECEIPT_NAME,
    DATASET_IDS,
    GENERATION_ID,
    HISTORICAL_DATASET_IDS,
    MANIFEST_DOMAIN,
    MANIFEST_NAME,
    ReconstructionFreezeError,
    SOURCE_AUTHORIZATION_NAME,
    SOURCE_DATASET_IDS,
    SOURCE_GENERATION_ID,
    SOURCE_MANIFEST_NAME,
    SOURCE_MEDIA,
    SOURCE_RECEIPTS,
    TARGET_ROOT,
    _claims,
    _historical_v1,
    _receipt_self_hash,
    _stable_payload,
    _strict_json,
    _validate_tree,
)
from freeze_kpp_iss_publication_v3 import PublicationCorpusFreezeError


PUBLICATION_SCOPE = "performance_and_topology_benchmark_results_only"
EXPECTED_MANIFEST_DESCRIPTOR = {
    "path": f"{TARGET_ROOT}/{MANIFEST_NAME}",
    "size_bytes": 5751,
    "file_sha256": "043cb90be4a16bbc0d636236a6a2c5d2c63f187d94aadf8358c9871bf8e6751a",
    "manifest_sha256": "faf79f71bb53356f95155491a560ca73bb321f9342712e5fab6bc45f7cee5cff",
}
EXPECTED_AUTHORIZATION_DESCRIPTOR = {
    "path": f"{TARGET_ROOT}/{AUTHORIZATION_RECEIPT_NAME}",
    "size_bytes": 2431,
    "sha256": "9eec424ef1112efc46283d9dd644782d3e6f67184f32cda7eada73c8bbfec803",
    "authorization_receipt_sha256": (
        "c6570bbcaf1f8daea450f8510b5141b781d715ecdc0995ed4f3ae5350f7b0f53"
    ),
}


class KppFrozenReconstructionV1DatasetError(RuntimeError):
    """Raised when reconstruction identity or bytes do not verify."""


def _fail(message: str) -> None:
    raise KppFrozenReconstructionV1DatasetError(message)


def _target_media(codec: str, role: str) -> dict[str, object]:
    source = SOURCE_MEDIA[(codec, role)]
    return {
        "codec_variant": codec,
        "role": role,
        "source_path": source["source_path"],
        "path": f"{TARGET_ROOT}/{codec}/iss_v2_{role}.mp4",
        "size_bytes": source["size_bytes"],
        "sha256": source["sha256"],
    }


def _source_documents() -> dict[str, object]:
    return {
        "manifest": {
            "source_path": f"data/videos/kpp/kpp_iss_publication_v3/{SOURCE_MANIFEST_NAME}",
            "path": f"{TARGET_ROOT}/receipts/{SOURCE_MANIFEST_NAME}",
            "size_bytes": 7225,
            "sha256": "9a9cf3e08be159bfd4bdeda1d9323b13102980322bde03d9b061e749c1d3fa24",
            "manifest_sha256": "bbe2cca51cdcc95651492e0f28fc95ed00b9106dce73b5995280259701c91cc2",
        },
        "authorization": {
            "source_path": f"data/videos/kpp/kpp_iss_publication_v3/{SOURCE_AUTHORIZATION_NAME}",
            "path": f"{TARGET_ROOT}/receipts/{SOURCE_AUTHORIZATION_NAME}",
            "size_bytes": 3300,
            "sha256": "eee7a49472077ff83bd9a9f3cc67a462c4441b0c841bc64d75859271333732ee",
            "authorization_receipt_sha256": (
                "11678b26210c4ae514535b399afa3ed9f1b412d116d9708c1a94af606cd03d2a"
            ),
        },
    }


def _source_publication() -> dict[str, object]:
    return {
        "generation_id": SOURCE_GENERATION_ID,
        "dataset_ids": copy.deepcopy(SOURCE_DATASET_IDS),
        "generation_identity_equivalent": False,
        "media_bytes_reused_exactly": True,
        **_source_documents(),
    }


def _installed_receipts() -> list[dict[str, object]]:
    return [
        {
            "source_path": item["source_path"],
            "path": f"{TARGET_ROOT}/receipts/{item['installed_name']}",
            "size_bytes": item["size_bytes"],
            "sha256": item["sha256"],
        }
        for item in SOURCE_RECEIPTS
    ]


def _datasets() -> list[dict[str, object]]:
    return [
        {
            "dataset_id": DATASET_IDS[codec],
            "codec_variant": codec,
            "publication_scope": PUBLICATION_SCOPE,
            "accuracy_ground_truth": False,
            "production_routing_validated": False,
            "historical_v1_identity_equivalent": False,
            "physical_stream_paths": [
                f"{TARGET_ROOT}/{codec}/iss_v2_{role}.mp4"
                for role in ("underbody", "front_gate")
            ],
        }
        for codec in ("h264", "h265")
    ]


def validate_kpp_frozen_reconstruction_v1_documents(
    manifest: Mapping[str, object], authorization: Mapping[str, object]
) -> bool:
    """Validate claim-bearing reconstruction documents without filesystem I/O."""

    if type(manifest) is not dict or set(manifest) != {
        "schema_version",
        "artifact_kind",
        "generation_id",
        "status",
        "dataset_root",
        "dataset_ids",
        "datasets",
        "historical_v1",
        "source_publication",
        "source_receipts",
        "media_artifacts",
        "authorization_receipt",
        "claims",
        "manifest_sha256",
    }:
        _fail("reconstruction manifest schema is not exact")
    if manifest.get("claims") != _claims():
        if isinstance(manifest.get("claims"), Mapping) and manifest["claims"].get(
            "historical_v1_dataset_identity_equivalent"
        ) is not False:
            _fail("historical v1 identity claim is forbidden")
        _fail("reconstruction manifest claims drifted")
    computed_manifest = _receipt_self_hash(
        manifest, field="manifest_sha256", domain=MANIFEST_DOMAIN
    )
    if computed_manifest != manifest.get("manifest_sha256"):
        _fail("reconstruction manifest self hash drifted")
    expected_manifest = {
        "schema_version": 1,
        "artifact_kind": "vast_kpp_frozen_reconstruction_v1_manifest",
        "generation_id": GENERATION_ID,
        "status": "frozen_distinct_reconstruction",
        "dataset_root": TARGET_ROOT,
        "dataset_ids": copy.deepcopy(DATASET_IDS),
        "datasets": _datasets(),
        "historical_v1": _historical_v1(),
        "source_publication": _source_publication(),
        "source_receipts": _installed_receipts(),
        "media_artifacts": [
            _target_media(codec, role)
            for codec in ("h264", "h265")
            for role in ("underbody", "front_gate")
        ],
        "authorization_receipt": copy.deepcopy(EXPECTED_AUTHORIZATION_DESCRIPTOR),
        "claims": _claims(),
        "manifest_sha256": EXPECTED_MANIFEST_DESCRIPTOR["manifest_sha256"],
    }
    if manifest != expected_manifest:
        _fail("reconstruction manifest identity or graph drifted")

    if type(authorization) is not dict or set(authorization) != {
        "schema_version",
        "artifact_kind",
        "generation_id",
        "dataset_ids",
        "status",
        "authorization_basis",
        "historical_v1",
        "source_publication",
        "claims",
        "authorization_receipt_sha256",
    }:
        _fail("reconstruction authorization schema is not exact")
    expected_authorization = {
        "schema_version": 1,
        "artifact_kind": "vast_kpp_frozen_reconstruction_v1_authorization_receipt",
        "generation_id": GENERATION_ID,
        "dataset_ids": copy.deepcopy(DATASET_IDS),
        "status": "authorized_reconstruction_for_performance_publication",
        "authorization_basis": {
            "kind": "explicit_user_instruction",
            "basis_id": AUTHORIZATION_BASIS_ID,
            "authorized_scope": PUBLICATION_SCOPE,
            "excluded_scopes": [
                "accuracy_evaluation",
                "production_routing_validation",
                "historical_v1_identity_equivalence",
            ],
        },
        "historical_v1": _historical_v1(),
        "source_publication": _source_publication(),
        "claims": _claims(),
        "authorization_receipt_sha256": EXPECTED_AUTHORIZATION_DESCRIPTOR[
            "authorization_receipt_sha256"
        ],
    }
    if authorization != expected_authorization:
        _fail("reconstruction authorization identity or claims drifted")
    computed_authorization = _receipt_self_hash(
        authorization,
        field="authorization_receipt_sha256",
        domain=AUTHORIZATION_RECEIPT_DOMAIN,
    )
    if computed_authorization != authorization["authorization_receipt_sha256"]:
        _fail("reconstruction authorization self hash drifted")
    return True


def _stream_expectations(codec: str) -> list[dict[str, object]]:
    result = []
    roles = ("plate_number", "plate_number", "vehicle_type", "damage", "damage")
    for stream_id in range(6):
        underbody = stream_id == 5
        role = "underbody" if underbody else "front_gate"
        result.append(
            {
                "stream_id": stream_id,
                "camera_role": "foreign_object" if underbody else roles[stream_id],
                "path": f"{TARGET_ROOT}/{codec}/iss_v2_{role}.mp4",
                "sha256": SOURCE_MEDIA[(codec, role)]["sha256"],
                "codec_name": "h264" if codec == "h264" else "hevc",
                "width": 1700 if underbody else 1920,
                "height": 236 if underbody else 1080,
                "frame_count": 35646 if underbody else 33120,
            }
        )
    return result


def _validate_entry(name: str, entry: Mapping[str, object]) -> str:
    inverse = {dataset_id: codec for codec, dataset_id in DATASET_IDS.items()}
    codec = inverse.get(name)
    if codec is None:
        _fail(f"unknown reconstruction dataset {name!r}")
    if not isinstance(entry, Mapping):
        _fail(f"dataset {name!r} is not an object")
    expected_scalars = {
        "kind": "frozen_reconstruction_codec_corpus",
        "generation_id": GENERATION_ID,
        "status": "frozen_distinct_reconstruction",
        "publishable": True,
        "publication_scope": PUBLICATION_SCOPE,
        "codec_variant": codec,
        "analytics_routing": "unresolved",
        "logical_stream_instances": 6,
        "unique_recorded_sources": 2,
        "fps_policy": "cfr_600_from_source_pts",
        "source_dataset": SOURCE_DATASET_IDS[codec],
    }
    for field, expected in expected_scalars.items():
        if entry.get(field) != expected:
            _fail(f"dataset {name!r} field {field!r} drifted")
    preparation = entry.get("preparation")
    if not isinstance(preparation, Mapping) or dict(preparation) != {
        "mode": "check_only_frozen_reconstruction_v1",
        "reconstruction_manifest": copy.deepcopy(EXPECTED_MANIFEST_DESCRIPTOR),
    }:
        _fail(f"dataset {name!r} preparation gate drifted")
    provenance = entry.get("provenance")
    expected_provenance = {
        "schema_version": 1,
        "artifact_kind": "vast_kpp_frozen_reconstruction_v1_dataset_provenance",
        "generation_id": GENERATION_ID,
        "reconstruction_manifest": copy.deepcopy(EXPECTED_MANIFEST_DESCRIPTOR),
        "authorization_receipt": copy.deepcopy(EXPECTED_AUTHORIZATION_DESCRIPTOR),
        "historical_v1": _historical_v1(),
        "source_publication": {
            "generation_id": SOURCE_GENERATION_ID,
            "dataset_id": SOURCE_DATASET_IDS[codec],
            "generation_identity_equivalent": False,
            "media_bytes_reused_exactly": True,
        },
        "media_artifacts": [
            _target_media(codec, role) for role in ("underbody", "front_gate")
        ],
        "claims": _claims(),
    }
    if not isinstance(provenance, Mapping) or dict(provenance) != expected_provenance:
        _fail(f"dataset {name!r} provenance drifted")
    streams = entry.get("streams")
    if type(streams) is not list or len(streams) != 6:
        _fail(f"dataset {name!r} stream set is not exact")
    for raw, expected in zip(streams, _stream_expectations(codec), strict=True):
        if type(raw) is not dict:
            _fail(f"dataset {name!r} stream is invalid")
        for field, value in expected.items():
            if raw.get(field) != value:
                _fail(f"dataset {name!r} stream {expected['stream_id']} drifted")
    return codec


def _read_pinned_json(
    root: Path, descriptor: Mapping[str, object], *, label: str, hash_field: str
):
    path = root.joinpath(*PurePosixPath(str(descriptor["path"])).parts)
    try:
        size, digest, payload = _stable_payload(path, label=label, retain=True)
        if size != descriptor["size_bytes"] or digest != descriptor[hash_field]:
            _fail(f"{label} byte pin drifted")
        assert payload is not None
        return _strict_json(payload, label=label)
    except PublicationCorpusFreezeError as exc:
        raise KppFrozenReconstructionV1DatasetError(str(exc)) from exc


def _verify_descriptor(root: Path, descriptor: Mapping[str, object], *, label: str):
    path = root.joinpath(*PurePosixPath(str(descriptor["path"])).parts)
    try:
        size, digest, _ = _stable_payload(path, label=label, retain=False)
    except PublicationCorpusFreezeError as exc:
        raise KppFrozenReconstructionV1DatasetError(str(exc)) from exc
    if size != descriptor["size_bytes"] or digest != descriptor["sha256"]:
        _fail(f"{label} byte pin drifted")


def validate_kpp_frozen_reconstruction_v1_manifest_entry(
    name: str,
    entry: Mapping[str, object],
    *,
    project_root: Path,
    require_files: bool,
) -> bool:
    """Validate one reconstruction entry; ignore every unrelated dataset."""

    if name not in DATASET_IDS.values():
        return False
    codec = _validate_entry(name, entry)
    if not require_files:
        return True
    root = project_root.absolute()
    corpus = root.joinpath(*PurePosixPath(TARGET_ROOT).parts)
    try:
        _validate_tree(corpus, SOURCE_RECEIPTS)
    except (OSError, ReconstructionFreezeError) as exc:  # type: ignore[name-defined]
        raise KppFrozenReconstructionV1DatasetError(str(exc)) from exc
    manifest = _read_pinned_json(
        root,
        EXPECTED_MANIFEST_DESCRIPTOR,
        label="reconstruction manifest",
        hash_field="file_sha256",
    )
    authorization = _read_pinned_json(
        root,
        EXPECTED_AUTHORIZATION_DESCRIPTOR,
        label="reconstruction authorization",
        hash_field="sha256",
    )
    validate_kpp_frozen_reconstruction_v1_documents(manifest, authorization)
    for descriptor in manifest["media_artifacts"]:
        _verify_descriptor(root, descriptor, label="reconstruction media")
    for descriptor in manifest["source_receipts"]:
        _verify_descriptor(root, descriptor, label="reconstruction source receipt")
    source = manifest["source_publication"]
    for role in ("manifest", "authorization"):
        _verify_descriptor(root, source[role], label=f"embedded source {role}")
    selected = [_target_media(codec, role) for role in ("underbody", "front_gate")]
    if entry["provenance"]["media_artifacts"] != selected:
        _fail(f"dataset {name!r} selected media drifted")
    return True


__all__ = [
    "AUTHORIZATION_RECEIPT_NAME",
    "DATASET_IDS",
    "EXPECTED_AUTHORIZATION_DESCRIPTOR",
    "EXPECTED_MANIFEST_DESCRIPTOR",
    "GENERATION_ID",
    "KppFrozenReconstructionV1DatasetError",
    "MANIFEST_NAME",
    "TARGET_ROOT",
    "validate_kpp_frozen_reconstruction_v1_documents",
    "validate_kpp_frozen_reconstruction_v1_manifest_entry",
]
