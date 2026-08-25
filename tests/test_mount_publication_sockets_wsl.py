from __future__ import annotations

import os
from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "mount_publication_sockets_wsl.sh"


class MountPublicationSocketsWslTests(unittest.TestCase):
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
        self.assertIn("--source-socket-dir", completed.stdout)
        self.assertIn("--project-root", completed.stdout)
        self.assertIn("--project-socket-mount", completed.stdout)
        self.assertIn("--check-only", completed.stdout)

    @unittest.skipIf(os.name == "nt", "live mount verification requires WSL")
    def test_check_only_accepts_the_canonical_writable_mount(self) -> None:
        source = (
            Path.home()
            / ".local/state/vast/publication/sockets/model-parity-v3-20260824"
        )
        target = ROOT / ".publication-sockets/model-parity-v3"
        if not source.is_dir() or not target.is_dir():
            self.skipTest("canonical publication socket mount is not materialized")
        completed = subprocess.run(
            [
                "bash",
                str(SCRIPT),
                "--check-only",
                "--source-socket-dir",
                str(source),
                "--project-root",
                str(ROOT),
                "--project-socket-mount",
                ".publication-sockets/model-parity-v3",
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.assertIn('"status":"verified"', completed.stdout)
        self.assertIn('"target_writable":true', completed.stdout)
        self.assertIn('"source_target_identity_equal":true', completed.stdout)


if __name__ == "__main__":
    unittest.main()
