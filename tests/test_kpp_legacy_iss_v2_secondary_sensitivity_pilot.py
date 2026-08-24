from __future__ import annotations

import contextlib
import copy
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import kpp_legacy_iss_v2_secondary_sensitivity_decision as decision
import kpp_legacy_iss_v2_secondary_sensitivity_pilot as pilot


class KppLegacyIssV2SecondarySensitivityPilotTests(unittest.TestCase):
    def _sample(
        self,
        *,
        branch: str,
        source_role: str,
        corpus_role: str,
        ordinal: int,
        output_root: str,
        dataset_aggregate_sha256: str,
    ) -> dict[str, object]:
        codec = "h264" if ordinal % 2 == 0 else "h265"
        stratum_index = 2 * ordinal + (0 if corpus_role == "calibration" else 1)
        frame_index = (300 if source_role == "front_gate" else 900) + stratum_index
        source_pts = frame_index
        source_time_base = "1/600"
        pts_ns = (source_pts * 1_000_000_000) // 600
        dataset_file_sha = hashlib.sha256(
            f"dataset:{codec}:{source_role}".encode("ascii")
        ).hexdigest()
        raw_segment_sha = hashlib.sha256(
            f"raw:{source_role}:{corpus_role}:{codec}:{ordinal}".encode("ascii")
        ).hexdigest()
        tensor_segment_sha = hashlib.sha256(
            f"tensor:{source_role}:{corpus_role}:{codec}:{ordinal}".encode("ascii")
        ).hexdigest()
        bundle_ordinal = 2 * (ordinal // 2) + (
            0 if corpus_role == "calibration" else 1
        )
        width, height = (
            (1920, 1080) if source_role == "front_gate" else (1700, 236)
        )
        raw_segment_bytes = width * height * 3
        physical_payload = {
            "dataset_aggregate_sha256": dataset_aggregate_sha256,
            "dataset_file_sha256": dataset_file_sha,
            "codec": codec,
            "source_role": source_role,
            "stream_index": 0,
            "frame_index": frame_index,
            "source_pts": source_pts,
            "source_time_base": source_time_base,
            "pts_ns": pts_ns,
            "decoded_frame_sha256": raw_segment_sha,
        }
        return {
            "sample_id": (
                f"kpp-v2-candidate.{branch}.{corpus_role}.{codec}.{ordinal:02d}"
            ),
            "physical_sample_sha256": hashlib.sha256(
                pilot.canonical_line(physical_payload)
            ).hexdigest(),
            "branch": branch,
            "source_role": source_role,
            "corpus_role": corpus_role,
            "stratum_index": stratum_index,
            "dataset_file_id": f"kpp-legacy-iss-v2-{codec}-{source_role}",
            "dataset_file_sha256": dataset_file_sha,
            "codec": codec,
            "file_index": 1 if source_role == "front_gate" else 0,
            "stream_index": 0,
            "frame_index": frame_index,
            "source_pts": source_pts,
            "source_time_base": source_time_base,
            "pts_ns": pts_ns,
            "input_sha256": raw_segment_sha,
            "preprocessed_tensor_sha256": tensor_segment_sha,
            "raw_frame": {
                "path": f"{output_root}/raw_{codec}_{source_role}.rgb24.bin",
                "size_bytes": 30 * raw_segment_bytes,
                "sha256": hashlib.sha256(
                    f"raw-bundle:{codec}:{source_role}".encode("ascii")
                ).hexdigest(),
                "offset_bytes": bundle_ordinal * raw_segment_bytes,
                "segment_size_bytes": raw_segment_bytes,
                "segment_sha256": raw_segment_sha,
                "encoding": "raw_bytes_v1",
                "dtype": "uint8",
                "shape": [height, width, 3],
                "layout": "HWC",
                "color_order": "RGB",
            },
            "preprocessed_tensor": {
                "path": f"{output_root}/tensor_{codec}_{source_role}.f32.bin",
                "size_bytes": 30 * pilot.TENSOR_SEGMENT_BYTES,
                "sha256": hashlib.sha256(
                    f"bundle:{codec}:{source_role}".encode("ascii")
                ).hexdigest(),
                "offset_bytes": bundle_ordinal * pilot.TENSOR_SEGMENT_BYTES,
                "segment_size_bytes": pilot.TENSOR_SEGMENT_BYTES,
                "segment_sha256": tensor_segment_sha,
                "encoding": "raw_f32_le_c_contiguous_v1",
                "dtype": "float32",
                "shape": [1, 3, 224, 224],
                "layout": "NCHW",
                "preprocessing_contract_sha256": "3" * 64,
            },
        }

    def _fixture(self, root: Path) -> tuple[Path, str, str]:
        config_dir = root / "configs"
        candidate = root / "staging" / "synthetic-candidate"
        config_dir.mkdir(parents=True)
        candidate.mkdir(parents=True)
        decision_path = config_dir / decision.DECISION_PATH.name
        decision_path.write_bytes(
            decision.canonical_bytes(decision.expected_decision()) + b"\n"
        )

        output_root = "staging/synthetic-candidate"
        dataset_aggregate = "2" * 64
        dataset_descriptor = {
            "role": "candidate dataset manifest",
            "path": f"{output_root}/dataset_manifest.json",
            "size_bytes": 1,
            "sha256": "4" * 64,
        }
        sampling_rule = decision.expected_decision()["sampling_rule"]
        sampling_sha = hashlib.sha256(pilot.canonical_line(sampling_rule)).hexdigest()
        producer = {
            "candidate_only": True,
            "sampling_rule_sha256": sampling_sha,
            "preprocessing_contract_sha256": "3" * 64,
            "materialization_receipt_sha256": "5" * 64,
            "materialization_receipt_self_sha256": "6" * 64,
            "model_parity_manifest_sha256": "7" * 64,
            "tool_pins_sha256": "8" * 64,
        }

        outputs: list[dict[str, object]] = []
        for branch in pilot.BRANCHES:
            binding = pilot.BRANCH_BINDINGS[branch]
            for corpus_role in pilot.CORPUS_ROLES:
                samples = [
                    self._sample(
                        branch=branch,
                        source_role=binding["source_role"],
                        corpus_role=corpus_role,
                        ordinal=ordinal,
                        output_root=output_root,
                        dataset_aggregate_sha256=dataset_aggregate,
                    )
                    for ordinal in range(30)
                ]
                corpus = {
                    "schema_version": 1,
                    "artifact_kind": pilot.CORPUS_ARTIFACT_KIND,
                    "branch": branch,
                    "workload_slot_id": binding["workload_slot_id"],
                    "source_ref": binding["source_ref"],
                    "source_role": binding["source_role"],
                    "semantic_claim": "topology_load_proxy_candidate_only",
                    "corpus_role": corpus_role,
                    "promotable": False,
                    "publication_authorized": False,
                    "evidence_accepted": False,
                    "pi_approval_status": "required",
                    "dataset_manifest": dataset_descriptor,
                    "dataset_aggregate_sha256": dataset_aggregate,
                    "producer_contract": producer,
                    "sample_count": 30,
                    "samples": samples,
                    "samples_sha256": hashlib.sha256(
                        pilot.canonical_line(samples)
                    ).hexdigest(),
                    "claims": copy.deepcopy(pilot.CANDIDATE_CLAIMS),
                }
                payload = pilot.canonical_line(corpus)
                path = candidate / f"corpus_{branch}_{corpus_role}.json"
                path.write_bytes(payload)
                outputs.append(
                    {
                        "role": f"{branch}/{corpus_role} corpus candidate",
                        "path": f"{output_root}/{path.name}",
                        "size_bytes": len(payload),
                        "sha256": hashlib.sha256(payload).hexdigest(),
                    }
                )

        for codec in pilot.CODECS:
            for source_role in ("front_gate", "underbody"):
                width, height = (
                    (1920, 1080)
                    if source_role == "front_gate"
                    else (1700, 236)
                )
                raw_segment_bytes = width * height * 3
                outputs.extend(
                    (
                        {
                            "role": f"{codec}/{source_role} decoded RGB bundle",
                            "path": (
                                f"{output_root}/raw_{codec}_{source_role}.rgb24.bin"
                            ),
                            "size_bytes": 30 * raw_segment_bytes,
                            "sha256": hashlib.sha256(
                                f"raw-bundle:{codec}:{source_role}".encode("ascii")
                            ).hexdigest(),
                        },
                        {
                            "role": (
                                f"{codec}/{source_role} preprocessed tensor bundle"
                            ),
                            "path": (
                                f"{output_root}/tensor_{codec}_{source_role}.f32.bin"
                            ),
                            "size_bytes": 30 * pilot.TENSOR_SEGMENT_BYTES,
                            "sha256": hashlib.sha256(
                                f"bundle:{codec}:{source_role}".encode("ascii")
                            ).hexdigest(),
                        },
                    )
                )

        outputs.sort(key=lambda item: str(item["path"]))
        branch_mapping = {
            branch: {
                "branch": branch,
                **copy.deepcopy(binding),
                "semantic_claim": "topology_load_proxy_only",
                "tensor_name": "data",
            }
            for branch, binding in pilot.BRANCH_BINDINGS.items()
        }
        receipt: dict[str, object] = {
            "schema_version": 1,
            "artifact_kind": pilot.RECEIPT_ARTIFACT_KIND,
            "generation_id": "kpp_legacy_iss_v2",
            "status": "materialized_nonpromotable_candidate",
            "promotable": False,
            "publication_authorized": False,
            "evidence_accepted": False,
            "pi_approval_status": "required",
            "output_root": output_root,
            "source_materialization_receipt": {},
            "source_model_parity_manifest_sha256": "7" * 64,
            "source_dataset_config": {},
            "dataset_aggregate_sha256": dataset_aggregate,
            "branch_source_mapping": branch_mapping,
            "sampling_rule": sampling_rule,
            "sampling_rule_sha256": sampling_sha,
            "tool_pins": {},
            "outputs": outputs,
            "claims": copy.deepcopy(pilot.CANDIDATE_CLAIMS),
            "authoritative_commit_record": {
                "path": f"{output_root}/authoritative_commit.json",
                "size_bytes": 1,
                "sha256": "9" * 64,
            },
        }
        receipt["candidate_receipt_sha256"] = pilot.candidate_receipt_self_sha(
            receipt
        )
        receipt_payload = pilot.canonical_line(receipt)
        (candidate / pilot.RECEIPT_NAME).write_bytes(receipt_payload)
        return (
            candidate,
            hashlib.sha256(receipt_payload).hexdigest(),
            str(receipt["candidate_receipt_sha256"]),
        )

    def _reseal_corpus_mutation(
        self,
        candidate: Path,
        *,
        filename: str,
        mutate: object,
    ) -> tuple[str, str]:
        receipt_path = candidate / pilot.RECEIPT_NAME
        receipt = json.loads(receipt_path.read_text(encoding="ascii"))
        corpus_path = candidate / filename
        corpus = json.loads(corpus_path.read_text(encoding="ascii"))
        mutate(corpus)
        corpus["samples_sha256"] = hashlib.sha256(
            pilot.canonical_line(corpus["samples"])
        ).hexdigest()
        corpus_payload = pilot.canonical_line(corpus)
        corpus_path.write_bytes(corpus_payload)
        logical_suffix = f"/{filename}"
        descriptor = next(
            item
            for item in receipt["outputs"]
            if item["path"].endswith(logical_suffix)
        )
        descriptor["size_bytes"] = len(corpus_payload)
        descriptor["sha256"] = hashlib.sha256(corpus_payload).hexdigest()
        receipt["candidate_receipt_sha256"] = pilot.candidate_receipt_self_sha(
            receipt
        )
        receipt_payload = pilot.canonical_line(receipt)
        receipt_path.write_bytes(receipt_payload)
        return (
            hashlib.sha256(receipt_payload).hexdigest(),
            str(receipt["candidate_receipt_sha256"]),
        )

    def _reseal_receipt_mutation(
        self, candidate: Path, *, mutate: object
    ) -> tuple[str, str]:
        receipt_path = candidate / pilot.RECEIPT_NAME
        receipt = json.loads(receipt_path.read_text(encoding="ascii"))
        mutate(receipt)
        receipt["candidate_receipt_sha256"] = pilot.candidate_receipt_self_sha(
            receipt
        )
        payload = pilot.canonical_line(receipt)
        receipt_path.write_bytes(payload)
        return (
            hashlib.sha256(payload).hexdigest(),
            str(receipt["candidate_receipt_sha256"]),
        )

    def _physical_sample_sha(
        self, sample: dict[str, object], dataset_aggregate_sha256: str
    ) -> str:
        payload = {
            "dataset_aggregate_sha256": dataset_aggregate_sha256,
            "dataset_file_sha256": sample["dataset_file_sha256"],
            "codec": sample["codec"],
            "source_role": sample["source_role"],
            "stream_index": sample["stream_index"],
            "frame_index": sample["frame_index"],
            "source_pts": sample["source_pts"],
            "source_time_base": sample["source_time_base"],
            "pts_ns": sample["pts_ns"],
            "decoded_frame_sha256": sample["input_sha256"],
        }
        return hashlib.sha256(pilot.canonical_line(payload)).hexdigest()

    def test_exact_synthetic_contract_builds_one_deterministic_plan(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project_root = Path(raw)
            candidate, receipt_file_sha, receipt_self_sha = self._fixture(project_root)
            kwargs = {
                "project_root": project_root,
                "decision_path": decision.DECISION_PATH,
                "candidate_root": candidate.relative_to(project_root),
                "role": "secondary",
                "expected_receipt_file_sha256": receipt_file_sha,
                "expected_receipt_self_sha256": receipt_self_sha,
            }
            first = pilot.build_pilot_plan(**kwargs)
            second = pilot.build_pilot_plan(**kwargs)

        self.assertEqual(first, second)
        self.assertEqual(first["artifact_kind"], pilot.PLAN_ARTIFACT_KIND)
        self.assertEqual(first["role"], "secondary")
        self.assertEqual(len(first["requests"]), 8)
        self.assertEqual(
            [request["sample_id"] for request in first["requests"]],
            [
                f"kpp-v2-candidate.{branch}.calibration.{codec}.{ordinal:02d}"
                for branch in pilot.BRANCHES
                for codec, ordinal in (("h264", 0), ("h265", 1))
            ],
        )
        self.assertEqual(
            {request["model"]["engine_sha256"] for request in first["requests"]},
            {
                value["engine_sha256"]
                for value in pilot.TENSORRT_ENGINE_PINS.values()
            },
        )
        self.assertEqual(first["runtime"]["worker_image_id"], pilot.TENSORRT_IMAGE_ID)
        self.assertEqual(first["runtime"]["gpu_uuid"], pilot.TENSORRT_GPU_UUID)
        self.assertTrue(
            {
                "publication_ready",
                "publication_authorized",
                "publication_capable",
                "publishable",
                "accepted_evidence",
                "accepted_evidence_written",
                "accepted_measurement_evidence_emitted",
                "evidence_accepted",
                "benchmark",
                "promotable",
                "result_accepted",
            }.issubset(set(pilot.FAIL_CLOSED_FLAGS))
        )
        for key in pilot.FAIL_CLOSED_FLAGS:
            self.assertIs(first[key], False, key)

    def test_missing_exact_image_is_blocked_exit_78_without_spawn_or_write(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project_root = Path(raw)
            candidate, receipt_file_sha, receipt_self_sha = self._fixture(project_root)
            before = sorted(
                path.relative_to(project_root).as_posix()
                for path in project_root.rglob("*")
            )
            stdout = io.StringIO()
            argv = [
                "--project-root",
                str(project_root),
                "--candidate-root",
                candidate.relative_to(project_root).as_posix(),
                "--role",
                "sensitivity",
                "--expected-receipt-file-sha256",
                receipt_file_sha,
                "--expected-receipt-self-sha256",
                receipt_self_sha,
            ]
            with mock.patch.object(
                subprocess, "run", side_effect=AssertionError("subprocess forbidden")
            ), mock.patch.object(
                subprocess, "Popen", side_effect=AssertionError("subprocess forbidden")
            ), mock.patch.object(
                Path, "write_bytes", side_effect=AssertionError("write forbidden")
            ), mock.patch.object(
                Path, "write_text", side_effect=AssertionError("write forbidden")
            ), contextlib.redirect_stdout(stdout):
                status = pilot.main(argv)
            after = sorted(
                path.relative_to(project_root).as_posix()
                for path in project_root.rglob("*")
            )

        self.assertEqual(status, 78)
        self.assertEqual(after, before)
        assessment = json.loads(stdout.getvalue())
        self.assertEqual(assessment["artifact_kind"], pilot.ASSESSMENT_ARTIFACT_KIND)
        self.assertEqual(
            assessment["status"], "blocked_missing_exact_pinned_docker_image"
        )
        self.assertEqual(assessment["required_image_id"], pilot.TENSORRT_IMAGE_ID)
        self.assertEqual(assessment["available_image_ids"], [])
        for key in pilot.FAIL_CLOSED_FLAGS:
            self.assertIs(assessment[key], False, key)

    def test_exact_external_image_assertion_prints_plan_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project_root = Path(raw)
            candidate, receipt_file_sha, receipt_self_sha = self._fixture(project_root)
            before = sorted(
                path.relative_to(project_root).as_posix()
                for path in project_root.rglob("*")
            )
            stdout = io.StringIO()
            argv = [
                "--project-root",
                str(project_root),
                "--candidate-root",
                candidate.relative_to(project_root).as_posix(),
                "--role",
                "secondary",
                "--expected-receipt-file-sha256",
                receipt_file_sha,
                "--expected-receipt-self-sha256",
                receipt_self_sha,
                "--available-image-id",
                pilot.TENSORRT_IMAGE_ID,
            ]
            with mock.patch.object(
                Path, "write_bytes", side_effect=AssertionError("write forbidden")
            ), mock.patch.object(
                Path, "write_text", side_effect=AssertionError("write forbidden")
            ), contextlib.redirect_stdout(stdout):
                status = pilot.main(argv)
            after = sorted(
                path.relative_to(project_root).as_posix()
                for path in project_root.rglob("*")
            )

        self.assertEqual(status, 0)
        self.assertEqual(after, before)
        plan = json.loads(stdout.getvalue())
        self.assertEqual(plan["artifact_kind"], pilot.PLAN_ARTIFACT_KIND)
        self.assertEqual(plan["request_count"], 8)

    def test_receipt_self_hash_and_exact_eight_descriptors_are_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project_root = Path(raw)
            candidate, _, _ = self._fixture(project_root)
            receipt_path = candidate / pilot.RECEIPT_NAME
            original = json.loads(receipt_path.read_text(encoding="ascii"))

            bad_self = copy.deepcopy(original)
            bad_self["candidate_receipt_sha256"] = "0" * 64
            bad_self_payload = pilot.canonical_line(bad_self)
            receipt_path.write_bytes(bad_self_payload)
            with self.assertRaisesRegex(
                pilot.PilotContractError, "receipt self SHA-256 drifted"
            ):
                pilot.build_pilot_plan(
                    project_root=project_root,
                    candidate_root=candidate.relative_to(project_root),
                    role="secondary",
                    expected_receipt_file_sha256=hashlib.sha256(
                        bad_self_payload
                    ).hexdigest(),
                    expected_receipt_self_sha256="0" * 64,
                )

            missing = copy.deepcopy(original)
            missing["outputs"] = [
                item
                for item in missing["outputs"]
                if not item["path"].endswith(
                    "/corpus_vehicle_type_evaluation.json"
                )
            ]
            missing["candidate_receipt_sha256"] = pilot.candidate_receipt_self_sha(
                missing
            )
            missing_payload = pilot.canonical_line(missing)
            receipt_path.write_bytes(missing_payload)
            with self.assertRaisesRegex(
                pilot.PilotContractError, "exact 8 corpus descriptors drifted"
            ):
                pilot.build_pilot_plan(
                    project_root=project_root,
                    candidate_root=candidate.relative_to(project_root),
                    role="sensitivity",
                    expected_receipt_file_sha256=hashlib.sha256(
                        missing_payload
                    ).hexdigest(),
                    expected_receipt_self_sha256=str(
                        missing["candidate_receipt_sha256"]
                    ),
                )

    def test_same_size_namespace_swap_at_held_read_close_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project_root = Path(raw)
            candidate, receipt_file_sha, receipt_self_sha = self._fixture(project_root)
            target = candidate / "corpus_damage_calibration.json"
            replacement = candidate / "same-size-replacement.json"
            original_payload = target.read_bytes()
            replacement_payload = original_payload.replace(
                b'"schema_version":1', b'"schema_version":2', 1
            )
            self.assertEqual(len(replacement_payload), len(original_payload))
            replacement.write_bytes(replacement_payload)
            real_open = pilot._open_binary_custody
            swapped = False
            swap_denied = False

            @contextlib.contextmanager
            def swap_at_close(
                path: Path, *, label: str, custody: object
            ) -> object:
                nonlocal swap_denied, swapped
                with real_open(path, label=label, custody=custody) as source:
                    yield source
                if path.name == target.name and not (swapped or swap_denied):
                    try:
                        os.replace(replacement, target)
                        swapped = True
                    except OSError:
                        swap_denied = True

            rejected = False
            with mock.patch.object(
                pilot, "_open_binary_custody", side_effect=swap_at_close
            ):
                try:
                    pilot.build_pilot_plan(
                        project_root=project_root,
                        candidate_root=candidate.relative_to(project_root),
                        role="secondary",
                        expected_receipt_file_sha256=receipt_file_sha,
                        expected_receipt_self_sha256=receipt_self_sha,
                    )
                except pilot.PilotContractError as error:
                    rejected = True
                    self.assertRegex(str(error), "changed while reading|identity changed")
            self.assertTrue(swap_denied or (swapped and rejected))

    @unittest.skipUnless(os.name == "nt", "Windows rename custody attack")
    def test_windows_candidate_rename_out_back_metadata_restore_is_denied(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project_root = Path(raw)
            candidate, receipt_file_sha, receipt_self_sha = self._fixture(project_root)
            moved = candidate.with_name("synthetic-candidate-moved")
            candidate_stat = candidate.stat()
            parent_stat = candidate.parent.stat()
            real_load = pilot._load_canonical_object
            attack_succeeded = False
            attack_denied = False

            def attack_after_receipt(*args: object, **kwargs: object) -> object:
                nonlocal attack_denied, attack_succeeded
                result = real_load(*args, **kwargs)
                if kwargs.get("label") == "candidate receipt" and not (
                    attack_succeeded or attack_denied
                ):
                    try:
                        os.replace(candidate, moved)
                        os.replace(moved, candidate)
                        os.utime(
                            candidate,
                            ns=(candidate_stat.st_atime_ns, candidate_stat.st_mtime_ns),
                        )
                        os.utime(
                            candidate.parent,
                            ns=(parent_stat.st_atime_ns, parent_stat.st_mtime_ns),
                        )
                        attack_succeeded = True
                    except OSError:
                        attack_denied = True
                        if moved.exists() and not candidate.exists():
                            os.replace(moved, candidate)
                return result

            rejected = False
            with mock.patch.object(
                pilot, "_load_canonical_object", side_effect=attack_after_receipt
            ):
                try:
                    pilot.build_pilot_plan(
                        project_root=project_root,
                        candidate_root=candidate.relative_to(project_root),
                        role="secondary",
                        expected_receipt_file_sha256=receipt_file_sha,
                        expected_receipt_self_sha256=receipt_self_sha,
                    )
                except pilot.PilotContractError:
                    rejected = True

        self.assertTrue(attack_denied or rejected)
        self.assertFalse(attack_succeeded and not rejected)

    @unittest.skipIf(os.name == "nt", "POSIX openat custody only")
    def test_posix_candidate_reads_are_relative_to_held_directory(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project_root = Path(raw)
            candidate, receipt_file_sha, receipt_self_sha = self._fixture(project_root)
            real_open = pilot.os.open
            relative_opens: list[tuple[str, int | None]] = []

            def observed_open(
                path: object,
                flags: int,
                mode: int = 0o777,
                *,
                dir_fd: int | None = None,
            ) -> int:
                relative_opens.append((os.fspath(path), dir_fd))
                return real_open(path, flags, mode, dir_fd=dir_fd)

            with mock.patch.object(pilot.os, "open", side_effect=observed_open):
                pilot.build_pilot_plan(
                    project_root=project_root,
                    candidate_root=candidate.relative_to(project_root),
                    role="secondary",
                    expected_receipt_file_sha256=receipt_file_sha,
                    expected_receipt_self_sha256=receipt_self_sha,
                )

        candidate_leaves = {pilot.RECEIPT_NAME} | {
            f"corpus_{branch}_{corpus_role}.json"
            for branch in pilot.BRANCHES
            for corpus_role in pilot.CORPUS_ROLES
        }
        held_relative = {
            path for path, dir_fd in relative_opens if dir_fd is not None
        }
        self.assertTrue(candidate_leaves.issubset(held_relative))

    @unittest.skipIf(os.name == "nt", "POSIX directory custody only")
    def test_posix_directory_acquisition_wraps_os_errors_and_closes_fd(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project_root = Path(raw)
            real_open = pilot.os.open
            real_set_inheritable = pilot.os.set_inheritable
            real_fstat = pilot.os.fstat

            for phase in ("open", "set_inheritable", "fstat"):
                with self.subTest(phase=phase):
                    opened: list[int] = []

                    def controlled_open(
                        path: object,
                        flags: int,
                        mode: int = 0o777,
                        *,
                        dir_fd: int | None = None,
                    ) -> int:
                        if phase == "open" and Path(os.fspath(path)) == project_root:
                            raise PermissionError("synthetic directory open denied")
                        descriptor = real_open(path, flags, mode, dir_fd=dir_fd)
                        opened.append(descriptor)
                        return descriptor

                    def controlled_set_inheritable(
                        descriptor: int, inheritable: bool
                    ) -> None:
                        if phase == "set_inheritable" and descriptor in opened:
                            raise PermissionError(
                                "synthetic directory inheritable denied"
                            )
                        real_set_inheritable(descriptor, inheritable)

                    def controlled_fstat(descriptor: int) -> os.stat_result:
                        if phase == "fstat" and descriptor in opened:
                            raise PermissionError("synthetic directory fstat denied")
                        return real_fstat(descriptor)

                    with mock.patch.object(
                        pilot.os, "open", side_effect=controlled_open
                    ), mock.patch.object(
                        pilot.os,
                        "set_inheritable",
                        side_effect=controlled_set_inheritable,
                    ), mock.patch.object(
                        pilot.os, "fstat", side_effect=controlled_fstat
                    ), self.assertRaisesRegex(
                        pilot.PilotContractError,
                        "cannot acquire synthetic root directory custody",
                    ):
                        pilot._open_directory_hold(
                            project_root,
                            label="synthetic root",
                            parent=None,
                        )

                    for descriptor in opened:
                        with self.assertRaises(OSError):
                            real_fstat(descriptor)

    @unittest.skipIf(os.name == "nt", "POSIX directory custody only")
    def test_posix_directory_permission_error_is_canonical_exit_78_assessment(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project_root = Path(raw)
            candidate, receipt_file_sha, receipt_self_sha = self._fixture(project_root)
            real_open = pilot.os.open

            def deny_project_root_only(
                path: object,
                flags: int,
                mode: int = 0o777,
                *,
                dir_fd: int | None = None,
            ) -> int:
                if dir_fd is None and Path(os.fspath(path)) == project_root:
                    raise PermissionError("synthetic project-root custody denied")
                return real_open(path, flags, mode, dir_fd=dir_fd)

            argv = [
                "--project-root",
                str(project_root),
                "--candidate-root",
                candidate.relative_to(project_root).as_posix(),
                "--role",
                "secondary",
                "--expected-receipt-file-sha256",
                receipt_file_sha,
                "--expected-receipt-self-sha256",
                receipt_self_sha,
            ]
            stdout = io.StringIO()
            with mock.patch.object(
                pilot.os, "open", side_effect=deny_project_root_only
            ), contextlib.redirect_stdout(stdout):
                status = pilot.main(argv)

        output = stdout.getvalue()
        assessment = json.loads(output)
        self.assertEqual(status, 78)
        self.assertEqual(output, pilot.canonical_line(assessment).decode("ascii"))
        self.assertEqual(
            assessment["blockers"],
            [
                "cannot acquire project root directory custody: "
                "synthetic project-root custody denied"
            ],
        )
        unsigned = copy.deepcopy(assessment)
        declared_sha = unsigned.pop("assessment_sha256")
        self.assertEqual(
            declared_sha,
            hashlib.sha256(
                pilot.ASSESSMENT_DOMAIN + pilot.canonical_line(unsigned)
            ).hexdigest(),
        )
        for key in pilot.FAIL_CLOSED_FLAGS:
            self.assertIs(assessment[key], False, key)

    def test_exact_sample_and_raw_frame_schema_rejects_resealed_drift(self) -> None:
        cases = (
            (
                "extra sample field",
                lambda document: document["samples"][0].__setitem__("extra", False),
                "sample fields drifted",
            ),
            (
                "missing sample field",
                lambda document: document["samples"][0].pop("source_pts"),
                "sample fields drifted",
            ),
            (
                "extra raw-frame field",
                lambda document: document["samples"][0]["raw_frame"].__setitem__(
                    "extra", False
                ),
                "raw frame fields drifted",
            ),
            (
                "missing raw-frame field",
                lambda document: document["samples"][0]["raw_frame"].pop(
                    "color_order"
                ),
                "raw frame fields drifted",
            ),
        )
        for label, mutate, expected_error in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as raw:
                project_root = Path(raw)
                candidate, _, _ = self._fixture(project_root)
                receipt_file_sha, receipt_self_sha = self._reseal_corpus_mutation(
                    candidate,
                    filename="corpus_damage_calibration.json",
                    mutate=mutate,
                )
                with self.assertRaisesRegex(
                    pilot.PilotContractError, expected_error
                ):
                    pilot.build_pilot_plan(
                        project_root=project_root,
                        candidate_root=candidate.relative_to(project_root),
                        role="secondary",
                        expected_receipt_file_sha256=receipt_file_sha,
                        expected_receipt_self_sha256=receipt_self_sha,
                    )

    def test_receipt_and_corpus_fixed_fields_require_exact_json_types(self) -> None:
        cases = (
            (
                "receipt schema bool",
                True,
                lambda document: document.__setitem__("schema_version", True),
                "candidate receipt fixed contract drifted",
            ),
            (
                "receipt claim integer",
                True,
                lambda document: document["claims"].__setitem__("accuracy", 0),
                "candidate receipt fixed contract drifted",
            ),
            (
                "corpus schema bool",
                False,
                lambda document: document.__setitem__("schema_version", True),
                "corpus fixed contract drifted",
            ),
            (
                "corpus claim integer",
                False,
                lambda document: document["claims"].__setitem__("accuracy", 0),
                "corpus fixed contract drifted",
            ),
        )
        for label, receipt_case, mutate, expected_error in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as raw:
                project_root = Path(raw)
                candidate, _, _ = self._fixture(project_root)
                if receipt_case:
                    receipt_file_sha, receipt_self_sha = (
                        self._reseal_receipt_mutation(
                            candidate, mutate=mutate
                        )
                    )
                else:
                    receipt_file_sha, receipt_self_sha = (
                        self._reseal_corpus_mutation(
                            candidate,
                            filename="corpus_vehicle_type_evaluation.json",
                            mutate=mutate,
                        )
                    )
                with self.assertRaisesRegex(
                    pilot.PilotContractError, expected_error
                ):
                    pilot.build_pilot_plan(
                        project_root=project_root,
                        candidate_root=candidate.relative_to(project_root),
                        role="secondary",
                        expected_receipt_file_sha256=receipt_file_sha,
                        expected_receipt_self_sha256=receipt_self_sha,
                    )

    def test_sha_fields_require_exact_strings_and_physical_sha_is_recomputed(self) -> None:
        cases = (
            (
                "numeric SHA",
                lambda document: document["samples"][0].__setitem__(
                    "dataset_file_sha256", 123
                ),
                "dataset file SHA-256 must be a lowercase SHA-256 string",
            ),
            (
                "physical SHA reseal",
                lambda document: document["samples"][0].__setitem__(
                    "physical_sample_sha256", "f" * 64
                ),
                "physical sample SHA-256 drifted",
            ),
        )
        for label, mutate, expected_error in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as raw:
                project_root = Path(raw)
                candidate, _, _ = self._fixture(project_root)
                receipt_file_sha, receipt_self_sha = self._reseal_corpus_mutation(
                    candidate,
                    filename="corpus_plate_number_calibration.json",
                    mutate=mutate,
                )
                with self.assertRaisesRegex(
                    pilot.PilotContractError, expected_error
                ):
                    pilot.build_pilot_plan(
                        project_root=project_root,
                        candidate_root=candidate.relative_to(project_root),
                        role="sensitivity",
                        expected_receipt_file_sha256=receipt_file_sha,
                        expected_receipt_self_sha256=receipt_self_sha,
                    )

    def test_resealed_sample_provenance_drift_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project_root = Path(raw)
            candidate, _, _ = self._fixture(project_root)
            receipt_file_sha, receipt_self_sha = self._reseal_corpus_mutation(
                candidate,
                filename="corpus_plate_number_evaluation.json",
                mutate=lambda document: document["samples"][0].__setitem__(
                    "file_index", 0
                ),
            )
            with self.assertRaisesRegex(
                pilot.PilotContractError, "sample provenance drifted"
            ):
                pilot.build_pilot_plan(
                    project_root=project_root,
                    candidate_root=candidate.relative_to(project_root),
                    role="secondary",
                    expected_receipt_file_sha256=receipt_file_sha,
                    expected_receipt_self_sha256=receipt_self_sha,
                )

    def test_raw_and_tensor_bundle_descriptors_bind_to_receipt_outputs(self) -> None:
        cases = (
            (
                "raw",
                lambda document: document["samples"][0]["raw_frame"].__setitem__(
                    "sha256", "a" * 64
                ),
            ),
            (
                "tensor",
                lambda document: document["samples"][0][
                    "preprocessed_tensor"
                ].__setitem__("sha256", "b" * 64),
            ),
        )
        for label, mutate in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as raw:
                project_root = Path(raw)
                candidate, _, _ = self._fixture(project_root)
                receipt_file_sha, receipt_self_sha = self._reseal_corpus_mutation(
                    candidate,
                    filename="corpus_foreign_object_calibration.json",
                    mutate=mutate,
                )
                with self.assertRaisesRegex(
                    pilot.PilotContractError, "bundle descriptor binding drifted"
                ):
                    pilot.build_pilot_plan(
                        project_root=project_root,
                        candidate_root=candidate.relative_to(project_root),
                        role="secondary",
                        expected_receipt_file_sha256=receipt_file_sha,
                        expected_receipt_self_sha256=receipt_self_sha,
                    )

    def test_calibration_and_evaluation_physical_frames_are_disjoint(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project_root = Path(raw)
            candidate, _, _ = self._fixture(project_root)
            calibration = json.loads(
                (candidate / "corpus_foreign_object_calibration.json").read_text(
                    encoding="ascii"
                )
            )
            calibration_sample = calibration["samples"][0]

            def overlap(document: dict[str, object]) -> None:
                sample = document["samples"][0]
                for key in (
                    "dataset_file_id",
                    "dataset_file_sha256",
                    "file_index",
                    "stream_index",
                    "frame_index",
                    "source_pts",
                    "source_time_base",
                    "pts_ns",
                    "input_sha256",
                ):
                    sample[key] = copy.deepcopy(calibration_sample[key])
                sample["raw_frame"]["segment_sha256"] = sample["input_sha256"]
                sample["physical_sample_sha256"] = self._physical_sample_sha(
                    sample, str(document["dataset_aggregate_sha256"])
                )

            receipt_file_sha, receipt_self_sha = self._reseal_corpus_mutation(
                candidate,
                filename="corpus_foreign_object_evaluation.json",
                mutate=overlap,
            )
            with self.assertRaisesRegex(
                pilot.PilotContractError,
                "calibration/evaluation physical frames overlap",
            ):
                pilot.build_pilot_plan(
                    project_root=project_root,
                    candidate_root=candidate.relative_to(project_root),
                    role="sensitivity",
                    expected_receipt_file_sha256=receipt_file_sha,
                    expected_receipt_self_sha256=receipt_self_sha,
                )

    def test_disjointness_uses_stable_physical_address_only(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project_root = Path(raw)
            candidate, _, _ = self._fixture(project_root)
            calibration = json.loads(
                (candidate / "corpus_foreign_object_calibration.json").read_text(
                    encoding="ascii"
                )
            )
            calibration_sample = calibration["samples"][0]

            def overlap_with_resealed_decoded_fields(
                document: dict[str, object],
            ) -> None:
                sample = document["samples"][0]
                for key in (
                    "dataset_file_id",
                    "dataset_file_sha256",
                    "stream_index",
                    "frame_index",
                ):
                    sample[key] = copy.deepcopy(calibration_sample[key])
                sample["source_pts"] = calibration_sample["source_pts"] + 17
                sample["pts_ns"] = (
                    sample["source_pts"] * 1_000_000_000 // 600
                )
                sample["input_sha256"] = hashlib.sha256(
                    b"resealed-decoded-frame"
                ).hexdigest()
                sample["raw_frame"]["segment_sha256"] = sample["input_sha256"]
                sample["physical_sample_sha256"] = self._physical_sample_sha(
                    sample, str(document["dataset_aggregate_sha256"])
                )

            receipt_file_sha, receipt_self_sha = self._reseal_corpus_mutation(
                candidate,
                filename="corpus_foreign_object_evaluation.json",
                mutate=overlap_with_resealed_decoded_fields,
            )
            with self.assertRaisesRegex(
                pilot.PilotContractError,
                "calibration/evaluation physical frames overlap",
            ):
                pilot.build_pilot_plan(
                    project_root=project_root,
                    candidate_root=candidate.relative_to(project_root),
                    role="sensitivity",
                    expected_receipt_file_sha256=receipt_file_sha,
                    expected_receipt_self_sha256=receipt_self_sha,
                )

    def test_each_corpus_role_has_unique_stable_physical_addresses(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project_root = Path(raw)
            candidate, _, _ = self._fixture(project_root)

            def duplicate_address_with_resealed_decoded_fields(
                document: dict[str, object],
            ) -> None:
                first = document["samples"][0]
                duplicate = document["samples"][2]
                for key in (
                    "dataset_file_id",
                    "dataset_file_sha256",
                    "stream_index",
                    "frame_index",
                ):
                    duplicate[key] = copy.deepcopy(first[key])
                duplicate["source_pts"] = first["source_pts"] + 23
                duplicate["pts_ns"] = (
                    duplicate["source_pts"] * 1_000_000_000 // 600
                )
                duplicate["input_sha256"] = hashlib.sha256(
                    b"resealed-duplicate-decoded-frame"
                ).hexdigest()
                duplicate["raw_frame"]["segment_sha256"] = duplicate[
                    "input_sha256"
                ]
                duplicate["physical_sample_sha256"] = self._physical_sample_sha(
                    duplicate, str(document["dataset_aggregate_sha256"])
                )

            receipt_file_sha, receipt_self_sha = self._reseal_corpus_mutation(
                candidate,
                filename="corpus_foreign_object_calibration.json",
                mutate=duplicate_address_with_resealed_decoded_fields,
            )
            with self.assertRaisesRegex(
                pilot.PilotContractError,
                "physical frame addresses are not unique",
            ):
                pilot.build_pilot_plan(
                    project_root=project_root,
                    candidate_root=candidate.relative_to(project_root),
                    role="secondary",
                    expected_receipt_file_sha256=receipt_file_sha,
                    expected_receipt_self_sha256=receipt_self_sha,
                )

    def test_oversized_time_base_is_a_deterministic_exit_78_assessment(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project_root = Path(raw)
            candidate, _, _ = self._fixture(project_root)
            receipt_file_sha, receipt_self_sha = self._reseal_corpus_mutation(
                candidate,
                filename="corpus_foreign_object_evaluation.json",
                mutate=lambda document: document["samples"][0].__setitem__(
                    "source_time_base", "1/" + ("9" * 5_000)
                ),
            )
            stdout = io.StringIO()
            argv = [
                "--project-root",
                str(project_root),
                "--candidate-root",
                candidate.relative_to(project_root).as_posix(),
                "--role",
                "secondary",
                "--expected-receipt-file-sha256",
                receipt_file_sha,
                "--expected-receipt-self-sha256",
                receipt_self_sha,
            ]
            with contextlib.redirect_stdout(stdout):
                status = pilot.main(argv)

        self.assertEqual(status, 78)
        assessment = json.loads(stdout.getvalue())
        self.assertEqual(
            assessment["blockers"], ["source time base is invalid"]
        )
        for key in pilot.FAIL_CLOSED_FLAGS:
            self.assertIs(assessment[key], False, key)

    def test_deep_json_is_a_deterministic_exit_78_assessment(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project_root = Path(raw)
            candidate, _, _ = self._fixture(project_root)
            receipt_path = candidate / pilot.RECEIPT_NAME
            payload = b'{"nested":' + (b"[" * 2_000) + b"0" + (b"]" * 2_000) + b"}\n"
            receipt_path.write_bytes(payload)
            argv = [
                "--project-root",
                str(project_root),
                "--candidate-root",
                candidate.relative_to(project_root).as_posix(),
                "--role",
                "secondary",
                "--expected-receipt-file-sha256",
                hashlib.sha256(payload).hexdigest(),
                "--expected-receipt-self-sha256",
                "0" * 64,
            ]
            first_stdout = io.StringIO()
            with contextlib.redirect_stdout(first_stdout):
                first_status = pilot.main(argv)
            recursion_stdout = io.StringIO()
            with mock.patch.object(
                pilot.json, "loads", side_effect=RecursionError("synthetic depth")
            ), contextlib.redirect_stdout(recursion_stdout):
                recursion_status = pilot.main(argv)

        self.assertEqual([first_status, recursion_status], [78, 78])
        self.assertEqual(first_stdout.getvalue(), recursion_stdout.getvalue())
        assessment = json.loads(first_stdout.getvalue())
        self.assertEqual(assessment["status"], "blocked_contract_validation_failed")
        self.assertEqual(
            assessment["blockers"], ["JSON nesting exceeds contract limit"]
        )
        for key in pilot.FAIL_CLOSED_FLAGS:
            self.assertIs(assessment[key], False, key)

    def test_resealed_corpus_claim_drift_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project_root = Path(raw)
            candidate, _, _ = self._fixture(project_root)
            receipt_path = candidate / pilot.RECEIPT_NAME
            receipt = json.loads(receipt_path.read_text(encoding="ascii"))
            corpus_path = candidate / "corpus_damage_calibration.json"
            corpus = json.loads(corpus_path.read_text(encoding="ascii"))
            corpus["promotable"] = True
            corpus_payload = pilot.canonical_line(corpus)
            corpus_path.write_bytes(corpus_payload)
            for descriptor in receipt["outputs"]:
                if descriptor["path"].endswith("/corpus_damage_calibration.json"):
                    descriptor["size_bytes"] = len(corpus_payload)
                    descriptor["sha256"] = hashlib.sha256(corpus_payload).hexdigest()
            receipt["candidate_receipt_sha256"] = pilot.candidate_receipt_self_sha(
                receipt
            )
            receipt_payload = pilot.canonical_line(receipt)
            receipt_path.write_bytes(receipt_payload)

            with self.assertRaisesRegex(
                pilot.PilotContractError, "corpus fixed contract drifted"
            ):
                pilot.build_pilot_plan(
                    project_root=project_root,
                    decision_path=decision.DECISION_PATH,
                    candidate_root=candidate.relative_to(project_root),
                    role="secondary",
                    expected_receipt_file_sha256=hashlib.sha256(
                        receipt_payload
                    ).hexdigest(),
                    expected_receipt_self_sha256=str(
                        receipt["candidate_receipt_sha256"]
                    ),
                )


if __name__ == "__main__":
    unittest.main()
