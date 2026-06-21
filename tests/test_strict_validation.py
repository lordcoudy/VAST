#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from validate_strict_telemetry_fix import (  # noqa: E402
    DEFAULT_SYSTEMS,
    StrictValidationError,
    clear_runtime_artifacts,
    completed_systems,
    expand_policies,
    guard_repo_child,
    run_experiments_command,
    run_validation,
    runtime_artifact_paths,
    scenario_completed,
    scenario_groups,
    scenario_variant_paths,
    validation_environment,
)

from run_openvino_container_chunks import (  # noqa: E402
    ChunkRunError,
    append_csv as append_openvino_chunk_csv,
    build_stream_command,
    parse_stream_sources,
)


class StrictValidationAutomationTests(unittest.TestCase):
    def test_guard_rejects_paths_outside_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            outside = Path(tmp) / "outside"
            outside.mkdir()

            with self.assertRaisesRegex(StrictValidationError, "outside repository"):
                guard_repo_child(outside, root)

    def test_runtime_artifact_paths_are_constrained(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            paths = runtime_artifact_paths(root, Path("runs/strict_validation"))

            self.assertEqual(paths[0], root / ".cache" / "savant")
            self.assertEqual(paths[1], root / "runs" / "strict_validation")
            for path in paths:
                self.assertEqual(guard_repo_child(path, root), path.resolve())

    def test_clear_runtime_artifacts_keeps_dataset_assets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            savant_cache = root / ".cache" / "savant"
            validation_runs = root / "runs" / "strict_validation"
            dataset = root / "data" / "benchmark"
            savant_cache.mkdir(parents=True)
            validation_runs.mkdir(parents=True)
            dataset.mkdir(parents=True)
            savant_cache.joinpath("engine.cache").write_text("x", encoding="utf-8")
            validation_runs.joinpath("summary.csv").write_text("x", encoding="utf-8")
            dataset.joinpath("clip.mp4").write_text("x", encoding="utf-8")

            clear_runtime_artifacts(root, Path("runs/strict_validation"))

            self.assertFalse(savant_cache.exists())
            self.assertFalse(validation_runs.exists())
            self.assertTrue(dataset.exists())

    def test_expand_all_policies_from_config(self) -> None:
        config = {"benchmark": {"scheduler_policies": ["cpu_only", "gpu_only", "static_hybrid"]}}

        self.assertEqual(expand_policies(config, ["all"]), ["cpu_only", "gpu_only", "static_hybrid"])
        self.assertEqual(expand_policies(config, ["gpu_only"]), ["gpu_only"])
        with self.assertRaisesRegex(StrictValidationError, "unknown scheduler policies"):
            expand_policies(config, ["missing"])

    def test_completed_systems_detects_all_requested_repeats(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for rep in range(1, 6):
                path = root / "cpu_only" / "20260619_001025" / "canonical_heterogeneous" / "streams_6" / "savant" / f"rep_{rep:02d}"
                path.mkdir(parents=True)
                (path / "run_metadata.json").write_text("{}", encoding="utf-8")
            partial = root / "cpu_only" / "20260619_001025" / "canonical_heterogeneous" / "streams_6" / "openvino_gva" / "rep_01"
            partial.mkdir(parents=True)

            self.assertEqual(
                completed_systems(root, "cpu_only", "canonical_heterogeneous", ["savant", "openvino_gva"], 5),
                {"savant"},
            )

    def test_scenario_completed_requires_every_variant_stream_and_repeat(self) -> None:
        config = {
            "scenarios": {
                "profile": {
                    "workload": {
                        "stream_range": [1, 2],
                        "variants": [{"name": "low"}, {"name": "high"}],
                    }
                }
            }
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prefixes = scenario_variant_paths(config, "profile")
            first = root / "cpu_only" / "old" / Path(*prefixes[0]) / "savant" / "rep_01"
            first.mkdir(parents=True)
            (first / "run_metadata.json").write_text("{}", encoding="utf-8")
            self.assertFalse(scenario_completed(root, "cpu_only", config, "profile", "savant", 1))

            for index, prefix in enumerate(prefixes):
                run_dir = root / "cpu_only" / f"run_{index}" / Path(*prefix) / "savant" / "rep_01"
                run_dir.mkdir(parents=True, exist_ok=True)
                (run_dir / "run_metadata.json").write_text("{}", encoding="utf-8")
            self.assertTrue(scenario_completed(root, "cpu_only", config, "profile", "savant", 1))

    def test_auto_scenario_groups_use_local_and_single_server_dispatch(self) -> None:
        config = {
            "scenarios": {
                "local": {"distributed": {"enabled": False}},
                "distributed": {"distributed": {"enabled": True}},
            }
        }

        self.assertEqual(
            scenario_groups(config, "all", "auto"),
            [("heterogeneous", ["local"]), ("single-server-distributed", ["distributed"])],
        )

    def test_validation_environment_sets_savant_defaults_without_overriding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = validation_environment(root, {"SAVANT_LOCAL_STARTUP_WAIT_S": "999"})

            self.assertEqual(env["SAVANT_LOCAL_PREWARM"], "1")
            self.assertEqual(env["SAVANT_LOCAL_STARTUP_WAIT_S"], "999")
            self.assertEqual(env["SAVANT_LOCAL_SHUTDOWN_GRACE_S"], "30")
            self.assertNotIn("GST_PLUGIN_PATH", env)

    def test_openvino_chunk_command_isolates_one_stream(self) -> None:
        args = argparse.Namespace(
            image="intel/dlstreamer:latest",
            project_dir="/repo",
            output_dir="/repo/runs/out",
            container_output_dir="/workspace/project/runs/out",
            duration=65,
            chunk_s=30,
            streams=2,
            video_layout_dir="/workspace/project/data/videos",
            detect_bin="object_detect model=/workspace/project/model.xml device=CPU",
            run_id="strict-openvino",
            role="local",
            stages="decode,detect,aggregate",
            detector="people",
            backend="native",
            dataset_streams_json='["data/benchmark/a.mp4", "data/benchmark/b.mp4"]',
            input_port="",
            output_host="",
            output_port="",
            port_stride=1,
            min_objects=5,
            max_objects=35,
            parallel_streams=0,
        )

        stream_sources = parse_stream_sources(args)
        run_id, command = build_stream_command(
            args,
            chunk_index=3,
            chunk_duration=5,
            stream_index=1,
            stream_source=stream_sources[1],
        )

        self.assertEqual(run_id, "strict-openvino-chunk03-stream01")
        self.assertEqual(command[command.index("--streams") + 1], "1")
        self.assertEqual(command[command.index("--duration") + 1], "5")
        self.assertEqual(command[command.index("--output-dir") + 1], "/workspace/project/runs/out/chunks/chunk_03/stream_01")
        self.assertIn('DATASET_STREAMS_JSON=["data/benchmark/b.mp4"]', command)

    def test_openvino_chunk_sources_cycle_when_scenario_has_more_streams_than_clips(self) -> None:
        args = argparse.Namespace(
            dataset_streams_json='["data/benchmark/a.mp4", "data/benchmark/b.mp4"]',
            streams=5,
        )

        self.assertEqual(
            parse_stream_sources(args),
            [
                "data/benchmark/a.mp4",
                "data/benchmark/b.mp4",
                "data/benchmark/a.mp4",
                "data/benchmark/b.mp4",
                "data/benchmark/a.mp4",
            ],
        )

    def test_openvino_chunk_merge_rewrites_stream_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "chunk_frames.csv"
            dst = root / "frames.csv"
            src.write_text(
                "schema_version,run_id,trace_id,stream_id,frame_id,stage\n"
                "1,old,old:0:7,0,7,decode\n",
                encoding="utf-8",
            )

            append_openvino_chunk_csv(src, dst, run_id="strict-openvino-chunk01-stream05", stream_index=5)

            with dst.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["run_id"], "strict-openvino-chunk01-stream05")
            self.assertEqual(rows[0]["stream_id"], "5")
            self.assertEqual(rows[0]["trace_id"], "strict-openvino-chunk01-stream05:5:7")

    def test_openvino_chunk_merge_rejects_malformed_raw_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "chunk_events.csv"
            dst = root / "frame_events.csv"
            src.write_text(
                "schema_version,run_id,trace_id,stream_id,frame_id,stage\n"
                "2,old,old:0:7,0,7,decode,unexpected\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ChunkRunError, "malformed raw CSV row.*line 2"):
                append_openvino_chunk_csv(src, dst, run_id="strict-openvino", stream_index=0)

    def test_openvino_chunk_merge_rejects_empty_surplus_raw_field(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "chunk_events.csv"
            dst = root / "frame_events.csv"
            src.write_text(
                "schema_version,run_id,trace_id,stream_id,frame_id,stage\n"
                "2,old,old:0:7,0,7,decode,\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ChunkRunError, "malformed raw CSV row.*line 2"):
                append_openvino_chunk_csv(src, dst, run_id="strict-openvino", stream_index=0)

    def test_run_validation_dry_run_plan_reaches_benchmark_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_dir = root / "configs"
            config_dir.mkdir()
            (config_dir / "experiments.yaml").write_text(
                "benchmark:\n"
                "  scheduler_policies:\n"
                "    - static_hybrid\n"
                "protocol:\n"
                "  repeats: 1\n",
                encoding="utf-8",
            )
            args = argparse.Namespace(
                project_root=root,
                config=Path("configs/experiments.yaml"),
                manifest=Path("configs/datasets.yaml"),
                dataset="mot17_uadetrac_public",
                source_root=Path("data/videos"),
                dataset_output_dir=Path("data/benchmark"),
                output_root=Path("runs/strict_validation"),
                scenario="canonical_heterogeneous",
                run_kind="heterogeneous",
                systems=["openvino_gva"],
                policies=["static_hybrid"],
                repeats=1,
                warmup=0,
                measurement=1,
                clear_runtime_artifacts=False,
                skip_build=True,
                dry_run_plan=True,
                resume=False,
            )
            calls = []

            def fake_run_command(command, *, cwd, env, dry_run):
                calls.append((command, cwd, dry_run))

            with mock.patch("validate_strict_telemetry_fix.run_command", side_effect=fake_run_command):
                run_validation(args)

            self.assertEqual(len(calls), 3)
            self.assertTrue(all(dry_run for _, _, dry_run in calls))
            self.assertIn("scripts/run_experiments.py", calls[-1][0])
            self.assertEqual(calls[-1][1], root.resolve())

    def test_run_validation_all_dry_run_dispatches_local_and_single_server_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_dir = root / "configs"
            config_dir.mkdir()
            (config_dir / "experiments.yaml").write_text(
                "benchmark:\n"
                "  scheduler_policies: [cpu_only]\n"
                "protocol:\n"
                "  repeats: 1\n"
                "scenarios:\n"
                "  local_profile:\n"
                "    distributed: {enabled: false}\n"
                "  distributed_profile:\n"
                "    distributed: {enabled: true}\n",
                encoding="utf-8",
            )
            args = argparse.Namespace(
                project_root=root,
                config=Path("configs/experiments.yaml"),
                manifest=Path("configs/datasets.yaml"),
                dataset="mot17_uadetrac_public",
                source_root=Path("data/videos"),
                dataset_output_dir=Path("data/benchmark"),
                output_root=Path("runs/strict_validation"),
                scenario="all",
                run_kind="auto",
                systems=["gstreamer_custom"],
                policies=["cpu_only"],
                repeats=1,
                warmup=0,
                measurement=1,
                clear_runtime_artifacts=False,
                skip_build=True,
                dry_run_plan=True,
                resume=False,
            )
            calls = []

            with mock.patch("validate_strict_telemetry_fix.run_command", side_effect=lambda *a, **k: calls.append(a[0])):
                run_validation(args)

            benchmark_calls = calls[2:]
            self.assertEqual(len(benchmark_calls), 2)
            self.assertIn("--run-kind heterogeneous", " ".join(benchmark_calls[0]))
            self.assertIn("--scenarios local_profile", " ".join(benchmark_calls[0]))
            self.assertIn("--run-kind single-server-distributed", " ".join(benchmark_calls[1]))
            self.assertIn("--scenarios distributed_profile", " ".join(benchmark_calls[1]))

    def test_run_experiments_command_is_strict_local_benchmark(self) -> None:
        args = argparse.Namespace(
            config=Path("configs/experiments.yaml"),
            dataset="mot17_uadetrac_public",
            run_kind="heterogeneous",
            systems=DEFAULT_SYSTEMS,
            scenario="canonical_heterogeneous",
            output_root=Path("runs/strict_validation"),
            repeats=None,
            warmup=None,
            measurement=None,
            dry_run_plan=False,
        )

        command = run_experiments_command(args, "static_hybrid", ["openvino_gva", "gstreamer_custom"])
        joined = " ".join(command)

        self.assertIn("scripts/run_experiments.py", command)
        self.assertIn("--systems openvino_gva gstreamer_custom", joined)
        self.assertIn("--mode benchmark", joined)
        self.assertIn("--run-kind heterogeneous", joined)
        self.assertIn("--dataset mot17_uadetrac_public", joined)
        self.assertIn("--scenarios canonical_heterogeneous", joined)
        self.assertIn("--policy static_hybrid", joined)
        self.assertIn("runs/strict_validation/static_hybrid", joined)


if __name__ == "__main__":
    unittest.main()
