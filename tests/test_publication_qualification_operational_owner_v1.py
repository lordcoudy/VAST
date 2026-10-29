"""Stock owner of reviewed original operations; local fixture engine only.

Real here: stock capture-plan builder and held loader, the owner sequencing,
its runtime_registry wrapper, capture_original_engine_processes_v1,
measurement_container_custody_v1 around the stock native _invoke_engine,
genuine held-ELF child processes and their /proc identities, the stock native
transfer materializer (first scratch and second pilot commit), real
NativePolicyRuntimeCoordinator producers, the actual guardian front/recorder,
the owner binding writer and the cold closure reconcile whose original
process/container validators are NOT mocked.

Fixture here: the engine is a compiled local ELF that models Docker daemon
replies (no Docker, image, container or GPU is used); in-container native
producer work is replaced by the real in-process coordinator writing into the
same mounted scratch; the held precheck/Savant runner and the pilot executor
loop are stand-ins for the stock loaders, which need the full physical input
universe; inference is the existing local backend; the stock measured CSV
cohort adapter is mocked exactly as in the existing 37-binding test. Nothing
here is physical benchmark, qualification or publication acceptance.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import hashlib
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from analytics_execution_endpoint import expected_capability_from_binding_and_probe
from analytics_execution_protocol import canonical_json_bytes
import checkpoint_gstreamer_publication_runtime_v3 as stock_native_runtime
from checkpoint_native_policy_runtime import NativePolicyRuntimeCoordinator
from checkpoint_publication_launcher_adapter_v3 import NativePublicationOutcomeV3, NativePublicationRequestV3
from checkpoint_runtime_plan import validate_checkpoint_runtime_plan
from publication_operational_capture_plan_v1 import (
    DIAGNOSTIC_MODE, QUALIFICATION_MODE, build_operational_capture_plan_v1, held_operational_capture_plan_v1,
)
import publication_operational_container_custody_v1 as container_module
from publication_operational_container_custody_v1 import measurement_container_custody_v1
import publication_operational_process_custody_v1 as process_module
from publication_operational_process_custody_v1 import original_engine_phase_v1
from publication_operational_request_domain_v1 import NATIVE_OPERATIONAL_JSONL
from publication_operational_runtime_context_v1 import CAPTURE_KEY, OUTPUT_PATH_RULE, _materialize_operational_file_v1
import publication_policy_qualification_execution_closure_v1 as closure
import publication_policy_qualification_pilot_executor_v2 as pilot
from tests.test_publication_operational_boundary_v1 import _BoundaryFixture, _descriptor, _write_json
from tests.test_publication_operational_container_custody_v1 import ENGINE_SOURCE
from tests.test_publication_operational_execution_binding_v1 import (
    BRANCHES, NATIVE, _OriginalBindingFixture, _relative, _sealed_file,
)
from tests.test_checkpoint_gstreamer_analytics_sidecar import _binding, _probe
from tests.test_checkpoint_native_policy_runtime import calibration

import publication_qualification_operational_owner_v1 as owner

SHARED = "checkpoint_video_dag_shared"


class _OwnerFixture(_OriginalBindingFixture):
    """Stock-shaped 37/2 plan; reuses the original guardian/request recipe."""

    def __init__(self, root, mode, *, pilot_fault=None):
        self.root, self.mode, self.pilot_fault = root, mode, pilot_fault
        self.boundary = _BoundaryFixture(root)
        config_source = Path(self.boundary.inputs["execution_config"]["path"])
        config_source.write_bytes(canonical_json_bytes(
            {key: value for key, value in self.boundary.config.items() if key != "identity"}) + b"\n")
        self.boundary.inputs["execution_config"] = _descriptor(config_source)
        self.maps, self.runtime_bundles = {}, {}
        self.held_calls, self.registry_calls, self.pilot_calls = [], [], []
        self._compile_engine()
        import importlib
        planner_module = importlib.import_module("tests.test_publication_operational_capture_plan_v1")
        planner_module.CapturePlanTests.setUpClass()
        planner = planner_module.CapturePlanTests("runTest")
        planner.root = root
        planner.calls = []
        (root / "outputs").mkdir()
        planner.guardian = {role: self.boundary.inputs[role] for role in
            ("capability_manifest", "execution_config", "execution_code_closure", "model_authority")}
        for role, source in (
                ("native_protocol_source", ROOT / "deploy/native_gst_probe/vast_native_gst_probe.cpp"),
                ("proxy_protocol_source", ROOT / "scripts/checkpoint_deepstream_protocol_bridge.py")):
            path = root / "inputs" / source.name
            path.write_bytes(source.read_bytes())
            planner.guardian[role] = _descriptor(path)
        self.capabilities = {(branch, resource): expected_capability_from_binding_and_probe(
            binding=_binding(branch, resource, self.boundary.config),
            runtime_probe=_probe(resource, self.boundary.config), resource=resource)
            for branch in BRANCHES for resource in ("cpu", "gpu")}
        if mode == QUALIFICATION_MODE:
            self.rows = planner.qualification_operations()
        else:
            self.rows = [planner.operation("diagnostic-baseline", "diagnostic", "gstreamer_custom", "cpu", "h264", False),
                         planner.operation("diagnostic-shared", "diagnostic", "gstreamer_custom", "cpu", "h264", True)]
        self.calibrations = {system: calibration(self.boundary.manifest, system=system)
            for system in {row["system"] for row in self.rows}}
        calibration_refs = {system: _write_json(root / "inputs" / ("calibration-" + system + ".json"), value)
            for system, value in self.calibrations.items()}
        # Stock planner reservations: pilots for cells, diagnostics otherwise.
        self.output = root / "outputs" / "stock-operations"
        self.pilots = root / "outputs" / "pilots"
        self.cells = {cell.arm_id: cell for cell in pilot.qualification_pilot_cells_v2()}
        self.cells_by_arm = {}
        image = {"image_id": "sha256:" + "a" * 64,
            "repository_digest": "vast/local-owner-fixture@sha256:" + "b" * 64,
            "inspect_projection_sha256": "c" * 64, "base_image_id": "sha256:" + "d" * 64}
        for row in self.rows:
            row["descriptors"].update({
                **{role: self.boundary.inputs[role] for role in
                    ("capability_manifest", "execution_code_closure", "model_authority")},
                "calibration": calibration_refs[row["system"]],
                "policy_request_source": planner.guardian["native_protocol_source"],
                "policy_coordinator_source": self._copy_source("checkpoint_native_policy_runtime.py"),
            })
            if row["system"] not in NATIVE:
                for route, workers in row["front_workers_by_route"].items():
                    worker_id = self.capabilities[tuple(route.split(":"))]["worker_id"]
                    for worker in workers:
                        worker["worker_id"] = worker_id
            if row["phase"] == "qualification_cell":
                directory = pilot._pilot_path(self.pilots, self.cells[row["arm_id"]])
                self.cells_by_arm[row["arm_id"]] = row
            else:
                directory = self.output / "diagnostics" / row["operation_id"] / "evidence"
            process_dir = self.output / "process-captures" / row["operation_id"]
            reservation = {"measurement_dir": str(directory),
                "native_domain": str(Path(str(directory) + ".operational") / NATIVE_OPERATIONAL_JSONL),
                "process_receipt": str(process_dir / "original_engine_process_capture.v1.json"),
                "container_receipt": str(process_dir / "container-custody/original_container_custody.v1.json")}
            original = {"schema_version": 1, "artifact_kind": "vast_original_native_operation_input_v1",
                "operation": {key: value for key, value in row.items() if key != "original_operation"},
                "container_image": image, "outputs": reservation}
            Path(row["original_operation"]["path"]).unlink()
            row["original_operation"], _ = _sealed_file(Path(row["original_operation"]["path"]), original)

        def original_validator(row, assets):
            original = json.loads(assets[row["original_operation"]["path"]])
            if original["operation"] != {key: value for key, value in row.items() if key != "original_operation"}:
                raise AssertionError("local original operation changed")
            plan = json.loads(assets[row["descriptors"]["source_plan"]["path"]])
            validate_checkpoint_runtime_plan(plan)
            if plan["system"] != row["system"] or plan["scenario"] != row["scenario"]:
                raise AssertionError("local stock source plan changed")

        self.plan = build_operational_capture_plan_v1(project_root=root, output_dir=self.output / "capture-plan",
            mode=mode, operations=self.rows, guardian_descriptors=planner.guardian,
            guardian_output_dir=root / "outputs/guardian-operational", original_operation_validator=original_validator)
        self.plan_path = Path(self.plan["descriptor"]["path"])
        with held_operational_capture_plan_v1(project_root=root, index_path=self.plan_path,
                expected_descriptor=self.plan["descriptor"]) as held:
            self.contexts = copy.deepcopy(held["native_contexts_by_id"])
            self.context_refs = {row["operation_id"]: row["descriptor"] for row in held["index"]["native_contexts"]}
            self.boundary.service._operational_context = {
                "headers_by_route": {tuple(route.split(":")): copy.deepcopy(header)
                    for route, header in held["guardian_context"]["headers_by_route"].items()},
                "output_dir": Path(held["guardian_context"]["output_dir"])}
        probes = {}
        for resource in ("cpu", "gpu"):
            probes[resource] = _relative(root, _write_json(root / "inputs" / ("probe-" + resource + ".json"),
                _probe(resource, self.boundary.config)))
            probes[resource]["worker_implementation_sha256"] = _probe(resource, self.boundary.config)["worker_implementation_sha256"]
        self.preprocessing = {"candidate_manifest": _relative(root, self.boundary.inputs["capability_manifest"]),
            "model_parity_refresh_authority": {
                "execution_config": _relative(root, self.boundary.inputs["execution_config"]),
                "runtime_probes": probes,
                "binding_set": {"index": _relative(root, _descriptor(root / "bindings/index.json")),
                    "bindings": {f"{branch}:{resource}": _relative(root, _descriptor(
                        root / "bindings" / (branch + "." + self.capabilities[(branch, resource)]["engine"] + ".json")))
                        for branch in BRANCHES for resource in ("cpu", "gpu")}}}}
        self.runtime = {"receipt": {"path": "runtime-bundles/materialization.json"}}
        (root / "runtime-bundles").mkdir()
        self._bundles()
        (root / "runtime-scratch").mkdir()
        (root / "pilot-staging").mkdir()
        self.stock_arguments = {name: root / "inputs" / ("fixture-unused-" + name) for name in owner.STOCK_ARGUMENTS}
        self.stock_arguments.update(pilot_root=self.pilots, checkpoint_path=root / "outputs/pilot-checkpoint.v3.json")
        self.pilot = {"guardian_request_workload": {"cells": [
            {"arm_id": row["arm_id"], "request_count": 4}
            for row in self.rows if row["phase"] == "qualification_cell"]}}

    def _compile_engine(self):
        # External to project_root exactly like the stock Docker CLI.
        self.external = self.root.parent / (self.root.name + ".owner-fixture-engine")
        self.external.mkdir()
        (self.external / "daemon-state").mkdir(mode=0o700)
        (self.external / "unused-opdir").mkdir(mode=0o700)
        source = self.external / "engine.c"
        source.write_text(ENGINE_SOURCE)
        self.engine_path = self.external / "docker"
        subprocess.run([shutil.which("cc"), "-O0", "-std=c11",
            '-DSTATE_FILE="' + str(self.external / "daemon-state/fixture.state") + '"',
            '-DOPDIR="' + str(self.external / "unused-opdir") + '"',
            str(source), "-o", str(self.engine_path)], check=True, capture_output=True)
        source.unlink()
        self.engine_ref = _descriptor(self.engine_path)
        self.engine_fd = os.open(self.engine_path, os.O_RDONLY)
        raw = self.engine_path.read_bytes()
        self.engine = SimpleNamespace(path=self.engine_path, fd=self.engine_fd, size=len(raw),
            sha256=hashlib.sha256(raw).hexdigest(), proc_path=f"/proc/self/fd/{self.engine_fd}")
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        path = self.root / "engine.sock"
        self.socket.bind(str(path))
        info = path.lstat()
        self.socket_pin = {"path": str(path), "device": info.st_dev, "inode": info.st_ino,
            "owner_uid": info.st_uid, "owner_gid": info.st_gid}

    def close(self):
        os.close(self.engine_fd)
        self.socket.close()
        shutil.rmtree(self.external)

    def _bundles(self):
        for row in self.rows:
            if row["phase"] not in {"qualification_cell", "diagnostic"}:
                continue
            original = json.loads(Path(row["original_operation"]["path"]).read_bytes())
            contract = {"operational_capture": {"mode": self.mode, "output_dir": OUTPUT_PATH_RULE},
                "container_image": original["container_image"],
                "files": {"operational_request_context": _relative(self.root, self.context_refs[row["operation_id"]]),
                    "container_engine": copy.deepcopy(self.engine_ref),
                    "policy_capability_manifest": _relative(self.root, row["descriptors"]["capability_manifest"]),
                    "policy_calibration": _relative(self.root, row["descriptors"]["calibration"])}}
            doc = {"runtime_inputs": {"dataset": {row["system"] + "_publication_runtime_v3": contract}}}
            ref, doc = _sealed_file(self.root / "runtime-bundles" / (row["operation_id"] + ".json"), doc, "bundle_sha256")
            self.runtime_bundles[row["arm_id"]] = {"path": Path(ref["path"]).name, "size_bytes": ref["size_bytes"],
                "sha256": ref["sha256"], "bundle_sha256": doc["bundle_sha256"]}
        # The stock materialization always has 32 bundles; a bounded
        # diagnostic reads only its own two. Others are never opened here.
        for arm in self.cells:
            self.runtime_bundles.setdefault(arm, {"path": "fixture-unread-" + arm + ".json",
                "size_bytes": 1, "sha256": "0" * 64, "bundle_sha256": "0" * 64})

    def request(self, *, system, scenario, run_id, arm_id, output_dir):
        manifest = Path(self.boundary.inputs["capability_manifest"]["path"])
        return NativePublicationRequestV3(system=system,
            topology_kind="shared_video_dag" if scenario == SHARED else "independent_processes",
            scenario=scenario, project_root=self.root, output_dir=output_dir, arm_contract_path=manifest,
            arm_contract_file_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest(),
            run_id=run_id, arm_id=arm_id, runtime_inputs={"fixture_only": True}, launcher_evidence_files=())

    def native_runtime(self, request, row):
        """Stand-in for the stock runtime tail: actual engine CLI + transfer."""
        original = json.loads(Path(row["original_operation"]["path"]).read_bytes())
        context, context_ref = self.contexts[row["operation_id"]], self.context_refs[row["operation_id"]]
        scratch = Path(tempfile.mkdtemp(prefix="runtime-", dir=self.root / "runtime-scratch"))
        operational = scratch / "operational"
        operational.mkdir(mode=0o700)
        relative = Path(context_ref["path"]).relative_to(self.root).as_posix()
        arguments = ("run", "--rm", "--mount", f"type=bind,src={self.root},dst=/workspace/project,readonly",
            "--mount", f"type=bind,src={operational},dst=/opt/vast/operational", original["container_image"]["image_id"],
            "--operational-request-context", "/workspace/project/" + relative,
            "--operational-output-dir", "/opt/vast/operational")
        with original_engine_phase_v1("measurement"), measurement_container_custody_v1(
                self.engine, self.socket_pin, arguments) as owned:
            completed = stock_native_runtime._invoke_engine(self.engine, self.socket_pin, owned.argv, 5.0)
            owned.completed(completed.returncode)
        if completed.returncode != 0:
            raise RuntimeError("fixture engine measurement failed")
        reset_arm = (f"{row['run_id']}:{row['scenario']}:{row['codec']}:{row['policy']}:{float(row['deadline_ms'])}"
            if row["system"] in NATIVE else row["arm_id"])
        coordinator = NativePolicyRuntimeCoordinator(
            **{key: row[key] for key in ("run_id", "system", "scenario", "codec", "policy", "deadline_ms")},
            arm_id=reset_arm, branches=BRANCHES, capability_manifest=self.boundary.manifest,
            calibration=self.calibrations[row["system"]],
            operational_context={"header": context["native_header"], "output_dir": operational})
        canonical = {}
        for frame in (1, 2, 3):
            for branch in BRANCHES:
                emitted = self.complete(row, coordinator, frame, branch)
                if frame == 2:
                    canonical[emitted["input_frame_key"]] = {
                        "trace_id": row["run_id"] + ":canonical:0:2", "stream_id": 0, "frame_id": 2}
        output = Path(request.output_dir)
        coordinator.promote(output, canonical_frames=canonical)
        self.maps[row["operation_id"]] = canonical
        (output / "ingress_ledger.csv").write_text("fixture_only,input_frame_key,trace_id,stream_id,frame_id\n" +
            "".join(f"true,{key},{value['trace_id']},0,2\n" for key, value in canonical.items()), encoding="ascii")
        _materialize_operational_file_v1(self.root, operational, Path(str(output) + ".operational"))
        return NativePublicationOutcomeV3(exit_code=0)

    def held_runner(self, *, project_root, capture_plan_path, operation, stock_arguments):
        self.held_calls.append(operation["operation_id"])
        if stock_arguments != self.stock_arguments or capture_plan_path != self.plan_path:
            raise AssertionError("owner detached held stock arguments")
        original = json.loads(Path(operation["original_operation"]["path"]).read_bytes())
        directory = Path(original["outputs"]["measurement_dir"])
        directory.mkdir(parents=True)
        request = self.request(system=operation["system"], scenario=operation["scenario"],
            run_id=operation["run_id"], arm_id=operation["arm_id"], output_dir=directory)
        with owner.original_operation_capture_v1(project_root=project_root, operation=operation,
                native_context_descriptor=self.context_refs[operation["operation_id"]], original=original):
            self.native_runtime(request, operation)

    def base_registry(self):
        def runner(request):
            self.registry_calls.append(request.arm_id)
            return self.native_runtime(request, self.cells_by_arm[request.arm_id])
        return {system: runner for system in pilot.SYSTEMS}

    def _run_cell(self, registry, cell, pilot_root, **changes):
        final = pilot._pilot_path(Path(pilot_root), cell)
        attempt = Path(tempfile.mkdtemp(prefix=cell.arm_id + ".", dir=self.root / "pilot-staging"))
        output = attempt / "pilot"
        output.mkdir(mode=0o700)
        coordinates = {"system": cell.system, "scenario": cell.scenario, "run_id": cell.run_id, "arm_id": cell.arm_id}
        coordinates.update(changes)
        request = self.request(output_dir=output, **coordinates)
        outcome = registry[cell.system](request)
        if type(outcome) is not NativePublicationOutcomeV3 or outcome.exit_code != 0:
            raise AssertionError("fixture pilot runtime failed")
        final.parent.mkdir(parents=True, exist_ok=True)
        # Actual stock commit of the original capture beside the final cell.
        pilot._commit_operational_capture_for_cell(request=request,
            contract={CAPTURE_KEY: {"mode": QUALIFICATION_MODE, "output_dir": OUTPUT_PATH_RULE}}, final=final)
        os.rename(output, final)

    def pilot_executor(self, *, project_root, runtime_registry, **stock):
        if set(stock) != set(owner.STOCK_ARGUMENTS) or set(runtime_registry) != set(pilot.SYSTEMS):
            raise AssertionError("owner detached pilot executor stock arguments")
        self.pilot_calls.append(dict(stock))
        for ordinal, cell in enumerate(pilot.qualification_pilot_cells_v2()):
            if self.pilot_fault == "foreign" and ordinal == 0:
                self._run_cell(runtime_registry, cell, stock["pilot_root"],
                    arm_id="qualification-arm-v2-foreign-cpu-h264-independent-processes")
            if self.pilot_fault == "substituted" and ordinal == 0:
                self._run_cell(runtime_registry, cell, stock["pilot_root"], run_id="qualification-v2-foreign-run")
            self._run_cell(runtime_registry, cell, stock["pilot_root"])
            if self.pilot_fault == "duplicate" and ordinal == 0:
                self._run_cell(runtime_registry, cell, stock["pilot_root"])
            if self.pilot_fault == "missing" and ordinal == 0:
                return {"fixture_only": True}
        return {"fixture_only": True}

    def execute(self, **changes):
        arguments = dict(project_root=self.root, capture_plan_path=self.plan_path,
            stock_arguments=self.stock_arguments, held_operation_runner=self.held_runner,
            pilot_executor=self.pilot_executor, runtime_registry=self.base_registry())
        arguments.update(changes)
        return owner.execute_qualification_operational_owner_v1(**arguments)

    def run_once(self):
        self.boundary.start()
        try:
            self.result = self.execute()
        finally:
            self.boundary.stop()

    def bind(self, name="original_operational_execution_binding.v1.json"):
        return owner.bind_operational_execution_v1(project_root=self.root, capture_plan_path=self.plan_path,
            binding_path=self.root / "outputs" / name)

    def reconcile(self, binding, **changes):
        args = dict(project_root=self.root, binding_path=Path(binding["descriptor"]["path"]),
            guardian_authority_path=self.boundary.service.evidence.authority_path,
            preprocessing_receipt=self.preprocessing, lifecycle_counters=self.boundary.lifecycle["counters"],
            scratch_root=self.root / "binding-cold-scratch", expected_mode=self.mode,
            pilot_execution=self.pilot if self.mode == QUALIFICATION_MODE else None,
            runtime=self.runtime, runtime_bundles=self.runtime_bundles)
        args.update(changes)
        outputs = {row["operation_id"]: row for row in binding["value"]["operation_outputs"]}
        mapped = []

        def cohort(**kwargs):
            identity = kwargs["operation"]["operation_id"]
            mapped.append(identity)
            if kwargs["ingress_descriptor"] != outputs[identity]["accepted_ingress"]:
                raise AssertionError("mocked cohort received foreign physical ingress")
            return copy.deepcopy(self.maps[identity])
        # Only the stock CSV cohort is a fixture; original validators are real.
        with mock.patch.object(closure, "_operational_measured_ingress_v1", side_effect=cohort), \
                mock.patch.object(process_module, "original_process_validator_v1",
                    wraps=process_module.original_process_validator_v1) as process, \
                mock.patch.object(container_module, "original_container_validator_v1",
                    wraps=container_module.original_container_validator_v1) as container:
            result = closure.reconcile_operational_capture_binding_v1(**args)
        return result, mapped, process.call_count, container.call_count


def _fixture(mode, *, fault=None):
    temporary = tempfile.TemporaryDirectory(prefix="vast-owner-")
    root = Path(temporary.name).resolve()
    fixture = _OwnerFixture(root, mode, pilot_fault=fault)
    return temporary, fixture


_REAL_LINUX = (sys.platform.startswith("linux") and hasattr(os, "memfd_create") and shutil.which("cc") is not None)


@unittest.skipUnless(_REAL_LINUX, "actual Linux /proc, seqpacket transport and a C compiler are required")
class QualificationOwner37Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary, cls.fixture = _fixture(QUALIFICATION_MODE)
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.addClassCleanup(cls.fixture.close)
        cls.fixture.run_once()
        cls.binding = cls.fixture.bind()

    def test_owner_executes_exact_37_and_binding_passes_cold_closure_with_real_validators(self):
        fixture = self.fixture
        held = [row["operation_id"] for row in fixture.rows if row["phase"] != "qualification_cell"]
        self.assertEqual(fixture.held_calls, held)
        self.assertEqual(len(fixture.pilot_calls), 1)
        self.assertEqual(sorted(fixture.registry_calls), sorted(fixture.cells_by_arm))
        self.assertEqual(fixture.result["operation_ids"], [row["operation_id"] for row in fixture.rows])
        self.assertFalse(fixture.result["accepted"])
        value = self.binding["value"]
        self.assertEqual(set(value), {"schema_version", "artifact_kind", "mode", "capture_plan",
            "guardian_companion", "operation_outputs", "sha256"})
        self.assertEqual(value["artifact_kind"], "vast_original_operational_execution_binding_v1")
        self.assertEqual(value["capture_plan"], fixture.plan["descriptor"])
        self.assertEqual(value["guardian_companion"], fixture.boundary.service.operational_group)
        self.assertEqual([row["operation_id"] for row in value["operation_outputs"]],
                         [row["operation_id"] for row in fixture.rows])
        self.assertEqual(oct(Path(self.binding["descriptor"]["path"]).stat().st_mode & 0o777), "0o444")
        result, mapped, processes, containers = fixture.reconcile(self.binding)
        self.assertEqual(result["original_operation_count"], 37)
        self.assertEqual(result["qualification_cell_count"], 32)
        self.assertFalse(result["publication_authority"])
        self.assertEqual(result["reconciliation"]["request_count"], 444)
        self.assertEqual(result["reconciliation"]["measurement_request_count"], 148)
        self.assertEqual(result["reconciliation"]["requests_by_worker"],
                         fixture.boundary.lifecycle["counters"]["requests_by_worker"])
        self.assertEqual(mapped, [row["operation_id"] for row in fixture.rows])
        self.assertEqual((processes, containers), (37, 37))

    def test_cells_retain_actual_two_transfer_chain_and_held_operations_one_transfer(self):
        for row in self.fixture.rows:
            original = json.loads(Path(row["original_operation"]["path"]).read_bytes())
            summary = process_module.original_process_validator_v1(project_root=self.fixture.root,
                receipt_path=original["outputs"]["process_receipt"], operation_id=row["operation_id"],
                original_operation_descriptor=row["original_operation"],
                native_context_descriptor=self.fixture.context_refs[row["operation_id"]],
                expected_container_image=original["container_image"])
            expected = 2 if row["phase"] == "qualification_cell" else 1
            self.assertEqual(len(summary["native_transfers"]), expected, row["operation_id"])
            self.assertEqual(summary["measurement"]["launch"]["engine"]["sha256"], self.fixture.engine_ref["sha256"])

    def test_repeated_owner_invocation_is_rejected_before_any_launch(self):
        fixture = self.fixture
        held, pilots, registry = list(fixture.held_calls), list(fixture.pilot_calls), list(fixture.registry_calls)
        with self.assertRaisesRegex(ValueError, "occupied"):
            fixture.execute()
        self.assertEqual((fixture.held_calls, fixture.pilot_calls, fixture.registry_calls), (held, pilots, registry))

    def test_resumed_pilot_checkpoint_cannot_satisfy_one_owner(self):
        fixture = self.fixture
        checkpoint = Path(fixture.stock_arguments["checkpoint_path"])
        checkpoint.write_text("{}\n")
        self.addCleanup(checkpoint.unlink)
        with self.assertRaisesRegex(ValueError, "checkpoint|occupied"):
            fixture.execute()

    def test_extra_foreign_capture_namespace_blocks_binding(self):
        foreign = self.fixture.output / "process-captures" / "foreign-original-operation"
        foreign.mkdir()
        self.addCleanup(shutil.rmtree, foreign)
        with self.assertRaisesRegex(ValueError, "extra|foreign|uncounted"):
            self.fixture.bind("extra.binding.json")
        self.assertFalse((self.fixture.root / "outputs/extra.binding.json").exists())

    def test_swapped_original_receipts_block_binding(self):
        captures = self.fixture.output / "process-captures"
        first, second = (captures / self.fixture.rows[0]["operation_id"], captures / self.fixture.rows[5]["operation_id"])
        hold = captures.parent / "swap-hold"
        first.rename(hold)
        second.rename(first)
        hold.rename(second)

        def restore():
            second.rename(hold)
            first.rename(second)
            hold.rename(first)
        self.addCleanup(restore)
        with self.assertRaises(ValueError):
            self.fixture.bind("swapped.binding.json")
        self.assertFalse((self.fixture.root / "outputs/swapped.binding.json").exists())

    def test_missing_original_receipt_blocks_binding(self):
        target = self.fixture.output / "process-captures" / self.fixture.rows[-1]["operation_id"]
        hold = self.fixture.output / "missing-hold"
        target.rename(hold)
        self.addCleanup(hold.rename, target)
        with self.assertRaisesRegex(ValueError, "missing|extra|foreign|uncounted"):
            self.fixture.bind("missing.binding.json")

    def test_stock_binding_writer_rejects_missing_extra_and_duplicate_outputs(self):
        value = self.binding["value"]
        base = dict(mode=value["mode"], capture_plan=value["capture_plan"],
            guardian_companion=value["guardian_companion"])
        outputs = value["operation_outputs"]
        extra_field = copy.deepcopy(outputs)
        extra_field[0]["foreign"] = True
        cases = {"missing": outputs[:-1], "extra": [*outputs, copy.deepcopy(outputs[0])],
            "duplicate": [*outputs[:-1], copy.deepcopy(outputs[0])], "field": extra_field,
            "mode": None}
        for name, rows in cases.items():
            with self.subTest(case=name):
                arguments = dict(base, operation_outputs=outputs if rows is None else rows)
                if name == "mode":
                    arguments["mode"] = DIAGNOSTIC_MODE
                with self.assertRaises(ValueError):
                    owner.write_operational_execution_binding_v1(project_root=self.fixture.root,
                        binding_path=self.fixture.root / "outputs" / ("writer-" + name + ".json"), **arguments)
                self.assertFalse((self.fixture.root / "outputs" / ("writer-" + name + ".json")).exists())


@unittest.skipUnless(_REAL_LINUX, "actual Linux /proc, seqpacket transport and a C compiler are required")
class DiagnosticOwner2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary, cls.fixture = _fixture(DIAGNOSTIC_MODE)
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.addClassCleanup(cls.fixture.close)
        cls.fixture.run_once()
        cls.binding = cls.fixture.bind()

    def test_owner_executes_exact_two_held_originals_and_cold_closure_accepts_binding(self):
        fixture = self.fixture
        self.assertEqual(fixture.held_calls, ["diagnostic-baseline", "diagnostic-shared"])
        self.assertEqual((fixture.pilot_calls, fixture.registry_calls), ([], []))
        self.assertEqual(self.binding["value"]["mode"], DIAGNOSTIC_MODE)
        result, mapped, processes, containers = fixture.reconcile(self.binding)
        self.assertEqual(result["original_operation_count"], 2)
        self.assertEqual(result["qualification_cell_count"], 0)
        self.assertEqual(result["reconciliation"]["request_count"], 24)
        self.assertEqual(mapped, ["diagnostic-baseline", "diagnostic-shared"])
        self.assertEqual((processes, containers), (2, 2))

    def test_two_operation_binding_cannot_satisfy_complete_qualification(self):
        with self.assertRaises(closure.QualificationExecutionClosureV1Error):
            self.fixture.reconcile(self.binding, expected_mode=QUALIFICATION_MODE, pilot_execution=self.fixture.pilot)

    def test_missing_diagnostic_receipt_blocks_binding(self):
        target = self.fixture.output / "process-captures" / "diagnostic-shared"
        hold = self.fixture.output / "missing-hold"
        target.rename(hold)
        self.addCleanup(hold.rename, target)
        with self.assertRaises(ValueError):
            self.fixture.bind("missing.binding.json")


@unittest.skipUnless(_REAL_LINUX, "actual Linux /proc, seqpacket transport and a C compiler are required")
class QualificationOwnerFailClosedTests(unittest.TestCase):
    """Each fault is a fresh one-attempt chain; nothing is retried."""

    def run_fault(self, fault, message):
        temporary, fixture = _fixture(QUALIFICATION_MODE, fault=fault)
        self.addCleanup(temporary.cleanup)
        self.addCleanup(fixture.close)
        with self.assertRaisesRegex(ValueError, message):
            fixture.run_once()
        held = [row["operation_id"] for row in fixture.rows if row["phase"] != "qualification_cell"]
        self.assertEqual(fixture.held_calls, held)
        with self.assertRaises(ValueError):
            fixture.bind()
        self.assertFalse((fixture.root / "outputs/original_operational_execution_binding.v1.json").exists())
        return fixture

    def captured(self, fixture):
        return sorted(path.name for path in (fixture.output / "process-captures").iterdir())

    def test_foreign_cell_request_is_rejected_before_launch(self):
        fixture = self.run_fault("foreign", "foreign")
        self.assertEqual(fixture.registry_calls, [])
        self.assertEqual(len(self.captured(fixture)), 5)

    def test_substituted_cell_coordinates_are_rejected_before_launch(self):
        fixture = self.run_fault("substituted", "differs from the planned original")
        self.assertEqual(fixture.registry_calls, [])
        self.assertEqual(len(self.captured(fixture)), 5)

    def test_duplicate_cell_invocation_is_rejected_before_second_launch(self):
        fixture = self.run_fault("duplicate", "duplicate")
        self.assertEqual(len(fixture.registry_calls), 1)
        self.assertEqual(len(self.captured(fixture)), 6)

    def test_missing_cells_after_pilot_return_fail_closed(self):
        fixture = self.run_fault("missing", "missing")
        self.assertEqual(len(fixture.registry_calls), 1)
        self.assertEqual(len(self.captured(fixture)), 6)


class HeldQualificationOriginalTests(unittest.TestCase):
    """Held prechecks/Savant reuse the stock cell bundle with their own context."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="vast-owner-held-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        (self.root / "plan").mkdir()
        self.cell = _write_json(self.root / "plan/native_context_10.v1.json", {"fixture_only": "cell"})
        self.own = _write_json(self.root / "plan/native_context_00.v1.json", {"fixture_only": "precheck"})

    def runtime_inputs(self, system, *, mode=QUALIFICATION_MODE, declared=None):
        declared = declared or self.cell
        relative = Path(declared["path"]).relative_to(self.root).as_posix()
        container = ("/opt/vast/input/operational/native-context.json" if system in {"deepstream", "savant"}
                     else "/workspace/project/" + relative)
        contract = {CAPTURE_KEY: {"mode": mode, "output_dir": OUTPUT_PATH_RULE},
            "container_image": {"fixture_only": True}, "files": {
                "operational_request_context": {"path": relative, "size_bytes": declared["size_bytes"],
                    "sha256": declared["sha256"], "container_path": container},
                "policy_calibration": {"path": "inputs/calibration.json", "size_bytes": 1, "sha256": "1" * 64}}}
        return {"system": system, "dataset": {system + "_publication_runtime_v3": contract}}

    def bind(self, system, value, **changes):
        from publication_operational_stock_operations_v1 import held_operation_runtime_inputs_v1
        arguments = dict(root=self.root, runtime_inputs=value, runtime_key=system + "_publication_runtime_v3",
            system=system, cell_context=self.cell, own_context=self.own)
        arguments.update(changes)
        return held_operation_runtime_inputs_v1(**arguments)

    def test_native_precheck_changes_only_its_own_pinned_context(self):
        original = self.runtime_inputs("openvino_gva")
        result = self.bind("openvino_gva", original)
        contract = result["dataset"]["openvino_gva_publication_runtime_v3"]
        self.assertEqual(contract["files"]["operational_request_context"], {"path": "plan/native_context_00.v1.json",
            "size_bytes": self.own["size_bytes"], "sha256": self.own["sha256"],
            "container_path": "/workspace/project/plan/native_context_00.v1.json"})
        expected = copy.deepcopy(original)
        expected["dataset"]["openvino_gva_publication_runtime_v3"]["files"]["operational_request_context"] = \
            contract["files"]["operational_request_context"]
        self.assertEqual(result, expected)
        self.assertEqual(original, self.runtime_inputs("openvino_gva"))

    def test_savant_original_keeps_sdk_context_mount_path(self):
        result = self.bind("savant", self.runtime_inputs("savant"))
        declared = result["dataset"]["savant_publication_runtime_v3"]["files"]["operational_request_context"]
        self.assertEqual(declared["container_path"], "/opt/vast/input/operational/native-context.json")
        self.assertEqual((declared["path"], declared["sha256"]), ("plan/native_context_00.v1.json", self.own["sha256"]))

    def test_foreign_or_inactive_bundle_context_is_rejected(self):
        foreign = _write_json(self.root / "plan/native_context_11.v1.json", {"fixture_only": "foreign"})
        cases = {"foreign": dict(value=self.runtime_inputs("gstreamer_custom", declared=foreign)),
            "mode": dict(value=self.runtime_inputs("gstreamer_custom", mode=DIAGNOSTIC_MODE)),
            "reuse": dict(value=self.runtime_inputs("gstreamer_custom"), own_context=self.cell)}
        for name, case in cases.items():
            with self.subTest(case=name), self.assertRaises(ValueError):
                self.bind("gstreamer_custom", case.pop("value"), **case)

    def test_held_runner_dispatches_each_system_to_its_stock_runtime(self):
        import publication_benchmark_native_diagnostic_v1 as diagnostic
        for system in pilot.SYSTEMS:
            expected = (diagnostic.run_checkpoint_gstreamer_publication_runtime_v3 if system == "gstreamer_custom"
                        else pilot.NATIVE_RUNTIME_REGISTRY[system])
            self.assertIs(diagnostic._stock_runtime_v1(system), expected)
        with self.assertRaises(KeyError):
            diagnostic._stock_runtime_v1("foreign")


if __name__ == "__main__":
    unittest.main()
