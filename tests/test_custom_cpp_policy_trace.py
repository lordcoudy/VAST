#!/usr/bin/env python3
from __future__ import annotations

import ast
import csv
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ADAPTER_DIR = ROOT / "deploy" / "custom_cpp_cuda_qt"


def feedback_contract_columns() -> list[str]:
    source = (ROOT / "scripts" / "benchmark_contract.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if any(isinstance(target, ast.Name) and target.id == "POLICY_FEEDBACK_COLUMNS" for target in node.targets):
            value = ast.literal_eval(node.value)
            if isinstance(value, list) and all(isinstance(column, str) for column in value):
                return value
    raise AssertionError("POLICY_FEEDBACK_COLUMNS was not found as a literal list")


class CustomCppPolicyTraceTests(unittest.TestCase):
    def compile_and_run(self, source_text: str) -> list[str]:
        compiler = shutil.which("c++")
        if compiler is None:
            self.skipTest("A C++17 compiler is required for the policy trace helper test")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "policy_trace_smoke.cpp"
            binary = root / "policy_trace_smoke"
            source.write_text(textwrap.dedent(source_text), encoding="utf-8")
            subprocess.run(
                [
                    compiler,
                    "-std=c++17",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    "-I",
                    str(ADAPTER_DIR),
                    str(source),
                    "-o",
                    str(binary),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            return subprocess.check_output([str(binary)], text=True).splitlines()

    def test_format_helpers_emit_valid_json_and_csv(self) -> None:
        lines = self.compile_and_run(
            r'''
                    #include <iostream>
                    #include <limits>
                    #include "policy_trace_format.hpp"

                    int main() {
                      std::cout << vast_policy_trace::csv_escape("{\"cpu\":1,\"gpu\":2}") << '\n';
                      std::cout << vast_policy_trace::json_quote("line\n\"value") << '\n';
                      std::cout << vast_policy_trace::json_number(1.25) << '\n';
                      try {
                        (void)vast_policy_trace::json_number(std::numeric_limits<double>::quiet_NaN());
                      } catch (const std::runtime_error&) {
                        std::cout << "nonfinite-rejected\n";
                      }
                      return 0;
                    }
            '''
        )

        self.assertEqual(next(csv.reader([lines[0]])), ['{"cpu":1,"gpu":2}'])
        self.assertEqual(json.loads(lines[1]), 'line\n"value')
        self.assertEqual(float(lines[2]), 1.25)
        self.assertEqual(lines[3], "nonfinite-rejected")

    def test_weighted_proxy_core_is_deterministic_and_directionally_consistent(self) -> None:
        lines = self.compile_and_run(
            r'''
            #include <iostream>
            #include "weighted_proxy_policy.hpp"

            int main() {
              using namespace vast_weighted_proxy;
              DecisionInput minimum;
              minimum.cpu_profile_proxy_ms = 2.0;
              minimum.gpu_profile_proxy_ms = 1.0;
              const Decision minimum_result = choose(minimum);
              std::cout << (minimum_result.selected == Resource::Gpu) << ','
                        << minimum_result.cpu_score_ms << ',' << minimum_result.gpu_score_ms << ','
                        << minimum_result.reason << '\n';

              DecisionInput queue_tie;
              queue_tie.cpu_profile_proxy_ms = 1.0;
              queue_tie.gpu_profile_proxy_ms = 0.5;
              queue_tie.gpu_queue_depth = 1;
              const Decision queue_result = choose(queue_tie);
              std::cout << (queue_result.selected == Resource::Cpu) << ',' << queue_result.reason << '\n';

              DecisionInput preference_tie;
              preference_tie.cpu_profile_proxy_ms = 1.0;
              preference_tie.gpu_profile_proxy_ms = 1.0;
              preference_tie.stage_preference = Resource::Gpu;
              const Decision preference_result = choose(preference_tie);
              std::cout << (preference_result.selected == Resource::Gpu) << ','
                        << preference_result.reason << '\n';

              const UpdateSignal late = classify_update(120.0, 100.0, 2);
              const UpdateSignal stable = classify_update(80.0, 100.0, 0);
              const UpdateSignal unassigned = classify_update(120.0, 100.0, 0);
              std::cout << (update_delta(late) > 0.0) << ','
                        << (update_delta(stable) < 0.0) << ','
                        << (unassigned == UpdateSignal::None) << ','
                        << apply_weight_delta(1.499, update_delta(late)) << ','
                        << apply_weight_delta(0.5001, update_delta(stable)) << '\n';

              const WeightPair projected = project_box_mean_one(
                  WeightPair{1.0, 1.4}, WeightPair{0.5, 0.5}, WeightPair{1.5, 1.5});
              std::cout << projected.cpu << ',' << projected.gpu << ','
                        << mean_one(projected) << ','
                        << l1_variation(WeightPair{1.0, 1.0}, projected) << '\n';

              FeedbackGateInput gate;
              gate.signal = UpdateSignal::PenalizeGpu;
              gate.lag_limit = 8;
              gate.events_since_update = 1;
              gate.cooldown_events = 2;
              gate.candidate_variation = 0.4;
              gate.variation_budget = 0.5;
              std::cout << evaluate_feedback_gate(gate).reason << ',';
              gate.events_since_update = 2;
              const FeedbackGateDecision apply = evaluate_feedback_gate(gate);
              std::cout << apply.apply << ',' << apply.reason << ',';
              gate.variation_before = 0.2;
              std::cout << evaluate_feedback_gate(gate).reason << ',';
              gate.variation_before = 0.0;
              gate.has_first_consumer = false;
              std::cout << evaluate_feedback_gate(gate).reason << '\n';
              return 0;
            }
            '''
        )

        self.assertEqual(lines[0], "1,2,1,minimum_weighted_proxy_score")
        self.assertEqual(lines[1], "1,score_tie_lower_queue_depth")
        self.assertEqual(lines[2], "1,score_tie_stage_preference")
        direction = lines[3].split(",")
        self.assertEqual(direction[:3], ["1", "1", "1"])
        self.assertEqual(float(direction[3]), 1.5)
        self.assertEqual(float(direction[4]), 0.5)
        projection = lines[4].split(",")
        self.assertAlmostEqual(float(projection[0]), 0.8)
        self.assertAlmostEqual(float(projection[1]), 1.2)
        self.assertEqual(projection[2], "1")
        self.assertAlmostEqual(float(projection[3]), 0.4)
        self.assertEqual(
            lines[5],
            "cooldown_active,1,prototype_deadline_miss_with_gpu_backlog,"
            "variation_budget_exhausted,no_subsequent_decision_before_end",
        )

    def test_adapter_labels_trace_as_simplified_native_proxy(self) -> None:
        source = (ADAPTER_DIR / "adaptive_scheduler_app.cu").read_text(encoding="utf-8")
        core = (ADAPTER_DIR / "weighted_proxy_policy.hpp").read_text(encoding="utf-8")
        for required in (
            "policy_decisions.csv",
            "simplified-cpu-gpu-weighted-proxy-v4-",
            "native_scheduler_trace",
            '"full"',
            "weighted_proxy_policy.hpp",
            "decision_id",
            "feature_provenance_json",
            "source_decision_ids_json",
            "causal_trace_completeness",
            'terminal_status = "completed"',
            "task.applied_decision_ids",
            "task.max_applied_gpu_queue_depth",
            "task.oldest_applied_parameter_snapshot_seq",
            "policy_feedback.csv",
            "native_terminal_feedback",
            "flush_pending_policy_feedback_locked",
            "feedback_update_rule",
            "stage_preference",
        ):
            self.assertIn(required, source)
        for required in (
            "prototype_deadline_miss_with_gpu_backlog",
            "prototype_on_time_with_empty_gpu_queue",
        ):
            self.assertIn(required, core)
        self.assertNotIn("aw-heft-v", source.lower())

        header_line = next(
            line.strip()
            for line in source.splitlines()
            if line.strip().startswith('feedback << "schema_version,')
        )
        emitted_header = header_line.split('"', 2)[1].removesuffix(r"\n").split(",")
        self.assertEqual(emitted_header, feedback_contract_columns())

    def test_frozen_policy_artifact_is_reproducible_and_normalized(self) -> None:
        artifact = ROOT / "policies" / "ql_heft_frozen.policy"
        digest_file = artifact.with_suffix(artifact.suffix + ".sha256")
        with tempfile.TemporaryDirectory() as tmp:
            generated = Path(tmp) / artifact.name
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "train_ql_heft.py"),
                    "--seed",
                    "14700",
                    "--episodes",
                    "10000",
                    "--output",
                    str(generated),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(generated.read_bytes(), artifact.read_bytes())
            self.assertEqual(
                generated.with_suffix(generated.suffix + ".sha256").read_text(encoding="utf-8"),
                digest_file.read_text(encoding="utf-8"),
            )

        payload = artifact.read_bytes()
        expected_digest = digest_file.read_text(encoding="utf-8").split()[0]
        self.assertEqual(hashlib.sha256(payload).hexdigest(), expected_digest)
        values = dict(
            line.split("=", 1)
            for line in payload.decode("utf-8").splitlines()
            if line
        )
        self.assertEqual(values["schema_version"], "2")
        self.assertAlmostEqual(
            float(values["cpu_queue_weight"]) + float(values["gpu_queue_weight"]),
            2.0,
        )
        self.assertEqual(values["projection_rule"], "euclidean_box_mean_one_v1")
        self.assertEqual(
            values["feedback_update_rule"],
            "simplified_gpu_queue_terminal_signal_v1",
        )


if __name__ == "__main__":
    unittest.main()
