from __future__ import annotations

import os
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in os.sys.path:
    os.sys.path.insert(0, str(SCRIPTS))

from publication_physical_io_v1 import (  # noqa: E402
    PhysicalRootCustodyV1,
    PublicationPhysicalIoV1Error,
)
import publication_physical_io_v1 as physical_io  # noqa: E402


class InjectedCrash(BaseException):
    pass


class PublicationPhysicalIoV1Tests(unittest.TestCase):
    _FIFO_SWAP_CHILD = r"""
import os
import sys
from pathlib import Path

source_root = Path(sys.argv[1])
physical_root = Path(sys.argv[2])
operation = sys.argv[3]
sys.path.insert(0, str(source_root / "scripts"))

import publication_physical_io_v1 as physical_io

victim = physical_root / "output" / "victim.bin"
real_open = os.open
swapped = False


def fault_open(path, flags, mode=0o777, *, dir_fd=None):
    global swapped
    if not swapped and path == "victim.bin" and dir_fd is not None:
        victim.unlink()
        os.mkfifo(victim, mode=0o600)
        swapped = True
    return real_open(path, flags, mode, dir_fd=dir_fd)


try:
    with physical_io.PhysicalRootCustodyV1.open(physical_root) as custody:
        physical_io.os.open = fault_open
        try:
            if operation == "stat":
                custody.stat_regular_identity(victim, label="FIFO-swapped stat leaf")
            elif operation == "read":
                custody.read_descriptor_identity(
                    victim,
                    label="FIFO-swapped read leaf",
                    maximum=8,
                    capture=True,
                )
            else:
                raise AssertionError(f"unknown operation: {operation}")
        finally:
            physical_io.os.open = real_open
except physical_io.PublicationPhysicalIoV1Error:
    if not swapped:
        raise AssertionError("fault injector did not replace the regular leaf")
else:
    raise AssertionError("FIFO replacement was accepted")
"""

    _FRESH_IMPORT_CHILD = r"""
import importlib
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, sys.argv[1])
for module_name in sys.argv[2].split(","):
    importlib.import_module(module_name)
physical = importlib.import_module("publication_physical_io_v1")
guardian = importlib.import_module("publication_guardian_preprocessing_contract_v1")
assert physical.PhysicalRootCustodyV1 is not None
assert guardian.DirectoryFdCustodyV1 is not None
with tempfile.TemporaryDirectory() as temporary:
    with physical.PhysicalRootCustodyV1.open(Path(temporary)) as custody:
        custody.verify()
"""

    def test_fresh_process_import_orders_do_not_cycle(self) -> None:
        orders = (
            (
                "publication_physical_io_v1",
                "publication_guardian_preprocessing_contract_v1",
            ),
            (
                "publication_guardian_preprocessing_contract_v1",
                "publication_physical_io_v1",
            ),
        )
        for order in orders:
            with self.subTest(order=order):
                completed = subprocess.run(
                    [
                        sys.executable,
                        "-B",
                        "-c",
                        self._FRESH_IMPORT_CHILD,
                        str(SCRIPTS),
                        ",".join(order),
                    ],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(
                    completed.returncode,
                    0,
                    msg=f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}",
                )

    def test_exclusive_write_lists_and_stats_one_readonly_inode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with PhysicalRootCustodyV1.open(root) as custody:
                output = custody.ensure_directory("output", label="output")
                self.assertEqual(
                    custody.list_directory_names(output, label="output"), ()
                )
                descriptor, identity = custody.write_exclusive_identity(
                    output / "receipt.json",
                    b"{}\n",
                    label="receipt",
                    mode=0o444,
                    create_parents=False,
                )
                mode, stat_identity = custody.stat_regular_identity(
                    output / "receipt.json", label="receipt"
                )
                self.assertEqual(descriptor["size_bytes"], 3)
                self.assertEqual(identity, stat_identity)
                self.assertEqual(mode, 0o444)
                self.assertEqual(
                    custody.list_directory_names(output, label="output"),
                    ("receipt.json",),
                )

    def test_atomic_no_replace_commit_and_durable_adoption_preserve_inode(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = b'{"causal":"payload"}\n'
            output = root / "output/receipt.json"
            with PhysicalRootCustodyV1.open(root) as custody:
                descriptor, identity, disposition = (
                    custody.commit_or_adopt_exact_identity(
                        output,
                        payload,
                        label="atomic receipt",
                        mode=0o444,
                    )
                )
                self.assertEqual(disposition, "published")
                self.assertEqual(output.read_bytes(), payload)
                self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o444)
                self.assertEqual(output.stat().st_nlink, 1)
                adopted, adopted_identity, adopted_disposition = (
                    custody.commit_or_adopt_exact_identity(
                        output,
                        payload,
                        label="atomic receipt",
                        mode=0o444,
                    )
                )
            self.assertEqual(adopted, descriptor)
            self.assertEqual(adopted_identity, identity)
            self.assertEqual(adopted_disposition, "adopted")
            self.assertEqual((output.stat().st_dev, output.stat().st_ino), identity)

    @unittest.skipUnless(os.name == "posix", "POSIX dirfd replacement only")
    def test_atomic_replace_retries_delayed_post_rename_visibility(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "output/checkpoint.json"
            output.parent.mkdir()
            output.write_bytes(b'{"generation":0}\n')
            replacement = b'{"generation":1}\n'
            real_stat = physical_io.os.stat
            delayed_misses = 3

            def delayed_stat(path, *args, **kwargs):
                nonlocal delayed_misses
                if (
                    path == output.name
                    and kwargs.get("dir_fd") is not None
                    and delayed_misses > 0
                ):
                    delayed_misses -= 1
                    raise FileNotFoundError(path)
                return real_stat(path, *args, **kwargs)

            with (
                PhysicalRootCustodyV1.open(root) as custody,
                mock.patch.object(physical_io.os, "stat", side_effect=delayed_stat),
                mock.patch.object(physical_io.time, "sleep") as sleep,
            ):
                descriptor = custody.replace_atomic(
                    output,
                    replacement,
                    label="delayed checkpoint",
                    mode=0o600,
                )

            self.assertEqual(delayed_misses, 0)
            self.assertEqual(sleep.call_count, 3)
            self.assertEqual(
                descriptor["sha256"],
                physical_io.hashlib.sha256(replacement).hexdigest(),
            )
            self.assertEqual(output.read_bytes(), replacement)

    @unittest.skipUnless(
        os.name == "posix"
        and physical_io._filesystem_magic_posix(ROOT)  # noqa: SLF001
        == physical_io._V9FS_MAGIC,  # noqa: SLF001
        "DrvFS replacement visibility is WSL workspace-specific",
    )
    def test_drvfs_atomic_replace_closes_staging_fd_before_verification(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            root = Path(tmp)
            output = root / "runtime/checkpoint.json"
            output.parent.mkdir()
            output.write_bytes(b'{"generation":0}\n')
            replacement = b'{"generation":1}\n'
            with PhysicalRootCustodyV1.open(root) as custody:
                descriptor = custody.replace_atomic(
                    output,
                    replacement,
                    label="DrvFS mutable checkpoint",
                    mode=0o600,
                )
            self.assertEqual(output.read_bytes(), replacement)
            self.assertEqual(
                descriptor["sha256"],
                physical_io.hashlib.sha256(replacement).hexdigest(),
            )

    @unittest.skipUnless(os.name == "posix", "atomic crash recovery is POSIX-only")
    def test_atomic_no_replace_recovers_every_physical_crash_window(self) -> None:
        steps = (
            "mid_write",
            "post_fsync_pre_publish",
            "post_publish_pre_parent_fsync",
        )
        for position, step in enumerate(steps):
            with self.subTest(step=step), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                payload = f'{{"step":{position}}}\n'.encode("ascii")
                output = root / "output/receipt.json"

                def crash(observed: str) -> None:
                    if observed == step:
                        raise InjectedCrash(observed)

                with PhysicalRootCustodyV1.open(root) as custody:
                    with self.assertRaises(InjectedCrash):
                        custody.commit_or_adopt_exact_identity(
                            output,
                            payload,
                            label=f"faulted receipt {step}",
                            mode=0o444,
                            after_publish_step=crash,
                        )
                    published_identity = (
                        (output.stat().st_dev, output.stat().st_ino)
                        if output.exists()
                        else None
                    )
                    descriptor, identity, disposition = (
                        custody.commit_or_adopt_exact_identity(
                            output,
                            payload,
                            label=f"resumed receipt {step}",
                            mode=0o444,
                        )
                    )
                    self.assertEqual(output.read_bytes(), payload)
                    self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o444)
                    self.assertEqual(output.stat().st_nlink, 1)
                    self.assertEqual(
                        descriptor["sha256"],
                        physical_io.hashlib.sha256(payload).hexdigest(),
                    )
                    if published_identity is None:
                        self.assertEqual(disposition, "published")
                    else:
                        self.assertEqual(disposition, "adopted")
                        self.assertEqual(identity, published_identity)

    @unittest.skipUnless(os.name == "posix", "empty atomic capture is POSIX-only")
    def test_empty_capture_opt_in_recovers_every_window_and_rejects_rebind(self) -> None:
        steps = (
            "mid_write",
            "post_fsync_pre_publish",
            "post_publish_pre_parent_fsync",
        )
        empty_sha = physical_io.hashlib.sha256(b"").hexdigest()
        for step in steps:
            with self.subTest(step=step), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                output = root / "captures/stderr.bin"

                def crash(observed: str) -> None:
                    if observed == step:
                        raise InjectedCrash(observed)

                with PhysicalRootCustodyV1.open(root) as custody:
                    with self.assertRaises(InjectedCrash):
                        custody.commit_or_adopt_exact_identity(
                            output,
                            b"",
                            label=f"empty capture {step}",
                            mode=0o444,
                            allow_empty=True,
                            after_publish_step=crash,
                        )
                    published_identity = (
                        (output.stat().st_dev, output.stat().st_ino)
                        if output.exists()
                        else None
                    )
                    descriptor, identity, disposition = (
                        custody.commit_or_adopt_exact_identity(
                            output,
                            b"",
                            label=f"resumed empty capture {step}",
                            mode=0o444,
                            allow_empty=True,
                        )
                    )
                    self.assertEqual(output.read_bytes(), b"")
                    self.assertEqual(descriptor["size_bytes"], 0)
                    self.assertEqual(descriptor["sha256"], empty_sha)
                    self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o444)
                    self.assertEqual(output.stat().st_nlink, 1)
                    if published_identity is None:
                        self.assertEqual(disposition, "published")
                    else:
                        self.assertEqual(disposition, "adopted")
                        self.assertEqual(identity, published_identity)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "captures/stdout.bin"
            with PhysicalRootCustodyV1.open(root) as custody:
                with self.assertRaises(PublicationPhysicalIoV1Error):
                    custody.commit_or_adopt_exact_identity(
                        output,
                        b"",
                        label="empty capture without opt-in",
                    )
                custody.commit_or_adopt_exact_identity(
                    output,
                    b"",
                    label="empty capture fixture",
                    mode=0o444,
                    allow_empty=True,
                )
                original = output.stat()
                displaced = output.with_suffix(".owned")
                output.rename(displaced)
                output.write_bytes(b"attacker-nonempty")
                output.chmod(0o444)
                with self.assertRaises(PublicationPhysicalIoV1Error):
                    custody.commit_or_adopt_exact_identity(
                        output,
                        b"",
                        label="rebound empty capture",
                        mode=0o444,
                        allow_empty=True,
                    )
            self.assertEqual(output.read_bytes(), b"attacker-nonempty")
            self.assertEqual(
                (displaced.stat().st_dev, displaced.stat().st_ino),
                (original.st_dev, original.st_ino),
            )

    @unittest.skipUnless(
        os.name == "posix"
        and physical_io._filesystem_magic_posix(ROOT)  # noqa: SLF001
        == physical_io._V9FS_MAGIC,  # noqa: SLF001
        "DrvFS hard-link fallback is WSL workspace-specific",
    )
    def test_drvfs_unsupported_rename_recovers_two_link_publish(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            root = Path(tmp)
            output = root / "output/receipt.json"
            observed: dict[str, object] = {}

            def inspect(step: str) -> None:
                if step != "post_publish_pre_parent_fsync":
                    return
                observed["links"] = output.stat().st_nlink
                transaction_root = root / physical_io._ATOMIC_STAGING_ROOT
                observed["stages"] = list(
                    transaction_root.glob("txn-*/payload.stage")
                )
                raise InjectedCrash(step)

            with PhysicalRootCustodyV1.open(root) as custody:
                with self.assertRaises(InjectedCrash):
                    custody.commit_or_adopt_exact_identity(
                        output,
                        b"drvfs\n",
                        label="DrvFS receipt",
                        after_publish_step=inspect,
                    )
                self.assertEqual(observed["links"], 2)
                self.assertEqual(len(observed["stages"]), 1)
                _descriptor, identity, disposition = (
                    custody.commit_or_adopt_exact_identity(
                        output,
                        b"drvfs\n",
                        label="resumed DrvFS receipt",
                    )
                )
            self.assertEqual(disposition, "adopted")
            self.assertEqual(output.stat().st_nlink, 1)
            self.assertEqual((output.stat().st_dev, output.stat().st_ino), identity)

    @unittest.skipUnless(os.name == "posix", "flock serialization is POSIX-only")
    def test_concurrent_exact_publishers_lock_before_staging_epoch_pin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "output/receipt.json"
            payload = b"concurrent exact receipt\n"
            callers_ready = threading.Barrier(2)
            first_inside_lock = threading.Event()
            release_first = threading.Event()
            hook_owner: list[int] = []
            hook_guard = threading.Lock()

            def publish() -> tuple[dict[str, object], tuple[int, int], str]:
                with PhysicalRootCustodyV1.open(root) as custody:
                    callers_ready.wait(timeout=10)

                    def hold_first(step: str) -> None:
                        if step != "mid_write":
                            return
                        with hook_guard:
                            if not hook_owner:
                                hook_owner.append(threading.get_ident())
                                first_inside_lock.set()
                                owns_hold = True
                            else:
                                owns_hold = False
                        if owns_hold and not release_first.wait(timeout=10):
                            raise AssertionError("concurrent publisher was not released")

                    return custody.commit_or_adopt_exact_identity(
                        output,
                        payload,
                        label="concurrent exact physical receipt",
                        after_publish_step=hold_first,
                    )

            with ThreadPoolExecutor(max_workers=2) as executor:
                first = executor.submit(publish)
                second = executor.submit(publish)
                self.assertTrue(first_inside_lock.wait(timeout=10))
                time.sleep(0.05)
                self.assertFalse(first.done() and second.done())
                release_first.set()
                results = [first.result(timeout=10), second.result(timeout=10)]

            self.assertEqual({item[2] for item in results}, {"published", "adopted"})
            self.assertEqual(results[0][0], results[1][0])
            self.assertEqual(results[0][1], results[1][1])
            self.assertEqual(output.read_bytes(), payload)
            self.assertEqual(
                set((root / physical_io._ATOMIC_STAGING_ROOT).iterdir()),
                {root / physical_io._ATOMIC_STAGING_ROOT / physical_io._ATOMIC_STAGING_LOCK},
            )

    def test_atomic_resume_rejects_partial_final_and_foreign_stage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "output/receipt.json"
            output.parent.mkdir()
            output.write_bytes(b"partial")
            output.chmod(0o600)
            before = output.stat()
            with PhysicalRootCustodyV1.open(root) as custody:
                with self.assertRaises(PublicationPhysicalIoV1Error):
                    custody.commit_or_adopt_exact_identity(
                        output,
                        b"trusted-complete\n",
                        label="partial attacker final",
                    )
            after = output.stat()
            self.assertEqual((before.st_dev, before.st_ino), (after.st_dev, after.st_ino))
            self.assertEqual(output.read_bytes(), b"partial")

        if os.name == "posix":
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                payload = b"trusted-complete\n"
                relative = "output/receipt.json"
                transaction_key = PhysicalRootCustodyV1._atomic_transaction_key(
                    relative, payload, 0o444
                )
                transaction = (
                    root
                    / physical_io._ATOMIC_STAGING_ROOT
                    / f"txn-{transaction_key}"
                )
                transaction.mkdir(parents=True, mode=0o700)
                foreign = root / "foreign"
                foreign.write_bytes(b"foreign\n")
                (transaction / physical_io._ATOMIC_STAGING_LEAF).symlink_to(
                    foreign
                )
                with PhysicalRootCustodyV1.open(root) as custody:
                    with self.assertRaisesRegex(
                        PublicationPhysicalIoV1Error, "foreign"
                    ):
                        custody.commit_or_adopt_exact_identity(
                            relative,
                            payload,
                            label="foreign transaction stage",
                        )
                self.assertEqual(foreign.read_bytes(), b"foreign\n")

    @unittest.skipUnless(os.name == "posix", "transaction provenance is POSIX-only")
    def test_atomic_resume_never_deletes_unproven_regular_or_hardlink_stage(self) -> None:
        payload = b"trusted-complete\n"
        relative = "output/receipt.json"

        for with_final in (False, True):
            for hardlinked in (False, True):
                with self.subTest(with_final=with_final, hardlinked=hardlinked):
                    with tempfile.TemporaryDirectory() as tmp:
                        root = Path(tmp)
                        transaction_key = PhysicalRootCustodyV1._atomic_transaction_key(
                            relative, payload, 0o444
                        )
                        transaction = (
                            root
                            / physical_io._ATOMIC_STAGING_ROOT
                            / f"txn-{transaction_key}"
                        )
                        transaction.mkdir(parents=True, mode=0o700)
                        transaction.parent.chmod(0o700)
                        transaction.chmod(0o700)
                        stage = transaction / physical_io._ATOMIC_STAGING_LEAF
                        foreign = root / "foreign"
                        foreign.write_bytes(b"foreign-stage\n")
                        if hardlinked:
                            os.link(foreign, stage)
                        else:
                            stage.write_bytes(b"foreign-stage\n")
                        before = stage.stat()
                        output = root / relative
                        if with_final:
                            output.parent.mkdir(parents=True)
                            output.write_bytes(payload)
                            output.chmod(0o444)

                        with PhysicalRootCustodyV1.open(root) as custody:
                            with self.assertRaisesRegex(
                                PublicationPhysicalIoV1Error,
                                "provenance|intent|foreign",
                            ):
                                custody.commit_or_adopt_exact_identity(
                                    relative,
                                    payload,
                                    label="unproven regular transaction stage",
                                )

                        after = stage.stat()
                        self.assertEqual(
                            (before.st_dev, before.st_ino),
                            (after.st_dev, after.st_ino),
                        )
                        self.assertEqual(stage.read_bytes(), b"foreign-stage\n")
                        if hardlinked:
                            self.assertEqual(foreign.read_bytes(), b"foreign-stage\n")

    @unittest.skipUnless(os.name == "posix", "transaction ABA test is POSIX-only")
    def test_atomic_mid_write_resume_rejects_stage_aba_without_deleting_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "output/receipt.json"
            payload = b"trusted-complete\n"

            def crash(step: str) -> None:
                if step == "mid_write":
                    raise InjectedCrash(step)

            with PhysicalRootCustodyV1.open(root) as custody:
                with self.assertRaises(InjectedCrash):
                    custody.commit_or_adopt_exact_identity(
                        output,
                        payload,
                        label="mid-write provenance fixture",
                        after_publish_step=crash,
                    )

            transaction_key = PhysicalRootCustodyV1._atomic_transaction_key(
                "output/receipt.json", payload, 0o444
            )
            transaction = (
                root
                / physical_io._ATOMIC_STAGING_ROOT
                / f"txn-{transaction_key}"
            )
            self.assertTrue(
                (transaction / physical_io._ATOMIC_TRANSACTION_INTENT).is_file()
            )
            self.assertTrue((transaction / physical_io._ATOMIC_STAGE_INTENT).is_file())
            stage = transaction / physical_io._ATOMIC_STAGING_LEAF
            displaced = root / "owned-displaced.stage"
            stage.rename(displaced)
            stage.write_bytes(b"foreign-replacement\n")
            before = stage.stat()

            with PhysicalRootCustodyV1.open(root) as custody:
                with self.assertRaisesRegex(
                    PublicationPhysicalIoV1Error, "identity|provenance|intent"
                ):
                    custody.commit_or_adopt_exact_identity(
                        output,
                        payload,
                        label="mid-write ABA resume",
                    )

            after = stage.stat()
            self.assertEqual(
                (before.st_dev, before.st_ino), (after.st_dev, after.st_ino)
            )
            self.assertEqual(stage.read_bytes(), b"foreign-replacement\n")
            self.assertEqual(displaced.read_bytes(), payload[: len(payload) // 2])

    @unittest.skipUnless(os.name == "posix", "fsync fault test is POSIX-only")
    def test_exact_adoption_requires_file_and_parent_durability_barriers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "output/receipt.json"
            output.parent.mkdir()
            output.write_bytes(b"complete\n")
            output.chmod(0o444)
            real_fsync = os.fsync
            calls = 0

            def crash_first_fsync(descriptor: int) -> None:
                nonlocal calls
                calls += 1
                if calls == 1:
                    raise InjectedCrash("pre-fsync")
                real_fsync(descriptor)

            with PhysicalRootCustodyV1.open(root) as custody:
                with mock.patch.object(
                    physical_io.os, "fsync", side_effect=crash_first_fsync
                ):
                    with self.assertRaises(InjectedCrash):
                        custody.adopt_exact_durable_identity(
                            output,
                            b"complete\n",
                            label="not-yet-durable receipt",
                        )
                descriptor, identity = custody.adopt_exact_durable_identity(
                    output,
                    b"complete\n",
                    label="durable receipt",
                )
            self.assertEqual(descriptor["size_bytes"], len(b"complete\n"))
            self.assertEqual((output.stat().st_dev, output.stat().st_ino), identity)

    def test_same_bytes_hardlink_is_not_one_physical_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "output"
            output.mkdir()
            source = output / "receipt.json"
            source.write_bytes(b"{}\n")
            alias = output / "alias.json"
            try:
                os.link(source, alias)
            except OSError:
                self.skipTest("hard links are unavailable")
            with PhysicalRootCustodyV1.open(root) as custody:
                with self.assertRaises(PublicationPhysicalIoV1Error):
                    custody.read_descriptor(
                        source, label="hardlinked receipt", maximum=3, capture=True
                    )

    def test_no_overwrite_preserves_existing_inode_and_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "output"
            output.mkdir()
            target = output / "receipt.json"
            target.write_bytes(b"attacker\n")
            before = target.lstat()
            with PhysicalRootCustodyV1.open(root) as custody:
                with self.assertRaises(PublicationPhysicalIoV1Error):
                    custody.write_exclusive(
                        target,
                        b"trusted\n",
                        label="receipt",
                        mode=0o444,
                        create_parents=False,
                    )
            after = target.lstat()
            self.assertEqual(
                (before.st_dev, before.st_ino), (after.st_dev, after.st_ino)
            )
            self.assertEqual(target.read_bytes(), b"attacker\n")

    def test_owned_directory_journal_removes_only_exact_empty_identities(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with PhysicalRootCustodyV1.open(root) as custody:
                output, created = custody.ensure_directory_owned(
                    "output/nested", label="owned nested output"
                )
                self.assertEqual(
                    [path for path, _identity in created],
                    ["output", "output/nested"],
                )
                for path, identity in created:
                    mode, observed_identity = custody.stat_directory_identity(
                        path, label=f"owned directory {path}"
                    )
                    self.assertEqual(mode, 0o700)
                    self.assertEqual(observed_identity, identity)

                leaf = output / "keep.txt"
                leaf.write_bytes(b"keep\n")
                with self.assertRaisesRegex(
                    PublicationPhysicalIoV1Error, "not empty"
                ):
                    custody.rmdir_owned_identity(
                        "output/nested",
                        created[-1][1],
                        label="nonempty owned nested output",
                    )
                self.assertEqual(leaf.read_bytes(), b"keep\n")
                leaf.unlink()
                for path, identity in reversed(created):
                    custody.rmdir_owned_identity(
                        path, identity, label=f"rollback owned directory {path}"
                    )
            self.assertFalse((root / "output").exists())

    @unittest.skipUnless(os.name == "posix", "dirfd rebind test is POSIX-only")
    def test_parent_rebind_to_exact_copy_fails_closed_and_preserves_canary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "output"
            output.mkdir()
            trusted = output / "receipt.json"
            trusted.write_bytes(b"{}\n")
            displaced = root / "displaced"
            attacker = root / "attacker"
            attacker.mkdir()
            (attacker / "receipt.json").write_bytes(b"{}\n")
            canary = attacker / "canary.txt"
            canary.write_text("keep\n", encoding="ascii")

            with PhysicalRootCustodyV1.open(root) as custody:
                custody.read_descriptor(
                    trusted, label="trusted receipt", maximum=3, capture=True
                )
                output.rename(displaced)
                attacker.rename(output)
                with self.assertRaises(PublicationPhysicalIoV1Error):
                    custody.list_directory_names(output, label="rebound output")

            self.assertEqual((output / "canary.txt").read_text(encoding="ascii"), "keep\n")
            self.assertTrue(stat.S_ISREG((displaced / "receipt.json").lstat().st_mode))

    @unittest.skipUnless(os.name == "posix", "FIFO fault test is POSIX-only")
    def test_regular_leaf_to_fifo_swap_fails_closed_without_blocking(self) -> None:
        for operation in ("stat", "read"):
            with (
                self.subTest(operation=operation),
                tempfile.TemporaryDirectory() as tmp,
            ):
                root = Path(tmp)
                output = root / "output"
                output.mkdir()
                (output / "victim.bin").write_bytes(b"trusted\n")
                started = time.monotonic()
                try:
                    completed = subprocess.run(
                        [
                            sys.executable,
                            "-c",
                            self._FIFO_SWAP_CHILD,
                            str(ROOT),
                            str(root),
                            operation,
                        ],
                        capture_output=True,
                        text=True,
                        timeout=2.0,
                        check=False,
                    )
                except subprocess.TimeoutExpired as error:
                    self.fail(
                        f"{operation} blocked after regular-to-FIFO swap: {error}"
                    )
                elapsed = time.monotonic() - started
                self.assertLess(elapsed, 1.5)
                self.assertEqual(
                    completed.returncode,
                    0,
                    msg=(
                        f"stdout:\n{completed.stdout}\n"
                        f"stderr:\n{completed.stderr}"
                    ),
                )


if __name__ == "__main__":
    unittest.main()
