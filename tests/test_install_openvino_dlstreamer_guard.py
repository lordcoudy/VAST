from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "install_openvino_dlstreamer.sh"


@unittest.skipUnless(shutil.which("bash"), "bash is required")
class InstallOpenvinoDlstreamerGuardTests(unittest.TestCase):
    def test_script_parses(self) -> None:
        completed = subprocess.run(
            ["bash", "-n", str(SCRIPT)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_install_root_is_exactly_allowlisted(self) -> None:
        probe = 'source "$1"; validate_install_root "$2"'
        accepted = subprocess.run(
            ["bash", "-c", probe, "bash", str(SCRIPT), "/opt/vast/dlstreamer"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        self.assertEqual(accepted.stdout.strip(), "/opt/vast/dlstreamer")
        for unsafe in (
            "/",
            "/usr",
            "/opt/vast",
            "/opt/vast/dlstreamer/..",
            "relative",
        ):
            with self.subTest(unsafe=unsafe):
                rejected = subprocess.run(
                    ["bash", "-c", probe, "bash", str(SCRIPT), unsafe],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertNotEqual(rejected.returncode, 0)


if __name__ == "__main__":
    unittest.main()
