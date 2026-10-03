from __future__ import annotations

import copy
import contextlib
import hashlib
import json
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from benchmark_contract import ContractError  # noqa: E402
import checkpoint_model_parity as checkpoint_model_parity_module  # noqa: E402
from checkpoint_model_parity import (  # noqa: E402
    ARTIFACT_KIND,
    BRANCHES,
    MIN_CALIBRATION_SAMPLES,
    MIN_PARITY_SAMPLES,
    PARITY_TOLERANCES,
    assess_model_parity,
    build_image_inspect_command,
    build_parser,
    load_parity_manifest,
    load_parity_preprocessing_contract,
    main,
    validate_manifest_identity,
)


CPU_IMAGE_ID = "sha256:5c43c6c1f95b3fbb4a95957d1d293b1272c1db6a44a7a2063aad3aeba7c951d1"
GPU_IMAGE_ID = "sha256:16d284eb311f04a95f148746f0dc5637d54d527cc42be9a6cced5fcf0240770c"
CPU_WORKER_IMAGE_ID = "sha256:e2b01f8f40da08fc59d671e19a7f4eca6dd7d46678de0138ab7af51b09cb9b03"
GPU_WORKER_IMAGE_ID = "sha256:2ff600e743e6fc089ace1ea40894d73581fcda8007fa758fd0f32eb9b1c72f09"
CPU_WORKER_IMPLEMENTATION_SHA = "f15ab5fd7d846376ccba55e55b663f4d16e114ef4cf5519794795cde7a416f8b"
GPU_WORKER_IMPLEMENTATION_SHA = "eb6fce9ec42f26e0d38263053aedbb8d9c247c1872be39d67d7f3c0da4c48ab7"


def canonical_sha(value: object) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def ref(root: Path, path: Path) -> dict[str, object]:
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": file_sha(path),
    }


def sized_ref(root: Path, path: Path) -> dict[str, object]:
    return {**ref(root, path), "size_bytes": path.stat().st_size}


def image_runner(commands: list[list[str]]):
    def runner(command: list[str]) -> str:
        commands.append(command)
        if command[:3] != ["docker", "image", "inspect"]:
            raise AssertionError(command)
        image = command[-1]
        image_id = CPU_IMAGE_ID if "openvino" in image else GPU_IMAGE_ID
        return json.dumps(
            {
                "Id": image_id,
                "RepoDigests": [f"{image.split(':', 1)[0]}@{image_id}"],
                "Architecture": "amd64",
                "Os": "linux",
            }
        )

    return runner


def complete_branch(root: Path, branch: str, index: int) -> dict[str, object]:
    directory = root / "artifacts" / branch
    directory.mkdir(parents=True, exist_ok=True)
    source = directory / f"{branch}.onnx"
    xml = directory / f"{branch}.xml"
    weights = directory / f"{branch}.bin"
    engine = directory / f"{branch}.engine"
    source.write_bytes(f"official-onnx-{branch}\n".encode("ascii"))
    xml.write_text(f"openvino-ir-{branch}\n", encoding="utf-8")
    weights.write_bytes(f"openvino-weights-{branch}\n".encode("ascii"))
    engine.write_bytes(f"tensorrt-engine-{branch}\n".encode("ascii"))
    source_sha = file_sha(source)
    xml_sha = file_sha(xml)
    weights_sha = file_sha(weights)
    engine_sha = file_sha(engine)

    side = 300 if branch == "plate_number" else 512
    layout = "NHWC" if branch == "plate_number" else "NCHW"
    shape = [1, side, side, 3] if layout == "NHWC" else [1, 3, side, side]
    input_name = "Placeholder" if branch == "plate_number" else f"input_{index}"
    preprocessing = {
        "decoded_color_order": "BGR",
        "tensor_color_order": "BGR",
        "resize_algorithm": "bilinear_half_pixel",
        "resize_mode": "stretch",
        "normalization_scale": 0.00392156862745098,
        "normalization_mean": [0.0, 0.0, 0.0],
        "normalization_std": [1.0, 1.0, 1.0],
        "letterbox": False,
        "padding_value": [0.0, 0.0, 0.0],
    }
    output_contract = {
        "tensor_names": ["detection_out"],
        "dtype": "float32",
        "shape": [1, 1, 200, 7],
        "semantics": "detection_output_1x1nx7",
        "coordinates": "normalized_xyxy",
        "class_id_map": {"0": "background", "1": "object"},
        "decoder": "detection_output_v1",
        "confidence_threshold": 0.5,
        "nms": {
            "mode": "in_graph",
            "iou_threshold": 0.45,
            "max_detections": 200,
        },
    }
    input_contract = {
        "name": input_name,
        "dtype": "float32",
        "layout": layout,
        "shape": shape,
        "dynamic_shape_binding": {
            "enabled": False,
            "input_name": input_name,
            "min": shape,
            "opt": shape,
            "max": shape,
        },
    }
    preprocessing_sha = canonical_sha(preprocessing)
    output_sha = canonical_sha(output_contract)

    calibration_corpus = directory / "calibration_corpus.json"
    parity_corpus = directory / "parity_corpus.json"
    calibration_sample_ids = [
        f"{branch}:calibration:{sample:03d}"
        for sample in range(MIN_CALIBRATION_SAMPLES)
    ]
    parity_sample_ids = [
        f"{branch}:evaluation:{sample:03d}"
        for sample in range(MIN_PARITY_SAMPLES)
    ]
    calibration_samples_sha = canonical_sha(calibration_sample_ids)
    parity_samples_sha = canonical_sha(parity_sample_ids)
    write_json(
        calibration_corpus,
        {
            "schema_version": 1,
            "artifact_kind": "checkpoint_model_parity_corpus",
            "branch": branch,
            "corpus_role": "calibration",
            "sample_count": MIN_CALIBRATION_SAMPLES,
            "unique_sample_count": MIN_CALIBRATION_SAMPLES,
            "sample_ids": calibration_sample_ids,
            "sample_ids_sha256": calibration_samples_sha,
            "dataset_sha256": hashlib.sha256(b"dataset").hexdigest(),
        },
    )
    write_json(
        parity_corpus,
        {
            "schema_version": 1,
            "artifact_kind": "checkpoint_model_parity_corpus",
            "branch": branch,
            "corpus_role": "evaluation",
            "sample_count": MIN_PARITY_SAMPLES,
            "unique_sample_count": MIN_PARITY_SAMPLES,
            "sample_ids": parity_sample_ids,
            "sample_ids_sha256": parity_samples_sha,
            "dataset_sha256": hashlib.sha256(b"dataset").hexdigest(),
        },
    )
    calibration_corpus_sha = file_sha(calibration_corpus)
    parity_corpus_sha = file_sha(parity_corpus)

    cpu_probe = directory / "cpu_probe.json"
    cuda_probe = directory / "cuda_probe.json"
    write_json(
        cpu_probe,
        {
            "schema_version": 1,
            "artifact_kind": "checkpoint_model_execution_probe",
            "branch": branch,
            "runtime": "openvino",
            "device_api": "OPENVINO_CPU",
            "device_id": "CPU",
            "success": True,
            "source_sha256": source_sha,
            "model_sha256": xml_sha,
            "weights_sha256": weights_sha,
            "engine_sha256": None,
            "preprocessing_contract_sha256": preprocessing_sha,
            "output_contract_sha256": output_sha,
            "runtime_image_id": CPU_IMAGE_ID,
            "sample_count": 1,
        },
    )
    write_json(
        cuda_probe,
        {
            "schema_version": 1,
            "artifact_kind": "checkpoint_model_execution_probe",
            "branch": branch,
            "runtime": "tensorrt",
            "device_api": "NVIDIA_CUDA",
            "device_id": "GPU-00000000-0000-0000-0000-000000000001",
            "success": True,
            "source_sha256": source_sha,
            "model_sha256": None,
            "weights_sha256": None,
            "engine_sha256": engine_sha,
            "preprocessing_contract_sha256": preprocessing_sha,
            "output_contract_sha256": output_sha,
            "runtime_image_id": GPU_IMAGE_ID,
            "sample_count": 1,
        },
    )

    calibration = directory / "calibration.json"
    write_json(
        calibration,
        {
            "schema_version": 1,
            "artifact_kind": "checkpoint_model_parity_calibration",
            "branch": branch,
            "source_sha256": source_sha,
            "corpus_manifest_sha256": calibration_corpus_sha,
            "sample_count": MIN_CALIBRATION_SAMPLES,
            "unique_sample_count": MIN_CALIBRATION_SAMPLES,
            "selection_rule": "pre_registered_per_branch_v1",
            "tolerances": PARITY_TOLERANCES,
        },
    )
    calibration_sha = file_sha(calibration)
    parity = directory / "numeric_parity.json"
    write_json(
        parity,
        {
            "schema_version": 1,
            "artifact_kind": "checkpoint_model_numeric_parity",
            "branch": branch,
            "source_sha256": source_sha,
            "openvino_model_sha256": xml_sha,
            "openvino_weights_sha256": weights_sha,
            "tensorrt_engine_sha256": engine_sha,
            "cpu_probe_sha256": file_sha(cpu_probe),
            "cuda_probe_sha256": file_sha(cuda_probe),
            "calibration_evidence_sha256": calibration_sha,
            "corpus_manifest_sha256": parity_corpus_sha,
            "preprocessing_contract_sha256": preprocessing_sha,
            "output_contract_sha256": output_sha,
            "sample_count": MIN_PARITY_SAMPLES,
            "unique_sample_count": MIN_PARITY_SAMPLES,
            "metrics": {
                key: (0.0 if limit == 0.0 else limit / 2.0)
                for key, limit in PARITY_TOLERANCES.items()
            },
            "passed": True,
        },
    )

    return {
        "lineage_mode": "common_source",
        "source_artifact": {
            "format": "onnx",
            "path": source.relative_to(root).as_posix(),
            "sha256": source_sha,
            "opset": 17,
            "exporter": {
                "name": "official_exporter",
                "version": "1.2.3",
                "command_sha256": hashlib.sha256(b"export-command").hexdigest(),
            },
        },
        "openvino_ir": {
            "model": ref(root, xml),
            "weights": ref(root, weights),
            "derived_from_source_sha256": source_sha,
            "toolchain": {
                "name": "openvino_model_optimizer",
                "version": "2026.1.0",
                "command_sha256": hashlib.sha256(b"ov-command").hexdigest(),
            },
        },
        "tensorrt_engine": {
            "artifact": ref(root, engine),
            "derived_from_source_sha256": source_sha,
            "toolchain": {
                "name": "TensorRT",
                "version": "8.6.1.6",
                "cuda_version": "12.2.2",
                "gpu_compute_capability": "8.6",
                "builder_flags_sha256": hashlib.sha256(b"trt-flags").hexdigest(),
            },
        },
        "lineage_equivalence_evidence": {"path": None, "sha256": None},
        "input_contract": input_contract,
        "preprocessing": preprocessing,
        "output_contract": output_contract,
        "evidence": {
            "cpu_execution_probe": ref(root, cpu_probe),
            "cuda_execution_probe": ref(root, cuda_probe),
            "calibration_corpus": ref(root, calibration_corpus),
            "calibration": ref(root, calibration),
            "parity_corpus": ref(root, parity_corpus),
            "numeric_parity": ref(root, parity),
        },
    }


def complete_manifest(root: Path) -> Path:
    raw = {
        "schema_version": 1,
        "artifact_kind": ARTIFACT_KIND,
        "manifest_id": "synthetic-complete-parity-v1",
        "claim_scope": "cpu_openvino_vs_nvidia_cuda_tensorrt",
        "required_branches": list(BRANCHES),
        "matrix_binding": {
            "cpu": {
                "runtime": "openvino",
                "device": "CPU",
                "image": "vast/openvino-native-probe:fixture",
            },
            "gpu": {
                "runtime": "tensorrt",
                "device_api": "NVIDIA_CUDA",
                "image": "vast/deepstream-native-probe:fixture",
            },
            "openvino_gpu_accepted": False,
            "same_source_semantics_required": True,
        },
        "evidence_policy": {
            "canonical_source_preference": "onnx",
            "accepted_lineage_modes": [
                "common_source",
                "verified_equivalent_derivations",
            ],
            "minimum_calibration_samples_per_branch": MIN_CALIBRATION_SAMPLES,
            "minimum_numeric_parity_samples_per_branch": MIN_PARITY_SAMPLES,
            "calibration_and_evaluation_disjoint": True,
            "tolerances": PARITY_TOLERANCES,
        },
        "branches": {
            branch: complete_branch(root, branch, index)
            for index, branch in enumerate(BRANCHES, start=1)
        },
    }
    path = root / "parity.yaml"
    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return path


class ManifestContractTests(unittest.TestCase):
    def test_accepts_plain_manifest_through_temporary_directory_short_alias(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            long_parent = root / "manifest-directory-with-long-name"
            long_parent.mkdir()
            path = long_parent / "parity-v3.yaml"
            path.write_bytes(
                (
                    ROOT
                    / "configs"
                    / "checkpoint_analytics_model_parity.yaml"
                ).read_bytes()
            )
            if os.name == "nt":
                import ctypes
                from ctypes import wintypes

                get_short_path_name = ctypes.WinDLL(
                    "kernel32",
                    use_last_error=True,
                ).GetShortPathNameW
                get_short_path_name.argtypes = [
                    wintypes.LPCWSTR,
                    wintypes.LPWSTR,
                    wintypes.DWORD,
                ]
                get_short_path_name.restype = wintypes.DWORD
                required = get_short_path_name(os.fspath(path), None, 0)
                if required == 0:
                    self.skipTest("Windows 8.3 aliases are unavailable")
                buffer = ctypes.create_unicode_buffer(required)
                written = get_short_path_name(
                    os.fspath(path),
                    buffer,
                    required,
                )
                if written == 0 or written >= required:
                    self.skipTest("Windows 8.3 alias lookup failed")
                candidate = Path(buffer.value)
                if candidate == path.resolve():
                    self.skipTest("Windows 8.3 aliases are disabled")
            else:
                candidate = path

            loaded = load_parity_manifest(candidate)

        self.assertEqual(loaded["schema_version"], 3)
        validate_manifest_identity(loaded)

    def test_rejects_symlink_or_reparse_parent_component(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            target = root / "plain-parent"
            target.mkdir()
            manifest = target / "parity-v3.yaml"
            manifest.write_bytes(
                (
                    ROOT
                    / "configs"
                    / "checkpoint_analytics_model_parity.yaml"
                ).read_bytes()
            )
            alias = root / "parent-alias"
            alias.symlink_to(target, target_is_directory=True)

            with self.assertRaisesRegex(
                ContractError,
                "manifest was not found|link|reparse",
            ):
                load_parity_manifest(alias / manifest.name)

    def test_resolve_runtime_error_is_contract_error_and_cli_exit_78(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            path = root / "parity-v3.yaml"
            path.write_bytes(
                (
                    ROOT
                    / "configs"
                    / "checkpoint_analytics_model_parity.yaml"
                ).read_bytes()
            )
            original_resolve = Path.resolve

            def fail_manifest_resolve(
                candidate: Path,
                *args: object,
                **kwargs: object,
            ) -> Path:
                if Path(os.path.abspath(os.fspath(candidate))) == path:
                    raise RuntimeError("simulated link loop")
                return original_resolve(candidate, *args, **kwargs)

            with (
                mock.patch.object(Path, "resolve", fail_manifest_resolve),
                self.assertRaisesRegex(
                    ContractError,
                    "manifest was not found|link loop",
                ),
            ):
                load_parity_manifest(path)

            with (
                mock.patch.object(Path, "resolve", fail_manifest_resolve),
                mock.patch("builtins.print") as printed,
            ):
                self.assertEqual(
                    main(["manifest", "--config", os.fspath(path)]),
                    78,
                )
            result = json.loads(printed.call_args.args[0])
            self.assertEqual(result["status"], "contract_error")

    def test_rejects_nonregular_missing_and_path_substituted_manifest(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            directory = root / "manifest-directory"
            directory.mkdir()
            for path in (root / "missing.yaml", directory):
                with self.subTest(path=path), self.assertRaisesRegex(
                    ContractError,
                    "manifest was not found",
                ):
                    load_parity_manifest(path)

            payload = (
                ROOT
                / "configs"
                / "checkpoint_analytics_model_parity.yaml"
            ).read_bytes()
            path = root / "parity-v3.yaml"
            replacement = root / "replacement.yaml"
            path.write_bytes(payload)
            replacement.write_bytes(payload)
            original_open = Path.open
            substitution_attempted = False
            substitution_blocked = False

            def substitute_before_open(
                opened_path: Path,
                *args: object,
                **kwargs: object,
            ):
                nonlocal substitution_attempted, substitution_blocked
                if (
                    not substitution_attempted
                    and Path(os.path.abspath(os.fspath(opened_path))) == path
                ):
                    substitution_attempted = True
                    try:
                        os.replace(replacement, path)
                    except OSError:
                        substitution_blocked = True
                return original_open(opened_path, *args, **kwargs)

            with mock.patch.object(Path, "open", substitute_before_open):
                if os.name == "nt":
                    loaded = load_parity_manifest(path)
                    validate_manifest_identity(loaded)
                else:
                    with self.assertRaisesRegex(
                        ContractError,
                        "changed|substitut|identity",
                    ):
                        load_parity_manifest(path)
            self.assertTrue(substitution_attempted)
            self.assertEqual(substitution_blocked, os.name == "nt")

    @unittest.skipUnless(os.name == "nt", "Windows share-mode custody only")
    def test_manifest_custody_blocks_same_size_in_place_rewrite_with_restored_mtime(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            path = root / "parity-v3.yaml"
            payload = (
                ROOT
                / "configs"
                / "checkpoint_analytics_model_parity.yaml"
            ).read_bytes()
            path.write_bytes(payload)
            original_open = Path.open
            rewrite_attempted = False
            rewrite_blocked = False

            def rewrite_during_read(
                opened_path: Path,
                *args: object,
                **kwargs: object,
            ):
                nonlocal rewrite_attempted, rewrite_blocked
                if (
                    not rewrite_attempted
                    and Path(os.path.abspath(os.fspath(opened_path))) == path
                ):
                    rewrite_attempted = True
                    before = path.stat()
                    try:
                        with original_open(path, "r+b") as writer:
                            writer.write(payload)
                            writer.flush()
                            os.fsync(writer.fileno())
                        os.utime(
                            path,
                            ns=(before.st_atime_ns, before.st_mtime_ns),
                        )
                    except OSError:
                        rewrite_blocked = True
                return original_open(opened_path, *args, **kwargs)

            with mock.patch.object(Path, "open", rewrite_during_read):
                loaded = load_parity_manifest(path)

            self.assertTrue(rewrite_attempted)
            self.assertTrue(rewrite_blocked)
            validate_manifest_identity(loaded)

    @unittest.skipUnless(os.name == "nt", "Windows pre-custody drift only")
    def test_manifest_rejects_same_size_rewrite_before_native_custody(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            path = root / "parity-v3.yaml"
            payload = (
                ROOT
                / "configs"
                / "checkpoint_analytics_model_parity.yaml"
            ).read_bytes()
            mutated_payload = payload.replace(b"false", b"False", 1)
            self.assertNotEqual(mutated_payload, payload)
            self.assertEqual(len(mutated_payload), len(payload))
            self.assertEqual(
                yaml.safe_load(mutated_payload),
                yaml.safe_load(payload),
            )
            path.write_bytes(payload)
            original_custody = checkpoint_model_parity_module._manifest_native_custody
            rewrite_completed = False

            @contextlib.contextmanager
            def rewrite_at_custody_entry(chains: object):
                nonlocal rewrite_completed
                if not rewrite_completed:
                    before = path.stat()
                    with path.open("r+b") as writer:
                        writer.write(mutated_payload)
                        writer.flush()
                        os.fsync(writer.fileno())
                    os.utime(
                        path,
                        ns=(before.st_atime_ns, before.st_mtime_ns),
                    )
                    rewrite_completed = True
                with original_custody(chains) as entries:
                    yield entries

            with (
                mock.patch.object(
                    checkpoint_model_parity_module,
                    "_manifest_native_custody",
                    rewrite_at_custody_entry,
                ),
                self.assertRaisesRegex(
                    ContractError,
                    "bytes changed before native custody",
                ),
            ):
                load_parity_manifest(path)
            self.assertTrue(rewrite_completed)

    @unittest.skipUnless(os.name == "nt", "Windows ctime views only")
    def test_windows_cross_view_ignores_only_ctime_and_each_view_binds_it(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            path = root / "parity-v3.yaml"
            path.write_bytes(
                (
                    ROOT
                    / "configs"
                    / "checkpoint_analytics_model_parity.yaml"
                ).read_bytes()
            )
            chain = checkpoint_model_parity_module._manifest_chain_snapshot(path)
            original_open_custody = (
                checkpoint_model_parity_module._open_windows_custody_handle
            )

            def expose_alternate_native_ctime(
                candidate: Path,
                *,
                is_directory: bool,
            ):
                handle, state, attributes = original_open_custody(
                    candidate,
                    is_directory=is_directory,
                )
                if not is_directory:
                    state = (*state[:-1], state[-1] + 100)
                return handle, state, attributes

            with mock.patch.object(
                checkpoint_model_parity_module,
                "_open_windows_custody_handle",
                expose_alternate_native_ctime,
            ):
                with checkpoint_model_parity_module._windows_manifest_custody(
                    (chain,)
                ) as entries:
                    with self.assertRaisesRegex(
                        ContractError,
                        "native handle changed",
                    ):
                        checkpoint_model_parity_module._validate_native_custody(
                            entries
                        )

            leaf_path, leaf_state = chain[-1]
            changed_path_chain = (
                *chain[:-1],
                (leaf_path, (*leaf_state[:-1], leaf_state[-1] + 100)),
            )
            with self.assertRaisesRegex(ContractError, "identity changed"):
                checkpoint_model_parity_module._require_manifest_chain_unchanged(
                    chain,
                    changed_path_chain,
                )

    @unittest.skipUnless(os.name == "nt", "Windows path-view ctime only")
    def test_windows_same_view_callsites_reject_ctime_only_drift(self) -> None:
        phase_calls = {
            "preflight": {2},
            "lexical_open_to_final": {7, 9},
            "resolved_open_to_final": {8, 10},
        }
        for phase, shifted_calls in phase_calls.items():
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                path = root / "parity-v3.yaml"
                path.write_bytes(
                    (
                        ROOT
                        / "configs"
                        / "checkpoint_analytics_model_parity.yaml"
                    ).read_bytes()
                )
                original_snapshot = (
                    checkpoint_model_parity_module._manifest_chain_snapshot
                )
                call_index = 0

                def inject_ctime_only(candidate: Path):
                    nonlocal call_index
                    call_index += 1
                    chain = original_snapshot(candidate)
                    if call_index not in shifted_calls:
                        return chain
                    leaf_path, leaf_state = chain[-1]
                    return (
                        *chain[:-1],
                        (leaf_path, (*leaf_state[:-1], leaf_state[-1] + 100)),
                    )

                with (
                    mock.patch.object(
                        checkpoint_model_parity_module,
                        "_manifest_chain_snapshot",
                        inject_ctime_only,
                    ),
                    self.assertRaisesRegex(ContractError, "identity changed"),
                ):
                    load_parity_manifest(path)

    @unittest.skipIf(os.name == "nt", "POSIX ctime detection only")
    def test_posix_same_size_byte_drift_with_restored_mtime_is_detected(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            path = root / "parity-v3.yaml"
            payload = (
                ROOT
                / "configs"
                / "checkpoint_analytics_model_parity.yaml"
            ).read_bytes()
            mutated_payload = payload.replace(b"false", b"False", 1)
            self.assertNotEqual(mutated_payload, payload)
            self.assertEqual(len(mutated_payload), len(payload))
            self.assertEqual(
                yaml.safe_load(mutated_payload),
                yaml.safe_load(payload),
            )
            path.write_bytes(payload)
            original_open = Path.open
            rewrite_completed = False

            def rewrite_during_open(
                opened_path: Path,
                *args: object,
                **kwargs: object,
            ):
                nonlocal rewrite_completed
                if (
                    not rewrite_completed
                    and Path(os.path.abspath(os.fspath(opened_path))) == path
                ):
                    before = path.stat()
                    with original_open(path, "r+b") as writer:
                        writer.write(mutated_payload)
                        writer.flush()
                        os.fsync(writer.fileno())
                    os.utime(
                        path,
                        ns=(before.st_atime_ns, before.st_mtime_ns),
                    )
                    rewrite_completed = True
                return original_open(opened_path, *args, **kwargs)

            with (
                mock.patch.object(Path, "open", rewrite_during_open),
                self.assertRaisesRegex(ContractError, "changed|identity"),
            ):
                load_parity_manifest(path)
            self.assertTrue(rewrite_completed)

    def test_post_read_rewrite_is_blocked_or_detected_before_return(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            path = root / "parity-v3.yaml"
            payload = (
                ROOT
                / "configs"
                / "checkpoint_analytics_model_parity.yaml"
            ).read_bytes()
            path.write_bytes(payload)
            original_validate = checkpoint_model_parity_module._validate_manifest_v3
            rewrite_attempted = False
            rewrite_blocked = False

            def rewrite_during_validation(value: object) -> None:
                nonlocal rewrite_attempted, rewrite_blocked
                if not rewrite_attempted:
                    rewrite_attempted = True
                    before = path.stat()
                    try:
                        with path.open("r+b") as writer:
                            writer.write(payload)
                            writer.flush()
                            os.fsync(writer.fileno())
                        os.utime(
                            path,
                            ns=(before.st_atime_ns, before.st_mtime_ns),
                        )
                    except OSError:
                        rewrite_blocked = True
                original_validate(value)

            with mock.patch.object(
                checkpoint_model_parity_module,
                "_validate_manifest_v3",
                rewrite_during_validation,
            ):
                if os.name == "nt":
                    loaded = load_parity_manifest(path)
                    validate_manifest_identity(loaded)
                else:
                    with self.assertRaisesRegex(
                        ContractError,
                        "changed|identity",
                    ):
                        load_parity_manifest(path)

            self.assertTrue(rewrite_attempted)
            self.assertEqual(rewrite_blocked, os.name == "nt")

    @unittest.skipUnless(os.name == "nt", "Windows share-mode custody only")
    def test_manifest_ancestor_custody_blocks_parent_rename_aba(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            parent = root / "manifest-parent"
            parent.mkdir()
            renamed = root / "manifest-parent-renamed"
            path = parent / "parity-v3.yaml"
            path.write_bytes(
                (
                    ROOT
                    / "configs"
                    / "checkpoint_analytics_model_parity.yaml"
                ).read_bytes()
            )
            original_open = Path.open
            rename_attempted = False
            rename_blocked = False

            def rename_parent_during_read(
                opened_path: Path,
                *args: object,
                **kwargs: object,
            ):
                nonlocal rename_attempted, rename_blocked
                if (
                    not rename_attempted
                    and Path(os.path.abspath(os.fspath(opened_path))) == path
                ):
                    rename_attempted = True
                    try:
                        os.replace(parent, renamed)
                        os.replace(renamed, parent)
                    except OSError:
                        rename_blocked = True
                return original_open(opened_path, *args, **kwargs)

            with mock.patch.object(Path, "open", rename_parent_during_read):
                loaded = load_parity_manifest(path)

            self.assertTrue(rename_attempted)
            self.assertTrue(rename_blocked)
            validate_manifest_identity(loaded)

    def test_rejects_hardlinked_manifest_as_non_unique(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            path = root / "parity-v3.yaml"
            alias = root / "parity-v3-hardlink.yaml"
            path.write_bytes(
                (
                    ROOT
                    / "configs"
                    / "checkpoint_analytics_model_parity.yaml"
                ).read_bytes()
            )
            os.link(path, alias)

            with self.assertRaisesRegex(ContractError, "hardlink|unique"):
                load_parity_manifest(alias)

    def test_unhashable_yaml_keys_are_contract_errors_and_cli_exit_78(self) -> None:
        malformed_payloads = (
            "? [sequence, key]\n: value\n",
            "? {mapping: key}\n: value\n",
        )
        for index, payload in enumerate(malformed_payloads):
            with self.subTest(index=index), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp).resolve() / "unhashable-key.yaml"
                path.write_text(payload, encoding="utf-8")

                with self.assertRaisesRegex(
                    ContractError,
                    "invalid model parity manifest",
                ):
                    load_parity_manifest(path)

                with mock.patch("builtins.print") as printed:
                    self.assertEqual(
                        main(["manifest", "--config", os.fspath(path)]),
                        78,
                    )
                result = json.loads(printed.call_args.args[0])
                self.assertEqual(result["status"], "contract_error")

    def test_deep_yaml_recursion_is_contract_error_and_cli_exit_78(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp).resolve() / "deeply-nested.yaml"
            path.write_text(
                "value: " + "[" * 2000 + "0" + "]" * 2000 + "\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                ContractError,
                "invalid model parity manifest",
            ):
                load_parity_manifest(path)

            with mock.patch("builtins.print") as printed:
                self.assertEqual(
                    main(["manifest", "--config", os.fspath(path)]),
                    78,
                )
            result = json.loads(printed.call_args.args[0])
            self.assertEqual(result["status"], "contract_error")

    def test_manifest_identity_is_deterministic_and_tamper_evident(self) -> None:
        loaded = load_parity_manifest(
            ROOT / "configs" / "checkpoint_analytics_model_parity.yaml"
        )
        self.assertEqual(loaded["required_branches"], list(BRANCHES))
        self.assertRegex(loaded["identity"]["sha256"], r"^[0-9a-f]{64}$")
        validate_manifest_identity(loaded)
        self.assertEqual(
            loaded["identity"]["sha256"],
            load_parity_manifest(
                ROOT / "configs" / "checkpoint_analytics_model_parity.yaml"
            )["identity"]["sha256"],
        )
        tampered = copy.deepcopy(loaded)
        tampered["evidence_policy"]["minimum_calibration_samples_per_branch"] = 1
        with self.assertRaisesRegex(ContractError, "identity|calibration"):
            validate_manifest_identity(tampered)

    def test_preprocessing_projection_accepts_frozen_v3_and_v4_by_binding_hash(self) -> None:
        source = ROOT / "configs" / "checkpoint_analytics_model_parity.yaml"
        raw = yaml.safe_load(source.read_text(encoding="utf-8"))
        expected = canonical_sha(raw["preprocessing_contract"])
        self.assertEqual(
            load_parity_preprocessing_contract(
                source, expected_sha256=expected
            ),
            raw["preprocessing_contract"],
        )

        raw["schema_version"] = 4
        raw["artifact_kind"] = "checkpoint_analytics_model_parity_manifest_v4"
        raw["manifest_id"] = str(raw["manifest_id"]).removesuffix("-v3") + "-v4"
        raw["refresh_authority"] = {
            "source_manifest": {},
            "image_identity_patch": {},
            "runtime_probes": {},
            "execution_config": {},
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp).resolve() / "accepted-v4.yaml"
            path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
            self.assertEqual(
                load_parity_preprocessing_contract(
                    path, expected_sha256=expected
                ),
                raw["preprocessing_contract"],
            )
            with self.assertRaisesRegex(
                ContractError, "differs from execution bindings"
            ):
                load_parity_preprocessing_contract(
                    path, expected_sha256="0" * 64
                )

    def test_preprocessing_projection_rejects_v4_schema_and_contract_drift(self) -> None:
        raw = yaml.safe_load(
            (
                ROOT / "configs" / "checkpoint_analytics_model_parity.yaml"
            ).read_text(encoding="utf-8")
        )
        expected = canonical_sha(raw["preprocessing_contract"])
        raw["schema_version"] = 4
        raw["artifact_kind"] = "checkpoint_analytics_model_parity_manifest_v4"
        raw["manifest_id"] = str(raw["manifest_id"]).removesuffix("-v3") + "-v4"
        raw["refresh_authority"] = {
            "source_manifest": {},
            "image_identity_patch": {},
            "runtime_probes": {},
            "execution_config": {},
        }
        raw["preprocessing_contract"]["resize_shorter_side"] = 255
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp).resolve() / "drifted-v4.yaml"
            path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
            with self.assertRaisesRegex(ContractError, "geometry drifted"):
                load_parity_preprocessing_contract(
                    path, expected_sha256=expected
                )

    def test_rejects_fake_openvino_gpu_matrix_binding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "parity-v2.yaml"
            raw = yaml.safe_load((ROOT / "configs" / "checkpoint_analytics_model_parity.yaml").read_text(encoding="utf-8"))
            raw["matrix_binding"]["gpu"]["runtime"] = "openvino"
            raw["matrix_binding"]["gpu"]["device_api"] = "OPENVINO_GPU"
            path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
            with self.assertRaisesRegex(ContractError, "TensorRT|NVIDIA_CUDA|OpenVINO GPU"):
                load_parity_manifest(path)

    def test_rejects_symlinked_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = complete_manifest(root)
            link = root / "parity-link.yaml"
            link.symlink_to(target.name)
            with self.assertRaisesRegex(ContractError, "manifest was not found"):
                load_parity_manifest(link)

    def test_cli_exposes_only_manifest_and_assess(self) -> None:
        parser = build_parser()
        self.assertEqual(parser.parse_args(["manifest"]).command, "manifest")
        self.assertEqual(parser.parse_args(["assess"]).command, "assess")
        with self.assertRaises(SystemExit):
            parser.parse_args(["run"])

    def test_default_v3_manifest_remains_blocked_on_all_32_evidence_refs(self) -> None:
        result = assess_model_parity(
            ROOT / "configs" / "checkpoint_analytics_model_parity.yaml",
            project_root=ROOT,
            command_runner=image_runner([]),
        )
        self.assertFalse(result["publication_ready"])
        self.assertEqual(result["schema_version"], 3)
        self.assertEqual(
            sum("evidence_missing" in blocker for blocker in result["blockers"]),
            32,
        )


@unittest.skip("schema-v1 fixture retained only as migration history")
class AssessmentTests(unittest.TestCase):
    def test_complete_common_source_contract_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            commands: list[list[str]] = []
            result = assess_model_parity(
                complete_manifest(root),
                project_root=root,
                command_runner=image_runner(commands),
            )
        self.assertTrue(result["publication_ready"])
        self.assertEqual(result["blockers"], [])
        self.assertEqual(set(result["branches"]), set(BRANCHES))
        self.assertTrue(all(value["ready"] for value in result["branches"].values()))
        self.assertEqual(len(commands), 2)
        self.assertTrue(all(command[:3] == ["docker", "image", "inspect"] for command in commands))

    def test_verified_equivalent_derivations_can_replace_a_local_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = complete_manifest(root)
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            branch = raw["branches"]["damage"]
            graph_sha = hashlib.sha256(b"official-canonical-graph-damage").hexdigest()
            branch["lineage_mode"] = "verified_equivalent_derivations"
            branch["source_artifact"] = {
                "format": "onnx",
                "path": None,
                "sha256": None,
                "opset": None,
                "exporter": {"name": None, "version": None, "command_sha256": None},
            }
            branch["openvino_ir"]["derived_from_source_sha256"] = graph_sha
            branch["tensorrt_engine"]["derived_from_source_sha256"] = graph_sha
            proof_path = root / "artifacts" / "damage" / "lineage_equivalence.json"
            write_json(
                proof_path,
                {
                    "schema_version": 1,
                    "artifact_kind": "checkpoint_model_lineage_equivalence",
                    "branch": "damage",
                    "proof_method": "official_exporter_attestation_and_graph_digest_v1",
                    "openvino_model_sha256": branch["openvino_ir"]["model"]["sha256"],
                    "openvino_weights_sha256": branch["openvino_ir"]["weights"]["sha256"],
                    "tensorrt_engine_sha256": branch["tensorrt_engine"]["artifact"]["sha256"],
                    "openvino_derivation_graph_sha256": graph_sha,
                    "tensorrt_derivation_graph_sha256": graph_sha,
                    "attestation_sha256": hashlib.sha256(b"official-attestation").hexdigest(),
                },
            )
            branch["lineage_equivalence_evidence"] = ref(root, proof_path)

            for probe_name in ("cpu_execution_probe", "cuda_execution_probe"):
                probe_ref = branch["evidence"][probe_name]
                probe_path = root / probe_ref["path"]
                probe = json.loads(probe_path.read_text(encoding="utf-8"))
                probe["source_sha256"] = graph_sha
                write_json(probe_path, probe)
                probe_ref["sha256"] = file_sha(probe_path)
            calibration_ref = branch["evidence"]["calibration"]
            calibration_path = root / calibration_ref["path"]
            calibration = json.loads(calibration_path.read_text(encoding="utf-8"))
            calibration["source_sha256"] = graph_sha
            write_json(calibration_path, calibration)
            calibration_ref["sha256"] = file_sha(calibration_path)
            parity_ref = branch["evidence"]["numeric_parity"]
            parity_path = root / parity_ref["path"]
            parity = json.loads(parity_path.read_text(encoding="utf-8"))
            parity["source_sha256"] = graph_sha
            parity["cpu_probe_sha256"] = branch["evidence"]["cpu_execution_probe"]["sha256"]
            parity["cuda_probe_sha256"] = branch["evidence"]["cuda_execution_probe"]["sha256"]
            parity["calibration_evidence_sha256"] = calibration_ref["sha256"]
            write_json(parity_path, parity)
            parity_ref["sha256"] = file_sha(parity_path)
            path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")

            result = assess_model_parity(
                path,
                project_root=root,
                command_runner=image_runner([]),
            )
        self.assertTrue(result["publication_ready"])
        self.assertEqual(result["branches"]["damage"]["source_identity_sha256"], graph_sha)

    def test_repository_state_is_honestly_blocked(self) -> None:
        commands: list[list[str]] = []
        result = assess_model_parity(
            ROOT / "configs" / "checkpoint_analytics_model_parity.yaml",
            project_root=ROOT,
            command_runner=image_runner(commands),
        )
        self.assertFalse(result["publication_ready"])
        self.assertFalse(result["openvino_gpu_counted_as_nvidia_cuda"])
        for branch in BRANCHES:
            blockers = result["branches"][branch]["blockers"]
            self.assertIn(f"branch:{branch}:canonical_source_artifact_missing", blockers)
            self.assertIn(f"branch:{branch}:tensorrt_engine_artifact_missing", blockers)
            self.assertIn(f"branch:{branch}:cpu_execution_probe_evidence_missing", blockers)
            self.assertIn(f"branch:{branch}:cuda_execution_probe_evidence_missing", blockers)
            self.assertIn(f"branch:{branch}:numeric_parity_evidence_missing", blockers)
            self.assertIn(f"branch:{branch}:calibration_evidence_missing", blockers)
            self.assertTrue(result["branches"][branch]["artifacts"]["openvino_model"]["present"])
            self.assertTrue(result["branches"][branch]["artifacts"]["openvino_weights"]["present"])

    def test_symlinked_model_artifact_is_not_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = complete_manifest(root)
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            branch = raw["branches"]["plate_number"]
            source = root / branch["source_artifact"]["path"]
            alias = source.with_name("source-alias.onnx")
            alias.symlink_to(source.name)
            branch["source_artifact"]["path"] = alias.relative_to(root).as_posix()
            path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")

            result = assess_model_parity(
                path,
                project_root=root,
                command_runner=image_runner([]),
            )

        self.assertFalse(result["publication_ready"])
        self.assertIn(
            "branch:plate_number:canonical_source_artifact_missing",
            result["branches"]["plate_number"]["blockers"],
        )

    def test_lineage_preprocessing_and_toolchain_drift_fail_closed(self) -> None:
        mutations = (
            (
                lambda raw: raw["branches"]["damage"]["openvino_ir"].update(
                    {"derived_from_source_sha256": "0" * 64}
                ),
                "branch:damage:openvino_source_lineage_mismatch",
            ),
            (
                lambda raw: raw["branches"]["damage"]["preprocessing"].update(
                    {"resize_algorithm": None}
                ),
                "branch:damage:preprocessing_contract_incomplete:resize_algorithm",
            ),
            (
                lambda raw: raw["branches"]["damage"]["tensorrt_engine"]["toolchain"].update(
                    {"builder_flags_sha256": None}
                ),
                "branch:damage:tensorrt_toolchain_incomplete:builder_flags_sha256",
            ),
        )
        for mutate, blocker in mutations:
            with self.subTest(blocker=blocker), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                path = complete_manifest(root)
                raw = yaml.safe_load(path.read_text(encoding="utf-8"))
                mutate(raw)
                path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
                result = assess_model_parity(
                    path,
                    project_root=root,
                    command_runner=image_runner([]),
                )
                self.assertFalse(result["publication_ready"])
                self.assertIn(blocker, result["branches"]["damage"]["blockers"])

    def test_openvino_gpu_execution_evidence_is_not_cuda(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = complete_manifest(root)
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            gpu_ref = raw["branches"]["vehicle_type"]["evidence"]["cuda_execution_probe"]
            gpu_path = root / gpu_ref["path"]
            evidence = json.loads(gpu_path.read_text(encoding="utf-8"))
            evidence["runtime"] = "openvino"
            evidence["device_api"] = "OPENVINO_GPU"
            write_json(gpu_path, evidence)
            gpu_ref["sha256"] = file_sha(gpu_path)
            path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
            result = assess_model_parity(
                path,
                project_root=root,
                command_runner=image_runner([]),
            )
        self.assertIn(
            "branch:vehicle_type:cuda_execution_probe_not_nvidia_tensorrt",
            result["branches"]["vehicle_type"]["blockers"],
        )

    def test_calibration_minimum_and_numeric_tolerances_are_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = complete_manifest(root)
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            corpus_ref = raw["branches"]["foreign_object"]["evidence"]["calibration_corpus"]
            corpus_path = root / corpus_ref["path"]
            corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
            corpus["sample_count"] = MIN_CALIBRATION_SAMPLES - 1
            corpus["unique_sample_count"] = MIN_CALIBRATION_SAMPLES - 1
            write_json(corpus_path, corpus)
            corpus_ref["sha256"] = file_sha(corpus_path)
            path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
            result = assess_model_parity(
                path,
                project_root=root,
                command_runner=image_runner([]),
            )
            self.assertIn(
                "branch:foreign_object:calibration_corpus_below_30",
                result["branches"]["foreign_object"]["blockers"],
            )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = complete_manifest(root)
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            parity_ref = raw["branches"]["plate_number"]["evidence"]["numeric_parity"]
            parity_path = root / parity_ref["path"]
            parity = json.loads(parity_path.read_text(encoding="utf-8"))
            parity["metrics"]["raw_max_abs_error"] = (
                PARITY_TOLERANCES["raw_max_abs_error"] * 2.0
            )
            write_json(parity_path, parity)
            parity_ref["sha256"] = file_sha(parity_path)
            path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
            result = assess_model_parity(
                path,
                project_root=root,
                command_runner=image_runner([]),
            )
            self.assertIn(
                "branch:plate_number:numeric_parity_tolerance_exceeded:raw_max_abs_error",
                result["branches"]["plate_number"]["blockers"],
            )

    def test_calibration_and_evaluation_sample_ids_must_be_disjoint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = complete_manifest(root)
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            evidence = raw["branches"]["vehicle_type"]["evidence"]
            calibration_path = root / evidence["calibration_corpus"]["path"]
            parity_corpus_path = root / evidence["parity_corpus"]["path"]
            calibration_corpus = json.loads(calibration_path.read_text(encoding="utf-8"))
            parity_corpus = json.loads(parity_corpus_path.read_text(encoding="utf-8"))
            parity_corpus["sample_ids"][0] = calibration_corpus["sample_ids"][0]
            parity_corpus["sample_ids_sha256"] = canonical_sha(parity_corpus["sample_ids"])
            write_json(parity_corpus_path, parity_corpus)
            evidence["parity_corpus"]["sha256"] = file_sha(parity_corpus_path)
            parity_path = root / evidence["numeric_parity"]["path"]
            parity = json.loads(parity_path.read_text(encoding="utf-8"))
            parity["corpus_manifest_sha256"] = evidence["parity_corpus"]["sha256"]
            write_json(parity_path, parity)
            evidence["numeric_parity"]["sha256"] = file_sha(parity_path)
            path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")

            result = assess_model_parity(
                path,
                project_root=root,
                command_runner=image_runner([]),
            )
        self.assertIn(
            "branch:vehicle_type:calibration_and_evaluation_corpora_not_disjoint",
            result["branches"]["vehicle_type"]["blockers"],
        )

    def test_non_finite_tolerance_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = complete_manifest(root)
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            raw["evidence_policy"]["tolerances"]["raw_max_abs_error"] = math.inf
            path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
            with self.assertRaisesRegex(ContractError, "tolerance"):
                load_parity_manifest(path)

    def test_image_command_cannot_pull_or_run(self) -> None:
        command = build_image_inspect_command("vast/deepstream-native-probe:7.0")
        self.assertEqual(command[:3], ["docker", "image", "inspect"])
        self.assertNotIn("pull", command)
        self.assertNotIn("run", command)


def _fixture_sha(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _write_evidence(root: Path, branch: str, name: str, value: object) -> dict[str, object]:
    path = root / "evidence" / branch / f"{name}.json"
    write_json(path, value)
    return ref(root, path)


def complete_v3_manifest(root: Path, *, cuda_delta: float = 0.00001) -> Path:
    raw = yaml.safe_load(
        (ROOT / "configs" / "checkpoint_analytics_model_parity.yaml").read_text(
            encoding="utf-8"
        )
    )
    raw["manifest_id"] = "synthetic-complete-parity-v3"
    raw["matrix_binding"]["cpu"]["image_id"] = CPU_IMAGE_ID
    raw["matrix_binding"]["gpu"]["image_id"] = GPU_IMAGE_ID
    raw["toolchain_registry"]["openvino_cpu"]["image_id"] = CPU_IMAGE_ID
    raw["toolchain_registry"]["tensorrt_cuda"]["image_id"] = GPU_IMAGE_ID
    raw["worker_runtime_registry"]["openvino_cpu"]["base_image_id"] = CPU_IMAGE_ID
    raw["worker_runtime_registry"]["openvino_cpu"]["image_id"] = CPU_WORKER_IMAGE_ID
    raw["worker_runtime_registry"]["openvino_cpu"]["worker_implementation_sha256"] = CPU_WORKER_IMPLEMENTATION_SHA
    raw["worker_runtime_registry"]["tensorrt_cuda"]["base_image_id"] = GPU_IMAGE_ID
    raw["worker_runtime_registry"]["tensorrt_cuda"]["image_id"] = GPU_WORKER_IMAGE_ID
    raw["worker_runtime_registry"]["tensorrt_cuda"]["worker_implementation_sha256"] = GPU_WORKER_IMPLEMENTATION_SHA
    preprocessing_sha = canonical_sha(raw["preprocessing_contract"])

    for branch in BRANCHES:
        slot = raw["workload_slots"][branch]
        source = raw["source_registry"][slot["source_ref"]]
        artifact_dir = root / "artifacts" / branch
        artifact_dir.mkdir(parents=True, exist_ok=True)
        source_path = artifact_dir / source["filename"]
        source_path.write_bytes(f"fixture-onnx-{branch}\n".encode("ascii"))
        source["path"] = source_path.relative_to(root).as_posix()
        source["sha256"] = file_sha(source_path)
        source["size_bytes"] = source_path.stat().st_size
        ov = slot["openvino_ir"]
        trt = slot["tensorrt_engine"]
        for key, suffix in (("model", ".xml"), ("weights", ".bin")):
            path = artifact_dir / f"{branch}{suffix}"
            path.write_bytes(f"fixture-openvino-{key}-{branch}\n".encode("ascii"))
            ov[key] = sized_ref(root, path)
        engine_path = artifact_dir / f"{branch}.engine"
        engine_path.write_bytes(f"fixture-tensorrt-{branch}\n".encode("ascii"))
        trt["artifact"] = sized_ref(root, engine_path)
        ov["derived_from_source_sha256"] = source["sha256"]
        trt["derived_from_source_sha256"] = source["sha256"]
        output_sha = canonical_sha(
            {
                "classification_contract": raw["classification_contract"],
                "source_output": source["output"],
            }
        )
        cpu_probe = {
            "schema_version": 3,
            "artifact_kind": "checkpoint_model_execution_probe",
            "branch": branch,
            "workload_slot_id": slot["slot_id"],
            "resource": "openvino_cpu",
            "runtime": "openvino",
            "device_api": "OPENVINO_CPU",
            "device_id": "CPU",
            "success": True,
            "source_sha256": source["sha256"],
            "model_sha256": ov["model"]["sha256"],
            "weights_sha256": ov["weights"]["sha256"],
            "engine_sha256": None,
            "preprocessing_contract_sha256": preprocessing_sha,
            "output_contract_sha256": output_sha,
            "runtime_image_id": CPU_WORKER_IMAGE_ID,
            "worker_implementation_sha256": CPU_WORKER_IMPLEMENTATION_SHA,
            "input_name": source["input"]["name"],
            "input_shape": source["input"]["execution_shape"],
            "input_dtype": "float32",
            "output_name": source["output"]["name"],
            "output_shape": [1, 1000],
            "output_dtype": "float32",
            "sample_count": 1,
            "all_outputs_finite": True,
        }
        cuda_probe = dict(cpu_probe)
        cuda_probe.update(
            {
                "resource": "tensorrt_cuda",
                "runtime": "tensorrt",
                "device_api": "NVIDIA_CUDA",
                "device_id": raw["toolchain_registry"]["tensorrt_cuda"]["gpu_uuid"],
                "model_sha256": None,
                "weights_sha256": None,
                "engine_sha256": trt["artifact"]["sha256"],
                "runtime_image_id": GPU_WORKER_IMAGE_ID,
                "worker_implementation_sha256": GPU_WORKER_IMPLEMENTATION_SHA,
            }
        )
        evidence = slot["evidence"]
        evidence["cpu_execution_probe"] = _write_evidence(root, branch, "cpu_execution_probe", cpu_probe)
        evidence["cuda_execution_probe"] = _write_evidence(root, branch, "cuda_execution_probe", cuda_probe)
        dataset_files = []
        for file_index, codec in enumerate(("h264", "h265")):
            video = artifact_dir / f"dataset-{codec}.bin"
            video.write_bytes((f"fixture-{codec}-{branch}\n" * 4).encode("ascii"))
            dataset_files.append(
                {
                    "file_id": f"{branch}-{codec}",
                    "file_index": file_index,
                    "path": video.relative_to(root).as_posix(),
                    "sha256": file_sha(video),
                    "size_bytes": video.stat().st_size,
                    "codec": codec,
                    "container": "annex_b",
                }
            )
        dataset_manifest = {
            "schema_version": 2,
            "artifact_kind": "checkpoint_model_dataset_manifest",
            "dataset_id": f"fixture-{branch}-h264-h265",
            "files": dataset_files,
            "files_sha256": canonical_sha(dataset_files),
        }
        dataset_ref = _write_evidence(root, branch, "dataset_manifest", dataset_manifest)
        dataset_aggregate = canonical_sha(
            {"dataset_id": dataset_manifest["dataset_id"], "files": dataset_files}
        )
        decoder_impl = artifact_dir / "decoder-implementation.bin"
        decoder_impl.write_bytes(b"fixture-decoder-implementation-v2\n")
        preprocess_impl = artifact_dir / "preprocessing-implementation.py"
        preprocess_impl.write_bytes(b"fixture-preprocessing-implementation-v2\n")
        producer_contract = {
            "decoder": {
                "name": "fixture-decoder",
                "version": "2.0",
                "runtime_image_id": CPU_IMAGE_ID,
                "implementation": sized_ref(root, decoder_impl),
                "canonical_argv_sha256": _fixture_sha("fixture-decoder-argv-v2"),
                "pixel_format": "rgb24",
            },
            "preprocessing": {
                "implementation": sized_ref(root, preprocess_impl),
                "canonical_argv_sha256": _fixture_sha("fixture-preprocess-argv-v2"),
                "contract_sha256": preprocessing_sha,
            },
        }
        raw_frame_bundle = artifact_dir / "raw-rgb-frame.bundle"
        raw_frame_bundle.write_bytes(bytes(range(12)))
        tensor_bundle = artifact_dir / "preprocessed-fp32.bundle"
        tensor_bundle.write_bytes(b"\0" * (1 * 3 * 224 * 224 * 4))

        def physical_samples(role_name: str, start_frame: int, count: int) -> list[dict[str, object]]:
            result = []
            raw_segment_sha = file_sha(raw_frame_bundle)
            tensor_segment_sha = file_sha(tensor_bundle)
            for index in range(count):
                file_record = dataset_files[index % 2]
                frame_index = start_frame + index
                pts_ns = frame_index * 40_000_000
                raw_descriptor = {
                    **sized_ref(root, raw_frame_bundle),
                    "offset_bytes": 0,
                    "length_bytes": 12,
                    "segment_sha256": raw_segment_sha,
                    "encoding": "raw_bytes_v1",
                    "dtype": "uint8",
                    "shape": [2, 2, 3],
                    "layout": "HWC",
                    "color_order": "RGB",
                }
                tensor_descriptor = {
                    **sized_ref(root, tensor_bundle),
                    "offset_bytes": 0,
                    "length_bytes": 1 * 3 * 224 * 224 * 4,
                    "segment_sha256": tensor_segment_sha,
                    "encoding": "raw_f32_le_c_contiguous_v1",
                    "dtype": "float32",
                    "shape": [1, 3, 224, 224],
                    "layout": "NCHW",
                    "color_order": "RGB",
                }
                physical_payload = {
                    "dataset_aggregate_sha256": dataset_aggregate,
                    "dataset_file_id": file_record["file_id"],
                    "dataset_file_sha256": file_record["sha256"],
                    "codec": file_record["codec"],
                    "file_index": file_record["file_index"],
                    "stream_index": 0,
                    "frame_index": frame_index,
                    "pts_ns": pts_ns,
                    "raw_frame_sha256": raw_segment_sha,
                }
                result.append(
                    {
                        "sample_id": f"{role_name}-{branch}-{index:03d}",
                        "physical_sample_sha256": canonical_sha(physical_payload),
                        "dataset_file_id": file_record["file_id"],
                        "dataset_file_sha256": file_record["sha256"],
                        "codec": file_record["codec"],
                        "file_index": file_record["file_index"],
                        "stream_index": 0,
                        "frame_index": frame_index,
                        "pts_ns": pts_ns,
                        "input_sha256": raw_segment_sha,
                        "preprocessed_tensor_sha256": tensor_segment_sha,
                        "raw_frame": raw_descriptor,
                        "preprocessed_tensor": tensor_descriptor,
                    }
                )
            return result

        calibration_samples = physical_samples("cal", 0, MIN_CALIBRATION_SAMPLES)
        evaluation_samples = physical_samples("eval", 1000, MIN_PARITY_SAMPLES)
        calibration_corpus = {
            "schema_version": 2,
            "artifact_kind": "checkpoint_model_parity_corpus",
            "branch": branch,
            "workload_slot_id": slot["slot_id"],
            "corpus_role": "calibration",
            "dataset_manifest": dataset_ref,
            "dataset_aggregate_sha256": dataset_aggregate,
            "producer_contract": producer_contract,
            "sample_count": len(calibration_samples),
            "samples": calibration_samples,
            "samples_sha256": canonical_sha(calibration_samples),
        }
        evaluation_corpus = dict(calibration_corpus)
        evaluation_corpus.update(
            {
                "corpus_role": "evaluation",
                "sample_count": len(evaluation_samples),
                "samples": evaluation_samples,
                "samples_sha256": canonical_sha(evaluation_samples),
            }
        )
        evidence["calibration_corpus"] = _write_evidence(root, branch, "calibration_corpus", calibration_corpus)
        evidence["evaluation_corpus"] = _write_evidence(root, branch, "evaluation_corpus", evaluation_corpus)

        def artifact_binding(resource: str) -> dict[str, object]:
            if resource == "openvino_cpu":
                return {
                    "model_sha256": ov["model"]["sha256"],
                    "weights_sha256": ov["weights"]["sha256"],
                    "engine_sha256": None,
                    "runtime_image_id": CPU_WORKER_IMAGE_ID,
                }
            return {
                "model_sha256": None,
                "weights_sha256": None,
                "engine_sha256": trt["artifact"]["sha256"],
                "runtime_image_id": GPU_WORKER_IMAGE_ID,
            }

        for resource, prefix in (("openvino_cpu", "cpu"), ("tensorrt_cuda", "cuda")):
            calibration = {
                "schema_version": 2,
                "artifact_kind": "checkpoint_model_policy_calibration",
                "branch": branch,
                "workload_slot_id": slot["slot_id"],
                "resource": resource,
                "source_sha256": source["sha256"],
                **artifact_binding(resource),
                "execution_probe_sha256": evidence[f"{prefix}_execution_probe"]["sha256"],
                "corpus_manifest_sha256": evidence["calibration_corpus"]["sha256"],
                "sample_count": len(calibration_samples),
                "samples": [
                    {"sample_id": sample["sample_id"], "service_time_ms": 1.0 + index / 100.0}
                    for index, sample in enumerate(calibration_samples)
                ],
            }
            evidence[f"{prefix}_policy_calibration"] = _write_evidence(root, branch, f"{prefix}_policy_calibration", calibration)
        cpu_values = [0.1 + index / 10000.0 for index in range(1000)]
        cuda_values = [value + cuda_delta for value in cpu_values]
        for resource, prefix, values in (("openvino_cpu", "cpu", cpu_values), ("tensorrt_cuda", "cuda", cuda_values)):
            bundle = {
                "schema_version": 2,
                "artifact_kind": "checkpoint_model_raw_output_bundle",
                "branch": branch,
                "workload_slot_id": slot["slot_id"],
                "resource": resource,
                "source_sha256": source["sha256"],
                **artifact_binding(resource),
                "execution_probe_sha256": evidence[f"{prefix}_execution_probe"]["sha256"],
                "corpus_manifest_sha256": evidence["evaluation_corpus"]["sha256"],
                "preprocessing_contract_sha256": preprocessing_sha,
                "output_contract_sha256": output_sha,
                "tensor_name": source["output"]["name"],
                "dtype": "float32",
                "sample_shape": [1, 1000],
                "sample_count": len(evaluation_samples),
                "samples": [
                    {
                        "sample_id": sample["sample_id"],
                        "input_sha256": sample["input_sha256"],
                        "preprocessed_tensor_sha256": sample["preprocessed_tensor_sha256"],
                        "values": values,
                    }
                    for sample in evaluation_samples
                ],
            }
            evidence[f"{prefix}_raw_output_bundle"] = _write_evidence(root, branch, f"{prefix}_raw_output_bundle", bundle)
    path = root / "parity-v3.yaml"
    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return path


class SchemaV3RedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.raw = yaml.safe_load(
            (ROOT / "configs" / "checkpoint_analytics_model_parity.yaml").read_text(
                encoding="utf-8"
            )
        )

    def test_source_registry_is_pinned_once_with_actual_onnx_metadata(self) -> None:
        self.assertEqual(self.raw["schema_version"], 3)
        sources = self.raw["source_registry"]
        expected = {
            "resnet18_v1_7": ("e7cb849a949bdceba02356b8b923d53cc01108e1", "4e8f8653e7a2222b3904cc3fe8e304cd8b339ce1d05fd24688162f86fb6df52c", 46820737, 8, "0.0.3", "resnetv15_dense0_fwd"),
            "resnet34_v1_7": ("9019d62c2f74b941ae6ce05de1d4013732703765", "883a41b2e30ddc2e422c108b091b5e70b92d37dc5c345a2c563dcae27971e2cc", 87302588, 8, "0.0.3", "resnetv16_dense0_fwd"),
            "resnet50_v1_12": ("1f95315d8bd3b3ca2ceabe54d274e0cdf5a83bbe", "3f03fdef724b22947eed826f1eef1dc5c34151bb4c37d634f1db89dfa2dd1526", 102576593, 12, "0.0.4", "resnetv17_dense0_fwd"),
            "resnet101_v1_7": ("524206ecbf2cefaa7654d6e6ff29f9a921f2b1d5", "760702f6ec0138f71ebac66f4e95d1c72dc9267a8544f4d4667a53075fd0497c", 178914043, 8, "0.0.3", "resnetv18_dense0_fwd"),
        }
        self.assertEqual(set(sources), set(expected))
        for source_id, facts in expected.items():
            source = sources[source_id]
            self.assertEqual(
                (source["repository_revision"], source["sha256"], source["size_bytes"], source["onnx_opset"], source["onnx_ir_version"], source["output"]["name"]),
                facts,
            )
            self.assertEqual(source["input"]["execution_shape"], [1, 3, 224, 224])
            self.assertEqual(source["output"]["execution_shape"], [1, 1000])
            self.assertEqual(
                source["repository"],
                f"https://huggingface.co/onnxmodelzoo/{source['filename'].removesuffix('.onnx')}",
            )
            self.assertEqual(
                source["resolve_url"],
                f"{source['repository']}/resolve/{source['repository_revision']}/{source['filename']}",
            )

    def test_four_opaque_slots_reference_sources_without_repeating_them(self) -> None:
        expected = {
            "plate_number": ("opaque_rn18", "resnet18_v1_7"),
            "vehicle_type": ("opaque_rn34", "resnet34_v1_7"),
            "damage": ("opaque_rn50", "resnet50_v1_12"),
            "foreign_object": ("opaque_rn101", "resnet101_v1_7"),
        }
        slots = self.raw["workload_slots"]
        self.assertEqual(
            {
                branch: (slot["slot_id"], slot["source_ref"])
                for branch, slot in slots.items()
            },
            expected,
        )
        self.assertTrue(all("source_artifact" not in slot for slot in slots.values()))

    def test_each_slot_requires_raw_bundles_and_resource_calibration(self) -> None:
        expected = {
            "cpu_execution_probe",
            "cuda_execution_probe",
            "calibration_corpus",
            "evaluation_corpus",
            "cpu_policy_calibration",
            "cuda_policy_calibration",
            "cpu_raw_output_bundle",
            "cuda_raw_output_bundle",
        }
        for slot in self.raw["workload_slots"].values():
            self.assertEqual(set(slot["evidence"]), expected)
            self.assertGreater(slot["openvino_ir"]["model"]["size_bytes"], 0)
            self.assertGreater(slot["openvino_ir"]["weights"]["size_bytes"], 0)
            self.assertGreater(slot["tensorrt_engine"]["artifact"]["size_bytes"], 0)
            self.assertFalse(slot["tensorrt_engine"]["rebuild_sha_expected"])

    def test_base_provenance_and_worker_runtime_identities_are_distinct(self) -> None:
        execution = yaml.safe_load(
            (ROOT / "configs" / "analytics_execution_layer.yaml").read_text(
                encoding="utf-8"
            )
        )
        registry = self.raw["worker_runtime_registry"]
        for resource, execution_resource in (("openvino_cpu", "cpu"), ("tensorrt_cuda", "gpu")):
            toolchain = self.raw["toolchain_registry"][resource]
            worker = execution["workers"][execution_resource]
            runtime = registry[resource]
            self.assertEqual(runtime["base_image"], toolchain["image"])
            self.assertEqual(runtime["base_image_id"], toolchain["image_id"])
            self.assertEqual(runtime["image"], worker["image"])
            self.assertEqual(runtime["image_id"], worker["image_id"])
            self.assertEqual(
                runtime["worker_implementation_sha256"],
                worker["worker_implementation_sha256"],
            )
            self.assertNotEqual(runtime["image_id"], runtime["base_image_id"])

    def test_worker_runtime_relabel_and_implementation_drift_fail_closed(self) -> None:
        mutations = (
            ("image_id", self.raw["toolchain_registry"]["openvino_cpu"]["image_id"], "worker runtime"),
            ("worker_implementation_sha256", "0" * 64, "worker runtime"),
        )
        for field, value, message in mutations:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / "parity-v3.yaml"
                raw = copy.deepcopy(self.raw)
                raw["worker_runtime_registry"]["openvino_cpu"][field] = value
                path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
                with self.assertRaisesRegex(ContractError, message):
                    load_parity_manifest(path)

    def test_unmaterialized_manifest_still_has_exact_32_missing_evidence_refs(self) -> None:
        missing = [
            reference
            for slot in self.raw["workload_slots"].values()
            for reference in slot["evidence"].values()
            if reference["sha256"] is None
        ]
        self.assertEqual(len(missing), 32)


class AssessmentV3Tests(unittest.TestCase):
    def _manifest_and_raw(self, root: Path) -> tuple[Path, dict[str, object]]:
        path = complete_v3_manifest(root)
        return path, yaml.safe_load(path.read_text(encoding="utf-8"))

    def _rewrite_evidence(
        self,
        root: Path,
        path: Path,
        raw: dict[str, object],
        branch: str,
        name: str,
        value: object,
    ) -> None:
        reference = raw["workload_slots"][branch]["evidence"][name]
        evidence_path = root / reference["path"]
        write_json(evidence_path, value)
        reference["sha256"] = file_sha(evidence_path)
        path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")

    def test_complete_raw_evidence_is_recomputed_and_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            commands: list[list[str]] = []
            result = assess_model_parity(
                complete_v3_manifest(root),
                project_root=root,
                command_runner=image_runner(commands),
            )
        self.assertTrue(result["publication_ready"])
        self.assertTrue(result["raw_per_sample_outputs_recomputed"])
        self.assertFalse(result["claimed_aggregate_metrics_accepted"])
        self.assertEqual(result["blockers"], [])
        self.assertEqual(len(commands), 2)
        for branch in BRANCHES:
            parity = result["branches"][branch]["recomputed_parity"]
            self.assertTrue(parity["passed"])
            self.assertEqual(parity["sample_count"], MIN_PARITY_SAMPLES)
            self.assertEqual(parity["output_values_compared"], MIN_PARITY_SAMPLES * 1000)
            self.assertEqual(len(parity["per_sample"]), MIN_PARITY_SAMPLES)

    def test_claimed_aggregate_fields_are_rejected_not_trusted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path, raw = self._manifest_and_raw(root)
            branch = "plate_number"
            reference = raw["workload_slots"][branch]["evidence"]["cuda_raw_output_bundle"]
            bundle_path = root / reference["path"]
            bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
            bundle["metrics"] = {name: 0.0 for name in PARITY_TOLERANCES}
            bundle["passed"] = True
            self._rewrite_evidence(root, path, raw, branch, "cuda_raw_output_bundle", bundle)
            result = assess_model_parity(path, project_root=root, command_runner=image_runner([]))
        self.assertFalse(result["publication_ready"])
        self.assertIn(
            "branch:plate_number:cuda_raw_output_bundle_schema_invalid",
            result["branches"]["plate_number"]["blockers"],
        )
        self.assertIsNone(result["branches"]["plate_number"]["recomputed_parity"])

    def test_numeric_tolerance_and_top1_are_computed_from_raw_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path, raw = self._manifest_and_raw(root)
            branch = "vehicle_type"
            reference = raw["workload_slots"][branch]["evidence"]["cuda_raw_output_bundle"]
            bundle_path = root / reference["path"]
            bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
            bundle["samples"][0]["values"][0] = 10.0
            self._rewrite_evidence(root, path, raw, branch, "cuda_raw_output_bundle", bundle)
            result = assess_model_parity(path, project_root=root, command_runner=image_runner([]))
        blockers = result["branches"][branch]["blockers"]
        self.assertIn(f"branch:{branch}:numeric_parity_tolerance_exceeded:raw_max_abs_error", blockers)
        self.assertIn(f"branch:{branch}:numeric_parity_tolerance_exceeded:top1_mismatch_rate", blockers)
        self.assertFalse(result["branches"][branch]["recomputed_parity"]["passed"])

    def test_relative_error_floor_is_tied_to_the_absolute_logit_tolerance(self) -> None:
        self.assertEqual(
            checkpoint_model_parity_module.RELATIVE_ERROR_FLOOR,
            PARITY_TOLERANCES["raw_max_abs_error"],
        )
        cpu = [{"sample_id": "near-zero", "values": [0.000030, 1.0]}]
        cuda = [{"sample_id": "near-zero", "values": [0.000035, 1.000001]}]
        parity, blockers = (
            checkpoint_model_parity_module._recompute_classification_parity_v2(
                "plate_number", cpu, cuda
            )
        )
        self.assertEqual(blockers, [])
        self.assertTrue(parity["passed"])
        self.assertLessEqual(
            parity["aggregates"]["raw_max_rel_error"],
            PARITY_TOLERANCES["raw_max_rel_error"],
        )

    def test_exact_sample_order_and_hashes_are_required(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path, raw = self._manifest_and_raw(root)
            branch = "damage"
            reference = raw["workload_slots"][branch]["evidence"]["cuda_raw_output_bundle"]
            bundle = json.loads((root / reference["path"]).read_text(encoding="utf-8"))
            bundle["samples"][0], bundle["samples"][1] = bundle["samples"][1], bundle["samples"][0]
            self._rewrite_evidence(root, path, raw, branch, "cuda_raw_output_bundle", bundle)
            result = assess_model_parity(path, project_root=root, command_runner=image_runner([]))
        self.assertIn(
            f"branch:{branch}:cuda_raw_output_sample_order_or_hash_mismatch",
            result["branches"][branch]["blockers"],
        )

    def test_non_finite_json_and_duplicate_keys_fail_closed(self) -> None:
        for duplicate in (False, True):
            with self.subTest(duplicate=duplicate), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                path, raw = self._manifest_and_raw(root)
                branch = "foreign_object"
                reference = raw["workload_slots"][branch]["evidence"]["cpu_raw_output_bundle"]
                bundle_path = root / reference["path"]
                if duplicate:
                    payload = bundle_path.read_text(encoding="utf-8").rstrip()
                    bundle_path.write_text(payload[:-1] + ',"dtype":"float32"}\n', encoding="utf-8")
                else:
                    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
                    bundle["samples"][0]["values"][0] = math.nan
                    bundle_path.write_text(json.dumps(bundle, allow_nan=True) + "\n", encoding="utf-8")
                reference["sha256"] = file_sha(bundle_path)
                path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
                result = assess_model_parity(path, project_root=root, command_runner=image_runner([]))
            self.assertIn(
                f"branch:{branch}:cpu_raw_output_bundle_evidence_invalid",
                result["branches"][branch]["blockers"],
            )

    def test_policy_calibration_is_separate_and_requires_30_per_resource(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path, raw = self._manifest_and_raw(root)
            branch = "plate_number"
            reference = raw["workload_slots"][branch]["evidence"]["cuda_policy_calibration"]
            calibration = json.loads((root / reference["path"]).read_text(encoding="utf-8"))
            calibration["samples"] = calibration["samples"][:29]
            calibration["sample_count"] = 29
            self._rewrite_evidence(root, path, raw, branch, "cuda_policy_calibration", calibration)
            result = assess_model_parity(path, project_root=root, command_runner=image_runner([]))
        self.assertIn(
            f"branch:{branch}:cuda_policy_calibration_below_{MIN_CALIBRATION_SAMPLES}",
            result["branches"][branch]["blockers"],
        )

    def test_calibration_and_evaluation_corpora_are_disjoint_v2(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path, raw = self._manifest_and_raw(root)
            branch = "vehicle_type"
            evidence = raw["workload_slots"][branch]["evidence"]
            calibration = json.loads((root / evidence["calibration_corpus"]["path"]).read_text(encoding="utf-8"))
            evaluation = json.loads((root / evidence["evaluation_corpus"]["path"]).read_text(encoding="utf-8"))
            original_id = evaluation["samples"][0]["sample_id"]
            evaluation["samples"][0] = dict(calibration["samples"][0])
            evaluation["samples"][0]["sample_id"] = original_id
            evaluation["samples_sha256"] = canonical_sha(evaluation["samples"])
            self._rewrite_evidence(root, path, raw, branch, "evaluation_corpus", evaluation)
            result = assess_model_parity(path, project_root=root, command_runner=image_runner([]))
        self.assertIn(
            f"branch:{branch}:calibration_and_evaluation_corpora_not_disjoint",
            result["branches"][branch]["blockers"],
        )

    def test_claimed_tensor_hash_is_checked_against_materialized_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path, raw = self._manifest_and_raw(root)
            branch = "damage"
            corpus_ref = raw["workload_slots"][branch]["evidence"]["evaluation_corpus"]
            corpus = json.loads((root / corpus_ref["path"]).read_text(encoding="utf-8"))
            tensor_path = root / corpus["samples"][0]["preprocessed_tensor"]["path"]
            payload = bytearray(tensor_path.read_bytes())
            payload[0] ^= 1
            tensor_path.write_bytes(payload)
            result = assess_model_parity(path, project_root=root, command_runner=image_runner([]))
        blockers = result["branches"][branch]["blockers"]
        self.assertIn(
            f"branch:{branch}:evaluation_corpus_preprocessed_tensor_bundle_sha256_mismatch",
            blockers,
        )
        self.assertIsNone(result["branches"][branch]["recomputed_parity"])

    def test_openvino_gpu_probe_cannot_satisfy_nvidia_cuda(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path, raw = self._manifest_and_raw(root)
            branch = "damage"
            reference = raw["workload_slots"][branch]["evidence"]["cuda_execution_probe"]
            probe = json.loads((root / reference["path"]).read_text(encoding="utf-8"))
            probe["runtime"] = "openvino"
            probe["device_api"] = "OPENVINO_GPU"
            probe["device_id"] = "GPU"
            self._rewrite_evidence(root, path, raw, branch, "cuda_execution_probe", probe)
            result = assess_model_parity(path, project_root=root, command_runner=image_runner([]))
        self.assertIn(
            f"branch:{branch}:cuda_execution_probe_not_nvidia_tensorrt",
            result["branches"][branch]["blockers"],
        )

    def test_symlinked_model_artifact_is_not_accepted_v2(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path, raw = self._manifest_and_raw(root)
            branch = "damage"
            reference = raw["workload_slots"][branch]["openvino_ir"]["model"]
            model_path = root / reference["path"]
            target = model_path.with_name("real-model.xml")
            target.write_bytes(model_path.read_bytes())
            model_path.unlink()
            model_path.symlink_to(target.name)
            result = assess_model_parity(path, project_root=root, command_runner=image_runner([]))
        self.assertIn(
            f"branch:{branch}:openvino_model_artifact_missing",
            result["branches"][branch]["blockers"],
        )

    def test_symlinked_v2_manifest_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = complete_v3_manifest(root)
            link = root / "parity-v3-link.yaml"
            link.symlink_to(target.name)
            with self.assertRaisesRegex(ContractError, "manifest was not found"):
                load_parity_manifest(link)

    def test_duplicate_yaml_keys_and_toolchain_argv_drift_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            duplicate = root / "duplicate.yaml"
            text = (ROOT / "configs" / "checkpoint_analytics_model_parity.yaml").read_text(encoding="utf-8")
            duplicate.write_text("schema_version: 3\n" + text, encoding="utf-8")
            with self.assertRaisesRegex(ContractError, "duplicate key"):
                load_parity_manifest(duplicate)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = complete_v3_manifest(root)
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            derived = raw["workload_slots"]["plate_number"]["tensorrt_engine"]
            derived["canonical_argv"].remove("--noTF32")
            derived["canonical_argv_sha256"] = canonical_sha(derived["canonical_argv"])
            path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
            with self.assertRaisesRegex(ContractError, "canonical_argv drifted"):
                load_parity_manifest(path)

    def test_image_command_is_read_only_inspect(self) -> None:
        command = build_image_inspect_command("vast/deepstream-native-probe:7.0")
        self.assertEqual(command[:3], ["docker", "image", "inspect"])
        self.assertNotIn("pull", command)
        self.assertNotIn("run", command)


if __name__ == "__main__":
    unittest.main()
