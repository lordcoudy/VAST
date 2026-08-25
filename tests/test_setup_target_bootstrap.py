from __future__ import annotations

import os
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SETUP_SCRIPT = PROJECT_ROOT / "scripts" / "setup_target.sh"
SOURCE_GUARD = 'if [[ "${BASH_SOURCE[0]}" == "$0" ]]'
CANONICAL_WSL_VENV = Path(
    "/home/s-a-balashov/.local/state/vast/publication/runtime/"
    "full-publication-cp312-v1"
)


@unittest.skipIf(os.name == "nt", "requires native Linux bash")
class SetupTargetBootstrapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.script_text = SETUP_SCRIPT.read_text(encoding="utf-8")

    def run_sourced(
        self,
        body: str,
        *,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        self.assertIn(
            SOURCE_GUARD,
            self.script_text,
            "setup_target.sh must not run installers when sourced by direct tests",
        )
        child_env = os.environ.copy()
        if env:
            child_env.update(env)
        return subprocess.run(
            [
                "bash",
                "-c",
                'source "$1"\n' + body,
                "setup-target-test",
                str(SETUP_SCRIPT),
            ],
            cwd=PROJECT_ROOT,
            env=child_env,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_script_is_safe_to_source_and_exposes_argument_parser(self) -> None:
        completed = self.run_sourced("type parse_args >/dev/null")

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout, "")

    def test_wsl_default_uses_canonical_ext4_publication_venv(self) -> None:
        completed = self.run_sourced(
            'is_wsl() { return 0; }\nparse_args\nprintf "%s" "$VENV_DIR"',
            env={"HOME": "/home/s-a-balashov", "VENV_DIR": ""},
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout, str(CANONICAL_WSL_VENV))

    def test_new_publication_venv_uses_plain_python_copy(self) -> None:
        self.assertIn(
            '"$PYTHON_BIN" -m venv --copies "$VENV_DIR"',
            self.script_text,
        )

    def test_non_wsl_default_preserves_project_local_venv(self) -> None:
        completed = self.run_sourced(
            'is_wsl() { return 1; }\nparse_args\nprintf "%s" "$VENV_DIR"',
            env={"VENV_DIR": ""},
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout, str(PROJECT_ROOT / ".venv"))

    def test_explicit_absolute_linux_venv_is_selected(self) -> None:
        selected = "/home/s-a-balashov/.local/state/vast/publication/runtime/custom"
        completed = self.run_sourced(
            'is_wsl() { return 0; }\n'
            'parse_args --venv-dir "$TEST_VENV_DIR"\n'
            'printf "%s" "$VENV_DIR"',
            env={"TEST_VENV_DIR": selected, "VENV_DIR": ""},
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout, selected)

    def test_wsl_rejects_project_venv_on_drvfs(self) -> None:
        completed = self.run_sourced(
            'is_wsl() { return 0; }\n'
            'parse_args --venv-dir /mnt/e/STUDY/VAST/.venv',
            env={"VENV_DIR": ""},
        )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("WSL Linux filesystem", completed.stderr)

    def test_relative_venv_path_is_rejected(self) -> None:
        completed = self.run_sourced(
            'is_wsl() { return 1; }\nparse_args --venv-dir .venv',
            env={"VENV_DIR": ""},
        )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("absolute Linux path", completed.stderr)

    def test_setup_activates_selected_venv_and_installs_project_requirements(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            selected = Path(temp_dir) / "publication-venv"
            bin_dir = selected / "bin"
            bin_dir.mkdir(parents=True)
            quoted_selected = shlex.quote(str(selected))
            (bin_dir / "activate").write_text(
                f"VIRTUAL_ENV={quoted_selected}\n"
                "export VIRTUAL_ENV\n"
                'PATH="$VIRTUAL_ENV/bin:$PATH"\n'
                "export PATH\n",
                encoding="utf-8",
            )
            fake_python = bin_dir / "python"
            fake_python.write_text(
                "#!/usr/bin/env bash\n"
                'printf "%s\\n" "$*" >> "$VIRTUAL_ENV/python-invocations"\n',
                encoding="utf-8",
            )
            fake_python.chmod(0o755)

            completed = self.run_sourced(
                'is_wsl() { return 0; }\n'
                'parse_args --venv-dir "$TEST_VENV_DIR"\n'
                "setup_python_env\n"
                'printf "\\nVIRTUAL_ENV=%s" "$VIRTUAL_ENV"',
                env={
                    "INSTALL_OPENVINO": "0",
                    "TEST_VENV_DIR": str(selected),
                    "VENV_DIR": "",
                },
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn(f"VIRTUAL_ENV={selected}", completed.stdout)
            invocations = (selected / "python-invocations").read_text(encoding="utf-8")
            self.assertIn("-m pip install -r requirements.txt", invocations)
            self.assertNotIn("pip install psutil", invocations)


if __name__ == "__main__":
    unittest.main()
