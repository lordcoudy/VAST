"""Local four-wrapper composition; mocked CLI, no image or acceptance proof."""
from __future__ import annotations

import hashlib
import importlib
import json
import os
from dataclasses import replace
from types import SimpleNamespace
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from publication_operational_request_domain_v1 import canonical_json_v1, payload_with_sha256_v1
from tests.test_publication_operational_request_domain_v1 import native_fixture, native_header
from publication_operational_runtime_context_v1 import operational_output_dir_v1

MODE = "bounded_native_diagnostic_operational_v1"
RULE = "request_output_dir_sibling_v1"
NAME = "native_operational_requests.v1.jsonl"
SYSTEMS = {
    "gstreamer_custom": ("test_checkpoint_gstreamer_custom_publication_runtime_v3", "GstreamerPublicationRuntimeV3Tests", "checkpoint_gstreamer_publication_runtime_v3"),
    "openvino_gva": ("test_checkpoint_openvino_gva_publication_runtime_v3", "OpenVINOGVAPublicationRuntimeV3Tests", "checkpoint_openvino_gva_publication_runtime_v3"),
    "deepstream": ("test_checkpoint_deepstream_publication_runtime_v3", "DeepStreamPublicationRuntimeV3Tests", "checkpoint_deepstream_publication_runtime_v3"),
    "savant": ("test_checkpoint_savant_publication_runtime_v3", "SavantPublicationRuntimeV3Tests", "checkpoint_savant_publication_runtime_v3"),
}


def _json(value):
    return canonical_json_v1(value) + b"\n"


def _mounts(argv):
    rows = []
    for index, token in enumerate(argv[:-1]):
        if token == "--mount":
            rows.append(dict(part.split("=", 1) if "=" in part else (part, True)
                             for part in argv[index + 1].split(",")))
    return rows


@unittest.skipUnless(os.name == "posix", "Actual v3 file/mount custody is Linux-only")
class OperationalWrapperCompositionTests(unittest.TestCase):
    def fixture(self, system):
        test_name, class_name, runtime_name = SYSTEMS[system]
        module = importlib.import_module("tests." + test_name)
        fixture = getattr(module, class_name)("runTest")
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        runtime = importlib.import_module(runtime_name)
        request = fixture.request
        # Keep one ordinary parent below the ancestor used by the custody
        # regression: a leaf-only symlink check cannot establish this path.
        output = fixture.output.parent / "nested" / fixture.output.name
        output.parent.mkdir(mode=0o700)
        fixture.output.rename(output)
        fixture.output = output
        fixture.arm_path = output / request.arm_contract_path.name
        request = replace(request, output_dir=output, arm_contract_path=fixture.arm_path)
        request.runtime_inputs["output_dir"] = str(output)
        request.runtime_inputs["arm_contract_path"] = str(fixture.arm_path)
        fixture.request = request
        # Existing CLI fixtures are prepared before the immutable snapshot.
        # They confer no real image/model/publication grant.
        request.runtime_inputs["deadline_ms"] = 100.0
        contract = fixture.runtime_contract
        scratch = fixture.root / "owned-wrapper-scratch"
        scratch.mkdir(mode=0o700)
        contract["scratch_root"] = str(scratch)
        prototype, records = native_fixture()
        header = native_header(prototype, records)
        for key in ("run_id", "arm_id", "system", "scenario"):
            header[key] = getattr(request, key)
        for key in ("codec", "policy", "deadline_ms"):
            header[key] = request.runtime_inputs[key]
        header["counts"] = dict.fromkeys(header["counts"], 0)
        header = payload_with_sha256_v1(header)
        limits = {"max_admissions_per_stream": 241 if system in {"gstreamer_custom", "openvino_gva"} else 281,
                  "min_schedule_step_ns": 999_999_600}
        document = payload_with_sha256_v1({"schema_version": 1,
            "artifact_kind": "vast_native_operational_capture_context_v1", "mode": MODE,
            "native_header": header, "admission_limits": limits})
        source = fixture.root / "runtime/operational-context.json"
        source.parent.mkdir(parents=True, exist_ok=True)
        raw = _json(document)
        source.write_bytes(raw)
        container_root = "/workspace/project" if system in {"gstreamer_custom", "openvino_gva"} else "/opt/vast/input"
        contract["files"]["operational_request_context"] = {
            "path": "runtime/operational-context.json",
            "container_path": container_root + "/runtime/operational-context.json",
            "size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
        }
        contract["operational_capture"] = {"mode": MODE, "output_dir": RULE}
        fixture.context_source = source
        fixture.context_bytes = raw
        fixture.operational_bytes = _json({"artifact_kind": "vast_local_mocked_cli_capture_v1",
                                           "system": system, "physical_model_inference": False})
        fixture.legacy_bytes = _json({"artifact_kind": "vast_local_mocked_cli_legacy_v1", "system": system})
        fixture.before = _json(request.runtime_inputs)
        fixture.scratch = scratch
        fixture.main_calls = []
        fixture.module = module
        fixture.runtime = runtime
        runner_system = "gstreamer" if system == "gstreamer_custom" else system
        fixture.runner = getattr(runtime, "run_checkpoint_" + runner_system + "_publication_runtime_v3")
        fixture.capture_target = request.output_dir.with_name(request.output_dir.name + ".operational")
        return fixture

    def invoke(self, fixture, *, mode="success", mutate_ancestor=False):
        def run(engine, engine_socket, argv, timeout_s):
            os.fstat(engine.fd)
            if argv[:2] == ("image", "inspect"):
                projection = getattr(fixture, "inspect_projection", None)
                if projection is None:
                    projection = fixture.inspect_payload
                return mock.Mock(returncode=0, stdout=_json([projection]), stderr=b"")
            if "/usr/bin/sha256sum" in argv:
                artifacts = fixture.runtime_contract["embedded_artifacts"]
                return mock.Mock(returncode=0, stdout="".join(f"{digest}  {path}\n" for path, digest in artifacts.items()).encode(), stderr=b"")
            probe = fixture.runtime_contract["files"].get("device_probe")
            if probe is not None and probe["container_path"] in argv:
                if fixture.request.system == "openvino_gva":
                    raw = fixture.module.canonical(fixture.device_probe)
                else:
                    raw = fixture.runtime._canonical(fixture.device_probe)
                return mock.Mock(returncode=0, stdout=raw, stderr=b"")
            if "/usr/bin/nvidia-smi" in argv:
                raw = b"NVIDIA GeForce RTX 3060, GPU-00bb784b-60f3-8bf6-bbd3-5a0c09805266, 610.47\n"
                return mock.Mock(returncode=0, stdout=raw, stderr=b"")
            fixture.main_calls.append(argv)
            mounts = _mounts(argv)
            output = Path(next(row["src"] for row in mounts if row.get("dst") == "/opt/vast/output"))
            capture = Path(next(row["src"] for row in mounts if row.get("dst") == "/opt/vast/operational"))
            self.assertNotEqual(output, capture)
            self.assertEqual(capture.parent, output.parent)
            self.assertTrue(capture.is_dir())
            self.assertFalse(next(row for row in mounts if row.get("dst") == "/opt/vast/operational").get("readonly", False))
            self.assertEqual(argv[argv.index("--operational-output-dir") + 1], "/opt/vast/operational")
            context = argv[argv.index("--operational-request-context") + 1]
            binding = max((row for row in mounts if context.startswith(str(row.get("dst")) + "/")), key=lambda row: len(row["dst"]))
            actual_context = Path(binding["src"]) / context[len(binding["dst"]) + 1:]
            self.assertEqual(actual_context.read_bytes(), fixture.context_bytes)
            self.assertEqual(_json(fixture.request.runtime_inputs), fixture.before)
            (capture / NAME).write_bytes(fixture.operational_bytes)
            (output / fixture.module.EVIDENCE_NAME).write_bytes(fixture.legacy_bytes)
            if mode == "unexpected_legacy":
                (output / "foreign-extra.json").write_bytes(b"foreign\n")
            if mutate_ancestor:
                parent = fixture.request.output_dir.parent.parent
                fixture.alias_ancestor = parent
                fixture.original_parent = parent.with_name(parent.name + ".original")
                fixture.foreign_parent = fixture.root / "foreign-parent"
                fixture.foreign_parent.mkdir()
                (fixture.foreign_parent / fixture.request.output_dir.parent.name).mkdir()
                parent.rename(fixture.original_parent)
                parent.symlink_to(fixture.foreign_parent, target_is_directory=True)
            if mode == "failed":
                return mock.Mock(returncode=23, stdout=b"original child stdout", stderr=b"original child failure")
            acceptance = {"status": "accepted_native_checkpoint_arm", "run_id": fixture.request.run_id,
                "system": fixture.request.system, "scenario": fixture.request.scenario,
                "topology_kind": fixture.request.topology_kind, "codec": fixture.request.runtime_inputs["codec"],
                "policy": fixture.request.runtime_inputs["policy"], "deadline_ms": 100.0}
            status = {"schema_version": 3,
                "artifact_kind": "vast_" + fixture.request.system + "_publication_terminal_status_v3",
                "run_id": fixture.request.run_id, "arm_id": fixture.request.arm_id,
                "system": fixture.request.system, "scenario": fixture.request.scenario,
                "topology_kind": fixture.request.topology_kind, "codec": "h264", "policy": "cpu_only",
                "deadline_ms": 100.0, "accepted_benchmark_sidecars_written": True,
                "publication_blockers": [], "publication_acceptance": acceptance}
            return mock.Mock(returncode=0, stdout=_json(status), stderr=b"")
        return run

    def test_all_four_active_wrappers_copy_separately_and_leave_original_inputs_unchanged(self):
        for system in SYSTEMS:
            with self.subTest(system=system):
                fixture = self.fixture(system)
                with mock.patch.object(fixture.runtime, "_invoke_engine", side_effect=self.invoke(fixture)):
                    result = fixture.runner(fixture.request)
                self.assertEqual(result.exit_code, 0)
                self.assertEqual(len(fixture.main_calls), 1)
                self.assertEqual((fixture.capture_target / NAME).read_bytes(), fixture.operational_bytes)
                self.assertEqual((fixture.request.output_dir / fixture.module.EVIDENCE_NAME).read_bytes(), fixture.legacy_bytes)
                self.assertEqual({path.name for path in fixture.request.output_dir.iterdir()},
                    {"backend_publication_arm_contract.json", fixture.module.EVIDENCE_NAME})
                self.assertEqual(_json(fixture.request.runtime_inputs), fixture.before)
                self.assertEqual(fixture.context_source.read_bytes(), fixture.context_bytes)
                self.assertEqual(list(fixture.scratch.iterdir()), [])

    def test_materializer_bound_primary_context_composes_with_all_four_actual_wrappers(self):
        materializer = importlib.import_module("publication_policy_qualification_runtime_inputs_v2")
        for system in SYSTEMS:
            with self.subTest(system=system):
                fixture = self.fixture(system)
                context = json.loads(fixture.context_bytes)
                pins = {}
                for header_role, file_role in (("capability_manifest", "policy_capability_manifest"),
                                               ("calibration", "policy_calibration")):
                    descriptor = fixture.runtime_contract["files"][file_role]
                    plain = {key: descriptor[key] for key in ("path", "size_bytes", "sha256")}
                    pin = materializer._descriptor_pin(fixture.root, plain, label="original local wrapper " + header_role)
                    pins[header_role] = pin
                    context["native_header"]["descriptors"][header_role] = plain
                context["native_header"] = payload_with_sha256_v1(context["native_header"])
                context = payload_with_sha256_v1(context)
                fixture.context_bytes = _json(context)
                fixture.context_source.write_bytes(fixture.context_bytes)
                descriptor = {"path": fixture.context_source.relative_to(fixture.root).as_posix(),
                              "size_bytes": len(fixture.context_bytes),
                              "sha256": hashlib.sha256(fixture.context_bytes).hexdigest()}
                cell = SimpleNamespace(**{key: getattr(fixture.request, key) for key in
                    ("run_id", "arm_id", "system", "scenario")},
                    **{key: fixture.request.runtime_inputs[key] for key in ("codec", "policy", "deadline_ms")})
                operation = dict(cell.__dict__, phase="diagnostic", warmup_s=30.0, measurement_s=180.0,
                                 drain_timeout_s=10.0, streams=6, branches=4)
                plan = {"index": {"mode": MODE}, "runtime_contexts_by_arm": {
                    cell.arm_id: {"operation": operation, "context": context, "descriptor": descriptor}}}
                inputs = SimpleNamespace(root=fixture.root, candidate_manifest=pins["capability_manifest"],
                                         calibrations={system: pins["calibration"]})
                original = fixture.runtime_contract
                del original["operational_capture"]
                del original["files"]["operational_request_context"]
                before = _json(original)
                bound = materializer._bind_operational_context_for_cell(cell=cell, inputs=inputs,
                    contract=original, capture_plan=plan)
                self.assertEqual(_json(original), before)
                fixture.runtime_contract = bound
                fixture.request.runtime_inputs["dataset"][system + "_publication_runtime_v3"] = bound
                fixture.before = _json(fixture.request.runtime_inputs)
                with mock.patch.object(fixture.runtime, "_invoke_engine", side_effect=self.invoke(fixture)):
                    result = fixture.runner(fixture.request)
                self.assertEqual(result.exit_code, 0)
                self.assertEqual(len(fixture.main_calls), 1)
                self.assertEqual((fixture.capture_target / NAME).read_bytes(), fixture.operational_bytes)
                self.assertEqual(_json(original), before)
                self.assertEqual(_json(fixture.request.runtime_inputs), fixture.before)

    def test_physical_37_operation_builder_absolute_context_binds_all_four_wrappers(self):
        materializer = importlib.import_module("publication_policy_qualification_runtime_inputs_v2")
        builder = importlib.import_module("publication_operational_capture_plan_v1")
        planner_tests = importlib.import_module("tests.test_publication_operational_capture_plan_v1")
        planner_tests.CapturePlanTests.setUpClass()
        for system in SYSTEMS:
            with self.subTest(system=system):
                fixture = self.fixture(system)
                planner = planner_tests.CapturePlanTests("runTest")
                planner.root = fixture.root
                (fixture.root / "inputs").mkdir(exist_ok=True)
                (fixture.root / "outputs").mkdir(exist_ok=True)
                planner.calls = []
                planner.guardian = {
                    role: planner.write("inputs/" + role + ".json",
                        {"fixture_only": True, "role": role})
                    for role in planner_tests.GUARDIAN_ROLES
                }
                pins = {}
                for role, file_role in (("capability_manifest", "policy_capability_manifest"),
                                        ("calibration", "policy_calibration")):
                    relative = {key: fixture.runtime_contract["files"][file_role][key]
                                for key in ("path", "size_bytes", "sha256")}
                    pins[role] = materializer._descriptor_pin(fixture.root, relative,
                        label="original builder-wrapper fixture " + role)
                    if role == "capability_manifest":
                        planner.guardian[role] = dict(relative,
                            path=str(fixture.root / relative["path"]))
                rows = planner.qualification_operations()
                selected = next(row for row in rows if row["phase"] == "qualification_cell"
                    and row["system"] == system and row["codec"] == "h264"
                    and row["policy"] == "cpu_only"
                    and row["scenario"] == fixture.request.scenario)
                selected["descriptors"]["calibration"] = {
                    "path": str(pins["calibration"].path),
                    "size_bytes": pins["calibration"].snapshot[4],
                    "sha256": pins["calibration"].sha256}
                selected["original_operation"] = planner.write(
                    "inputs/" + selected["operation_id"] + "-original.json",
                    {key: value for key, value in selected.items()
                     if key != "original_operation"})
                fixture.request = replace(fixture.request, run_id=selected["run_id"],
                                          arm_id=selected["arm_id"])
                fixture.request.runtime_inputs["run_id"] = selected["run_id"]
                if "arm_id" in fixture.request.runtime_inputs:
                    fixture.request.runtime_inputs["arm_id"] = selected["arm_id"]
                original = fixture.runtime_contract
                del original["operational_capture"]
                del original["files"]["operational_request_context"]
                before = _json(original)
                plan = builder.build_operational_capture_plan_v1(
                    project_root=fixture.root, output_dir=fixture.root / "outputs/capture-plan",
                    mode=builder.QUALIFICATION_MODE, operations=rows,
                    guardian_descriptors=planner.guardian,
                    guardian_output_dir=fixture.root / "outputs/guardian",
                    original_operation_validator=planner.validator)
                self.assertEqual(len(planner.calls), 37)
                self.assertFalse(plan["value"]["accepted"])
                self.assertFalse(plan["value"]["publication_ready"])
                with builder.held_operational_capture_plan_v1(project_root=fixture.root,
                        index_path=Path(plan["descriptor"]["path"]),
                        expected_descriptor=plan["descriptor"]) as held:
                    self.assertEqual(len(held["runtime_contexts_by_arm"]), 32)
                    actual = held["runtime_contexts_by_arm"][selected["arm_id"]]
                    self.assertTrue(Path(actual["descriptor"]["path"]).is_absolute())
                    self.assertEqual(actual["context"]["native_header"]["operation_input"],
                                     selected["original_operation"])
                    fixture.context_source = Path(actual["descriptor"]["path"])
                    fixture.context_bytes = fixture.context_source.read_bytes()
                    cell = SimpleNamespace(**{key: selected[key] for key in
                        ("run_id", "arm_id", "system", "scenario", "codec", "policy", "deadline_ms")})
                    inputs = SimpleNamespace(root=fixture.root,
                        candidate_manifest=pins["capability_manifest"],
                        calibrations={system: pins["calibration"]})
                    bound = materializer._bind_operational_context_for_cell(
                        cell=cell, inputs=inputs, contract=original, capture_plan=held)
                    self.assertEqual(_json(original), before)
                    pin = bound["files"]["operational_request_context"]
                    self.assertFalse(Path(pin["path"]).is_absolute())
                    expected_container = ("/opt/vast/input/operational/native-context.json"
                        if system in {"deepstream", "savant"}
                        else "/workspace/project/" + pin["path"])
                    self.assertEqual(pin["container_path"], expected_container)
                    fixture.runtime_contract = bound
                    fixture.request.runtime_inputs["dataset"][
                        system + "_publication_runtime_v3"] = bound
                    fixture.before = _json(fixture.request.runtime_inputs)
                    with mock.patch.object(fixture.runtime, "_invoke_engine",
                            side_effect=self.invoke(fixture)):
                        result = fixture.runner(fixture.request)
                    self.assertEqual(result.exit_code, 0)
                    self.assertEqual(len(fixture.main_calls), 1)
                    self.assertEqual((fixture.capture_target / NAME).read_bytes(),
                                     fixture.operational_bytes)
                    self.assertEqual(fixture.context_source.read_bytes(), fixture.context_bytes)
                    self.assertEqual(_json(original), before)
                    self.assertEqual(_json(fixture.request.runtime_inputs), fixture.before)

    def test_all_four_original_child_failures_keep_literal_capture_and_original_cause(self):
        for system in SYSTEMS:
            with self.subTest(system=system):
                fixture = self.fixture(system)
                with mock.patch.object(fixture.runtime, "_invoke_engine", side_effect=self.invoke(fixture, mode="failed")), self.assertRaises(Exception) as caught:
                    fixture.runner(fixture.request)
                self.assertIn("native_runtime_failed", caught.exception.blocker)
                retained = Path(str(fixture.capture_target) + ".failed")
                self.assertEqual((retained / NAME).read_bytes(), fixture.operational_bytes)
                self.assertFalse(fixture.capture_target.exists())
                self.assertEqual({path.name for path in fixture.request.output_dir.iterdir()}, {"backend_publication_arm_contract.json"})
                self.assertEqual(_json(fixture.request.runtime_inputs), fixture.before)
                self.assertEqual(list(fixture.scratch.iterdir()), [])

    def test_all_four_stock_legacy_namespace_checks_precede_operational_copy(self):
        for system in SYSTEMS:
            with self.subTest(system=system):
                fixture = self.fixture(system)
                with mock.patch.object(fixture.runtime, "_invoke_engine", side_effect=self.invoke(fixture, mode="unexpected_legacy")), self.assertRaises(Exception):
                    fixture.runner(fixture.request)
                self.assertFalse(fixture.capture_target.exists())
                self.assertEqual((Path(str(fixture.capture_target) + ".failed") / NAME).read_bytes(), fixture.operational_bytes)
                self.assertFalse((fixture.request.output_dir / fixture.module.EVIDENCE_NAME).exists())

    def test_all_four_context_file_tampering_is_rejected_before_the_mocked_arm(self):
        for system in SYSTEMS:
            with self.subTest(system=system):
                fixture = self.fixture(system)
                original = self.invoke(fixture)
                def tamper(engine, engine_socket, argv, timeout_s):
                    value = original(engine, engine_socket, argv, timeout_s)
                    if argv[:2] == ("image", "inspect"):
                        fixture.context_source.write_bytes(fixture.context_bytes + b"\n")
                    return value
                with mock.patch.object(fixture.runtime, "_invoke_engine", side_effect=tamper), self.assertRaises(Exception):
                    fixture.runner(fixture.request)
                self.assertEqual(fixture.main_calls, [])
                self.assertFalse(fixture.capture_target.exists())
                self.assertEqual(_json(fixture.request.runtime_inputs), fixture.before)

    def test_all_four_declared_alias_or_existing_symlink_outputs_fail_before_engine(self):
        for system in SYSTEMS:
            for mode in ("alias", "symlink"):
                with self.subTest(system=system, mode=mode):
                    fixture = self.fixture(system)
                    if mode == "alias":
                        fixture.runtime_contract["operational_capture"]["output_dir"] = str(fixture.capture_target.parent / ".." / fixture.capture_target.parent.name / fixture.capture_target.name)
                    else:
                        foreign = fixture.root / "foreign-output"
                        foreign.mkdir()
                        fixture.capture_target.symlink_to(foreign, target_is_directory=True)
                    with mock.patch.object(fixture.runtime, "_invoke_engine") as engine, self.assertRaises(Exception):
                        fixture.runner(fixture.request)
                    engine.assert_not_called()

    def test_failed_retention_rejects_ancestor_alias_and_preserves_owned_private_stage(self):
        for system in SYSTEMS:
            with self.subTest(system=system):
                fixture = self.fixture(system)
                try:
                    with mock.patch.object(fixture.runtime, "_invoke_engine", side_effect=self.invoke(fixture, mode="failed", mutate_ancestor=True)), self.assertRaises(Exception) as caught:
                        fixture.runner(fixture.request)
                    self.assertIn("native_runtime_failed", caught.exception.blocker)
                    redirected = fixture.foreign_parent / fixture.request.output_dir.parent.name / (fixture.request.output_dir.name + ".operational.failed")
                    self.assertFalse(redirected.exists())
                    self.assertTrue(fixture.request.output_dir.parent.is_dir())
                    self.assertFalse(fixture.request.output_dir.parent.is_symlink())
                    stages = list(fixture.scratch.iterdir())
                    self.assertEqual(len(stages), 1)
                    self.assertEqual((stages[0] / "operational" / NAME).read_bytes(), fixture.operational_bytes)
                    self.assertTrue(any("requires inspection" in note for note in caught.exception.__notes__))
                    self.assertEqual(_json(fixture.request.runtime_inputs), fixture.before)
                finally:
                    if hasattr(fixture, "original_parent"):
                        fixture.alias_ancestor.unlink()
                        fixture.original_parent.rename(fixture.alias_ancestor)


@unittest.skipUnless(os.name == "posix", "Actual qualification custody is Linux-only")
class OperationalPilotCompositionTests(unittest.TestCase):
    def pilot(self, root, system="gstreamer_custom"):
        fixture_module = importlib.import_module("tests.test_publication_policy_qualification_pilot_executor_v2")
        target = importlib.import_module("publication_policy_qualification_pilot_executor_v2")
        fixture = fixture_module.InputFixture(root)
        self.addCleanup(fixture.close)
        inputs = target._load_qualification_inputs(project_root=root,
            candidate_index_path=fixture.candidate_index, candidate_manifest_path=fixture.candidate_manifest,
            candidate_receipt_path=fixture.candidate_receipt, bootstrap_mapping_path=fixture.bootstrap_mapping,
            bootstrap_receipt_path=fixture.bootstrap_receipt, bootstrap_dir=fixture.bootstrap_dir,
            transaction_receipt_path=fixture.transaction_receipt)
        operational = target._load_operational_inputs(inputs=inputs, bootstrap_dir=fixture.bootstrap_dir,
            cells=target.qualification_pilot_cells_v2(),
            runtime_input_materialization_receipt_path=fixture.runtime_materialization_receipt,
            guardian_service_authority_path=fixture.guardian_service_authority,
            preprocessing_contract_path=fixture.preprocessing_contract,
            preprocessing_contract_receipt_path=fixture.preprocessing_receipt,
            service_authority_validator=lambda value, **_: dict(value),
            preprocessing_contract_loader=fixture.preprocessing_loader,
            runtime_expectations_loader=lambda _: dict(fixture.runtime_expectations))
        cell = next(row for row in target.qualification_pilot_cells_v2() if row.system == system)
        staging = fixture.pilot_root / ".qualification-pilot-staging-v2"
        staging.mkdir(mode=0o700)
        fixture.events = []
        fixture.requests = []
        fixture.original_inputs = []
        fixture.original_failure = RuntimeError("original local mocked native failure")
        fixture.capture_bytes = _json({"artifact_kind": "vast_local_mocked_pilot_capture_v1", "system": system})
        fixture.target = target
        fixture.fixture_module = fixture_module

        def request_factory(**kwargs):
            request = fixture.request(kwargs["cell"], kwargs["output_dir"], kwargs["evidence_names"])
            contract = request.runtime_inputs["dataset"][target.RUNTIME_INPUT_KEY_BY_SYSTEM[system]]
            contract["operational_capture"] = {"mode": "complete_qualification_operational_identity_v1", "output_dir": RULE}
            fixture.events.append("request")
            fixture.requests.append(request)
            fixture.original_inputs.append(_json(request.runtime_inputs))
            return request

        def collector_factory(path, *, run_id):
            return fixture_module.FakeCollector(path, run_id=run_id, events=fixture.events)

        def finalizer(**kwargs):
            fixture.events.append("finalizer")
            value = fixture_module.acceptance_payload(cell, fixture)
            fixture_module.write_json(kwargs["output_dir"] / target.ACCEPTANCE_FILENAME, value)
            return value

        def runtime(request):
            fixture.events.append("runtime")
            self.assertEqual(_json(request.runtime_inputs), fixture.original_inputs[-1])
            contract = request.runtime_inputs["dataset"][target.RUNTIME_INPUT_KEY_BY_SYSTEM[system]]
            source = operational_output_dir_v1(request, contract)
            if fixture.fail_runtime:
                source = Path(str(source) + ".failed")
            source.mkdir(mode=0o700)
            (source / NAME).write_bytes(fixture.capture_bytes)
            fixture.capture_source = source
            if fixture.fail_runtime:
                raise fixture.original_failure
            fixture_module.write_request_child_evidence(request)
            return fixture_module.NativePublicationOutcomeV3(exit_code=0)

        def acceptance_fixture(**kwargs):
            # Same explicit fake acceptance used by the original executor
            # fixtures. This test proves control/custody, not qualification.
            return json.loads(kwargs["acceptance_path"].read_bytes())

        patcher = mock.patch.object(target, "validate_checkpoint_qualification_pilot_acceptance_v1", side_effect=acceptance_fixture)
        patcher.start()
        self.addCleanup(patcher.stop)
        fixture.fail_runtime = False
        fixture.run_arguments = dict(inputs=inputs, bootstrap_dir=fixture.bootstrap_dir,
            pilot_root=fixture.pilot_root, staging_root=staging, cell=cell,
            runtime=runtime, request_factory=request_factory, collector_factory=collector_factory,
            acceptance_finalizer=finalizer, operational=operational)
        fixture.final = target._pilot_path(fixture.pilot_root, cell)
        fixture.staging = staging
        return fixture

    def test_actual_run_one_cell_commits_separate_capture_after_stock_finalization(self):
        for system in SYSTEMS:
            with self.subTest(system=system), tempfile.TemporaryDirectory(prefix="vast-pilot-composition-") as temporary:
                fixture = self.pilot(Path(temporary).resolve(), system)
                committed = fixture.target._run_one_cell(**fixture.run_arguments, execution_barrier=lambda: fixture.events.append("barrier"))
                try:
                    self.assertEqual(committed.final, fixture.final)
                    target = Path(str(fixture.final) + ".operational")
                    self.assertEqual((target / NAME).read_bytes(), fixture.capture_bytes)
                    self.assertFalse(fixture.capture_source.exists())
                    self.assertEqual({path.name for path in fixture.final.iterdir()}, set(fixture.target.FINAL_NAMESPACE_FILES))
                    self.assertEqual(_json(fixture.requests[0].runtime_inputs), fixture.original_inputs[0])
                    self.assertLess(fixture.events.index("runtime"), fixture.events.index("finalizer"))
                    self.assertEqual(fixture.events.count("barrier"), 3)
                    self.assertEqual(list(fixture.staging.iterdir()), [])
                finally:
                    if committed.anchor is not None:
                        committed.anchor.close()

    def test_actual_run_one_cell_preserves_original_failure_and_captured_attempt(self):
        with tempfile.TemporaryDirectory(prefix="vast-pilot-failure-") as temporary:
            fixture = self.pilot(Path(temporary).resolve())
            fixture.fail_runtime = True
            with self.assertRaises(RuntimeError) as caught:
                fixture.target._run_one_cell(**fixture.run_arguments, execution_barrier=lambda: None)
            self.assertIs(caught.exception, fixture.original_failure)
            self.assertFalse(fixture.final.exists())
            self.assertEqual((fixture.capture_source / NAME).read_bytes(), fixture.capture_bytes)
            self.assertEqual(len(list(fixture.staging.iterdir())), 1)
            self.assertTrue(any("retained" in note for note in caught.exception.__notes__))
            self.assertEqual(_json(fixture.requests[0].runtime_inputs), fixture.original_inputs[0])

    def test_actual_precommit_failure_preserves_cause_and_orphan_blocks_before_reinvocation(self):
        with tempfile.TemporaryDirectory(prefix="vast-pilot-precommit-") as temporary:
            fixture = self.pilot(Path(temporary).resolve())
            original = RuntimeError("original local precommit barrier failed")
            calls = 0
            def barrier():
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise original
            with self.assertRaises(RuntimeError) as caught:
                fixture.target._run_one_cell(**fixture.run_arguments, execution_barrier=barrier)
            self.assertIs(caught.exception, original)
            self.assertFalse(fixture.final.exists())
            self.assertEqual((Path(str(fixture.final) + ".operational") / NAME).read_bytes(), fixture.capture_bytes)
            self.assertFalse(fixture.capture_source.exists())
            self.assertEqual(len(list(fixture.staging.iterdir())), 1)
            self.assertTrue(any("retained" in note for note in caught.exception.__notes__))
            events = list(fixture.events)
            requests = len(fixture.requests)
            with self.assertRaisesRegex(fixture.target.QualificationPilotExecutorV2Error, "orphan original pilot capture"):
                fixture.target._run_one_cell(**fixture.run_arguments, execution_barrier=lambda: None)
            self.assertEqual(fixture.events, events)
            self.assertEqual(len(fixture.requests), requests)
            self.assertEqual(len(list(fixture.staging.iterdir())), 1)


if __name__ == "__main__":
    unittest.main()
