"""R5/S5 re-verification: two fresh Windows checkouts (core.autocrlf true/false) of C_Q1 must
reproduce every image build input byte-for-byte as built in the exact-commit build root."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

COMMIT = sys.argv[1]
REPO = Path(r"E:/STUDY/VAST")
BUILD_ROOT = Path(r"E:/STUDY/VAST/tmp/qfb-root-20261007a")
WORK = Path(r"E:/STUDY/VAST/tmp/qfb-r5s5-checkouts-20261008e")
OUT = Path(sys.argv[2])


def inventory(root: Path) -> list[str]:
    paths = {"configs/publication_image_build_v1.json", "configs/publication_qualification_image_refreeze_v1.json"}
    for allow in list(root.glob("deploy/**/*allowlist*.txt")):
        paths.add(allow.relative_to(root).as_posix())
        for line in allow.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and (root / line).is_file():
                paths.add(line)
    for dockerfile in root.glob("deploy/**/Dockerfile*"):
        paths.add(dockerfile.relative_to(root).as_posix())
    return sorted(paths)


def describe(root: Path, paths: list[str]) -> dict[str, list]:
    return {path: [(root / path).stat().st_size, hashlib.sha256((root / path).read_bytes()).hexdigest()] for path in paths}


def checkout(autocrlf: str, paths: list[str]) -> Path:
    target = WORK / f"autocrlf-{autocrlf}"
    assert not target.exists(), target
    git = ["git", "-c", f"core.autocrlf={autocrlf}", "-c", "core.longpaths=true"]
    subprocess.run(git + ["clone", "-q", "--no-checkout", str(REPO), str(target)], check=True)
    for key, value in (("core.autocrlf", autocrlf), ("core.longpaths", "true")):
        subprocess.run(["git", "-C", str(target), "config", key, value], check=True)
    subprocess.run(["git", "-C", str(target), "sparse-checkout", "set", "--no-cone", *["/" + p for p in paths]], check=True)
    subprocess.run(["git", "-C", str(target), "-c", "advice.detachedHead=false", "checkout", "-q", COMMIT], check=True)
    return target


def main() -> None:
    WORK.mkdir(exist_ok=True)
    paths = inventory(BUILD_ROOT)
    reference = describe(BUILD_ROOT, paths)
    result = {"kind": "r5_s5_fresh_checkout_reproduction_v1", "commit": COMMIT, "inventory_files": len(paths),
              "reference_root": str(BUILD_ROOT), "checkouts": {}}
    for autocrlf in ("true", "false"):
        root = checkout(autocrlf, paths)
        observed = describe(root, paths)
        differing = sorted(path for path in paths if observed[path] != reference[path])
        status = subprocess.run(["git", "-C", str(root), "status", "--porcelain"], capture_output=True, text=True).stdout
        result["checkouts"][autocrlf] = {"root": str(root), "differing_files": differing, "clean": status == "",
                                         "equal": not differing}
    result["reproduced"] = all(row["equal"] and row["clean"] for row in result["checkouts"].values())
    result["reference"] = reference
    OUT.write_text(json.dumps(result, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({k: (v if k != "reference" else len(v)) for k, v in result.items() if k != "checkouts"}),
          {k: (len(v["differing_files"]), v["clean"]) for k, v in result["checkouts"].items()})


if __name__ == "__main__":
    main()
