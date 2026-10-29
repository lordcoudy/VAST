"""Current gate controls around the exact frozen owner; no physical authority."""
from contextlib import contextmanager
from pathlib import Path
import hashlib
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from tests import test_accepted_policy_fixture_compiler_owner_v1 as owner_cases
from tests.fixtures import accepted_policy_fixture_compiler_admission_v1 as admission
from tests.fixtures import accepted_policy_fixture_compiler_v1 as executor


@contextmanager
def admitted_case():
    case = owner_cases.OwnerTests("runTest")
    case.setUp()
    try:
        case.effects()
        yield case
    finally:
        case.doCleanups()


def arguments(case):
    return dict(project_root=case.root, source_path=case.source,
        executable_path=case.executable, qualification=case.qualification,
        admission=case.admission, absolute_deadline_ns=case.now[0] + 150_000_000_000)


def prospective_arguments(case):
    raw = case.source.read_bytes()
    source, executable = case.root / "prospective/engine.c", case.root / "prospective/engine"
    case.admit["source"] = dict(relative_path=str(source.relative_to(case.root)), size_bytes=len(raw),
                                sha256=hashlib.sha256(raw).hexdigest())
    case.admit["executable_relative"] = str(executable.relative_to(case.root))
    case.admission = case.seal("admission.json", case.admit)
    return {**arguments(case), "source_path": source, "executable_path": executable}, raw


def write_after_preflight(kwargs, raw):
    result = admission.preflight_fixture_engine_v1(**kwargs, source_bytes=raw)
    if result is not None or kwargs["source_path"].parent.exists():
        raise AssertionError("preflight allocated or supplied acceptance")
    kwargs["source_path"].parent.mkdir()
    kwargs["source_path"].write_bytes(raw)


class FixtureCompilerAdmissionTests(unittest.TestCase):
    def test_frozen_executor_identity_and_component_entrypoint_are_preserved(self):
        raw = executor._compiler_read_v1(Path(executor.__file__).resolve(), 262144)
        self.assertEqual(len(raw), 103925)
        self.assertEqual(hashlib.sha256(raw).hexdigest(),
            "1e40d4786fd03543ac43df7fe0e42a4349d55bad9288ead28f5d2a6ad87bcb03")
        self.assertTrue(callable(executor.compile_fixture_engine_v1))
        self.assertTrue(callable(executor._compile_fixture_component_v1))
        self.assertFalse(hasattr(executor, "preflight_fixture_engine_v1"))
        self.assertFalse(hasattr(executor, "_compiler_preparation_clock_v1"))

    def test_preflight_allocates_nothing_and_hashes_executor_not_gate(self):
        with admitted_case() as case:
            kwargs, raw = prospective_arguments(case)
            with patch.object(admission, "__file__", str(case.root / "absent-gate.py")), \
                    patch.object(Path, "mkdir", side_effect=AssertionError("preflight mkdir")), \
                    patch.object(Path, "write_bytes", side_effect=AssertionError("preflight write")), \
                    patch.object(executor, "compile_fixture_engine_v1", side_effect=AssertionError("preflight compile")), \
                    patch.object(executor, "_compiler_restore_handlers_v1", side_effect=AssertionError("preflight cleanup")):
                self.assertIsNone(admission.preflight_fixture_engine_v1(**kwargs, source_bytes=raw))
            self.assertFalse(kwargs["source_path"].parent.exists())
            self.assertEqual(case.clients, [])

    def test_ram_success_then_written_source_drift_refuses_before_public_entry(self):
        with admitted_case() as case:
            kwargs, raw = prospective_arguments(case)
            write_after_preflight(kwargs, raw)
            changed = raw.replace(b"return 0", b"return 1")
            self.assertNotEqual(changed, raw)
            self.assertEqual(len(changed), len(raw))
            kwargs["source_path"].write_bytes(changed)
            with patch.object(executor, "compile_fixture_engine_v1") as owner:
                with self.assertRaisesRegex(executor.FixtureCompilerError, "owner_source_binding"):
                    admission.compile_admitted_fixture_engine_v1(**kwargs)
            owner.assert_not_called()
            self.assertFalse(kwargs["executable_path"].exists())
            self.assertEqual(case.clients, [])

    def test_gate_file_hash_cannot_replace_executor_binding(self):
        with admitted_case() as case:
            gate_raw = executor._compiler_read_v1(Path(admission.__file__).resolve(), 32768)
            gate_sha = hashlib.sha256(gate_raw).hexdigest()
            self.assertNotEqual(gate_sha, admission.FROZEN_EXECUTOR_SHA256)
            case.recipe["bindings"]["host_sha256"] = gate_sha
            case.qualification = case.seal("qualification.json", case.recipe)
            case.admit["recipe_sha256"] = case.qualification["sha256"]
            case.admit["bindings"]["host_sha256"] = gate_sha
            case.admission = case.seal("admission.json", case.admit)
            with patch.object(executor, "compile_fixture_engine_v1") as owner:
                with self.assertRaisesRegex(executor.FixtureCompilerError, "owner_helper_drift"):
                    admission.compile_admitted_fixture_engine_v1(**arguments(case))
            owner.assert_not_called()
            self.assertEqual(case.clients, [])

    def test_handoff_rechecks_expiry_runtime_floor_and_remaining_time(self):
        for failure, code in (("expiry", "owner_physical_admission"),
                ("runtime", "owner_runtime_binding"), ("floor", "owner_fresh_floor"),
                ("clock", "owner_containment_room")):
            with self.subTest(failure=failure), admitted_case() as case:
                kwargs, raw = prospective_arguments(case)
                write_after_preflight(kwargs, raw)
                if failure == "runtime":
                    case.host["boot_id"] = "00000000-0000-0000-0000-000000000002"
                if failure == "clock":
                    case.now[0] += 70_000_000_000
                real_time = time.time_ns()
                free = {"c_free": 0 if failure == "floor" else 1_000_000_000_000,
                        "project_free": 1_000_000_000_000}
                with patch.object(admission.time, "time_ns", return_value=(
                        case.admit["expires_unix_ns"] + 1 if failure == "expiry" else real_time)), \
                        patch.object(executor, "_compiler_floor_facts_v1", return_value=free), \
                        patch.object(executor, "compile_fixture_engine_v1") as owner:
                    with self.assertRaisesRegex(executor.FixtureCompilerError, code):
                        admission.compile_admitted_fixture_engine_v1(**kwargs)
                owner.assert_not_called()
                self.assertFalse(kwargs["executable_path"].exists())
                self.assertEqual(case.clients, [])

    def test_handoff_calls_public_owner_once_with_original_inputs_and_result(self):
        with admitted_case() as case:
            kwargs = arguments(case)
            result = {"accepted": False, "normal_closed": False, "facts": {"original": "controlled"}}
            with patch.object(executor, "compile_fixture_engine_v1", return_value=result) as owner:
                observed = admission.compile_admitted_fixture_engine_v1(**kwargs)
            self.assertIs(observed, result)
            owner.assert_called_once()
            self.assertEqual(set(owner.call_args.kwargs), set(kwargs))
            for key, value in kwargs.items():
                self.assertIs(owner.call_args.kwargs[key], value, key)
            self.assertEqual(case.clients, [])

    def test_expiry_during_reads_refuses_both_paths_before_return_or_owner(self):
        for prospective in (True, False):
            with self.subTest(prospective=prospective), admitted_case() as case:
                kwargs, raw = prospective_arguments(case) if prospective else (arguments(case), None)
                wall = [time.time_ns()]
                case.admit["expires_unix_ns"] = wall[0] + 55_000_000_000
                kwargs["admission"] = case.seal("admission.json", case.admit)

                def delayed_floor(root):
                    wall[0] += 56_000_000_000
                    case.now[0] += 56_000_000_000
                    return {"c_free": 1_000_000_000_000, "project_free": 1_000_000_000_000}

                with patch.object(admission.time, "time_ns", side_effect=lambda: wall[0]), \
                        patch.object(executor, "_compiler_floor_facts_v1", side_effect=delayed_floor), \
                        patch.object(executor, "compile_fixture_engine_v1") as owner:
                    with self.assertRaisesRegex(executor.FixtureCompilerError, "owner_physical_admission"):
                        if prospective:
                            admission.preflight_fixture_engine_v1(**kwargs, source_bytes=raw)
                        else:
                            admission.compile_admitted_fixture_engine_v1(**kwargs)
                self.assertEqual(kwargs["absolute_deadline_ns"] - case.now[0], 94_000_000_000)
                owner.assert_not_called()
                self.assertFalse(kwargs["executable_path"].exists())
                if prospective:
                    self.assertFalse(kwargs["source_path"].parent.exists())
                self.assertEqual(case.clients, [])

    def test_handoff_preserves_original_exception_facts_and_ordered_causes(self):
        with admitted_case() as case:
            error = executor.FixtureCompilerError("initiating", "distinct_secondary")
            error.facts = {"accepted": False, "original": "controlled"}
            facts, causes = error.facts, error.causes
            with patch.object(executor, "compile_fixture_engine_v1", side_effect=error) as owner:
                with self.assertRaises(executor.FixtureCompilerError) as observed:
                    admission.compile_admitted_fixture_engine_v1(**arguments(case))
            self.assertIs(observed.exception, error)
            self.assertIs(observed.exception.facts, facts)
            self.assertIs(observed.exception.causes, causes)
            self.assertEqual(causes, ["initiating", "distinct_secondary"])
            owner.assert_called_once()
            self.assertEqual(case.clients, [])

    def test_frozen_owner_revalidates_source_after_successful_gate(self):
        with admitted_case() as case:
            actual_owner = executor.compile_fixture_engine_v1
            raw = case.source.read_bytes()

            def changed_at_handoff(**kwargs):
                case.source.write_bytes(raw.replace(b"return 0", b"return 1"))
                return actual_owner(**kwargs)

            with patch.object(executor, "compile_fixture_engine_v1", side_effect=changed_at_handoff) as owner:
                with self.assertRaisesRegex(executor.FixtureCompilerError, "owner_source_binding"):
                    admission.compile_admitted_fixture_engine_v1(**arguments(case))
            owner.assert_called_once()
            self.assertFalse(case.executable.exists())
            self.assertEqual(case.clients, [])


if __name__ == "__main__":
    unittest.main()
