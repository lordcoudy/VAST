from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from types import MappingProxyType
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import checkpoint_deepstream_publication_runtime_v3 as deepstream  # noqa: E402
import checkpoint_gstreamer_publication_runtime_v3 as gstreamer  # noqa: E402
import checkpoint_openvino_gva_publication_runtime_v3 as openvino  # noqa: E402
import checkpoint_savant_publication_runtime_v3 as savant  # noqa: E402
import publication_physical_io_v1 as physical_io  # noqa: E402
from checkpoint_publication_launcher_adapter_v3 import (  # noqa: E402
    NativePublicationRequestV3,
)
from publication_child_evidence_materializer_v1 import (  # noqa: E402
    INTENT_KIND_V1,
    INTENT_ROOT_V1,
    RECEIPT_KIND_V1,
    RECEIPT_ROOT_V1,
)


_WRAPPERS: tuple[tuple[str, Any, type[RuntimeError]], ...] = (
    ("openvino_gva", openvino, openvino.OpenVINOGVAPublicationRuntimeV3Error),
    ("gstreamer_custom", gstreamer, gstreamer.GstreamerPublicationRuntimeV3Error),
    ("deepstream", deepstream, deepstream.DeepStreamPublicationRuntimeV3Error),
    ("savant", savant, savant.SavantPublicationRuntimeV3Error),
)
_TARGETS = ("first-evidence.json", "second-evidence.json")
_MAPPING = {
    "first-evidence.json": "child-first.json",
    "second-evidence.json": "child-second.json",
}
_PAYLOADS = {
    "child-first.json": b'{"child":"first"}\n',
    "child-second.json": b'{"child":"second"}\n',
}
_PHYSICAL_STEPS = (
    "mid_write",
    "post_fsync_pre_publish",
    "post_publish_pre_parent_fsync",
)


def _request(root: Path, output: Path, *, system: str) -> NativePublicationRequestV3:
    arm = output / "backend_publication_arm_contract.json"
    if not arm.exists():
        arm.write_bytes(b'{"parent":"arm"}\n')
    return NativePublicationRequestV3(
        system=system,
        topology_kind="single_process",
        scenario="nominal",
        project_root=root,
        output_dir=output,
        arm_contract_path=arm,
        arm_contract_file_sha256=hashlib.sha256(arm.read_bytes()).hexdigest(),
        run_id="run-child-evidence-v1",
        arm_id=f"arm-{system}",
        runtime_inputs=MappingProxyType({}),
        launcher_evidence_files=_TARGETS,
    )


def _case(root: Path, *, name: str) -> tuple[Path, Path, NativePublicationRequestV3]:
    source = root / f"source-{name}"
    output = root / f"output-{name}"
    source.mkdir()
    output.mkdir()
    for leaf, payload in _PAYLOADS.items():
        (source / leaf).write_bytes(payload)
    return source, output, _request(root, output, system=name)


def _receipt_path(root: Path, output: Path) -> Path:
    relative = output.relative_to(root).as_posix()
    key = hashlib.sha256(relative.encode("ascii")).hexdigest()
    return root / RECEIPT_ROOT_V1 / f"group-{key}.json"


def _intent_path(root: Path, output: Path) -> Path:
    relative = output.relative_to(root).as_posix()
    key = hashlib.sha256(relative.encode("ascii")).hexdigest()
    return root / INTENT_ROOT_V1 / f"group-{key}.json"


@unittest.skipUnless(os.name == "posix" and hasattr(os, "fork"), "WSL/POSIX only")
class PublicationChildEvidenceMaterializerV1Tests(unittest.TestCase):
    maxDiff = None

    def _run_three_window_matrix(
        self, *, system: str, module: Any, error_type: type[RuntimeError]
    ) -> None:
        del error_type
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            fault_prefixes = (
                "intent",
                f"leaf:{_TARGETS[1]}",
                "receipt",
            )
            for fault_prefix in fault_prefixes:
                for step in _PHYSICAL_STEPS:
                    with self.subTest(
                        system=system, boundary=fault_prefix, step=step
                    ):
                        case_root = root / f"{fault_prefix.replace(':', '-')}-{step}"
                        case_root.mkdir()
                        source, output, request = _case(case_root, name=system)
                        target_label = f"{fault_prefix}:{step}"
                        child = os.fork()
                        if child == 0:
                            # Force the WSL/DrvFS hard-link fallback even when the
                            # test temp directory itself supports renameat2.
                            physical_io._RENAMEAT2_API = False
                            module._copy_evidence(
                                source,
                                request,
                                _MAPPING,
                                _fault_hook=lambda observed: (
                                    os._exit(91)
                                    if observed == target_label
                                    else None
                                ),
                            )
                            os._exit(0)
                        waited, status = os.waitpid(child, 0)
                        self.assertEqual(waited, child)
                        self.assertTrue(os.WIFEXITED(status))
                        self.assertEqual(os.WEXITSTATUS(status), 91)

                        existing_identities = {
                            name: (
                                int((output / name).stat().st_dev),
                                int((output / name).stat().st_ino),
                            )
                            for name in _TARGETS
                            if (output / name).exists()
                        }
                        if fault_prefix == "intent":
                            self.assertEqual(existing_identities, {})
                        elif fault_prefix.startswith("leaf:"):
                            self.assertIn(_TARGETS[0], existing_identities)
                            if step == "post_publish_pre_parent_fsync":
                                self.assertEqual(
                                    (output / _TARGETS[1]).stat().st_nlink, 2
                                )
                            else:
                                self.assertNotIn(_TARGETS[1], existing_identities)
                        else:
                            self.assertEqual(set(existing_identities), set(_TARGETS))

                        if step == "post_publish_pre_parent_fsync":
                            if fault_prefix == "intent":
                                self.assertEqual(
                                    _intent_path(case_root, output).stat().st_nlink,
                                    2,
                                )
                            elif fault_prefix == "receipt":
                                self.assertEqual(
                                    _receipt_path(case_root, output).stat().st_nlink,
                                    2,
                                )

                        module._copy_evidence(source, request, _MAPPING)
                        identities = tuple(
                            (
                                int((output / name).stat().st_dev),
                                int((output / name).stat().st_ino),
                            )
                            for name in _TARGETS
                        )
                        for position, name in enumerate(_TARGETS):
                            if name in existing_identities:
                                self.assertEqual(
                                    identities[position], existing_identities[name]
                                )
                            info = (output / name).stat()
                            self.assertEqual(info.st_nlink, 1)
                            self.assertEqual(stat.S_IMODE(info.st_mode), 0o444)
                            self.assertEqual(
                                (output / name).read_bytes(),
                                _PAYLOADS[_MAPPING[name]],
                            )

                        # A lost caller response after receipt-last is idempotent
                        # and preserves every committed inode.
                        module._copy_evidence(source, request, _MAPPING)
                        self.assertEqual(
                            identities,
                            tuple(
                                (
                                    int((output / name).stat().st_dev),
                                    int((output / name).stat().st_ino),
                                )
                                for name in _TARGETS
                            ),
                        )
                        intent = json.loads(
                            _intent_path(case_root, output).read_text("ascii")
                        )
                        receipt = json.loads(
                            _receipt_path(case_root, output).read_text("ascii")
                        )
                        self.assertEqual(intent["artifact_kind"], INTENT_KIND_V1)
                        self.assertEqual(receipt["artifact_kind"], RECEIPT_KIND_V1)
                        self.assertEqual(
                            [item["target_name"] for item in receipt["leaves"]],
                            list(_TARGETS),
                        )

    def test_openvino_three_physical_windows_resume_same_path(self) -> None:
        self._run_three_window_matrix(
            system="openvino_gva",
            module=openvino,
            error_type=openvino.OpenVINOGVAPublicationRuntimeV3Error,
        )

    def test_gstreamer_three_physical_windows_resume_same_path(self) -> None:
        self._run_three_window_matrix(
            system="gstreamer_custom",
            module=gstreamer,
            error_type=gstreamer.GstreamerPublicationRuntimeV3Error,
        )

    def test_deepstream_three_physical_windows_resume_same_path(self) -> None:
        self._run_three_window_matrix(
            system="deepstream",
            module=deepstream,
            error_type=deepstream.DeepStreamPublicationRuntimeV3Error,
        )

    def test_savant_three_physical_windows_resume_same_path(self) -> None:
        self._run_three_window_matrix(
            system="savant",
            module=savant,
            error_type=savant.SavantPublicationRuntimeV3Error,
        )

    def test_attacker_insertion_at_publish_window_is_never_overwritten(self) -> None:
        for system, module, error_type in _WRAPPERS:
            with self.subTest(system=system), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                source, output, request = _case(root, name=system)
                attacker = b"attacker-owned\n"
                second = output / _TARGETS[1]

                def insert(observed: str) -> None:
                    if observed == (
                        f"leaf:{_TARGETS[1]}:post_fsync_pre_publish"
                    ):
                        second.write_bytes(attacker)

                with self.assertRaises(error_type):
                    module._copy_evidence(
                        source, request, _MAPPING, _fault_hook=insert
                    )
                attacker_identity = (second.stat().st_dev, second.stat().st_ino)
                self.assertEqual(second.read_bytes(), attacker)
                with self.assertRaises(error_type):
                    module._copy_evidence(source, request, _MAPPING)
                self.assertEqual(second.read_bytes(), attacker)
                self.assertEqual(
                    (second.stat().st_dev, second.stat().st_ino), attacker_identity
                )

    def test_foreign_prefix_without_parent_intent_is_rejected(self) -> None:
        for system, module, error_type in _WRAPPERS:
            with self.subTest(system=system), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                source, output, request = _case(root, name=system)
                foreign = output / _TARGETS[0]
                foreign.write_bytes(_PAYLOADS[_MAPPING[_TARGETS[0]]])
                identity = (foreign.stat().st_dev, foreign.stat().st_ino)
                with self.assertRaises(error_type):
                    module._copy_evidence(source, request, _MAPPING)
                self.assertEqual((foreign.stat().st_dev, foreign.stat().st_ino), identity)
                self.assertFalse((output / _TARGETS[1]).exists())
                self.assertFalse(_intent_path(root, output).exists())

    def test_foreign_non_evidence_baseline_is_not_silently_adopted(self) -> None:
        for system, module, error_type in _WRAPPERS:
            with self.subTest(system=system), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                source, output, request = _case(root, name=system)
                foreign = output / "attacker-foreign-baseline.txt"
                foreign.write_bytes(b"attacker-owned\n")
                identity = (foreign.stat().st_dev, foreign.stat().st_ino)
                with self.assertRaises(error_type):
                    module._copy_evidence(source, request, _MAPPING)
                self.assertEqual(foreign.read_bytes(), b"attacker-owned\n")
                self.assertEqual((foreign.stat().st_dev, foreign.stat().st_ino), identity)
                self.assertFalse(_intent_path(root, output).exists())

    def test_output_directory_rebind_to_symlink_is_rejected_without_escape(self) -> None:
        for system, module, error_type in _WRAPPERS:
            with self.subTest(system=system), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                source, output, request = _case(root, name=system)
                moved = root / f"moved-{system}"
                outside = root / f"outside-{system}"
                outside.mkdir()
                sentinel = outside / "sentinel.txt"
                sentinel.write_bytes(b"outside-owned\n")

                def rebind(observed: str) -> None:
                    if observed == "intent:post_fsync_pre_publish":
                        output.rename(moved)
                        output.symlink_to(outside, target_is_directory=True)

                with self.assertRaises(error_type):
                    module._copy_evidence(
                        source, request, _MAPPING, _fault_hook=rebind
                    )
                self.assertTrue(output.is_symlink())
                self.assertEqual(sentinel.read_bytes(), b"outside-owned\n")
                self.assertEqual(tuple(path.name for path in outside.iterdir()), ("sentinel.txt",))
                self.assertFalse(any((moved / name).exists() for name in _TARGETS))

    def test_parent_receipt_replacement_is_rejected_and_preserved(self) -> None:
        for system, module, error_type in _WRAPPERS:
            with self.subTest(system=system), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                source, output, request = _case(root, name=system)
                module._copy_evidence(source, request, _MAPPING)
                receipt = _receipt_path(root, output)
                receipt.unlink()
                attacker = b'{"attacker":"receipt"}\n'
                receipt.write_bytes(attacker)
                attacker_identity = (receipt.stat().st_dev, receipt.stat().st_ino)
                with self.assertRaises(error_type):
                    module._copy_evidence(source, request, _MAPPING)
                self.assertEqual(receipt.read_bytes(), attacker)
                self.assertEqual(
                    (receipt.stat().st_dev, receipt.stat().st_ino), attacker_identity
                )

    def test_identical_child_rerun_is_not_same_attempt_recovery(self) -> None:
        for system, module, error_type in _WRAPPERS:
            with self.subTest(system=system), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                source, output, request = _case(root, name=system)
                module._copy_evidence(source, request, _MAPPING)
                committed = tuple(
                    ((output / name).stat().st_dev, (output / name).stat().st_ino)
                    for name in _TARGETS
                )
                old_source = root / f"old-source-{system}"
                source.rename(old_source)
                source.mkdir()
                for leaf, payload in _PAYLOADS.items():
                    (source / leaf).write_bytes(payload)
                with self.assertRaises(error_type):
                    module._copy_evidence(source, request, _MAPPING)
                self.assertEqual(
                    committed,
                    tuple(
                        ((output / name).stat().st_dev, (output / name).stat().st_ino)
                        for name in _TARGETS
                    ),
                )

    def test_completed_path_is_bound_and_changed_payload_requires_new_attempt_path(self) -> None:
        for system, module, error_type in _WRAPPERS:
            with self.subTest(system=system), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                source, output, request = _case(root, name=system)
                module._copy_evidence(source, request, _MAPPING)
                committed = {
                    target: (
                        (output / target).read_bytes(),
                        (output / target).stat().st_dev,
                        (output / target).stat().st_ino,
                    )
                    for target in _TARGETS
                }
                changed = b'{"child":"changed-attempt"}\n'
                (source / _MAPPING[_TARGETS[1]]).write_bytes(changed)
                with self.assertRaises(error_type):
                    module._copy_evidence(source, request, _MAPPING)
                for target, (payload, device, inode) in committed.items():
                    self.assertEqual((output / target).read_bytes(), payload)
                    self.assertEqual(
                        ((output / target).stat().st_dev, (output / target).stat().st_ino),
                        (device, inode),
                    )

                new_output = root / f"output-{system}-attempt-2"
                new_output.mkdir()
                new_request = _request(root, new_output, system=system)
                module._copy_evidence(source, new_request, _MAPPING)
                self.assertEqual((new_output / _TARGETS[1]).read_bytes(), changed)


if __name__ == "__main__":
    unittest.main()
