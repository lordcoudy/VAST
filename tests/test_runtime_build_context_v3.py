from __future__ import annotations

import hashlib
import importlib.util
import os
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MATERIALIZER = ROOT / "scripts" / "materialize_runtime_build_context_v3.py"


def _module():
    spec = importlib.util.spec_from_file_location(
        "materialize_runtime_build_context_v3", MATERIALIZER,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load runtime build-context materializer")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _aggregate(root: Path, relative_paths: tuple[str, ...]) -> str:
    rows = bytearray()
    for relative in sorted(relative_paths):
        digest = hashlib.sha256((root / relative).read_bytes()).hexdigest()
        rows.extend(f"{digest}  {relative}\n".encode("ascii"))
    return hashlib.sha256(rows).hexdigest()


class RuntimeBuildContextCopyExtentTests(unittest.TestCase):
    def _refused_stream(self, sealed: bytes, chunks: tuple[bytes, ...], prefix: bytes) -> None:
        module = _module()
        # Keep the actual source/destination witnesses, including failed REDs.
        temporary = Path(tempfile.mkdtemp(prefix="buildextent-"))
        source = temporary / "source"
        destination = temporary / "destination"
        source.write_bytes(sealed)
        expected = source.stat()
        write = os.write

        def short_write(descriptor, data):
            return write(descriptor, data[:1])

        with mock.patch.object(module.os, "read", side_effect=(*chunks, b"")) as reads, \
                mock.patch.object(module.os, "write", side_effect=short_write) as writes, \
                mock.patch.object(module.os, "fsync") as fsync:
            with self.assertRaisesRegex(ValueError, "size drifted"):
                module._copy_held_source(
                    source, destination, expected=expected, source_date_epoch=0,
                )
            self.assertEqual(destination.read_bytes(), prefix)
            self.assertEqual(writes.call_count, len(prefix))
            self.assertEqual(reads.call_count, len(chunks))
            fsync.assert_not_called()

    def test_growth_is_refused_before_any_destination_write(self) -> None:
        for sealed, chunk in ((b"", b"x"), (b"abcd", b"abcde")):
            with self.subTest(sealed_size=len(sealed)):
                self._refused_stream(sealed, (chunk,), b"")

    def test_growth_after_prefix_cannot_cross_sealed_extent(self) -> None:
        for chunks, prefix in (((b"ab", b"cde"), b"ab"), ((b"abcd", b"x"), b"abcd")):
            with self.subTest(prefix=prefix):
                self._refused_stream(b"abcd", chunks, prefix)

    def test_truncated_stream_is_refused_before_fsync(self) -> None:
        self._refused_stream(b"abcd", (b"abc", b""), b"abc")

    def test_exact_empty_and_chunked_streams_preserve_bytes_hash_and_short_writes(self) -> None:
        for sealed, chunks in ((b"", (b"",)), (b"abcd", (b"ab", b"cd", b""))):
            with self.subTest(sealed_size=len(sealed)):
                module = _module()
                temporary = Path(tempfile.mkdtemp(prefix="buildextent-"))
                source = temporary / "source"
                destination = temporary / "destination"
                source.write_bytes(sealed)
                write = os.write

                def short_write(descriptor, data):
                    return write(descriptor, data[:1])

                with mock.patch.object(module.os, "read", side_effect=chunks), \
                        mock.patch.object(module.os, "write", side_effect=short_write):
                    digest = module._copy_held_source(
                        source, destination, expected=source.stat(), source_date_epoch=0,
                    )
                self.assertEqual(destination.read_bytes(), sealed)
                self.assertEqual(digest, hashlib.sha256(sealed).hexdigest())
                self.assertEqual(int(destination.stat().st_mtime), 0)


class RuntimeBuildContextV3Tests(unittest.TestCase):
    def _fixture(self, parent: Path) -> tuple[Path, tuple[Path, Path], tuple[str, ...]]:
        project = parent / "project"
        (project / "manifests").mkdir(parents=True)
        (project / "runtime").mkdir()
        (project / "bundle").mkdir()
        (project / "runtime" / "entry.py").write_text(
            "value = 'runtime'\n", encoding="utf-8",
        )
        (project / "bundle" / "requirements.lock").write_text(
            "dependency==1 --hash=sha256:" + "a" * 64 + "\n",
            encoding="ascii",
        )
        (project / "bundle" / "dependency.whl").write_bytes(b"wheel-bytes")
        source_manifest = project / "manifests" / "runtime.txt"
        dependency_manifest = project / "manifests" / "dependencies.txt"
        source_manifest.write_bytes(
            b"manifests/dependencies.txt\n"
            b"manifests/runtime.txt\n"
            b"runtime/entry.py\n"
        )
        dependency_manifest.write_bytes(
            b"bundle/dependency.whl\n"
            b"bundle/requirements.lock\n"
        )
        paths = (
            "bundle/dependency.whl",
            "bundle/requirements.lock",
            "manifests/dependencies.txt",
            "manifests/runtime.txt",
            "runtime/entry.py",
        )
        return project, (source_manifest, dependency_manifest), paths

    def test_materializes_only_manifest_union_with_frozen_metadata(self) -> None:
        module = _module()
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            project, manifests, expected = self._fixture(parent)
            output = parent / "context"
            output.mkdir()
            result = module.materialize_runtime_build_context(
                project_root=project,
                output_dir=output,
                manifest_paths=manifests,
                source_date_epoch=1_722_470_400,
            )
            observed = tuple(sorted(
                path.relative_to(output).as_posix()
                for path in output.rglob("*") if path.is_file()
            ))
            self.assertEqual(observed, expected)
            self.assertEqual(result["relative_paths"], expected)
            self.assertEqual(result["aggregate_sha256"], _aggregate(output, expected))
            for relative in expected:
                path = output / relative
                self.assertEqual(path.read_bytes(), (project / relative).read_bytes())
                self.assertEqual(int(path.stat().st_mtime), 1_722_470_400)
                if os.name == "posix":
                    self.assertEqual(path.stat().st_mode & 0o777, 0o444)

    def test_rejects_nonempty_or_project_internal_output(self) -> None:
        module = _module()
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            project, manifests, _ = self._fixture(parent)
            internal = project / "context"
            internal.mkdir()
            with self.assertRaisesRegex(ValueError, "outside project root"):
                module.materialize_runtime_build_context(
                    project_root=project,
                    output_dir=internal,
                    manifest_paths=manifests,
                    source_date_epoch=0,
                )
            output = parent / "context"
            output.mkdir()
            (output / "foreign").write_text("do not overwrite", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "must be empty"):
                module.materialize_runtime_build_context(
                    project_root=project,
                    output_dir=output,
                    manifest_paths=manifests,
                    source_date_epoch=0,
                )

    def test_rejects_hardlinked_source_without_partial_copy(self) -> None:
        module = _module()
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            project, manifests, _ = self._fixture(parent)
            os.link(
                project / "bundle" / "dependency.whl",
                project / "bundle" / "dependency.alias.whl",
            )
            output = parent / "context"
            output.mkdir()
            with self.assertRaisesRegex(ValueError, "single-link"):
                module.materialize_runtime_build_context(
                    project_root=project,
                    output_dir=output,
                    manifest_paths=manifests,
                    source_date_epoch=0,
                )
            self.assertEqual(list(output.iterdir()), [])

    def test_rejects_manifest_path_escape_and_member_escape(self) -> None:
        module = _module()
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            project, manifests, _ = self._fixture(parent)
            outside_manifest = parent / "outside.txt"
            outside_manifest.write_bytes(b"runtime/entry.py\n")
            output = parent / "context"
            output.mkdir()
            with self.assertRaisesRegex(ValueError, "manifest escapes project root"):
                module.materialize_runtime_build_context(
                    project_root=project,
                    output_dir=output,
                    manifest_paths=(outside_manifest,),
                    source_date_epoch=0,
                )

            manifests[0].write_bytes(b"../outside.txt\n")
            with self.assertRaisesRegex(ValueError, "not canonical and relative"):
                module.materialize_runtime_build_context(
                    project_root=project,
                    output_dir=output,
                    manifest_paths=manifests,
                    source_date_epoch=0,
                )
            self.assertEqual(list(output.iterdir()), [])

    def test_rejects_source_replacement_before_held_copy(self) -> None:
        module = _module()
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            project, manifests, _ = self._fixture(parent)
            output = parent / "context"
            output.mkdir()
            original = module._copy_held_source
            replaced = False

            def replace_then_copy(source, destination, **kwargs):
                nonlocal replaced
                if not replaced:
                    replaced = True
                    source.write_bytes(source.read_bytes() + b"drift")
                return original(source, destination, **kwargs)

            with mock.patch.object(module, "_copy_held_source", replace_then_copy):
                with self.assertRaisesRegex(ValueError, "changed before copy"):
                    module.materialize_runtime_build_context(
                        project_root=project,
                        output_dir=output,
                        manifest_paths=manifests,
                        source_date_epoch=0,
                    )

    def test_rejects_concurrently_injected_empty_directory(self) -> None:
        module = _module()
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            project, manifests, _ = self._fixture(parent)
            output = parent / "context"
            output.mkdir()
            original = module._copy_held_source
            injected = False

            def copy_then_inject(source, destination, **kwargs):
                nonlocal injected
                digest = original(source, destination, **kwargs)
                if not injected:
                    injected = True
                    (output / "foreign-empty-directory").mkdir()
                return digest

            with mock.patch.object(module, "_copy_held_source", copy_then_inject):
                with self.assertRaisesRegex(ValueError, "inventory drifted"):
                    module.materialize_runtime_build_context(
                        project_root=project,
                        output_dir=output,
                        manifest_paths=manifests,
                        source_date_epoch=0,
                    )

    @unittest.skipUnless(os.name == "posix", "symlink fixture requires POSIX")
    def test_rejects_symlinked_manifest_member_without_partial_copy(self) -> None:
        module = _module()
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            project, manifests, _ = self._fixture(parent)
            target = project / "runtime" / "entry.py"
            target.unlink()
            target.symlink_to(project / "bundle" / "requirements.lock")
            output = parent / "context"
            output.mkdir()
            with self.assertRaisesRegex(ValueError, "physical single-link regular file"):
                module.materialize_runtime_build_context(
                    project_root=project,
                    output_dir=output,
                    manifest_paths=manifests,
                    source_date_epoch=0,
                )
            self.assertEqual(list(output.iterdir()), [])

    @unittest.skipUnless(os.name == "posix", "symlink fixture requires POSIX")
    def test_rejects_symlinked_manifest_itself(self) -> None:
        module = _module()
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            project, manifests, _ = self._fixture(parent)
            alias = project / "manifests" / "runtime-alias.txt"
            alias.symlink_to(manifests[0])
            output = parent / "context"
            output.mkdir()
            with self.assertRaisesRegex(ValueError, "physical single-link regular file"):
                module.materialize_runtime_build_context(
                    project_root=project,
                    output_dir=output,
                    manifest_paths=(alias, manifests[1]),
                    source_date_epoch=0,
                )
            self.assertEqual(list(output.iterdir()), [])


class RuntimeBuildContextMetadataTests(unittest.TestCase):
    def _case(self):
        # Retain small witnesses for both RED and GREEN; never replay a root.
        parent = Path(tempfile.mkdtemp(prefix="buildmeta-"))
        project, manifests, paths = RuntimeBuildContextV3Tests()._fixture(parent)
        output = parent / "context"
        output.mkdir()
        return _module(), project, manifests, paths, output

    def _manifest(self, raw):
        parent = Path(tempfile.mkdtemp(prefix="buildmeta-"))
        path = parent / "manifest.txt"
        path.write_bytes(raw)
        return _module(), parent, path

    def _run(self, module, project, manifests, output):
        return module.materialize_runtime_build_context(
            project_root=project, output_dir=output,
            manifest_paths=manifests, source_date_epoch=0,
        )

    def _refuse_before_copy(self, module, project, manifests, output, message):
        with mock.patch.object(module, "_copy_held_source", wraps=module._copy_held_source) as copy:
            with self.assertRaisesRegex(ValueError, message):
                self._run(module, project, manifests, output)
            copy.assert_not_called()
        self.assertEqual(list(output.iterdir()), [])

    def test_manifest_size_is_refused_before_reading_or_decoding(self):
        module, root, manifest = self._manifest(b"x" * 8192 + b"\n")
        # GREEN strengthening after retained RED: reject from sealed metadata,
        # before either the old unbounded read or a new descriptor/read path.
        with mock.patch.object(Path, "read_bytes", side_effect=AssertionError("unbounded manifest read")), \
                mock.patch.object(module.os, "open", side_effect=AssertionError("oversize manifest opened")), \
                mock.patch.object(module.os, "read", side_effect=AssertionError("oversize manifest read")):
            with self.assertRaisesRegex(ValueError, "manifest byte bound"):
                module._manifest_members(root, manifest)

    def test_manifest_growth_and_truncation_cannot_be_accumulated(self):
        for chunks in ((b"x\nx",), (b"x", b"\nx"), (b"x", b"")):
            with self.subTest(chunks=chunks):
                module, root, manifest = self._manifest(b"x\n")
                with mock.patch.object(module.os, "read", side_effect=chunks) as read:
                    with self.assertRaisesRegex(ValueError, "manifest size drifted"):
                        module._manifest_members(root, manifest)
                    self.assertLessEqual(read.call_count, len(chunks))
                    self.assertEqual(read.call_args_list[0].args[1], 3)
                    if read.call_count == 2:
                        self.assertEqual(read.call_args_list[1].args[1], 2)

    def test_manifest_open_is_nonblocking_nofollow_and_immediately_validated(self):
        module, root, manifest = self._manifest(b"x\n")
        with mock.patch.object(module.os, "open", wraps=os.open) as opened, \
                mock.patch.object(module.os, "fstat", wraps=os.fstat) as checked:
            self.assertEqual(module._manifest_members(root, manifest), ("x",))
        self.assertEqual(opened.call_count, 1)
        self.assertGreaterEqual(checked.call_count, 1)
        flags = opened.call_args.args[1]
        for name in ("O_NONBLOCK", "O_NOFOLLOW", "O_CLOEXEC"):
            if hasattr(os, name):
                self.assertEqual(flags & getattr(os, name), getattr(os, name))

    def test_manifest_entry_count_is_refused_before_path_collection(self):
        raw = b"".join(f"x{index:03d}\n".encode("ascii") for index in range(129))
        module, root, manifest = self._manifest(raw)
        with self.assertRaisesRegex(ValueError, "manifest entry bound"):
            module._manifest_members(root, manifest)

    def test_path_bytes_alphabet_and_depth_are_bounded(self):
        for value in ("x" * 257, "/".join("x" for _ in range(9)), "caf\u00e9", "x\x01y"):
            with self.subTest(value=value):
                module, root, manifest = self._manifest(value.encode("utf-8") + b"\n")
                with self.assertRaisesRegex(ValueError, "manifest path bound"):
                    module._manifest_members(root, manifest)

    def test_four_manifest_inputs_refuse_before_any_destination_write(self):
        module, project, manifests, _, output = self._case()
        extra = tuple(project / "manifests" / name for name in ("third.txt", "fourth.txt"))
        for path in extra:
            path.write_bytes(b"runtime/entry.py\n")
        self._refuse_before_copy(module, project, manifests + extra, output, "manifest count bound")

    def test_manifest_input_iterator_stops_after_first_excess_element(self):
        module, project, manifests, _, output = self._case()
        consumed = []

        def candidates():
            for index in range(4):
                consumed.append(index)
                yield manifests[index % 2]
            raise AssertionError("input consumed beyond the first excess manifest")

        self._refuse_before_copy(module, project, candidates(), output, "manifest count bound")
        self.assertEqual(consumed, [0, 1, 2, 3])

    def test_union_overflow_refuses_before_member_stat_or_copy(self):
        module, project, manifests, _, output = self._case()
        rows = tuple(f"x{index:03d}" for index in range(129))
        with mock.patch.object(module, "_manifest_members", side_effect=(rows[:65], rows[65:])), \
                mock.patch.object(module, "_physical_member", side_effect=AssertionError("early member stat")):
            self._refuse_before_copy(module, project, manifests, output, "path union bound")

    def _sized_member(self, original, sizes):
        def member(root, relative):
            source, info = original(root, relative)
            if relative in sizes:
                info = SimpleNamespace(**{
                    name: (sizes[relative] if name == "st_size" else getattr(info, name))
                    for name in ("st_dev", "st_ino", "st_mode", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")
                })
            return source, info
        return member

    def test_late_oversize_or_negative_member_refuses_before_first_copy(self):
        for size in (-1, 32 * 1024**2 + 1):
            with self.subTest(size=size):
                module, project, manifests, _, output = self._case()
                member = self._sized_member(module._physical_member, {"runtime/entry.py": size})
                with mock.patch.object(module, "_physical_member", side_effect=member):
                    self._refuse_before_copy(module, project, manifests, output, "member byte bound")

    def test_total_member_bytes_refuse_before_first_copy(self):
        module, project, manifests, _, output = self._case()
        member = self._sized_member(module._physical_member, {
            "bundle/dependency.whl": 24 * 1024**2, "runtime/entry.py": 24 * 1024**2,
        })
        with mock.patch.object(module, "_physical_member", side_effect=member):
            self._refuse_before_copy(module, project, manifests, output, "context byte bound")

    def test_manifest_descriptor_substitution_refuses_before_first_read(self):
        module, root, manifest = self._manifest(b"x\n")
        info = manifest.stat()
        fifo = SimpleNamespace(**{
            name: (stat.S_IFIFO | 0o600 if name == "st_mode" else getattr(info, name))
            for name in ("st_dev", "st_ino", "st_mode", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")
        })
        with mock.patch.object(module.os, "fstat", return_value=fifo), \
                mock.patch.object(module.os, "read", side_effect=AssertionError("unsafe descriptor read")) as read:
            with self.assertRaisesRegex(ValueError, "manifest changed before read"):
                module._manifest_members(root, manifest)
            read.assert_not_called()

    def test_manifest_read_and_close_failures_keep_both_original_causes(self):
        module, root, manifest = self._manifest(b"x\n")
        primary = OSError("controlled read")
        secondary = OSError("controlled close")
        close = os.close

        def close_then_fail(descriptor):
            close(descriptor)
            raise secondary

        with mock.patch.object(module.os, "read", side_effect=primary), \
                mock.patch.object(module.os, "close", side_effect=close_then_fail):
            with self.assertRaises(ValueError) as refused:
                module._manifest_members(root, manifest)
        causes = []
        current = refused.exception
        for _ in range(8):
            if current is None or any(current is item for item in causes):
                break
            causes.append(current)
            current = current.__cause__ or current.__context__
        self.assertTrue(any(item is primary for item in causes))
        self.assertTrue(any(item is secondary for item in causes))

    def test_exact_manifest_and_path_boundaries_preserve_original_rows(self):
        rows = tuple(f"{index:03d}" + "x" * 60 for index in range(128))
        raw = ("\n".join(rows) + "\n").encode("ascii")
        self.assertEqual(len(raw), 8192)
        module, root, manifest = self._manifest(raw)
        self.assertEqual(module._manifest_members(root, manifest), rows)
        for value in ("x" * 256, "/".join("x" for _ in range(8)), 'a"b'):
            module, root, manifest = self._manifest(value.encode("ascii") + b"\n")
            self.assertEqual(module._manifest_members(root, manifest), (value,))

    def test_success_preserves_schema_bytes_hash_and_timestamp(self):
        module, project, manifests, paths, output = self._case()
        result = self._run(module, project, manifests, output)
        self.assertEqual(result, {
            "schema_version": 3, "artifact_kind": "vast_exact_runtime_build_context_v3",
            "relative_paths": paths, "aggregate_sha256": _aggregate(project, paths),
            "source_date_epoch": 0,
        })
        for relative in paths:
            self.assertEqual((output / relative).read_bytes(), (project / relative).read_bytes())
            self.assertEqual(int((output / relative).stat().st_mtime), 0)

    def test_output_scans_never_collect_or_recurse_into_unexpected_tree(self):
        module, project, manifests, _, output = self._case()
        original_copy = module._copy_held_source
        original_scan = os.scandir
        foreign = output / "foreign"

        def copy_then_inject(*args, **kwargs):
            digest = original_copy(*args, **kwargs)
            foreign.mkdir(exist_ok=True)
            return digest

        def scan(path):
            if Path(path) == foreign:
                raise AssertionError("descended into an unadmitted directory")
            return original_scan(path)

        with mock.patch.object(module, "_copy_held_source", side_effect=copy_then_inject), \
                mock.patch.object(module.os, "scandir", side_effect=scan), \
                mock.patch.object(Path, "rglob", side_effect=AssertionError("unbounded recursive scan")), \
                mock.patch.object(Path, "iterdir", side_effect=AssertionError("eager directory scan")):
            with self.assertRaisesRegex(ValueError, "inventory drifted"):
                self._run(module, project, manifests, output)


if __name__ == "__main__":
    unittest.main()
