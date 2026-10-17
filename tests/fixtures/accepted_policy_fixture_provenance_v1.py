"""Prove that explicit physical-input consumers use their selected frozen code."""
from __future__ import annotations

import hashlib
from pathlib import Path
import sys


def loaded_fixture_production_sources_v1(*, project_root: Path) -> list[dict[str, object]]:
    root = project_root.resolve(strict=True)
    records = []
    for name, module in sorted(sys.modules.items()):
        filename = getattr(module, "__file__", None)
        if not filename or name == "__main__" or name.startswith("tests."):
            continue
        path = Path(filename).resolve(strict=True)
        if path.suffix != ".py" or "scripts" not in {parent.name for parent in path.parents}:
            continue
        if not path.is_relative_to(root / "scripts"):
            raise ValueError(f"production module escaped selected frozen root: {name}: {path}")
        payload = path.read_bytes()
        records.append({"module": name, "loaded_path": str(path), "project_path": path.relative_to(root).as_posix(),
                        "size_bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()})
    if not records:
        raise ValueError("no selected production modules were observed")
    return records
