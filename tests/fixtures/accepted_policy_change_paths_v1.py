"""Resolve only this repair's active or supported dated archive evidence."""
from datetime import date
from pathlib import Path
import re


CHANGE = "fix-accepted-policy-preprocessing"


def consumer_evidence_directory_v1(project_root: Path) -> Path:
    root = Path(project_root)
    if not root.is_absolute() or not root.is_dir() or root.resolve(strict=True) != root:
        raise ValueError("fixture repository root is not canonical")
    changes = root / "openspec/changes"
    active = changes / CHANGE
    candidates = [active] if active.exists() else []
    for archived in (changes / "archive").glob("*-" + CHANGE):
        match = re.fullmatch(r"(\d{4}-\d{2}-\d{2})-" + re.escape(CHANGE), archived.name)
        if match is None:
            raise ValueError("fixture archive name is unsupported")
        date.fromisoformat(match[1])
        candidates.append(archived)
    if len(candidates) != 1:
        raise ValueError("fixture evidence origin is missing or ambiguous")
    directory = candidates[0] / "evidence/consumer-01"
    if not directory.is_dir() or directory.resolve(strict=True) != directory:
        raise ValueError("fixture evidence directory is missing or aliased")
    return directory
