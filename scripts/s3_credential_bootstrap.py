#!/usr/bin/env python3
"""Import an ACL-verified Windows profile over stdin into a private WSL file."""
from __future__ import annotations
import configparser
import json
import os
from pathlib import Path
import pwd
import stat
import sys
import tempfile


def main():
    try:
        if sys.argv[1:] != ['--acl-verified-stdin'] or os.name != 'posix' or os.getuid() != 1000:
            raise ValueError
        raw = sys.stdin.buffer.read(65537)
        if len(raw) > 65536:
            raise ValueError
        parser = configparser.ConfigParser(interpolation=None, strict=True)
        parser.read_string(raw.decode('utf-8-sig'))
        section = parser['vast-s3']
        fields = {'aws_access_key_id','aws_secret_access_key'}
        if parser.defaults() or set(section) not in (fields, fields|{'aws_session_token'}) or section['aws_access_key_id'] != 'vast':
            raise ValueError
        if any(not v or len(v)>4096 or any(ord(c)<33 or ord(c)>126 for c in v) for v in section.values()):
            raise ValueError
        selected = configparser.ConfigParser(interpolation=None)
        selected['vast-s3'] = dict(section)
        root = Path(pwd.getpwuid(1000).pw_dir)/'.config/vast/s3'
        root.mkdir(parents=True, mode=0o700, exist_ok=True)
        if root.resolve(strict=True) != root or root.stat().st_uid != 1000:
            raise ValueError
        root.chmod(0o700)
        target = root/'credentials.ini'
        if os.path.lexists(target):
            before = target.lstat()
            if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_uid != 1000
                    or stat.S_IMODE(before.st_mode) != 0o600):
                raise ValueError
        fd, staging = tempfile.mkstemp(prefix='.credential-import-',dir=root)
        try:
            with os.fdopen(fd,'w',encoding='utf-8') as output:
                os.fchmod(output.fileno(),0o600)
                selected.write(output)
                output.flush()
                os.fsync(output.fileno())
            os.replace(staging,target)
            directory = os.open(root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if os.path.exists(staging):
                os.unlink(staging)
        print(json.dumps({'status':'private_profile_imported','path':str(target),'profile':'vast-s3',
                          'principal':'vast','user_uid':1000,'directory_mode':'0700','file_mode':'0600'}))
        return 0
    except Exception:
        print(json.dumps({'status':'blocked','reason':'credential bootstrap source, ownership or custody is invalid'}))
        return 78


if __name__ == '__main__':
    raise SystemExit(main())
