from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from production_parent_artifact_pin_store_v1 import (  # noqa: E402
    PIN_DIRECTORY_NAME,
    ProductionParentArtifactPinStoreV1,
    ProductionParentArtifactPinStoreV1Error,
)


class SyntheticParentPinCrash(BaseException):
    pass


class ProductionParentArtifactPinStoreV1Tests(unittest.TestCase):
    def make_store(
        self,
        root: Path,
        *,
        after_physical_commit_step=None,
    ) -> ProductionParentArtifactPinStoreV1:
        output = root / "run/pairs/0000-pair/attempt-0001/arms/01-arm"
        output.mkdir(parents=True, exist_ok=True)
        return ProductionParentArtifactPinStoreV1(
            project_root=root,
            output_dir=output,
            arm_contract_file_sha256="a" * 64,
            execution_binding={
                "schema_version": 1,
                "artifact_kind": "vast_full_publication_arm_execution_binding",
                "arm_id": "arm",
            },
            after_physical_commit_step=after_physical_commit_step,
        )

    @staticmethod
    def pin(state: str) -> dict[str, object]:
        names = {
            "result": "backend_publication_launcher_result_v3.json",
            "receipt_intent": "backend_publication_output_receipt_v3.json",
            "committed": "backend_publication_output_receipt_v3.json",
        }
        return {
            "state": state,
            "path": names[state],
            "size_bytes": 101 if state == "result" else 202,
            "sha256": ("b" if state == "result" else "c") * 64,
        }

    def test_result_then_committed_round_trip_is_idempotent_and_external(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            store = self.make_store(root)
            result = self.pin("result")
            intent = self.pin("receipt_intent")
            committed = self.pin("committed")
            store(copy.deepcopy(result))
            store(copy.deepcopy(result))
            self.assertEqual(store.load_expected_pin(), result)
            store(copy.deepcopy(intent))
            store(copy.deepcopy(intent))
            self.assertEqual(store.load_expected_pin(), intent)
            store(copy.deepcopy(committed))
            store(copy.deepcopy(committed))
            self.assertEqual(store.load_expected_pin(), committed)
            self.assertFalse(store.pin_root.is_relative_to(store.output_dir))
            self.assertEqual(
                {path.name for path in store.pin_root.iterdir()},
                {
                    "result.pin.v1.json",
                    "receipt-intent.pin.v1.json",
                    "committed.pin.v1.json",
                },
            )
            store.close()

    def test_tamper_collision_and_unexpected_namespace_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            store = self.make_store(root)
            result = self.pin("result")
            store(copy.deepcopy(result))
            path = store.pin_root / "result.pin.v1.json"
            path.chmod(0o600)
            value = json.loads(path.read_text(encoding="ascii"))
            value["artifact_pin"]["sha256"] = "f" * 64
            path.write_text(json.dumps(value), encoding="ascii")
            with self.assertRaisesRegex(
                ProductionParentArtifactPinStoreV1Error,
                "identity|custody|mutated|unsafe|unreadable",
            ):
                store.load_expected_pin()
            store._close_unchecked()  # noqa: SLF001 - fault-injection cleanup

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            store = self.make_store(root)
            store(copy.deepcopy(self.pin("result")))
            drifted = self.pin("result")
            drifted["sha256"] = "d" * 64
            with self.assertRaisesRegex(
                ProductionParentArtifactPinStoreV1Error, "collision"
            ):
                store(copy.deepcopy(drifted))
            store.close()

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            store = self.make_store(root)
            store.close()
            (store.pin_root / "unexpected").write_text("x", encoding="ascii")
            store = self.make_store(root)
            with self.assertRaisesRegex(
                ProductionParentArtifactPinStoreV1Error, "unexpected"
            ):
                store.load_expected_pin()
            store._close_unchecked()  # noqa: SLF001 - invalid namespace cleanup

    def test_committed_without_result_and_wrong_descriptor_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            store = self.make_store(root)
            with self.assertRaisesRegex(
                ProductionParentArtifactPinStoreV1Error, "predecessor|result"
            ):
                store(copy.deepcopy(self.pin("committed")))
            store.close()

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            store = self.make_store(root)
            wrong = self.pin("result")
            wrong["path"] = "child-self-declared.json"
            with self.assertRaisesRegex(
                ProductionParentArtifactPinStoreV1Error, "descriptor"
            ):
                store(copy.deepcopy(wrong))
            store.close()

    def test_parent_pin_recovers_every_atomic_physical_window(self) -> None:
        steps = (
            "mid_write",
            "post_fsync_pre_publish",
            "post_publish_pre_parent_fsync",
        )
        for step in steps:
            with self.subTest(step=step), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                faulted: list[Path] = []

                def crash(observed_step: str, path: Path) -> None:
                    if observed_step == step and not faulted:
                        faulted.append(path)
                        raise SyntheticParentPinCrash()

                store = self.make_store(
                    root, after_physical_commit_step=crash
                )
                result = self.pin("result")
                with self.assertRaises(SyntheticParentPinCrash):
                    store(copy.deepcopy(result))
                self.assertEqual(len(faulted), 1)
                pin_path = faulted[0]
                published_identity = (
                    (pin_path.stat().st_dev, pin_path.stat().st_ino)
                    if pin_path.exists()
                    else None
                )
                store._close_unchecked()  # noqa: SLF001 - simulated hard crash

                resumed = self.make_store(root)
                resumed(copy.deepcopy(result))
                self.assertEqual(resumed.load_expected_pin(), result)
                self.assertEqual(pin_path.stat().st_mode & 0o777, 0o400)
                self.assertEqual(pin_path.stat().st_nlink, 1)
                if published_identity is not None:
                    self.assertEqual(
                        (pin_path.stat().st_dev, pin_path.stat().st_ino),
                        published_identity,
                    )
                resumed.close()

    def test_foreign_partial_pin_is_rejected_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            store = self.make_store(root)
            path = store.pin_root / "result.pin.v1.json"
            payload = b"attacker-partial\n"
            path.write_bytes(payload)
            with self.assertRaisesRegex(
                ProductionParentArtifactPinStoreV1Error,
                "collision|identity|unsafe|unreadable|custody|directory",
            ):
                store(copy.deepcopy(self.pin("result")))
            self.assertEqual(path.read_bytes(), payload)
            store._close_unchecked()  # noqa: SLF001 - adversarial cleanup

    @unittest.skipUnless(os.name == "posix", "POSIX no-follow custody regression")
    def test_intermediate_symlink_cannot_route_parent_pins_into_child_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            output = root / "run/pairs/0000-pair/attempt-0001/arms/01-arm"
            output.mkdir(parents=True)
            controlled = output / "child-controlled-pins"
            controlled.mkdir()
            (output.parent / PIN_DIRECTORY_NAME).symlink_to(
                controlled,
                target_is_directory=True,
            )
            with self.assertRaisesRegex(
                ProductionParentArtifactPinStoreV1Error,
                "physical|custody|directory|link",
            ):
                self.make_store(root)

    @unittest.skipUnless(os.name == "posix", "POSIX dirfd custody regression")
    def test_pin_root_permanent_rebind_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            store = self.make_store(root)
            store(copy.deepcopy(self.pin("result")))
            held = store.pin_root.with_name(store.pin_root.name + ".held")
            store.pin_root.rename(held)
            store.pin_root.mkdir()
            with self.assertRaisesRegex(
                ProductionParentArtifactPinStoreV1Error,
                "custody|mutated|changed|rebound",
            ):
                store.load_expected_pin()
            store._close_unchecked()  # noqa: SLF001 - adversarial rebind cleanup

    @unittest.skipUnless(os.name == "posix", "Linux mutation-watch regression")
    def test_pin_root_aba_rebind_restored_before_read_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            store = self.make_store(root)
            store(copy.deepcopy(self.pin("result")))
            held = store.pin_root.with_name(store.pin_root.name + ".held")
            store.pin_root.rename(held)
            store.pin_root.mkdir()
            store.pin_root.rmdir()
            held.rename(store.pin_root)
            with self.assertRaisesRegex(
                ProductionParentArtifactPinStoreV1Error,
                "custody|mutated|changed",
            ):
                store.load_expected_pin()
            store._close_unchecked()  # noqa: SLF001 - adversarial ABA cleanup


if __name__ == "__main__":
    unittest.main()
