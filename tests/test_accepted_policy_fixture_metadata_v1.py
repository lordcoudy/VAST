"""Selected source metadata bounds; no runtime/compiler/consumer execution."""
import hashlib
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from tests.fixtures import accepted_policy_fixture_provenance_v1 as provenance


class FixtureMetadataTests(unittest.TestCase):
    def source(self, root, content=b"bounded source\n"):
        directory = root / "scripts"
        directory.mkdir()
        path = directory / "selected.py"
        path.write_bytes(content)
        return path

    def test_256_complete_source_records_fit_but_257_refuse(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name).resolve()
            path = self.source(root)
            modules = {"selected_%03d" % n: SimpleNamespace(__file__=str(path)) for n in range(256)}
            with patch.object(provenance.sys, "modules", modules):
                rows = provenance.loaded_fixture_production_sources_v1(project_root=root)
                self.assertEqual(len(rows), 256)
                modules["selected_256"] = SimpleNamespace(__file__=str(path))
                with self.assertRaisesRegex(ValueError, "source.*count|record.*bound"):
                    provenance.loaded_fixture_production_sources_v1(project_root=root)

    def test_selected_source_path_over_512_bytes_refuses(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name).resolve()
            directory = root / "scripts" / ("a" * 190) / ("b" * 190) / ("c" * 150)
            directory.mkdir(parents=True)
            path = directory / "selected.py"
            path.write_bytes(b"bounded\n")
            self.assertGreater(len(str(path)), 512)
            with patch.object(provenance.sys, "modules", {"selected": SimpleNamespace(__file__=str(path))}):
                with self.assertRaisesRegex(ValueError, "identity|path.*bound"):
                    provenance.loaded_fixture_production_sources_v1(project_root=root)

    def test_escaping_and_non_ascii_module_identities_refuse(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name).resolve()
            path = self.source(root)
            for module in ('unsafe"module', "unsafe\\module", "unsafe\tmodule", "unsafe\u00e9module"):
                with self.subTest(module=module), patch.object(provenance.sys, "modules",
                        {module: SimpleNamespace(__file__=str(path))}):
                    with self.assertRaisesRegex(ValueError, "identity|ASCII|bound"):
                        provenance.loaded_fixture_production_sources_v1(project_root=root)

    def test_source_over_two_mib_refuses_without_full_payload_copy(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name).resolve()
            path = self.source(root)
            with path.open("wb") as stream:
                stream.truncate(2 * 1024 * 1024 + 1)
            real_open = Path.open
            class NoPayloadRead:
                def __init__(self, stream): self.stream = stream
                def __enter__(self): return self
                def __exit__(self, *args): self.stream.close()
                def fileno(self): return self.stream.fileno()
                def read(self, *args): raise AssertionError("oversized source reached payload read")
            def open_spy(selected, *args, **kwargs):
                stream = real_open(selected, *args, **kwargs)
                return NoPayloadRead(stream) if selected == path else stream
            with patch.object(provenance.sys, "modules", {"selected": SimpleNamespace(__file__=str(path))}), \
                    patch.object(Path, "open", open_spy):
                with self.assertRaisesRegex(ValueError, "source.*bound|source.*size"):
                    provenance.loaded_fixture_production_sources_v1(project_root=root)

    def test_source_change_during_hashing_refuses(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name).resolve()
            path = self.source(root, b"original\n")
            real_open, changed = Path.open, []
            class Reader:
                def __init__(self, stream): self.stream = stream
                def __enter__(self): return self
                def __exit__(self, *args): self.stream.close()
                def fileno(self): return self.stream.fileno()
                def read(self, size=-1):
                    raw = self.stream.read(size)
                    if raw and not changed:
                        changed.append(True)
                        replacement = path.with_name("replacement.py")
                        with real_open(replacement, "wb") as writer:
                            writer.write(b"foreign!\n")
                        replacement.replace(path)
                    return raw
            def open_spy(selected, *args, **kwargs):
                stream = real_open(selected, *args, **kwargs)
                return Reader(stream) if selected == path else stream
            with patch.object(provenance.sys, "modules", {"selected": SimpleNamespace(__file__=str(path))}), \
                    patch.object(Path, "open", open_spy):
                with self.assertRaisesRegex(ValueError, "changed|drift"):
                    provenance.loaded_fixture_production_sources_v1(project_root=root)
            self.assertEqual(changed, [True])

    def test_complete_small_descriptor_fields_and_hash_remain_unchanged(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name).resolve()
            raw = b"bounded source\n"
            path = self.source(root, raw)
            with patch.object(provenance.sys, "modules", {"selected": SimpleNamespace(__file__=str(path))}):
                self.assertEqual(provenance.loaded_fixture_production_sources_v1(project_root=root), [
                    {"module": "selected", "loaded_path": str(path), "project_path": "scripts/selected.py",
                     "size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}])


if __name__ == "__main__":
    unittest.main()
