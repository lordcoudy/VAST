"""Static gate: Python sources packaged in runtime images stay Python 3.10.

DeepStream and Savant runtime images (and the TensorRT worker built on the
DeepStream base) run CPython 3.10.12, while host tests run on newer Python.
This gate scans every Python file named by the runtime and worker source
allowlists for APIs and grammar newer than Python 3.10.  The final grammar
check remains the in-image compilation (Amendment 6, D(a)).
"""

from __future__ import annotations

import ast
import builtins
import io
import tokenize
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MINIMUM_RUNTIME_PYTHON = (3, 10)
SOURCE_ALLOWLISTS = (
    "deploy/deepstream/checkpoint/runtime-source-allowlist.txt",
    "deploy/savant/publication/runtime-source-allowlist.txt",
    "deploy/openvino_gva/publication/runtime-source-allowlist.txt",
    "deploy/gstreamer_custom/publication/runtime-source-allowlist.txt",
    "deploy/analytics_execution/publication/openvino-source-allowlist.txt",
    "deploy/analytics_execution/publication/tensorrt-source-allowlist.txt",
)

# Qualified module attributes (or modules) added after Python 3.10.
NEWER_QUALIFIED_NAMES = frozenset({
    "asyncio.Barrier",
    "asyncio.Runner",
    "asyncio.TaskGroup",
    "asyncio.timeout",
    "asyncio.timeout_at",
    "collections.abc.Buffer",
    "contextlib.chdir",
    "datetime.UTC",
    "enum.EnumCheck",
    "enum.FlagBoundary",
    "enum.ReprEnum",
    "enum.StrEnum",
    "enum.global_enum",
    "enum.member",
    "enum.nonmember",
    "enum.verify",
    "hashlib.file_digest",
    "inspect.markcoroutinefunction",
    "itertools.batched",
    "logging.getLevelNamesMapping",
    "math.cbrt",
    "math.exp2",
    "math.sumprod",
    "operator.call",
    "os.path.isjunction",
    "os.path.splitroot",
    "pathlib.Path.walk",
    "pathlib.Path.is_junction",
    "re.NOFLAG",
    "sys.exception",
    "sys.monitoring",
    "tomllib",
    "types.get_original_bases",
    "typing.LiteralString",
    "typing.Never",
    "typing.NotRequired",
    "typing.Required",
    "typing.Self",
    "typing.TypeAliasType",
    "typing.TypeVarTuple",
    "typing.Unpack",
    "typing.assert_never",
    "typing.assert_type",
    "typing.clear_overloads",
    "typing.dataclass_transform",
    "typing.get_overloads",
    "typing.override",
    "typing.reveal_type",
    "wsgiref.types",
})
NEWER_BUILTINS = frozenset({"BaseExceptionGroup", "ExceptionGroup"})
# Exception-only method; an unguarded call raises AttributeError on 3.10.
NEWER_EXCEPTION_METHODS = frozenset({"add_note"})
# pathlib.Path methods, flagged only on receivers resolved to pathlib paths.
NEWER_PATH_METHODS = frozenset({"walk", "is_junction"})
PATHLIB_TYPES = frozenset({"pathlib.Path", "pathlib.PosixPath", "pathlib.WindowsPath"})
NEWER_KEYWORDS = frozenset({
    ("dataclasses.dataclass", "weakref_slot"),
    ("shutil.rmtree", "onexc"),
    ("tempfile.NamedTemporaryFile", "delete_on_close"),
    ("tempfile.TemporaryDirectory", "delete"),
})


def runtime_python_sources() -> tuple[Path, ...]:
    """Python files named by the runtime and worker image source allowlists."""

    names: set[str] = set()
    for allowlist in SOURCE_ALLOWLISTS:
        for line in (ROOT / allowlist).read_text(encoding="utf-8").splitlines():
            name = line.strip()
            if name and not name.startswith("#"):
                names.add(name)
    sources = []
    for name in sorted(names):
        path = ROOT / name
        if name.endswith(".py"):
            sources.append(path)
        elif path.is_file():
            with path.open("rb") as handle:
                first = handle.readline()
            if first.startswith(b"#!") and b"python" in first:
                sources.append(path)
    return tuple(sources)


def _quote(token: str) -> str:
    body = token.lstrip("rRbBfFuU")
    return body[:3] if body[:3] in ('"""', "'''") else body[:1]


def post_310_fstring_findings(source: str) -> list[str]:
    """PEP 701 forms that ``ast.parse(feature_version=(3, 10))`` accepts."""

    fstring_start = getattr(tokenize, "FSTRING_START", None)
    if fstring_start is None:
        # Older tokenizers reject these forms during ast.parse already.
        return []
    findings = []
    open_quotes: list[str] = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        line = token.start[0]
        if token.type == tokenize.FSTRING_END:
            open_quotes.pop()
            continue
        if open_quotes:
            if token.type == tokenize.FSTRING_MIDDLE:
                if len(open_quotes) > 1 and "\\" in token.string:
                    findings.append(f"{line}: backslash inside an f-string expression")
            elif token.type in (tokenize.STRING, fstring_start):
                quote = _quote(token.string)
                if any(quote.startswith(outer) for outer in open_quotes):
                    findings.append(f"{line}: nested string reuses the enclosing f-string quote")
                if token.type == tokenize.STRING and "\\" in token.string:
                    findings.append(f"{line}: backslash inside an f-string expression")
            elif token.type == tokenize.COMMENT:
                findings.append(f"{line}: comment inside an f-string expression")
        if token.type == fstring_start:
            open_quotes.append(_quote(token.string))
    return findings


def post_310_syntax_findings(source: str) -> list[str]:
    """Explicit checks for grammar newer than Python 3.10."""

    findings = []
    try:
        ast.parse(source, feature_version=MINIMUM_RUNTIME_PYTHON)
    except SyntaxError as error:
        findings.append(f"{error.lineno}: not Python 3.10 grammar: {error.msg}")
    tree = ast.parse(source)
    try_star = getattr(ast, "TryStar", None)
    type_alias = getattr(ast, "TypeAlias", None)
    for node in ast.walk(tree):
        line = getattr(node, "lineno", 0)
        if try_star is not None and isinstance(node, try_star):
            findings.append(f"{line}: except* (PEP 654)")
        if type_alias is not None and isinstance(node, type_alias):
            findings.append(f"{line}: type alias statement (PEP 695)")
        if getattr(node, "type_params", None):
            findings.append(f"{line}: generic type parameters (PEP 695)")
        if isinstance(node, ast.Subscript):
            elements = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
            segment = ast.get_source_segment(source, node.slice) or ""
            if any(isinstance(item, ast.Starred) for item in elements) and not segment.startswith("("):
                findings.append(f"{line}: starred subscript (PEP 646)")
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            vararg = node.args.vararg
            if vararg is not None and isinstance(vararg.annotation, ast.Starred):
                findings.append(f"{line}: starred *args annotation (PEP 646)")
    findings.extend(post_310_fstring_findings(source))
    return findings


def _import_aliases(tree: ast.AST) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    aliases[alias.asname] = alias.name
                else:
                    top = alias.name.split(".", 1)[0]
                    aliases[top] = top
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            for alias in node.names:
                if alias.name != "*":
                    aliases[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    return aliases


def _locally_bound(tree: ast.AST) -> set[str]:
    bound: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and not isinstance(node.ctx, ast.Load):
            bound.add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(node.name)
        elif isinstance(node, ast.arg):
            bound.add(node.arg)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bound.add(node.name)
    return bound


def _is_newer(qualified: str) -> bool:
    parts = qualified.split(".")
    return any(".".join(parts[:index]) in NEWER_QUALIFIED_NAMES for index in range(1, len(parts) + 1))


def post_310_api_findings(source: str) -> list[str]:
    """Python 3.11+ APIs, matched through resolved import names."""

    tree = ast.parse(source)
    aliases = _import_aliases(tree)
    bound = _locally_bound(tree) - set(aliases)

    def resolve(node: ast.AST) -> str | None:
        if isinstance(node, ast.Name):
            if node.id in aliases:
                return aliases[node.id]
            if node.id not in bound and (hasattr(builtins, node.id) or node.id in NEWER_BUILTINS):
                return "builtins." + node.id
            return None
        if isinstance(node, ast.Attribute):
            base = resolve(node.value)
            return None if base is None else f"{base}.{node.attr}"
        return None

    def path_receiver(node: ast.AST) -> bool:
        if isinstance(node, ast.Call):
            node = node.func
        return resolve(node) in PATHLIB_TYPES

    findings = []
    for node in ast.walk(tree):
        line = getattr(node, "lineno", 0)
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_newer(alias.name):
                    findings.append(f"{line}: import {alias.name}")
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            for alias in node.names:
                if _is_newer(f"{node.module}.{alias.name}"):
                    findings.append(f"{line}: from {node.module} import {alias.name}")
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            if node.id in NEWER_BUILTINS and resolve(node) == "builtins." + node.id:
                findings.append(f"{line}: builtin {node.id}")
        elif isinstance(node, ast.Attribute):
            qualified = resolve(node)
            if qualified is not None and _is_newer(qualified):
                findings.append(f"{line}: {qualified}")
            elif node.attr in NEWER_EXCEPTION_METHODS:
                findings.append(f"{line}: unguarded .{node.attr}")
            elif node.attr in NEWER_PATH_METHODS and path_receiver(node.value):
                findings.append(f"{line}: pathlib.Path.{node.attr}")
        if isinstance(node, ast.Call):
            callee = resolve(node.func)
            if (
                callee == "builtins.getattr"
                and len(node.args) == 2
                and isinstance(node.args[1], ast.Constant)
                and isinstance(node.args[1].value, str)
            ):
                name = node.args[1].value
                base = resolve(node.args[0])
                if name in NEWER_EXCEPTION_METHODS or (base is not None and _is_newer(f"{base}.{name}")):
                    findings.append(f"{line}: unguarded getattr(..., {name!r})")
            for keyword in node.keywords:
                if (callee, keyword.arg) in NEWER_KEYWORDS:
                    findings.append(f"{line}: {callee}({keyword.arg}=...)")
    return findings


class RuntimeImagePython310CompatV1Tests(unittest.TestCase):
    maxDiff = None

    def test_allowlists_name_existing_python_sources(self) -> None:
        sources = runtime_python_sources()
        self.assertGreater(len(sources), 80)
        missing = [str(path.relative_to(ROOT)) for path in sources if not path.is_file()]
        self.assertEqual(missing, [])
        self.assertIn(ROOT / "scripts/checkpoint_runtime.py", sources)
        self.assertIn(ROOT / "deploy/analytics_execution/tensorrt_worker.py", sources)

    def test_runtime_sources_use_python_310_grammar(self) -> None:
        findings = []
        for path in runtime_python_sources():
            source = path.read_text(encoding="utf-8")
            findings.extend(
                f"{path.relative_to(ROOT).as_posix()}:{item}"
                for item in post_310_syntax_findings(source)
            )
        self.assertEqual(findings, [])

    def test_runtime_sources_avoid_post_310_apis(self) -> None:
        findings = []
        for path in runtime_python_sources():
            source = path.read_text(encoding="utf-8")
            findings.extend(
                f"{path.relative_to(ROOT).as_posix()}:{item}"
                for item in post_310_api_findings(source)
            )
        self.assertEqual(findings, [])

    def test_api_detector_resolves_aliases_and_keeps_guarded_forms(self) -> None:
        flagged = {
            "import sys\nsys.exception()\n": "sys.exception",
            "import sys as system\nsystem.exception()\n": "sys.exception",
            "from sys import exception\n": "from sys import exception",
            "from sys import exception as current\n": "from sys import exception",
            "import sys\ngetattr(sys, 'exception')()\n": "getattr(..., 'exception')",
            "error = ValueError()\nerror.add_note('n')\n": ".add_note",
            "error = ValueError()\ngetattr(error, 'add_note')('n')\n": "getattr(..., 'add_note')",
            "raise ExceptionGroup('x', [ValueError()])\n": "builtin ExceptionGroup",
            "isinstance(1, BaseExceptionGroup)\n": "builtin BaseExceptionGroup",
            "import tomllib\n": "import tomllib",
            "from tomllib import loads\n": "from tomllib import loads",
            "import datetime as dt\ndt.UTC\n": "datetime.UTC",
            "from datetime import UTC\n": "from datetime import UTC",
            "import enum\nenum.StrEnum\n": "enum.StrEnum",
            "import hashlib\nhashlib.file_digest\n": "hashlib.file_digest",
            "from typing import Self\n": "from typing import Self",
            "import typing as t\nt.assert_never\n": "typing.assert_never",
            "from typing import Never, override\n": "from typing import Never",
            "import asyncio\nasyncio.TaskGroup()\n": "asyncio.TaskGroup",
            "import asyncio\nasyncio.timeout(1)\n": "asyncio.timeout",
            "import contextlib\ncontextlib.chdir('.')\n": "contextlib.chdir",
            "import operator\noperator.call(print)\n": "operator.call",
            "from itertools import batched\n": "from itertools import batched",
            "import math\nmath.cbrt(8)\nmath.exp2(1)\n": "math.cbrt",
            "import os\nos.path.isjunction('.')\n": "os.path.isjunction",
            "import os.path as osp\nosp.isjunction('.')\n": "os.path.isjunction",
            "from pathlib import Path\nPath('.').walk()\n": "pathlib.Path.walk",
            "import shutil\nshutil.rmtree('x', onexc=print)\n": "shutil.rmtree(onexc=...)",
            "import tempfile\ntempfile.NamedTemporaryFile(delete_on_close=False)\n":
                "tempfile.NamedTemporaryFile(delete_on_close=...)",
        }
        for source, expected in flagged.items():
            with self.subTest(source=source):
                findings = post_310_api_findings(source)
                self.assertTrue(any(expected in item for item in findings), findings)
        clean = (
            "import socket\nsocket.timeout\n",
            "custody = object()\ncustody.verify()\n",
            "import enum\nclass E(enum.Enum):\n    A = 1\n",
            "import sys\nsys.exc_info()[1]\n",
            "import sys\ngetattr(sys, 'exception', None)\n",
            "error = ValueError()\nnote_adder = getattr(error, 'add_note', None)\n"
            "if callable(note_adder):\n    note_adder('n')\n"
            "else:\n    error.__notes__ = [*getattr(error, '__notes__', ()), 'n']\n",
            "import os\ngetattr(os.path, 'isjunction', lambda _path: False)\n",
            "import ast, os\nast.walk(ast.parse(''))\nos.walk('.')\n",
            "future = object()\nfuture.exception()\n",
            "import asyncio\nasyncio.wait_for(None, 1)\n",
            "class ExceptionGroup(Exception):\n    pass\nraise ExceptionGroup()\n",
            "import shutil\nshutil.rmtree('x', onerror=print)\n",
            "import tempfile\ntempfile.NamedTemporaryFile(delete=False)\n",
            "from typing import Any, Optional\n",
        )
        for source in clean:
            with self.subTest(source=source):
                self.assertEqual(post_310_api_findings(source), [])

    @unittest.skipUnless(hasattr(tokenize, "FSTRING_START"), "PEP 701 tokens need Python 3.12+")
    def test_syntax_detector_flags_post_310_grammar(self) -> None:
        flagged = (
            'x = {"a": 1}\nf"{x["a"]}"\n',
            "f'{f'{1}'}'\n",
            "f\"{'\\n'.join([])}\"\n",
            "a = [1]\nb = [0]\na[*b]\n",
            "def f(*args: *tuple[int, ...]):\n    pass\n",
            "try:\n    pass\nexcept* ValueError:\n    pass\n",
            "type Alias = int\n",
            "def f[T](value: T) -> T:\n    return value\n",
            "class C[T]:\n    pass\n",
        )
        for source in flagged:
            with self.subTest(source=source):
                self.assertNotEqual(post_310_syntax_findings(source), [])
        clean = (
            'x = {"a": 1}\nf"{x[\'a\']}"\n',
            'f"""{"nested"}"""\n',
            "f'{1:>{4}}' + f'{{literal}}\\n'\n",
            "a = {(1,): 0}\nb = [1]\na[(*b,)]\n",
            "a = [[0]]\na[0, ...] if False else a[0]\n",
            "def f(*args: int):\n    pass\n",
            "match 1:\n    case 1:\n        pass\n",
        )
        for source in clean:
            with self.subTest(source=source):
                self.assertEqual(post_310_syntax_findings(source), [])


if __name__ == "__main__":
    unittest.main()
