#!/usr/bin/env python3
"""Run the durable-process gate in two required fresh interpreters."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
KIND = "vast_publication_durable_process_split_gate_receipt_v1"
DOMAIN = b"VAST:publication-durable-process-split-gate:v1\0"

GATES = (
    (
        "native_thread_strict_supervisor",
        25,
        ("tests.test_backend_publication_process_supervisor_v3",),
    ),
    (
        "durable_output_production_finalizer",
        51,
        (
            "tests.test_backend_publication_output_transaction_v3",
            "tests.test_backend_publication_output_transaction_production_v3",
            "tests.test_production_arm_evidence_finalizer_v1",
        ),
    ),
)


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")


def main() -> int:
    observations: list[dict[str, object]] = []
    for name, expected_count, modules in GATES:
        command = [sys.executable, "-B", "-m", "unittest", *modules, "-q"]
        completed = subprocess.run(
            command,
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            env={},
            timeout=180,
            check=False,
        )
        diagnostic = completed.stdout + completed.stderr
        match = re.search(rb"Ran ([0-9]+) tests? in", diagnostic)
        observed_count = int(match.group(1)) if match is not None else -1
        if completed.returncode != 0 or observed_count != expected_count:
            sys.stderr.buffer.write(diagnostic)
            return 1
        observations.append(
            {
                "name": name,
                "fresh_interpreter": True,
                "expected_test_count": expected_count,
                "observed_test_count": observed_count,
                "exit_code": completed.returncode,
                "modules": list(modules),
                "diagnostic_sha256": hashlib.sha256(diagnostic).hexdigest(),
            }
        )
    core = {
        "schema_version": 1,
        "artifact_kind": KIND,
        "status": "green",
        "python_executable": str(Path(sys.executable).resolve(strict=True)),
        "gates": observations,
        "same_process_topology_valid": False,
        "same_process_blocker": "native_thread_strict_supervisor_requires_fresh_interpreter",
        "benchmark_executed": False,
        "pilot_executed": False,
    }
    receipt = {
        **core,
        "receipt_sha256": hashlib.sha256(DOMAIN + _canonical(core)).hexdigest(),
    }
    sys.stdout.buffer.write(_canonical(receipt) + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
