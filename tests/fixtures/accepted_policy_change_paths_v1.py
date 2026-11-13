"""Resolve only this repair's active or supported dated archive evidence."""
from datetime import date
import os
from pathlib import Path
import re


CHANGE = "fix-accepted-policy-preprocessing"


def change_directory_v1(project_root: Path) -> Path:
    """This change's directory: the active one, or its single dated archive."""
    root = Path(project_root)
    if not root.is_absolute() or not root.is_dir() or root.resolve(strict=True) != root:
        raise ValueError("fixture repository root is not canonical")
    changes = root / "openspec/changes"
    active = changes / CHANGE
    candidates = [active] if os.path.lexists(active) else []
    for archived in (changes / "archive").glob("*-" + CHANGE):
        if archived.name[11:] != CHANGE:
            continue  # another change's archive
        match = re.fullmatch(r"(\d{4}-\d{2}-\d{2})-" + re.escape(CHANGE), archived.name)
        if match is None:
            raise ValueError("fixture archive name is unsupported")
        date.fromisoformat(match[1])
        candidates.append(archived)
    if len(candidates) != 1:
        raise ValueError("fixture evidence origin is missing or ambiguous")
    directory = candidates[0]
    if not directory.is_dir() or directory.resolve(strict=True) != directory:
        raise ValueError("fixture change directory is missing or aliased")
    return directory


def retired_route_path_v1(repo_root, relative):
    """Retired 465-resume routes read the pre-fresh gate2_c bytes (design.md, fresh direct gate 2)."""
    if relative == "tests/fixtures/accepted_policy_fixture_compiler_gate2_c_v1.py":
        return change_directory_v1(repo_root) / "evidence/retired-development-tests-20261111" / (Path(relative).name + ".retired")
    return current_path_v1(repo_root, relative)


def current_path_v1(project_root: Path, relative: str) -> Path:
    """Open path for a recorded active-form relative path, which stays the identity (R1)."""
    active = "openspec/changes/" + CHANGE + "/"
    if not relative.startswith(active):
        return Path(project_root) / relative
    return change_directory_v1(project_root) / relative[len(active):]


def consumer_evidence_directory_v1(project_root: Path) -> Path:
    directory = change_directory_v1(project_root) / "evidence/consumer-01"
    if not directory.is_dir() or directory.resolve(strict=True) != directory:
        raise ValueError("fixture evidence directory is missing or aliased")
    return directory
