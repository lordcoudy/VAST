#!/usr/bin/env python3
from __future__ import annotations

import platform
import shutil
import subprocess
from pathlib import Path

import psutil


def run_cmd(cmd: list[str]) -> str:
    try:
        return subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return "unavailable"


def detect_cpu() -> str:
    for cmd in (
        ["sysctl", "-n", "machdep.cpu.brand_string"],
        ["wmic", "cpu", "get", "Name", "/value"],
    ):
        output = run_cmd(cmd)
        if output != "unavailable" and output.strip():
            return output.strip().replace("Name=", "")
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.exists():
        for line in cpuinfo.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.lower().startswith("model name"):
                return line.split(":", 1)[1].strip()
    return platform.processor() or "unavailable"


def main() -> None:
    cpu_name = detect_cpu()
    gpu_name = run_cmd(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"]) or "unavailable"
    ram_gb = round(psutil.virtual_memory().total / (1024**3), 2)

    print(f"OS: {platform.platform()}")
    print(f"CPU: {cpu_name}")
    print(f"GPU: {gpu_name}")
    print(f"RAM: {ram_gb} GB")
    print("Tools:")
    for tool in ("docker", "nvcc", "cmake", "gst-launch-1.0", "chronyc", "iperf3", "rsync"):
        print(f"  {tool}: {shutil.which(tool) or 'unavailable'}")


if __name__ == "__main__":
    main()
