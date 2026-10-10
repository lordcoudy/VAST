"""Selected-component construction tests; local metadata is not a live grant."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import socket
import tempfile
import unittest
from unittest.mock import patch
from contextlib import ExitStack, contextmanager

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import publication_policy_qualification_runtime_inputs_v2 as stock
from analytics_execution_protocol import canonical_json_bytes, canonical_sha256, PROTOCOL_IDENTITY_SHA256
from analytics_execution_endpoint import expected_capability_from_binding_and_probe, terminal_detector_identity
from checkpoint_gstreamer_runtime import build_publication_pair_plans
from checkpoint_deepstream_protocol_bridge import analytics_backend_identity
from publication_operational_request_domain_v1 import payload_with_sha256_v1
from test_checkpoint_gstreamer_analytics_sidecar import _load_execution_config, _binding, _probe, PREPROCESSING_CONTRACT
from test_checkpoint_native_policy_runtime import capability_manifest, calibration
from test_publication_qualification_image_refreeze_v1 import _runtime_physical


class ComponentPureFactoryTests(unittest.TestCase):
    def test_native_factory_uses_explicit_current_material_without_qualification_inputs(self):
        self.assertTrue(hasattr(stock, "_runtime_contract_from_material_v1"),
                        "selected native execution must not manufacture QualificationInputs")
        cell = next(c for c in stock.qualification_pilot_cells_v2()
                    if c.system == "gstreamer_custom" and c.resource == "cpu" and c.codec == "h264")
        nvidia = {"uuid": "GPU-00000000-0000-0000-0000-000000000001", "name": "fixture", "driver_version": "1.0"}
        material = dict(files={"fixture": {"path": "inputs/file"}}, source_files=[], model_files=[],
                        support_files=[], image={"image_id": "fixture"}, engine_socket={"path": "/fixture"},
                        analytics_socket={"path": "/fixture", "device": 1, "inode": 2, "owner_uid": 1, "owner_gid": 1},
                        scratch_root=Path("/tmp"), probe={"value": {"fixture": True}},
                        capability_hashes={"cpu": "a" * 64, "gpu": "b" * 64})
        # Compare the existing wrapper's actual result, including all original
        # time/resource/evidence constants, to the explicit-material factory.
        class Inventory:
            preprocessing_sha256 = "c" * 64
        inventory = Inventory()
        inventory.nvidia = nvidia
        before = copy.deepcopy(material)
        legacy = stock._runtime_contract_for_cell(cell, inventory=inventory, **material)
        selected = stock._runtime_contract_from_material_v1(cell, nvidia=nvidia,
                    preprocessing_sha256=inventory.preprocessing_sha256, **material)
        self.assertEqual(selected, legacy)
        self.assertEqual(material, before)
        self.assertEqual(selected["ready_timeout_s"], 300.0)
        self.assertEqual(selected["container_timeout_s"], 900.0)

    def test_selected_pin_factory_does_not_read_other_system_calibrations(self):
        self.assertTrue(hasattr(stock, "_system_file_descriptors_from_pins_v1"),
                        "selected file construction must consume only explicit physical pins")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("candidate.json", "calibration.json"):
                (root / name).write_bytes(b"{}\n")
            candidate = stock._project_pin(root, "candidate.json", label="candidate fixture")
            calibration = stock._project_pin(root, "calibration.json", label="calibration fixture")
            pins = {}
            for role in ("device_probe", "experiments_config", "analytics_model_manifest"):
                path = root / role
                path.write_bytes(b"fixture\n")
                pins[role] = stock._project_pin(root, role, label=role)
            dataset = stock._project_pin(root, "candidate.json", label="dataset fixture")
            engine = pins["device_probe"]
            result = stock._system_file_descriptors_from_pins_v1(root=root, dataset_pin=dataset,
                parity_pin=dataset, candidate_pin=candidate, calibration_pin=calibration,
                system="gstreamer_custom", fixed=pins, engine_asset_path=root / "engine-copy",
                engine_pin=engine, adapter_descriptor={"path": "adapter", "size_bytes": 1, "sha256": "a" * 64})
            self.assertEqual(set(result), stock.gstreamer_runtime.FILE_ROLES)
            self.assertEqual(result["policy_calibration"]["path"], "calibration.json")
            self.assertNotIn("publication_coordinator", result)


class ComponentAuthorityFixture:
    """Genuine physical metadata/validators; no actual model or image grant."""
    def __init__(self, root):
        self.root = root
        self.config = _load_execution_config()
        self.candidate = capability_manifest()
        self.refs, self.bindings = {}, {}
        execution = self.write("inputs/execution.json", {k: v for k, v in self.config.items() if k != "identity"})
        projection = {"execution_config": {**execution, "content_identity_sha256": self.config["identity"]["sha256"],
                     "worker_projection_sha256": canonical_sha256(self.config["workers"])},
                      "binding_set": {}, "workers": {}, "runtime_probes": {}}
        terminal = []
        index_rows, identities, binding_refs = [], {}, {}
        for branch in stock.BRANCHES:
            for role in ("source", "model", "weights", "engine"):
                descriptor = self.binary("models/" + branch + "/" + role, (branch + role).encode())
                self.refs[(branch, role)] = descriptor
                terminal.append(self.mount(descriptor))
            for resource in stock.RESOURCES:
                binding = _binding(branch, resource, self.config)
                binding["source_path"] = "/workspace/" + self.refs[(branch, "source")]["path"]
                binding["source_model_sha256"] = self.refs[(branch, "source")]["sha256"]
                if resource == "cpu":
                    for field, role in (("model_path", "model"), ("weights_path", "weights")):
                        binding[field] = "/workspace/" + self.refs[(branch, role)]["path"]
                    binding["model_artifact_sha256"] = self.refs[(branch, "model")]["sha256"]
                    binding["runtime_weights_sha256"] = self.refs[(branch, "weights")]["sha256"]
                else:
                    binding["engine_path"] = "/workspace/" + self.refs[(branch, "engine")]["path"]
                    binding["model_artifact_sha256"] = self.refs[(branch, "engine")]["sha256"]
                probe = _probe(resource, self.config)
                capability = expected_capability_from_binding_and_probe(binding=binding, runtime_probe=probe, resource=resource)
                row = self.candidate["systems"]["gstreamer_custom"]["branches"][branch][resource]
                identity = {"runtime_backend": "fixture-" + resource + "-native-worker", "device_api": capability["device_api"],
                    "gpu_id": None if resource == "cpu" else 0, "worker_image_digest": capability["worker_image_id"],
                    "implementation_version": "sha256:" + capability["worker_implementation_sha256"],
                    "terminal_detector": terminal_detector_identity(capability), "terminal_backend": analytics_backend_identity(capability)}
                row.update(identity)
                row["runtime_identity"] = copy.deepcopy(identity)
                name = branch + "." + stock.ENGINE_BY_RESOURCE[resource] + ".json"
                ref = self.write("inputs/bindings/" + name, binding)
                binding_refs[branch + ":" + resource] = ref
                index_rows.append({"path": name, "bytes": ref["size_bytes"], "sha256": ref["sha256"]})
                identities[name] = canonical_sha256(binding)
                self.bindings[(branch, resource)] = binding
        core = {"schema_version": 1, "artifact_kind": "vast_analytics_execution_worker_binding_set",
            "protocol_identity_sha256": PROTOCOL_IDENTITY_SHA256, "execution_config_identity_sha256": self.config["identity"]["sha256"],
            "model_parity_manifest_identity_sha256": "a" * 64, "worker_project_root": "/workspace",
            "worker_implementation_sha256": {stock.ENGINE_BY_RESOURCE[resource]: self.config["workers"][resource]["worker_implementation_sha256"]
                                           for resource in stock.RESOURCES},
            "bindings_identity_sha256": canonical_sha256(identities), "files": index_rows}
        index = {**core, "identity": {"algorithm": "sha256", "sha256": canonical_sha256(core)}}
        index_ref = self.write("inputs/bindings/index.json", index)
        projection["binding_set"] = {"index": index_ref, "identity_sha256": index["identity"]["sha256"],
            "bindings_identity_sha256": index["bindings_identity_sha256"], "bindings": binding_refs}
        for resource in stock.RESOURCES:
            probe = _probe(resource, self.config)
            projection["runtime_probes"][resource] = {**self.write("inputs/" + resource + "-probe.json", probe),
                "worker_implementation_sha256": probe["worker_implementation_sha256"]}
            worker = self.config["workers"][resource]
            projection["workers"][resource] = {k: worker[k] for k in ("image", "image_id", "worker_implementation_sha256")}
            projection["workers"][resource].update(source_set_sha256="a" * 64, receipt_sha256="b" * 64)
        parity_ref = self.write("inputs/parity.json", {"preprocessing_contract": PREPROCESSING_CONTRACT})
        model_receipt = {"schema_version": 4, "artifact_kind": "vast_checkpoint_model_parity_acceptance_receipt_v4",
            "publication_ready": True, "blockers": [], "accepted_manifest": parity_ref,
            "refresh_authority": {**projection, "image_identity_patch": {"historical_fixture": True}}}
        model_receipt["receipt_sha256"] = canonical_sha256(model_receipt)
        receipt_ref = self.write("inputs/original-parity-receipt.json", model_receipt)
        candidate_ref = self.write("inputs/candidate.json", self.candidate)
        calibration_ref = self.write("inputs/calibration.json", calibration(self.candidate))
        sources = [self.binary("data/front.h264", b"frontfixture"), self.binary("data/underbody.h264", b"underbodyfixture")]
        config = yaml.safe_load((ROOT / stock.EXPERIMENTS_PATH).read_bytes())
        datasets = yaml.safe_load((ROOT / stock.DATASETS_PATH).read_bytes())
        selected = datasets["datasets"]["kpp_iss_publication_v3_h264"]
        old_paths = [selected["streams"][0]["path"], selected["streams"][5]["path"]]
        for row in selected["streams"]:
            ref = sources[old_paths.index(row["path"])]
            row.update(path=ref["path"], sha256=ref["sha256"])
        for row in selected["provenance"]["media_artifacts"]:
            ref = sources[old_paths.index(row["path"])]
            row.update(path=ref["path"], sha256=ref["sha256"], size_bytes=ref["size_bytes"])
        experiments_ref = self.write("configs/experiments.yaml", config)
        datasets_ref = self.write("configs/datasets.yaml", datasets)
        plans = build_publication_pair_plans(config=config, datasets=datasets["datasets"], system="gstreamer_custom", codec="h264")
        plan_refs = {key: self.write("inputs/" + key + ".plan.json", plan) for key, plan in plans.items()}
        source_ref = self.binary("scripts/current-runtime.py", b"# currentfixture\n")
        native_ref = self.binary("deploy/native_gst_probe/vast_native_gst_probe.cpp", b"// original native fixture\n")
        coordinator_ref = self.binary("scripts/checkpoint_native_policy_runtime.py", b"# original coordinator fixture\n")
        dependency_ref = self.binary("deploy/Dockerfile", b"FROM fixture\n")
        allow = self.binary("deploy/source-allowlist.txt", b"deploy/native_gst_probe/vast_native_gst_probe.cpp\nscripts/checkpoint_native_policy_runtime.py\nscripts/current-runtime.py\n")
        depallow = self.binary("deploy/dependency-allowlist.txt", b"deploy/Dockerfile\n")
        registry_ref = self.write("configs/publication_qualification_image_refreeze_v1.json", {"systems": [{"system": "gstreamer_custom",
            "source_allowlist": allow["path"], "dependency_allowlist": depallow["path"], "native_source_prefix": None}]})
        physical = _runtime_physical("gstreamer_custom", "sha256:" + "c" * 64, "c")
        def aggregate(ref):
            return hashlib.sha256((ref["sha256"] + "  " + ref["path"] + "\n").encode()).hexdigest()
        source_aggregate = hashlib.sha256(b"".join((ref["sha256"] + "  " + ref["path"] + "\n").encode()
            for ref in sorted((source_ref, native_ref, coordinator_ref), key=lambda ref: ref["path"]))).hexdigest()
        physical["source_identity"] = {"runtime_source_sha256": source_aggregate, "runtime_source_count": 3,
            "dependency_set_sha256": aggregate(dependency_ref), "dependency_count": 1,
            "source_allowlist_sha256": allow["sha256"], "source_allowlist": {"path": allow["path"], "size": allow["size_bytes"], "sha256": allow["sha256"]},
            "native_source_sha256": None, "native_source_count": 0}
        runtime_receipt = {"schema_version": 1, "artifact_kind": "vast_publication_qualification_runtime_image_freeze_receipt_v1",
            "system": "gstreamer_custom", "candidate_binding_eligible": True, "blockers": [],
            "build_registry_sha256": "a" * 64, "refreeze_registry_sha256": "b" * 64,
            "fragment_identity": {"image_id": physical["image_id"]}, "physical_identity": physical}
        runtime_receipt["receipt_sha256"] = canonical_sha256(runtime_receipt)
        image_ref = self.write("inputs/current-image-receipt.json", runtime_receipt)
        closure_ref = self.write("inputs/code-closure.json", {"kind": "vast_publication_policy_qualification_execution_code_closure_v1",
            "status": "frozen", "project_sources": [source_ref], "receipt_sha256": canonical_sha256({
                "kind": "vast_publication_policy_qualification_execution_code_closure_v1", "status": "frozen", "project_sources": [source_ref]})})
        proxies = [self.mount(self.binary("models/proxy-" + str(index), ("proxy" + str(index)).encode())) for index in range(8)]
        environment = {"proof_inputs": [source_ref, native_ref, coordinator_ref, dependency_ref, allow, depallow, registry_ref],
            "datasets_config": datasets_ref, "experiments_config": experiments_ref,
            "proxy_manifest": self.write("inputs/proxy-manifest.json", {"fixture_only": True}),
            "worker_freeze_receipt": self.write("inputs/worker-freeze.json", {"fixture_only": True})}
        self.value = payload_with_sha256_v1({"schema_version": 1, "artifact_kind": "vast_gstreamer_component_authority_v1",
            "scope": "selected_gstreamer_forced_resource_pair_only", "accepted": False, "publication_ready": False, "qualification_ready": False,
            "resource": "cpu", "policy_contract_sha256": self.candidate["policy_contract_sha256"], "capability_manifest": candidate_ref,
            "calibration": calibration_ref, "model_authority": receipt_ref, "worker_projection": projection,
            "image_authority": {"receipt": image_ref, "contract": {"image_id": physical["image_id"],
                "repository_digest": physical["canonical_repository_digest"], "inspect_projection_sha256": physical["inspect_projection_sha256"],
                "base_image_id": physical["base"]["image_id"]}}, "environment": environment,
            "planned_cells": [cell.__dict__ for cell in stock.qualification_pilot_cells_v2() if cell.system == "gstreamer_custom"
                              and cell.resource == "cpu" and cell.codec == "h264"], "source_plans": plan_refs,
            "source_descriptors": [self.mount(ref) for ref in sources], "model_descriptors": terminal,
            "proxy_model_descriptors": proxies, "execution_code_closure": closure_ref})
        self.authority = self.write("inputs/component-authority.json", self.value)

    def binary(self, name, raw):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        return {"path": name, "size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}

    def write(self, name, value):
        return self.binary(name, canonical_json_bytes(value) + b"\n")

    def mount(self, ref):
        return {**ref, "container_path": "/workspace/project/" + ref["path"]}


class ComponentPhysicalAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.fixture = ComponentAuthorityFixture(self.root)

    def load(self, **kwargs):
        from publication_gstreamer_component_authority_v1 import load_component_authority_v1
        return load_component_authority_v1(project_root=self.root,
            component_authority_path=self.root / self.fixture.authority["path"], **kwargs)

    def test_real_physical_selected_eight_keep_complete_declaration_verbatim(self):
        loaded = self.load(expected_descriptor=self.fixture.authority)
        self.assertEqual(loaded["capability_manifest"], self.fixture.candidate)
        self.assertEqual(len(loaded["worker_capabilities"]), 8)
        self.assertEqual(len(loaded["planned_cells"]), 2)
        self.assertEqual(set(loaded["source_plans"]), {"baseline", "shared"})
        self.assertFalse(loaded["document"]["publication_ready"])
        self.assertNotIn("image_identity_patch", loaded["worker_projection"])

    def test_original_stock_probe_authority_shape_and_implementation_are_bound(self):
        from checkpoint_model_parity_acceptance_v4 import validate_refresh_authority_v4
        # Only the committed receipt's metadata is read. The actual stock
        # schema validator performs no engine query or model assessment here.
        original = json.loads((ROOT / "configs/checkpoint_analytics_model_parity.refreshed.v4.qfb-20261008e.accepted.acceptance_receipt.json").read_bytes())
        refresh = validate_refresh_authority_v4(original["refresh_authority"])
        fields = {"path", "size_bytes", "sha256", "worker_implementation_sha256"}
        for resource in stock.RESOURCES:
            self.assertEqual(set(refresh["runtime_probes"][resource]), fields)
            self.assertEqual(set(self.fixture.value["worker_projection"]["runtime_probes"][resource]), fields)
        loaded = self.load()
        self.assertEqual(loaded["worker_projection"], self.fixture.value["worker_projection"])
        for label, mutate, message in (
            ("invented field", lambda row: row.update(content_identity_sha256="e" * 64), "probe authority fields"),
            ("foreign implementation", lambda row: row.update(worker_implementation_sha256="e" * 64), "probe implementation"),
        ):
            with self.subTest(label=label):
                value = copy.deepcopy(self.fixture.value)
                mutate(value["worker_projection"]["runtime_probes"]["cpu"])
                receipt = json.loads((self.root / self.fixture.value["model_authority"]["path"]).read_bytes())
                # Reseal the local fixture's original projection too, so the
                # negative reaches the actual probe join, not an earlier seal.
                receipt["refresh_authority"].update(copy.deepcopy(value["worker_projection"]))
                receipt["receipt_sha256"] = canonical_sha256({k: v for k, v in receipt.items() if k != "receipt_sha256"})
                value["model_authority"] = self.fixture.write(self.fixture.value["model_authority"]["path"], receipt)
                self.fixture.write(self.fixture.authority["path"], payload_with_sha256_v1(value))
                with self.assertRaisesRegex(ValueError, message):
                    self.load()

    def test_resealed_sibling_policy_count_and_model_binding_fail(self):
        for field, mutation in (("planned_cells", lambda v: v["planned_cells"][0].update(system="openvino_gva")),
                                ("policy", lambda v: v["planned_cells"][0].update(policy="static_hybrid")),
                                ("count", lambda v: v["planned_cells"].pop()),
                                ("worker", lambda v: v["worker_projection"]["workers"]["cpu"].update(image_id="sha256:" + "e" * 64))):
            with self.subTest(field=field):
                value = copy.deepcopy(self.fixture.value)
                mutation(value)
                self.fixture.write(self.fixture.authority["path"], payload_with_sha256_v1(value))
                with self.assertRaises(ValueError):
                    self.load()

    def test_stale_current_source_rejects_even_same_length(self):
        path = self.root / "scripts/current-runtime.py"
        raw = path.read_bytes()
        path.write_bytes(raw.replace(b"current", b"foreign"))
        with self.assertRaises((ValueError, RuntimeError)):
            self.load()

    def test_held_leaf_replacement_and_legitimate_sibling_output(self):
        from publication_gstreamer_component_authority_v1 import held_component_authority_v1
        with held_component_authority_v1(project_root=self.root, component_authority_path=self.fixture.authority["path"]) as loaded:
            (self.root / "inputs/new-output.json").write_bytes(b"{}\n")
            loaded["verify_barrier"]()
        with self.assertRaises((ValueError, RuntimeError)):
            with held_component_authority_v1(project_root=self.root, component_authority_path=self.fixture.authority["path"]):
                path = self.root / "scripts/current-runtime.py"
                replacement = path.with_name("replacement")
                replacement.write_bytes(path.read_bytes())
                replacement.replace(path)

    def test_expected_descriptor_semantic_seal_and_symlink_are_not_alias_authority(self):
        foreign = {**self.fixture.authority, "path": "inputs/another.json"}
        with self.assertRaises(ValueError):
            self.load(expected_descriptor=foreign)
        value = copy.deepcopy(self.fixture.value)
        value["resource"] = "gpu"
        self.fixture.write(self.fixture.authority["path"], value)
        with self.assertRaises(ValueError):
            self.load()
        self.fixture.write(self.fixture.authority["path"], self.fixture.value)
        path = self.root / "scripts/current-runtime.py"
        raw = path.read_bytes()
        path.unlink()
        target = self.root / "scripts/alias-target.py"
        target.write_bytes(raw)
        path.symlink_to(target.name)
        with self.assertRaises((ValueError, RuntimeError)):
            self.load()

    def test_original_seven_roles_and_front_workers_are_independently_bound(self):
        from publication_gstreamer_component_authority_v1 import validate_component_original_native_row_v1
        from publication_operational_stock_operations_v1 import front_workers_from_stock_plan_v1
        loaded = self.load()
        cell = loaded["planned_cells"][0]
        plan = loaded["source_plans"]["baseline"]
        def absolute(ref):
            return {**ref, "path": str(self.root / ref["path"])}
        refs = {"capability_manifest": loaded["capability_manifest_descriptor"], "calibration": loaded["calibration_descriptor"],
            "model_authority": loaded["document"]["model_authority"], "execution_code_closure": loaded["execution_code_closure_descriptor"],
            "policy_request_source": loaded["policy_request_source_descriptor"],
            "policy_coordinator_source": loaded["policy_coordinator_source_descriptor"],
            "source_plan": loaded["document"]["source_plans"]["baseline"]}
        row = {"phase": "diagnostic", **{key: cell[key] for key in
            ("arm_id", "run_id", "system", "scenario", "codec", "policy", "deadline_ms")}, "warmup_s": 30.0,
            "measurement_s": 180.0, "drain_timeout_s": 10.0, "streams": 6, "branches": 4,
            "descriptors": {role: absolute(ref) for role, ref in refs.items()},
            "front_workers_by_route": front_workers_from_stock_plan_v1(plan, loaded["worker_capabilities"])}
        validate_component_original_native_row_v1(source=loaded, row=row, source_plan=plan)
        for role in refs:
            changed = copy.deepcopy(row)
            changed["descriptors"][role]["sha256"] = "e" * 64
            with self.subTest(role=role), self.assertRaises(ValueError):
                validate_component_original_native_row_v1(source=loaded, row=changed, source_plan=plan)
        changed = copy.deepcopy(row)
        changed["front_workers_by_route"]["plate_number:cpu"][0]["stream_id"] = 5
        with self.assertRaises(ValueError):
            validate_component_original_native_row_v1(source=loaded, row=changed, source_plan=plan)


class ComponentHostPredicatesTests(unittest.TestCase):
    def test_actual_materializer_commits_last_and_raw_refusal_leaves_only_owned_prefix(self):
        """Only expensive model/image/closure authorities are explicit fixtures.

        Real selected worker/table validators, original stock plan construction,
        physical hashes/custody and receipt-last I/O remain exercised. This
        cannot attest an image, model, GPU or benchmark execution.
        """
        import publication_gstreamer_component_inputs_v1 as component
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            fixture = ComponentAuthorityFixture(root)
            model_ref = fixture.value["model_authority"]
            model_receipt = json.loads((root / model_ref["path"]).read_bytes())
            model_receipt["accepted_assessment"] = fixture.write("inputs/assessment.json", {"fixture_only": True})
            model_receipt["receipt_sha256"] = canonical_sha256({k: v for k, v in model_receipt.items() if k != "receipt_sha256"})
            fixture.write(model_ref["path"], model_receipt)
            profile = json.loads((root / fixture.value["calibration"]["path"]).read_bytes())
            profile.update(source_candidate_manifest_sha256=fixture.value["capability_manifest"]["sha256"],
                source_model_parity_acceptance_binding_sha256="b" * 64, source_physical_response_evidence_sha256="c" * 64)
            fixture.write(fixture.value["calibration"]["path"], profile)
            material = {"services": {}, "transfers": {}, "acceptance_binding_sha256": "b" * 64,
                "physical_response_evidence_sha256": "c" * 64, "model_parity_refresh_authority": model_receipt["refresh_authority"]}
            for branch in stock.BRANCHES:
                for resource in stock.RESOURCES:
                    row = profile["costs"][branch][resource]
                    material["services"][(branch, resource)] = [("s" + str(n), row["service_ms"]) for n in range(row["samples"])]
                    material["transfers"][(branch, resource)] = [("s" + str(n), row["transfer_ms"]) for n in range(row["samples"])]
            probe = {"schema_version": 1, "artifact_kind": "vast_openvino_checkpoint_device_probe", "openvino_version": "fixture",
                "available_devices": [{"device_id": "CPU"}], "gstreamer_elements": {
                    name: {"available": True} for name in stock.gstreamer_runtime.REQUIRED_GSTREAMER_ELEMENTS}}
            parity = {"preprocessing_contract": PREPROCESSING_CONTRACT,
                "toolchain_registry": {"tensorrt_cuda": {"gpu_uuid": "GPU-00000000-0000-0000-0000-000000000001",
                    "gpu_name": "fixture", "driver_version": "1.0"}}}
            fixture.write(model_receipt["accepted_manifest"]["path"], parity)
            # Bind the updated physical parity file into its unchanged-origin
            # fixture receipt, rather than relabeling an old physical hash.
            model_receipt["accepted_manifest"] = fixture.write(model_receipt["accepted_manifest"]["path"], parity)
            model_receipt["receipt_sha256"] = canonical_sha256({k: v for k, v in model_receipt.items() if k != "receipt_sha256"})
            fixture.write(model_ref["path"], model_receipt)
            runtime = json.loads((root / fixture.value["image_authority"]["receipt"]["path"]).read_bytes())
            closure_descriptor = fixture.value["execution_code_closure"]
            closure = json.loads((root / closure_descriptor["path"]).read_bytes())
            model_pins = tuple(stock._descriptor_pin(root, ref, label="local model pin") for ref in fixture.value["model_descriptors"])
            proxies = tuple(stock._descriptor_pin(root, ref, label="local proxy pin") for ref in fixture.value["proxy_model_descriptors"])
            proxy_manifest = stock._descriptor_pin(root, fixture.value["environment"]["proxy_manifest"], label="local proxy manifest")
            bindings = {branch: {stock.ENGINE_BY_RESOURCE[resource]: fixture.bindings[(branch, resource)]
                       for resource in stock.RESOURCES} for branch in stock.BRANCHES}
            calls = []
            def validator(**arguments):
                calls.append(arguments)
                return material
            dependencies = component.ComponentInputDependenciesV1(model_validator=validator,
                code_closure_loader=lambda **kwargs: {"receipt_descriptor": closure_descriptor, "receipt": closure},
                inspect_image=lambda *args: {"fixture_only": True}, probe_openvino_device=lambda *args: probe)
            socket_path = root / "engine.sock"
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener, ExitStack() as stack:
                listener.bind(str(socket_path))
                stack.enter_context(patch.object(component, "_current_runtime", return_value=(runtime, fixture.value["image_authority"]["contract"], {})))
                stack.enter_context(patch.object(component, "_current_workers", return_value={"fixture_only": True}))
                stack.enter_context(patch.object(component, "_proof_inputs", return_value=fixture.value["environment"]["proof_inputs"]))
                stack.enter_context(patch.object(component, "_proxy_pins", return_value=(proxy_manifest, proxies)))
                stack.enter_context(patch.object(stock, "_parity_model_inventory", return_value=model_pins))
                stack.enter_context(patch.object(component, "build_worker_bindings", return_value=bindings))
                arguments = dict(project_root=root, capability_manifest_path=fixture.value["capability_manifest"]["path"],
                    calibration_path=fixture.value["calibration"]["path"], model_parity_receipt_path=model_ref["path"],
                    runtime_image_receipt_path=fixture.value["image_authority"]["receipt"]["path"],
                    worker_freeze_receipt_path=fixture.value["environment"]["worker_freeze_receipt"]["path"],
                    execution_code_closure_path=closure_descriptor["path"], resource="cpu", output_dir=root / "prepared",
                    container_engine=Path("/usr/bin/true"), container_engine_socket=socket_path, dependencies=dependencies)
                result = component.materialize_component_authority_v1(**arguments)
                self.assertEqual(len(calls), 2)
                self.assertTrue(all(callable(call["acceptance_loader"]) for call in calls))
                self.assertEqual(result["descriptor"]["sha256"], hashlib.sha256(result["authority_path"].read_bytes()).hexdigest())
                self.assertFalse(result["document"]["publication_ready"])
                with component.held_component_authority_v1(project_root=root,
                        component_authority_path=result["authority_path"]) as loaded:
                    for field in ("source_descriptors", "model_descriptors", "proxy_model_descriptors"):
                        changed = {key: copy.deepcopy(value) for key, value in loaded.items()
                                   if key not in {"verify_barrier", "root"}}
                        changed[field][0], changed[field][1] = changed[field][1], changed[field][0]
                        with self.assertRaisesRegex(ValueError, "selected mounted"):
                            component._verify_host_material(root, changed, dependencies)
                calls.clear()
                def fail_after_original_read(**kwargs):
                    calls.append(kwargs)
                    if len(calls) % 2 == 0:
                        raise ValueError("original numeric model validation refused")
                    return material
                refused = component.ComponentInputDependenciesV1(model_validator=fail_after_original_read,
                    code_closure_loader=dependencies.code_closure_loader, inspect_image=dependencies.inspect_image,
                    probe_openvino_device=dependencies.probe_openvino_device)
                with self.assertRaisesRegex(ValueError, "original numeric model validation refused"):
                    component.materialize_component_authority_v1(**{**arguments, "output_dir": root / "refused", "dependencies": refused})
                self.assertTrue((root / "refused/baseline.source-plan.json").exists())
                self.assertFalse((root / "refused/gstreamer-component-authority.v1.json").exists())
                with self.assertRaises(ValueError):
                    component.materialize_component_authority_v1(**arguments)

    def test_selected_costs_retain_actual_original_sample_ids_and_medians(self):
        from publication_gstreamer_component_inputs_v1 import _calibration
        manifest = capability_manifest()
        profile = calibration(manifest)
        reference = {"sha256": "a" * 64}
        services, transfers = {}, {}
        for branch in stock.BRANCHES:
            for resource in stock.RESOURCES:
                row = profile["costs"][branch][resource]
                services[(branch, resource)] = [("s" + str(n), row["service_ms"]) for n in range(row["samples"])]
                transfers[(branch, resource)] = [("s" + str(n), row["transfer_ms"]) for n in range(row["samples"])]
        material = {"services": services, "transfers": transfers, "acceptance_binding_sha256": "b" * 64,
                    "physical_response_evidence_sha256": "c" * 64}
        profile.update(source_candidate_manifest_sha256="a" * 64,
                       source_model_parity_acceptance_binding_sha256="b" * 64,
                       source_physical_response_evidence_sha256="c" * 64)
        _calibration(manifest, reference, profile, material)
        changed = copy.deepcopy(material)
        changed["transfers"][("damage", "gpu")][0] = ("foreign-original-sample", 1.0)
        with self.assertRaises(ValueError):
            _calibration(manifest, reference, profile, changed)
        changed_profile = copy.deepcopy(profile)
        changed_profile["costs"]["damage"]["gpu"]["service_ms"] += 0.01
        with self.assertRaises(ValueError):
            _calibration(manifest, reference, changed_profile, material)

    def test_model_observer_accepts_actual_stock_formatted_inspect_contract(self):
        import checkpoint_model_parity as parity
        import publication_gstreamer_component_inputs_v1 as component
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            socket_path = root / "engine.sock"
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
                listener.bind(str(socket_path))
                engine = stock._external_executable_pin(Path("/usr/bin/true"), label="genuine fixture ELF")
                socket_pin = stock._socket_record(socket_path, label="genuine fixture socket")
                (root / "receipt.json").write_bytes(canonical_json_bytes({
                    "accepted_manifest": {"path": "manifest"},
                    "accepted_assessment": {"path": "assessment"}}) + b"\n")
                images = ["sha256:" + char * 64 for char in "abcd"]
                runners = []
                def model_validator(**kwargs):
                    return kwargs["acceptance_loader"](project_root=root, receipt_path=root / "receipt.json")
                def accepted_loader(**kwargs):
                    runners.append(kwargs["command_runner"])
                    # Keep both original native-base and both worker inspect
                    # roles; these are explicit local image metadata fixtures.
                    return [parity._inspect_image(image, runners[-1]) for image in images]
                def formatted_object(argv, **kwargs):
                    return {"Id": argv[-1], "RepoDigests": [], "Architecture": "amd64", "Os": "linux"}
                dependency = component.ComponentInputDependenciesV1(model_validator=model_validator)
                with patch("checkpoint_model_parity_acceptance_v4.load_verified_model_parity_acceptance_v4", side_effect=accepted_loader), \
                     patch.object(stock, "_run_json", side_effect=formatted_object) as observed:
                    result = component._model_material(root, "receipt.json", dependency, engine=engine, engine_socket=socket_pin)
                    self.assertEqual(result, [{"reference": image, "image_id": image, "repo_digests": [],
                        "architecture": "amd64", "os": "linux"} for image in images])
                    self.assertEqual([call.args[0] for call in observed.call_args_list], [
                        (str(engine.path), "--host=unix://" + str(socket_path), *parity.build_image_inspect_command(image)[1:])
                        for image in images])
                    before = observed.call_count
                    for command in (["docker", "image", "inspect", images[0]],
                                    ["docker", "container", "inspect", "--format", "{{json .}}", images[0]],
                                    ["docker", "image", "inspect", "--format", "{{json .Id}}", images[0]],
                                    [*parity.build_image_inspect_command(images[0]), "foreign"],
                                    ["docker", "image", "inspect", "--format", "{{json .}}", None]):
                        with self.subTest(command=command), self.assertRaises(ValueError):
                            runners[0](command)
                    self.assertEqual(observed.call_count, before)
                with patch.object(stock, "_run_json", return_value=[{"Id": images[0]}]):
                    with self.assertRaisesRegex(ValueError, "object"):
                        runners[0](parity.build_image_inspect_command(images[0]))

    def test_model_observer_routes_only_inspect_to_original_pinned_engine_socket(self):
        import checkpoint_model_parity as parity
        import publication_gstreamer_component_inputs_v1 as component
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            socket_path = root / "engine.sock"
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
                listener.bind(str(socket_path))
                engine = stock._external_executable_pin(Path("/usr/bin/true"), label="genuine fixture ELF")
                socket_pin = stock._socket_record(socket_path, label="genuine fixture socket")
                raw = canonical_json_bytes({"accepted_manifest": {"path": "manifest"}, "accepted_assessment": {"path": "assessment"}}) + b"\n"
                (root / "receipt.json").write_bytes(raw)
                runners = []
                def model_validator(**kwargs):
                    return kwargs["acceptance_loader"](project_root=root, receipt_path=root / "receipt.json")
                def accepted_loader(**kwargs):
                    runner = kwargs["command_runner"]
                    runners.append(runner)
                    return runner(parity.build_image_inspect_command("sha256:" + "a" * 64))
                dependency = component.ComponentInputDependenciesV1(model_validator=model_validator)
                with patch("checkpoint_model_parity_acceptance_v4.load_verified_model_parity_acceptance_v4", side_effect=accepted_loader), \
                     patch.object(stock, "_run_json", return_value={"Id": "sha256:" + "a" * 64}) as observed:
                    value = component._model_material(root, "receipt.json", dependency, engine=engine, engine_socket=socket_pin)
                self.assertEqual(json.loads(value)["Id"], "sha256:" + "a" * 64)
                self.assertEqual(observed.call_args.args[0], (str(engine.path), "--host=unix://" + str(socket_path),
                                                             "image", "inspect", "--format", "{{json .}}", "sha256:" + "a" * 64))
                with self.assertRaises(ValueError):
                    runners[0](["docker", "run", "--rm", "foreign"])

    def test_materializer_refuses_bad_mode_or_occupied_output_before_any_preflight(self):
        import publication_gstreamer_component_inputs_v1 as component
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            output = root / "occupied"
            output.mkdir()
            arguments = dict(project_root=root, capability_manifest_path="missing", calibration_path="missing",
                model_parity_receipt_path="missing", runtime_image_receipt_path="missing", worker_freeze_receipt_path="missing",
                execution_code_closure_path="missing", resource="cpu", output_dir=output)
            with patch.object(component, "_model_material") as validator:
                with self.assertRaises(ValueError):
                    component.materialize_component_authority_v1(**arguments)
                with self.assertRaises(ValueError):
                    component.materialize_component_authority_v1(**{**arguments, "resource": "static_hybrid"})
                validator.assert_not_called()


class ComponentHeldSessionTests(unittest.TestCase):
    """Real input FDs and stock image projection; expensive authorities are fixtures."""
    def setUp(self):
        import publication_gstreamer_component_inputs_v1 as component
        import checkpoint_model_parity as parity
        self.component, self.parity = component, parity
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.fixture = ComponentAuthorityFixture(self.root)
        self.authority = self.root / self.fixture.authority["path"]
        self.socket_path = self.root / "session-engine.sock"
        self.listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.listener.bind(str(self.socket_path))
        self.addCleanup(self.listener.close)
        engine_path = self.root / "session-engine"
        engine_path.write_bytes(Path("/usr/bin/true").read_bytes())
        engine_path.chmod(0o555)
        self.engine = stock._external_executable_pin(engine_path, label="genuine local fixture ELF")
        self.socket_pin = stock._socket_record(self.socket_path, label="genuine local fixture socket")
        self.full_calls = 0
        self.images = ["sha256:" + c * 64 for c in "abcd"]
        self.raw = {image: {"Id": image, "RepoDigests": ["fixture@" + image],
            "Architecture": "amd64", "Os": "linux"} for image in self.images}
        self.projections = [(tuple(parity.build_image_inspect_command(image)),
            parity._inspect_image(image, lambda _command, image=image: json.dumps(self.raw[image])))
            for image in self.images]

    @contextmanager
    def session(self):
        component = self.component
        @contextmanager
        def held_fixture(**arguments):
            # The real pure loader owns original files/epochs. Only unavailable
            # complete model/image acceptance is explicitly injected here.
            self.full_calls += 1
            with component.held_component_authority_v1(project_root=self.root,
                    component_authority_path=self.authority) as selected:
                original = selected["verify_barrier"]
                def verify():
                    original()
                    stock._require_file_pin_unchanged(self.engine, label="original fixture engine")
                    if stock._socket_record(self.socket_path, label="original fixture socket") != self.socket_pin:
                        raise ValueError("fixture original socket drift")
                selected.update(engine_pin=self.engine, engine_socket=self.socket_pin, verify_barrier=verify)
                arguments["_image_observations"][:] = copy.deepcopy(self.projections)
                yield selected
        with patch.object(component, "_held_selected_component_inputs_v1", held_fixture), \
             patch.object(stock, "_run_json", side_effect=lambda argv, **kw: copy.deepcopy(self.raw[argv[-1]])) as observed:
            with component._held_selected_component_session_v1(project_root=self.root,
                    component_authority_path=self.authority) as session:
                yield session, observed

    def borrow(self, session, boundary="execute", **changes):
        return self.component._borrow_selected_component_session_v1(session, project_root=self.root,
            component_authority_path=self.authority, boundary=boundary, **changes)

    def test_five_boundaries_share_one_full_assessment_but_observe_twenty_images(self):
        with self.session() as (session, observed):
            for boundary in ("materialize", "execute", "execute", "cold", "cold"):
                with self.borrow(session, boundary) as selected:
                    self.assertEqual(selected["root"], self.root)
            self.assertEqual(self.full_calls, 1)
            self.assertEqual(observed.call_count, 20)
            self.assertEqual([c.args[0][-1] for c in observed.call_args_list], self.images * 5)

    def test_raw_dict_foreign_pid_root_authority_and_closed_session_fail(self):
        with self.session() as (session, observed):
            with self.assertRaises(ValueError), self.borrow({}):
                pass
            with patch.object(self.component.os, "getpid", return_value=session._owner + 1):
                with self.assertRaises(ValueError), self.borrow(session):
                    pass
            for root, authority in ((self.root.parent, self.authority),
                                    (self.root, self.root / "another-authority.json")):
                with self.assertRaises(ValueError), self.component._borrow_selected_component_session_v1(session,
                        project_root=root, component_authority_path=authority, boundary="execute"):
                    pass
            self.assertEqual(observed.call_count, 0)
            with self.assertRaises(ValueError):
                self.component._SelectedComponentSession(object(), session._selected, self.projections)
        with self.assertRaises(ValueError), self.borrow(session):
            pass

    def test_same_bytes_replacement_is_rejected_before_live_image_observation(self):
        with self.assertRaises(ValueError), self.session() as (session, observed):
            path = self.root / self.fixture.value["source_descriptors"][0]["path"]
            raw = path.read_bytes()
            replacement = path.with_name(path.name + ".replacement")
            replacement.write_bytes(raw)
            os.replace(replacement, path)
            with self.borrow(session):
                pass
        self.assertEqual(observed.call_count, 0)

    def test_same_image_id_does_not_hide_projection_drift(self):
        for field, changed in (("RepoDigests", ["foreign@sha256:" + "e" * 64]),
                               ("Architecture", "foreign"), ("Os", "foreign")):
            with self.subTest(field=field), self.session() as (session, observed):
                with patch.object(stock, "_run_json", return_value={**self.raw[self.images[0]], field: changed}):
                    with self.assertRaisesRegex(ValueError, "projection"), self.borrow(session):
                        pass

    def test_engine_bytes_or_socket_identity_drift_rejects(self):
        with self.session() as (session, observed):
            self.engine.path.chmod(0o755)
            self.engine.path.write_bytes(b"foreign fixture ELF bytes")
            with self.assertRaises(Exception), self.borrow(session):
                pass
            self.assertEqual(observed.call_count, 0)

    def test_original_socket_replacement_and_ancestor_alias_reject_before_inspect(self):
        with self.session() as (session, observed):
            self.socket_path.unlink()
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as foreign:
                foreign.bind(str(self.socket_path))
                with self.assertRaises(ValueError), self.borrow(session):
                    pass
                self.assertEqual(observed.call_count, 0)
        # A real ancestor alias must not become a legitimate session root.
        alias = self.root / "root-alias"
        alias.symlink_to(self.root, target_is_directory=True)
        with self.session() as (session, observed):
            with self.assertRaises(ValueError), self.component._borrow_selected_component_session_v1(
                    session, project_root=alias, component_authority_path=self.authority, boundary="execute"):
                pass
            self.assertEqual(observed.call_count, 0)

    def test_private_projection_collector_publishes_only_after_complete_assessment(self):
        images = {"base": {"cpu": self.projections[0][1], "gpu": self.projections[2][1]},
                  "workers": {"cpu": self.projections[1][1], "gpu": self.projections[3][1]}}
        receipt = {"accepted_manifest": {"path": "fixture-manifest"},
            "accepted_assessment": {"path": "fixture-assessment"}, "runtime_images": images}
        path = self.root / "collection-receipt.json"
        path.write_bytes(canonical_json_bytes(receipt) + b"\n")
        result = {"acceptance_binding": {"runtime_images_sha256": self.component.canonical_sha256(images)}}
        collector, cases = [], []
        def accepted_loader(**arguments):
            for image in cases or self.images:
                self.parity._inspect_image(image, arguments["command_runner"])
            # The external numeric/model assessment is an explicit fixture.
            # Collection is still private until its complete validator returns.
            self.assertEqual(collector, [])
            return copy.deepcopy(result)
        def validator(**arguments):
            return arguments["acceptance_loader"](project_root=self.root, receipt_path=path)
        dependencies = self.component.ComponentInputDependenciesV1(model_validator=validator)
        with patch("checkpoint_model_parity_acceptance_v4.load_verified_model_parity_acceptance_v4",
                side_effect=accepted_loader), patch.object(stock, "_run_json",
                side_effect=lambda argv, **kw: copy.deepcopy(self.raw[argv[-1]])):
            actual = self.component._model_material(self.root, path.name, dependencies,
                engine=self.engine, engine_socket=self.socket_pin, _image_observations=collector)
            self.assertEqual(actual, result)
            self.assertEqual(collector, self.projections)
            for changed in (self.images[:3], self.images[::-1], self.images + [self.images[0]]):
                cases[:] = changed
                collector.clear()
                with self.subTest(changed=changed), self.assertRaises(ValueError):
                    self.component._model_material(self.root, path.name, dependencies,
                        engine=self.engine, engine_socket=self.socket_pin, _image_observations=collector)
                self.assertEqual(collector, [])
            cases.clear()
            result["acceptance_binding"]["runtime_images_sha256"] = "f" * 64
            with self.assertRaises(ValueError):
                self.component._model_material(self.root, path.name, dependencies,
                    engine=self.engine, engine_socket=self.socket_pin, _image_observations=collector)
            self.assertEqual(collector, [])
        with patch("checkpoint_model_parity_acceptance_v4.load_verified_model_parity_acceptance_v4",
                 side_effect=RuntimeError("original complete assessment refused")):
            with self.assertRaisesRegex(RuntimeError, "original complete assessment refused"):
                self.component._model_material(self.root, path.name, dependencies,
                    engine=self.engine, engine_socket=self.socket_pin, _image_observations=collector)
            self.assertEqual(collector, [])

    def test_public_held_inputs_retains_independent_complete_validation(self):
        @contextmanager
        def expensive_fixture(**arguments):
            self.full_calls += 1
            self.assertIsNone(arguments.get("_image_observations"))
            with self.component.held_component_authority_v1(project_root=self.root,
                    component_authority_path=self.authority) as selected:
                yield selected
        with patch.object(self.component, "_held_selected_component_inputs_v1", expensive_fixture):
            for _ in range(2):
                with self.component.held_selected_component_inputs_v1(project_root=self.root,
                        component_authority_path=self.authority):
                    pass
        self.assertEqual(self.full_calls, 2)

    def test_exception_closes_actual_input_fds_and_keeps_original_failure(self):
        from publication_gstreamer_component_authority_v1 import ComponentPinsV1
        closed = []
        original_close = ComponentPinsV1.close
        def close(pins):
            closed.extend(row[1] for row in pins.files.values())
            original_close(pins)
        with patch.object(ComponentPinsV1, "close", close):
            with self.assertRaisesRegex(RuntimeError, "original fixture arm failure"):
                with self.session() as (session, observed), self.borrow(session):
                    raise RuntimeError("original fixture arm failure")
        self.assertTrue(closed)
        for fd in closed:
            with self.assertRaises(OSError):
                os.fstat(fd)
        self.assertFalse(session._active)


if __name__ == "__main__":
    unittest.main()
