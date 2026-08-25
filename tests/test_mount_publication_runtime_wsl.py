from __future__ import annotations

import os
from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "mount_publication_runtime_wsl.sh"


class MountPublicationRuntimeWslTests(unittest.TestCase):
    def test_script_is_shell_valid_and_never_edits_boot_configuration(self) -> None:
        self.assertTrue(SCRIPT.is_file())
        source = SCRIPT.read_text(encoding="utf-8")
        subprocess.run(["bash", "-n", str(SCRIPT)], check=True)
        for forbidden in (
            ".wslconfig",
            "/etc/fstab",
            "/etc/profile",
            "systemctl enable",
        ):
            self.assertNotIn(forbidden, source)

    def test_help_exposes_explicit_source_target_and_check_only(self) -> None:
        completed = subprocess.run(
            ["bash", str(SCRIPT), "--help"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.assertIn("--source-runtime", completed.stdout)
        self.assertIn("--project-root", completed.stdout)
        self.assertIn("--project-runtime-mount", completed.stdout)
        self.assertIn("--check-only", completed.stdout)

    @unittest.skipIf(os.name == "nt", "live mount verification requires WSL")
    def test_check_only_accepts_the_canonical_read_only_mounts(self) -> None:
        source = (
            Path.home()
            / ".local/state/vast/publication/runtime/full-publication-cp312-v1"
        )
        target = ROOT / ".publication-runtime/full-publication-cp312-v1"
        if not source.is_dir() or not target.is_dir():
            self.skipTest("canonical publication runtime mounts are not materialized")
        completed = subprocess.run(
            [
                "bash",
                str(SCRIPT),
                "--check-only",
                "--source-runtime",
                str(source),
                "--project-root",
                str(ROOT),
                "--project-runtime-mount",
                ".publication-runtime/full-publication-cp312-v1",
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.assertIn('"status":"verified"', completed.stdout)
        self.assertIn('"source_read_only":true', completed.stdout)
        self.assertIn('"target_read_only":true', completed.stdout)


if __name__ == "__main__":
    unittest.main()
