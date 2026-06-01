#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from benchmark_contract import ContractError, load_dataset


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate a VAST dataset manifest and local clip checksums")
    parser.add_argument("--manifest", type=Path, default=Path("configs/datasets.yaml"))
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--mode", choices=["smoke", "benchmark"], default="benchmark")
    args = parser.parse_args()
    dataset = load_dataset(
        args.manifest,
        args.dataset,
        mode=args.mode,
        project_root=Path.cwd(),
        require_files=True,
    )
    print(f"dataset={dataset['name']} streams={len(dataset['streams'])} aggregate_sha256={dataset['aggregate_sha256']}")


if __name__ == "__main__":
    try:
        main()
    except ContractError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
