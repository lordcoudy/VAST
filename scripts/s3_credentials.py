"""Resolve one explicit external profile; never consult ambient AWS credentials."""
from __future__ import annotations

import configparser
from dataclasses import dataclass, field
import os
from pathlib import Path
import stat

from artifact_store import ArtifactPermanentError
from s3_destination import read_physical_bytes, S3ConfigurationError


@dataclass(frozen=True, slots=True)
class S3Credentials:
    access_key: str = field(repr=False)
    secret_key: str = field(repr=False)
    token: str | None = field(default=None, repr=False)


def default_credentials_path() -> Path:
    if os.name == 'posix':
        import pwd
        return Path(pwd.getpwuid(os.getuid()).pw_dir) / '.config/vast/s3/credentials.ini'
    return Path.home() / '.aws/credentials'


def resolve_credentials(path: Path | str, *, profile: str = 'vast-s3') -> S3Credentials:
    """Physical private POSIX file, or operator ACL-verified Windows source.

    The production service runs under Linux. Windows import is deliberately
    performed by the bounded setup command after inspecting its ACL.
    """
    try:
        lexical = Path(os.path.abspath(os.fspath(path)))
        if profile != 'vast-s3' or os.name != 'posix':
            raise ArtifactPermanentError('S3 profile requires the private WSL credential source')
        directory, leaf = lexical.parent.lstat(), lexical.lstat()
        if (lexical.resolve(strict=True) != lexical or not stat.S_ISDIR(directory.st_mode)
                or directory.st_uid != os.getuid() or stat.S_IMODE(directory.st_mode) != 0o700
                or leaf.st_uid != os.getuid() or stat.S_IMODE(leaf.st_mode) != 0o600):
            raise ArtifactPermanentError('S3 profile ownership or permissions are unsafe')
        raw = read_physical_bytes(lexical, maximum=65536).decode('utf-8')
        parser = configparser.ConfigParser(interpolation=None, strict=True)
        parser.read_string(raw)
        if parser.defaults() or profile not in parser or set(parser[profile]) not in (
                {'aws_access_key_id', 'aws_secret_access_key'},
                {'aws_access_key_id', 'aws_secret_access_key', 'aws_session_token'}):
            raise ArtifactPermanentError('S3 selected profile has invalid fields')
        section = parser[profile]
        values = [section['aws_access_key_id'], section['aws_secret_access_key']]
        token = section.get('aws_session_token')
        if values[0] != 'vast' or any(not v or len(v) > 4096 or any(ord(c) < 33 or ord(c) > 126 for c in v)
                                     for v in values + ([token] if token is not None else [])):
            raise ArtifactPermanentError('S3 selected principal or credential values are invalid')
        return S3Credentials(*values, token)
    except ArtifactPermanentError:
        raise
    except (S3ConfigurationError, Exception):
        raise ArtifactPermanentError('S3 explicit credential profile is unavailable or invalid') from None
