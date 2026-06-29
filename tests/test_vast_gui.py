from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from http.server import ThreadingHTTPServer

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from vast_gui import (  # noqa: E402
    GuiError,
    VastGuiApp,
    build_run_command,
    make_handler,
)


def minimal_experiments() -> dict:
    return {
        "schema_version": 2,
        "project": {"name": "test"},
        "benchmark": {
            "dataset_manifest": "configs/datasets.yaml",
            "default_dataset": {"smoke": "smoke_testsrc", "benchmark": "kpp_real_avi"},
            "telemetry_schema_version": 2,
            "publishable_telemetry_sources": ["native"],
            "scheduler_policies": ["static_hybrid", "gpu_only"],
            "default_seed": 20260323,
            "active_scenarios": ["checkpoint_video_dag_shared"],
            "smoke_scenarios": ["checkpoint_video_dag_shared"],
            "report_scenarios": ["checkpoint_video_dag_shared"],
            "deadline_ms": [16.7, 33.3, 50, 100, 500],
            "report_deadline_ms": [16.7, 33.3, 50, 100, 500],
        },
        "transport": {
            "kind": "gstreamer_rtp_udp",
            "trace_metadata": "rtp_header_extension",
            "clock_sync": "chrony",
            "max_clock_offset_ms": 5,
            "startup_grace_s": 5,
            "role_ports": {"edge_to_gpu_worker": 5600, "gpu_worker_to_aggregator": 5700},
            "stream_port_stride": 1,
        },
        "hardware_target": {
            "gpu_model": "NVIDIA GeForce RTX 3060",
            "cpu_model": "Intel Core i7-14700K",
            "ram_gb": 22,
            "deadline_s": 0.1,
        },
        "protocol": {
            "warmup_s": 0,
            "measurement_s": 30,
            "repeats": 1,
            "metric_interval_s": 1,
            "custom_cpp_cuda_qt_metric_interval_s": 0.2,
        },
        "scenarios": {
            "checkpoint_video_dag_shared": {
                "description": "Canonical local profile.",
                "benchmark_status": "supported",
                "workload": {"streams": 6, "object_density": {"min": 5, "max": 35}},
                "pipeline": ["decode", "detect", "aggregate"],
                "placement": {
                    "policy": "canonical_local_cpu_gpu",
                    "stages": {"decode": "local", "detect": "local", "aggregate": "local"},
                },
                "network": {"profile": "local", "latency_ms": 0, "bandwidth_mbps": 0, "packet_loss_percent": 0},
                "distributed": {"enabled": False},
            }
        },
        "systems": {
            "deepstream": {
                "label": "NVIDIA DeepStream SDK",
                "detector": "native_deepstream",
                "backend": "tensorrt",
                "container_image": "nvcr.io/nvidia/deepstream:7.0-triton-multiarch",
                "supports_distributed": True,
                "command": (
                    "bash scripts/run_system_template.sh --system deepstream --scenario {scenario} "
                    "--duration {duration_s} --streams {streams} --min-objects {min_objects} "
                    "--max-objects {max_objects} --output {output_dir}/frames.csv"
                ),
            }
        },
    }


def minimal_datasets() -> dict:
    return {
        "schema_version": 1,
        "datasets": {
            "smoke_testsrc": {
                "kind": "synthetic",
                "description": "Smoke",
                "publishable": False,
                "fps": 30,
                "streams": [{"path": "data/videos/stream01.mp4"}],
            },
            "kpp_real_avi": {
                "kind": "real_avi",
                "description": "Benchmark",
                "publishable": True,
                "fps_policy": "pts_frame_count",
                "streams": [{"path": "data/videos/kpp/2.avi", "sha256": "abc", "camera_role": "plate_number"}],
            },
        },
    }


def write_yaml(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


class VastGuiTests(unittest.TestCase):
    def make_project(self, tmp: str) -> Path:
        root = Path(tmp)
        write_yaml(root / "configs" / "experiments.yaml", minimal_experiments())
        write_yaml(root / "configs" / "datasets.yaml", minimal_datasets())
        write_yaml(
            root / "configs" / "hosts.example.yaml",
            {
                "hosts": [
                    {
                        "name": "edge",
                        "address": "127.0.0.1",
                        "port": 22,
                        "roles": ["edge", "gpu_worker", "aggregator"],
                        "project_path": str(root),
                    }
                ]
            },
        )
        (root / "web").mkdir()
        (root / "web" / "index.html").write_text("ok", encoding="utf-8")
        return root

    def test_load_config_creates_hosts_from_example(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_project(tmp)
            app = VastGuiApp(root)

            payload = app.load_all_configs()

            self.assertTrue((root / "configs" / "hosts.yaml").exists())
            self.assertIn("deepstream", [item["key"] for item in payload["selectors"]["systems"]])
            self.assertEqual(payload["configs"]["hosts"]["hosts"][0]["name"], "edge")

    def test_save_config_validates_and_creates_backup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_project(tmp)
            app = VastGuiApp(root)
            payload = app.load_all_configs()
            experiments = payload["configs"]["experiments"]
            experiments["protocol"]["repeats"] = 3

            saved = app.save_config("experiments", {"data": experiments})

            self.assertTrue(Path(saved["backup"]).exists())
            reloaded = yaml.safe_load((root / "configs" / "experiments.yaml").read_text(encoding="utf-8"))
            self.assertEqual(reloaded["protocol"]["repeats"], 3)

    def test_invalid_command_template_is_rejected(self) -> None:
        config = minimal_experiments()
        config["systems"]["deepstream"]["command"] = "echo {scenario}"

        with self.assertRaisesRegex(GuiError, "missing placeholders"):
            VastGuiApp(Path.cwd()).save_config("experiments", {"data": config})

    def test_build_run_command_includes_profile_fields_and_env(self) -> None:
        command, env = build_run_command(
            Path.cwd(),
            {
                "systems": ["deepstream"],
                "scenarios": ["checkpoint_video_dag_shared"],
                "mode": "smoke",
                "dataset": "smoke_testsrc",
                "policy": "gpu_only",
                "run_kind": "single-server-distributed",
                "single_server_host": "127.0.0.1",
                "single_server_port": 2222,
                "single_server_user": "vast",
                "repeats": 2,
                "warmup": 0,
                "measurement": 5,
                "seed": 99,
                "resume_run_root": "runs/old",
                "env_overrides": "STARTUP_GRACE_S=60\nCMD_TIMEOUT_S=120",
            },
            dry_run=True,
        )

        self.assertIn("--dry-run-plan", command)
        self.assertIn("--single-server-port", command)
        self.assertIn("2222", command)
        self.assertEqual(env["STARTUP_GRACE_S"], "60")
        self.assertEqual(env["CMD_TIMEOUT_S"], "120")

    def test_analytics_index_and_detail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_project(tmp)
            run_dir = root / "runs" / "20260101_010101"
            rep_dir = run_dir / "checkpoint_video_dag_shared" / "streams_1" / "deepstream" / "rep_01"
            rep_dir.mkdir(parents=True)
            pd.DataFrame(
                [
                    {
                        "timestamp": "t",
                        "system": "deepstream",
                        "scenario": "checkpoint_video_dag_shared",
                        "repeat": 1,
                        "exit_code": 0,
                        "status": "completed",
                        "skip_reason": "",
                        "streams": 1,
                        "duration_s": 5,
                        "scenario_variant": "",
                        "placement_policy": "local",
                        "distributed": False,
                        "deployment_mode": "heterogeneous",
                        "host_topology": "single_host",
                        "host_role": "local",
                        "detector": "native",
                        "backend": "test",
                        "policy": "static_hybrid",
                        "dataset": "smoke_testsrc",
                        "deadline_ms": 100.0,
                        "throughput_fps": 30,
                        "latency_p50_ms": 10,
                        "latency_p95_ms": 20,
                        "latency_p99_ms": 30,
                        "slo_violation_rate_percent": 0,
                        "frames": 150,
                        "telemetry_source": "native",
                    }
                ]
            ).to_csv(run_dir / "summary.csv", index=False)
            pd.DataFrame(
                [
                    {
                        "schema_version": 2,
                        "run_id": "r",
                        "trace_id": "r:0:1",
                        "stream_id": 0,
                        "frame_id": 1,
                        "ingress_timestamp_ms": 1,
                        "egress_timestamp_ms": 21,
                        "e2e_latency_ms": 20,
                        "objects": 3,
                        "detector": "d",
                        "backend": "b",
                        "telemetry_source": "native",
                    }
                ]
            ).to_csv(rep_dir / "frames.csv", index=False)
            pd.DataFrame(
                [
                    {
                        "schema_version": 2,
                        "run_id": "r",
                        "trace_id": "r:0:1",
                        "stream_id": 0,
                        "frame_id": 1,
                        "stage": "detect",
                        "role": "local",
                        "host": "localhost",
                        "resource": "gpu",
                        "queue_enter_timestamp_ms": 1,
                        "stage_start_timestamp_ms": 2,
                        "stage_end_timestamp_ms": 7,
                        "queue_depth": 1,
                        "estimated_cost_ms": 5,
                        "policy_action": "gpu",
                    }
                ]
            ).to_csv(rep_dir / "frame_events.csv", index=False)
            pd.DataFrame(
                [
                    {
                        "timestamp_ms": 1,
                        "gpu_util_percent": 40,
                        "gpu_memory_mb": 512,
                        "gpu_power_w": 70,
                        "cpu_total_percent": 20,
                        "cpu_per_core_percent": "20",
                        "cpu_memory_mb": 1024,
                        "cpu_power_w": 40,
                    }
                ]
            ).to_csv(rep_dir / "system_metrics.csv", index=False)
            pd.DataFrame(
                [
                    {
                        "timestamp_ms": 1,
                        "source_role": "edge",
                        "target_role": "gpu_worker",
                        "latency_ms": 1,
                        "jitter_ms": 0.1,
                        "packet_loss_percent": 0,
                        "bandwidth_mbps": 1000,
                        "clock_offset_ms": 0,
                        "status": "measured",
                    }
                ]
            ).to_csv(rep_dir / "network_metrics.csv", index=False)

            app = VastGuiApp(root)
            analytics = app.analytics()
            detail = app.analytics_detail("20260101_010101")

            self.assertEqual(analytics["kpis"]["completed_rows"], 1)
            self.assertEqual(detail["frames"]["stats"][0]["latency_p95_ms"], 20)
            self.assertEqual(detail["stage_stats"][0]["stage"], "detect")
            self.assertEqual(detail["network_metrics"][0]["bandwidth_mbps"], 1000)

    def test_api_get_config_and_mocked_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_project(tmp)
            app = VastGuiApp(root)
            handler = make_handler(app)
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_port}"
            try:
                with urllib.request.urlopen(f"{base}/api/config", timeout=5) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                self.assertIn("experiments", payload["configs"])

                with mock.patch(
                    "vast_gui.subprocess.run",
                    return_value=SimpleNamespace(returncode=0, stdout="[plan] ok", stderr=""),
                ):
                    request = urllib.request.Request(
                        f"{base}/api/runs/dry-run",
                        data=json.dumps(
                            {
                                "systems": ["deepstream"],
                                "scenarios": ["checkpoint_video_dag_shared"],
                                "mode": "smoke",
                                "dataset": "smoke_testsrc",
                            }
                        ).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    with urllib.request.urlopen(request, timeout=5) as response:
                        dry_run = json.loads(response.read().decode("utf-8"))
                self.assertTrue(dry_run["ok"])
                self.assertIn("--dry-run-plan", dry_run["command"])
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
