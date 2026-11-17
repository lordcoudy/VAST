"""Read-only validation of publication image-freeze receipts."""

from __future__ import annotations

import hashlib
import json
import stat
from pathlib import Path
from typing import Mapping


RECEIPT_KIND = "vast_publication_image_freeze_receipt_v1"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")


def _receipt_sha256(payload: Mapping[str, object]) -> str:
    unsigned = dict(payload)
    unsigned.pop("receipt_sha256", None)
    return hashlib.sha256(_canonical_json(unsigned)).hexdigest()


def load_publication_image_freeze_receipt(path: Path) -> dict[str, object]:
    receipt_path = Path(path)
    info = receipt_path.lstat()
    _require(stat.S_ISREG(info.st_mode) and not receipt_path.is_symlink() and int(info.st_nlink) == 1, "producer receipt must be a physical single-link file")
    try:
        data = json.loads(receipt_path.read_bytes())
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("producer receipt is not valid JSON") from error
    _require(isinstance(data, dict) and data.get("artifact_kind") == RECEIPT_KIND and data.get("schema_version") == 1, "producer receipt envelope drifted")
    _require(type(data.get("receipt_sha256")) is str and data["receipt_sha256"] == _receipt_sha256(data), "producer receipt self-identity drifted")
    _require(isinstance(data.get("images"), list), "producer receipt images are invalid")
    return data
