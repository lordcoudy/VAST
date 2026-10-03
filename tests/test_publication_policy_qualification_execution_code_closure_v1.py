#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import publication_policy_qualification_execution_code_closure_v1 as target  # noqa: E402


def canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("ascii")


class QualificationExecutionCodeClosureV1Tests(unittest.TestCase):
    def _seed_tree(self, root: Path) -> None:
        scripts = root / "scripts"
        scripts.mkdir()
        for module in target.SEED_MODULES:
            path = scripts / f"{module}.py"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("from __future__ import annotations\n", encoding="utf-8")
        (scripts / "publication_policy_qualification_pilot_executor_v2.py").write_text(
            "from __future__ import annotations\n"
            "import closure_alpha\n"
            "import collect_metrics\n"
            "import publication_physical_io_v1\n"
            "def late():\n"
            "    from closure_beta import VALUE\n"
            "    return VALUE\n",
            encoding="utf-8",
        )
        (scripts / "closure_alpha.py").write_text(
            "from closure_gamma import VALUE\n", encoding="utf-8"
        )
        (scripts / "closure_beta.py").write_text("VALUE = 2\n", encoding="utf-8")
        (scripts / "closure_gamma.py").write_text("VALUE = 3\n", encoding="utf-8")
        (scripts / "collect_metrics.py").write_text("VALUE = 4\n", encoding="utf-8")
        (scripts / "publication_physical_io_v1.py").write_text(
            "VALUE = 5\n", encoding="utf-8"
        )

    def test_builder_recursively_freezes_exact_project_sources_and_interpreter(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            self._seed_tree(root)
            receipt_path = root / "authority/execution-code-closure.v1.json"

            built = target.materialize_execution_code_closure_v1(
                project_root=root,
                receipt_path=receipt_path,
            )

            receipt = built["receipt"]
            paths = [item["path"] for item in receipt["project_sources"]]
            self.assertEqual(paths, sorted(paths))
            self.assertEqual(
                set(paths),
                {
                    *(f"scripts/{module}.py" for module in target.SEED_MODULES),
                    "scripts/closure_alpha.py",
                    "scripts/closure_beta.py",
                    "scripts/closure_gamma.py",
                    "scripts/collect_metrics.py",
                    "scripts/publication_physical_io_v1.py",
                },
            )
            self.assertEqual(receipt["seeds"], list(target.SEED_MODULES))
            self.assertTrue(Path(receipt["interpreter"]["path"]).is_absolute())
            self.assertEqual(
                receipt["interpreter"]["sha256"],
                hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest(),
            )
            self.assertEqual(
                receipt["receipt_sha256"],
                target.semantic_sha256_v1(
                    {
                        key: value
                        for key, value in receipt.items()
                        if key != "receipt_sha256"
                    }
                ),
            )
            loaded = target.load_execution_code_closure_v1(
                project_root=root,
                receipt_path=receipt_path,
            )
            self.assertEqual(loaded["receipt"], receipt)
            self.assertEqual(receipt_path.read_bytes(), canonical_bytes(receipt))

    def test_loader_rejects_mutate_restore_snapshot_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            self._seed_tree(root)
            receipt_path = root / "authority/execution-code-closure.v1.json"
            target.materialize_execution_code_closure_v1(
                project_root=root,
                receipt_path=receipt_path,
            )
            source = root / "scripts/closure_beta.py"
            original = source.read_bytes()
            source.write_bytes(b"VALUE = 999\n")
            source.write_bytes(original)

            with self.assertRaisesRegex(
                target.ExecutionCodeClosureV1Error,
                "physical snapshot drifted",
            ):
                target.load_execution_code_closure_v1(
                    project_root=root,
                    receipt_path=receipt_path,
                )

    def test_loaded_project_module_escape_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            self._seed_tree(root)
            receipt_path = root / "authority/execution-code-closure.v1.json"
            receipt = target.materialize_execution_code_closure_v1(
                project_root=root,
                receipt_path=receipt_path,
            )["receipt"]
            escaped = root / "scripts/not_in_closure.py"
            escaped.write_text("VALUE = 1\n", encoding="utf-8")
            module = types.ModuleType("not_in_closure")
            module.__file__ = str(escaped)
            sys.modules[module.__name__] = module
            try:
                with self.assertRaisesRegex(
                    target.ExecutionCodeClosureV1Error,
                    "loaded project module escaped execution code closure",
                ):
                    target.assert_loaded_project_modules_covered_v1(
                        project_root=root,
                        receipt=receipt,
                    )
            finally:
                sys.modules.pop(module.__name__, None)


if __name__ == "__main__":
    unittest.main()
