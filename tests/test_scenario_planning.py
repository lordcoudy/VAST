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
    default_command_timeout_s,
    expand_scenario,
    load_config,
    normalize_run_kind,
    normalize_scenario,
    resolve_execution_context,
    scenario_env_prefix,
)


SHARED_PROOF_PIPELINE = [
    "decode",
    "preprocess",
    "plate_number",
    "vehicle_type",
    "damage",
    "foreign_object",
    "aggregate",
    "record",
]
INDEPENDENT_PROOF_PIPELINE = [
    "decode_plate_number",
    "preprocess_plate_number",
    "plate_number",
    "decode_vehicle_type",
    "preprocess_vehicle_type",
    "vehicle_type",
    "decode_damage",
    "preprocess_damage",
    "damage",
    "decode_foreign_object",
    "preprocess_foreign_object",
    "foreign_object",
    "aggregate",
    "record",
]
ACTIVE_SCENARIOS = ["checkpoint_independent_processes_baseline", "checkpoint_video_dag_shared"]


def distributed_fixture() -> dict:
    pipeline = ["decode", "preprocess", "detect", "track", "aggregate", "record"]
    return {
        "description": "Inline distributed fixture for planner tests.",
        "workload": {"streams": 6, "object_density": {"min": 1, "max": 12}},
        "pipeline": pipeline,
        "placement": {
            "policy": "fixture_edge_worker_aggregator",
            "stages": {
                "decode": "edge",
                "preprocess": "edge",
                "detect": "gpu_worker",
                "track": "gpu_worker",
                "aggregate": "aggregator",
                "record": "aggregator",
            },
        },
        "network": {"profile": "lan", "latency_ms": 5, "bandwidth_mbps": 1000, "packet_loss_percent": 0},
        "distributed": {"enabled": True, "sync_project": True},
    }


class ScenarioPlanningTests(unittest.TestCase):
    def test_checkpoint_shared_scenario_uses_real_kpp_schema(self) -> None:
        cfg = load_config(ROOT / "configs" / "experiments.yaml")
        scenario = normalize_scenario("checkpoint_video_dag_shared", cfg["scenarios"]["checkpoint_video_dag_shared"])

        self.assertEqual(scenario["workload"]["streams"], 6)
        self.assertEqual(scenario["workload"]["seed_group"], "kpp_real_codecs_v1")
        self.assertEqual(scenario["workload"]["logical_consumers"], 4)
        self.assertEqual(scenario["pipeline"], SHARED_PROOF_PIPELINE)
        self.assertFalse(scenario["distributed"]["enabled"])

    def test_checkpoint_profiles_share_workload_and_deadlines(self) -> None:
        cfg = load_config(ROOT / "configs" / "experiments.yaml")
        shared = normalize_scenario("checkpoint_video_dag_shared", cfg["scenarios"]["checkpoint_video_dag_shared"])
        baseline = normalize_scenario(
            "checkpoint_independent_processes_baseline",
            cfg["scenarios"]["checkpoint_independent_processes_baseline"],
        )

        self.assertEqual(shared["workload"], baseline["workload"])
        self.assertEqual(shared["workload"]["streams"], 6)
        self.assertEqual(shared["pipeline"], SHARED_PROOF_PIPELINE)
        self.assertEqual(baseline["pipeline"], INDEPENDENT_PROOF_PIPELINE)
        self.assertEqual(cfg["benchmark"]["active_scenarios"], ACTIVE_SCENARIOS)
        self.assertEqual(cfg["benchmark"]["report_scenarios"], ACTIVE_SCENARIOS)
        self.assertEqual(cfg["benchmark"]["deadline_ms"], [16.7, 33.3, 50, 100, 500])
        self.assertEqual(cfg["benchmark"]["report_deadline_ms"], [16.7, 33.3, 50, 100, 500])
        self.assertNotIn(3000, cfg["benchmark"]["report_deadline_ms"])

    def test_independent_baseline_repeats_common_stages_per_branch(self) -> None:
        cfg = load_config(ROOT / "configs" / "experiments.yaml")
        baseline = normalize_scenario(
            "checkpoint_independent_processes_baseline",
            cfg["scenarios"]["checkpoint_independent_processes_baseline"],
        )

        self.assertEqual(baseline["pipeline"], INDEPENDENT_PROOF_PIPELINE)
        self.assertEqual(sum(1 for stage in baseline["pipeline"] if stage.startswith("decode_")), 4)
        self.assertEqual(sum(1 for stage in baseline["pipeline"] if stage.startswith("preprocess_")), 4)
        self.assertEqual(set(baseline["placement"]["stages"].values()), {"local"})
        self.assertFalse(baseline["distributed"]["enabled"])

    def test_benchmark_all_selects_only_publishable_checkpoint_scenarios(self) -> None:
        cfg = load_config(ROOT / "configs" / "experiments.yaml")

        self.assertEqual(select_scenarios(cfg, ["all"], mode="benchmark"), ACTIVE_SCENARIOS)
        self.assertEqual(select_scenarios(cfg, ["all"], mode="benchmark", run_kind="auto"), ACTIVE_SCENARIOS)
        self.assertEqual(select_scenarios(cfg, ["all"], mode="benchmark", run_kind="heterogeneous"), ACTIVE_SCENARIOS)
        self.assertEqual(select_scenarios(cfg, ["all"], mode="benchmark", run_kind="distributed"), [])
        self.assertEqual(select_scenarios(cfg, ["all"], mode="smoke"), ["checkpoint_video_dag_shared"])

    def test_strict_adapter_accepts_every_configured_scenario(self) -> None:
        cfg = load_config(ROOT / "configs" / "experiments.yaml")

        for name, raw in cfg["scenarios"].items():
            with self.subTest(scenario=name):
                scenario = normalize_scenario(name, raw)
                plan = validate_benchmark_adapter(
                    system_key="deepstream",
                    scenario=scenario,
                    distributed=bool(scenario["distributed"]["enabled"]),
                    mode="benchmark",
                )
                self.assertEqual(plan.contract, "strict_native_schema_v2")
                self.assertEqual(plan.runner, "scripts/run_system_template.sh")

    def test_strict_adapter_rejects_unknown_distributed_role(self) -> None:
        scenario = normalize_scenario("distributed_fixture", distributed_fixture())
        scenario["placement"]["stages"]["track"] = "remote"

        with self.assertRaisesRegex(ContractError, "unsupported distributed roles: remote"):
            validate_benchmark_adapter(
                system_key="deepstream",
                scenario=scenario,
                distributed=True,
                mode="benchmark",
            )

    def test_strict_adapter_accepts_checkpoint_local_and_distributed_fixture(self) -> None:
        cfg = load_config(ROOT / "configs" / "experiments.yaml")
        local = normalize_scenario("checkpoint_video_dag_shared", cfg["scenarios"]["checkpoint_video_dag_shared"])
        distributed = normalize_scenario("distributed_fixture", distributed_fixture())

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
        scenario = normalize_scenario("checkpoint_video_dag_shared", cfg["scenarios"]["checkpoint_video_dag_shared"])
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
        scenario = normalize_scenario("distributed_fixture", distributed_fixture())
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
            run_relpath="runs/test/distributed_fixture/streams_6/custom/rep_01",
            duration_s=5,
            streams=6,
            min_objects=1,
            max_objects=12,
        )

        self.assertFalse(context.sync_project)
        self.assertEqual(context.host_topology, "single_host_ssh")
        self.assertEqual([s["role"] for s in steps], ["aggregator", "gpu_worker", "edge"])
        self.assertTrue(all(s["host_label"] == "127.0.0.1" for s in steps))

    def test_builtin_strict_systems_build_role_steps(self) -> None:
        cfg = load_config(ROOT / "configs" / "experiments.yaml")
        scenario = normalize_scenario("distributed_fixture", distributed_fixture())
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
                run_relpath=f"runs/test/distributed_fixture/streams_6/{system}/rep_01",
                duration_s=5,
                streams=6,
                min_objects=1,
                max_objects=12,
                transport=cfg["transport"],
                mode="benchmark",
            )
            self.assertEqual([s["role"] for s in steps], ["aggregator", "gpu_worker", "edge"])
            self.assertTrue(all(f"--system {system}" in s["remote_command"] for s in steps))
            self.assertTrue(all("EXPERIMENT_DISTRIBUTED=1" in s["remote_command"] for s in steps))
            self.assertTrue(all("EXPERIMENT_RTP_PORT_STRIDE=1" in s["remote_command"] for s in steps))
            self.assertTrue(all("DISTRIBUTED_NATIVE_CMD" not in s["remote_command"] for s in steps))
            self.assertTrue(all("setsid bash -lc" in s["remote_command"] for s in steps))
            self.assertTrue(all(">/dev/null 2>&1 &" in s["remote_command"] for s in steps))

    def test_builtin_strict_template_dry_run_commands(self) -> None:
        expectations = {
            "deepstream": ["vast/deepstream-native-probe:7.0", "nvinfer", "/usr/local/bin/vast_native_gst_probe"],
            "savant": ["vast/savant-native-probe:0.5.17-7.0", "/usr/local/bin/vast_native_gst_probe", "nvinfer"],
            "openvino_gva": ["vast_native_gst_probe", "gvadetect", "--input-port-base 5600"],
            "gstreamer_custom": ["GST_CUSTOM_STRICT=1", "--detect-bin identity", "--input-port-base 5600"],
        }
        for system, expected in expectations.items():
            env = os.environ.copy()
            env.update(
                {
                    "REAL_DRY_RUN": "1",
                    "BENCHMARK_MODE": "benchmark",
                    "EXPERIMENT_DISTRIBUTED": "1",
                    "EXPERIMENT_HOST_ROLE": "gpu_worker",
                    "EXPERIMENT_PIPELINE_STAGES": "detect,track",
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
                    "distributed_fixture",
                    "--duration",
                    "5",
                    "--streams",
                    "2",
                    "--min-objects",
                    "1",
                    "--max-objects",
                    "12",
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
                    "EXPERIMENT_PIPELINE_STAGES": ",".join(SHARED_PROOF_PIPELINE),
                }
            )
            completed = subprocess.run(
                [
                    "bash",
                    str(ROOT / "scripts" / "run_system_template.sh"),
                    "--system",
                    system,
                    "--scenario",
                    "checkpoint_video_dag_shared",
                    "--duration",
                    "5",
                    "--streams",
                    "2",
                    "--min-objects",
                    "20",
                    "--max-objects",
                    "80",
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
            if system == "savant":
                self.assertIn("Prewarming Savant local model cache", output)
                self.assertIn("wait_for_telemetry", output)
                self.assertIn("measurement_start_ms", output)
                self.assertIn("measurement_end_ms", output)
                self.assertIn(".cache/savant", output)
                self.assertNotIn("; sleep 5; for pid in $pids", output)

    def test_builtin_templates_dispatch_multistage_local_and_distributed_profiles(self) -> None:
        cases = [
            ("savant", "high_density_multistage", "0", "local", "decode,detect,track,classify,record"),
            ("gstreamer_custom", "edge_worker_aggregator_distributed", "1", "gpu_worker", "detect,track"),
        ]
        for system, scenario, distributed, role, stages in cases:
            with self.subTest(system=system, scenario=scenario):
                env = os.environ.copy()
                env.update(
                    {
                        "REAL_DRY_RUN": "1",
                        "BENCHMARK_MODE": "benchmark",
                        "EXPERIMENT_DISTRIBUTED": distributed,
                        "EXPERIMENT_HOST_ROLE": role,
                        "EXPERIMENT_PIPELINE_STAGES": stages,
                    }
                )
                completed = subprocess.run(
                    [
                        "bash",
                        str(ROOT / "scripts" / "run_system_template.sh"),
                        "--system",
                        system,
                        "--scenario",
                        scenario,
                        "--duration",
                        "5",
                        "--streams",
                        "1",
                        "--min-objects",
                        "1",
                        "--max-objects",
                        "2",
                        "--output",
                        str(ROOT / "runs" / "dry" / scenario / system / "frames.csv"),
                    ],
                    cwd=ROOT,
                    env=env,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                output = completed.stdout + completed.stderr
                self.assertEqual(completed.returncode, 1)
                self.assertNotIn("currently support only canonical", output)
                self.assertIn(stages, output)
                if system == "savant":
                    self.assertIn("stage_files_ready", output)
                    self.assertIn("frame_events_$stage.csv", output)

    def test_custom_cpp_uses_per_stream_frame_ids_for_distributed_preroll(self) -> None:
        body = (ROOT / "deploy" / "custom_cpp_cuda_qt" / "adaptive_scheduler_app.cu").read_text(encoding="utf-8")

        self.assertIn("task.frame_id = frame_idx;", body)
        self.assertNotIn("task.frame_id = stream_id * frames_per_stream_ + frame_idx;", body)

    def test_distributed_edge_preroll_keeps_rtp_producer_alive_for_cold_workers(self) -> None:
        env = os.environ.copy()
        env.update(
            {
                "REAL_DRY_RUN": "1",
                "BENCHMARK_MODE": "benchmark",
                "EXPERIMENT_DISTRIBUTED": "1",
                "EXPERIMENT_HOST_ROLE": "edge",
                "EXPERIMENT_PIPELINE_STAGES": "decode",
                "STARTUP_GRACE_S": "10",
            }
        )
        completed = subprocess.run(
            [
                "bash",
                str(ROOT / "scripts" / "run_system_template.sh"),
                "--system",
                "gstreamer_custom",
                "--scenario",
                "edge_worker_aggregator_distributed",
                "--duration",
                "5",
                "--streams",
                "1",
                "--min-objects",
                "1",
                "--max-objects",
                "2",
                "--output",
                str(ROOT / "runs" / "dry" / "edge_preroll" / "frames.csv"),
            ],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        output = completed.stdout + completed.stderr

        self.assertEqual(completed.returncode, 1)
        self.assertIn("--duration 15", output)

    def test_openvino_local_template_can_force_container_runtime(self) -> None:
        env = os.environ.copy()
        env.update(
            {
                "REAL_DRY_RUN": "1",
                "BENCHMARK_MODE": "benchmark",
                "EXPERIMENT_DISTRIBUTED": "0",
                "EXPERIMENT_HOST_ROLE": "local",
                "EXPERIMENT_PIPELINE_STAGES": ",".join(SHARED_PROOF_PIPELINE),
                "OPENVINO_GVA_FORCE_CONTAINER": "1",
                "DATASET_STREAMS_JSON": '["data/benchmark/mot17_02.mp4"]',
            }
        )
        completed = subprocess.run(
            [
                "bash",
                str(ROOT / "scripts" / "run_system_template.sh"),
                "--system",
                "openvino_gva",
                "--scenario",
                "checkpoint_video_dag_shared",
                "--duration",
                "5",
                "--streams",
                "1",
                "--min-objects",
                "5",
                "--max-objects",
                "35",
                "--output",
                str(ROOT / "runs" / "dry" / "local" / "openvino_container" / "frames.csv"),
            ],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        output = completed.stdout + completed.stderr

        self.assertEqual(completed.returncode, 1)
        self.assertIn("intel/dlstreamer:latest", output)
        self.assertIn("--entrypoint /workspace/project/build/bin/vast_native_gst_probe", output)
        self.assertIn("object_detect", output)
        self.assertIn("/workspace/project/models/openvino", output)
        self.assertIn("data/benchmark/mot17_02.mp4", output)

    def test_openvino_container_fallback_uses_short_finite_input_chunks(self) -> None:
        env = os.environ.copy()
        env.update(
            {
                "REAL_DRY_RUN": "1",
                "BENCHMARK_MODE": "benchmark",
                "EXPERIMENT_DISTRIBUTED": "0",
                "EXPERIMENT_HOST_ROLE": "local",
                "EXPERIMENT_PIPELINE_STAGES": ",".join(SHARED_PROOF_PIPELINE),
                "OPENVINO_GVA_FORCE_CONTAINER": "1",
                "DATASET_STREAMS_JSON": '["data/benchmark/mot17_02.mp4"]',
            }
        )
        completed = subprocess.run(
            [
                "bash",
                str(ROOT / "scripts" / "run_system_template.sh"),
                "--system",
                "openvino_gva",
                "--scenario",
                "checkpoint_video_dag_shared",
                "--duration",
                "16",
                "--streams",
                "1",
                "--min-objects",
                "5",
                "--max-objects",
                "35",
                "--output",
                str(ROOT / "runs" / "dry" / "local" / "openvino_chunks" / "frames.csv"),
            ],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        output = completed.stdout + completed.stderr

        self.assertEqual(completed.returncode, 1)
        self.assertIn("run_openvino_container_chunks.py", output)
        self.assertIn("--chunk-s 15", output)
        self.assertIn("--parallel-streams 1", output)

    def test_openvino_host_fallback_validates_runtime_model_load(self) -> None:
        body = (ROOT / "scripts" / "run_system_template.sh").read_text(encoding="utf-8")

        self.assertIn("openvino_host_runtime_usable", body)
        self.assertIn("videotestsrc num-buffers=1", body)
        self.assertIn("capsrelax ! object_detect", body)
        self.assertIn("OpenVINO host DL Streamer runtime failed model preflight", body)

    def test_savant_local_template_preserves_benchmark_dataset_paths(self) -> None:
        env = os.environ.copy()
        env.update(
            {
                "REAL_DRY_RUN": "1",
                "BENCHMARK_MODE": "benchmark",
                "EXPERIMENT_DISTRIBUTED": "0",
                "EXPERIMENT_HOST_ROLE": "local",
                "EXPERIMENT_PIPELINE_STAGES": ",".join(SHARED_PROOF_PIPELINE),
                "DATASET_STREAMS_JSON": '["data/benchmark/mot17_02.mp4","data/benchmark/mot17_04.mp4"]',
            }
        )
        completed = subprocess.run(
            [
                "bash",
                str(ROOT / "scripts" / "run_system_template.sh"),
                "--system",
                "savant",
                "--scenario",
                "checkpoint_video_dag_shared",
                "--duration",
                "5",
                "--streams",
                "2",
                "--min-objects",
                "5",
                "--max-objects",
                "35",
                "--output",
                str(ROOT / "runs" / "dry" / "local" / "savant_dataset" / "frames.csv"),
            ],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        output = completed.stdout + completed.stderr

        self.assertEqual(completed.returncode, 1)
        self.assertIn("file:///workspace/project/data/benchmark/mot17_02.mp4", output)
        self.assertIn("file:///workspace/project/data/benchmark/mot17_04.mp4", output)
        self.assertNotIn("file:///workspace/project/data/videos/mot17_02.mp4", output)
        self.assertNotIn("file:///workspace/project/data/videos/mot17_04.mp4", output)

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
            self.assertIn("VAST_NATIVE_PROBE_SOURCE_SHA", body)
            self.assertIn('org.vast.native_probe.source_sha="${VAST_NATIVE_PROBE_SOURCE_SHA}"', body)
            self.assertIn("for attempt in 1 2 3 4 5", body)
            self.assertIn("apt-get -o Acquire::Retries=5 update &&", body)
            self.assertIn("apt-get -o Acquire::Retries=5 install -y --fix-missing", body)
            self.assertIn('if [ "$attempt" -eq 5 ]; then exit 1; fi;', body)
            self.assertNotIn("$$attempt", body)
            self.assertIn("-DVAST_BUILD_NATIVE_GST_PROBE=ON", body)
            self.assertIn("-DVAST_BUILD_GSTREAMER_CUSTOM_PLUGIN=OFF", body)
            self.assertIn("-DVAST_BUILD_CUSTOM_CUDA_QT=OFF", body)

        build_script = (ROOT / "scripts" / "build_native_probe_images.sh").read_text(encoding="utf-8")
        self.assertIn("--build-arg VAST_NATIVE_PROBE_SOURCE_SHA", build_script)
        self.assertIn("--label \"$SOURCE_LABEL=", build_script)

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

        self.assertIn("deepstream_edge_pipeline", body)
        self.assertIn("deepstream_local_pipeline", body)
        self.assertIn("deepstream_worker_pipeline", body)
        self.assertIn("return args_.system == \"deepstream\" || args_.system == \"savant\";", body)
        self.assertIn("if (uses_deepstream_elements()) {\n      return deepstream_edge_pipeline(stream_id);", body)
        self.assertIn('set_string_property(pipeline, "uri_src" + std::to_string(stream_id), "uri", uri_for_stream(stream_id));', body)
        self.assertIn("uridecodebin name=uri_src", body)
        self.assertIn("nvurisrcbin name=uri_src", body)
        self.assertIn("file-loop=true", body)
        self.assertIn("! queue ! nvvideoconvert ! video/x-raw,format=I420", body)
        self.assertIn("! identity sync=true ! jpegenc", body)
        self.assertGreaterEqual(body.count("! identity sync=true ! jpegenc"), 2)
        self.assertIn("nvstreammux name=mux", body)
        self.assertIn("! mux\" << stream_id << \".sink_0", body)
        self.assertNotIn("video/x-raw(memory:NVMM),format=NV12 ! nvinfer", body)

    def test_native_probe_builds_dynamic_stage_probes(self) -> None:
        body = (ROOT / "deploy" / "native_gst_probe" / "vast_native_gst_probe.cpp").read_text(encoding="utf-8")

        self.assertIn("stage_names_", body)
        self.assertIn("add_local_stage_probes", body)
        self.assertIn("stage_probe_name", body)
        self.assertIn("stage_base_name", body)
        self.assertIn("generic_stage_operation", body)
        self.assertIn("deepstream_stage_operation", body)
        self.assertIn("write_stage_events", body)
        self.assertIn("ctx->stage", body)
        self.assertIn("videoconvert ! videoscale ! video/x-raw,format=RGB,width=640,height=360", body)
        self.assertIn("jpegenc ! jpegdec", body)
        self.assertIn("sleep-time=1000", body)

    def test_native_probe_handles_rtp_payload_buffer_lists(self) -> None:
        body = (ROOT / "deploy" / "native_gst_probe" / "vast_native_gst_probe.cpp").read_text(encoding="utf-8")

        self.assertIn("GST_PAD_PROBE_TYPE_BUFFER_LIST", body)
        self.assertIn("GST_PAD_PROBE_INFO_TYPE(info) & GST_PAD_PROBE_TYPE_BUFFER_LIST", body)
        self.assertIn("gst_buffer_list_make_writable", body)
        self.assertIn("gst_buffer_list_get_writable", body)
        self.assertIn("&NativeProbeRuntime::input_rtp_probe", body)
        self.assertIn("gst_buffer_list_get(list, index)", body)
        self.assertNotIn("VAST_SKIP_RTP_TRACE_EXTENSION", body)

    def test_native_probe_measurement_timer_starts_on_first_frame_event(self) -> None:
        body = (ROOT / "deploy" / "native_gst_probe" / "vast_native_gst_probe.cpp").read_text(encoding="utf-8")

        self.assertIn("waiting for first frame event", body)
        self.assertIn("start_measurement_timer_if_needed();", body)
        self.assertIn("measurement_started_.compare_exchange_strong", body)
        self.assertGreaterEqual(body.count("events_.flush();"), 2)
        self.assertGreaterEqual(body.count("frames_.flush();"), 2)

    def test_native_probe_stops_before_flushing_telemetry(self) -> None:
        body = (ROOT / "deploy" / "native_gst_probe" / "vast_native_gst_probe.cpp").read_text(encoding="utf-8")

        self.assertIn("stop_pipelines();", body)
        self.assertIn("flush_outputs();", body)
        self.assertIn("std::mutex output_mutex_;", body)

    def test_custom_gstreamer_template_prepends_project_plugin_path(self) -> None:
        body = (ROOT / "scripts" / "run_system_template.sh").read_text(encoding="utf-8")

        self.assertIn('"$PROJECT_DIR/build/lib${GST_PLUGIN_PATH:+:$GST_PLUGIN_PATH}"', body)
        self.assertIn('GST_PLUGIN_PATH=$(gstreamer_custom_plugin_path)', body)
        self.assertIn('video/x-raw,format=RGB ! %s', body)

    def test_custom_cuda_app_uses_monotonic_telemetry_timestamps(self) -> None:
        body = (ROOT / "deploy" / "custom_cpp_cuda_qt" / "adaptive_scheduler_app.cu").read_text(encoding="utf-8")

        self.assertIn("telemetry_timestamp_ms", body)
        self.assertIn("completed_at - task.created_at", body)
        self.assertNotIn("now - task.wall_created_at", body)

    def test_template_rejects_stale_native_probe_images(self) -> None:
        body = (ROOT / "scripts" / "run_system_template.sh").read_text(encoding="utf-8")

        self.assertIn("ensure_native_probe_image_current", body)
        self.assertIn("org.vast.native_probe.source_sha", body)
        self.assertIn("VAST_SKIP_NATIVE_IMAGE_SHA_CHECK", body)
        self.assertIn("Strict native $SYSTEM benchmark image is stale", body)

    def test_savant_local_template_waits_for_native_rows_before_measurement(self) -> None:
        body = (ROOT / "scripts" / "run_system_template.sh").read_text(encoding="utf-8")

        self.assertIn("SAVANT_LOCAL_PREWARM", body)
        self.assertIn("wait_for_csv_rows", body)
        self.assertIn("csv_ready", body)
        self.assertIn("required_stages='${PIPELINE_STAGES}'", body)
        self.assertIn("stage_files_ready()", body)
        self.assertIn("frame_events_\\$stage.csv", body)
        self.assertIn("EXPERIMENT_PIPELINE_STAGES='${PIPELINE_STAGES}'", body)
        self.assertNotIn("currently support only canonical", body)
        self.assertIn("wait_for_telemetry || { rc=\\$?; cleanup", body)
        self.assertIn("mark_measurement_start; sleep ${DURATION_S}; mark_measurement_end", body)
        self.assertIn("measurement_start_ms", body)
        self.assertIn("measurement_end_ms", body)
        self.assertIn("process_alive", body)
        self.assertIn("process exited before telemetry was ready", body)
        self.assertIn("wait_for_csv_rows \\\"\\$host_output/prewarm/frames.csv\\\" 2 'Savant local cache prewarm' \\\"\\$prewarm_pid\\\"", body)
        self.assertIn("pid_at \\\"\\$i\\\" \\$stream_pids", body)

    def test_savant_local_timeout_allows_prewarm_and_shutdown(self) -> None:
        base_env = {"STARTUP_GRACE_S": "180", "SAVANT_LOCAL_SHUTDOWN_GRACE_S": "15"}

        self.assertEqual(
            default_command_timeout_s(
                system_key="deepstream",
                duration_s=30,
                distributed_enabled=False,
                mode="benchmark",
                env=base_env,
            ),
            270,
        )
        self.assertEqual(
            default_command_timeout_s(
                system_key="savant",
                duration_s=30,
                distributed_enabled=False,
                mode="benchmark",
                env=base_env,
            ),
            540,
        )
        self.assertEqual(
            default_command_timeout_s(
                system_key="savant",
                duration_s=30,
                distributed_enabled=False,
                mode="benchmark",
                env={**base_env, "SAVANT_LOCAL_PREWARM": "0"},
            ),
            360,
        )

    def test_dlstreamer_installer_prefers_clean_docker_fallback(self) -> None:
        body = (ROOT / "scripts" / "install_openvino_dlstreamer.sh").read_text(encoding="utf-8")

        self.assertIn("docker create \"$image\" bash -lc 'sleep 600'", body)
        self.assertIn("DLSTREAMER_TRY_INTEL_APT", body)
        self.assertLess(
            body.index("if install_from_intel_dlstreamer_image; then"),
            body.index("Docker fallback failed; trying Intel OpenVINO APT repository"),
        )

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
        first = build_run_seed(20260323, "checkpoint_video_dag_shared", "", 6, 1)
        second = build_run_seed(20260323, "checkpoint_video_dag_shared", "", 6, 1)
        different_repeat = build_run_seed(20260323, "checkpoint_video_dag_shared", "", 6, 2)

        self.assertEqual(first, second)
        self.assertNotEqual(first, different_repeat)

    def test_distributed_plan_maps_roles_to_hosts(self) -> None:
        cfg = load_config(ROOT / "configs" / "experiments.yaml")
        scenario = normalize_scenario("distributed_fixture", distributed_fixture())
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
        self.assertIn(" && { setsid bash -lc", steps[0]["remote_command"])
        self.assertTrue(steps[0]["remote_command"].rstrip().endswith("; }"))


if __name__ == "__main__":
    unittest.main()
