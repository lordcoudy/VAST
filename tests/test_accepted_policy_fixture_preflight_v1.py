"""Controlled authority/source/cleanup edges; never compiler qualification."""
from contextlib import contextmanager
from pathlib import Path
import os
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from tests import test_accepted_policy_fixture_compiler_owner_v1 as owner_cases
from tests.fixtures import accepted_policy_fixture_compiler_v1 as compiler
from tests.fixtures import accepted_policy_fixture_compiler_admission_v1 as admission
from tests.fixtures import accepted_policy_original_custody_fixture_v1 as original
from tests.fixtures import accepted_policy_physical_fixture_v1 as physical_v1
from tests.fixtures import accepted_policy_physical_fixture_v2 as physical_v2


@contextmanager
def authority_case(module):
    case = owner_cases.OwnerTests("runTest")
    case.setUp()
    try:
        case.effects()
        output = case.root / "fixture"
        engine_output = output if module is original else output / "command-boundary"
        raw = compiler.build_fixture_source_v1(original.ENGINE_SOURCE, engine_output / "mutable/state", {}, {})
        case.admit["source"] = {"relative_path": str((engine_output / "immutable/engine.c").relative_to(case.root)),
            "size_bytes": len(raw), "sha256": owner_cases.digest(raw)}
        case.admit["executable_relative"] = str((engine_output / "immutable/engine").relative_to(case.root))
        arguments = dict(project_root=case.root, output_dir=output, image_inspections={}, device_probes={},
            compiler_qualification=case.qualification, compiler_absolute_deadline_ns=case.now[0] + 150_000_000_000)
        if module is not original:
            arguments.update(identity_patch_path=case.root / "unused-patch",
                accepted_model_parity_manifest_path=case.root / "unused-manifest",
                accepted_model_parity_assessment_path=case.root / "unused-assessment",
                accepted_model_parity_receipt_path=case.root / "unused-receipt")
        yield case, output, arguments
    finally:
        case.doCleanups()


class FixturePreflightTests(unittest.TestCase):
    def test_expired_foreign_root_and_foreign_source_refuse_at_all_three_entrypoints(self):
        for module in (original, physical_v1, physical_v2):
            for failure, code in (("expired", "owner_physical_admission"),
                                  ("root", "owner_admission_schema"), ("source", "owner_source_binding")):
                with self.subTest(module=module.__name__, failure=failure), authority_case(module) as (case, output, arguments):
                    if failure == "expired":
                        case.admit["expires_unix_ns"] = time.time_ns() - 1
                    elif failure == "root":
                        case.admit["project_root"] = str(case.root / "foreign")
                    else:
                        case.admit["source"]["sha256"] = "0" * 64
                    arguments["compiler_admission"] = case.seal("admission.json", case.admit)
                    prepare = (original.prepare_original_fixture_engine_v1 if module is original else
                               getattr(module, "prepared_complete_fixture_inputs_" + ("v1" if module is physical_v1 else "v2")))
                    with patch.object(compiler, "_DockerClientV1", side_effect=AssertionError("unadmitted API")), \
                            patch.object(original.socket, "socket", side_effect=AssertionError("unadmitted socket")):
                        with self.assertRaisesRegex(compiler.FixtureCompilerError, code):
                            with prepare(**arguments):
                                self.fail("invalid authority yielded")
                    self.assertFalse(output.exists())
                    self.assertEqual(case.clients, [])

    def test_valid_preflight_binds_prospective_state_and_source_without_writing(self):
        with authority_case(original) as (case, output, arguments):
            arguments["compiler_admission"] = case.seal("admission.json", case.admit)
            raw = original.preflight_original_fixture_engine_v1(**arguments)
            self.assertEqual(owner_cases.digest(raw), case.admit["source"]["sha256"])
            self.assertIn(str(output / "mutable/state").encode("ascii"), raw)
            self.assertFalse(output.exists())
            self.assertEqual(case.clients, [])

    def test_enclosing_clock_cannot_supply_a_fresh_window_longer_than_150_seconds(self):
        with patch.object(admission.time, "monotonic_ns", return_value=100):
            with self.assertRaisesRegex(compiler.FixtureCompilerError, "owner_preparation_deadline"):
                admission._compiler_preparation_clock_v1(150_000_000_101)
            self.assertEqual(admission._compiler_preparation_clock_v1(150_000_000_100), 100)

    def test_reply_string_and_table_overflow_refuse_before_output(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name).resolve()
            for replies in ({"image": {"oversized": "x" * (compiler.STRING_LIMIT + 1)}},
                            {str(number): {} for number in range(compiler.TABLE_LIMIT + 1)}):
                with self.subTest(entries=len(replies)):
                    with patch.object(admission, "preflight_fixture_engine_v1", side_effect=AssertionError("oversized source passed builder")):
                        with self.assertRaises(ValueError):
                            original.preflight_original_fixture_engine_v1(project_root=root, output_dir=root / "absent",
                                image_inspections=replies, device_probes={}, compiler_qualification={}, compiler_admission={},
                                compiler_absolute_deadline_ns=time.monotonic_ns() + 150_000_000_000)
                    self.assertFalse((root / "absent").exists())

    def test_source_write_or_flush_failure_preserves_distinct_close_cause(self):
        for stage in ("write", "flush"):
            closed = []
            class File:
                def write(self, raw):
                    if stage == "write":
                        raise OSError("controlled primary")
                    return len(raw)
                def flush(self):
                    raise OSError("controlled primary")
                def close(self):
                    closed.append(True)
                    raise ValueError("controlled secondary")
            with self.subTest(stage=stage), patch.object(Path, "open", return_value=File()), \
                    patch.object(original.os, "fsync", side_effect=AssertionError("failed stream reached fsync")):
                with self.assertRaises(compiler.FixtureCompilerError) as observed:
                    original._write_fixture_source_v1(Path("unused"), b"bounded", time.monotonic_ns() + 150_000_000_000)
            self.assertEqual(observed.exception.causes, ["fixture_source_OSError", "fixture_source_close_ValueError"])
            self.assertEqual(closed, [True])

    def test_deadline_after_flush_preserves_primary_and_close_cause(self):
        clock, closed = [1], []
        class File:
            def write(self, raw): return len(raw)
            def flush(self): clock[0] = 150_000_000_001
            def close(self):
                closed.append(True)
                raise ValueError("controlled close")
        with patch.object(Path, "open", return_value=File()), \
                patch.object(admission.time, "monotonic_ns", side_effect=lambda: clock[0]), \
                patch.object(original.os, "fsync", side_effect=AssertionError("expired source reached fsync")):
            with self.assertRaises(compiler.FixtureCompilerError) as observed:
                original._write_fixture_source_v1(Path("unused"), b"bounded", 150_000_000_001)
        self.assertEqual(observed.exception.causes, ["owner_preparation_deadline", "fixture_source_close_ValueError"])
        self.assertEqual(closed, [True])

    def test_compiler_refusal_opens_no_elf_or_socket_and_has_no_fallback(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name).resolve()
            authority = dict(compiler_qualification={}, compiler_admission={},
                             compiler_absolute_deadline_ns=time.monotonic_ns() + 150_000_000_000)
            with patch.object(admission, "preflight_fixture_engine_v1"), \
                    patch.object(admission, "compile_admitted_fixture_engine_v1", side_effect=compiler.FixtureCompilerError("controlled_compile_failure")) as compile_call, \
                    patch.object(original.socket, "socket", side_effect=AssertionError("refused compiler opened socket")):
                with self.assertRaisesRegex(compiler.FixtureCompilerError, "controlled_compile_failure"):
                    with original.prepare_original_fixture_engine_v1(project_root=root, output_dir=root / "fixture", **authority):
                        self.fail("refused compiler yielded")
                self.assertEqual(compile_call.call_count, 1)
                self.assertIs(compile_call.call_args.kwargs["qualification"], authority["compiler_qualification"])
                self.assertIs(compile_call.call_args.kwargs["admission"], authority["compiler_admission"])
                self.assertEqual(compile_call.call_args.kwargs["absolute_deadline_ns"], authority["compiler_absolute_deadline_ns"])
            self.assertFalse((root / "fixture/immutable/engine").exists())

    def test_socket_and_elf_cleanup_both_run_without_replacing_consumer_failure(self):
        with tempfile.TemporaryDirectory() as name:
            root, events = Path(name).resolve(), []
            primary = ValueError("controlled initiating consumer failure")
            actual_close = os.close
            class Socket:
                def bind(self, path): Path(path).write_bytes(b"controlled socket marker, never transport")
                def close(self):
                    events.append("socket-close")
                    raise OSError("controlled socket close")
            def close_fd(fd):
                actual_close(fd)
                events.append("elf-close")
                raise OSError("controlled ELF close report")
            def compile_spy(**kwargs):
                Path(kwargs["executable_path"]).write_bytes(b"controlled held bytes, never executed")
                return dict(accepted=True, normal_closed=True, receipt_persisted=True)
            with patch.object(admission, "preflight_fixture_engine_v1"), \
                    patch.object(admission, "compile_admitted_fixture_engine_v1", side_effect=compile_spy), \
                    patch.object(original.socket, "socket", return_value=Socket()), \
                    patch.object(original.os, "close", side_effect=close_fd):
                with self.assertRaises(ValueError) as observed:
                    with original.prepare_original_fixture_engine_v1(project_root=root, output_dir=root / "fixture",
                            compiler_qualification={}, compiler_admission={},
                            compiler_absolute_deadline_ns=time.monotonic_ns() + 150_000_000_000):
                        raise primary
            self.assertIs(observed.exception, primary)
            self.assertEqual(events, ["socket-close", "elf-close"])
            self.assertEqual(primary.fixture_cleanup_causes, ("fixture_socket_close_OSError", "fixture_elf_close_OSError"))


if __name__ == "__main__":
    unittest.main()
