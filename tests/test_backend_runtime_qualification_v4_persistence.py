from __future__ import annotations

import hashlib
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from backend_runtime_qualification_v4_persistence import (  # noqa: E402
    BINDING_INDEX_FILENAME,
    RECEIPT_FILENAME_TEMPLATE,
    SYSTEMS,
    BackendRuntimeQualificationV4PersistenceError,
    load_backend_runtime_qualification_v4_binding,
    promote_backend_runtime_qualification_v4,
)
import backend_runtime_qualification_v4_persistence as target  # noqa: E402


class InjectedCrash(BaseException):
    pass


class BackendRuntimeQualificationV4PersistenceContractTests(unittest.TestCase):
    def test_public_surface_is_explicit_and_four_system_closed(self) -> None:
        self.assertEqual(
            SYSTEMS,
            ("deepstream", "savant", "openvino_gva", "gstreamer_custom"),
        )
        self.assertEqual(
            BINDING_INDEX_FILENAME,
            "checkpoint_backend_runtime_qualification_v4_binding_index.json",
        )
        self.assertEqual(
            {
                RECEIPT_FILENAME_TEMPLATE.format(system=system)
                for system in SYSTEMS
            },
            {
                f"checkpoint_{system}_backend_runtime_qualification_v4_receipt.json"
                for system in SYSTEMS
            },
        )
        self.assertTrue(callable(promote_backend_runtime_qualification_v4))
        self.assertTrue(callable(load_backend_runtime_qualification_v4_binding))
        self.assertTrue(issubclass(
            BackendRuntimeQualificationV4PersistenceError, RuntimeError,
        ))

    def test_physical_reader_rehashes_and_rejects_links_aliases_and_tamper(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            source = root / "source.bin"
            payload = b"authenticated-q4-evidence"
            source.write_bytes(payload)
            descriptor = {
                "path": "source.bin",
                "size_bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
            registry = target._PhysicalRegistry(root)
            self.assertEqual(registry.read(descriptor, "source"), payload)
            self.assertEqual(registry.read(descriptor, "source-repeat"), payload)

            source.write_bytes(b"x" * len(payload))
            with self.assertRaisesRegex(
                BackendRuntimeQualificationV4PersistenceError,
                "size/SHA|changed",
            ):
                registry.read(descriptor, "source-tampered")

            source.write_bytes(payload)
            link = root / "link.bin"
            try:
                link.symlink_to(source)
            except OSError:
                pass
            else:
                linked = {**descriptor, "path": "link.bin"}
                with self.assertRaisesRegex(
                    BackendRuntimeQualificationV4PersistenceError,
                    "link/reparse",
                ):
                    target._PhysicalRegistry(root).read(linked, "linked")

            hardlink = root / "hardlink.bin"
            os.link(source, hardlink)
            with self.assertRaisesRegex(
                BackendRuntimeQualificationV4PersistenceError,
                "non-hardlinked",
            ):
                target._PhysicalRegistry(root).read(
                    {**descriptor, "path": "hardlink.bin"}, "hardlinked",
                )

    def test_atomic_output_is_idempotent_but_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            output = root / "receipt.json"
            value = {"schema_version": 4, "value": "accepted"}
            target._atomic_immutable(root, output, value)
            expected = output.read_bytes()
            target._atomic_immutable(root, output, value)
            self.assertEqual(output.read_bytes(), expected)
            self.assertEqual(output.stat().st_nlink, 1)
            with self.assertRaisesRegex(
                BackendRuntimeQualificationV4PersistenceError, "collision",
            ):
                target._atomic_immutable(
                    root,
                    output,
                    {"schema_version": 4, "value": "drifted"},
                )
            self.assertEqual(output.read_bytes(), expected)

    @unittest.skipUnless(os.name == "posix", "symlink containment is POSIX-only")
    def test_output_directory_rejects_intermediate_symlink_before_write(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            attacker = root / "attacker"
            attacker.mkdir()
            redirect = root / "redirect"
            redirect.symlink_to(attacker, target_is_directory=True)
            with self.assertRaisesRegex(
                BackendRuntimeQualificationV4PersistenceError,
                "outside project_root|link",
            ):
                target._output_directory(root, redirect / "created-outside")
            self.assertFalse((attacker / "created-outside").exists())

    @unittest.skipUnless(os.name == "posix", "atomic crash recovery is POSIX-only")
    def test_atomic_output_recovers_every_physical_publish_window(self) -> None:
        steps = (
            "mid_write",
            "post_fsync_pre_publish",
            "post_publish_pre_parent_fsync",
        )
        for position, step in enumerate(steps):
            with self.subTest(step=step), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                output = root / "accepted" / "receipt.json"
                value = {"schema_version": 4, "position": position}

                def crash(observed: str) -> None:
                    if observed == step:
                        raise InjectedCrash(observed)

                with self.assertRaises(InjectedCrash):
                    target._atomic_immutable(
                        root, output, value, after_publish_step=crash,
                    )
                published_identity = (
                    (output.stat().st_dev, output.stat().st_ino)
                    if output.exists()
                    else None
                )
                target._atomic_immutable(root, output, value)
                self.assertEqual(
                    output.read_bytes(), target._canonical_bytes(value) + b"\n",
                )
                self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o444)
                self.assertEqual(output.stat().st_nlink, 1)
                if published_identity is not None:
                    self.assertEqual(
                        (output.stat().st_dev, output.stat().st_ino),
                        published_identity,
                    )


if __name__ == "__main__":
    unittest.main()
