"""Amendment 9 (F5): host-only policy pilot validator used by F1 policy-assess/policy-promote.

The stock and the F5 validators run on the same arm with stubbed sidecar validators, so the
two semantic changes are compared directly: sidecars revalidated with reset evidence and six
streams; a GPU decision of a frame dropped at ingress without a transfer interval is not a
calibration sample.
"""
from __future__ import annotations

import contextlib
import difflib
import hashlib
import inspect
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
for _path in (ROOT, ROOT / "scripts"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import benchmark_contract  # noqa: E402
import publication_acceptance_evidence  # noqa: E402
import publication_policy_qualification as stock  # noqa: E402
import publication_qualification_promotion_v2 as promotion  # noqa: E402
import topology_contract  # noqa: E402


# The stock module is pinned by the attempt-4 execution code closure; F5 is reviewed against it.
STOCK_SHA256 = "f4478804491922c3e25ab414ba8f000c1964b46633f9dfb3a5bc87212748dbde"
EXPECTED_DIFF = """\
--- stock
+++ f5
@@ -1 +1 @@
-def _default_pilot_validator(pilot: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
+def policy_pilot_validator(pilot: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
@@ -121,0 +122,2 @@
+            require_reset_evidence=True,
+            expected_streams=6,
@@ -159,0 +162,4 @@
+    ingress_status = {
+        str(row["trace_id"]): str(row["terminal_status"])
+        for row in sidecars["ingress_ledger"].to_dict(orient="records")
+    }
@@ -199,0 +206,2 @@
+            if ingress_status.get(trace_id) == "drop":
+                continue
"""
ROLE_FILES = {
    "checkpoint_acceptance": "checkpoint_qualification_pilot_acceptance.json",
    "policy_decisions_jsonl": "publication_policy_decisions.jsonl",
    "resource_intervals": "resource_intervals.csv",
    "ingress_ledger": "ingress_ledger.csv",
    "topology_events": "topology_events.csv",
    "frames": "frames.csv",
    "frame_events": "frame_events.csv",
    "branch_terminals": "branch_terminals.csv",
}
SOURCE = "a" * 64


class _Policy:
    ANALYTICS_BRANCHES = ("plate_number", "damage")

    @staticmethod
    def validate_decision_record(record: dict, manifest: dict) -> dict:
        del manifest
        ok = record.get("replay") != "fail"
        return {"passed": ok, "blockers": [] if ok else ["replay mismatch"]}


def _decision(trace: str, branch: str, resource: str, **extra) -> dict:
    value = {
        "decision_id": f"decision-{trace}-{branch}", "trace_id": trace, "branch": branch,
        "selected_resource": resource, "system": "deepstream",
        "native_decision_evidence": {"event_id": f"event-{trace}-{branch}", "actual_service_ms": 2.5},
    }
    value.update(extra)
    return value


class _Arm:
    """One pilot arm: decision JSONL plus the sidecar frames the stubs return."""

    def __init__(self, root: Path, resource: str, decisions: list[dict], *, ingress: dict[str, str],
                 transfer: set[tuple[str, str]], csv_rows: dict[str, dict] | None = None) -> None:
        self.root = root
        self.arm = root / "pilots/deepstream" / resource / "h264/independent_processes"
        self.arm.mkdir(parents=True)
        self.pilot = {"system": "deepstream", "resource": resource, "codec": "h264",
                      "topology_kind": "independent_processes"}
        self.paths = {}
        for role, name in ROLE_FILES.items():
            path = self.arm / name
            path.write_text(f"{role}\n", encoding="utf-8")
            self.paths[role] = path
        self.paths["policy_decisions_jsonl"].write_text(
            "".join(json.dumps(record) + "\n" for record in decisions), encoding="utf-8")
        hashes = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                  for role, path in self.paths.items() if role not in {"checkpoint_acceptance", "policy_decisions_jsonl"}}
        self.acceptance = {
            "run_id": "run-fixture", "scenario": "checkpoint_independent_processes_baseline",
            "evidence_sha256": hashes,
            "full_resource_summary": {"evidence_accepted": True, "publication_bundle_bound": True,
                                      "full_resource_coverage_complete": True},
            "full_resource_finalization": {"hardware_collector_stopped": True,
                                           "validation": "full_resource_evidence_v2_passed",
                                           "prepared_by": "prepare_checkpoint_publication_acceptance"},
        }
        rows = csv_rows or {}
        self.sidecars = {
            "policy_decisions": pd.DataFrame([
                rows.get(record["decision_id"], {"decision_id": record["decision_id"], "trace_id": record["trace_id"],
                                                 "stage": record["branch"], "resource": record["selected_resource"]})
                for record in decisions
            ]),
            "branch_terminals": pd.DataFrame([
                {"trace_id": record["trace_id"], "branch_id": record["branch"], "terminal_status": "completed"}
                for record in decisions
            ]),
            "resource_intervals": pd.DataFrame(
                [{"component": "transfer", "trace_id": trace, "branch_id": branch, "duration_ns": 1_500_000}
                 for trace, branch in sorted(transfer)]
                + [{"component": "nvdec_submit_complete", "trace_id": "other", "branch_id": "plate_number",
                    "duration_ns": 1}],
            ),
            "ingress_ledger": pd.DataFrame([
                {"trace_id": trace, "terminal_status": status, "source_sha256": SOURCE}
                for trace, status in ingress.items()
            ]),
        }
        self.sidecar_calls: list[dict] = []

    @contextlib.contextmanager
    def stubs(self):
        def sidecars(run_dir, **kwargs):
            self.sidecar_calls.append(kwargs)
            return self.sidecars

        paths = dict(self.paths)
        with contextlib.ExitStack() as stack:
            for module in (stock, promotion):
                for name, value in (
                    ("_validate_evidence_descriptors", lambda root, pilot: dict(paths)),
                    ("validate_checkpoint_qualification_pilot_acceptance_v1", lambda **_kwargs: dict(self.acceptance)),
                ):
                    if hasattr(module, name):
                        stack.enter_context(mock.patch.object(module, name, value))
            stack.enter_context(mock.patch.object(
                publication_acceptance_evidence, "accepted_arm_evidence_files",
                lambda *_args, **_kwargs: set(self.acceptance["evidence_sha256"])))
            stack.enter_context(mock.patch.object(benchmark_contract, "canonicalize_frames_csv", lambda *a, **k: pd.DataFrame()))
            stack.enter_context(mock.patch.object(benchmark_contract, "validate_frame_events", lambda *a, **k: pd.DataFrame()))
            stack.enter_context(mock.patch.object(benchmark_contract, "validate_required_sidecars", sidecars))
            stack.enter_context(mock.patch.object(
                benchmark_contract, "load_dataset", lambda *a, **k: {"streams": [{"resolved_sha256": SOURCE}]}))
            stack.enter_context(mock.patch.object(topology_contract, "validate_topology_events", lambda *a, **k: pd.DataFrame()))
            yield

    def context(self) -> dict:
        dataset = self.root / "configs/datasets.yaml"
        dataset.parent.mkdir(parents=True, exist_ok=True)
        dataset.write_text("datasets: {}\n", encoding="utf-8")
        return {"project_root": self.root, "policy": _Policy, "capability_manifest": {}, "bindings": {},
                "dataset_manifest": {"path": "configs/datasets.yaml"}}

    def run(self, validator) -> list[dict]:
        with self.stubs():
            return validator(dict(self.pilot), self.context())


class PolicyPilotValidatorV2Tests(unittest.TestCase):
    def arm(self, resource: str, decisions: list[dict], **kwargs) -> _Arm:
        temporary = tempfile.TemporaryDirectory(prefix="policy-pilot-v2-")
        self.addCleanup(temporary.cleanup)
        return _Arm(Path(temporary.name).resolve(), resource, decisions, **kwargs)

    def test_sidecars_are_revalidated_with_reset_evidence_and_six_streams(self) -> None:
        arm = self.arm("cpu", [_decision("t1", "plate_number", "cpu"), _decision("t1", "damage", "cpu")],
                       ingress={"t1": "completed"}, transfer=set())
        arm.run(promotion.policy_pilot_validator)
        self.assertEqual(len(arm.sidecar_calls), 1)
        self.assertIs(arm.sidecar_calls[0]["require_reset_evidence"], True)
        self.assertEqual(arm.sidecar_calls[0]["expected_streams"], 6)

    def test_dropped_gpu_decision_without_transfer_is_not_a_sample(self) -> None:
        decisions = [_decision("t1", "plate_number", "gpu"), _decision("t1", "damage", "gpu"),
                     _decision("t2", "plate_number", "gpu"), _decision("t2", "damage", "gpu")]
        arm = self.arm("gpu", decisions, ingress={"t1": "completed", "t2": "drop"},
                       transfer={("t1", "plate_number"), ("t1", "damage"), ("t2", "damage")})
        samples = arm.run(promotion.policy_pilot_validator)
        self.assertEqual(sorted((row["trace_id"], row["branch"]) for row in samples),
                         [("t1", "damage"), ("t1", "plate_number"), ("t2", "damage")])
        self.assertTrue(all(row["transfer_ms"] > 0 for row in samples))
        with self.assertRaisesRegex(stock.QualificationError, "lacks native transfer interval"):
            arm.run(stock._default_pilot_validator)

    def test_completed_or_unknown_gpu_decision_without_transfer_is_refused(self) -> None:
        for trace, ingress in (("t1", {"t1": "completed"}), ("t1", {"t1": "censored"}), ("t9", {"t1": "completed"})):
            with self.subTest(ingress=ingress, trace=trace):
                arm = self.arm("gpu", [_decision(trace, "plate_number", "gpu")], ingress=ingress, transfer=set())
                with self.assertRaisesRegex(stock.QualificationError, "lacks native transfer interval"):
                    arm.run(promotion.policy_pilot_validator)

    def test_dropped_decision_is_still_fully_validated(self) -> None:
        cases = {
            "replay": [_decision("t2", "plate_number", "gpu", replay="fail")],
            "cell": [_decision("t2", "plate_number", "gpu", system="savant")],
        }
        for name, decisions in cases.items():
            with self.subTest(case=name):
                arm = self.arm("gpu", decisions, ingress={"t2": "drop"}, transfer=set())
                with self.assertRaises(stock.QualificationError):
                    arm.run(promotion.policy_pilot_validator)
        linkage = {"decision-t2-plate_number": {"decision_id": "decision-t2-plate_number", "trace_id": "t-other",
                                                "stage": "plate_number", "resource": "gpu"}}
        arm = self.arm("gpu", [_decision("t2", "plate_number", "gpu")], ingress={"t2": "drop"},
                       transfer=set(), csv_rows=linkage)
        with self.assertRaisesRegex(stock.QualificationError, "linkage mismatch"):
            arm.run(promotion.policy_pilot_validator)

    def test_cpu_and_gpu_with_transfer_samples_equal_stock(self) -> None:
        for resource in ("cpu", "gpu"):
            with self.subTest(resource=resource):
                decisions = [_decision(trace, branch, resource)
                             for trace in ("t1", "t2") for branch in _Policy.ANALYTICS_BRANCHES]
                transfer = {(trace, branch) for trace in ("t1", "t2") for branch in _Policy.ANALYTICS_BRANCHES}
                arm = self.arm(resource, decisions, ingress={"t1": "completed", "t2": "drop"},
                               transfer=transfer if resource == "gpu" else set())
                self.assertEqual(arm.run(promotion.policy_pilot_validator), arm.run(stock._default_pilot_validator))

    def test_copy_differs_from_stock_only_by_the_reviewed_hunks(self) -> None:
        stock_path = ROOT / "scripts/publication_policy_qualification.py"
        self.assertEqual(hashlib.sha256(stock_path.read_bytes()).hexdigest(), STOCK_SHA256)
        diff = "".join(difflib.unified_diff(
            inspect.getsource(stock._default_pilot_validator).splitlines(keepends=True),
            inspect.getsource(promotion.policy_pilot_validator).splitlines(keepends=True),
            "stock", "f5", n=0))
        self.assertEqual(diff, EXPECTED_DIFF)
        self.assertEqual(Path(inspect.getsourcefile(promotion.policy_pilot_validator)).name,
                         "publication_qualification_promotion_v2.py")


class PolicyCommandsUseF5Tests(unittest.TestCase):
    def test_policy_assess_and_promote_pass_the_f5_validator(self) -> None:
        argv = ["--project-root", "/r", "--qualification-transaction-receipt", "/r/t.json", "--index-path", "/r/i.json"]
        for system in promotion.SYSTEMS:
            argv += [f"--{system.replace('_', '-')}-fragment", f"/r/{system}.json"]
        root = Path("/r")
        with mock.patch.object(promotion, "_transaction", return_value=(root, {}, {})), \
                mock.patch.object(promotion, "_require_policy_index"), \
                mock.patch.object(promotion.policy_qualification, "assess_policy_qualification",
                                  return_value={"passed": True}) as assess, \
                mock.patch.object(promotion.policy_qualification, "promote_policy_qualification",
                                  return_value={"passed": True}) as promote, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(promotion.main(["policy-assess", *argv]), 0)
            self.assertEqual(promotion.main(["policy-promote", *argv, "--output-dir", "/r/out"]), 0)
        self.assertIs(assess.call_args.kwargs["pilot_validator"], promotion.policy_pilot_validator)
        self.assertIs(promote.call_args.kwargs["pilot_validator"], promotion.policy_pilot_validator)


if __name__ == "__main__":
    unittest.main()
