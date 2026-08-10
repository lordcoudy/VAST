#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Sequence

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from prepare_benchmark_dataset import (  # noqa: E402
    DatasetPrepError,
    VideoTranscodePlan,
    build_clip_plans,
    ffmpeg_command,
    prepare_clip,
)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_manifest(root: Path, target_name: str, sha256: str) -> Path:
    manifest = root / "configs" / "datasets.yaml"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        yaml.safe_dump(
            {
                "datasets": {
                    "mot17_uadetrac_public": {
                        "publishable": True,
                        "streams": [
                            {
                                "path": f"data/benchmark/{target_name}",
                                "sha256": sha256,
                            }
                        ],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    return manifest


def make_source_frame(root: Path, rel: Path) -> None:
    source_dir = root / "data" / "videos" / rel
    source_dir.mkdir(parents=True)
    source_dir.joinpath("000001.jpg" if "MOT17" in str(rel) else "img00001.jpg").write_bytes(b"frame")


def write_kpp_transcode_manifest(
    root: Path,
    *,
    source_sha256: str,
    target_sha256: str,
    duplicate_target_sha256: str | None = None,
) -> Path:
    manifest = root / "configs" / "datasets.yaml"
    manifest.parent.mkdir(parents=True)
    streams = [
        {
            "stream_id": 0,
            "path": "data/videos/kpp/h264/1.mp4",
            "source_path": "data/videos/kpp/1.avi",
            "sha256": target_sha256,
        }
    ]
    if duplicate_target_sha256 is not None:
        streams.append(
            {
                "stream_id": 1,
                "path": "data/videos/kpp/h264/1.mp4",
                "source_path": "data/videos/kpp/1.avi",
                "sha256": duplicate_target_sha256,
            }
        )
    manifest.write_text(
        yaml.safe_dump(
            {
                "datasets": {
                    "kpp_source": {
                        "kind": "real_avi",
                        "streams": [
                            {
                                "path": "data/videos/kpp/1.avi",
                                "sha256": source_sha256,
                            }
                        ],
                    },
                    "kpp_h264": {
                        "kind": "real_codec_transcode",
                        "source_dataset": "kpp_source",
                        "unique_recorded_sources": 1,
                        "transcode": {
                            "source_paths": ["data/videos/kpp/1.avi"],
                            "ffmpeg_filter": "fps=600",
                            "encoder": "libx264",
                            "preset": "veryfast",
                            "crf": 23,
                            "pix_fmt": "yuv420p",
                        },
                        "streams": streams,
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    return manifest


class PrepareBenchmarkDatasetTests(unittest.TestCase):
    def test_real_avi_dataset_has_no_preparation_plans(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "configs" / "datasets.yaml"
            manifest.parent.mkdir(parents=True)
            manifest.write_text(
                yaml.safe_dump(
                    {
                        "datasets": {
                            "kpp_real_avi": {
                                "kind": "real_avi",
                                "publishable": True,
                                "streams": [{"path": "data/videos/kpp/1.avi", "sha256": "abc"}],
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            plans = build_clip_plans(
                manifest=manifest,
                dataset_name="kpp_real_avi",
                project_root=root,
                source_root=Path("data/videos"),
                output_dir=Path("data/benchmark"),
            )

        self.assertEqual(plans, [])

    def test_public_manifest_maps_all_expected_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plans = build_clip_plans(
                manifest=ROOT / "configs" / "datasets.yaml",
                dataset_name="mot17_uadetrac_public",
                project_root=ROOT,
                source_root=Path("data/videos"),
                output_dir=Path(tmp),
            )

        self.assertEqual(
            {plan.target.name for plan in plans},
            {
                "mot17_02.mp4",
                "mot17_04.mp4",
                "mot17_09.mp4",
                "uadetrac_mvi_20011.mp4",
                "uadetrac_mvi_40152.mp4",
                "uadetrac_mvi_40714.mp4",
            },
        )
        by_name = {plan.target.name: plan for plan in plans}
        self.assertEqual(by_name["mot17_02.mp4"].source_dir.name, "img1")
        self.assertIn("MOT17-02-FRCNN", str(by_name["mot17_02.mp4"].source_dir))
        self.assertEqual(by_name["uadetrac_mvi_40714.mp4"].source_dir.name, "MVI_40714")

    def test_kpp_manifests_deduplicate_logical_replicas(self) -> None:
        expectations = {
            "kpp_real_h264": ("libx264", "veryfast", 23, "h264"),
            "kpp_real_h265": ("libx265", "ultrafast", 30, "h265"),
        }
        for dataset_name, (encoder, preset, crf, codec_dir) in expectations.items():
            with self.subTest(dataset=dataset_name):
                plans = build_clip_plans(
                    manifest=ROOT / "configs" / "datasets.yaml",
                    dataset_name=dataset_name,
                    project_root=ROOT,
                    source_root=Path("data/videos"),
                    output_dir=Path("data/benchmark"),
                )

                self.assertEqual(len(plans), 2)
                self.assertTrue(all(isinstance(plan, VideoTranscodePlan) for plan in plans))
                self.assertEqual({plan.encoder for plan in plans}, {encoder})
                self.assertEqual({plan.preset for plan in plans}, {preset})
                self.assertEqual({plan.crf for plan in plans}, {crf})
                self.assertEqual(
                    {plan.rel_path.as_posix() for plan in plans},
                    {
                        f"data/videos/kpp/{codec_dir}/1.mp4",
                        f"data/videos/kpp/{codec_dir}/2.mp4",
                    },
                )

    def test_kpp_ffmpeg_command_uses_manifest_transcode_contract(self) -> None:
        plan = build_clip_plans(
            manifest=ROOT / "configs" / "datasets.yaml",
            dataset_name="kpp_real_h264",
            project_root=ROOT,
            source_root=Path("data/videos"),
            output_dir=Path("data/benchmark"),
        )[0]
        self.assertIsInstance(plan, VideoTranscodePlan)
        command = ffmpeg_command(plan, Path("/tmp/kpp-output.mp4"))

        self.assertEqual(command[0], "ffmpeg")
        self.assertEqual(command[command.index("-vf") + 1], "fps=600")
        self.assertEqual(command[command.index("-c:v") + 1], "libx264")
        self.assertEqual(command[command.index("-preset") + 1], "veryfast")
        self.assertEqual(command[command.index("-crf") + 1], "23")
        self.assertEqual(command[command.index("-pix_fmt") + 1], "yuv420p")

    def test_kpp_matching_target_skips_without_source_video(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target_payload = b"already prepared KPP transcode"
            manifest = write_kpp_transcode_manifest(
                root,
                source_sha256=digest(b"source not present"),
                target_sha256=digest(target_payload),
            )
            target = root / "data/videos/kpp/h264/1.mp4"
            target.parent.mkdir(parents=True)
            target.write_bytes(target_payload)
            plan = build_clip_plans(
                manifest=manifest,
                dataset_name="kpp_h264",
                project_root=root,
                source_root=Path("data/videos"),
                output_dir=Path("data/benchmark"),
            )[0]

            def fail_runner(command):  # type: ignore[no-untyped-def]
                raise AssertionError(f"runner should not be called: {command}")

            self.assertEqual(prepare_clip(plan, runner=fail_runner), "skipped")

    def test_kpp_source_checksum_is_verified_before_transcode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = write_kpp_transcode_manifest(
                root,
                source_sha256=digest(b"expected source"),
                target_sha256=digest(b"expected target"),
            )
            source = root / "data/videos/kpp/1.avi"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"different source")
            plan = build_clip_plans(
                manifest=manifest,
                dataset_name="kpp_h264",
                project_root=root,
                source_root=Path("data/videos"),
                output_dir=Path("data/benchmark"),
            )[0]

            with self.assertRaisesRegex(DatasetPrepError, "source checksum mismatch"):
                prepare_clip(plan)

    def test_kpp_transcode_is_installed_after_output_checksum_matches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_payload = b"verified KPP source"
            target_payload = b"verified KPP transcode"
            manifest = write_kpp_transcode_manifest(
                root,
                source_sha256=digest(source_payload),
                target_sha256=digest(target_payload),
            )
            source = root / "data/videos/kpp/1.avi"
            source.parent.mkdir(parents=True)
            source.write_bytes(source_payload)
            plan = build_clip_plans(
                manifest=manifest,
                dataset_name="kpp_h264",
                project_root=root,
                source_root=Path("data/videos"),
                output_dir=Path("data/benchmark"),
            )[0]
            commands: list[Sequence[str]] = []

            def fake_runner(command):  # type: ignore[no-untyped-def]
                commands.append(command)
                Path(command[-1]).write_bytes(target_payload)
                return subprocess.CompletedProcess(command, 0)

            self.assertEqual(prepare_clip(plan, runner=fake_runner), "missing")
            self.assertEqual(plan.target.read_bytes(), target_payload)
            self.assertEqual(len(commands), 1)
            self.assertEqual(
                Path(commands[0][commands[0].index("-i") + 1]).resolve(),
                source.resolve(),
            )

    def test_kpp_duplicate_target_contract_drift_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = write_kpp_transcode_manifest(
                root,
                source_sha256=digest(b"source"),
                target_sha256=digest(b"target one"),
                duplicate_target_sha256=digest(b"target two"),
            )

            with self.assertRaisesRegex(DatasetPrepError, "logical replicas disagree"):
                build_clip_plans(
                    manifest=manifest,
                    dataset_name="kpp_h264",
                    project_root=root,
                    source_root=Path("data/videos"),
                    output_dir=Path("data/benchmark"),
                )

    def test_matching_checksum_skips_without_requiring_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = b"already prepared"
            manifest = write_manifest(root, "mot17_02.mp4", digest(payload))
            target = root / "data" / "benchmark" / "mot17_02.mp4"
            target.parent.mkdir(parents=True)
            target.write_bytes(payload)
            plan = build_clip_plans(
                manifest=manifest,
                dataset_name="mot17_uadetrac_public",
                project_root=root,
                source_root=Path("data/videos"),
                output_dir=Path("data/benchmark"),
            )[0]

            def fail_runner(command):  # type: ignore[no-untyped-def]
                raise AssertionError(f"runner should not be called: {command}")

            self.assertEqual(prepare_clip(plan, runner=fail_runner), "skipped")

    def test_missing_raw_source_fails_clearly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = write_manifest(root, "mot17_02.mp4", digest(b"expected"))
            plan = build_clip_plans(
                manifest=manifest,
                dataset_name="mot17_uadetrac_public",
                project_root=root,
                source_root=Path("data/videos"),
                output_dir=Path("data/benchmark"),
            )[0]

            with self.assertRaisesRegex(DatasetPrepError, "missing raw source directory"):
                prepare_clip(plan)

    def test_mismatched_output_triggers_regeneration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prepared = b"prepared bytes"
            manifest = write_manifest(root, "mot17_02.mp4", digest(prepared))
            make_source_frame(root, Path("MOT17/train/MOT17-02-FRCNN/img1"))
            target = root / "data" / "benchmark" / "mot17_02.mp4"
            target.parent.mkdir(parents=True)
            target.write_bytes(b"stale")
            plan = build_clip_plans(
                manifest=manifest,
                dataset_name="mot17_uadetrac_public",
                project_root=root,
                source_root=Path("data/videos"),
                output_dir=Path("data/benchmark"),
            )[0]
            commands: list[Sequence[str]] = []

            def fake_runner(command):  # type: ignore[no-untyped-def]
                commands.append(command)
                Path(command[-1]).write_bytes(prepared)
                return subprocess.CompletedProcess(command, 0)

            self.assertEqual(prepare_clip(plan, runner=fake_runner), "checksum_mismatch")
            self.assertEqual(target.read_bytes(), prepared)
            self.assertEqual(len(commands), 1)
            self.assertIn("%06d.jpg", " ".join(commands[0]))

    def test_dry_run_does_not_write_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = write_manifest(root, "uadetrac_mvi_20011.mp4", digest(b"expected"))
            make_source_frame(root, Path("DETRAC-Images/MVI_20011"))
            plan = build_clip_plans(
                manifest=manifest,
                dataset_name="mot17_uadetrac_public",
                project_root=root,
                source_root=Path("data/videos"),
                output_dir=Path("data/benchmark"),
            )[0]

            def fail_runner(command):  # type: ignore[no-untyped-def]
                raise AssertionError(f"runner should not be called: {command}")

            self.assertEqual(prepare_clip(plan, dry_run=True, runner=fail_runner), "dry_run_missing")
            self.assertFalse(plan.target.exists())


if __name__ == "__main__":
    unittest.main()
