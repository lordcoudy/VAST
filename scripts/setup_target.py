#!/usr/bin/env python3
from __future__ import annotations

import argparse
import platform
import subprocess
import sys
from pathlib import Path


def build_command(system_name: str, project_root: Path, passthrough: list[str]) -> tuple[list[str], str]:
    scripts_dir = project_root / "scripts"

    if system_name == "Windows":
        ps_script = scripts_dir / "setup_target_windows.ps1"
        return [
            "powershell",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ps_script),
            *passthrough,
        ], "windows"

    sh_script = scripts_dir / "setup_target.sh"
    return ["bash", str(sh_script), *passthrough], "linux"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="One-command setup launcher that auto-detects OS and runs matching installer"
    )
    parser.add_argument(
        "installer_args",
        nargs=argparse.REMAINDER,
        help="Arguments forwarded to the selected installer script",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print selected command only")
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent
    os_name = platform.system()

    cmd, selected = build_command(os_name, project_root, args.installer_args)

    print(f"[launcher] detected OS: {os_name}")
    print(f"[launcher] selected installer profile: {selected}")
    if os_name not in {"Windows", "Linux"}:
        print("[launcher] non-Windows OS detected, using Linux installer path by default")
    print("[launcher] running:", " ".join(cmd))

    if args.dry_run:
        return 0

    completed = subprocess.run(cmd, cwd=str(project_root), check=False)
    return int(completed.returncode)


if __name__ == "__main__":
    sys.exit(main())
