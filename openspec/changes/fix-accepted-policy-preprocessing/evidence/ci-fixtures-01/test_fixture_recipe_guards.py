#!/usr/bin/env python3
"""No-write checks for the evidence recipe's review and physical-input guards."""
from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("repair_fixture_recipe", HERE / "materialize_repair_ci_fixtures_v1.py")
RECIPE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RECIPE)


class FixtureRecipeGuardTests(unittest.TestCase):
    def test_duplicate_json_keys_refuse(self) -> None:
        with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
            json.loads('{"path":"one","path":"two"}', object_pairs_hook=RECIPE.pairs)

    def test_nonfinite_canonical_value_refuses(self) -> None:
        with self.assertRaises(ValueError):
            RECIPE.canonical({"value": float("nan")})

    def test_safe_single_link_physical_file_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            source = root / "metadata.json"
            source.write_bytes(b"{}\n")
            self.assertEqual(RECIPE.physical(root, "metadata.json"), source)

    def test_unsafe_relative_paths_refuse(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            for relative in ("", "../metadata.json", "/tmp/metadata.json", "./metadata.json", "a//b.json"):
                with self.subTest(relative=relative), self.assertRaisesRegex(ValueError, "unsafe relative input"):
                    RECIPE.physical(root, relative)

    def test_symlink_alias_refuses(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            (root / "metadata.json").write_bytes(b"{}\n")
            (root / "alias.json").symlink_to("metadata.json")
            with self.assertRaisesRegex(ValueError, "input path alias"):
                RECIPE.physical(root, "alias.json")

    def test_hardlink_alias_refuses(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            (root / "metadata.json").write_bytes(b"{}\n")
            os.link(root / "metadata.json", root / "alias.json")
            with self.assertRaisesRegex(ValueError, "single-link physical file"):
                RECIPE.physical(root, "metadata.json")

    def test_oversized_metadata_refuses(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            with (root / "oversized.json").open("wb") as stream:
                stream.truncate(4 * 1024**2 + 1)
            with self.assertRaisesRegex(ValueError, "bounded single-link physical file"):
                RECIPE.physical(root, "oversized.json")

    def test_wrong_review_hash_refuses_before_any_write(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            with mock.patch.object(RECIPE, "ROOT", root), mock.patch.object(RECIPE, "HERE", root):
                with self.assertRaisesRegex(ValueError, "reviewed fixture plan hash drifted"):
                    RECIPE.apply_reviewed({"status": "planned"}, {}, b"{}\n", "0" * 64)
            self.assertEqual(list(root.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
