"""Exact, nonsecret destination contract for new VAST S3 exports."""
from __future__ import annotations

from dataclasses import dataclass, asdict
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from types import MappingProxyType
from typing import Any

import yaml


class S3ConfigurationError(RuntimeError):
    """Permanent configuration rejection; messages never include input values."""


_EXPECTED = MappingProxyType({
    "artifact_kind": "vast_s3_destination_v1",
    "backend": "s3",
    "endpoint": "https://s3.savva-balashov.me",
    "bucket": "vast-archive",
    "prefix": "vast/",
    "region": "us-east-1",
    "addressing_style": "path",
    "credential_profile": "vast-s3",
})


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("utf-8")


class _UniqueLoader(yaml.SafeLoader):
    pass


def _mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if type(key) is not str or key in result:
            raise S3ConfigurationError("S3 descriptor contains invalid or duplicate keys")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def read_physical_bytes(path: Path, *, maximum: int = 65536) -> bytes:
    lexical = Path(os.path.abspath(os.fspath(path)))
    descriptor = -1
    try:
        if lexical.parent.resolve(strict=True) != lexical.parent:
            raise S3ConfigurationError("S3 descriptor parent is redirected")
        named = lexical.lstat()
        if not stat.S_ISREG(named.st_mode) or named.st_nlink != 1 or named.st_size > maximum:
            raise S3ConfigurationError("S3 descriptor must be one bounded physical file")
        descriptor = os.open(lexical, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                             | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0))
        opened = os.fstat(descriptor)
        snapshot = lambda s: (s.st_dev, s.st_ino, s.st_mode, s.st_nlink, s.st_size,
                              s.st_mtime_ns, s.st_ctime_ns)
        if snapshot(named) != snapshot(opened):
            raise S3ConfigurationError("S3 descriptor changed while opening")
        pieces = []
        length = 0
        while True:
            piece = os.read(descriptor, min(8192, maximum + 1 - length))
            if not piece:
                break
            pieces.append(piece)
            length += len(piece)
            if length > maximum:
                raise S3ConfigurationError("S3 descriptor exceeded its bound")
        if (length != opened.st_size or snapshot(os.fstat(descriptor)) != snapshot(opened)
                or snapshot(lexical.lstat()) != snapshot(opened)
                or lexical.parent.resolve(strict=True) != lexical.parent):
            raise S3ConfigurationError("S3 descriptor changed while reading")
        return b"".join(pieces)
    except S3ConfigurationError:
        raise
    except Exception:
        raise S3ConfigurationError("S3 descriptor is unavailable or unsafe") from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)


@dataclass(frozen=True, slots=True)
class S3Destination:
    artifact_kind: str
    backend: str
    endpoint: str
    bucket: str
    prefix: str
    region: str
    addressing_style: str
    credential_profile: str

    def __post_init__(self):
        if any(type(getattr(self, key)) is not str or getattr(self, key) != expected
               for key, expected in _EXPECTED.items()):
            raise S3ConfigurationError("S3 descriptor does not match the selected destination")

    @classmethod
    def from_mapping(cls, value: Any) -> "S3Destination":
        if type(value) is not dict or set(value) != set(_EXPECTED):
            raise S3ConfigurationError("S3 descriptor has invalid fields")
        return cls(**value)

    @classmethod
    def from_file(cls, path: Path | str) -> "S3Destination":
        try:
            return cls.from_mapping(yaml.load(read_physical_bytes(Path(path)).decode("utf-8"),
                                              Loader=_UniqueLoader))
        except S3ConfigurationError:
            raise
        except Exception:
            raise S3ConfigurationError("S3 descriptor is invalid") from None

    @property
    def identity(self) -> dict[str, Any]:
        material = {key: value for key, value in asdict(self).items()
                    if key not in {"artifact_kind", "credential_profile"}}
        material["signature_version"] = "s3v4"
        return {"schema_version": 1, **material,
                "destination_sha256": hashlib.sha256(canonical_bytes(material)).hexdigest()}

    def run_prefix(self, matrix_sha256: str, run_id: str) -> str:
        if (type(matrix_sha256) is not str or re.fullmatch(r"[0-9a-f]{64}", matrix_sha256) is None
                or type(run_id) is not str
                or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", run_id) is None
                or run_id in {".", ".."}):
            raise S3ConfigurationError("S3 run namespace identity is invalid")
        return self.prefix + matrix_sha256 + "/" + run_id + "/"

    def object_key(self, matrix_sha256: str, run_id: str, remote_name: str) -> str:
        validate_remote_name(remote_name)
        return self.run_prefix(matrix_sha256, run_id) + remote_name


def validate_remote_name(name: str) -> None:
    if (type(name) is not str or name in {".", ".."}
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,254}", name) is None):
        raise S3ConfigurationError("S3 object name is invalid")
