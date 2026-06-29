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
    build_clip_plans,
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
