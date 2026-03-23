#!/usr/bin/env python3
from __future__ import annotations

import platform
import subprocess

import psutil


def run_cmd(cmd: list[str]) -> str:
    try:
        return subprocess.check_output(cmd, text=True).strip()
    except Exception:
        return "unavailable"


def main() -> None:
    cpu_name = run_cmd(["sysctl", "-n", "machdep.cpu.brand_string"])
    gpu_name = run_cmd(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"]) or "unavailable"
    ram_gb = round(psutil.virtual_memory().total / (1024**3), 2)

    print(f"OS: {platform.platform()}")
    print(f"CPU: {cpu_name}")
    print(f"GPU: {gpu_name}")
    print(f"RAM: {ram_gb} GB")


if __name__ == "__main__":
    main()
