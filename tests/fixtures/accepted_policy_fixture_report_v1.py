"""Finite JSON geometry for the explicit fixture's reports, never a proof reducer.

Only exact JSON builtins and standard pathlib values are supported. Snapshot and
count the complete value before encoding, so a refused report opens no output
and an encoder never receives an unbounded or user-defined value.
"""
import json
import math
from pathlib import PosixPath, PurePosixPath, PureWindowsPath, WindowsPath


REPORT_LIMIT = 16 * 1024 * 1024
CONSUMER_LIMIT = 8 * 1024 * 1024
_PATH_TYPES = (PosixPath, WindowsPath, PurePosixPath, PureWindowsPath)


def fixture_report_bytes_v1(value, *, limit=REPORT_LIMIT):
    """Return unchanged compact ASCII JSON plus LF, or refuse before encoding.

    The bounded snapshot contains only exact builtins. Its strings are immutable
    and its containers are owned here, so later mutation of an input container
    cannot introduce a larger string or a callback during encoding.
    """
    if type(limit) is not int or not 1 <= limit <= REPORT_LIMIT:
        raise ValueError("fixture report byte limit is invalid")
    total, nodes, active = 1, 0, set()  # Include the final LF from the beginning.

    def add(count):
        nonlocal total
        if count > limit - total:
            raise ValueError("fixture report complete byte bound exceeded")
        total += count

    def string(text):
        if len(text) > 1048576:
            raise ValueError("fixture report string bound exceeded")
        add(2)
        for char in text:
            code = ord(char)
            if char in '\\"' or code in (8, 9, 10, 12, 13):
                add(2)
            elif code < 32 or code > 126:
                add(6 if code <= 65535 else 12)
            else:
                add(1)
        return text

    def snapshot(item, depth):
        nonlocal nodes
        nodes += 1
        if nodes > 65536 or depth > 32:
            raise ValueError("fixture report node/depth bound exceeded")
        kind = type(item)
        if item is None:
            add(4)
            return item
        if kind is bool:
            add(4 if item else 5)
            return item
        if kind is int:
            if not -(2**63) <= item < 2**63:
                raise ValueError("fixture report integer bound exceeded")
            add(len(str(item)))
            return item
        if kind is float:
            if not math.isfinite(item):
                raise ValueError("fixture report nonfinite float")
            add(len(repr(item)))  # Exact finite builtin float, not a callback.
            return item
        if kind is str:
            return string(item)
        if any(kind is supported for supported in _PATH_TYPES):
            parts = item.parts
            separators = max(0, len(parts) - 1 - bool(item.anchor))
            if len(parts) > 512 or sum(len(part) for part in parts) + separators > 512:
                raise ValueError("fixture report path bound exceeded")
            text = str(item)  # Exact supported stdlib type only.
            if len(text) > 512:
                raise ValueError("fixture report path bound exceeded")
            return string(text)
        if not (kind is dict or kind is list or kind is tuple):
            raise ValueError("fixture report unsupported value type")
        if len(item) > 4096:
            raise ValueError("fixture report container bound exceeded")
        identity = id(item)
        if identity in active:
            raise ValueError("fixture report cycle")
        active.add(identity)
        add(2)
        try:
            if kind is dict:
                copied = {}
                for index, (key, child) in enumerate(item.items()):
                    if index >= 4096 or type(key) is not str:
                        raise ValueError("fixture report key/container bound exceeded")
                    if index:
                        add(1)
                    copied_key = snapshot(key, depth + 1)
                    add(1)
                    copied[copied_key] = snapshot(child, depth + 1)
                return copied
            copied = []
            for index, child in enumerate(item):
                if index >= 4096:
                    raise ValueError("fixture report container bound exceeded")
                if index:
                    add(1)
                copied.append(snapshot(child, depth + 1))
            return copied
        except RuntimeError as error:
            raise ValueError("fixture report container changed during snapshot") from error
        finally:
            active.remove(identity)

    copied = snapshot(value, 0)
    raw = json.dumps(copied, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                     allow_nan=False).encode("ascii") + b"\n"
    if len(raw) != total or len(raw) > limit:
        raise ValueError("fixture report encoder geometry drift")
    return raw
