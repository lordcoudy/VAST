"""Prove that explicit physical-input consumers use their selected frozen code."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import sys


def fixture_metadata_identity_v1(value: str) -> str:
    """Selected fixture identities have a finite, non-escaping ASCII geometry."""
    if (type(value) is not str or not 1 <= len(value) <= 512
            or any(not 32 <= ord(char) <= 126 or char in '\\"' for char in value)):
        raise ValueError("fixture metadata identity/path requires <=512 safe ASCII bytes")
    return value


def _source_size_and_hash_v1(path: Path) -> tuple[int, str]:
    """Hash a bounded held source without making another full payload copy."""
    with path.open("rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or not 0 <= before.st_size <= 2 * 1024 * 1024:
            raise ValueError("fixture provenance source kind/size bound exceeded")
        digest, total = hashlib.sha256(), 0
        while total <= 2 * 1024 * 1024:
            raw = stream.read(min(65536, 2 * 1024 * 1024 + 1 - total))
            if not raw:
                break
            total += len(raw)
            if total > 2 * 1024 * 1024:
                raise ValueError("fixture provenance source size bound exceeded")
            digest.update(raw)
        after = os.fstat(stream.fileno())
        named = path.stat(follow_symlinks=False)
        identity = lambda row: (row.st_dev, row.st_ino, row.st_size, row.st_mtime_ns, row.st_ctime_ns)
        if (identity(before) != identity(after) or identity(after) != identity(named)
                or total != before.st_size or path.resolve(strict=True) != path):
            raise ValueError("fixture provenance source changed during hashing")
        return total, digest.hexdigest()


def loaded_fixture_production_sources_v1(*, project_root: Path) -> list[dict[str, object]]:
    root = project_root.resolve(strict=True)
    fixture_metadata_identity_v1(str(root))
    if len(sys.modules) > 8192:
        raise ValueError("fixture production module scan count bound exceeded")
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
        if len(records) >= 256:
            raise ValueError("fixture production source record count bound exceeded")
        module_name = fixture_metadata_identity_v1(name)
        loaded_path = fixture_metadata_identity_v1(str(path))
        project_path = fixture_metadata_identity_v1(path.relative_to(root).as_posix())
        size, digest = _source_size_and_hash_v1(path)
        record = {"module": module_name, "loaded_path": loaded_path, "project_path": project_path,
                  "size_bytes": size, "sha256": digest}
        # Fixed keys, three <=512 non-escaping strings, SHA64 and uint64 fit
        # 3*512 +64 +21 +128 <2048 BEFORE encoding; preserve every field.
        if len(json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")) > 2048:
            raise ValueError("fixture production source record byte bound exceeded")
        records.append(record)
    if not records:
        raise ValueError("no selected production modules were observed")
    return records
