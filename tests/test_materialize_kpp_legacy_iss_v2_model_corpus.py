from __future__ import annotations

import copy
import hashlib
import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import materialize_kpp_legacy_iss_v2_model_corpus as corpus  # noqa: E402


DATASET_ROOT = "data/videos/kpp/kpp_legacy_iss_v2"
MEDIA_PATHS = {
    ("h264", "underbody"): f"{DATASET_ROOT}/h264/iss_v2_underbody.mp4",
    ("h264", "front_gate"): f"{DATASET_ROOT}/h264/iss_v2_front_gate.mp4",
    ("h265", "underbody"): f"{DATASET_ROOT}/h265/iss_v2_underbody.mp4",
    ("h265", "front_gate"): f"{DATASET_ROOT}/h265/iss_v2_front_gate.mp4",
}
OTHER_PATHS = {
    ("avi", "underbody"): f"{DATASET_ROOT}/avi/iss_v2_underbody.avi",
    ("avi", "front_gate"): f"{DATASET_ROOT}/avi/iss_v2_front_gate.avi",
    ("receipt", "metadata"): f"{DATASET_ROOT}/metadata/iss_v2_underbody_metadata.json",
    ("receipt", "extraction"): f"{DATASET_ROOT}/receipts/kpp_iss_v2_extraction_receipt.json",
    ("receipt", "transcode"): f"{DATASET_ROOT}/receipts/kpp_iss_v2_transcode_receipt.json",
}


def canonical(value: object) -> bytes:
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("ascii")


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def receipt_self_sha(value: dict[str, object]) -> str:
    unsigned = copy.deepcopy(value)
    unsigned.pop("materialization_receipt_sha256", None)
    return hashlib.sha256(corpus.MATERIALIZATION_RECEIPT_DOMAIN + canonical(unsigned)).hexdigest()


class _RecordingTemporaryFile:
    def __init__(self, stream: object) -> None:
        self.stream = stream
        self.maximum_observed_size = 0

    def _observe(self) -> None:
        if not getattr(self.stream, "closed", True):
            self.maximum_observed_size = max(
                self.maximum_observed_size,
                corpus._capture_storage_size(self.stream),
            )

    def write(self, payload: bytes) -> int:
        written = self.stream.write(payload)
        self.stream.flush()
        self._observe()
        return written

    def close(self) -> None:
        self._observe()
        self.stream.close()

    def __enter__(self) -> "_RecordingTemporaryFile":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def __getattr__(self, name: str) -> object:
        return getattr(self.stream, name)


def preprocessing_contract() -> dict[str, object]:
    return {
        "contract_id": "imagenet_resnet_fp32_center_crop_v2",
        "decoded_color_order": "RGB",
        "tensor_color_order": "RGB",
        "decode_dtype": "uint8",
        "resize_shorter_side": 256,
        "resize_long_side_formula": "floor(long_side*256/short_side+0.5)",
        "resize_algorithm": "bilinear",
        "resize_coordinate_transform": "half_pixel",
        "half_pixel_coordinate_formula": "src=(dst+0.5)*src_size/dst_size-0.5",
        "border_mode": "edge_clamp",
        "interpolation_accumulator_dtype": "float32",
        "interpolation_output_dtype": "float32",
        "interpolation_rounding": "none",
        "resize_rounding": "round_half_up",
        "center_crop": [224, 224],
        "normalization_scale": 0.00392156862745098,
        "normalization_mean": [0.485, 0.456, 0.406],
        "normalization_std": [0.229, 0.224, 0.225],
        "normalization_evaluation_order": (
            "float32((float32(pixel)*scale-mean[channel])/std[channel])"
        ),
        "normalization_accumulator_dtype": "float32",
        "channel_transform": "HWC_RGB_to_CHW_RGB",
        "output_dtype": "float32",
        "output_layout": "NCHW",
        "execution_shape": [1, 3, 224, 224],
        "tensor_serialization": "raw_f32_le_c_contiguous_v1",
        "tensor_header": "none",
        "tensor_endianness": "little",
        "tensor_memory_order": "C",
    }


class Fixture:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        (self.root / "staging").mkdir()
        self.payloads: dict[str, bytes] = {}
        for (codec, role), relative in {**MEDIA_PATHS, **OTHER_PATHS}.items():
            payload = f"fixture:{codec}:{role}\n".encode("ascii")
            self.payloads[relative] = payload
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
        self.receipt = self._receipt()
        self.receipt_path = self.root / DATASET_ROOT / "kpp_iss_v2_materialization_receipt.json"
        self.receipt_payload = canonical(self.receipt)
        self.receipt_path.write_bytes(self.receipt_payload)
        self.parity_manifest_path = self.root / "candidate_inputs" / "parity.yaml"
        self.parity_manifest_path.parent.mkdir()
        self.parity_manifest_path.write_text(
            yaml.safe_dump(self._parity_manifest(), sort_keys=True), encoding="utf-8"
        )
        self.ffmpeg = self.root / "candidate_inputs" / "ffmpeg.exe"
        self.ffprobe = self.root / "candidate_inputs" / "ffprobe.exe"
        self.ffmpeg.write_bytes(b"fixture ffmpeg")
        self.ffprobe.write_bytes(b"fixture ffprobe")
        self.version_bytes = {
            self.ffmpeg: b"ffmpeg fixture version\n",
            self.ffprobe: b"ffprobe fixture version\n",
        }
        self.decode_calls = 0

    def _entry(self, codec: str) -> dict[str, object]:
        return {
            "dataset_contract_version": 2,
            "generation_id": "kpp_legacy_iss_v2",
            "status": "physically_assessed_candidate",
            "kind": "real_codec_transcode",
            "publishable": False,
            "codec_variant": codec,
            "streams": [
                {
                    "stream_id": index,
                    "path": MEDIA_PATHS[(codec, role)],
                    "sha256": sha256(self.payloads[MEDIA_PATHS[(codec, role)]]),
                }
                for index, role in enumerate(("underbody", "front_gate"))
            ],
        }

    def _receipt(self) -> dict[str, object]:
        installed: list[dict[str, object]] = []
        for (variant, role), path in MEDIA_PATHS.items():
            payload = self.payloads[path]
            installed.append(
                {
                    "artifact_kind": "media",
                    "codec_variant": variant,
                    "role": role,
                    "source_path": f"staging/{variant}/{role}",
                    "installed_path": path,
                    "size_bytes": len(payload),
                    "sha256": sha256(payload),
                }
            )
        for (kind, role), path in OTHER_PATHS.items():
            payload = self.payloads[path]
            if kind == "avi":
                installed.append(
                    {
                        "artifact_kind": "media",
                        "codec_variant": "avi",
                        "role": role,
                        "source_path": f"staging/avi/{role}",
                        "installed_path": path,
                        "size_bytes": len(payload),
                        "sha256": sha256(payload),
                    }
                )
            else:
                installed.append(
                    {
                        "artifact_kind": "receipt",
                        "receipt_role": role,
                        "source_path": f"staging/{role}.json",
                        "installed_path": path,
                        "size_bytes": len(payload),
                        "sha256": sha256(payload),
                    }
                )
        value: dict[str, object] = {
            "schema_version": 1,
            "artifact_kind": "vast_kpp_legacy_iss_v2_materialization_receipt",
            "generation_id": "kpp_legacy_iss_v2",
            "status": "physically_assessed_candidate",
            "dataset_root": DATASET_ROOT,
            "publishable": False,
            "publication_authorized": False,
            "source_receipt_external_pins": {
                role: next(
                    item["sha256"]
                    for item in installed
                    if item.get("receipt_role") == role
                )
                for role in ("extraction", "transcode", "metadata")
            },
            "installed_artifacts": installed,
            "dataset_entries": {
                "kpp_legacy_iss_v2_h264": self._entry("h264"),
                "kpp_legacy_iss_v2_h265": self._entry("h265"),
            },
            "claims": {
                "source_receipts_externally_pinned": True,
                "authoritative_receipt_graph_validated": True,
                "media_sources_derived_from_validated_receipts": True,
                "source_and_installed_bytes_stably_rehashed": True,
                "physical_artifact_bytes_assessed": True,
                "exact_output_tree_validated": True,
                "output_set_directory_published_atomically": True,
                (
                    "windows_project_root_data_videos_kpp_and_working_directory_"
                    "handle_custody_validated"
                ): True,
                "publishable": False,
                "publication_authorized": False,
            },
        }
        value["materialization_receipt_sha256"] = receipt_self_sha(value)
        return value

    @staticmethod
    def _parity_manifest() -> dict[str, object]:
        value = yaml.safe_load(
            (ROOT / "configs" / "checkpoint_analytics_model_parity.yaml").read_text(
                encoding="utf-8"
            )
        )
        assert type(value) is dict
        return value

    def replace_parity_manifest(self, value: dict[str, object]) -> None:
        self.parity_manifest_path.write_text(
            yaml.safe_dump(value, sort_keys=True), encoding="utf-8"
        )

    def probe(self, media: corpus.HeldMedia, _tool: Path) -> corpus.MediaProbe:
        role = media.role
        return corpus.MediaProbe(
            codec=media.codec,
            width=8 if role == "front_gate" else 6,
            height=4,
            stream_index=0,
            time_base="1/600",
            frame_count=120,
            frame_pts=tuple(range(120)),
        )

    def decode(
        self,
        media: corpus.HeldMedia,
        indexes: tuple[int, ...],
        probe: corpus.MediaProbe,
        _tool: Path,
    ) -> dict[int, corpus.DecodedFrame]:
        self.decode_calls += 1
        frames: dict[int, corpus.DecodedFrame] = {}
        for index in indexes:
            rgb = bytes(
                ((index + channel + (0 if media.role == "front_gate" else 17)) % 256)
                for channel in range(probe.width * probe.height * 3)
            )
            frames[index] = corpus.DecodedFrame(
                frame_index=index,
                source_pts=index,
                source_time_base=probe.time_base,
                pts_ns=round(index * 1_000_000_000 / 600),
                width=probe.width,
                height=probe.height,
                stride=probe.width * 3,
                rgb=rgb,
            )
        return frames

    @staticmethod
    def preprocess(
        frame: corpus.DecodedFrame,
        _contract: dict[str, object],
        contract_sha256: str,
        _tensor_name: str,
    ) -> tuple[bytes, dict[str, object]]:
        digest = hashlib.sha256(frame.rgb + contract_sha256.encode("ascii")).digest()
        payload = digest * (1 * 3 * 224 * 224 * 4 // len(digest))
        return payload, {
            "dtype": "float32",
            "layout": "NCHW",
            "shape": [1, 3, 224, 224],
            "byte_length": len(payload),
            "sha256": sha256(payload),
            "preprocessing_contract_sha256": contract_sha256,
        }

    def adapters(self) -> corpus._TestAdapters:
        return corpus._TestAdapters(
            probe=self.probe,
            decode=self.decode,
            preprocess=self.preprocess,
            version_reader=lambda path: self.version_bytes[path],
        )

    def run(
        self,
        *,
        output_name: str = "model-corpus-candidate",
        expected_source_set_sha256: str | None = None,
        test_adapters: corpus._TestAdapters | None = None,
    ) -> dict[str, object]:
        return corpus._materialize_model_corpus_impl(
            project_root=self.root,
            materialization_receipt=self.receipt_path,
            expected_materialization_receipt_size_bytes=len(self.receipt_payload),
            expected_materialization_receipt_sha256=sha256(self.receipt_payload),
            expected_materialization_receipt_self_sha256=str(
                self.receipt["materialization_receipt_sha256"]
            ),
            model_parity_manifest=self.parity_manifest_path,
            expected_model_parity_manifest_sha256=sha256(
                self.parity_manifest_path.read_bytes()
            ),
            ffmpeg=self.ffmpeg,
            expected_ffmpeg_sha256=sha256(self.ffmpeg.read_bytes()),
            expected_ffmpeg_version_sha256=sha256(self.version_bytes[self.ffmpeg]),
            ffprobe=self.ffprobe,
            expected_ffprobe_sha256=sha256(self.ffprobe.read_bytes()),
            expected_ffprobe_version_sha256=sha256(self.version_bytes[self.ffprobe]),
            expected_source_set_sha256=(
                expected_source_set_sha256
                if expected_source_set_sha256 is not None
                else corpus._source_set_external_pin_for_tests()
            ),
            output_dir=self.root / "staging" / output_name,
            test_adapters=test_adapters or self.adapters(),
        )


class NeutralSamplingPlanTests(unittest.TestCase):
    def test_midpoint_plan_is_balanced_disjoint_and_content_independent(self) -> None:
        plan = corpus.build_neutral_sample_plan(
            {"front_gate": 33120, "underbody": 35646}
        )
        self.assertEqual(len(plan), 240)
        for branch in corpus.BRANCHES:
            rows = [row for row in plan if row.branch == branch]
            calibration = [row for row in rows if row.corpus_role == "calibration"]
            evaluation = [row for row in rows if row.corpus_role == "evaluation"]
            self.assertEqual(len(calibration), 30)
            self.assertEqual(len(evaluation), 30)
            self.assertEqual({row.codec for row in calibration}, {"h264", "h265"})
            self.assertEqual(
                {row.frame_index for row in calibration}
                & {row.frame_index for row in evaluation},
                set(),
            )
            self.assertEqual(
                sum(row.codec == "h264" for row in calibration), 15
            )
            self.assertEqual(sum(row.codec == "h264" for row in evaluation), 15)
        plate = [row for row in plan if row.branch == "plate_number"]
        vehicle = [row for row in plan if row.branch == "vehicle_type"]
        self.assertEqual(
            [(row.corpus_role, row.codec, row.frame_index) for row in plate],
            [(row.corpus_role, row.codec, row.frame_index) for row in vehicle],
        )
        first = plate[0]
        self.assertEqual(first.frame_index, (1 * 33120) // 120)
        self.assertEqual(first.corpus_role, "calibration")
        self.assertEqual(first.codec, "h264")
        self.assertEqual(corpus.SAMPLING_RULE["selection_inputs"], ["frame_count"])


class ModelCorpusMaterializerTests(unittest.TestCase):
    def _install_synthetic_receipt_authority(
        self,
        payload: bytes = b"synthetic frozen materialization receipt\n",
        *,
        self_sha256: str = "b" * 64,
    ) -> bytes:
        patches = (
            mock.patch.object(
                corpus,
                "EXPECTED_MATERIALIZATION_RECEIPT_SIZE_BYTES",
                len(payload),
            ),
            mock.patch.object(
                corpus,
                "EXPECTED_MATERIALIZATION_RECEIPT_FILE_SHA256",
                sha256(payload),
            ),
            mock.patch.object(
                corpus,
                "EXPECTED_MATERIALIZATION_RECEIPT_SELF_SHA256",
                self_sha256,
            ),
        )
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        return payload

    @staticmethod
    def _commit_record_payload(
        output_name: str,
        candidate_receipt_core_sha256: str = "5" * 64,
    ) -> bytes:
        return corpus._authoritative_commit_record_payload(
            canonical_output_root=f"staging/{output_name}",
            canonical_output_name=output_name,
            outputs_sha256=sha256(canonical([])),
            sampling_rule_sha256=sha256(canonical(corpus.SAMPLING_RULE)),
            source_set_canonical_aggregate_sha256="1" * 64,
            source_materialization_receipt={
                "path": corpus.MATERIALIZATION_RECEIPT_PATH,
                "size_bytes": (
                    corpus.EXPECTED_MATERIALIZATION_RECEIPT_SIZE_BYTES
                ),
                "sha256": (
                    corpus.EXPECTED_MATERIALIZATION_RECEIPT_FILE_SHA256
                ),
                "materialization_receipt_sha256": (
                    corpus.EXPECTED_MATERIALIZATION_RECEIPT_SELF_SHA256
                ),
            },
            source_model_parity_manifest_sha256="4" * 64,
            candidate_receipt_core_sha256=(
                candidate_receipt_core_sha256
            ),
        )

    def _write_commit_bound_receipt(
        self,
        *,
        project_root: Path,
        candidate: Path,
        output_name: str,
        source_receipt_payload: bytes,
    ) -> tuple[dict[str, object], bytes]:
        output_root = f"staging/{output_name}"
        outputs: list[dict[str, object]] = []

        def add_output(name: str, payload: bytes, role: str) -> dict[str, object]:
            (candidate / name).write_bytes(payload)
            descriptor = {
                "role": role,
                "path": f"{output_root}/{name}",
                "size_bytes": len(payload),
                "sha256": sha256(payload),
            }
            outputs.append(descriptor)
            return descriptor

        dataset_payload = b"synthetic frozen dataset config\n"
        add_output(
            "source_materialization_receipt.json",
            source_receipt_payload,
            "source materialization receipt snapshot",
        )
        parity_payload = b"synthetic model parity manifest\n"
        add_output(
            "source_model_parity_manifest.yaml",
            parity_payload,
            "source model parity manifest snapshot",
        )
        add_output(
            "dataset_manifest.json",
            b"synthetic dataset manifest\n",
            "candidate dataset manifest",
        )
        for branch in corpus.BRANCHES:
            for corpus_role in ("calibration", "evaluation"):
                add_output(
                    f"corpus_{branch}_{corpus_role}.json",
                    f"{branch}/{corpus_role}\n".encode("ascii"),
                    f"{branch}/{corpus_role} corpus candidate",
                )
        for codec in corpus.CODECS:
            for source_role in corpus.SOURCE_ROLES:
                add_output(
                    f"raw_{codec}_{source_role}.rgb24.bin",
                    f"raw:{codec}:{source_role}\n".encode("ascii"),
                    f"{codec}/{source_role} decoded RGB bundle",
                )
                add_output(
                    f"tensor_{codec}_{source_role}.f32.bin",
                    f"tensor:{codec}:{source_role}\n".encode("ascii"),
                    f"{codec}/{source_role} preprocessed tensor bundle",
                )
        dataset_snapshot = add_output(
            "source_dataset_config.yaml",
            dataset_payload,
            "source frozen dataset config snapshot",
        )
        components: list[dict[str, object]] = []
        for name, canonical_path, runtime_path in (
            corpus._local_source_component_paths()
        ):
            payload = runtime_path.read_bytes()
            snapshot = add_output(
                f"source_code_{name}.py",
                payload,
                f"externally pinned {name} source snapshot",
            )
            components.append(
                {
                    "component": name,
                    "canonical_path": canonical_path,
                    "runtime_path": str(runtime_path),
                    "size_bytes": len(payload),
                    "sha256": sha256(payload),
                    "source_snapshot": snapshot,
                }
            )
        projection = corpus._source_set_projection(components)
        source_set_sha256 = sha256(canonical(projection))
        local_source_set = {
            "schema_version": 1,
            "artifact_kind": "vast_local_python_source_set_pin",
            "canonical_projection": projection,
            "canonical_aggregate_sha256": source_set_sha256,
            "source_bytes_externally_pinned_and_held": True,
            "executed_python_bytecode_attested": False,
            "launcher_execution_attested": False,
            "components": components,
        }
        materializer = next(
            item for item in components if item["component"] == "materializer"
        )
        shared_source_pin = {
            "path": materializer["runtime_path"],
            "size_bytes": materializer["size_bytes"],
            "sha256": materializer["sha256"],
            "source_set_canonical_aggregate_sha256": source_set_sha256,
            "source_bytes_externally_pinned_and_held": True,
            "executed_python_bytecode_attested": False,
            "launcher_execution_attested": False,
            "source_snapshot": materializer["source_snapshot"],
        }
        ffprobe_argv = [
            "FFPROBE", "-v", "error", "-select_streams", "v:0",
            "-count_frames", "-show_entries",
            "stream=index,codec_name,width,height,time_base,nb_read_frames:frame=stream_index,best_effort_timestamp",
            "-show_frames", "-of", "json", "SOURCE",
        ]
        ffmpeg_argv = [
            "FFMPEG", "-hide_banner", "-loglevel", "info", "-nostdin",
            "-i", "SOURCE", "-map", "0:v:0", "-an", "-sn", "-dn",
            "-vf",
            "select=EXACT_FRAME_INDEX_SET,showinfo,settb=expr=1/1000000000,showinfo",
            "-fps_mode", "passthrough", "-pix_fmt", "rgb24", "-f",
            "rawvideo", "pipe:1",
        ]
        subprocess_context = corpus._build_subprocess_context(
            root=project_root,
            cwd=candidate,
            published_cwd=project_root / "staging" / output_name,
        )
        outputs.sort(key=lambda item: str(item["path"]))
        receipt_core: dict[str, object] = {
            "schema_version": 1,
            "artifact_kind": corpus.RECEIPT_ARTIFACT_KIND,
            "generation_id": corpus.GENERATION_ID,
            "status": "materialized_nonpromotable_candidate",
            "promotable": False,
            "publication_authorized": False,
            "evidence_accepted": False,
            "pi_approval_status": "required",
            "output_root": output_root,
            "source_materialization_receipt": {
                "path": corpus.MATERIALIZATION_RECEIPT_PATH,
                "size_bytes": (
                    corpus.EXPECTED_MATERIALIZATION_RECEIPT_SIZE_BYTES
                ),
                "sha256": (
                    corpus.EXPECTED_MATERIALIZATION_RECEIPT_FILE_SHA256
                ),
                "materialization_receipt_sha256": (
                    corpus.EXPECTED_MATERIALIZATION_RECEIPT_SELF_SHA256
                ),
            },
            "source_model_parity_manifest_sha256": sha256(parity_payload),
            "source_dataset_config": {
                "source": {
                    "path": "configs/datasets.yaml",
                    "size_bytes": len(dataset_payload),
                    "sha256": sha256(dataset_payload),
                },
                "snapshot": dataset_snapshot,
                "canonical_frozen_validator_applied": True,
            },
            "dataset_aggregate_sha256": "6" * 64,
            "branch_source_mapping": {
                branch: {
                    "branch": branch,
                    "workload_slot_id": {
                        "plate_number": "opaque_rn18",
                        "vehicle_type": "opaque_rn34",
                        "damage": "opaque_rn50",
                        "foreign_object": "opaque_rn101",
                    }[branch],
                    "source_ref": {
                        "plate_number": "resnet18_v1_7",
                        "vehicle_type": "resnet34_v1_7",
                        "damage": "resnet50_v1_12",
                        "foreign_object": "resnet101_v1_7",
                    }[branch],
                    "source_role": corpus.BRANCH_SOURCE_ROLE[branch],
                    "semantic_claim": "topology_load_proxy_only",
                    "tensor_name": "data",
                }
                for branch in corpus.BRANCHES
            },
            "sampling_rule": copy.deepcopy(corpus.SAMPLING_RULE),
            "sampling_rule_sha256": sha256(canonical(corpus.SAMPLING_RULE)),
            "tool_pins": {
                "ffmpeg": {
                    "role": "ffmpeg",
                    "path": str(project_root / "ffmpeg.exe"),
                    "size_bytes": 1,
                    "sha256": "7" * 64,
                    "version_output_sha256": "8" * 64,
                    "canonical_argv_template_sha256": sha256(
                        canonical(ffmpeg_argv)
                    ),
                },
                "ffprobe": {
                    "role": "ffprobe",
                    "path": str(project_root / "ffprobe.exe"),
                    "size_bytes": 1,
                    "sha256": "9" * 64,
                    "version_output_sha256": "a" * 64,
                    "canonical_argv_template_sha256": sha256(
                        canonical(ffprobe_argv)
                    ),
                },
                "materializer": {
                    **shared_source_pin,
                    "role": "model corpus materializer source",
                },
                "preprocessor": {
                    **shared_source_pin,
                    "role": "candidate preprocessing implementation source",
                    "implementation_symbol": "_default_preprocess",
                },
                "local_source_set": local_source_set,
                "subprocess_context": copy.deepcopy(
                    subprocess_context.descriptor
                ),
            },
            "outputs": outputs,
            "claims": copy.deepcopy(corpus.CLAIMS),
        }
        record_payload = corpus._authoritative_commit_record_payload(
            canonical_output_root=output_root,
            canonical_output_name=output_name,
            outputs_sha256=sha256(canonical(outputs)),
            sampling_rule_sha256=receipt_core["sampling_rule_sha256"],
            source_set_canonical_aggregate_sha256=source_set_sha256,
            source_materialization_receipt=receipt_core[
                "source_materialization_receipt"
            ],
            source_model_parity_manifest_sha256=receipt_core[
                "source_model_parity_manifest_sha256"
            ],
            candidate_receipt_core_sha256=(
                corpus._candidate_receipt_core_sha(receipt_core)
            ),
        )
        receipt = copy.deepcopy(receipt_core)
        receipt["authoritative_commit_record"] = {
            "path": (
                f"{output_root}/{corpus.AUTHORITATIVE_COMMIT_RECORD_NAME}"
            ),
            "size_bytes": len(record_payload),
            "sha256": sha256(record_payload),
        }
        receipt["candidate_receipt_sha256"] = corpus._candidate_self_sha(
            receipt
        )
        (candidate / corpus.RECEIPT_NAME).write_bytes(canonical(receipt))
        return receipt, record_payload

    @staticmethod
    def _reseal_commit_bound_receipt(
        *,
        candidate: Path,
        receipt: dict[str, object],
    ) -> bytes:
        output_root = receipt["output_root"]
        assert type(output_root) is str
        output_name = Path(output_root).name
        tool_pins = receipt["tool_pins"]
        assert type(tool_pins) is dict
        local_source_set = tool_pins["local_source_set"]
        assert type(local_source_set) is dict
        record_payload = corpus._authoritative_commit_record_payload(
            canonical_output_root=output_root,
            canonical_output_name=output_name,
            outputs_sha256=sha256(canonical(receipt["outputs"])),
            sampling_rule_sha256=receipt["sampling_rule_sha256"],
            source_set_canonical_aggregate_sha256=local_source_set[
                "canonical_aggregate_sha256"
            ],
            source_materialization_receipt=receipt[
                "source_materialization_receipt"
            ],
            source_model_parity_manifest_sha256=receipt[
                "source_model_parity_manifest_sha256"
            ],
            candidate_receipt_core_sha256=(
                corpus._candidate_receipt_core_sha(receipt)
            ),
        )
        receipt["authoritative_commit_record"] = {
            "path": (
                f"{output_root}/{corpus.AUTHORITATIVE_COMMIT_RECORD_NAME}"
            ),
            "size_bytes": len(record_payload),
            "sha256": sha256(record_payload),
        }
        receipt["candidate_receipt_sha256"] = corpus._candidate_self_sha(
            receipt
        )
        (candidate / corpus.AUTHORITATIVE_COMMIT_RECORD_NAME).write_bytes(
            record_payload
        )
        (candidate / corpus.RECEIPT_NAME).write_bytes(canonical(receipt))
        return record_payload

    @classmethod
    def _new_commit_pending(
        cls,
        *,
        working: Path,
        output: Path,
        output_name: str,
    ) -> corpus._AuthoritativeCommitPending:
        return corpus._AuthoritativeCommitPending(
            working_path=working / corpus.AUTHORITATIVE_COMMIT_PENDING_NAME,
            published_path=output / corpus.AUTHORITATIVE_COMMIT_PENDING_NAME,
            commit_record_path=(
                output / corpus.AUTHORITATIVE_COMMIT_RECORD_NAME
            ),
            payload=cls._commit_record_payload(output_name),
        )

    def _create_windows_authoritative_candidate(
        self, root: Path
    ) -> tuple[
        Path,
        corpus._WindowsDirectoryCustody,
        Path,
        corpus._WindowsDirectoryCustody,
    ]:
        parent = root / "staging"
        parent.mkdir()
        parent_hold = corpus._open_windows_directory_custody(
            parent,
            label="test authoritative staging parent",
            require_delete_access=False,
        )
        try:
            working, candidate_hold = (
                corpus._create_windows_private_working_directory_with_custody(
                    parent=parent_hold,
                    prefix=".kpp-v2-model-corpus.",
                    suffix=".candidate",
                    label="test authoritative candidate",
                )
            )
        except BaseException:
            parent_hold.close()
            raise
        return parent, parent_hold, working, candidate_hold

    def _recorded_gateway_call(
        self,
        *,
        command: list[str],
        policy: dict[str, object],
        projection_updates: dict[str, object] | None = None,
        settle_seconds: float = 0.0,
    ) -> tuple[
        subprocess.CompletedProcess[bytes] | None,
        BaseException | None,
        list[_RecordingTemporaryFile],
        dict[str, object],
    ]:
        captures: list[_RecordingTemporaryFile] = []
        original_capture_factory = (
            corpus._open_private_hard_bounded_capture
        )

        def recording_capture_storage(
            *args: object, **kwargs: object
        ) -> _RecordingTemporaryFile:
            capture = _RecordingTemporaryFile(
                original_capture_factory(*args, **kwargs)
            )
            captures.append(capture)
            return capture

        completed: subprocess.CompletedProcess[bytes] | None = None
        failure: BaseException | None = None
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            cwd = root / "private-candidate-root"
            cwd.mkdir(mode=0o700)
            with mock.patch.object(
                corpus,
                "_SUBPROCESS_RESOURCE_POLICIES",
                {"capture_test": policy},
            ):
                context = corpus._build_subprocess_context(
                    root=root,
                    cwd=cwd,
                    published_cwd=root / "published-candidate-root",
                )
                projection = context.descriptor["canonical_projection"]
                assert type(projection) is dict
                if projection_updates:
                    projection.update(projection_updates)
                    context.descriptor["canonical_sha256"] = sha256(
                        canonical(projection)
                    )
                with mock.patch.object(
                    corpus,
                    "_open_private_hard_bounded_capture",
                    side_effect=recording_capture_storage,
                ):
                    try:
                        completed = corpus._run_sanitized_subprocess(
                            command,
                            context=context,
                            policy_id="capture_test",
                        )
                    except BaseException as exc:
                        failure = exc
            if settle_seconds:
                time.sleep(settle_seconds)
            self.assertEqual(
                [
                    thread.name
                    for thread in corpus.threading.enumerate()
                    if thread.name.startswith("kpp-capture-capture_test-")
                ],
                [],
                "the bounded gateway must not return with a live pipe reader",
            )
        for capture in captures:
            self.assertTrue(capture.stream.closed)
        return completed, failure, captures, projection

    def test_authoritative_source_set_rejects_noncanonical_loaded_paths(self) -> None:
        with tempfile.TemporaryDirectory() as raw, ExitStack() as custody:
            with self.assertRaisesRegex(
                corpus.ModelCorpusError, "not at its canonical path"
            ):
                corpus._held_local_source_set(
                    root=Path(raw).resolve(),
                    require_canonical_runtime_paths=True,
                    expected_aggregate_sha256=(
                        corpus._source_set_external_pin_for_tests()
                    ),
                    custody=custody,
                    held_files=[],
                )

    def test_windows_directory_identity_custody_requires_old_write_handle_close(
        self,
    ) -> None:
        if os.name != "nt":
            self.skipTest("Windows directory custody only")
        with tempfile.TemporaryDirectory() as raw:
            parent = Path(raw).resolve() / "staging"
            parent.mkdir()
            parent_hold = corpus._open_windows_directory_custody(
                parent,
                label="test staging parent",
                require_delete_access=False,
            )
            old_hold = None
            final_hold = None
            working = None
            try:
                working, old_hold = (
                    corpus._create_windows_private_working_directory_with_custody(
                        parent=parent_hold,
                        prefix=".namespace-lifecycle.",
                        suffix=".candidate",
                        label="test candidate",
                    )
                )
                original_identity = old_hold.identity
                with self.assertRaisesRegex(
                    corpus.ModelCorpusError, "could not acquire.*Win32"
                ):
                    corpus._open_windows_final_directory_identity_custody(
                        working, label="conflicting final directory identity"
                    )
                old_hold.close()
                old_hold = None
                final_hold = (
                    corpus._open_windows_final_directory_identity_custody(
                        working, label="final directory identity"
                    )
                )
                self.assertEqual(final_hold.identity, original_identity)
            finally:
                if final_hold is not None:
                    final_hold.close()
                if old_hold is not None:
                    old_hold.close()
                parent_hold.close()
                if working is not None and working.exists():
                    working.rmdir()

    @unittest.skipUnless(os.name == "nt", "Windows authoritative quarantine only")
    def test_authoritative_prepublish_failure_is_quarantined_with_marker(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            parent, parent_hold, working, candidate_hold = (
                self._create_windows_authoritative_candidate(root)
            )
            primary = corpus.ModelCorpusError("synthetic prepublication failure")
            output_custody = ExitStack()
            try:
                (working / "partial.bin").write_bytes(b"partial candidate")
                quarantine = corpus._quarantine_authoritative_failure(
                    parent_custody=parent_hold,
                    candidate_custody=candidate_hold,
                    private_candidate_name=working.name,
                    canonical_output_name="model-corpus-output",
                    output_file_custody=output_custody,
                    primary=primary,
                )
                self.assertIsNotNone(quarantine)
                assert quarantine is not None
                self.assertFalse(working.exists())
                self.assertEqual(
                    (quarantine / "partial.bin").read_bytes(),
                    b"partial candidate",
                )
                marker = json.loads(
                    (quarantine / corpus.AUTHORITATIVE_FAILURE_MARKER_NAME)
                    .read_text("ascii")
                )
                self.assertEqual(
                    set(marker),
                    {
                        "schema_version",
                        "artifact_kind",
                        "generation_id",
                        "status",
                        "source_namespace_state",
                        "source_namespace_name",
                        "canonical_output_name",
                        "quarantine_namespace_name",
                        "candidate_directory_identity",
                        "primary_exception",
                        "promotable",
                        "publication_authorized",
                        "evidence_accepted",
                        "candidate_success_attested",
                        "manual_forensic_review_required",
                        "forensic_remnant_only",
                        "tree_integrity_attested",
                        "directory_namespace_immutability_attested",
                        "future_candidate_tree_immutability_attested",
                    },
                )
                self.assertEqual(
                    marker["artifact_kind"],
                    corpus.AUTHORITATIVE_FAILURE_MARKER_ARTIFACT_KIND,
                )
                self.assertEqual(
                    marker["source_namespace_state"],
                    "prepublication_private_candidate",
                )
                self.assertEqual(
                    marker["canonical_output_name"], "model-corpus-output"
                )
                self.assertEqual(
                    marker["primary_exception"],
                    {
                        "type": "ModelCorpusError",
                        "message": "synthetic prepublication failure",
                    },
                )
                for key in (
                    "promotable",
                    "publication_authorized",
                    "evidence_accepted",
                    "candidate_success_attested",
                ):
                    self.assertIs(marker[key], False)
                self.assertIs(marker["manual_forensic_review_required"], True)
                self.assertIs(marker["forensic_remnant_only"], True)
                self.assertIs(marker["tree_integrity_attested"], False)
            finally:
                candidate_hold.close()
                parent_hold.close()

    @unittest.skipUnless(os.name == "nt", "Windows authoritative quarantine only")
    def test_failure_immediately_after_canonical_rename_moves_exact_file_id_to_quarantine(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            parent, parent_hold, working, candidate_hold = (
                self._create_windows_authoritative_candidate(root)
            )
            output_name = "model-corpus-output"
            output = parent / output_name
            original_identity = candidate_hold.identity
            try:
                (working / "before-rename.bin").write_bytes(b"retained")
                corpus._windows_publish_directory_by_handle(
                    source=candidate_hold,
                    parent=parent_hold,
                    target_name=output_name,
                )
                quarantine = corpus._quarantine_authoritative_failure(
                    parent_custody=parent_hold,
                    candidate_custody=candidate_hold,
                    private_candidate_name=working.name,
                    canonical_output_name=output_name,
                    output_file_custody=ExitStack(),
                    primary=corpus.ModelCorpusError(
                        "synthetic exception after rename"
                    ),
                )
                self.assertIsNotNone(quarantine)
                assert quarantine is not None
                self.assertFalse(output.exists())
                self.assertEqual(candidate_hold.identity, original_identity)
                marker = json.loads(
                    (quarantine / corpus.AUTHORITATIVE_FAILURE_MARKER_NAME)
                    .read_text("ascii")
                )
                self.assertEqual(
                    marker["source_namespace_state"],
                    "canonical_output_after_atomic_move",
                )
                self.assertEqual(
                    marker["candidate_directory_identity"],
                    {
                        "volume_serial_number": original_identity[0],
                        "file_index": original_identity[1],
                    },
                )
            finally:
                candidate_hold.close()
                parent_hold.close()

    @unittest.skipUnless(os.name == "nt", "Windows authoritative quarantine only")
    def test_postpublish_verification_failure_releases_leaf_then_quarantines(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            parent, parent_hold, working, candidate_hold = (
                self._create_windows_authoritative_candidate(root)
            )
            output_name = "model-corpus-output"
            output = parent / output_name
            output_custody = ExitStack()
            held = output_custody.enter_context(
                corpus._HeldOutputFile(
                    working_path=working / "held-leaf.bin",
                    published_path=output / "held-leaf.bin",
                    label="synthetic held leaf",
                    payload=b"held payload",
                )
            )
            try:
                held.prepare_for_parent_publish()
                held.release_for_parent_publish()
                corpus._windows_publish_directory_by_handle(
                    source=candidate_hold,
                    parent=parent_hold,
                    target_name=output_name,
                )
                held.acquire_final_custody()
                quarantine = corpus._quarantine_authoritative_failure(
                    parent_custody=parent_hold,
                    candidate_custody=candidate_hold,
                    private_candidate_name=working.name,
                    canonical_output_name=output_name,
                    output_file_custody=output_custody,
                    primary=corpus.ModelCorpusError(
                        "synthetic postpublication verification failure"
                    ),
                )
                self.assertIsNotNone(quarantine)
                assert quarantine is not None
                self.assertFalse(output.exists())
                self.assertEqual(
                    (quarantine / "held-leaf.bin").read_bytes(), b"held payload"
                )
            finally:
                output_custody.close()
                candidate_hold.close()
                parent_hold.close()

    @unittest.skipUnless(os.name == "nt", "Windows authoritative quarantine only")
    def test_authoritative_quarantine_collision_never_overwrites(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            parent, parent_hold, working, candidate_hold = (
                self._create_windows_authoritative_candidate(root)
            )
            first_token = "0" * 32
            second_token = "1" * 32
            try:
                collision = parent / corpus._authoritative_failed_name(first_token)
                collision.mkdir()
                (collision / "sentinel.bin").write_bytes(b"must not overwrite")
                with mock.patch.object(
                    corpus.secrets,
                    "token_hex",
                    side_effect=(first_token, second_token, "4" * 32),
                ):
                    quarantine = corpus._quarantine_authoritative_candidate(
                        parent_custody=parent_hold,
                        candidate_custody=candidate_hold,
                        private_candidate_name=working.name,
                        canonical_output_name="model-corpus-output",
                        primary=corpus.ModelCorpusError("synthetic failure"),
                    )
                self.assertEqual(
                    (collision / "sentinel.bin").read_bytes(),
                    b"must not overwrite",
                )
                self.assertEqual(
                    quarantine.name,
                    corpus._authoritative_failed_name(second_token),
                )
                self.assertTrue(
                    (quarantine / corpus.AUTHORITATIVE_FAILURE_MARKER_NAME).is_file()
                )
            finally:
                candidate_hold.close()
                parent_hold.close()

    @unittest.skipUnless(os.name == "nt", "Windows authoritative marker only")
    def test_authoritative_failure_marker_is_absent_or_exact_on_stage_faults(
        self,
    ) -> None:
        class InjectedMarkerFailure(BaseException):
            pass

        for fault_stage in ("write", "flush", "fsync", "verify"):
            with self.subTest(stage=fault_stage), tempfile.TemporaryDirectory() as raw:
                root = Path(raw).resolve()
                parent, parent_hold, working, candidate_hold = (
                    self._create_windows_authoritative_candidate(root)
                )
                quarantine_name = corpus._authoritative_failed_name("2" * 32)
                quarantine = parent / quarantine_name
                try:
                    corpus._windows_publish_directory_by_handle(
                        source=candidate_hold,
                        parent=parent_hold,
                        target_name=quarantine_name,
                    )

                    def fault_hook(stage: str) -> None:
                        if stage == fault_stage:
                            raise InjectedMarkerFailure(
                                f"injected marker {stage} fault"
                            )

                    with self.assertRaises(InjectedMarkerFailure):
                        corpus._write_authoritative_failure_marker_atomic(
                            candidate_custody=candidate_hold,
                            quarantine_path=quarantine,
                            marker_payload=canonical(
                                {
                                    "schema_version": 1,
                                    "artifact_kind": "synthetic_failure_marker",
                                }
                            ),
                            _test_fault_hook=fault_hook,
                        )
                    self.assertFalse(
                        (
                            quarantine
                            / corpus.AUTHORITATIVE_FAILURE_MARKER_NAME
                        ).exists(),
                        "canonical marker must remain absent after any staged fault",
                    )
                finally:
                    candidate_hold.close()
                    parent_hold.close()

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            parent, parent_hold, _working, candidate_hold = (
                self._create_windows_authoritative_candidate(root)
            )
            quarantine_name = corpus._authoritative_failed_name("3" * 32)
            quarantine = parent / quarantine_name
            payload = canonical(
                {
                    "schema_version": 1,
                    "artifact_kind": "synthetic_failure_marker",
                }
            )
            try:
                corpus._windows_publish_directory_by_handle(
                    source=candidate_hold,
                    parent=parent_hold,
                    target_name=quarantine_name,
                )
                corpus._write_authoritative_failure_marker_atomic(
                    candidate_custody=candidate_hold,
                    quarantine_path=quarantine,
                    marker_payload=payload,
                )
                self.assertEqual(
                    (
                        quarantine / corpus.AUTHORITATIVE_FAILURE_MARKER_NAME
                    ).read_bytes(),
                    payload,
                )
                self.assertEqual(
                    [
                        path.name
                        for path in quarantine.iterdir()
                        if path.name.startswith(".authoritative-failure-marker.")
                    ],
                    [],
                )
            finally:
                candidate_hold.close()
                parent_hold.close()

    def test_authoritative_quarantine_failure_preserves_primary_and_diagnostic(
        self,
    ) -> None:
        primary = corpus.ModelCorpusError("primary model-corpus failure")
        with mock.patch.object(
            corpus,
            "_quarantine_authoritative_candidate",
            side_effect=corpus.ModelCorpusError("candidate remains locked"),
        ):
            quarantine = corpus._quarantine_authoritative_failure(
                parent_custody=mock.sentinel.parent_custody,
                candidate_custody=mock.sentinel.candidate_custody,
                private_candidate_name=".private.candidate",
                canonical_output_name="canonical-output",
                output_file_custody=ExitStack(),
                primary=primary,
            )
        self.assertIsNone(quarantine)
        rendered = corpus._format_model_corpus_error(primary)
        self.assertIn("ModelCorpusError: primary model-corpus failure", rendered)
        self.assertIn(
            "DIAGNOSTIC: authoritative failure quarantine failed: "
            "ModelCorpusError: candidate remains locked",
            rendered,
        )

    def test_required_authoritative_close_phase_aggregates_every_resource_class(
        self,
    ) -> None:
        labels = (
            "output_file_custody",
            "commit_media_custody",
            "tool_custody",
            "working_directory_custody",
            "parent_directory_custody",
        )

        class Resource:
            def __init__(
                self,
                label: str,
                events: list[str],
                failure: BaseException | None,
            ) -> None:
                self.label = label
                self.events = events
                self.failure = failure

            def close(self) -> None:
                self.events.append(self.label)
                if self.failure is not None:
                    raise self.failure

        for failing_label in labels:
            with self.subTest(resource=failing_label):
                events: list[str] = []
                primary = corpus.ModelCorpusError(
                    f"{failing_label} synthetic close failure"
                )
                resources = [
                    (
                        label,
                        Resource(
                            label,
                            events,
                            primary if label == failing_label else None,
                        ).close,
                    )
                    for label in labels
                ]
                observed = corpus._close_required_authoritative_resources(
                    resources
                )
                self.assertIs(observed, primary)
                self.assertEqual(events, list(labels))
                self.assertIn(
                    f"required authoritative close failed for {failing_label}",
                    corpus._format_model_corpus_error(primary),
                )

        first = corpus.ModelCorpusError("first close failure")
        second = corpus.ModelCorpusError("second close failure")
        observed = corpus._close_required_authoritative_resources(
            [
                ("output_file_custody", lambda: (_ for _ in ()).throw(first)),
                ("tool_custody", lambda: (_ for _ in ()).throw(second)),
            ]
        )
        self.assertIs(observed, first)
        self.assertIn(
            "required authoritative close failed for tool_custody: "
            "ModelCorpusError: second close failure",
            corpus._format_model_corpus_error(first),
        )

    @unittest.skipUnless(os.name == "nt", "Windows authoritative guards only")
    def test_second_guard_duplicate_failure_leaves_original_custody_usable(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            _parent, parent_hold, working, candidate_hold = (
                self._create_windows_authoritative_candidate(root)
            )
            first_guard: list[corpus._WindowsDirectoryCustody] = []
            primary = corpus.ModelCorpusError("second duplicate failed")
            try:
                original_duplicate = corpus._duplicate_windows_directory_custody

                def duplicate(
                    source: corpus._WindowsDirectoryCustody, *, label: str
                ) -> corpus._WindowsDirectoryCustody:
                    if not first_guard:
                        guard = original_duplicate(source, label=label)
                        first_guard.append(guard)
                        return guard
                    raise primary

                with (
                    mock.patch.object(
                        corpus,
                        "_duplicate_windows_directory_custody",
                        side_effect=duplicate,
                    ),
                    self.assertRaises(corpus.ModelCorpusError) as raised,
                ):
                    corpus._acquire_authoritative_quarantine_guards(
                        parent_custody=parent_hold,
                        candidate_custody=candidate_hold,
                        expected_candidate_name=working.name,
                    )
                self.assertIs(raised.exception, primary)
                self.assertEqual(len(first_guard), 1)
                with self.assertRaisesRegex(corpus.ExtractionError, "closed"):
                    _ = first_guard[0].handle
                corpus._validate_windows_direct_child_custody(
                    parent=parent_hold,
                    child=candidate_hold,
                    expected_name=working.name,
                )
            finally:
                candidate_hold.close()
                parent_hold.close()

    @unittest.skipUnless(os.name == "nt", "Windows authoritative guards only")
    def test_duplicate_guards_quarantine_same_file_id_after_originals_close(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            parent, parent_hold, working, candidate_hold = (
                self._create_windows_authoritative_candidate(root)
            )
            output_name = "model-corpus-output"
            parent_guard = None
            candidate_guard = None
            try:
                corpus._windows_publish_directory_by_handle(
                    source=candidate_hold,
                    parent=parent_hold,
                    target_name=output_name,
                )
                parent_guard, candidate_guard = (
                    corpus._acquire_authoritative_quarantine_guards(
                        parent_custody=parent_hold,
                        candidate_custody=candidate_hold,
                        expected_candidate_name=output_name,
                    )
                )
                original_identity = candidate_hold.identity
                candidate_hold.close()
                candidate_hold = None
                parent_hold.close()
                parent_hold = None
                quarantine = corpus._quarantine_authoritative_failure(
                    parent_custody=parent_guard,
                    candidate_custody=candidate_guard,
                    private_candidate_name=working.name,
                    canonical_output_name=output_name,
                    output_file_custody=ExitStack(),
                    primary=corpus.ModelCorpusError(
                        "synthetic required-close failure"
                    ),
                )
                self.assertIsNotNone(quarantine)
                assert quarantine is not None
                self.assertFalse((parent / output_name).exists())
                marker = json.loads(
                    (quarantine / corpus.AUTHORITATIVE_FAILURE_MARKER_NAME)
                    .read_text("ascii")
                )
                self.assertEqual(
                    marker["candidate_directory_identity"],
                    {
                        "volume_serial_number": original_identity[0],
                        "file_index": original_identity[1],
                    },
                )
            finally:
                if candidate_guard is not None:
                    candidate_guard.close()
                if parent_guard is not None:
                    parent_guard.close()
                if candidate_hold is not None:
                    candidate_hold.close()
                if parent_hold is not None:
                    parent_hold.close()

    def test_postcommit_guard_close_failure_is_bounded_nonthrowing_warning(
        self,
    ) -> None:
        class FailingGuard:
            def __init__(self, message: str) -> None:
                self.message = message

            def close(self) -> None:
                raise corpus.ModelCorpusError(self.message)

        stderr = io.StringIO()
        with mock.patch.object(corpus.sys, "stderr", stderr):
            corpus._release_postcommit_authoritative_guards(
                [
                    (
                        "candidate_guard",
                        FailingGuard("candidate close\nfailed\x00secret"),
                    ),
                    ("parent_guard", FailingGuard("parent close failed")),
                ]
            )
        rendered = stderr.getvalue()
        self.assertIn("WARNING: postcommit candidate_guard release failed", rendered)
        self.assertIn("WARNING: postcommit parent_guard release failed", rendered)
        self.assertNotIn("\x00", rendered)

    @unittest.skipUnless(os.name == "nt", "Windows authoritative sentinel only")
    def test_failed_quarantine_leaves_canonical_namespace_commit_pending(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            parent, parent_hold, working, candidate_hold = (
                self._create_windows_authoritative_candidate(root)
            )
            output_name = "model-corpus-output"
            output = parent / output_name
            sentinel = None
            try:
                sentinel = self._new_commit_pending(
                    working=working,
                    output=output,
                    output_name=output_name,
                )
                sentinel.prepare_for_parent_publish()
                corpus._windows_publish_directory_by_handle(
                    source=candidate_hold,
                    parent=parent_hold,
                    target_name=output_name,
                )
                sentinel.acquire_after_publish()
                sentinel.close_for_failure()
                primary = corpus.ModelCorpusError(
                    "synthetic postpublication failure"
                )
                with mock.patch.object(
                    corpus,
                    "_windows_publish_directory_by_handle",
                    side_effect=corpus.ExtractionError(
                        "injected quarantine rename failure"
                    ),
                ):
                    quarantine = corpus._quarantine_authoritative_failure(
                        parent_custody=parent_hold,
                        candidate_custody=candidate_hold,
                        private_candidate_name=working.name,
                        canonical_output_name=output_name,
                        output_file_custody=ExitStack(),
                        primary=primary,
                    )
                self.assertIsNone(quarantine)
                self.assertTrue(output.is_dir())
                sentinel_path = output / corpus.AUTHORITATIVE_COMMIT_PENDING_NAME
                self.assertEqual(sentinel_path.read_bytes(), sentinel.payload)
                self.assertIn(
                    "authoritative failure quarantine failed",
                    corpus._format_model_corpus_error(primary),
                )
            finally:
                if sentinel is not None:
                    sentinel.close_for_failure()
                candidate_hold.close()
                parent_hold.close()

    @unittest.skipUnless(os.name == "nt", "Windows authoritative sentinel only")
    def test_commit_pending_removal_is_last_exact_handle_success_operation(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            parent, parent_hold, working, candidate_hold = (
                self._create_windows_authoritative_candidate(root)
            )
            output_name = "model-corpus-output"
            output = parent / output_name
            sentinel = None
            try:
                sentinel = self._new_commit_pending(
                    working=working,
                    output=output,
                    output_name=output_name,
                )
                sentinel.prepare_for_parent_publish()
                corpus._windows_publish_directory_by_handle(
                    source=candidate_hold,
                    parent=parent_hold,
                    target_name=output_name,
                )
                sentinel.acquire_after_publish()
                sentinel.verify(published=True)
                sentinel.commit_success(
                    parent_custody=parent_hold,
                    canonical_output_name=output_name,
                )
                corpus._finalize_commit_pending_sentinel(
                    sentinel,
                    active_primary=None,
                )
                self.assertFalse(
                    (output / corpus.AUTHORITATIVE_COMMIT_PENDING_NAME).exists()
                )
                self.assertEqual(
                    [path.name for path in output.iterdir()],
                    [corpus.AUTHORITATIVE_COMMIT_RECORD_NAME],
                )
                self.assertEqual(
                    (
                        output / corpus.AUTHORITATIVE_COMMIT_RECORD_NAME
                    ).read_bytes(),
                    sentinel.payload,
                )
                self.assertEqual(
                    [path.name for path in parent.iterdir()],
                    [output_name],
                )
            finally:
                if sentinel is not None:
                    sentinel.close_for_failure()
                candidate_hold.close()
                parent_hold.close()

    @unittest.skipUnless(os.name == "nt", "Windows semantic commit only")
    def test_postcommit_close_and_observer_faults_cannot_become_failed_publication(
        self,
    ) -> None:
        class InjectedPostcommitFailure(BaseException):
            pass

        scenarios = (
            "close",
            "after_native_commit",
        )
        for scenario in scenarios:
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as raw:
                root = Path(raw).resolve()
                parent, parent_hold, working, candidate_hold = (
                    self._create_windows_authoritative_candidate(root)
                )
                output_name = "model-corpus-output"
                output = parent / output_name
                sentinel = None
                try:
                    sentinel = self._new_commit_pending(
                        working=working,
                        output=output,
                        output_name=output_name,
                    )
                    sentinel.prepare_for_parent_publish()
                    corpus._windows_publish_directory_by_handle(
                        source=candidate_hold,
                        parent=parent_hold,
                        target_name=output_name,
                    )
                    sentinel.acquire_after_publish()
                    stderr = io.StringIO()
                    with (
                        mock.patch.object(corpus.sys, "stderr", stderr),
                        mock.patch.object(
                            corpus,
                            "_quarantine_authoritative_candidate",
                            side_effect=corpus.ModelCorpusError(
                                "forced quarantine failure"
                            ),
                        ) as quarantine,
                    ):
                        if scenario == "close":
                            original_close = (
                                corpus._close_commit_pending_stream
                            )

                            def close_then_raise(stream: object) -> None:
                                original_close(stream)
                                raise InjectedPostcommitFailure(
                                    "injected close failure"
                                )

                            with mock.patch.object(
                                corpus,
                                "_close_commit_pending_stream",
                                side_effect=close_then_raise,
                            ):
                                sentinel.commit_success(
                                    parent_custody=parent_hold,
                                    canonical_output_name=output_name,
                                )
                                corpus._finalize_commit_pending_sentinel(
                                    sentinel,
                                    active_primary=None,
                                )
                        else:
                            sentinel.commit_success(
                                parent_custody=parent_hold,
                                canonical_output_name=output_name,
                                _test_fault_hook=lambda stage: (
                                    (_ for _ in ()).throw(
                                        InjectedPostcommitFailure(
                                            f"injected {stage} boundary"
                                        )
                                    )
                                    if stage == scenario
                                    else None
                                )
                            )
                            corpus._finalize_commit_pending_sentinel(
                                sentinel,
                                active_primary=None,
                            )
                    quarantine.assert_not_called()
                    self.assertTrue(sentinel.semantic_commit_observed())
                    self.assertFalse(
                        (
                            output / corpus.AUTHORITATIVE_COMMIT_PENDING_NAME
                        ).exists()
                    )
                    self.assertEqual(
                        (
                            output / corpus.AUTHORITATIVE_COMMIT_RECORD_NAME
                        ).read_bytes(),
                        sentinel.payload,
                    )
                    self.assertIn("WARNING: postcommit", stderr.getvalue())
                finally:
                    if sentinel is not None:
                        sentinel.close_for_failure()
                    candidate_hold.close()
                    parent_hold.close()

    @unittest.skipUnless(os.name == "nt", "Windows semantic commit only")
    def test_persistent_postcommit_close_failure_releases_canonical_namespace(
        self,
    ) -> None:
        class PersistentCloseFailure(BaseException):
            pass

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            parent, parent_hold, working, candidate_hold = (
                self._create_windows_authoritative_candidate(root)
            )
            output_name = "model-corpus-output"
            output = parent / output_name
            sentinel = None
            try:
                sentinel = self._new_commit_pending(
                    working=working,
                    output=output,
                    output_name=output_name,
                )
                sentinel.prepare_for_parent_publish()
                corpus._windows_publish_directory_by_handle(
                    source=candidate_hold,
                    parent=parent_hold,
                    target_name=output_name,
                )
                sentinel.acquire_after_publish()
                stderr = io.StringIO()
                with (
                    mock.patch.object(corpus.sys, "stderr", stderr),
                    mock.patch.object(
                        corpus,
                        "_close_commit_pending_stream",
                        side_effect=PersistentCloseFailure(
                            "persistent injected close failure"
                        ),
                    ),
                    mock.patch.object(
                        corpus,
                        "_quarantine_authoritative_candidate",
                        side_effect=corpus.ModelCorpusError(
                            "forced quarantine failure"
                        ),
                    ) as quarantine,
                ):
                    sentinel.commit_success(
                        parent_custody=parent_hold,
                        canonical_output_name=output_name,
                    )
                    corpus._finalize_commit_pending_sentinel(
                        sentinel,
                        active_primary=None,
                    )

                quarantine.assert_not_called()
                self.assertTrue(sentinel.semantic_commit_observed())
                self.assertFalse(
                    (output / corpus.AUTHORITATIVE_COMMIT_PENDING_NAME).exists()
                )
                self.assertEqual(
                    [path.name for path in output.iterdir()],
                    [corpus.AUTHORITATIVE_COMMIT_RECORD_NAME],
                )
                self.assertEqual(
                    sentinel._hash_handle(),
                    sha256(sentinel.payload),
                )
                self.assertGreaterEqual(
                    stderr.getvalue().count("WARNING: postcommit"), 1
                )
            finally:
                if sentinel is not None:
                    sentinel.close_for_failure()
                candidate_hold.close()
                parent_hold.close()

    @unittest.skipUnless(os.name == "nt", "Windows semantic commit only")
    def test_pre_native_commit_failure_keeps_canonical_child_guard(
        self,
    ) -> None:
        class PrecommitFailure(BaseException):
            pass

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            parent, parent_hold, working, candidate_hold = (
                self._create_windows_authoritative_candidate(root)
            )
            output_name = "model-corpus-output"
            output = parent / output_name
            sentinel = None
            try:
                sentinel = self._new_commit_pending(
                    working=working,
                    output=output,
                    output_name=output_name,
                )
                sentinel.prepare_for_parent_publish()
                corpus._windows_publish_directory_by_handle(
                    source=candidate_hold,
                    parent=parent_hold,
                    target_name=output_name,
                )
                sentinel.acquire_after_publish()
                primary = None
                with (
                    mock.patch.object(
                        corpus,
                        "_windows_move_held_file_no_replace",
                        side_effect=AssertionError(
                            "native move must not run after a pre-call fault"
                        ),
                    ) as native_move,
                    mock.patch.object(
                        corpus,
                        "_quarantine_authoritative_candidate",
                        side_effect=corpus.ModelCorpusError(
                            "forced quarantine failure"
                        ),
                    ) as quarantine,
                ):
                    try:
                        sentinel.commit_success(
                            parent_custody=parent_hold,
                            canonical_output_name=output_name,
                            _test_fault_hook=lambda stage: (
                                (_ for _ in ()).throw(
                                    PrecommitFailure(
                                        "injected before native commit"
                                    )
                                )
                                if stage == "before_native_commit"
                                else None
                            ),
                        )
                    except BaseException as exc:
                        primary = exc
                    self.assertIsNotNone(primary)
                    assert primary is not None
                    committed = corpus._resolve_authoritative_commit_failure(
                        project_root=root,
                        authoritative=True,
                        succeeded=True,
                        commit_pending=sentinel,
                        parent_custody=parent_hold,
                        candidate_custody=candidate_hold,
                        private_candidate_name=working.name,
                        canonical_output_name=output_name,
                        output_file_custody=ExitStack(),
                        primary=primary,
                    )

                self.assertFalse(committed)
                native_move.assert_not_called()
                quarantine.assert_called_once()
                guard = output / corpus.AUTHORITATIVE_COMMIT_PENDING_NAME
                self.assertEqual(guard.read_bytes(), sentinel.payload)
                with self.assertRaisesRegex(
                    corpus.ModelCorpusError,
                    "candidate file set is not exact",
                ):
                    corpus._validate_exact_tree(output, set(), set())
                self.assertFalse(
                    (
                        output / corpus.AUTHORITATIVE_COMMIT_RECORD_NAME
                    ).exists()
                )
            finally:
                if sentinel is not None:
                    sentinel.close_for_failure()
                candidate_hold.close()
                parent_hold.close()

    @unittest.skipUnless(os.name == "nt", "Windows semantic commit only")
    def test_native_commit_false_keeps_canonical_child_guard(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            source_receipt_payload = (
                self._install_synthetic_receipt_authority()
            )
            parent, parent_hold, working, candidate_hold = (
                self._create_windows_authoritative_candidate(root)
            )
            output_name = "model-corpus-output"
            output = parent / output_name
            _receipt, payload = self._write_commit_bound_receipt(
                project_root=root,
                candidate=working,
                output_name=output_name,
                source_receipt_payload=source_receipt_payload,
            )
            sentinel = None
            try:
                sentinel = corpus._AuthoritativeCommitPending(
                    working_path=(
                        working / corpus.AUTHORITATIVE_COMMIT_PENDING_NAME
                    ),
                    published_path=(
                        output / corpus.AUTHORITATIVE_COMMIT_PENDING_NAME
                    ),
                    commit_record_path=(
                        output / corpus.AUTHORITATIVE_COMMIT_RECORD_NAME
                    ),
                    payload=payload,
                )
                sentinel.prepare_for_parent_publish()
                corpus._windows_publish_directory_by_handle(
                    source=candidate_hold,
                    parent=parent_hold,
                    target_name=output_name,
                )
                sentinel.acquire_after_publish()
                with mock.patch.object(
                    corpus,
                    "_windows_move_held_file_no_replace",
                    return_value=(False, 5),
                ):
                    with self.assertRaisesRegex(
                        corpus.ModelCorpusError,
                        "native commit move returned FALSE",
                    ):
                        sentinel.commit_success(
                            parent_custody=parent_hold,
                            canonical_output_name=output_name,
                        )

                self.assertFalse(sentinel.semantic_commit_observed())
                sentinel.verify(published=True)
                self.assertTrue(
                    os.path.lexists(
                        output / corpus.AUTHORITATIVE_COMMIT_PENDING_NAME
                    )
                )
                self.assertFalse(
                    (
                        output / corpus.AUTHORITATIVE_COMMIT_RECORD_NAME
                    ).exists()
                )
                sentinel.close_for_failure()
                with self.assertRaisesRegex(
                    corpus.ModelCorpusError,
                    "file set|commit record|commit-record",
                ):
                    corpus._validate_committed_authoritative_candidate(
                        project_root=root,
                        output=output,
                    )
            finally:
                if sentinel is not None:
                    sentinel.close_for_failure()
                candidate_hold.close()
                parent_hold.close()

    @unittest.skipUnless(os.name == "nt", "Windows semantic commit only")
    def test_committed_candidate_validator_rejects_record_drift_and_extra_leaf(
        self,
    ) -> None:
        mutations = ("tampered", "missing", "extra")
        for mutation in mutations:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as raw:
                root = Path(raw).resolve()
                source_receipt_payload = (
                    self._install_synthetic_receipt_authority()
                )
                output_name = "model-corpus-output"
                parent, parent_hold, working, candidate_hold = (
                    self._create_windows_authoritative_candidate(root)
                )
                output = parent / output_name
                _receipt, payload = self._write_commit_bound_receipt(
                    project_root=root,
                    candidate=working,
                    output_name=output_name,
                    source_receipt_payload=source_receipt_payload,
                )
                sentinel = None
                try:
                    sentinel = corpus._AuthoritativeCommitPending(
                        working_path=(
                            working / corpus.AUTHORITATIVE_COMMIT_PENDING_NAME
                        ),
                        published_path=(
                            output / corpus.AUTHORITATIVE_COMMIT_PENDING_NAME
                        ),
                        commit_record_path=(
                            output / corpus.AUTHORITATIVE_COMMIT_RECORD_NAME
                        ),
                        payload=payload,
                    )
                    sentinel.prepare_for_parent_publish()
                    corpus._windows_publish_directory_by_handle(
                        source=candidate_hold,
                        parent=parent_hold,
                        target_name=output_name,
                    )
                    sentinel.acquire_after_publish()
                    sentinel.commit_success(
                        parent_custody=parent_hold,
                        canonical_output_name=output_name,
                    )
                    corpus._finalize_commit_pending_sentinel(
                        sentinel,
                        active_primary=None,
                    )
                    corpus._validate_committed_authoritative_candidate(
                        project_root=root,
                        output=output,
                    )
                    record = (
                        output / corpus.AUTHORITATIVE_COMMIT_RECORD_NAME
                    )
                    if mutation == "tampered":
                        record.write_bytes(b"tampered\n")
                    elif mutation == "missing":
                        record.unlink()
                    else:
                        (output / "unexpected.bin").write_bytes(b"extra")
                    with self.assertRaises(corpus.ModelCorpusError):
                        corpus._validate_committed_authoritative_candidate(
                            project_root=root,
                            output=output,
                        )
                finally:
                    if sentinel is not None:
                        sentinel.close_for_failure()
                    candidate_hold.close()
                    parent_hold.close()

    @unittest.skipUnless(os.name == "nt", "Windows semantic commit only")
    def test_fault_immediately_after_native_true_is_postcommit_success(
        self,
    ) -> None:
        class PostcommitFailure(BaseException):
            pass

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            parent, parent_hold, working, candidate_hold = (
                self._create_windows_authoritative_candidate(root)
            )
            output_name = "model-corpus-output"
            output = parent / output_name
            sentinel = None
            try:
                sentinel = self._new_commit_pending(
                    working=working,
                    output=output,
                    output_name=output_name,
                )
                sentinel.prepare_for_parent_publish()
                corpus._windows_publish_directory_by_handle(
                    source=candidate_hold,
                    parent=parent_hold,
                    target_name=output_name,
                )
                sentinel.acquire_after_publish()
                observed_stages: list[str] = []
                stderr = io.StringIO()

                def fault_after_true(stage: str) -> None:
                    observed_stages.append(stage)
                    if stage == "after_native_commit":
                        raise PostcommitFailure(
                            "injected immediately after native TRUE"
                        )

                with (
                    mock.patch.object(corpus.sys, "stderr", stderr),
                    mock.patch.object(
                        corpus,
                        "_quarantine_authoritative_candidate",
                        side_effect=corpus.ModelCorpusError(
                            "forced quarantine failure"
                        ),
                    ) as quarantine,
                ):
                    sentinel.commit_success(
                        parent_custody=parent_hold,
                        canonical_output_name=output_name,
                        _test_fault_hook=fault_after_true,
                    )

                quarantine.assert_not_called()
                self.assertIn("after_native_commit", observed_stages)
                self.assertTrue(sentinel.semantic_commit_observed())
                self.assertEqual(
                    [path.name for path in output.iterdir()],
                    [corpus.AUTHORITATIVE_COMMIT_RECORD_NAME],
                )
                self.assertIn("WARNING: postcommit", stderr.getvalue())
            finally:
                if sentinel is not None:
                    sentinel.close_for_failure()
                candidate_hold.close()
                parent_hold.close()

    @unittest.skipUnless(os.name == "nt", "Windows semantic commit only")
    def test_native_true_then_python_gap_is_resolved_by_permanent_record(
        self,
    ) -> None:
        class NativeReturnGap(BaseException):
            pass

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            source_receipt_payload = (
                self._install_synthetic_receipt_authority()
            )
            output_name = "model-corpus-output"
            parent, parent_hold, working, candidate_hold = (
                self._create_windows_authoritative_candidate(root)
            )
            output = parent / output_name
            _expected_receipt, payload = self._write_commit_bound_receipt(
                project_root=root,
                candidate=working,
                output_name=output_name,
                source_receipt_payload=source_receipt_payload,
            )
            sentinel = None
            try:
                sentinel = corpus._AuthoritativeCommitPending(
                    working_path=(
                        working / corpus.AUTHORITATIVE_COMMIT_PENDING_NAME
                    ),
                    published_path=(
                        output / corpus.AUTHORITATIVE_COMMIT_PENDING_NAME
                    ),
                    commit_record_path=(
                        output / corpus.AUTHORITATIVE_COMMIT_RECORD_NAME
                    ),
                    payload=payload,
                )
                sentinel.prepare_for_parent_publish()
                corpus._windows_publish_directory_by_handle(
                    source=candidate_hold,
                    parent=parent_hold,
                    target_name=output_name,
                )
                sentinel.acquire_after_publish()
                real_move = corpus._windows_move_held_file_no_replace

                def move_then_raise(**kwargs: object) -> tuple[bool, int]:
                    moved, error = real_move(**kwargs)
                    self.assertTrue(moved)
                    self.assertEqual(error, 0)
                    raise NativeReturnGap(
                        "injected between native TRUE and Python return"
                    )

                primary = None
                with (
                    mock.patch.object(
                        corpus,
                        "_windows_move_held_file_no_replace",
                        side_effect=move_then_raise,
                    ),
                    mock.patch.object(
                        corpus,
                        "_quarantine_authoritative_candidate",
                        return_value=parent / ".must-not-quarantine.failed",
                    ) as quarantine,
                ):
                    try:
                        sentinel.commit_success(
                            parent_custody=parent_hold,
                            canonical_output_name=output_name,
                        )
                    except BaseException as exc:
                        primary = exc
                    self.assertIsNotNone(primary)
                    assert primary is not None
                    committed = corpus._resolve_authoritative_commit_failure(
                        project_root=root,
                        authoritative=True,
                        succeeded=True,
                        commit_pending=sentinel,
                        parent_custody=parent_hold,
                        candidate_custody=candidate_hold,
                        private_candidate_name=working.name,
                        canonical_output_name=output_name,
                        output_file_custody=ExitStack(),
                        primary=primary,
                    )

                self.assertTrue(committed)
                self.assertTrue(sentinel.semantic_commit_observed())
                quarantine.assert_not_called()
                corpus._finalize_commit_pending_sentinel(
                    sentinel,
                    active_primary=None,
                )
                validated = corpus._validate_committed_authoritative_candidate(
                    project_root=root,
                    output=output,
                )
                self.assertEqual(
                    validated,
                    json.loads(
                        (output / corpus.RECEIPT_NAME).read_text("ascii")
                    ),
                )
                self.assertFalse(
                    os.path.lexists(
                        output / corpus.AUTHORITATIVE_COMMIT_PENDING_NAME
                    )
                )
                self.assertEqual(
                    (
                        output / corpus.AUTHORITATIVE_COMMIT_RECORD_NAME
                    ).read_bytes(),
                    payload,
                )
            finally:
                if sentinel is not None:
                    sentinel.close_for_failure()
                candidate_hold.close()
                parent_hold.close()

    @unittest.skipUnless(os.name == "nt", "Windows authoritative resume only")
    def test_identical_public_call_resumes_existing_committed_candidate_read_only(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            staging = root / "staging"
            staging.mkdir()
            output = staging / "model-corpus-output"
            output.mkdir()
            (output / "authoritative_commit.json").write_bytes(b"held\n")
            expected_receipt = {
                "artifact_kind": corpus.RECEIPT_ARTIFACT_KIND,
                "candidate_receipt_sha256": "a" * 64,
            }
            before = {
                path.relative_to(root).as_posix(): path.read_bytes()
                for path in output.iterdir()
            }
            with (
                mock.patch.object(
                    corpus,
                    "_validate_committed_authoritative_candidate",
                    return_value=expected_receipt,
                ) as validate,
                mock.patch.object(
                    corpus,
                    "_validate_resumed_candidate_invocation",
                ) as validate_invocation,
                mock.patch.object(
                    corpus,
                    "_validated_materialization_receipt",
                    side_effect=AssertionError(
                        "resume must not read source materialization inputs"
                    ),
                ) as source_receipt,
                mock.patch.object(
                    corpus,
                    "_create_windows_private_working_directory_with_custody",
                    side_effect=AssertionError(
                        "resume must not create a working candidate"
                    ),
                ) as create,
            ):
                observed = corpus.materialize_model_corpus(
                    project_root=root,
                    materialization_receipt=(
                        root
                        / Path(
                            *Path(corpus.MATERIALIZATION_RECEIPT_PATH).parts
                        )
                    ),
                    expected_materialization_receipt_size_bytes=(
                        corpus.EXPECTED_MATERIALIZATION_RECEIPT_SIZE_BYTES
                    ),
                    expected_materialization_receipt_sha256=(
                        corpus.EXPECTED_MATERIALIZATION_RECEIPT_FILE_SHA256
                    ),
                    expected_materialization_receipt_self_sha256=(
                        corpus.EXPECTED_MATERIALIZATION_RECEIPT_SELF_SHA256
                    ),
                    model_parity_manifest=root / "must-not-open.yaml",
                    expected_model_parity_manifest_sha256="4" * 64,
                    ffmpeg=root / "must-not-run-ffmpeg.exe",
                    expected_ffmpeg_sha256="5" * 64,
                    expected_ffmpeg_version_sha256="6" * 64,
                    ffprobe=root / "must-not-run-ffprobe.exe",
                    expected_ffprobe_sha256="7" * 64,
                    expected_ffprobe_version_sha256="8" * 64,
                    expected_source_set_sha256="9" * 64,
                    output_dir=output,
                )

            self.assertEqual(observed, expected_receipt)
            validate.assert_called_once()
            validate_invocation.assert_called_once()
            source_receipt.assert_not_called()
            create.assert_not_called()
            self.assertEqual(
                {
                    path.relative_to(root).as_posix(): path.read_bytes()
                    for path in output.iterdir()
                },
                before,
            )

    @unittest.skipUnless(os.name == "nt", "Windows authoritative resume only")
    def test_existing_output_drift_or_collision_fails_untouched(self) -> None:
        for kind in ("directory", "file"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as raw:
                root = Path(raw).resolve()
                staging = root / "staging"
                staging.mkdir()
                output = staging / "model-corpus-output"
                if kind == "directory":
                    output.mkdir()
                    (output / "rogue.bin").write_bytes(b"rogue")
                else:
                    output.write_bytes(b"collision")
                with (
                    mock.patch.object(
                        corpus,
                        "_validated_materialization_receipt",
                        side_effect=AssertionError(
                            "invalid existing output must fail before inputs"
                        ),
                    ) as source_receipt,
                    mock.patch.object(
                        corpus,
                        "_create_windows_private_working_directory_with_custody",
                        side_effect=AssertionError(
                            "invalid existing output must not be mutated"
                        ),
                    ) as create,
                    self.assertRaises(corpus.ModelCorpusError),
                ):
                    corpus.materialize_model_corpus(
                        project_root=root,
                        materialization_receipt=(
                            root
                            / Path(
                                *Path(
                                    corpus.MATERIALIZATION_RECEIPT_PATH
                                ).parts
                            )
                        ),
                        expected_materialization_receipt_size_bytes=(
                            corpus.EXPECTED_MATERIALIZATION_RECEIPT_SIZE_BYTES
                        ),
                        expected_materialization_receipt_sha256=(
                            corpus.EXPECTED_MATERIALIZATION_RECEIPT_FILE_SHA256
                        ),
                        expected_materialization_receipt_self_sha256=(
                            corpus.EXPECTED_MATERIALIZATION_RECEIPT_SELF_SHA256
                        ),
                        model_parity_manifest=root / "unused.yaml",
                        expected_model_parity_manifest_sha256="4" * 64,
                        ffmpeg=root / "unused-ffmpeg.exe",
                        expected_ffmpeg_sha256="5" * 64,
                        expected_ffmpeg_version_sha256="6" * 64,
                        ffprobe=root / "unused-ffprobe.exe",
                        expected_ffprobe_sha256="7" * 64,
                        expected_ffprobe_version_sha256="8" * 64,
                        expected_source_set_sha256="9" * 64,
                        output_dir=output,
                    )
                source_receipt.assert_not_called()
                create.assert_not_called()
                if kind == "directory":
                    self.assertEqual(
                        (output / "rogue.bin").read_bytes(), b"rogue"
                    )
                    self.assertEqual(
                        [path.name for path in output.iterdir()],
                        ["rogue.bin"],
                    )
                else:
                    self.assertEqual(output.read_bytes(), b"collision")

    @unittest.skipUnless(os.name == "nt", "Windows committed resume only")
    def test_resealed_receipt_core_or_schema_drift_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = Fixture(Path(raw))
            self._install_synthetic_receipt_authority(
                fixture.receipt_payload,
                self_sha256=str(
                    fixture.receipt["materialization_receipt_sha256"]
                ),
            )
            output_name = "receipt-core-candidate"
            receipt = fixture.run(output_name=output_name)
            output = fixture.root / "staging" / output_name
            receipt["source_materialization_receipt"] = {
                "path": corpus.MATERIALIZATION_RECEIPT_PATH,
                "size_bytes": (
                    corpus.EXPECTED_MATERIALIZATION_RECEIPT_SIZE_BYTES
                ),
                "sha256": (
                    corpus.EXPECTED_MATERIALIZATION_RECEIPT_FILE_SHA256
                ),
                "materialization_receipt_sha256": (
                    corpus.EXPECTED_MATERIALIZATION_RECEIPT_SELF_SHA256
                ),
            }
            dataset_source = receipt["source_dataset_config"]["source"]
            dataset_source.pop("canonical_frozen_validator_applied", None)
            dataset_source["path"] = "configs/datasets.yaml"
            receipt["source_dataset_config"][
                "canonical_frozen_validator_applied"
            ] = True
            core_sha256 = corpus._candidate_receipt_core_sha(receipt)
            record_payload = corpus._authoritative_commit_record_payload(
                canonical_output_root=f"staging/{output_name}",
                canonical_output_name=output_name,
                outputs_sha256=sha256(canonical(receipt["outputs"])),
                sampling_rule_sha256=receipt["sampling_rule_sha256"],
                source_set_canonical_aggregate_sha256=receipt["tool_pins"][
                    "local_source_set"
                ]["canonical_aggregate_sha256"],
                source_materialization_receipt=receipt[
                    "source_materialization_receipt"
                ],
                source_model_parity_manifest_sha256=receipt[
                    "source_model_parity_manifest_sha256"
                ],
                candidate_receipt_core_sha256=core_sha256,
            )
            receipt["authoritative_commit_record"] = {
                "path": (
                    f"staging/{output_name}/"
                    f"{corpus.AUTHORITATIVE_COMMIT_RECORD_NAME}"
                ),
                "size_bytes": len(record_payload),
                "sha256": sha256(record_payload),
            }
            receipt["candidate_receipt_sha256"] = corpus._candidate_self_sha(
                receipt
            )
            (output / corpus.AUTHORITATIVE_COMMIT_RECORD_NAME).write_bytes(
                record_payload
            )
            record_document = json.loads(record_payload.decode("ascii"))
            self.assertEqual(
                record_document["candidate_receipt_core_sha256"],
                corpus._candidate_receipt_core_sha(receipt),
            )
            receipt_path = output / corpus.RECEIPT_NAME
            receipt_path.write_bytes(canonical(receipt))
            self.assertEqual(
                corpus._validate_committed_authoritative_candidate(
                    project_root=fixture.root,
                    output=output,
                ),
                receipt,
            )
            committed_tree = {
                path.name: path.read_bytes() for path in output.iterdir()
            }
            with (
                mock.patch.object(
                    corpus,
                    "_validated_materialization_receipt",
                    side_effect=AssertionError(
                        "committed resume must not reopen source inputs"
                    ),
                ) as source_receipt,
                mock.patch.object(
                    corpus,
                    "_create_windows_private_working_directory_with_custody",
                    side_effect=AssertionError(
                        "committed resume must not create or publish"
                    ),
                ) as create,
            ):
                resumed = corpus.materialize_model_corpus(
                    project_root=fixture.root,
                    materialization_receipt=fixture.receipt_path,
                    expected_materialization_receipt_size_bytes=(
                        corpus.EXPECTED_MATERIALIZATION_RECEIPT_SIZE_BYTES
                    ),
                    expected_materialization_receipt_sha256=(
                        corpus.EXPECTED_MATERIALIZATION_RECEIPT_FILE_SHA256
                    ),
                    expected_materialization_receipt_self_sha256=(
                        corpus.EXPECTED_MATERIALIZATION_RECEIPT_SELF_SHA256
                    ),
                    model_parity_manifest=fixture.parity_manifest_path,
                    expected_model_parity_manifest_sha256=receipt[
                        "source_model_parity_manifest_sha256"
                    ],
                    ffmpeg=fixture.ffmpeg,
                    expected_ffmpeg_sha256=receipt["tool_pins"]["ffmpeg"][
                        "sha256"
                    ],
                    expected_ffmpeg_version_sha256=receipt["tool_pins"][
                        "ffmpeg"
                    ]["version_output_sha256"],
                    ffprobe=fixture.ffprobe,
                    expected_ffprobe_sha256=receipt["tool_pins"]["ffprobe"][
                        "sha256"
                    ],
                    expected_ffprobe_version_sha256=receipt["tool_pins"][
                        "ffprobe"
                    ]["version_output_sha256"],
                    expected_source_set_sha256=receipt["tool_pins"][
                        "local_source_set"
                    ]["canonical_aggregate_sha256"],
                    output_dir=output,
                )
            self.assertEqual(resumed, receipt)
            source_receipt.assert_not_called()
            create.assert_not_called()
            self.assertEqual(
                {path.name: path.read_bytes() for path in output.iterdir()},
                committed_tree,
            )

            def claim_drift(value: dict[str, object]) -> None:
                value["claims"]["accuracy"] = True

            def unknown_top(value: dict[str, object]) -> None:
                value["unreviewed_extension"] = {"accepted": True}

            def dataset_drift(value: dict[str, object]) -> None:
                value["source_dataset_config"]["unknown"] = "drift"

            def tool_drift(value: dict[str, object]) -> None:
                value["tool_pins"]["ffmpeg"]["sha256"] = "f" * 64

            for label, mutate in (
                ("claims", claim_drift),
                ("unknown_top", unknown_top),
                ("source_dataset_config", dataset_drift),
                ("tool_pin", tool_drift),
            ):
                with self.subTest(label=label):
                    drifted = copy.deepcopy(receipt)
                    mutate(drifted)
                    drifted["candidate_receipt_sha256"] = (
                        corpus._candidate_self_sha(drifted)
                    )
                    receipt_path.write_bytes(canonical(drifted))
                    with self.assertRaises(corpus.ModelCorpusError):
                        corpus._validate_committed_authoritative_candidate(
                            project_root=fixture.root,
                            output=output,
                        )
            receipt_path.write_bytes(canonical(receipt))

    @unittest.skipUnless(os.name == "nt", "Windows committed resume only")
    def test_resealed_materializer_and_preprocessor_role_drift_is_rejected(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            (root / "staging").mkdir()
            candidate = root / "staging" / "source-role-candidate"
            candidate.mkdir()
            source_receipt_payload = self._install_synthetic_receipt_authority()
            receipt, _record_payload = self._write_commit_bound_receipt(
                project_root=root,
                candidate=candidate,
                output_name=candidate.name,
                source_receipt_payload=source_receipt_payload,
            )

            for pin_name in ("materializer", "preprocessor"):
                with self.subTest(pin_name=pin_name):
                    drifted = copy.deepcopy(receipt)
                    drifted["tool_pins"][pin_name]["role"] = (
                        "resealed descriptive role drift"
                    )
                    self._reseal_commit_bound_receipt(
                        candidate=candidate,
                        receipt=drifted,
                    )
                    with (
                        mock.patch.object(
                            corpus,
                            "_validate_private_publication_set",
                        ),
                        self.assertRaisesRegex(
                            corpus.ModelCorpusError,
                            rf"{pin_name} source pin binding drifted",
                        ),
                    ):
                        corpus._validate_committed_authoritative_candidate(
                            project_root=root,
                            output=candidate,
                        )

    @unittest.skipUnless(os.name == "nt", "Windows committed resume only")
    def test_committed_resume_holds_every_validated_leaf_through_terminal_scan(
        self,
    ) -> None:
        for attacked_role in ("receipt", "early_output", "commit_record"):
            with (
                self.subTest(attacked_role=attacked_role),
                tempfile.TemporaryDirectory() as raw,
            ):
                root = Path(raw).resolve()
                (root / "staging").mkdir()
                candidate = root / "staging" / f"held-{attacked_role}"
                candidate.mkdir()
                source_receipt_payload = (
                    self._install_synthetic_receipt_authority()
                )
                receipt, _record_payload = self._write_commit_bound_receipt(
                    project_root=root,
                    candidate=candidate,
                    output_name=candidate.name,
                    source_receipt_payload=source_receipt_payload,
                )
                self._reseal_commit_bound_receipt(
                    candidate=candidate,
                    receipt=receipt,
                )
                if attacked_role == "receipt":
                    attacked_path = candidate / corpus.RECEIPT_NAME
                elif attacked_role == "early_output":
                    attacked_path = root / Path(
                        *Path(receipt["outputs"][0]["path"]).parts
                    )
                else:
                    attacked_path = (
                        candidate / corpus.AUTHORITATIVE_COMMIT_RECORD_NAME
                    )

                before = {
                    path.name: path.read_bytes() for path in candidate.iterdir()
                }
                attacked = False

                def replace_same_size_after_validation() -> None:
                    nonlocal attacked
                    if attacked:
                        return
                    attacked = True
                    original = attacked_path.read_bytes()
                    self.assertGreater(len(original), 0)
                    replacement = attacked_path.with_name(
                        f".{attacked_path.name}.same-size-replacement"
                    )
                    replacement.write_bytes(
                        bytes([original[0] ^ 1]) + original[1:]
                    )
                    try:
                        os.replace(replacement, attacked_path)
                    except PermissionError as exc:
                        replacement.unlink(missing_ok=True)
                        raise corpus.ModelCorpusError(
                            "held committed leaf custody prevented injected replacement"
                        ) from exc

                original_tree_scan = corpus._validate_exact_tree
                original_candidate_self_sha = corpus._candidate_self_sha

                def scan_after_attack(
                    tree_root: Path,
                    expected_files: set[str],
                    expected_dirs: set[str],
                ) -> None:
                    if attacked_role != "commit_record":
                        replace_same_size_after_validation()
                    original_tree_scan(
                        tree_root,
                        expected_files,
                        expected_dirs,
                    )

                def self_sha_after_record_attack(
                    value: dict[str, object],
                ) -> str:
                    if attacked_role == "commit_record":
                        replace_same_size_after_validation()
                    return original_candidate_self_sha(value)

                with (
                    mock.patch.object(
                        corpus,
                        "_validate_exact_tree",
                        side_effect=scan_after_attack,
                    ),
                    mock.patch.object(
                        corpus,
                        "_candidate_self_sha",
                        side_effect=self_sha_after_record_attack,
                    ),
                    mock.patch.object(
                        corpus,
                        "_validate_private_publication_set",
                    ),
                    self.assertRaisesRegex(
                        corpus.ModelCorpusError,
                        "held committed leaf custody prevented",
                    ),
                ):
                    corpus._validate_committed_authoritative_candidate(
                        project_root=root,
                        output=candidate,
                    )

                self.assertTrue(attacked)
                self.assertEqual(
                    {
                        path.name: path.read_bytes()
                        for path in candidate.iterdir()
                    },
                    before,
                )

    @unittest.skipUnless(os.name == "nt", "Windows committed resume only")
    def test_existing_candidate_size_caps_reject_before_oversized_leaf_read(
        self,
    ) -> None:
        cases = ("receipt", "commit_record", "descriptor_payload")
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as raw:
                root = Path(raw).resolve()
                (root / "staging").mkdir()
                candidate = root / "staging" / "oversized-candidate"
                candidate.mkdir()
                original_open = corpus._open_binary_custody
                original_leaf = corpus._leaf_is_plain_file

                if case == "receipt":
                    attacked_path = candidate / corpus.RECEIPT_NAME
                    attacked_path.write_bytes(b"oversized receipt placeholder\n")
                    observed = attacked_path.lstat()
                    oversized = list(observed)
                    oversized[6] = (
                        corpus.AUTHORITATIVE_CANDIDATE_RECEIPT_MAX_BYTES + 1
                    )
                    fake_stat = os.stat_result(oversized)

                    def oversized_leaf(path: Path, *, label: str):
                        if path == attacked_path:
                            return fake_stat
                        return original_leaf(path, label=label)

                    leaf_patch = mock.patch.object(
                        corpus,
                        "_leaf_is_plain_file",
                        side_effect=oversized_leaf,
                    )
                else:
                    source_receipt_payload = (
                        self._install_synthetic_receipt_authority()
                    )
                    receipt, _record_payload = (
                        self._write_commit_bound_receipt(
                            project_root=root,
                            candidate=candidate,
                            output_name=candidate.name,
                            source_receipt_payload=source_receipt_payload,
                        )
                    )
                    self._reseal_commit_bound_receipt(
                        candidate=candidate,
                        receipt=receipt,
                    )
                    if case == "commit_record":
                        attacked_path = (
                            candidate / corpus.AUTHORITATIVE_COMMIT_RECORD_NAME
                        )
                        size_limit = (
                            corpus.AUTHORITATIVE_COMMIT_RECORD_MAX_BYTES
                        )
                    else:
                        attacked_name = "raw_h264_front_gate.rgb24.bin"
                        attacked_path = candidate / attacked_name
                        size_limit = (
                            corpus.AUTHORITATIVE_DESCRIPTOR_PAYLOAD_MAX_BYTES
                        )
                        attacked_descriptor = next(
                            item
                            for item in receipt["outputs"]
                            if item["path"].endswith(f"/{attacked_name}")
                        )
                        attacked_descriptor["size_bytes"] = size_limit + 1
                        attacked_descriptor["sha256"] = "e" * 64
                        self._reseal_commit_bound_receipt(
                            candidate=candidate,
                            receipt=receipt,
                        )
                    observed = attacked_path.lstat()
                    oversized = list(observed)
                    oversized[6] = size_limit + 1
                    fake_stat = os.stat_result(oversized)

                    def oversized_leaf(path: Path, *, label: str):
                        observed_leaf = original_leaf(path, label=label)
                        return fake_stat if path == attacked_path else observed_leaf

                    leaf_patch = mock.patch.object(
                        corpus,
                        "_leaf_is_plain_file",
                        side_effect=oversized_leaf,
                    )

                def deny_attacked_read(path: Path, *, label: str):
                    if path == attacked_path:
                        raise AssertionError(
                            f"oversized {case} was opened for a full read"
                        )
                    return original_open(path, label=label)

                before = {
                    path.name: (path.stat().st_size, path.stat().st_mtime_ns)
                    for path in candidate.iterdir()
                }
                with (
                    leaf_patch,
                    mock.patch.object(
                        corpus,
                        "_open_binary_custody",
                        side_effect=deny_attacked_read,
                    ),
                    mock.patch.object(
                        corpus,
                        "_validate_private_publication_set",
                    ),
                    mock.patch.object(
                        corpus,
                        "_validated_materialization_receipt",
                        side_effect=AssertionError(
                            "oversized resume must not access source inputs"
                        ),
                    ) as source_receipt,
                    mock.patch.object(
                        corpus,
                        "_create_windows_private_working_directory_with_custody",
                        side_effect=AssertionError(
                            "oversized resume must not create or write"
                        ),
                    ) as create,
                    mock.patch.object(
                        corpus,
                        "_run_sanitized_subprocess",
                        side_effect=AssertionError(
                            "oversized resume must not run a tool"
                        ),
                    ) as run_tool,
                    self.assertRaisesRegex(
                        corpus.ModelCorpusError,
                        "size limit|size cap|oversized",
                    ),
                ):
                    corpus.materialize_model_corpus(
                        project_root=root,
                        materialization_receipt=(
                            root
                            / Path(
                                *Path(
                                    corpus.MATERIALIZATION_RECEIPT_PATH
                                ).parts
                            )
                        ),
                        expected_materialization_receipt_size_bytes=(
                            corpus.EXPECTED_MATERIALIZATION_RECEIPT_SIZE_BYTES
                        ),
                        expected_materialization_receipt_sha256=(
                            corpus.EXPECTED_MATERIALIZATION_RECEIPT_FILE_SHA256
                        ),
                        expected_materialization_receipt_self_sha256=(
                            corpus.EXPECTED_MATERIALIZATION_RECEIPT_SELF_SHA256
                        ),
                        model_parity_manifest=root / "must-not-open.yaml",
                        expected_model_parity_manifest_sha256="4" * 64,
                        ffmpeg=root / "must-not-run-ffmpeg.exe",
                        expected_ffmpeg_sha256="5" * 64,
                        expected_ffmpeg_version_sha256="6" * 64,
                        ffprobe=root / "must-not-run-ffprobe.exe",
                        expected_ffprobe_sha256="7" * 64,
                        expected_ffprobe_version_sha256="8" * 64,
                        expected_source_set_sha256="9" * 64,
                        output_dir=candidate,
                    )
                source_receipt.assert_not_called()
                create.assert_not_called()
                run_tool.assert_not_called()
                self.assertEqual(
                    {
                        path.name: (path.stat().st_size, path.stat().st_mtime_ns)
                        for path in candidate.iterdir()
                    },
                    before,
                )

    def test_subprocess_projection_binds_parent_drained_hard_capture_v4(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            cwd = root / "private-candidate-root"
            cwd.mkdir(mode=0o700)
            context = corpus._build_subprocess_context(
                root=root,
                cwd=cwd,
                published_cwd=root / "published-candidate-root",
            )
            projection = context.descriptor["canonical_projection"]
            self.assertEqual(projection["schema_version"], 4)
            self.assertEqual(
                projection["policy_id"],
                "kpp_model_corpus_minimal_subprocess_context_v4",
            )
            self.assertEqual(
                projection["stdout"],
                "PARENT_DRAINED_PIPE_TO_PRIVATE_HARD_BOUNDED_CAPTURE",
            )
            self.assertEqual(
                projection["stderr"],
                "PARENT_DRAINED_PIPE_TO_PRIVATE_HARD_BOUNDED_CAPTURE",
            )
            self.assertEqual(
                projection["capture_transport"], "PARENT_DRAINED_OS_PIPE"
            )
            self.assertIs(
                projection["capture_storage_growth_hard_limited"], True
            )
            storage = projection["capture_storage"]
            if os.name == "nt":
                self.assertEqual(storage["platform_family"], "windows")
                self.assertEqual(
                    storage["creation_primitive"],
                    "CREATEFILEW_CREATE_NEW_SHARE_MODE_NONE",
                )
                self.assertIs(
                    storage["same_token_path_reopen_for_write_denied"],
                    True,
                )
                self.assertIs(
                    projection["capture_files_inside_private_cwd"], True
                )
                self.assertIs(
                    projection[
                        "temporary_capture_file_growth_hard_limited"
                    ],
                    True,
                )
            else:
                self.assertEqual(storage["platform_family"], "posix")
                self.assertEqual(
                    storage["storage_kind"], "PARENT_PRIVATE_MEMORY"
                )
                self.assertIs(
                    storage["same_token_path_reopen_for_write_denied"],
                    None,
                )
                self.assertIs(
                    projection["capture_files_inside_private_cwd"], False
                )
                self.assertIs(
                    projection[
                        "temporary_capture_file_growth_hard_limited"
                    ],
                    None,
                )
            self.assertEqual(projection["pipe_capture_chunk_bytes"], 65536)
            self.assertGreater(
                projection["pipe_reader_join_grace_seconds"], 0
            )
            self.assertIs(
                projection["process_tree_termination_attested"], False
            )
            self.assertIs(
                projection["descendant_output_completion_attested"], False
            )

    def test_private_capture_storage_enforces_platform_contract(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            cwd = Path(raw).resolve()
            with corpus._open_private_hard_bounded_capture(
                directory=cwd,
                prefix=".subprocess-contract-test.",
                limit=32,
            ) as capture:
                if os.name == "nt":
                    self.assertIsNotNone(capture.path)
                    self.assertEqual(len(list(cwd.iterdir())), 1)
                else:
                    self.assertIsNone(capture.path)
                    self.assertEqual(list(cwd.iterdir()), [])
                self.assertEqual(capture.write(b"x" * 32), 32)
                self.assertEqual(corpus._capture_storage_size(capture), 32)
                with self.assertRaisesRegex(
                    corpus.ModelCorpusError, "hard limit rejected"
                ):
                    capture.write(b"y")
                self.assertEqual(corpus._capture_storage_size(capture), 32)
            self.assertEqual(list(cwd.iterdir()), [])

    def test_parent_drained_capture_accepts_exact_stream_limits(self) -> None:
        completed, failure, captures, _projection = (
            self._recorded_gateway_call(
                command=[
                    sys.executable,
                    "-c",
                    (
                        "import os;"
                        "os.write(1,b'o'*4096);"
                        "os.write(2,b'e'*2048)"
                    ),
                ],
                policy={
                    "timeout_seconds": 5,
                    "stdout_limit_bytes": 4096,
                    "stderr_limit_bytes": 2048,
                },
            )
        )
        self.assertIsNone(failure)
        assert completed is not None
        self.assertEqual(completed.stdout, b"o" * 4096)
        self.assertEqual(completed.stderr, b"e" * 2048)
        self.assertEqual(len(captures), 2)
        self.assertEqual(
            [capture.maximum_observed_size for capture in captures],
            [4096, 2048],
        )

    def test_parent_drained_capture_rejects_limit_plus_one_without_disk_overshoot(
        self,
    ) -> None:
        completed, failure, captures, _projection = (
            self._recorded_gateway_call(
                command=[
                    sys.executable,
                    "-c",
                    "import os;os.write(1,b'o'*4097)",
                ],
                policy={
                    "timeout_seconds": 5,
                    "stdout_limit_bytes": 4096,
                    "stderr_limit_bytes": 2048,
                },
            )
        )
        self.assertIsNone(completed)
        self.assertIsInstance(failure, corpus.ModelCorpusError)
        self.assertRegex(str(failure), r"stdout.*4096")
        self.assertEqual(len(captures), 2)
        self.assertLessEqual(captures[0].maximum_observed_size, 4096)
        self.assertLessEqual(captures[1].maximum_observed_size, 2048)

    @unittest.skipUnless(os.name == "nt", "Windows native capture reopen only")
    def test_parent_drained_capture_blocks_native_same_token_reopen_and_growth(
        self,
    ) -> None:
        reopen_program = """
import ctypes
import msvcrt
import os
from ctypes import wintypes
from pathlib import Path

target = next(Path.cwd().glob(".subprocess-stdout.*"))
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
create_file = kernel32.CreateFileW
create_file.argtypes = [
    wintypes.LPCWSTR,
    wintypes.DWORD,
    wintypes.DWORD,
    ctypes.c_void_p,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.HANDLE,
]
create_file.restype = wintypes.HANDLE
handle = create_file(
    str(target),
    0x40000000,
    0x00000001 | 0x00000002 | 0x00000004,
    None,
    3,
    0x00000080,
    None,
)
invalid = ctypes.c_void_p(-1).value
if handle in (None, invalid):
    os.write(1, b"BLOCKED")
else:
    descriptor = msvcrt.open_osfhandle(
        int(handle), os.O_WRONLY | int(getattr(os, "O_BINARY", 0))
    )
    payload = b"x" * 1048577
    while payload:
        payload = payload[os.write(descriptor, payload):]
    os.close(descriptor)
    os.write(1, b"REOPENED")
"""
        completed, failure, captures, _projection = (
            self._recorded_gateway_call(
                command=[sys.executable, "-c", reopen_program],
                policy={
                    "timeout_seconds": 5,
                    "stdout_limit_bytes": 4096,
                    "stderr_limit_bytes": 2048,
                },
            )
        )
        self.assertEqual(len(captures), 2)
        self.assertLessEqual(captures[0].maximum_observed_size, 4096)
        self.assertLessEqual(captures[1].maximum_observed_size, 2048)
        self.assertIsNone(failure)
        assert completed is not None
        self.assertEqual(completed.stdout, b"BLOCKED")
        self.assertEqual(completed.stderr, b"")

    def test_parent_drained_capture_bounds_simultaneous_stdout_stderr_flood(
        self,
    ) -> None:
        flood_program = (
            "import os,threading;"
            "f=lambda fd,value:[os.write(fd,value*65536) for _ in range(32)];"
            "a=threading.Thread(target=f,args=(1,b'o'));"
            "b=threading.Thread(target=f,args=(2,b'e'));"
            "a.start();b.start();a.join();b.join()"
        )
        completed, failure, captures, _projection = (
            self._recorded_gateway_call(
                command=[sys.executable, "-c", flood_program],
                policy={
                    "timeout_seconds": 5,
                    "stdout_limit_bytes": 32768,
                    "stderr_limit_bytes": 16384,
                },
            )
        )
        self.assertIsNone(completed)
        self.assertIsInstance(failure, corpus.ModelCorpusError)
        self.assertRegex(str(failure), r"stdout|stderr")
        self.assertEqual(len(captures), 2)
        self.assertLessEqual(captures[0].maximum_observed_size, 32768)
        self.assertLessEqual(captures[1].maximum_observed_size, 16384)

    def test_parent_drained_capture_remains_bounded_on_timeout(self) -> None:
        completed, failure, captures, _projection = (
            self._recorded_gateway_call(
                command=[
                    sys.executable,
                    "-c",
                    (
                        "import os,time;"
                        "os.write(1,b'o'*1024);"
                        "os.write(2,b'e'*512);"
                        "time.sleep(5)"
                    ),
                ],
                policy={
                    "timeout_seconds": 0.1,
                    "stdout_limit_bytes": 4096,
                    "stderr_limit_bytes": 2048,
                },
            )
        )
        self.assertIsNone(completed)
        self.assertIsInstance(failure, corpus.ModelCorpusError)
        self.assertRegex(str(failure), r"timed out")
        self.assertEqual(len(captures), 2)
        self.assertLessEqual(captures[0].maximum_observed_size, 4096)
        self.assertLessEqual(captures[1].maximum_observed_size, 2048)

    def test_parent_drained_capture_fails_on_inherited_descendant_pipe(
        self,
    ) -> None:
        descendant_program = (
            "import os,subprocess,sys;"
            "subprocess.Popen([sys.executable,'-c',"
            "'import time;time.sleep(0.25)'],"
            "cwd=os.path.abspath(os.sep))"
        )
        completed, failure, captures, _projection = (
            self._recorded_gateway_call(
                command=[sys.executable, "-c", descendant_program],
                policy={
                    "timeout_seconds": 5,
                    "stdout_limit_bytes": 4096,
                    "stderr_limit_bytes": 2048,
                },
                projection_updates={
                    "pipe_reader_join_grace_seconds": 0.05,
                },
                settle_seconds=0.3,
            )
        )
        self.assertIsNone(completed)
        self.assertIsInstance(failure, corpus.ModelCorpusError)
        self.assertRegex(str(failure), r"inherited|pipe.*close|reader")
        self.assertEqual(len(captures), 2)
        self.assertLessEqual(captures[0].maximum_observed_size, 4096)
        self.assertLessEqual(captures[1].maximum_observed_size, 2048)

    def test_subprocess_gateway_strips_ffreport_and_inherited_loader_environment(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            cwd = root / "private-candidate-root"
            cwd.mkdir(mode=0o700)
            published = root / "published-candidate-root"
            external_report = root / "ffreport-outside-candidate.log"
            with (
                mock.patch.dict(
                    os.environ,
                    {
                        "FFREPORT": f"file={external_report}",
                        "LD_PRELOAD": "untrusted-loader",
                        "PYTHONPATH": "untrusted-pythonpath",
                        "CUDA_CACHE_PATH": str(root / "cuda-cache"),
                        "SystemRoot": str(root / "attacker-system-root"),
                        "WINDIR": str(root / "attacker-windir"),
                    },
                    clear=False,
                ),
            ):
                context = corpus._build_subprocess_context(
                    root=root,
                    cwd=cwd,
                    published_cwd=published,
                )
                completed = corpus._run_sanitized_subprocess(
                    [
                        sys.executable,
                        "-c",
                        (
                            "import json,os;"
                            "print(json.dumps({'cwd':os.getcwd(),"
                            "'environment':dict(os.environ)}))"
                        ),
                    ],
                    context=context,
                    policy_id="tool_version",
                )
            self.assertEqual(completed.returncode, 0)
            self.assertFalse(external_report.exists())
            observed = json.loads(completed.stdout.decode("utf-8"))
            environment = observed["environment"]
            normalized_environment = {
                key.casefold(): value for key, value in environment.items()
            }
            self.assertNotIn("ffreport", normalized_environment)
            self.assertNotIn("ld_preload", normalized_environment)
            self.assertNotIn("pythonpath", normalized_environment)
            self.assertNotIn("cuda_cache_path", normalized_environment)
            if os.name == "nt":
                self.assertEqual(
                    normalized_environment["systemroot"],
                    corpus._windows_directory_from_api(),
                )
                self.assertEqual(
                    normalized_environment["windir"],
                    normalized_environment["systemroot"],
                )
                self.assertNotEqual(
                    normalized_environment["systemroot"],
                    str(root / "attacker-system-root"),
                )
            self.assertEqual(Path(observed["cwd"]), cwd)
            self.assertEqual(
                normalized_environment,
                {
                    key.casefold(): value
                    for key, value in context.environment.items()
                },
            )
            self.assertEqual(
                context.descriptor["canonical_sha256"],
                sha256(canonical(context.descriptor["canonical_projection"])),
            )
            projection = context.descriptor["canonical_projection"]
            self.assertEqual(
                projection["subprocess_resource_policies"],
                corpus._SUBPROCESS_RESOURCE_POLICIES,
            )

    def test_subprocess_gateway_times_out_and_caps_each_output_stream(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            cwd = root / "private-candidate-root"
            cwd.mkdir(mode=0o700)
            published = root / "published-candidate-root"
            policy = {
                "tool_version": {
                    "timeout_seconds": 0.2,
                    "stdout_limit_bytes": 1024,
                    "stderr_limit_bytes": 1024,
                }
            }
            with mock.patch.object(
                corpus, "_SUBPROCESS_RESOURCE_POLICIES", policy
            ):
                context = corpus._build_subprocess_context(
                    root=root,
                    cwd=cwd,
                    published_cwd=published,
                )
                started = time.monotonic()
                with self.assertRaisesRegex(
                    corpus.ModelCorpusError, "tool_version.*timed out"
                ):
                    corpus._run_sanitized_subprocess(
                        [sys.executable, "-c", "import time; time.sleep(30)"],
                        context=context,
                        policy_id="tool_version",
                    )
                self.assertLess(time.monotonic() - started, 5.0)

                inherited_writer = (
                    "import subprocess,sys,time;"
                    "subprocess.Popen([sys.executable,'-c',"
                    "'import time; time.sleep(3)'],"
                    "stdout=sys.stdout,stderr=sys.stderr);"
                    "time.sleep(30)"
                )
                started = time.monotonic()
                with self.assertRaisesRegex(
                    corpus.ModelCorpusError, "tool_version.*timed out"
                ):
                    corpus._run_sanitized_subprocess(
                        [sys.executable, "-c", inherited_writer],
                        context=context,
                        policy_id="tool_version",
                    )
                self.assertLess(
                    time.monotonic() - started,
                    1.5,
                    "an inherited output handle must not extend the deadline",
                )
                # The contract deliberately does not claim process-tree
                # termination.  Let the synthetic grandchild release its
                # inherited capture-file handles before TemporaryDirectory
                # removes the Windows directory.
                time.sleep(3.1)

                for stream_name, descriptor in (
                    ("stdout", "1"),
                    ("stderr", "2"),
                ):
                    with self.subTest(stream=stream_name):
                        with self.assertRaisesRegex(
                            corpus.ModelCorpusError,
                            rf"tool_version.*{stream_name}.*1024",
                        ):
                            corpus._run_sanitized_subprocess(
                                [
                                    sys.executable,
                                    "-c",
                                    f"import os; os.write({descriptor}, b'x' * 8192)",
                                ],
                                context=context,
                                policy_id="tool_version",
                            )

    def test_subprocess_gateway_dynamic_rgb_limit_is_exact_and_prevalidated(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            cwd = root / "private-candidate-root"
            cwd.mkdir(mode=0o700)
            policy = {
                "decode": {
                    "timeout_seconds": 5,
                    "stdout_limit_bytes": "exact_expected_rgb_bytes",
                    "stdout_maximum_bytes": 4096,
                    "stderr_limit_bytes": 1024,
                }
            }
            with mock.patch.object(
                corpus, "_SUBPROCESS_RESOURCE_POLICIES", policy
            ):
                context = corpus._build_subprocess_context(
                    root=root,
                    cwd=cwd,
                    published_cwd=root / "published-candidate-root",
                )
                completed = corpus._run_sanitized_subprocess(
                    [sys.executable, "-c", "import os; os.write(1, b'r' * 4096)"],
                    context=context,
                    policy_id="decode",
                    exact_stdout_limit_bytes=4096,
                )
                self.assertEqual(completed.stdout, b"r" * 4096)

                with self.assertRaisesRegex(
                    corpus.ModelCorpusError, "decode.*stdout.*4096"
                ):
                    corpus._run_sanitized_subprocess(
                        [
                            sys.executable,
                            "-c",
                            "import os; os.write(1, b'r' * 4097)",
                        ],
                        context=context,
                        policy_id="decode",
                        exact_stdout_limit_bytes=4096,
                    )

                with mock.patch.object(corpus.subprocess, "Popen") as popen:
                    for policy_id, limit in (
                        ("missing", None),
                        ("decode", 4097),
                    ):
                        with self.subTest(policy=policy_id, limit=limit):
                            with self.assertRaises(corpus.ModelCorpusError):
                                corpus._run_sanitized_subprocess(
                                    [sys.executable, "-c", "raise SystemExit(0)"],
                                    context=context,
                                    policy_id=policy_id,
                                    exact_stdout_limit_bytes=limit,
                                )
                    popen.assert_not_called()

    def test_subprocess_gateway_reaps_direct_child_on_unexpected_base_exception(
        self,
    ) -> None:
        class InjectedLifecycleFailure(BaseException):
            pass

        class FakeProcess:
            def __init__(self, *, stdout: object, stderr: object) -> None:
                self.stdout_target = stdout
                self.stderr_target = stderr
                self.killed = False
                self.reaped = False

            def poll(self) -> int | None:
                return -9 if self.killed else None

            def kill(self) -> None:
                self.killed = True

            def wait(self, timeout: float | None = None) -> int:
                self.reaped = True
                self.killed = True
                return -9

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            cwd = root / "private-candidate-root"
            cwd.mkdir(mode=0o700)
            context = corpus._build_subprocess_context(
                root=root,
                cwd=cwd,
                published_cwd=root / "published-candidate-root",
            )
            spawned: list[FakeProcess] = []

            def spawn(*_args: object, **kwargs: object) -> FakeProcess:
                process = FakeProcess(
                    stdout=kwargs["stdout"], stderr=kwargs["stderr"]
                )
                spawned.append(process)
                return process

            primary = InjectedLifecycleFailure("injected post-spawn failure")
            with (
                mock.patch.object(corpus.subprocess, "Popen", side_effect=spawn),
                mock.patch.object(
                    corpus, "_capture_storage_size", side_effect=primary
                ),
                self.assertRaises(InjectedLifecycleFailure) as raised,
            ):
                corpus._run_sanitized_subprocess(
                    [sys.executable, "-c", "raise SystemExit(0)"],
                    context=context,
                    policy_id="tool_version",
                )

            self.assertIs(raised.exception, primary)
            self.assertEqual(len(spawned), 1)
            process = spawned[0]
            self.assertTrue(process.killed)
            self.assertTrue(process.reaped)
            self.assertIs(process.stdout_target, subprocess.PIPE)
            self.assertIs(process.stderr_target, subprocess.PIPE)

    def test_subprocess_gateway_rejects_completion_first_observed_after_deadline(
        self,
    ) -> None:
        class LateCompletedProcess:
            def __init__(self) -> None:
                self.reaped = False
                self.killed = False
                self.stdout = tempfile.TemporaryFile(mode="w+b")
                self.stderr = tempfile.TemporaryFile(mode="w+b")

            def poll(self) -> int:
                return 0

            def kill(self) -> None:
                self.killed = True

            def wait(self, timeout: float | None = None) -> int:
                self.reaped = True
                return 0

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            cwd = root / "private-candidate-root"
            cwd.mkdir(mode=0o700)
            policy = {
                "tool_version": {
                    "timeout_seconds": 5,
                    "stdout_limit_bytes": 1024,
                    "stderr_limit_bytes": 1024,
                }
            }
            process = LateCompletedProcess()
            ticks = iter((100.0, 106.0))
            with (
                mock.patch.object(
                    corpus, "_SUBPROCESS_RESOURCE_POLICIES", policy
                ),
            ):
                context = corpus._build_subprocess_context(
                    root=root,
                    cwd=cwd,
                    published_cwd=root / "published-candidate-root",
                )
                with (
                    mock.patch.object(
                        corpus.subprocess, "Popen", return_value=process
                    ),
                    mock.patch.object(
                        corpus.time,
                        "monotonic",
                        side_effect=lambda: next(ticks, 106.0),
                    ),
                    self.assertRaisesRegex(
                        corpus.ModelCorpusError, "tool_version.*timed out"
                    ),
                ):
                    corpus._run_sanitized_subprocess(
                        [sys.executable, "-c", "raise SystemExit(0)"],
                        context=context,
                        policy_id="tool_version",
                    )
            self.assertTrue(process.reaped)
            self.assertFalse(
                process.killed,
                "an already exited direct child only needs a bounded reap",
            )

    def test_subprocess_cleanup_failure_is_visible_in_sanitized_cli_error(
        self,
    ) -> None:
        class UnreapedProcess:
            def __init__(self, *, stdout: object, stderr: object) -> None:
                self.stdout_capture = stdout
                self.stderr_capture = stderr
                self.killed = False

            def poll(self) -> None:
                return None

            def kill(self) -> None:
                self.killed = True

            def wait(self, timeout: float | None = None) -> int:
                raise corpus.subprocess.TimeoutExpired("synthetic", timeout)

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            cwd = root / "private-candidate-root"
            cwd.mkdir(mode=0o700)
            context = corpus._build_subprocess_context(
                root=root,
                cwd=cwd,
                published_cwd=root / "published-candidate-root",
            )
            spawned: list[UnreapedProcess] = []

            def spawn(*_args: object, **kwargs: object) -> UnreapedProcess:
                process = UnreapedProcess(
                    stdout=kwargs["stdout"], stderr=kwargs["stderr"]
                )
                spawned.append(process)
                return process

            primary = corpus.ModelCorpusError(
                "primary failure\nwith injected control\x00text"
            )
            with (
                mock.patch.object(corpus.subprocess, "Popen", side_effect=spawn),
                mock.patch.object(
                    corpus, "_capture_storage_size", side_effect=primary
                ),
                self.assertRaises(corpus.ModelCorpusError) as raised,
            ):
                corpus._run_sanitized_subprocess(
                    [sys.executable, "-c", "raise SystemExit(0)"],
                    context=context,
                    policy_id="tool_version",
                )

            self.assertIs(raised.exception, primary)
            self.assertTrue(spawned[0].killed)
            rendered = corpus._format_model_corpus_error(primary)
            self.assertIn("ModelCorpusError: primary failure with injected", rendered)
            self.assertNotIn("\x00", rendered)
            self.assertIn(
                "DIAGNOSTIC: subprocess tool_version direct child was not reaped",
                rendered,
            )

            stderr = io.StringIO()
            with (
                mock.patch.object(corpus, "_parser") as parser,
                mock.patch.object(
                    corpus, "materialize_model_corpus", side_effect=primary
                ),
                mock.patch.object(corpus.sys, "stderr", stderr),
            ):
                parser.return_value.parse_args.return_value = mock.Mock()
                self.assertEqual(corpus.main([]), 2)
            self.assertEqual(
                stderr.getvalue().strip(), f"ERROR: {rendered}"
            )

    def test_subprocess_context_does_not_attest_descendant_output_completion(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            cwd = root / "private-candidate-root"
            cwd.mkdir(mode=0o700)
            context = corpus._build_subprocess_context(
                root=root,
                cwd=cwd,
                published_cwd=root / "published-candidate-root",
            )
            projection = context.descriptor["canonical_projection"]
            self.assertNotIn("truncation_on_success", projection)
            self.assertIs(
                projection["direct_child_output_truncation_on_success"],
                False,
            )
            self.assertIs(
                projection["descendant_output_completion_attested"], False
            )
            self.assertIs(projection["process_tree_termination_attested"], False)

    def test_frozen_dataset_config_validator_rejects_semantic_drift(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            config = root / "configs" / "datasets.yaml"
            config.parent.mkdir()
            source_payload = (
                ROOT / "configs" / "datasets.yaml"
            ).read_bytes()
            config.write_bytes(source_payload)
            document = yaml.safe_load(source_payload.decode("utf-8"))
            entries = {}
            for name in (
                "kpp_legacy_iss_v2_h264",
                "kpp_legacy_iss_v2_h265",
            ):
                entry = copy.deepcopy(document["datasets"][name])
                entry.pop("preparation")
                entries[name] = entry
            payload, descriptor = corpus._validated_frozen_dataset_config(
                root=root, receipt={"dataset_entries": entries}
            )
            self.assertEqual(payload, source_payload)
            self.assertEqual(descriptor["sha256"], sha256(source_payload))

            document["datasets"]["kpp_legacy_iss_v2_h264"]["publishable"] = True
            config.write_text(
                yaml.safe_dump(document, sort_keys=True), encoding="utf-8"
            )
            with self.assertRaisesRegex(
                corpus.ModelCorpusError, "frozen v2 dataset config authority"
            ):
                corpus._validated_frozen_dataset_config(
                    root=root, receipt={"dataset_entries": entries}
                )

    def test_local_source_set_external_pin_mismatch_fails_before_decode(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = Fixture(Path(raw))
            with self.assertRaisesRegex(
                corpus.ModelCorpusError, "source set.*external pin"
            ):
                fixture.run(
                    output_name="source-pin-blocked",
                    expected_source_set_sha256="0" * 64,
                )
            self.assertEqual(fixture.decode_calls, 0)
            self.assertFalse(
                (fixture.root / "staging" / "source-pin-blocked").exists()
            )

    def test_materializer_source_swap_under_custody_cannot_publish(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = Fixture(Path(raw))
            source_copy = (
                fixture.root
                / "candidate_inputs"
                / Path(corpus.__file__).name
            )
            source_copy.write_bytes(Path(corpus.__file__).read_bytes())
            original_decode = fixture.decode
            attacked = False

            def decode_with_source_swap(
                media: corpus.HeldMedia,
                indexes: tuple[int, ...],
                probe: corpus.MediaProbe,
                tool: Path,
            ) -> dict[int, corpus.DecodedFrame]:
                nonlocal attacked
                result = original_decode(media, indexes, probe, tool)
                if not attacked:
                    attacked = True
                    replacement = source_copy.with_suffix(".replacement.py")
                    replacement.write_bytes(source_copy.read_bytes())
                    try:
                        os.replace(replacement, source_copy)
                    except PermissionError as exc:
                        replacement.unlink(missing_ok=True)
                        raise corpus.ModelCorpusError(
                            "materializer source custody prevented swap"
                        ) from exc
                return result

            adapters = fixture.adapters()
            attacked_adapters = corpus._TestAdapters(
                probe=adapters.probe,
                decode=decode_with_source_swap,
                preprocess=adapters.preprocess,
                version_reader=adapters.version_reader,
            )
            with (
            mock.patch.object(corpus, "__file__", str(source_copy)),
            self.assertRaisesRegex(
                corpus.ModelCorpusError,
                r"(?:materializer source|local source component materializer).*(?:identity|custody)|prevented",
            ),
        ):
                fixture.run(
                    output_name="source-swap-blocked",
                    expected_source_set_sha256=(
                        corpus._source_set_external_pin_for_tests()
                    ),
                    test_adapters=attacked_adapters,
                )
            self.assertTrue(attacked)
            self.assertFalse(
                (fixture.root / "staging" / "source-swap-blocked").exists()
            )

    def test_published_leaf_mutation_after_earlier_check_cannot_return_success(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = Fixture(Path(raw))
            target = fixture.root / "staging" / "leaf-race-blocked"
            original_read_bytes = Path.read_bytes
            checked: list[Path] = []
            mutated = False

            def read_with_interleaved_mutation(path: Path) -> bytes:
                nonlocal mutated
                payload = original_read_bytes(path)
                if path.parent == target and path.name != corpus.RECEIPT_NAME:
                    if checked and not mutated:
                        mutated = True
                        try:
                            with checked[0].open("wb") as stream:
                                stream.write(b"post-check mutation")
                        except PermissionError as exc:
                            raise corpus.ModelCorpusError(
                                "held published identity prevented leaf mutation"
                            ) from exc
                    checked.append(path)
                return payload

            with (
                mock.patch.object(Path, "read_bytes", read_with_interleaved_mutation),
                self.assertRaisesRegex(
                    corpus.ModelCorpusError, "published.*drift|held.*drift|identity"
                ),
            ):
                fixture.run(output_name="leaf-race-blocked")
            self.assertTrue(mutated, "attack hook did not run")

    def test_rogue_sibling_after_postpublish_scan_cannot_return_success(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = Fixture(Path(raw))
            target = fixture.root / "staging" / "rogue-sibling-blocked"
            original = corpus._validate_private_publication_set
            attacked = False

            def validate_then_inject_rogue(
                root: Path, paths: list[Path]
            ) -> None:
                nonlocal attacked
                original(root, paths)
                if root == target and not attacked:
                    attacked = True
                    try:
                        (target / "rogue.bin").write_bytes(b"rogue")
                    except PermissionError as exc:
                        raise corpus.ModelCorpusError(
                            "published namespace custody prevented rogue sibling"
                        ) from exc

            with (
                mock.patch.object(
                    corpus,
                    "_validate_private_publication_set",
                    side_effect=validate_then_inject_rogue,
                ),
                self.assertRaisesRegex(
                    corpus.ModelCorpusError,
                    "namespace|file set|rogue|candidate.*exact",
                ),
            ):
                fixture.run(output_name="rogue-sibling-blocked")
            self.assertTrue(attacked, "rogue sibling attack hook did not run")

    def test_caller_cannot_self_authorize_an_alternative_v2_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = Fixture(Path(raw))
            with self.assertRaisesRegex(
                corpus.ModelCorpusError, "frozen.*receipt|receipt.*authority"
            ):
                corpus._require_frozen_materialization_receipt_pins(
                    expected_size_bytes=len(fixture.receipt_payload),
                    expected_file_sha256=sha256(fixture.receipt_payload),
                    expected_self_sha256=str(
                        fixture.receipt["materialization_receipt_sha256"]
                    ),
                )
            self.assertEqual(fixture.decode_calls, 0)
            self.assertEqual(list((fixture.root / "staging").iterdir()), [])

    def test_full_v3_parity_contract_drift_fails_before_decode_or_output(self) -> None:
        def duplicate_key(fixture: Fixture) -> None:
            with fixture.parity_manifest_path.open("a", encoding="utf-8") as stream:
                stream.write("schema_version: 3\n")

        def mutate(
            path: tuple[str, ...], value: object
        ):
            def apply(fixture: Fixture) -> None:
                manifest = fixture._parity_manifest()
                target: dict[str, object] = manifest
                for component in path[:-1]:
                    child = target[component]
                    assert type(child) is dict
                    target = child
                target[path[-1]] = value
                fixture.replace_parity_manifest(manifest)

            return apply

        cases = {
            "duplicate_key": duplicate_key,
            "normalization_scale": mutate(
                ("preprocessing_contract", "normalization_scale"), 0.5
            ),
            "normalization_mean": mutate(
                ("preprocessing_contract", "normalization_mean"), [0.0, 0.0, 0.0]
            ),
            "normalization_std": mutate(
                ("preprocessing_contract", "normalization_std"), [1.0, 1.0, 1.0]
            ),
            "execution_shape": mutate(
                (
                    "source_registry",
                    "resnet18_v1_7",
                    "input",
                    "execution_shape",
                ),
                [2, 3, 224, 224],
            ),
            "slot_id": mutate(
                ("workload_slots", "plate_number", "slot_id"), "opaque_rn34"
            ),
            "source_ref": mutate(
                ("workload_slots", "plate_number", "source_ref"), "resnet34_v1_7"
            ),
        }
        for label, apply in cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as raw:
                fixture = Fixture(Path(raw))
                apply(fixture)
                with self.assertRaisesRegex(
                    corpus.ModelCorpusError, "model parity manifest"
                ):
                    fixture.run(output_name=f"parity-{label}-blocked")
                self.assertEqual(fixture.decode_calls, 0)
                self.assertFalse(
                    (fixture.root / "staging" / f"parity-{label}-blocked").exists()
                )

    def test_materializes_protected_structurally_nonpromotable_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = Fixture(Path(raw))
            receipt = fixture.run()
            target = fixture.root / "staging" / "model-corpus-candidate"
            self.assertTrue(target.is_dir())
            self.assertEqual(
                list((fixture.root / "staging").glob(".*.failed")),
                [],
                "successful materialization must not create a failure quarantine",
            )
            if os.name != "nt":
                self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o700)
            self.assertEqual(receipt["artifact_kind"], corpus.RECEIPT_ARTIFACT_KIND)
            self.assertIs(receipt["promotable"], False)
            self.assertIs(receipt["publication_authorized"], False)
            self.assertIs(receipt["evidence_accepted"], False)
            self.assertEqual(receipt["pi_approval_status"], "required")
            self.assertEqual(fixture.decode_calls, 4)
            self.assertEqual(
                [path for path in target.iterdir() if path.is_dir()],
                [],
                "authoritative candidate namespace must be flat under held root",
            )

            candidate_receipt = json.loads(
                (target / corpus.RECEIPT_NAME).read_text("ascii")
            )
            self.assertEqual(candidate_receipt, receipt)
            unsigned = dict(receipt)
            unsigned.pop("candidate_receipt_sha256")
            self.assertEqual(
                receipt["candidate_receipt_sha256"],
                hashlib.sha256(corpus.CANDIDATE_RECEIPT_DOMAIN + canonical(unsigned)).hexdigest(),
            )
            outputs = receipt["outputs"]
            self.assertGreaterEqual(len(outputs), 19)
            for descriptor in outputs:
                self.assertEqual(
                    len(Path(descriptor["path"]).relative_to("staging/model-corpus-candidate").parts),
                    1,
                )
                payload = (fixture.root / descriptor["path"]).read_bytes()
                self.assertEqual(len(payload), descriptor["size_bytes"])
                self.assertEqual(sha256(payload), descriptor["sha256"])

            for branch in corpus.BRANCHES:
                documents = {}
                for role in ("calibration", "evaluation"):
                    path = target / f"corpus_{branch}_{role}.json"
                    document = json.loads(path.read_text("ascii"))
                    documents[role] = document
                    self.assertEqual(
                        document["artifact_kind"], corpus.CORPUS_CANDIDATE_ARTIFACT_KIND
                    )
                    self.assertNotEqual(
                        document["artifact_kind"], "checkpoint_model_parity_corpus"
                    )
                    self.assertIs(document["promotable"], False)
                    self.assertIs(document["publication_authorized"], False)
                    self.assertIs(document["evidence_accepted"], False)
                    self.assertEqual(document["sample_count"], 30)
                    self.assertEqual(
                        document["samples_sha256"], sha256(canonical(document["samples"]))
                    )
                    self.assertEqual(
                        {sample["codec"] for sample in document["samples"]},
                        {"h264", "h265"},
                    )
                    for sample in document["samples"]:
                        for key in ("raw_frame", "preprocessed_tensor"):
                            segment = sample[key]
                            bundle = (fixture.root / segment["path"]).read_bytes()
                            start = segment["offset_bytes"]
                            end = start + segment["segment_size_bytes"]
                            self.assertEqual(
                                sha256(bundle[start:end]), segment["segment_sha256"]
                            )
                self.assertTrue(
                    {
                        sample["physical_sample_sha256"]
                        for sample in documents["calibration"]["samples"]
                    }.isdisjoint(
                        sample["physical_sample_sha256"]
                        for sample in documents["evaluation"]["samples"]
                    )
                )

            claims = receipt["claims"]
            self.assertIs(claims["topology_load_proxy_candidate_only"], True)
            self.assertIs(
                claims["materializer_source_bytes_externally_pinned_and_held"],
                True,
            )
            for true_claim in (
                "local_python_source_set_externally_pinned_and_held",
                "subprocess_environment_sanitized_and_bound",
                "subprocess_private_cwd_bound",
                "directory_namespace_point_in_time_validated",
            ):
                self.assertIs(claims[true_claim], True)
            for false_claim in (
                "accuracy",
                "representative",
                "production_semantics",
                "statistical_independence",
                "model_acceptance",
                "runtime_acceptance",
                "executed_python_bytecode_attested",
                "launcher_execution_attested",
                "subprocess_dynamic_library_closure_attested",
                "directory_namespace_immutability_attested",
                "future_candidate_tree_immutability_attested",
            ):
                self.assertIs(claims[false_claim], False)

            materializer_pin = receipt["tool_pins"]["materializer"]
            preprocessor_pin = receipt["tool_pins"]["preprocessor"]
            self.assertEqual(materializer_pin["sha256"], preprocessor_pin["sha256"])
            self.assertEqual(
                materializer_pin["source_snapshot"],
                preprocessor_pin["source_snapshot"],
            )
            snapshot = materializer_pin["source_snapshot"]
            snapshot_payload = (fixture.root / snapshot["path"]).read_bytes()
            self.assertEqual(sha256(snapshot_payload), materializer_pin["sha256"])
            self.assertIs(materializer_pin["executed_python_bytecode_attested"], False)
            self.assertIs(materializer_pin["launcher_execution_attested"], False)

            source_set = receipt["tool_pins"]["local_source_set"]
            self.assertEqual(
                {item["component"] for item in source_set["components"]},
                {
                    "materializer",
                    "benchmark_contract",
                    "checkpoint_model_parity",
                    "extract_kpp_legacy_iss",
                    "kpp_legacy_iss_v2_manifest",
                    "backend_runtime_grant",
                    "model_parity_grant",
                    "checkpoint_acceptance_metadata_binding",
                    "backend_publication_output_receipt",
                    "formal_aw_heft_reference",
                    "publication_acceptance_evidence",
                    "backend_publication_dispatch",
                },
            )
            self.assertEqual(
                source_set["canonical_aggregate_sha256"],
                corpus._source_set_external_pin_for_tests(),
            )
            for component in source_set["components"]:
                snapshot = component["source_snapshot"]
                payload = (fixture.root / snapshot["path"]).read_bytes()
                self.assertEqual(len(payload), component["size_bytes"])
                self.assertEqual(sha256(payload), component["sha256"])

    def test_external_receipt_pin_mismatch_fails_before_decode_or_output(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = Fixture(Path(raw))
            with self.assertRaisesRegex(corpus.ModelCorpusError, "receipt.*external pin"):
                corpus._materialize_model_corpus_impl(
                    project_root=fixture.root,
                    materialization_receipt=fixture.receipt_path,
                    expected_materialization_receipt_size_bytes=len(fixture.receipt_payload),
                    expected_materialization_receipt_sha256="0" * 64,
                    expected_materialization_receipt_self_sha256=str(
                        fixture.receipt["materialization_receipt_sha256"]
                    ),
                    model_parity_manifest=fixture.parity_manifest_path,
                    expected_model_parity_manifest_sha256=sha256(
                        fixture.parity_manifest_path.read_bytes()
                    ),
                    ffmpeg=fixture.ffmpeg,
                    expected_ffmpeg_sha256=sha256(fixture.ffmpeg.read_bytes()),
                    expected_ffmpeg_version_sha256=sha256(
                        fixture.version_bytes[fixture.ffmpeg]
                    ),
                    ffprobe=fixture.ffprobe,
                    expected_ffprobe_sha256=sha256(fixture.ffprobe.read_bytes()),
                    expected_ffprobe_version_sha256=sha256(
                        fixture.version_bytes[fixture.ffprobe]
                    ),
                    expected_source_set_sha256=(
                        corpus._source_set_external_pin_for_tests()
                    ),
                    output_dir=fixture.root / "staging" / "blocked",
                    test_adapters=fixture.adapters(),
                )
            self.assertEqual(fixture.decode_calls, 0)
            self.assertFalse((fixture.root / "staging" / "blocked").exists())

    def test_hardlinked_installed_media_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = Fixture(Path(raw))
            source = fixture.root / MEDIA_PATHS[("h264", "front_gate")]
            alias = source.with_name("hardlink-alias.mp4")
            try:
                os.link(source, alias)
            except OSError as exc:
                self.skipTest(f"hardlinks unavailable: {exc}")
            with self.assertRaisesRegex(corpus.ModelCorpusError, "hardlink"):
                fixture.run(output_name="hardlink-blocked")
            self.assertFalse((fixture.root / "staging" / "hardlink-blocked").exists())

    def test_linked_or_reparse_installed_media_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = Fixture(Path(raw))
            source = (fixture.root / MEDIA_PATHS[("h265", "underbody")]).absolute()
            original = corpus._is_link

            def injected_link(path: Path) -> bool:
                return path.absolute() == source or original(path)

            with (
                mock.patch.object(corpus, "_is_link", side_effect=injected_link),
                self.assertRaisesRegex(corpus.ModelCorpusError, "link|reparse"),
            ):
                fixture.run(output_name="link-blocked")
            self.assertFalse((fixture.root / "staging" / "link-blocked").exists())

    def test_source_path_swap_during_decode_is_rejected_without_publication(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = Fixture(Path(raw))
            original_decode = fixture.decode
            swapped = False

            def decode_with_swap(
                media: corpus.HeldMedia,
                indexes: tuple[int, ...],
                probe: corpus.MediaProbe,
                tool: Path,
            ) -> dict[int, corpus.DecodedFrame]:
                nonlocal swapped
                result = original_decode(media, indexes, probe, tool)
                if not swapped:
                    swapped = True
                    replacement = media.path.with_name("replacement.mp4")
                    replacement.write_bytes(media.path.read_bytes())
                    try:
                        os.replace(replacement, media.path)
                    except PermissionError:
                        replacement.unlink(missing_ok=True)
                        raise corpus.ModelCorpusError(
                            "injected path swap was prevented by source custody"
                        )
                return result

            adapters = fixture.adapters()
            adapters = corpus._TestAdapters(
                probe=adapters.probe,
                decode=decode_with_swap,
                preprocess=adapters.preprocess,
                version_reader=adapters.version_reader,
            )
            with self.assertRaisesRegex(
                corpus.ModelCorpusError, "changed|identity|prevented"
            ):
                corpus._materialize_model_corpus_impl(
                    project_root=fixture.root,
                    materialization_receipt=fixture.receipt_path,
                    expected_materialization_receipt_size_bytes=len(fixture.receipt_payload),
                    expected_materialization_receipt_sha256=sha256(fixture.receipt_payload),
                    expected_materialization_receipt_self_sha256=str(
                        fixture.receipt["materialization_receipt_sha256"]
                    ),
                    model_parity_manifest=fixture.parity_manifest_path,
                    expected_model_parity_manifest_sha256=sha256(
                        fixture.parity_manifest_path.read_bytes()
                    ),
                    ffmpeg=fixture.ffmpeg,
                    expected_ffmpeg_sha256=sha256(fixture.ffmpeg.read_bytes()),
                    expected_ffmpeg_version_sha256=sha256(
                        fixture.version_bytes[fixture.ffmpeg]
                    ),
                    ffprobe=fixture.ffprobe,
                    expected_ffprobe_sha256=sha256(fixture.ffprobe.read_bytes()),
                    expected_ffprobe_version_sha256=sha256(
                        fixture.version_bytes[fixture.ffprobe]
                    ),
                    expected_source_set_sha256=(
                        corpus._source_set_external_pin_for_tests()
                    ),
                    output_dir=fixture.root / "staging" / "swap-blocked",
                    test_adapters=adapters,
                )
            self.assertFalse((fixture.root / "staging" / "swap-blocked").exists())

    def test_codec_frame_count_drift_requires_scientific_decision(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = Fixture(Path(raw))

            def mismatched_probe(
                media: corpus.HeldMedia, tool: Path
            ) -> corpus.MediaProbe:
                result = fixture.probe(media, tool)
                if media.codec == "h265" and media.role == "underbody":
                    return corpus.MediaProbe(
                        **{
                            **result.__dict__,
                            "frame_count": 119,
                            "frame_pts": result.frame_pts[:119],
                        }
                    )
                return result

            adapters = fixture.adapters()
            adapters = corpus._TestAdapters(
                probe=mismatched_probe,
                decode=adapters.decode,
                preprocess=adapters.preprocess,
                version_reader=adapters.version_reader,
            )
            with self.assertRaisesRegex(
                corpus.ScientificChoiceRequired,
                "frame counts.*approval|scientific",
            ):
                corpus._materialize_model_corpus_impl(
                    project_root=fixture.root,
                    materialization_receipt=fixture.receipt_path,
                    expected_materialization_receipt_size_bytes=len(fixture.receipt_payload),
                    expected_materialization_receipt_sha256=sha256(fixture.receipt_payload),
                    expected_materialization_receipt_self_sha256=str(
                        fixture.receipt["materialization_receipt_sha256"]
                    ),
                    model_parity_manifest=fixture.parity_manifest_path,
                    expected_model_parity_manifest_sha256=sha256(
                        fixture.parity_manifest_path.read_bytes()
                    ),
                    ffmpeg=fixture.ffmpeg,
                    expected_ffmpeg_sha256=sha256(fixture.ffmpeg.read_bytes()),
                    expected_ffmpeg_version_sha256=sha256(
                        fixture.version_bytes[fixture.ffmpeg]
                    ),
                    ffprobe=fixture.ffprobe,
                    expected_ffprobe_sha256=sha256(fixture.ffprobe.read_bytes()),
                    expected_ffprobe_version_sha256=sha256(
                        fixture.version_bytes[fixture.ffprobe]
                    ),
                    expected_source_set_sha256=(
                        corpus._source_set_external_pin_for_tests()
                    ),
                    output_dir=fixture.root / "staging" / "drift-blocked",
                    test_adapters=adapters,
                )
            self.assertFalse((fixture.root / "staging" / "drift-blocked").exists())


if __name__ == "__main__":
    unittest.main()
