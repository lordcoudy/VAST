#!/usr/bin/env python3
"""Freeze a distinct KPP reconstruction when historical v1 bytes are absent.

This is not an identity recovery of ``kpp_real_*``. It copies the already
frozen publication-v3 media and receipt graph into a standalone generation and
authorizes only performance/topology publication.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import stat
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from extract_kpp_legacy_iss import ExtractionError, _create_private_working_directory
from freeze_kpp_iss_publication_v3 import (
    AUTHORIZATION_RECEIPT_DOMAIN as SOURCE_AUTHORIZATION_DOMAIN,
    MANIFEST_DOMAIN as SOURCE_MANIFEST_DOMAIN,
    PublicationCorpusFreezeError,
    _canonical_bytes,
    _is_link_or_reparse,
    _lexists,
    _receipt_self_hash,
    _require_plain_chain,
    _stable_payload,
    _strict_json,
    _validated_root,
)
from freeze_kpp_legacy_iss_v2_transcodes import (
    TranscodeFreezeError,
    _atomic_publish_directory,
    _copy_pinned_snapshot,
)


GENERATION_ID = "kpp_frozen_reconstruction_v1"
DATASET_IDS = {
    "h264": "kpp_frozen_reconstruction_v1_h264",
    "h265": "kpp_frozen_reconstruction_v1_h265",
}
SOURCE_GENERATION_ID = "kpp_iss_publication_v3"
SOURCE_DATASET_IDS = {
    "h264": "kpp_iss_publication_v3_h264",
    "h265": "kpp_iss_publication_v3_h265",
}
HISTORICAL_DATASET_IDS = ["kpp_real_avi", "kpp_real_h264", "kpp_real_h265"]
SOURCE_ROOT = "data/videos/kpp/kpp_iss_publication_v3"
TARGET_ROOT = "data/videos/kpp/kpp_frozen_reconstruction_v1"
SOURCE_MANIFEST_NAME = "kpp_iss_publication_v3_manifest.json"
SOURCE_AUTHORIZATION_NAME = "kpp_iss_publication_v3_authorization_receipt.json"
AUTHORIZATION_RECEIPT_NAME = "kpp_frozen_reconstruction_v1_authorization_receipt.json"
MANIFEST_NAME = "kpp_frozen_reconstruction_v1_manifest.json"
AUTHORIZATION_BASIS_ID = (
    "explicit_user_instruction_2026-08-24_reconstruct_all_missing_frozen_kpp"
)
AUTHORIZATION_RECEIPT_DOMAIN = (
    b"VAST:kpp-frozen-reconstruction-v1-authorization-receipt:v1\0"
)
MANIFEST_DOMAIN = b"VAST:kpp-frozen-reconstruction-v1-manifest:v1\0"

SOURCE_MANIFEST_PIN: dict[str, object] = {
    "source_path": f"{SOURCE_ROOT}/{SOURCE_MANIFEST_NAME}",
    "size_bytes": 7225,
    "sha256": "9a9cf3e08be159bfd4bdeda1d9323b13102980322bde03d9b061e749c1d3fa24",
    "manifest_sha256": "bbe2cca51cdcc95651492e0f28fc95ed00b9106dce73b5995280259701c91cc2",
}
SOURCE_AUTHORIZATION_PIN: dict[str, object] = {
    "source_path": f"{SOURCE_ROOT}/{SOURCE_AUTHORIZATION_NAME}",
    "size_bytes": 3300,
    "sha256": "eee7a49472077ff83bd9a9f3cc67a462c4441b0c841bc64d75859271333732ee",
    "authorization_receipt_sha256": (
        "11678b26210c4ae514535b399afa3ed9f1b412d116d9708c1a94af606cd03d2a"
    ),
}
SOURCE_MEDIA: dict[tuple[str, str], dict[str, object]] = {
    ("h264", "underbody"): {
        "source_path": f"{SOURCE_ROOT}/h264/iss_v2_underbody.mp4",
        "size_bytes": 1_079_445_865,
        "sha256": "b7e5165549172266a5617ff7bbca6e5b888775b0a2490e27b7cbe17640e3b102",
    },
    ("h264", "front_gate"): {
        "source_path": f"{SOURCE_ROOT}/h264/iss_v2_front_gate.mp4",
        "size_bytes": 63_131_711,
        "sha256": "08991b572d2d990a07536c9a4a7eed7780b27127c0e38abe7b607ba97dd59273",
    },
    ("h265", "underbody"): {
        "source_path": f"{SOURCE_ROOT}/h265/iss_v2_underbody.mp4",
        "size_bytes": 223_684_192,
        "sha256": "5368c94a26659c529106724427fc6c3e60fe6788d56699da14c93bc4222e7839",
    },
    ("h265", "front_gate"): {
        "source_path": f"{SOURCE_ROOT}/h265/iss_v2_front_gate.mp4",
        "size_bytes": 14_910_770,
        "sha256": "fa400ecc8b84afc8144fac1da522ef3e9e321c7feb89a5086ac1a1e3ccbe7728",
    },
}
SOURCE_RECEIPTS: list[dict[str, object]] = [
    {
        "source_path": f"{SOURCE_ROOT}/receipts/kpp_iss_v2_extraction_receipt.json",
        "installed_name": "kpp_iss_v2_extraction_receipt.json",
        "size_bytes": 2495,
        "sha256": "f160ce153804f92dd02068ad48547b396636bd2cb7dfc8fb39114210f23a0e05",
    },
    {
        "source_path": f"{SOURCE_ROOT}/receipts/kpp_iss_v2_transcode_receipt.json",
        "installed_name": "kpp_iss_v2_transcode_receipt.json",
        "size_bytes": 7092,
        "sha256": "f78406237d539224a25c38bf40f913f18069e120e8e66e9d11270ff88ceb5470",
    },
    {
        "source_path": f"{SOURCE_ROOT}/receipts/iss_v2_underbody_metadata.json",
        "installed_name": "iss_v2_underbody_metadata.json",
        "size_bytes": 12_731_945,
        "sha256": "d23872d4b4706ef7d804f917a72407f82326eb3cdd5d39d347913f20cc65b0d4",
    },
    {
        "source_path": f"{SOURCE_ROOT}/receipts/kpp_iss_v2_materialization_receipt.json",
        "installed_name": "kpp_iss_v2_materialization_receipt.json",
        "size_bytes": 28_131,
        "sha256": "dd0d2aa38da1281a750806858b555b994a9dcf3c9bcd35e8379dbc9d339f2b33",
    },
]

_EXPECTED_SOURCE_CLAIMS = {
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


class ReconstructionFreezeError(RuntimeError):
    """Raised when reconstruction cannot be frozen without ambiguity."""


@dataclass(frozen=True)
class _TestAdapters:
    source_pins: Mapping[str, object]


def _production_pins() -> dict[str, object]:
    return {
        "manifest": copy.deepcopy(SOURCE_MANIFEST_PIN),
        "authorization": copy.deepcopy(SOURCE_AUTHORIZATION_PIN),
        "media": copy.deepcopy(SOURCE_MEDIA),
        "receipts": copy.deepcopy(SOURCE_RECEIPTS),
    }


def _descriptor(value: object, *, label: str, self_field: str | None = None):
    if not isinstance(value, Mapping):
        raise ReconstructionFreezeError(f"{label} pin is invalid")
    result = dict(value)
    keys = {"source_path", "size_bytes", "sha256"}
    if self_field:
        keys.add(self_field)
    if set(result) != keys:
        raise ReconstructionFreezeError(f"{label} pin schema is not exact")
    source_path = result["source_path"]
    path = PurePosixPath(source_path) if type(source_path) is str else None
    if (
        path is None
        or path.is_absolute()
        or path.as_posix() != source_path
        or any(part in ("", ".", "..") or ":" in part for part in path.parts)
    ):
        raise ReconstructionFreezeError(f"{label} source_path is invalid")
    if type(result["size_bytes"]) is not int or result["size_bytes"] <= 0:
        raise ReconstructionFreezeError(f"{label} size pin is invalid")
    for field in filter(None, ("sha256", self_field)):
        digest = result[field]
        if (
            type(digest) is not str
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
            or digest == "0" * 64
        ):
            raise ReconstructionFreezeError(f"{label} {field} pin is invalid")
    return result


def _read_json(root: Path, pin: Mapping[str, object], *, label: str, field: str, domain: bytes):
    path = root.joinpath(*PurePosixPath(str(pin["source_path"])).parts)
    try:
        _require_plain_chain(root, path)
        size, digest, payload = _stable_payload(path, label=label, retain=True)
        if size != pin["size_bytes"] or digest != pin["sha256"]:
            raise ReconstructionFreezeError(f"{label} external byte pin drifted")
        assert payload is not None
        value = _strict_json(payload, label=label)
        computed = _receipt_self_hash(value, field=field, domain=domain)
    except PublicationCorpusFreezeError as exc:
        raise ReconstructionFreezeError(str(exc)) from exc
    if value.get(field) != pin[field] or computed != value.get(field):
        raise ReconstructionFreezeError(f"{label} self hash is invalid")
    return value


def _check_claims(value: object, *, label: str) -> None:
    if not isinstance(value, Mapping):
        raise ReconstructionFreezeError(f"{label} claims are invalid")
    for field, expected in _EXPECTED_SOURCE_CLAIMS.items():
        if value.get(field) is not expected:
            if field == "v1_dataset_identity_equivalent":
                raise ReconstructionFreezeError(f"{label} forbidden v1 identity claim")
            raise ReconstructionFreezeError(f"{label} claim {field!r} drifted")


def _validate_source_graph(root: Path, pins: Mapping[str, object]):
    if set(pins) != {"manifest", "authorization", "media", "receipts"}:
        raise ReconstructionFreezeError("source pin set is not exact")
    manifest_pin = _descriptor(
        pins["manifest"], label="source manifest", self_field="manifest_sha256"
    )
    authorization_pin = _descriptor(
        pins["authorization"],
        label="source authorization",
        self_field="authorization_receipt_sha256",
    )
    manifest = _read_json(
        root,
        manifest_pin,
        label="source manifest",
        field="manifest_sha256",
        domain=SOURCE_MANIFEST_DOMAIN,
    )
    authorization = _read_json(
        root,
        authorization_pin,
        label="source authorization",
        field="authorization_receipt_sha256",
        domain=SOURCE_AUTHORIZATION_DOMAIN,
    )
    expected_documents = (
        (manifest, "vast_kpp_iss_publication_v3_manifest", "frozen_publication_corpus"),
        (
            authorization,
            "vast_kpp_iss_publication_v3_authorization_receipt",
            "authorized_for_performance_publication",
        ),
    )
    for value, kind, status in expected_documents:
        if (
            value.get("schema_version") != 1
            or type(value.get("schema_version")) is not int
            or value.get("artifact_kind") != kind
            or value.get("generation_id") != SOURCE_GENERATION_ID
            or value.get("status") != status
            or value.get("dataset_ids") != SOURCE_DATASET_IDS
        ):
            raise ReconstructionFreezeError("source identity or status drifted")
        _check_claims(value.get("claims"), label=kind)
    if manifest.get("dataset_root") != SOURCE_ROOT:
        raise ReconstructionFreezeError("source dataset root drifted")
    source_generation = manifest.get("source_generation")
    if not isinstance(source_generation, Mapping) or source_generation.get(
        "identity_equivalent"
    ) is not False:
        raise ReconstructionFreezeError("source v1 identity boundary is invalid")
    expected_authorization = {
        "path": authorization_pin["source_path"],
        "size_bytes": authorization_pin["size_bytes"],
        "sha256": authorization_pin["sha256"],
        "authorization_receipt_sha256": authorization_pin[
            "authorization_receipt_sha256"
        ],
    }
    if manifest.get("authorization_receipt") != expected_authorization:
        raise ReconstructionFreezeError("source authorization graph drifted")

    raw_media = pins["media"]
    identities = {
        (codec, role)
        for codec in ("h264", "h265")
        for role in ("underbody", "front_gate")
    }
    if not isinstance(raw_media, Mapping) or set(raw_media) != identities:
        raise ReconstructionFreezeError("source media pin set is not exact")
    media = {
        identity: _descriptor(
            raw_media[identity], label=f"source media {identity[0]}/{identity[1]}"
        )
        for identity in identities
    }
    observed_media = manifest.get("media_artifacts")
    if type(observed_media) is not list:
        raise ReconstructionFreezeError("source manifest media graph is invalid")
    projected_media = {}
    for raw in observed_media:
        if type(raw) is not dict:
            raise ReconstructionFreezeError("source manifest media graph is invalid")
        identity = (raw.get("codec_variant"), raw.get("role"))
        if identity in projected_media:
            raise ReconstructionFreezeError("source manifest media graph is duplicated")
        projected_media[identity] = {
            "source_path": raw.get("path"),
            "size_bytes": raw.get("size_bytes"),
            "sha256": raw.get("sha256"),
        }
    if projected_media != media:
        raise ReconstructionFreezeError("source manifest media graph drifted")

    raw_receipts = pins["receipts"]
    if type(raw_receipts) is not list or not raw_receipts:
        raise ReconstructionFreezeError("source receipt pin set is invalid")
    receipts = []
    names: set[str] = set()
    for index, raw in enumerate(raw_receipts):
        if not isinstance(raw, Mapping) or set(raw) != {
            "source_path",
            "installed_name",
            "size_bytes",
            "sha256",
        }:
            raise ReconstructionFreezeError("source receipt pin schema is not exact")
        item = _descriptor(
            {key: raw[key] for key in ("source_path", "size_bytes", "sha256")},
            label=f"source receipt {index}",
        )
        name = raw["installed_name"]
        if (
            type(name) is not str
            or PurePosixPath(name).name != name
            or name in names
        ):
            raise ReconstructionFreezeError("source receipt installed name is invalid")
        names.add(name)
        receipts.append({**item, "installed_name": name})
    manifest_receipts = manifest.get("source_receipts")
    if type(manifest_receipts) is not list:
        raise ReconstructionFreezeError("source manifest receipt graph is invalid")
    observed_receipts = {
        (item.get("path"), item.get("size_bytes"), item.get("sha256"))
        for item in manifest_receipts
        if type(item) is dict
    }
    expected_receipts = {
        (item["source_path"], item["size_bytes"], item["sha256"])
        for item in receipts
    }
    if (
        len(observed_receipts) != len(manifest_receipts)
        or observed_receipts != expected_receipts
    ):
        raise ReconstructionFreezeError("source manifest receipt graph drifted")
    return media, receipts, manifest_pin, authorization_pin


def _claims() -> dict[str, bool]:
    return {
        "publication_authorized": True,
        "publication_scope_performance_and_topology_only": True,
        "accuracy_ground_truth_validated": False,
        "production_routing_validated": False,
        "historical_v1_source_bytes_recovered": False,
        "historical_v1_dataset_identity_equivalent": False,
        "reconstruction_identity_distinct": True,
        "media_reused_without_retranscode": True,
        "source_v3_receipt_graph_exactly_pinned": True,
        "all_copied_bytes_verified": True,
        "output_set_directory_published_atomically": True,
    }


def _historical_v1() -> dict[str, object]:
    return {
        "dataset_ids": copy.deepcopy(HISTORICAL_DATASET_IDS),
        "source_bytes_available": False,
        "identity_recovered": False,
        "reconstruction_is_identity_substitute": False,
    }


def _write_canonical(path: Path, value: Mapping[str, object]) -> bytes:
    payload = _canonical_bytes(value)
    try:
        with path.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        raise ReconstructionFreezeError(f"cannot write artifact: {exc}") from exc
    if path.read_bytes() != payload:
        raise ReconstructionFreezeError(f"artifact changed: {path.name}")
    return payload


def _tree_files(receipts: Sequence[Mapping[str, object]]) -> set[str]:
    return {
        *(
            f"{codec}/iss_v2_{role}.mp4"
            for codec in ("h264", "h265")
            for role in ("underbody", "front_gate")
        ),
        f"receipts/{SOURCE_MANIFEST_NAME}",
        f"receipts/{SOURCE_AUTHORIZATION_NAME}",
        *(f"receipts/{item['installed_name']}" for item in receipts),
        AUTHORIZATION_RECEIPT_NAME,
        MANIFEST_NAME,
    }


def _validate_tree(root: Path, receipts: Sequence[Mapping[str, object]]) -> None:
    if not root.is_dir() or _is_link_or_reparse(root):
        raise ReconstructionFreezeError("reconstruction root is not plain")
    directories, files, pending = set(), set(), [root]
    while pending:
        for child in pending.pop().iterdir():
            if _is_link_or_reparse(child):
                raise ReconstructionFreezeError("reconstruction contains a link")
            relative, observed = child.relative_to(root).as_posix(), child.lstat()
            if stat.S_ISDIR(observed.st_mode):
                directories.add(relative)
                pending.append(child)
            elif stat.S_ISREG(observed.st_mode) and int(observed.st_nlink) == 1:
                files.add(relative)
            else:
                raise ReconstructionFreezeError("reconstruction entry is not plain")
    if directories != {"h264", "h265", "receipts"} or files != _tree_files(receipts):
        raise ReconstructionFreezeError("reconstruction tree is not exact")


def _cleanup(working: Path, parent: Path, receipts: Sequence[Mapping[str, object]]) -> None:
    if (
        working.parent != parent
        or not working.name.startswith(".kpp_frozen_reconstruction_v1.")
        or not working.name.endswith(".candidate")
        or not working.is_dir()
        or _is_link_or_reparse(working)
    ):
        return
    for relative in sorted(_tree_files(receipts)):
        path = working.joinpath(*PurePosixPath(relative).parts)
        if _lexists(path):
            if _is_link_or_reparse(path) or not path.is_file():
                return
            path.unlink()
    for directory in (working / "receipts", working / "h265", working / "h264"):
        if _lexists(directory):
            directory.rmdir()
    working.rmdir()


def _copy(root: Path, working: Path, descriptor: Mapping[str, object], relative: str):
    source = root.joinpath(*PurePosixPath(str(descriptor["source_path"])).parts)
    try:
        _require_plain_chain(root, source)
        _copy_pinned_snapshot(
            source=source,
            target=working.joinpath(*PurePosixPath(relative).parts),
            expected_sha256=str(descriptor["sha256"]),
            expected_size_bytes=int(descriptor["size_bytes"]),
            label=f"reconstruction source {relative}",
        )
    except (PublicationCorpusFreezeError, TranscodeFreezeError) as exc:
        raise ReconstructionFreezeError(str(exc)) from exc
    return {
        "source_path": descriptor["source_path"],
        "path": f"{TARGET_ROOT}/{relative}",
        "size_bytes": descriptor["size_bytes"],
        "sha256": descriptor["sha256"],
    }


def _freeze_reconstruction_impl(
    *, project_root: Path, authorization_basis: str, test_adapters: _TestAdapters | None
) -> dict[str, object]:
    if authorization_basis != AUTHORIZATION_BASIS_ID:
        raise ReconstructionFreezeError(
            "explicit reconstruction authorization is missing or invalid"
        )
    try:
        root = _validated_root(project_root)
    except PublicationCorpusFreezeError as exc:
        raise ReconstructionFreezeError(str(exc)) from exc
    target = root.joinpath(*PurePosixPath(TARGET_ROOT).parts)
    try:
        _require_plain_chain(root, target)
    except PublicationCorpusFreezeError as exc:
        raise ReconstructionFreezeError(str(exc)) from exc
    if _lexists(target):
        raise ReconstructionFreezeError(f"target already exists: {TARGET_ROOT}")
    parent = target.parent
    if not parent.is_dir() or _is_link_or_reparse(parent):
        raise ReconstructionFreezeError("target parent must be a plain directory")
    pins = (
        _production_pins()
        if test_adapters is None
        else copy.deepcopy(dict(test_adapters.source_pins))
    )
    media, receipts, manifest_pin, authorization_pin = _validate_source_graph(root, pins)
    try:
        working = _create_private_working_directory(
            parent=parent,
            prefix=".kpp_frozen_reconstruction_v1.",
            suffix=".candidate",
        )
    except ExtractionError as exc:
        raise ReconstructionFreezeError(str(exc)) from exc
    published = False
    try:
        for name in ("h264", "h265", "receipts"):
            (working / name).mkdir()
        source_documents = {
            "manifest": _copy(
                root, working, manifest_pin, f"receipts/{SOURCE_MANIFEST_NAME}"
            ),
            "authorization": _copy(
                root, working, authorization_pin, f"receipts/{SOURCE_AUTHORIZATION_NAME}"
            ),
        }
        source_documents["manifest"]["manifest_sha256"] = manifest_pin[
            "manifest_sha256"
        ]
        source_documents["authorization"][
            "authorization_receipt_sha256"
        ] = authorization_pin["authorization_receipt_sha256"]
        installed_receipts = [
            _copy(root, working, item, f"receipts/{item['installed_name']}")
            for item in receipts
        ]
        installed_media = []
        for codec in ("h264", "h265"):
            for role in ("underbody", "front_gate"):
                copied = _copy(
                    root,
                    working,
                    media[(codec, role)],
                    f"{codec}/iss_v2_{role}.mp4",
                )
                installed_media.append(
                    {"codec_variant": codec, "role": role, **copied}
                )

        claims = _claims()
        source_publication = {
            "generation_id": SOURCE_GENERATION_ID,
            "dataset_ids": copy.deepcopy(SOURCE_DATASET_IDS),
            "generation_identity_equivalent": False,
            "media_bytes_reused_exactly": True,
            **source_documents,
        }
        authorization: dict[str, object] = {
            "schema_version": 1,
            "artifact_kind": "vast_kpp_frozen_reconstruction_v1_authorization_receipt",
            "generation_id": GENERATION_ID,
            "dataset_ids": copy.deepcopy(DATASET_IDS),
            "status": "authorized_reconstruction_for_performance_publication",
            "authorization_basis": {
                "kind": "explicit_user_instruction",
                "basis_id": AUTHORIZATION_BASIS_ID,
                "authorized_scope": "performance_and_topology_benchmark_results_only",
                "excluded_scopes": [
                    "accuracy_evaluation",
                    "production_routing_validation",
                    "historical_v1_identity_equivalence",
                ],
            },
            "historical_v1": _historical_v1(),
            "source_publication": copy.deepcopy(source_publication),
            "claims": copy.deepcopy(claims),
        }
        authorization["authorization_receipt_sha256"] = _receipt_self_hash(
            authorization,
            field="authorization_receipt_sha256",
            domain=AUTHORIZATION_RECEIPT_DOMAIN,
        )
        auth_payload = _write_canonical(
            working / AUTHORIZATION_RECEIPT_NAME, authorization
        )
        auth_descriptor = {
            "path": f"{TARGET_ROOT}/{AUTHORIZATION_RECEIPT_NAME}",
            "size_bytes": len(auth_payload),
            "sha256": hashlib.sha256(auth_payload).hexdigest(),
            "authorization_receipt_sha256": authorization[
                "authorization_receipt_sha256"
            ],
        }
        datasets = [
            {
                "dataset_id": DATASET_IDS[codec],
                "codec_variant": codec,
                "publication_scope": "performance_and_topology_benchmark_results_only",
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
        manifest: dict[str, object] = {
            "schema_version": 1,
            "artifact_kind": "vast_kpp_frozen_reconstruction_v1_manifest",
            "generation_id": GENERATION_ID,
            "status": "frozen_distinct_reconstruction",
            "dataset_root": TARGET_ROOT,
            "dataset_ids": copy.deepcopy(DATASET_IDS),
            "datasets": datasets,
            "historical_v1": _historical_v1(),
            "source_publication": copy.deepcopy(source_publication),
            "source_receipts": installed_receipts,
            "media_artifacts": installed_media,
            "authorization_receipt": auth_descriptor,
            "claims": copy.deepcopy(claims),
        }
        manifest["manifest_sha256"] = _receipt_self_hash(
            manifest, field="manifest_sha256", domain=MANIFEST_DOMAIN
        )
        manifest_payload = _write_canonical(working / MANIFEST_NAME, manifest)
        _validate_tree(working, receipts)
        try:
            _atomic_publish_directory(working, target)
        except TranscodeFreezeError as exc:
            raise ReconstructionFreezeError(str(exc)) from exc
        published = True
        _validate_tree(target, receipts)
        if (target / MANIFEST_NAME).read_bytes() != manifest_payload:
            raise ReconstructionFreezeError("published manifest changed")
        if (target / AUTHORIZATION_RECEIPT_NAME).read_bytes() != auth_payload:
            raise ReconstructionFreezeError("published authorization changed")
        for item in installed_media:
            relative = PurePosixPath(str(item["path"])).relative_to(TARGET_ROOT)
            try:
                size, digest, _ = _stable_payload(
                    target.joinpath(*relative.parts),
                    label="published reconstruction media",
                    retain=False,
                )
            except PublicationCorpusFreezeError as exc:
                raise ReconstructionFreezeError(str(exc)) from exc
            if size != item["size_bytes"] or digest != item["sha256"]:
                raise ReconstructionFreezeError("published media drifted")
        return manifest
    except Exception:
        if not published and _lexists(working):
            try:
                _cleanup(working, parent, receipts)
            except OSError:
                pass
        raise


def freeze_reconstruction(
    *, project_root: Path, authorization_basis: str
) -> dict[str, object]:
    """Freeze the authoritative standalone reconstruction."""

    return _freeze_reconstruction_impl(
        project_root=project_root,
        authorization_basis=authorization_basis,
        test_adapters=None,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--authorization-basis", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        manifest = freeze_reconstruction(
            project_root=args.project_root,
            authorization_basis=args.authorization_basis,
        )
    except ReconstructionFreezeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 78
    print(json.dumps(manifest, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "AUTHORIZATION_BASIS_ID",
    "AUTHORIZATION_RECEIPT_DOMAIN",
    "DATASET_IDS",
    "GENERATION_ID",
    "MANIFEST_DOMAIN",
    "ReconstructionFreezeError",
    "SOURCE_AUTHORIZATION_DOMAIN",
    "SOURCE_MANIFEST_DOMAIN",
    "SOURCE_ROOT",
    "TARGET_ROOT",
    "freeze_reconstruction",
]
