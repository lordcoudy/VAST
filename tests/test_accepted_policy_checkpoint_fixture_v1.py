"""Refusal boundaries for the genuine-input checkpoint fixture builder."""

from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


class AcceptedPolicyCheckpointFixtureTests(unittest.TestCase):
    def test_loaded_executor_cannot_authorize_another_project_root(self):
        from tests.fixtures.accepted_policy_checkpoint_fixture_v1 import write_complete_fixture_checkpoint_v1
        with tempfile.TemporaryDirectory() as name:
            root = Path(name).resolve(strict=True)
            with self.assertRaisesRegex(ValueError, "selected project root"):
                write_complete_fixture_checkpoint_v1(prepared={"root": root, "output_dir": root},
                    guardian_authority_path=root / "authority.json")
            self.assertEqual(list(root.iterdir()), [])

    def test_checkpoint_cannot_escape_selected_root_before_any_io(self):
        from tests.fixtures.accepted_policy_checkpoint_fixture_v1 import write_complete_fixture_checkpoint_v1
        with tempfile.TemporaryDirectory() as name:
            namespace = Path(name).resolve(strict=True)
            root = namespace / "project"
            root.mkdir()
            with self.assertRaisesRegex(ValueError, "fresh canonical project artifact"):
                write_complete_fixture_checkpoint_v1(prepared={"root": root, "output_dir": root},
                    guardian_authority_path=root / "authority.json", checkpoint_path=namespace / "escape.json")
            self.assertFalse((namespace / "escape.json").exists())


if __name__ == "__main__":
    unittest.main()
