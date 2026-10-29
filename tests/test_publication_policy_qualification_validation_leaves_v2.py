from __future__ import annotations

import ast
import hashlib
import importlib
import inspect
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

TRANSACTION_BUILDER = "publication_policy_qualification_transaction_v2"
TRANSACTION_LEAF = "publication_policy_qualification_transaction_validation_v2"
FRAGMENT_BUILDER = "publication_policy_qualification_fragments_from_authority_v2"
FRAGMENT_LEAF = "publication_policy_qualification_fragment_validation_v2"

# Source bodies frozen from approved pre-extraction commit 299c9c0eefb83fe3031096b0e96527236678a4d2.
PREDICATE_LOCKS = {
    TRANSACTION_LEAF: (18, "848cfb033614e531c9133e2a847064de7881feeeda4d3ae0169b8c7265dbdb4e"),
    FRAGMENT_LEAF: (40, "dba29d7fd618f83a92e6b1b7742d8a84f13600a7539d106a6e5aa3b6a7cf46ea"),
}
HOST_MODULES = {
    TRANSACTION_BUILDER,
    FRAGMENT_BUILDER,
    "backend_publication_dispatch_v3",
    "checkpoint_deepstream_publication_runtime_v3",
    "checkpoint_gstreamer_publication_runtime_v3",
    "checkpoint_openvino_gva_publication_runtime_v3",
    "checkpoint_savant_publication_runtime_v3",
    "checkpoint_publication_launcher_adapter_v3",
    "checkpoint_publication_launcher_guard_v3",
    "production_arm_evidence_finalizer_v1",
    "publication_policy_qualification_pilot_executor_v2",
    "publication_policy_qualification_index_v2",
    "publication_policy_qualification_bootstrap_v2",
    "publication_policy_qualification_execution_code_closure_v1",
    "full_resource_qualification",
    "full_resource_qualification_index_v1",
    "publication_qualification_promotion_v2",
    "collect_metrics",
}


def definitions(module_name: str) -> tuple[str, list[ast.FunctionDef | ast.ClassDef]]:
    source = (SCRIPTS / f"{module_name}.py").read_text(encoding="utf-8")
    nodes = sorted(
        (
            node
            for node in ast.parse(source).body
            if isinstance(node, (ast.FunctionDef, ast.ClassDef))
        ),
        key=lambda node: node.name,
    )
    return source, nodes


class QualificationValidationLeafV2Tests(unittest.TestCase):
    def test_extracted_predicates_and_signatures_are_source_identical(self) -> None:
        for name, (count, expected) in PREDICATE_LOCKS.items():
            with self.subTest(module=name):
                source, nodes = definitions(name)
                lines = source.splitlines()
                bodies = [
                    "\n".join(
                        lines[
                            min([node.lineno] + [item.lineno for item in node.decorator_list]) - 1
                            : node.end_lineno
                        ]
                    )
                    for node in nodes
                ]
                self.assertEqual(len(nodes), count)
                self.assertEqual(hashlib.sha256("\n\n".join(bodies).encode()).hexdigest(), expected)

    def test_builders_reexport_the_original_shared_objects(self) -> None:
        for builder_name, leaf_name in (
            (TRANSACTION_BUILDER, TRANSACTION_LEAF),
            (FRAGMENT_BUILDER, FRAGMENT_LEAF),
        ):
            builder = importlib.import_module(builder_name)
            leaf = importlib.import_module(leaf_name)
            for node in definitions(leaf_name)[1]:
                with self.subTest(builder=builder_name, symbol=node.name):
                    self.assertIs(getattr(builder, node.name), getattr(leaf, node.name))
        builder = importlib.import_module(FRAGMENT_BUILDER)
        leaf = importlib.import_module(FRAGMENT_LEAF)
        self.assertIs(builder.DEFAULT_DEPENDENCIES, leaf.DEFAULT_DEPENDENCIES)
        for name in (
            "validate_publication_policy_qualification_fragments_from_authority_v2",
            "materialize_publication_policy_qualification_fragments_from_authority_v2",
        ):
            self.assertIs(
                inspect.signature(getattr(builder, name)).parameters["dependencies"].default,
                leaf.DEFAULT_DEPENDENCIES,
            )
        transaction = importlib.import_module(TRANSACTION_BUILDER)
        transaction_leaf = importlib.import_module(TRANSACTION_LEAF)
        self.assertIs(
            transaction.TransactionDependencies.__dataclass_fields__["load_identity_patch"].default,
            transaction_leaf._default_load_identity_patch,
        )
        self.assertIs(
            transaction.TransactionDependencies.__dataclass_fields__["load_parity_acceptance"].default,
            transaction_leaf._default_load_parity_acceptance,
        )

    def test_transaction_custody_and_error_are_not_duplicated(self) -> None:
        builder = importlib.import_module(TRANSACTION_BUILDER)
        leaf = importlib.import_module(TRANSACTION_LEAF)
        self.assertIs(builder._ACTIVE_CUSTODY, leaf._ACTIVE_CUSTODY)
        sentinel = object()
        token = builder._ACTIVE_CUSTODY.set(sentinel)
        try:
            self.assertIs(leaf._ACTIVE_CUSTODY.get(), sentinel)
        finally:
            builder._ACTIVE_CUSTODY.reset(token)
        self.assertIs(builder.QualificationTransactionV2Error, leaf.QualificationTransactionV2Error)
        self.assertIs(
            leaf.cold_validate_committed_transaction_v2,
            builder._cold_validate_committed_transaction,
        )

    def test_transaction_cold_output_and_refusals_remain_exact(self) -> None:
        leaf = importlib.import_module(TRANSACTION_LEAF)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            payload = root / "payload.json"
            payload.write_bytes(b"{}\n")
            descriptor = leaf.file_descriptor(root, payload)
            receipt = {
                "schema_version": leaf.SCHEMA_VERSION,
                "artifact_kind": leaf.TRANSACTION_KIND,
                **{
                    field: dict(descriptor)
                    for field in (
                        "hardware_resource_collector",
                        "image_identity_patch",
                        "accepted_model_parity_manifest",
                        "accepted_model_parity_assessment",
                        "accepted_model_parity_receipt",
                    )
                },
                "fragments": {system: dict(descriptor) for system in leaf.SYSTEMS},
                "candidate": {field: dict(descriptor) for field in ("index", "manifest", "receipt")},
                "bootstrap": {
                    "mapping": dict(descriptor),
                    "calibrations": {system: dict(descriptor) for system in leaf.SYSTEMS},
                    "receipt": dict(descriptor),
                },
            }
            receipt_path = root / leaf.TRANSACTION_RECEIPT_FILENAME

            def save() -> None:
                receipt["receipt_sha256"] = leaf._self_sha(receipt, "receipt_sha256")
                receipt_path.write_bytes(leaf._canonical(receipt))

            save()
            self.assertIsNone(leaf.cold_validate_committed_transaction_v2(root=root, receipt_path=receipt_path))
            payload.write_bytes(b"tampered\n")
            with self.assertRaisesRegex(
                leaf.QualificationTransactionV2Error,
                "^transaction receipt descriptor drifted: hardware_resource_collector$",
            ):
                leaf.cold_validate_committed_transaction_v2(root=root, receipt_path=receipt_path)
            payload.write_bytes(b"{}\n")
            del receipt["fragments"]["savant"]
            save()
            with self.assertRaisesRegex(
                leaf.QualificationTransactionV2Error,
                "^transaction receipt fragment coverage drifted$",
            ):
                leaf.cold_validate_committed_transaction_v2(root=root, receipt_path=receipt_path)
            receipt_path.write_text(json.dumps(receipt), encoding="ascii")
            with self.assertRaisesRegex(
                leaf.QualificationTransactionV2Error,
                "^cold transaction receipt is not canonical JSON$",
            ):
                leaf.cold_validate_committed_transaction_v2(root=root, receipt_path=receipt_path)

    def test_leaf_import_graph_never_reaches_host_or_builders(self) -> None:
        for name in (TRANSACTION_LEAF, FRAGMENT_LEAF):
            seen: set[str] = set()
            pending = [name]
            while pending:
                current = pending.pop()
                if current in seen:
                    continue
                seen.add(current)
                source = SCRIPTS / f"{current}.py"
                for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
                    imports = (
                        [node.module]
                        if isinstance(node, ast.ImportFrom)
                        else [alias.name for alias in node.names]
                        if isinstance(node, ast.Import)
                        else []
                    )
                    for imported in imports:
                        if current == name and imported:
                            self.assertFalse(
                                imported.startswith("publication_guardian_")
                                or imported == "checkpoint_gstreamer_analytics_sidecar",
                                f"{name} directly imports guardian/sidecar: {imported}",
                            )
                        if imported and (SCRIPTS / f"{imported}.py").is_file():
                            pending.append(imported)
            self.assertFalse(seen & HOST_MODULES, f"{name} imports host modules: {seen & HOST_MODULES}")

    def test_cold_descriptor_reader_refuses_physical_aliases(self) -> None:
        leaf = importlib.import_module(TRANSACTION_LEAF)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            source = root / "source.json"
            source.write_bytes(b"{}\n")
            linked = root / "linked.json"
            os.link(source, linked)
            with self.assertRaisesRegex(leaf.QualificationTransactionV2Error, "one canonical physical file"):
                leaf.file_descriptor(root, linked)
            linked.unlink()
            linked.symlink_to(source)
            with self.assertRaisesRegex(leaf.QualificationTransactionV2Error, "one canonical physical file"):
                leaf.file_descriptor(root, linked)

    def test_transaction_reader_uses_shared_custody_when_held(self) -> None:
        builder = importlib.import_module(TRANSACTION_BUILDER)
        leaf = importlib.import_module(TRANSACTION_LEAF)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            custody = mock.Mock()
            custody.root = root
            descriptor = {"path": "held.json", "size_bytes": 3, "sha256": hashlib.sha256(b"{}\n").hexdigest()}
            custody.read_descriptor_identity.return_value = (descriptor, b"{}\n", object())
            token = builder._ACTIVE_CUSTODY.set(custody)
            try:
                self.assertEqual(leaf._read_json(root, "held.json", label="held input"), (root / "held.json", {}))
                custody.read_descriptor_identity.assert_called_with(
                    "held.json", label="held input", maximum=1024 * 1024 * 1024, capture=True,
                )
                self.assertEqual(leaf.file_descriptor(root, "held.json"), descriptor)
                custody.read_descriptor_identity.assert_called_with(
                    "held.json", label="descriptor input", maximum=1024 * 1024 * 1024, capture=False,
                )
                custody.read_descriptor_identity.side_effect = leaf.PublicationPhysicalIoV1Error("changed")
                with self.assertRaisesRegex(leaf.QualificationTransactionV2Error, "physical custody failed: changed"):
                    leaf._read_json(root, "held.json", label="held input")
            finally:
                builder._ACTIVE_CUSTODY.reset(token)
            self.assertIsNone(leaf._ACTIVE_CUSTODY.get())

    def test_standalone_and_both_import_orders_in_fresh_interpreters(self) -> None:
        for builder, leaf in (
            (TRANSACTION_BUILDER, TRANSACTION_LEAF),
            (FRAGMENT_BUILDER, FRAGMENT_LEAF),
        ):
            for order in ((leaf,), (leaf, builder), (builder, leaf)):
                with self.subTest(order=order):
                    code = (
                        "import importlib,sys; "
                        f"sys.path.insert(0,{str(SCRIPTS)!r}); "
                        f"modules=[importlib.import_module(name) for name in {order!r}]; "
                    )
                    if len(order) == 1:
                        code += f"assert not set(sys.modules).intersection({HOST_MODULES!r})"
                    else:
                        names = [node.name for node in definitions(leaf)[1]]
                        code += (
                            f"a=importlib.import_module({builder!r}); "
                            f"b=importlib.import_module({leaf!r}); "
                            f"assert all(getattr(a,n) is getattr(b,n) for n in {names!r})"
                        )
                    result = subprocess.run(
                        [sys.executable, "-B", "-c", code],
                        cwd=ROOT,
                        capture_output=True,
                        text=True,
                        timeout=60,
                        check=False,
                    )
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
