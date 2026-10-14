from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from s3_destination import S3Destination, S3ConfigurationError


def destination_config():
    return {
        "artifact_kind": "vast_s3_destination_v1",
        "backend": "s3",
        "endpoint": "https://s3.savva-balashov.me",
        "bucket": "vast-archive",
        "prefix": "vast/",
        "region": "us-east-1",
        "addressing_style": "path",
        "credential_profile": "vast-s3",
    }


class S3DestinationTests(unittest.TestCase):
    def test_selected_destination_and_run_keys_are_deterministic(self):
        one = S3Destination.from_mapping(destination_config())
        two = S3Destination.from_mapping(destination_config())
        self.assertEqual(one.identity, two.identity)
        self.assertEqual(one.run_prefix("a" * 64, "run-01"), "vast/" + "a" * 64 + "/run-01/")
        self.assertEqual(one.object_key("a" * 64, "run-01", "pair.receipt.json"),
                         "vast/" + "a" * 64 + "/run-01/pair.receipt.json")
        self.assertNotIn("credential_profile", one.identity)
        self.assertRegex(one.identity["destination_sha256"], r"^[0-9a-f]{64}$")

    def test_unknown_missing_or_wrong_type_fields_are_rejected(self):
        for key in destination_config():
            missing = destination_config()
            del missing[key]
            wrong = destination_config()
            wrong[key] = 1
            for value in (missing, wrong):
                with self.subTest(key=key, value=value), self.assertRaises(S3ConfigurationError):
                    S3Destination.from_mapping(value)
        value = destination_config()
        value["secret_access_key"] = "must-not-be-consumed"
        with self.assertRaises(S3ConfigurationError) as caught:
            S3Destination.from_mapping(value)
        self.assertNotIn("must-not-be-consumed", str(caught.exception))

    def test_unsafe_or_foreign_destination_is_rejected(self):
        for key, values in {
            "endpoint": ["http://s3.savva-balashov.me", "https://user:password@s3.savva-balashov.me",
                         "https://s3.savva-balashov.me?secret=hidden", "https://s3.savva-balashov.me/#x",
                         "https://other.example", "https://s3.savva-balashov.me/", "https://s3.savva-balashov.me:443"],
            "bucket": ["other-bucket", "vast-archive/escape", ""],
            "prefix": ["", "/vast/", "../vast/", "vast/../", "vast//", "foreign/", "vast/\n"],
            "region": ["other-region", ""],
            "addressing_style": ["virtual", "auto"],
            "credential_profile": ["default", "vast-s3\n"],
        }.items():
            for bad in values:
                value = destination_config()
                value[key] = bad
                with self.subTest(key=key, value=bad), self.assertRaises(S3ConfigurationError):
                    S3Destination.from_mapping(value)

    def test_object_key_cannot_escape_run_namespace(self):
        destination = S3Destination.from_mapping(destination_config())
        for matrix, run, name in [("A" * 64, "run-01", "pair"), ("a" * 64, "../run", "pair"),
                                  ("a" * 64, "run-01", "../pair"), ("a" * 64, "run-01", "a/b"),
                                  ("a" * 64, "run-01", "a\\b"), ("a" * 64, "run-01", ".."),
                                  ("a" * 64, "run-01", "x\x00y"), ("a" * 64, "run-01", "")]:
            with self.subTest(matrix=matrix, run=run, name=name), self.assertRaises(S3ConfigurationError):
                destination.object_key(matrix, run, name)

    def test_descriptor_requires_one_unchanged_physical_bounded_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "destination.json"
            config.write_text(json.dumps(destination_config()), encoding="utf-8")
            self.assertEqual(S3Destination.from_file(config).bucket, "vast-archive")
            if os.name == "posix":
                alias = Path(tmp) / "alias.json"
                alias.symlink_to(config)
                with self.assertRaises(S3ConfigurationError):
                    S3Destination.from_file(alias)
                hard = Path(tmp) / "hard.json"
                os.link(config, hard)
                with self.assertRaises(S3ConfigurationError):
                    S3Destination.from_file(config)
                hard.unlink()
            config.write_bytes(b"x" * (65536 + 1))
            with self.assertRaises(S3ConfigurationError):
                S3Destination.from_file(config)

    def test_duplicate_yaml_keys_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "destination.yaml"
            config.write_text("backend: s3\nbackend: seafile\n", encoding="utf-8")
            with self.assertRaises(S3ConfigurationError):
                S3Destination.from_file(config)


if __name__ == "__main__":
    unittest.main()
