#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

import yaml

from benchmark_contract import ContractError


MODEL_BINDING_SCHEMA_VERSION = 2
MODEL_BINDING_ARTIFACT_KIND = "checkpoint_analytics_model_bindings"
OMZ_CATALOG_VERSION = "2024.6.0"
OMZ_CATALOG_REVISION = "602c643ac909f1bbfa1fed0f3c4723772508d7d9"
OMZ_LICENSE_URL = (
    "https://raw.githubusercontent.com/openvinotoolkit/open_model_zoo/"
    f"{OMZ_CATALOG_REVISION}/LICENSE"
)
SELECTION_BASIS = "public_omz_proxies_frozen_before_benchmark_results"
SEMANTIC_CLAIM = "topology_load_proxy_only"
OUTPUT_SEMANTICS = "openvino_detection_output_1x1nx7"
OUTPUT_COORDINATES = "normalized_xyxy"
DETECTOR_FACTORY = "gvadetect"
DETECTOR_DEVICE = "CPU"
DETECTOR_INPUT_FORMAT = "BGR"
DETECTOR_BATCH_SIZE = 1
DETECTOR_NIREQ = 1
DETECTOR_IE_CONFIG = "PERFORMANCE_HINT=LATENCY,NUM_STREAMS=1,INFERENCE_NUM_THREADS=1"

_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_SHA384_RE = re.compile(r"[0-9a-f]{96}")
_REVISION_RE = re.compile(r"[0-9a-f]{40}")
_STABLE_ID_RE = re.compile(r"[A-Za-z0-9._-]{1,120}")
_MODEL_NAME_RE = re.compile(r"[a-z0-9][a-z0-9-]{1,98}[a-z0-9]")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_yaml(path: Path) -> dict[str, Any]:
    _require(path.is_file(), f"analytics model manifest was not found: {path}")
    with path.open("r", encoding="utf-8") as source:
        raw = yaml.safe_load(source) or {}
    _require(isinstance(raw, dict), "analytics model manifest must be a mapping")
    return raw


def _safe_url(value: Any, *, field: str) -> str:
    url = str(value or "")
    parsed = urlparse(url)
    _require(parsed.scheme == "https" and bool(parsed.netloc), f"{field} must be an HTTPS URL")
    _require(not parsed.username and not parsed.password and not parsed.fragment, f"{field} is unsafe")
    return url


def _artifact_path(value: Any, *, manifest: Path, field: str) -> Path:
    raw = str(value or "")
    _require(bool(raw), f"{field} is required")
    _require(not any(char in raw for char in ('"', "\r", "\n")), f"{field} contains unsafe characters")
    path = Path(raw)
    path = (path if path.is_absolute() else manifest.parent / path).resolve()
    _require(path.is_file(), f"{field} artifact was not found: {path}")
    return path


def _validate_provenance(raw: Any) -> dict[str, str]:
    _require(isinstance(raw, dict), "analytics model provenance must be a mapping")
    expected = {
        "catalog": "Open Model Zoo",
        "catalog_version": OMZ_CATALOG_VERSION,
        "catalog_revision": OMZ_CATALOG_REVISION,
        "license_spdx": "Apache-2.0",
        "license_url": OMZ_LICENSE_URL,
        "acquisition_tool": "omz_downloader",
    }
    _require(set(raw) == set(expected), "analytics model provenance fields have drifted")
    for field, value in expected.items():
        _require(str(raw.get(field, "")) == value, f"analytics model provenance {field} has drifted")
    _require(
        _REVISION_RE.fullmatch(str(raw["catalog_revision"])) is not None,
        "analytics model provenance catalog_revision must be a commit digest",
    )
    _safe_url(raw["license_url"], field="analytics model provenance license_url")
    return {field: str(value) for field, value in raw.items()}


def _validate_input(branch: str, raw: Any) -> dict[str, Any]:
    _require(isinstance(raw, dict), f"{branch}: input must be a mapping")
    _require(
        set(raw) == {"name", "layout", "shape", "color_order"},
        f"{branch}: input fields have drifted",
    )
    name = str(raw.get("name") or "")
    layout = str(raw.get("layout") or "")
    shape = raw.get("shape")
    color_order = str(raw.get("color_order") or "")
    _require(bool(name) and not any(char in name for char in "\r\n"), f"{branch}: input.name is invalid")
    _require(layout in {"NCHW", "NHWC"}, f"{branch}: input.layout must be NCHW or NHWC")
    _require(
        isinstance(shape, list)
        and len(shape) == 4
        and all(type(value) is int and value > 0 for value in shape),
        f"{branch}: input.shape must contain four positive canonical integers",
    )
    _require(shape[0] == 1, f"{branch}: input.shape must have batch size 1")
    channel_index = 1 if layout == "NCHW" else 3
    _require(shape[channel_index] == 3, f"{branch}: input.shape must have three color channels")
    _require(color_order == "BGR", f"{branch}: input.color_order must be BGR")
    return {"name": name, "layout": layout, "shape": list(shape), "color_order": color_order}


def _validate_output(branch: str, raw: Any) -> dict[str, str]:
    _require(isinstance(raw, dict), f"{branch}: output must be a mapping")
    _require(set(raw) == {"semantics", "coordinates"}, f"{branch}: output fields have drifted")
    semantics = str(raw.get("semantics") or "")
    coordinates = str(raw.get("coordinates") or "")
    _require(semantics == OUTPUT_SEMANTICS, f"{branch}: output.semantics has drifted")
    _require(coordinates == OUTPUT_COORDINATES, f"{branch}: output.coordinates has drifted")
    return {"semantics": semantics, "coordinates": coordinates}


def _validate_branch(
    branch: str,
    raw: Any,
    *,
    manifest: Path,
    catalog_revision: str,
) -> dict[str, str]:
    _require(isinstance(raw, dict), f"analytics model binding {branch} must be a mapping")
    expected_fields = {
        "proxy_role",
        "semantic_claim",
        "source_model_name",
        "source_model_config_url",
        "factory",
        "device",
        "input_format",
        "batch_size",
        "nireq",
        "ie_config",
        "detector_id",
        "model_path",
        "model_sha256",
        "model_source_url",
        "model_source_sha384",
        "weights_path",
        "weights_sha256",
        "weights_source_url",
        "weights_source_sha384",
        "input",
        "output",
    }
    _require(set(raw) == expected_fields, f"{branch}: analytics model binding fields have drifted")
    _require(str(raw.get("proxy_role") or "") == branch, f"{branch}: proxy_role must equal the branch")
    _require(
        str(raw.get("semantic_claim") or "") == SEMANTIC_CLAIM,
        f"{branch}: semantic_claim must remain topology-only",
    )

    source_model_name = str(raw.get("source_model_name") or "")
    _require(
        _MODEL_NAME_RE.fullmatch(source_model_name) is not None,
        f"{branch}: source_model_name is invalid",
    )
    config_url = _safe_url(raw.get("source_model_config_url"), field=f"{branch}: source_model_config_url")
    expected_config_url = (
        "https://raw.githubusercontent.com/openvinotoolkit/open_model_zoo/"
        f"{catalog_revision}/models/intel/{source_model_name}/model.yml"
    )
    _require(config_url == expected_config_url, f"{branch}: source_model_config_url has drifted")

    factory = str(raw.get("factory") or "")
    device = str(raw.get("device") or "")
    input_format = str(raw.get("input_format") or "")
    batch_size = raw.get("batch_size")
    nireq = raw.get("nireq")
    ie_config = str(raw.get("ie_config") or "")
    detector_id = str(raw.get("detector_id") or "")
    _require(factory == DETECTOR_FACTORY, f"{branch}: factory must be {DETECTOR_FACTORY}")
    _require(device == DETECTOR_DEVICE, f"{branch}: device must be {DETECTOR_DEVICE} for the frozen OpenVINO proxy set")
    _require(input_format == DETECTOR_INPUT_FORMAT, f"{branch}: input_format must be {DETECTOR_INPUT_FORMAT}")
    _require(batch_size == DETECTOR_BATCH_SIZE, f"{branch}: batch_size must be {DETECTOR_BATCH_SIZE}")
    _require(nireq == DETECTOR_NIREQ, f"{branch}: nireq must be {DETECTOR_NIREQ}")
    _require(ie_config == DETECTOR_IE_CONFIG, f"{branch}: ie_config has drifted")
    _require(_STABLE_ID_RE.fullmatch(detector_id) is not None, f"{branch}: detector_id is invalid")

    model_path = _artifact_path(raw.get("model_path"), manifest=manifest, field=f"{branch}: model_path")
    weights_path = _artifact_path(
        raw.get("weights_path"), manifest=manifest, field=f"{branch}: weights_path"
    )
    _require(model_path.suffix == ".xml", f"{branch}: model_path must be an OpenVINO .xml file")
    _require(weights_path == model_path.with_suffix(".bin"), f"{branch}: weights_path must be the sibling .bin")

    model_sha256 = str(raw.get("model_sha256") or "")
    weights_sha256 = str(raw.get("weights_sha256") or "")
    _require(_SHA256_RE.fullmatch(model_sha256) is not None, f"{branch}: model_sha256 is invalid")
    _require(_SHA256_RE.fullmatch(weights_sha256) is not None, f"{branch}: weights_sha256 is invalid")
    _require(_sha256_file(model_path) == model_sha256, f"{branch}: model SHA-256 differs from the manifest")
    _require(
        _sha256_file(weights_path) == weights_sha256,
        f"{branch}: weights SHA-256 differs from the manifest",
    )

    model_source_url = _safe_url(raw.get("model_source_url"), field=f"{branch}: model_source_url")
    weights_source_url = _safe_url(
        raw.get("weights_source_url"), field=f"{branch}: weights_source_url"
    )
    expected_base = (
        "https://storage.openvinotoolkit.org/repositories/open_model_zoo/"
        f"2023.0/models_bin/1/{source_model_name}/FP16/{source_model_name}"
    )
    _require(model_source_url == f"{expected_base}.xml", f"{branch}: model_source_url has drifted")
    _require(weights_source_url == f"{expected_base}.bin", f"{branch}: weights_source_url has drifted")
    model_source_sha384 = str(raw.get("model_source_sha384") or "")
    weights_source_sha384 = str(raw.get("weights_source_sha384") or "")
    _require(
        _SHA384_RE.fullmatch(model_source_sha384) is not None,
        f"{branch}: model_source_sha384 is invalid",
    )
    _require(
        _SHA384_RE.fullmatch(weights_source_sha384) is not None,
        f"{branch}: weights_source_sha384 is invalid",
    )

    input_contract = _validate_input(branch, raw.get("input"))
    output_contract = _validate_output(branch, raw.get("output"))
    return {
        "factory": factory,
        "device": device,
        "input_format": input_format,
        "batch_size": str(batch_size),
        "nireq": str(nireq),
        "ie_config": ie_config,
        "model_path": str(model_path),
        "model_sha256": model_sha256,
        "weights_path": str(weights_path),
        "weights_sha256": weights_sha256,
        "detector_id": detector_id,
        "source_model_name": source_model_name,
        "semantic_claim": SEMANTIC_CLAIM,
        "input_name": str(input_contract["name"]),
        "input_layout": str(input_contract["layout"]),
        "input_shape": ",".join(str(value) for value in input_contract["shape"]),
        "input_color_order": str(input_contract["color_order"]),
        "output_semantics": str(output_contract["semantics"]),
        "output_coordinates": str(output_contract["coordinates"]),
        "source_model_config_url": config_url,
        "model_source_url": model_source_url,
        "model_source_sha384": model_source_sha384,
        "weights_source_url": weights_source_url,
        "weights_source_sha384": weights_source_sha384,
    }


def load_analytics_model_bindings(
    path: Path,
    *,
    required_branches: Iterable[str],
) -> dict[str, dict[str, str]]:
    """Load the frozen, source-attributed OpenVINO proxy model set fail-closed."""

    resolved_manifest = path.resolve()
    raw = _load_yaml(resolved_manifest)
    expected_top_level = {
        "schema_version",
        "artifact_kind",
        "manifest_id",
        "selection_basis",
        "runtime_family",
        "precision",
        "effective_batch_size",
        "provenance",
        "branches",
    }
    _require(set(raw) == expected_top_level, "analytics model manifest top-level fields have drifted")
    _require(
        raw.get("schema_version") == MODEL_BINDING_SCHEMA_VERSION,
        f"analytics model manifest schema_version must be {MODEL_BINDING_SCHEMA_VERSION}",
    )
    _require(
        raw.get("artifact_kind") == MODEL_BINDING_ARTIFACT_KIND,
        "analytics model manifest artifact_kind is invalid",
    )
    _require(
        _STABLE_ID_RE.fullmatch(str(raw.get("manifest_id") or "")) is not None,
        "analytics model manifest_id is invalid",
    )
    _require(str(raw.get("selection_basis") or "") == SELECTION_BASIS, "analytics model selection_basis has drifted")
    _require(str(raw.get("runtime_family") or "") == "openvino_dlstreamer", "analytics model runtime_family has drifted")
    _require(str(raw.get("precision") or "") == "FP16", "analytics model precision must be FP16")
    _require(raw.get("effective_batch_size") == 1, "analytics model effective_batch_size must be 1")
    provenance = _validate_provenance(raw.get("provenance"))

    raw_branches = raw.get("branches")
    _require(isinstance(raw_branches, dict), "analytics model manifest requires a branches mapping")
    required = tuple(str(value) for value in required_branches)
    expected = set(required)
    _require(expected and len(expected) == len(required), "required analytics branches must be unique")
    _require(
        {str(value) for value in raw_branches} == expected,
        "analytics model manifest must exactly cover the required branches",
    )

    detector_ids = [
        str(raw_branches[branch].get("detector_id") or "")
        for branch in sorted(expected)
        if isinstance(raw_branches[branch], dict)
    ]
    _require(
        len(detector_ids) == len(expected) and len(detector_ids) == len(set(detector_ids)),
        "analytics model detector_id values must be unique",
    )
    source_models = [
        str(raw_branches[branch].get("source_model_name") or "")
        for branch in sorted(expected)
        if isinstance(raw_branches[branch], dict)
    ]
    _require(
        len(source_models) == len(expected) and len(source_models) == len(set(source_models)),
        "analytics model source_model_name values must be unique",
    )

    bindings = {
        branch: _validate_branch(
            branch,
            raw_branches[branch],
            manifest=resolved_manifest,
            catalog_revision=provenance["catalog_revision"],
        )
        for branch in sorted(expected)
    }
    return bindings

