from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

SOURCE_BOUND_FILES = (
    "policies/ql_heft_frozen.policy",
    "policies/aw_heft_reference_v1.json",
    "scripts/formal_aw_heft_reference.py",
    "scripts/resource_interval_contract.py",
    "deploy/native_gst_probe/checkpoint_resource_interval_emitter.hpp",
    "deploy/native_gst_probe/vast_native_gst_probe.cpp",
)


class RepositoryIntegrityTests(unittest.TestCase):
    def test_local_capability_and_staging_files_are_git_ignored(self) -> None:
        ignored_entries = {
            line.strip()
            for line in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        self.assertIn("seafile.txt", ignored_entries)
        self.assertIn("staging/", ignored_entries)

    def test_source_bound_files_use_canonical_lf_bytes(self) -> None:
        for relative_path in SOURCE_BOUND_FILES:
            with self.subTest(path=relative_path):
                payload = (ROOT / relative_path).read_bytes()
                self.assertNotIn(
                    b"\r\n",
                    payload,
                    "source-bound files must remain byte-identical across checkouts",
                )

    def test_resource_v2_docs_describe_native_sources_without_claiming_acceptance(self) -> None:
        for relative_path in ("README.md", "INSTRUCTIONS.md", "docs/NATIVE_ADAPTERS.md"):
            with self.subTest(path=relative_path):
                source = " ".join((ROOT / relative_path).read_text(encoding="utf-8").split())
                self.assertIn("runtime-only decoder submit-to-output intervals", source)
                self.assertIn("CUDA-event transfer emitter is still missing", source)
                self.assertNotIn(
                    "native CUDA-event and decoder submit/complete emitters still do not exist",
                    source,
                )

        instructions = (ROOT / "INSTRUCTIONS.md").read_text(encoding="utf-8")
        self.assertIn(
            "ready_validator_and_native_interval_sources_not_target_verified_not_publication_bound",
            instructions,
        )
        self.assertNotIn(
            "ready_validator_and_fanout_source_not_target_verified_not_publication_bound",
            instructions,
        )


if __name__ == "__main__":
    unittest.main()
