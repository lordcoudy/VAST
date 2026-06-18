#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
import unittest
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from benchmark_adapters import select_scenarios, validate_benchmark_adapter
from benchmark_contract import ContractError
from distributed_executor import build_distributed_plan, run_network_preflight
from run_experiments import (
    build_run_seed,
    expand_scenario,
    load_config,
    normalize_run_kind,
    normalize_scenario,
    resolve_execution_context,
    scenario_env_prefix,
)


class ScenarioPlanningTests(unittest.TestCase):
    def test_baseline_scenario_uses_new_schema(self) -> None:
        cfg = load_config(ROOT / "configs" / "experiments.yaml")
        scenario = normalize_scenario("baseline", cfg["scenarios"]["baseline"])

        self.assertEqual(scenario["workload"]["streams"], 6)
        self.assertEqual(scenario["pipeline"], ["decode", "detect"])
        self.assertFalse(scenario["distributed"]["enabled"])

    def test_stream_range_expands_to_variants(self) -> None:
        cfg = load_config(ROOT / "configs" / "experiments.yaml")
        variants = expand_scenario(cfg, "stream_scaling")

        self.assertEqual(variants[0]["streams"], 1)
        self.assertEqual(variants[-1]["streams"], 16)
        self.assertEqual(len(variants), 16)

    def test_hybrid_variant_sets_placement_policy(self) -> None:
        cfg = load_config(ROOT / "configs" / "experiments.yaml")
        variants = expand_scenario(cfg, "hybrid_placement")
        policies = [v["scenario"]["placement"]["policy"] for v in variants]

        self.assertEqual(policies, ["cpu_only", "gpu_only", "cpu_gpu_split"])

    def test_canonical_profiles_share_workload_and_pipeline(self) -> None:
        cfg = load_config(ROOT / "configs" / "experiments.yaml")
        local = normalize_scenario("canonical_heterogeneous", cfg["scenarios"]["canonical_heterogeneous"])
        distributed = normalize_scenario("canonical_distributed", cfg["scenarios"]["canonical_distributed"])

        self.assertEqual(local["workload"], distributed["workload"])
        self.assertEqual(local["workload"]["seed_group"], "canonical_v1")
        self.assertEqual(local["pipeline"], ["decode", "detect", "aggregate"])
        self.assertEqual(local["pipeline"], distributed["pipeline"])
        self.assertFalse(local["distributed"]["enabled"])
        self.assertTrue(distributed["distributed"]["enabled"])

    def test_benchmark_all_selects_only_supported_scenarios(self) -> None:
        cfg = load_config(ROOT / "configs" / "experiments.yaml")

        self.assertEqual(
            select_scenarios(cfg, ["all"], mode="benchmark"),
            ["canonical_heterogeneous", "canonical_distributed"],
        )
        self.assertEqual(
            select_scenarios(cfg, ["all"], mode="benchmark", run_kind="heterogeneous"),
            ["canonical_heterogeneous"],
        )
        self.assertEqual(
            select_scenarios(cfg, ["all"], mode="benchmark", run_kind="distributed"),
            ["canonical_distributed"],
        )
        self.assertIn("baseline", select_scenarios(cfg, ["all"], mode="smoke"))

    def test_strict_adapter_rejects_experimental_multistage_scenario(self) -> None:
        cfg = load_config(ROOT / "configs" / "experiments.yaml")
        scenario = normalize_scenario("high_density_multistage", cfg["scenarios"]["high_density_multistage"])

        with self.assertRaisesRegex(ContractError, "unsupported benchmark pipeline"):
            validate_benchmark_adapter(
                system_key="deepstream",
                scenario=scenario,
                distributed=False,
                mode="benchmark",
            )

    def test_strict_adapter_accepts_canonical_local_and_distributed(self) -> None:
        cfg = load_config(ROOT / "configs" / "experiments.yaml")
        local = normalize_scenario("canonical_heterogeneous", cfg["scenarios"]["canonical_heterogeneous"])
        distributed = normalize_scenario("canonical_distributed", cfg["scenarios"]["canonical_distributed"])

        local_plan = validate_benchmark_adapter(
            system_key="deepstream",
            scenario=local,
            distributed=False,
            mode="benchmark",
        )
        distributed_plan = validate_benchmark_adapter(
            system_key="openvino_gva",
            scenario=distributed,
            distributed=True,
            mode="benchmark",
        )

        self.assertEqual(local_plan.contract, "strict_native_schema_v2")
        self.assertEqual(distributed_plan.runner, "scripts/run_system_template.sh")

    def test_heterogeneous_context_forces_distributed_env_off(self) -> None:
        cfg = load_config(ROOT / "configs" / "experiments.yaml")
        scenario = normalize_scenario("canonical_heterogeneous", cfg["scenarios"]["canonical_heterogeneous"])
        context = resolve_execution_context(
            requested_run_kind=normalize_run_kind("local"),
            scenario=scenario,
            hosts_config={"hosts": []},
            hosts_config_path=ROOT / "configs" / "hosts.yaml",
            single_server_host="127.0.0.1",
            single_server_user="",
            single_server_port=22,
            project_root=ROOT,
        )

        env_prefix = scenario_env_prefix(scenario, distributed=context.distributed_enabled)
        self.assertEqual(context.deployment_mode, "heterogeneous")
        self.assertIn("EXPERIMENT_DISTRIBUTED=0", env_prefix)

    def test_single_server_distributed_uses_localhost_without_sync(self) -> None:
        cfg = load_config(ROOT / "configs" / "experiments.yaml")
        scenario = normalize_scenario("canonical_distributed", cfg["scenarios"]["canonical_distributed"])
        context = resolve_execution_context(
            requested_run_kind="single-server-distributed",
            scenario=scenario,
            hosts_config={"hosts": []},
            hosts_config_path=ROOT / "configs" / "hosts.yaml",
            single_server_host="127.0.0.1",
            single_server_user="",
            single_server_port=22,
            project_root=ROOT,
        )
        steps = build_distributed_plan(
            hosts_config=context.hosts_config,
            scenario=scenario,
            system_key="custom_cpp_cuda_qt",
            command_template=cfg["systems"]["custom_cpp_cuda_qt"]["command"],
            run_relpath="runs/test/canonical_distributed/streams_6/custom/rep_01",
            duration_s=5,
            streams=6,
            min_objects=5,
            max_objects=35,
        )

        self.assertFalse(context.sync_project)
        self.assertEqual(context.host_topology, "single_host_ssh")
        self.assertEqual([s["role"] for s in steps], ["aggregator", "gpu_worker", "edge"])
        self.assertTrue(all(s["host_label"] == "127.0.0.1" for s in steps))

    def test_builtin_strict_systems_build_role_steps(self) -> None:
        cfg = load_config(ROOT / "configs" / "experiments.yaml")
        scenario = normalize_scenario("canonical_distributed", cfg["scenarios"]["canonical_distributed"])
        context = resolve_execution_context(
            requested_run_kind="single-server-distributed",
            scenario=scenario,
            hosts_config={"hosts": []},
            hosts_config_path=ROOT / "configs" / "hosts.yaml",
            single_server_host="127.0.0.1",
            single_server_user="",
            single_server_port=22,
            project_root=ROOT,
        )
        for system in ("deepstream", "savant", "openvino_gva", "gstreamer_custom"):
            steps = build_distributed_plan(
                hosts_config=context.hosts_config,
                scenario=scenario,
                system_key=system,
                command_template=cfg["systems"][system]["command"],
                run_relpath=f"runs/test/canonical_distributed/streams_6/{system}/rep_01",
                duration_s=5,
                streams=6,
                min_objects=5,
                max_objects=35,
                transport=cfg["transport"],
                mode="benchmark",
            )
            self.assertEqual([s["role"] for s in steps], ["aggregator", "gpu_worker", "edge"])
            self.assertTrue(all(f"--system {system}" in s["remote_command"] for s in steps))
            self.assertTrue(all("EXPERIMENT_DISTRIBUTED=1" in s["remote_command"] for s in steps))
            self.assertTrue(all("EXPERIMENT_RTP_PORT_STRIDE=1" in s["remote_command"] for s in steps))
            self.assertTrue(all("DISTRIBUTED_NATIVE_CMD" not in s["remote_command"] for s in steps))

    def test_builtin_strict_template_dry_run_commands(self) -> None:
        expectations = {
            "deepstream": ["vast/deepstream-native-probe:7.0", "nvinfer", "/usr/local/bin/vast_native_gst_probe"],
            "savant": ["vast/savant-native-probe:0.5.17-7.0", "savant.entrypoint", "canonical_distributed_module.yml"],
            "openvino_gva": ["vast_native_gst_probe", "gvadetect", "--input-port-base 5600"],
            "gstreamer_custom": ["GST_CUSTOM_STRICT=1", "adaptivescheduler", "--input-port-base 5600"],
        }
        for system, expected in expectations.items():
            env = os.environ.copy()
            env.update(
                {
                    "REAL_DRY_RUN": "1",
                    "BENCHMARK_MODE": "benchmark",
                    "EXPERIMENT_DISTRIBUTED": "1",
                    "EXPERIMENT_HOST_ROLE": "gpu_worker",
                    "EXPERIMENT_PIPELINE_STAGES": "detect",
                    "EXPERIMENT_RTP_INPUT_PORT": "5600",
                    "EXPERIMENT_RTP_OUTPUT_HOST": "127.0.0.1",
                    "EXPERIMENT_RTP_OUTPUT_PORT": "5700",
                }
            )
            completed = subprocess.run(
                [
                    "bash",
                    str(ROOT / "scripts" / "run_system_template.sh"),
                    "--system",
                    system,
                    "--scenario",
                    "canonical_distributed",
                    "--duration",
                    "5",
                    "--streams",
                    "2",
                    "--min-objects",
                    "5",
                    "--max-objects",
                    "35",
                    "--output",
                    str(ROOT / "runs" / "dry" / system / "frames.csv"),
                ],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            output = completed.stdout + completed.stderr
            self.assertEqual(completed.returncode, 1)
            for fragment in expected:
                self.assertIn(fragment, output)
            if system == "deepstream":
                self.assertIn("--entrypoint /usr/local/bin/vast_native_gst_probe", output)
                self.assertNotIn("'vast/deepstream-native-probe:7.0'     /usr/local/bin/vast_native_gst_probe", output)

    def test_builtin_strict_local_template_dry_run_commands(self) -> None:
        expectations = {
            "deepstream": ["vast/deepstream-native-probe:7.0", "nvinfer", "/usr/local/bin/vast_native_gst_probe", "--role local"],
            "savant": ["ghcr.io/insight-platform/savant-deepstream:0.5.17-7.0", "savant.entrypoint", "canonical_heterogeneous_module.yml"],
            "openvino_gva": ["vast_native_gst_probe", "gvadetect", "--role local"],
            "gstreamer_custom": ["GST_CUSTOM_STRICT=1", "adaptivescheduler", "--role local"],
        }
        for system, expected in expectations.items():
            env = os.environ.copy()
            env.update(
                {
                    "REAL_DRY_RUN": "1",
                    "BENCHMARK_MODE": "benchmark",
                    "EXPERIMENT_DISTRIBUTED": "0",
                    "EXPERIMENT_HOST_ROLE": "local",
                    "EXPERIMENT_PIPELINE_STAGES": "decode,detect,aggregate",
                }
            )
            completed = subprocess.run(
                [
                    "bash",
                    str(ROOT / "scripts" / "run_system_template.sh"),
                    "--system",
                    system,
                    "--scenario",
                    "canonical_heterogeneous",
                    "--duration",
                    "5",
                    "--streams",
                    "2",
                    "--min-objects",
                    "5",
                    "--max-objects",
                    "35",
                    "--output",
                    str(ROOT / "runs" / "dry" / "local" / system / "frames.csv"),
                ],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            output = completed.stdout + completed.stderr
            self.assertEqual(completed.returncode, 1)
            for fragment in expected:
                self.assertIn(fragment, output)
            self.assertNotIn("deepstream-test3-app", output)
            self.assertNotIn("deploy/savant/module.yml", output)
            if system == "deepstream":
                self.assertIn("--entrypoint /usr/local/bin/vast_native_gst_probe", output)
                self.assertNotIn("'vast/deepstream-native-probe:7.0'     /usr/local/bin/vast_native_gst_probe", output)

    def test_gstreamer_custom_plugin_is_bundled(self) -> None:
        source = ROOT / "deploy" / "gstreamer_adaptivescheduler" / "gstadaptivescheduler.c"
        cmake = (ROOT / "CMakeLists.txt").read_text(encoding="utf-8")
        body = source.read_text(encoding="utf-8")

        self.assertIn("add_library(gstadaptivescheduler MODULE", cmake)
        self.assertIn("LIBRARY_OUTPUT_DIRECTORY", cmake)
        self.assertIn('gst_element_register(plugin, "adaptivescheduler"', body)
        self.assertIn("GST_PLUGIN_DEFINE", body)

    def test_native_probe_dockerfiles_disable_unneeded_custom_plugin_target(self) -> None:
        for name in ("Dockerfile.deepstream", "Dockerfile.savant"):
            body = (ROOT / "deploy" / "native_gst_probe" / name).read_text(encoding="utf-8")
            self.assertIn("COPY deploy/native_gst_probe", body)
            self.assertIn("-DVAST_BUILD_NATIVE_GST_PROBE=ON", body)
            self.assertIn("-DVAST_BUILD_GSTREAMER_CUSTOM_PLUGIN=OFF", body)
            self.assertIn("-DVAST_BUILD_CUSTOM_CUDA_QT=OFF", body)

    def test_native_probe_sets_string_properties_after_parse_launch(self) -> None:
        body = (ROOT / "deploy" / "native_gst_probe" / "vast_native_gst_probe.cpp").read_text(encoding="utf-8")
        self.assertNotIn("filesrc location=", body)
        self.assertNotIn("udpsink host=", body)
        self.assertIn("filesrc name=file_src", body)
        self.assertIn("udpsink name=out_sink", body)
        self.assertIn('set_string_property(pipeline, "file_src" + std::to_string(stream_id), "location"', body)
        self.assertIn('set_string_property(pipeline, "out_sink" + std::to_string(stream_id), "host"', body)

    def test_deepstream_native_probe_uses_nvstreammux_topology(self) -> None:
        body = (ROOT / "deploy" / "native_gst_probe" / "vast_native_gst_probe.cpp").read_text(encoding="utf-8")

        self.assertIn("deepstream_local_pipeline", body)
        self.assertIn("deepstream_worker_pipeline", body)
        self.assertIn("uridecodebin name=uri_src", body)
        self.assertIn("nvstreammux name=mux", body)
        self.assertIn("! mux\" << stream_id << \".sink_0", body)
        self.assertNotIn("video/x-raw(memory:NVMM),format=NV12 ! nvinfer", body)

    def test_single_server_preflight_records_loopback_metrics(self) -> None:
        hosts_config = {
            "hosts": [
                {
                    "address": "127.0.0.1",
                    "project_path": str(ROOT),
                    "roles": ["edge", "gpu_worker", "aggregator"],
                }
            ]
        }
        with tempfile.TemporaryDirectory() as tmp:
            network_csv = Path(tmp) / "network_metrics.csv"
            result = run_network_preflight(
                hosts_config=hosts_config,
                network_csv=network_csv,
                network_profile={},
                max_clock_offset_ms=5,
            )

            self.assertFalse(result.skipped)
            self.assertIn("same_host_loopback", network_csv.read_text(encoding="utf-8"))

    def test_workload_seed_is_independent_of_system(self) -> None:
        first = build_run_seed(20260323, "canonical_heterogeneous", "", 6, 1)
        second = build_run_seed(20260323, "canonical_heterogeneous", "", 6, 1)
        different_repeat = build_run_seed(20260323, "canonical_heterogeneous", "", 6, 2)

        self.assertEqual(first, second)
        self.assertNotEqual(first, different_repeat)

    def test_distributed_plan_maps_roles_to_hosts(self) -> None:
        cfg = load_config(ROOT / "configs" / "experiments.yaml")
        scenario = normalize_scenario(
            "edge_worker_aggregator_distributed",
            cfg["scenarios"]["edge_worker_aggregator_distributed"],
        )
        hosts_config = {
            "hosts": [
                {
                    "address": "edge.example.net",
                    "user": "vast",
                    "project_path": "/opt/vast",
                    "roles": ["edge"],
                },
                {
                    "address": "gpu.example.net",
                    "user": "vast",
                    "project_path": "/opt/vast",
                    "roles": ["gpu_worker"],
                },
                {
                    "address": "agg.example.net",
                    "user": "vast",
                    "project_path": "/opt/vast",
                    "roles": ["aggregator"],
                },
            ]
        }

        steps = build_distributed_plan(
            hosts_config=hosts_config,
            scenario=scenario,
            system_key="custom_cpp_cuda_qt",
            command_template=cfg["systems"]["custom_cpp_cuda_qt"]["command"],
            run_relpath="runs/test/scenario/streams_1/custom/rep_01",
            duration_s=5,
            streams=1,
            min_objects=0,
            max_objects=1,
        )

        self.assertEqual([s["role"] for s in steps], ["aggregator", "gpu_worker", "edge"])
        self.assertIn("EXPERIMENT_DISTRIBUTED=1", steps[0]["remote_command"])
        self.assertIn("EXPERIMENT_RTP_INPUT_PORT=5700", steps[0]["remote_command"])
        self.assertIn("--output /opt/vast/runs/test", steps[0]["remote_command"])
        self.assertIn(" && { (METRICS_PY=", steps[0]["remote_command"])
        self.assertTrue(steps[0]["remote_command"].rstrip().endswith("; }"))


if __name__ == "__main__":
    unittest.main()
