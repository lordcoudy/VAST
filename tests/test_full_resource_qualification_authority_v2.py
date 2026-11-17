"""Amendment 8: resource index branch for authority-binding-v2 (F2), topology v2 in
resource pilot revalidation (F3) and the host-only boundary of F1-F3."""
from __future__ import annotations

import copy
import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
for _path in (ROOT, SCRIPTS, ROOT / "tests"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import full_resource_qualification as qualification  # noqa: E402
import full_resource_qualification_index_v1 as target  # noqa: E402
import publication_policy_qualification_execution_code_closure_v1 as code_closure  # noqa: E402
import publication_policy_qualification_fragments_from_authority_v2 as fragments_v2  # noqa: E402
import tests.test_topology_contract as topology_fixture  # noqa: E402
from tests.test_full_resource_qualification import _datasets  # noqa: E402


AUTHORITY_KIND = "vast_publication_policy_qualification_authority_binding_v2"
INTERVAL_EMITTERS = {
    "deepstream": "scripts/checkpoint_deepstream_resource_runtime_v3.py",
    "savant": "scripts/checkpoint_savant_resource_runtime_v3.py",
    "openvino_gva": "deploy/native_gst_probe/checkpoint_resource_interval_emitter.hpp",
    "gstreamer_custom": "deploy/native_gst_probe/checkpoint_resource_interval_emitter.hpp",
}
HOST_SOURCES = (
    "scripts/full_resource_contract.py",
    "scripts/resource_interval_contract.py",
    "scripts/collect_metrics.py",
    *sorted(set(INTERVAL_EMITTERS.values())),
)
# Host-only Amendment 8 files (F1-F3): outside the execution code closure and every image allowlist.
HOST_ONLY = (
    "scripts/publication_qualification_promotion_v2.py",
    "scripts/full_resource_qualification_index_v1.py",
    "scripts/full_resource_qualification.py",
)


def _descriptor(root: Path, path: Path) -> dict:
    payload = path.read_bytes()
    return {
        "path": path.relative_to(root).as_posix(),
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _runtime_identity(system: str, resource: str) -> dict:
    return {
        "runtime_backend": f"{system}_physical_runtime_authority_v2",
        "analytics_device_api": "HOST_CPU" if resource == "cpu" else "NVIDIA_CUDA",
        "decoder_device_api": "NVIDIA_NVDEC",
        "worker_image_digest": "sha256:" + "3" * 64,
        "implementation_version": "patch-sha256:" + "9" * 64,
        "hardware_binding_id": "nvidia-gpu:GPU-fixture:driver-610.47",
    }


class AuthorityBindingV2ResourceIndexTests(unittest.TestCase):
    """(b) F2 accepts exactly the transaction-v2 binding kind; everything else is refused."""

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="resource-authority-v2-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        for relative in HOST_SOURCES:
            destination = self.root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, destination)
        self.contract = target._build_resource_contract(self.root)

    def binding(self, coordinate_system: str, coordinate_resource: str, **changes) -> tuple[dict, dict]:
        system, resource = coordinate_system, coordinate_resource
        identity = _runtime_identity(system, resource)
        document = {
            "schema_version": 2,
            "artifact_kind": AUTHORITY_KIND,
            "system": system,
            "role": "resource",
            "branch": "all_branches",
            "resource": resource,
            "implementation_id": f"{system}-full-resource-authority-v2:{resource}:" + "a" * 64,
            "emitter_id": f"{system}-native-resource-emitter-v2:{resource}:" + "a" * 64,
            "runtime_identity": identity,
            "authority": {"fixture": "embedded authority"},
        }
        resign = changes.pop("_resign", True)
        document.update(changes)
        document["binding_sha256"] = fragments_v2._self_sha(document, "binding_sha256")
        if not resign:
            document["authority"] = {"fixture": "edited after signing"}
        path = self.root / f"artifacts/fragments/{system}/bindings/resource/{resource}.binding.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(fragments_v2._canonical_bytes(document) + b"\n")
        item = _descriptor(self.root, path)
        row = {
            "branch": "all_branches", "resource": resource, "role": "resource",
            "implementation_id": f"{system}-full-resource-authority-v2:{resource}:" + "a" * 64,
            "emitter_id": f"{system}-native-resource-emitter-v2:{resource}:" + "a" * 64,
            "path": item["path"], "size": item["size_bytes"], "sha256": item["sha256"],
            "runtime_identity": copy.deepcopy(identity),
        }
        return document, row

    def read(self, system: str, resource: str, row: dict) -> dict:
        return target._read_binding(
            root=self.root, system=system, resource=resource, row=row,
            resource_contract=self.contract,
        )

    def test_authority_v2_binding_projects_static_resource_v2_evidence(self) -> None:
        for system in qualification.SYSTEMS:
            for resource in qualification.RESOURCES:
                with self.subTest(system=system, resource=resource):
                    _document, row = self.binding(system, resource)
                    value = self.read(system, resource, row)
                    interval = _descriptor(self.root, self.root / INTERVAL_EMITTERS[system])
                    collector = _descriptor(self.root, self.root / "scripts/collect_metrics.py")
                    self.assertEqual(value["implementation_artifact"]["path"], row["path"])
                    self.assertEqual(value["runtime_identity"], row["runtime_identity"])
                    self.assertEqual(
                        {role: item["artifact"] for role, item in value["emitters"].items()},
                        {
                            "resource_intervals": interval,
                            "fanout_work_counters": interval,
                            "hardware_resource_samples": collector,
                        },
                    )
                    self.assertEqual(
                        value["emitters"]["resource_intervals"]["emitter_id"],
                        f"{row['emitter_id']}:resource_intervals",
                    )

    def test_drifted_authority_v2_bindings_are_refused(self) -> None:
        cases = {
            "schema_version": {"schema_version": 1},
            "self_hash": {"_resign": False},
            "role": {"role": "policy"},
            "branch": {"branch": "plate_number"},
            "system": {"system": "savant"},
            "resource": {"resource": "gpu"},
            "implementation_id": {"implementation_id": "deepstream-full-resource-authority-v2:cpu:" + "b" * 64},
            "emitter_id": {"emitter_id": "deepstream-native-resource-emitter-v2:cpu:" + "b" * 64},
            "runtime_identity": {"runtime_identity": _runtime_identity("deepstream", "gpu")},
            "image": {"runtime_identity": {**_runtime_identity("deepstream", "cpu"), "worker_image_digest": "sha256:bad"}},
        }
        for name, change in cases.items():
            with self.subTest(case=name):
                _document, row = self.binding("deepstream", "cpu", **change)
                if name in {"runtime_identity", "image"}:
                    row["runtime_identity"] = copy.deepcopy(change["runtime_identity"])
                with self.assertRaises(target.FullResourceQualificationIndexV1Error):
                    self.read("deepstream", "cpu", row)

    def test_foreign_study_and_component_kinds_are_refused(self) -> None:
        for kind in (
            "vast_finite_study_selected_native_image_v1",
            "vast_gstreamer_component_authority_v1",
            "vast_gstreamer_component_runtime_bundle_v1",
            "vast_deepstream_resource_binding_material_v2",
            "vast_publication_policy_qualification_authority_binding_v3",
        ):
            with self.subTest(kind=kind):
                _document, row = self.binding("deepstream", "cpu", artifact_kind=kind)
                with self.assertRaises(target.FullResourceQualificationIndexV1Error):
                    self.read("deepstream", "cpu", row)


class ResourcePilotTopologyV2Tests(unittest.TestCase):
    """(c) resource promotion revalidates pilots with the checkpoint scenario topology v2."""

    def _arm(self, root: Path, rows: list[dict]) -> tuple[dict, dict]:
        arm = root / "pilots/deepstream/cpu/h264/shared_video_dag"
        arm.mkdir(parents=True)
        files = {}
        for role in qualification.PILOT_EVIDENCE_ROLES:
            if role == "checkpoint_acceptance":
                continue
            path = arm / f"{role}.csv"
            if role == "topology_events":
                topology_fixture.write_rows(path, rows)
            else:
                path.write_text(f"{role}\n", encoding="utf-8")
            files[role] = path
        hashes = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in files.values()}
        acceptance = arm / "checkpoint_qualification_pilot_acceptance.json"
        acceptance.write_text("{}\n", encoding="utf-8")
        evidence = {"checkpoint_acceptance": _descriptor(root, acceptance)}
        evidence.update({role: _descriptor(root, path) for role, path in files.items()})
        value = {
            "run_id": "resource-pilot-fixture",
            "scenario": "checkpoint_video_dag_shared",
            "full_resource_finalization": {
                "hardware_collector_stopped": True,
                "validation": "full_resource_evidence_v2_passed",
                "prepared_by": "prepare_checkpoint_publication_acceptance",
            },
            "evidence_sha256": hashes,
            "full_resource_evidence_sha256": {
                f"{role}.csv": hashes[f"{role}.csv"] for role in qualification.EMITTER_ROLES
            },
        }
        return evidence, value

    def _revalidate(self, rows: list[dict]) -> str:
        """Run the stock resource pilot validator up to the sidecar stage; return its refusal."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            evidence, acceptance = self._arm(root, rows)
            frames = topology_fixture.frames()
            frame_events = topology_fixture.frame_events(rows)

            def sidecars_reached(*_args, **_kwargs):
                raise RuntimeError("topology accepted; sidecar stage reached")

            validators = {
                "canonicalize_frames_csv": lambda *_a, **_k: frames,
                "validate_frame_events": lambda *_a, **_k: frame_events,
                "validate_topology_events": topology_fixture.validate_topology_events,
                "validate_required_sidecars": sidecars_reached,
                "accepted_arm_evidence_files": lambda *_a, **_k: set(acceptance["evidence_sha256"]),
                "validate_frozen_policy_decisions": None,
            }
            pilot = {"system": "deepstream", "resource": "cpu", "codec": "h264",
                     "topology_kind": "shared_video_dag", "evidence": evidence}
            with mock.patch.object(
                qualification, "validate_checkpoint_qualification_pilot_acceptance_v1",
                return_value=acceptance,
            ), mock.patch.object(qualification, "_load_resource_validators", return_value=validators), \
                    mock.patch.object(qualification, "BRANCHES", tuple(topology_fixture.BRANCHES)):
                with self.assertRaises(qualification.FullResourceQualificationError) as raised:
                    qualification._default_pilot_validator(
                        pilot,
                        {"project_root": root, "pilot_evidence": evidence, "datasets": _datasets()},
                    )
            return str(raised.exception)

    def test_postprocess_stages_of_topology_v2_are_accepted(self) -> None:
        rows = topology_fixture.postprocess_v2_rows(topology_fixture.shared_rows())
        self.assertIn("sidecar stage reached", self._revalidate(rows))

    def test_topology_without_postprocess_is_refused_under_v2(self) -> None:
        refusal = self._revalidate(topology_fixture.shared_rows())
        self.assertNotIn("sidecar stage reached", refusal)
        self.assertIn("postprocess", refusal)


class HostOnlyBoundaryTests(unittest.TestCase):
    """(d) F1-F3 stay host-only: outside the closure graph and all image allowlists."""

    def test_amendment8_files_are_outside_execution_code_closure(self) -> None:
        for relative in HOST_ONLY:
            self.assertTrue((ROOT / relative).is_file(), relative)
        closure = {
            path.relative_to(ROOT).as_posix()
            for _module, path in code_closure._discover_sources(ROOT)
        }
        self.assertTrue(closure, "closure graph must not be empty")
        for relative in HOST_ONLY:
            self.assertNotIn(relative, closure)

    def test_amendment8_files_are_outside_every_image_allowlist(self) -> None:
        sources = sorted(ROOT.glob("deploy/**/*allowlist*.txt")) + [
            ROOT / "configs/publication_image_build_v1.json",
            ROOT / "configs/publication_qualification_image_refreeze_v1.json",
        ]
        self.assertGreater(len(sources), 10)
        for source in sources:
            text = source.read_text(encoding="utf-8")
            for relative in HOST_ONLY:
                with self.subTest(allowlist=source.relative_to(ROOT).as_posix(), path=relative):
                    self.assertNotIn(Path(relative).name, text)


if __name__ == "__main__":
    unittest.main()
