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
    def test_source_bound_files_use_canonical_lf_bytes(self) -> None:
        for relative_path in SOURCE_BOUND_FILES:
            with self.subTest(path=relative_path):
                payload = (ROOT / relative_path).read_bytes()
                self.assertNotIn(
                    b"\r\n",
                    payload,
                    "source-bound files must remain byte-identical across checkouts",
                )


if __name__ == "__main__":
    unittest.main()
