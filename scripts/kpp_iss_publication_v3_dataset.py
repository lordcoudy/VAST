#!/usr/bin/env python3
"""Fail-closed dataset gate for the frozen KPP ISS publication-v3 corpus."""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any

from freeze_kpp_iss_publication_v3 import (
    AUTHORIZATION_BASIS_ID,
    AUTHORIZATION_RECEIPT_DOMAIN,
    DATASET_IDS as _FROZEN_DATASET_IDS,
    FROZEN_FFPROBE,
    FROZEN_MEDIA,
    FROZEN_SOURCE_ARCHIVES,
    FROZEN_SOURCE_RECEIPTS,
    GENERATION_ID,
    MANIFEST_DOMAIN,
    PublicationCorpusFreezeError,
    SOURCE_GENERATION_ID,
    TARGET_ROOT,
    _canonical_bytes,
    _receipt_self_hash,
    _require_plain_chain,
    _stable_payload,
    _strict_json,
    _validate_exact_tree,
    _validate_source_graph,
    _validated_root,
)


DATASET_IDS = copy.deepcopy(_FROZEN_DATASET_IDS)
PUBLICATION_SCOPE = "performance_and_topology_benchmark_results_only"
MANIFEST_PATH = f"{TARGET_ROOT}/kpp_iss_publication_v3_manifest.json"
AUTHORIZATION_PATH = (
    f"{TARGET_ROOT}/kpp_iss_publication_v3_authorization_receipt.json"
)
EXPECTED_MANIFEST_DESCRIPTOR: dict[str, object] = {
    "path": MANIFEST_PATH,
    "size_bytes": 7225,
    "file_sha256": (
        "9a9cf3e08be159bfd4bdeda1d9323b13102980322bde03d9b061e749c1d3fa24"
    ),
    "manifest_sha256": (
        "bbe2cca51cdcc95651492e0f28fc95ed00b9106dce73b5995280259701c91cc2"
    ),
}
EXPECTED_AUTHORIZATION_DESCRIPTOR: dict[str, object] = {
    "path": AUTHORIZATION_PATH,
    "size_bytes": 3300,
    "sha256": (
        "eee7a49472077ff83bd9a9f3cc67a462c4441b0c841bc64d75859271333732ee"
    ),
    "authorization_receipt_sha256": (
        "11678b26210c4ae514535b399afa3ed9f1b412d116d9708c1a94af606cd03d2a"
    ),
}
SOURCE_RECEIPT_DOMAINS: dict[str, bytes] = {
    "extraction": b"VAST:kpp-legacy-iss-extraction-receipt:v1\0",
    "transcode": b"VAST:kpp-legacy-iss-v2-transcode-receipt:v1\0",
    "metadata": b"VAST:kpp-legacy-iss-metadata:v1\0",
    "materialization": b"VAST:kpp-legacy-iss-v2-materialization-receipt:v1\0",
}
_RECEIPT_IDENTITIES = {
    "extraction": (
        "vast_kpp_legacy_iss_extraction_receipt",
        "headless_stream_copy_candidate",
        "kpp_iss_v2_extraction_receipt.json",
    ),
    "transcode": (
        "vast_kpp_legacy_iss_v2_transcode_receipt",
        "pinned_codec_transcode_candidate",
        "kpp_iss_v2_transcode_receipt.json",
    ),
    "metadata": (
        "vast_kpp_legacy_iss_metadata",
        "authoritative_windows_candidate",
        "iss_v2_underbody_metadata.json",
    ),
    "materialization": (
        "vast_kpp_legacy_iss_v2_materialization_receipt",
        "physically_assessed_candidate",
        "kpp_iss_v2_materialization_receipt.json",
    ),
}
EXPECTED_CLAIMS: dict[str, bool] = {
    "publication_authorized": True,
    "publication_scope_performance_and_topology_only": True,
    "accuracy_ground_truth_validated": False,
    "production_routing_validated": False,
    "v1_dataset_identity_equivalent": False,
    "source_timestamps_preserved": False,
    "media_reused_without_retranscode": True,
    "source_receipt_graph_exactly_pinned": True,
    "all_media_bytes_and_ffprobe_contracts_verified": True,
    "output_set_directory_published_atomically": True,
}


class KppIssPublicationV3DatasetError(RuntimeError):
    """Raised when the publication-v3 dataset contract does not verify."""


def document_self_hash(
    value: Mapping[str, object], *, field: str, domain: bytes
) -> str:
    """Return the domain-separated canonical self hash used by frozen receipts."""

    try:
        return _receipt_self_hash(value, field=field, domain=domain)
    except PublicationCorpusFreezeError as exc:
        raise KppIssPublicationV3DatasetError(str(exc)) from exc


def _source_receipt_descriptors() -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for role in ("extraction", "transcode", "metadata", "materialization"):
        pin = FROZEN_SOURCE_RECEIPTS[role]
        installed_name = _RECEIPT_IDENTITIES[role][2]
        result.append(
            {
                "role": role,
                "source_path": pin["source_path"],
                "path": f"{TARGET_ROOT}/receipts/{installed_name}",
                "size_bytes": pin["size_bytes"],
                "sha256": pin["sha256"],
                "self_hash_field": pin["self_hash_field"],
                "self_hash": pin["self_hash"],
            }
        )
    return result


EXPECTED_SOURCE_RECEIPTS = _source_receipt_descriptors()


def _media_descriptor(codec: str, role: str) -> dict[str, object]:
    pin = FROZEN_MEDIA[(codec, role)]
    return {
        "codec_variant": codec,
        "role": role,
        "source_path": pin["source_path"],
        "path": f"{TARGET_ROOT}/{codec}/iss_v2_{role}.mp4",
        "size_bytes": pin["size_bytes"],
        "sha256": pin["sha256"],
    }


def _selected_media(codec: str) -> list[dict[str, object]]:
    return [
        _media_descriptor(codec, role)
        for role in ("underbody", "front_gate")
    ]


_PLAYBACK = {
    "contract_version": 1,
    "encoded_timeline_fps": 600,
    "offered_playback_fps": 1,
    "selection_basis": (
        "discarded_prebenchmark_capacity_pilots_positive_completed_frames_"
        "guardrail_no_effect_estimation"
    ),
    "timestamp_scale": 600,
}
_ROUTING_PROFILES = [
    {
        "name": "architecture_reuse_all_branches_v1",
        "production_semantics": False,
        "routing_mode": "all_branches_per_stream",
        "scope": "topology_only_stress",
    }
]
_TIMESTAMP_CONTRACT = {
    "accuracy_ground_truth": False,
    "clock_domains": {
        "frame_clock": {
            "epoch": None,
            "present_only_when_observed": True,
            "source": "tag_4_frame_time_and_magnet_time_integers",
            "unit": None,
        },
        "header_clock": {
            "resolution": "millisecond",
            "source": "record_header_8xu16_calendar_fields",
            "timezone": None,
        },
    },
    "clock_domains_equated": False,
    "demuxed_or_decoded_frame_index_alignment": "not_claimed",
    "derived_codec_frame_index_alignment": "not_claimed",
    "event_semantics_validated": False,
    "frame_clock_epoch_validated": False,
    "frame_clock_unit_validated": False,
    "metadata_scope": "underbody_source_avi_only",
    "schema_version": 1,
    "source_timestamps_preserved": False,
    "timestamps_interpolated": False,
    "timezone_validated": False,
    "underbody_avi_physical_movi_packet_index_alignment": (
        "validated_exact_physical_packet_sequence"
    ),
    "video_timeline_authority": "receipt_bound_pinned_ffprobe_validation",
    "video_timeline_policy": "cfr_600_from_source_pts",
}
_PREDECESSOR_IDENTITIES = {
    "h264": "7e17965a9dbdaafb2a9f78301d2939b4a5342b779b75161b0f7ae78b2aa14374",
    "h265": "7716333249ad9afcad485b9b08ef4aadb975edbdcfa9dca9f6f005e79e70d1f1",
}


def _stream(codec: str, stream_id: int) -> dict[str, object]:
    role = "underbody" if stream_id == 5 else "front_gate"
    pin = FROZEN_MEDIA[(codec, role)]
    front_roles = ("plate_number", "plate_number", "vehicle_type", "damage", "damage")
    return {
        "avg_frame_rate": "600/1",
        "camera_role": "foreign_object" if role == "underbody" else front_roles[stream_id],
        "codec_name": "h264" if codec == "h264" else "hevc",
        "container": "mp4",
        "duration_s": 59.41 if role == "underbody" else 55.2,
        "fps_policy": "cfr_600_from_source_pts",
        "frame_count": 35646 if role == "underbody" else 33120,
        "height": 236 if role == "underbody" else 1080,
        "path": f"{TARGET_ROOT}/{codec}/iss_v2_{role}.mp4",
        "pix_fmt": "yuv420p",
        "r_frame_rate": "600/1",
        "sha256": pin["sha256"],
        "source_id": f"kpp_iss_publication_v3_{role}",
        "source_path": str(pin["source_path"]),
        "stream_id": stream_id,
        "width": 1700 if role == "underbody" else 1920,
    }


def _expected_entry(codec: str) -> dict[str, object]:
    predecessor = f"kpp_legacy_iss_v2_{codec}"
    return {
        "analytics_routing": "unresolved",
        "annotations": {
            "accuracy_ground_truth": False,
            "normalization_receipt_sha256": FROZEN_SOURCE_RECEIPTS["metadata"]["self_hash"],
            "path": f"{TARGET_ROOT}/receipts/iss_v2_underbody_metadata.json",
            "sha256": FROZEN_SOURCE_RECEIPTS["metadata"]["sha256"],
            "use": "underbody_foreign_object_events_and_realism_metadata_only",
        },
        "benchmark_playback": copy.deepcopy(_PLAYBACK),
        "codec_variant": codec,
        "dataset_contract_version": 3,
        "description": (
            f"Frozen KPP ISS publication-v3 {codec.upper()} corpus authorized "
            "for performance and topology benchmark results only."
        ),
        "experimental_routing_profiles": copy.deepcopy(_ROUTING_PROFILES),
        "fps_policy": "cfr_600_from_source_pts",
        "generation_id": GENERATION_ID,
        "kind": "frozen_publication_codec_corpus",
        "lineage": {
            "identity_equivalent": False,
            "predecessor_dataset": predecessor,
            "predecessor_manifest_identity_schema_version": 1,
            "predecessor_manifest_identity_sha256": _PREDECESSOR_IDENTITIES[codec],
            "reason": (
                "distinct_authorized_publication_identity_reusing_exact_"
                "receipt_pinned_media_bytes"
            ),
        },
        "logical_stream_instances": 6,
        "preparation": {
            "mode": "check_only_frozen_publication_v3",
            "publication_manifest": copy.deepcopy(EXPECTED_MANIFEST_DESCRIPTOR),
        },
        "provenance": {
            "artifact_kind": "vast_kpp_iss_publication_v3_dataset_provenance",
            "schema_version": 1,
            "generation_id": GENERATION_ID,
            "publication_manifest": copy.deepcopy(EXPECTED_MANIFEST_DESCRIPTOR),
            "authorization_receipt": copy.deepcopy(EXPECTED_AUTHORIZATION_DESCRIPTOR),
            "source_generation": {
                "generation_id": SOURCE_GENERATION_ID,
                "identity_equivalent": False,
            },
            "source_receipts": copy.deepcopy(EXPECTED_SOURCE_RECEIPTS),
            "media_artifacts": _selected_media(codec),
            "claims": copy.deepcopy(EXPECTED_CLAIMS),
        },
        "publication_scope": PUBLICATION_SCOPE,
        "publishable": True,
        "source_dataset": predecessor,
        "status": "frozen_publication_corpus",
        "streams": [_stream(codec, index) for index in range(6)],
        "timestamp_contract": copy.deepcopy(_TIMESTAMP_CONTRACT),
        "unique_recorded_sources": 2,
        "workload_scope": "replicated_logical_streams_from_two_recordings",
    }


def _codec_for_name(name: str) -> str | None:
    for codec, dataset_id in DATASET_IDS.items():
        if name == dataset_id:
            return codec
    return None


def _fail(message: str) -> None:
    raise KppIssPublicationV3DatasetError(message)


def _validate_entry(name: str, entry: Mapping[str, object]) -> str:
    codec = _codec_for_name(name)
    if codec is None:
        _fail(f"{name!r} is not a publication-v3 dataset id")
    if type(entry) is not dict or entry != _expected_entry(codec):
        _fail(f"dataset {name!r} publication-v3 YAML contract drifted")
    return codec


def _validate_source_receipts(
    receipts: Mapping[str, Mapping[str, object]],
) -> dict[str, dict[str, object]]:
    expected_by_role = {str(item["role"]): item for item in EXPECTED_SOURCE_RECEIPTS}
    if type(receipts) is not dict or set(receipts) != set(expected_by_role):
        _fail("publication-v3 source receipt set is not exact")
    validated: dict[str, dict[str, object]] = {}
    for role in ("extraction", "transcode", "metadata", "materialization"):
        raw = receipts[role]
        if type(raw) is not dict:
            _fail(f"{role} source receipt is not an object")
        value = dict(raw)
        descriptor = expected_by_role[role]
        artifact_kind, status, _ = _RECEIPT_IDENTITIES[role]
        if (
            value.get("schema_version") != 1
            or type(value.get("schema_version")) is not int
            or value.get("artifact_kind") != artifact_kind
            or value.get("generation_id") != SOURCE_GENERATION_ID
            or value.get("status") != status
        ):
            _fail(f"{role} source receipt identity or status drifted")
        self_field = str(descriptor["self_hash_field"])
        observed = value.get(self_field)
        computed = document_self_hash(
            value, field=self_field, domain=SOURCE_RECEIPT_DOMAINS[role]
        )
        if observed != descriptor["self_hash"] or computed != descriptor["self_hash"]:
            _fail(f"{role} source receipt self hash drifted")
        claims = value.get("claims")
        if not isinstance(claims, Mapping):
            _fail(f"{role} source receipt claims are invalid")
        for field in (
            "publication_authorized",
            "v1_dataset_identity_equivalent",
            "accuracy_ground_truth_validated",
        ):
            if field in claims and claims.get(field) is not False:
                _fail(f"{role} source receipt makes forbidden claim {field}")
        if role != "materialization":
            if any(
                claims.get(field) is not False
                for field in (
                    "publication_authorized",
                    "v1_dataset_identity_equivalent",
                    "accuracy_ground_truth_validated",
                )
            ):
                _fail(f"{role} source receipt omits a required false claim")
        elif (
            value.get("publishable") is not False
            or value.get("publication_authorized") is not False
            or claims.get("publishable") is not False
            or claims.get("publication_authorized") is not False
        ):
            _fail("materialization source receipt old publication claims drifted")
        validated[role] = value
    return validated


def validate_kpp_iss_publication_v3_documents(
    name: str,
    entry: Mapping[str, object],
    manifest: Mapping[str, object],
    authorization: Mapping[str, object],
    receipts: Mapping[str, Mapping[str, object]],
) -> bool:
    """Validate all claim-bearing v3 documents without consulting the filesystem."""

    codec = _validate_entry(name, entry)
    if type(manifest) is not dict:
        _fail("publication-v3 manifest is not an object")
    expected_manifest_keys = {
        "schema_version",
        "artifact_kind",
        "generation_id",
        "status",
        "dataset_root",
        "dataset_ids",
        "datasets",
        "source_generation",
        "source_archives",
        "source_receipts",
        "ffprobe",
        "media_artifacts",
        "authorization_receipt",
        "claims",
        "manifest_sha256",
    }
    if set(manifest) != expected_manifest_keys:
        _fail("publication-v3 manifest schema is not exact")
    if (
        manifest.get("schema_version") != 1
        or type(manifest.get("schema_version")) is not int
        or manifest.get("artifact_kind") != "vast_kpp_iss_publication_v3_manifest"
        or manifest.get("generation_id") != GENERATION_ID
        or manifest.get("status") != "frozen_publication_corpus"
        or manifest.get("dataset_root") != TARGET_ROOT
        or manifest.get("dataset_ids") != DATASET_IDS
        or manifest.get("source_generation")
        != {"generation_id": SOURCE_GENERATION_ID, "identity_equivalent": False}
        or manifest.get("source_archives") != FROZEN_SOURCE_ARCHIVES
        or manifest.get("source_receipts") != EXPECTED_SOURCE_RECEIPTS
        or manifest.get("ffprobe") != {"role": "ffprobe", **FROZEN_FFPROBE}
        or manifest.get("authorization_receipt") != EXPECTED_AUTHORIZATION_DESCRIPTOR
        or manifest.get("claims") != EXPECTED_CLAIMS
    ):
        _fail("publication-v3 manifest identity, pins, or claims drifted")
    expected_datasets = [
        {
            "dataset_id": DATASET_IDS[variant],
            "codec_variant": variant,
            "publication_scope": PUBLICATION_SCOPE,
            "analytics_routing": "unresolved",
            "accuracy_ground_truth": False,
            "physical_stream_paths": [
                f"{TARGET_ROOT}/{variant}/iss_v2_{role}.mp4"
                for role in ("underbody", "front_gate")
            ],
        }
        for variant in ("h264", "h265")
    ]
    if manifest.get("datasets") != expected_datasets:
        _fail("publication-v3 dataset projection drifted")
    observed_manifest_self_hash = manifest.get("manifest_sha256")
    computed_manifest_self_hash = document_self_hash(
        manifest, field="manifest_sha256", domain=MANIFEST_DOMAIN
    )
    if (
        observed_manifest_self_hash != EXPECTED_MANIFEST_DESCRIPTOR["manifest_sha256"]
        or computed_manifest_self_hash != observed_manifest_self_hash
    ):
        _fail("publication-v3 manifest self hash drifted")

    if type(authorization) is not dict:
        _fail("publication-v3 authorization receipt is not an object")
    expected_authorization = {
        "schema_version": 1,
        "artifact_kind": "vast_kpp_iss_publication_v3_authorization_receipt",
        "generation_id": GENERATION_ID,
        "dataset_ids": copy.deepcopy(DATASET_IDS),
        "status": "authorized_for_performance_publication",
        "authorization_basis": {
            "kind": "explicit_user_instruction",
            "basis_id": AUTHORIZATION_BASIS_ID,
            "authorized_scope": PUBLICATION_SCOPE,
            "excluded_scopes": [
                "accuracy_evaluation",
                "production_routing_validation",
                "v1_dataset_equivalence",
            ],
        },
        "source_generation": {
            "generation_id": SOURCE_GENERATION_ID,
            "identity_equivalent": False,
        },
        "source_archives": copy.deepcopy(FROZEN_SOURCE_ARCHIVES),
        "source_receipts": copy.deepcopy(EXPECTED_SOURCE_RECEIPTS),
        "claims": copy.deepcopy(EXPECTED_CLAIMS),
        "authorization_receipt_sha256": EXPECTED_AUTHORIZATION_DESCRIPTOR[
            "authorization_receipt_sha256"
        ],
    }
    if authorization != expected_authorization:
        _fail("publication-v3 authorization receipt drifted")
    computed_authorization_self_hash = document_self_hash(
        authorization,
        field="authorization_receipt_sha256",
        domain=AUTHORIZATION_RECEIPT_DOMAIN,
    )
    if computed_authorization_self_hash != authorization["authorization_receipt_sha256"]:
        _fail("publication-v3 authorization receipt self hash drifted")

    validated_receipts = _validate_source_receipts(receipts)
    by_role = {str(item["role"]): item for item in EXPECTED_SOURCE_RECEIPTS}
    manifest_media = manifest.get("media_artifacts")
    if type(manifest_media) is not list:
        _fail("publication-v3 manifest media_artifacts is invalid")
    ffprobe_by_identity: dict[tuple[str, str], object] = {}
    for raw in manifest_media:
        if type(raw) is not dict:
            _fail("publication-v3 manifest media artifact is invalid")
        identity = (str(raw.get("codec_variant", "")), str(raw.get("role", "")))
        if identity in ffprobe_by_identity:
            _fail("publication-v3 manifest media identity is duplicated")
        ffprobe_by_identity[identity] = raw.get("ffprobe")
    pins = {
        "source_archives": copy.deepcopy(FROZEN_SOURCE_ARCHIVES),
        "receipts": copy.deepcopy(FROZEN_SOURCE_RECEIPTS),
        "media": {
            identity: {**copy.deepcopy(pin), "media": ffprobe_by_identity.get(identity)}
            for identity, pin in FROZEN_MEDIA.items()
        },
        "ffprobe": copy.deepcopy(FROZEN_FFPROBE),
    }
    try:
        normalized = _validate_source_graph(
            validated_receipts,
            pins=pins,
            receipt_descriptors=by_role,
        )
    except PublicationCorpusFreezeError as exc:
        raise KppIssPublicationV3DatasetError(str(exc)) from exc
    expected_media = []
    for variant in ("h264", "h265"):
        for role in ("underbody", "front_gate"):
            expected_media.append(
                {
                    **_media_descriptor(variant, role),
                    "ffprobe": copy.deepcopy(normalized[(variant, role)]["media"]),
                }
            )
    if manifest_media != expected_media:
        _fail("publication-v3 media artifact graph drifted")
    if entry["provenance"]["media_artifacts"] != _selected_media(codec):
        _fail(f"dataset {name!r} selected media provenance drifted")
    return True


def _read_pinned_json(
    root: Path,
    descriptor: Mapping[str, object],
    *,
    label: str,
    file_hash_field: str,
) -> dict[str, Any]:
    relative = str(descriptor["path"])
    path = root.joinpath(*PurePosixPath(relative).parts)
    _require_plain_chain(root, path)
    size, digest, payload = _stable_payload(path, label=label, retain=True)
    if size != descriptor["size_bytes"] or digest != descriptor[file_hash_field]:
        _fail(f"{label} does not match its external byte pin")
    assert payload is not None
    try:
        return _strict_json(payload, label=label)
    except PublicationCorpusFreezeError as exc:
        raise KppIssPublicationV3DatasetError(str(exc)) from exc


def validate_kpp_iss_publication_v3_manifest_entry(
    name: str,
    entry: Mapping[str, object],
    *,
    project_root: Path,
    require_files: bool,
) -> bool:
    """Validate one v3 entry; return False unchanged for all other datasets."""

    if _codec_for_name(name) is None:
        return False
    _validate_entry(name, entry)
    if not require_files:
        return True
    try:
        root = _validated_root(project_root)
        corpus = root.joinpath(*PurePosixPath(TARGET_ROOT).parts)
        _require_plain_chain(root, corpus)
        _validate_exact_tree(corpus)
        manifest = _read_pinned_json(
            root,
            EXPECTED_MANIFEST_DESCRIPTOR,
            label="publication-v3 manifest",
            file_hash_field="file_sha256",
        )
        authorization = _read_pinned_json(
            root,
            EXPECTED_AUTHORIZATION_DESCRIPTOR,
            label="publication-v3 authorization receipt",
            file_hash_field="sha256",
        )
        receipts: dict[str, dict[str, Any]] = {}
        for descriptor in EXPECTED_SOURCE_RECEIPTS:
            role = str(descriptor["role"])
            receipts[role] = _read_pinned_json(
                root,
                descriptor,
                label=f"publication-v3 {role} source receipt",
                file_hash_field="sha256",
            )
        for variant in ("h264", "h265"):
            for role in ("underbody", "front_gate"):
                descriptor = _media_descriptor(variant, role)
                relative = str(descriptor["path"])
                path = root.joinpath(*PurePosixPath(relative).parts)
                _require_plain_chain(root, path)
                size, digest, _ = _stable_payload(
                    path,
                    label=f"publication-v3 {variant}/{role} media",
                    retain=False,
                )
                if size != descriptor["size_bytes"] or digest != descriptor["sha256"]:
                    _fail(f"publication-v3 {variant}/{role} media drifted")
        validate_kpp_iss_publication_v3_documents(
            name, entry, manifest, authorization, receipts
        )
        _validate_exact_tree(corpus)
    except KppIssPublicationV3DatasetError:
        raise
    except PublicationCorpusFreezeError as exc:
        raise KppIssPublicationV3DatasetError(str(exc)) from exc
    return True

