"""Preparation socket ownership and distinct failures; no real resources."""
from contextlib import ExitStack
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from tests.fixtures import accepted_policy_physical_fixture_v2 as physical


class PreparationSocketCleanupTests(unittest.TestCase):
    def run_preparation(self, *, constructor_failure=False, first_failure=False,
                        front_failure=None, control_failure=None):
        self.initiating = RuntimeError("controlled initiating failure")
        self.front = Mock()
        self.control = Mock()
        self.front.close.side_effect = front_failure
        self.control.close.side_effect = control_failure
        sockets = [self.initiating] if first_failure else [
            self.front, self.initiating if constructor_failure else self.control]
        with ExitStack() as stack:
            stack.enter_context(patch.object(physical, "_fixture_command_replies_v2", return_value=({}, {})))
            stack.enter_context(patch.object(physical, "preflight_original_fixture_engine_v1"))
            stack.enter_context(patch.object(physical.fixture_admission, "_compiler_preparation_clock_v1"))
            stack.enter_context(patch.object(physical.tempfile, "mkdtemp", return_value="/var/tmp/controlled-prep"))
            stack.enter_context(patch.object(physical.socket, "socket", side_effect=sockets))
            self.engine = stack.enter_context(patch.object(physical, "prepare_original_fixture_engine_v1",
                side_effect=self.initiating))
            stack.enter_context(patch.object(Path, "mkdir"))
            stack.enter_context(patch.object(Path, "exists", return_value=False))
            stack.enter_context(patch.object(Path, "is_symlink", return_value=False))
            self.error = None
            try:
                with physical.prepared_complete_fixture_inputs_v2(project_root=ROOT,
                        output_dir=ROOT / "controlled-preparation",
                        identity_patch_path=ROOT / "controlled-patch",
                        accepted_model_parity_manifest_path=ROOT / "controlled-manifest",
                        accepted_model_parity_assessment_path=ROOT / "controlled-assessment",
                        accepted_model_parity_receipt_path=ROOT / "controlled-receipt",
                        image_inspections={}, device_probes={}):
                    self.fail("controlled engine failure must prevent yield")
            except BaseException as error:
                self.error = error

    def assert_retained(self, *secondary):
        self.assertIs(getattr(self.error, "primary", self.error), self.initiating)
        self.assertEqual(getattr(self.error, "secondary", ()), secondary)
        if secondary:
            self.assertIs(self.error.__cause__, self.initiating)

    def test_second_socket_constructor_failure_closes_first_owned_socket(self):
        self.run_preparation(constructor_failure=True)
        self.assert_retained()
        self.front.close.assert_called_once_with()
        self.control.close.assert_not_called()
        self.engine.assert_not_called()

    def test_second_constructor_and_close_failures_are_both_retained(self):
        close_error = OSError("controlled front close")
        self.run_preparation(constructor_failure=True, front_failure=close_error)
        self.assert_retained(close_error)
        self.front.close.assert_called_once_with()
        self.engine.assert_not_called()

    def test_front_close_failure_does_not_skip_control_close_or_mask_body(self):
        close_error = OSError("controlled front close")
        self.run_preparation(front_failure=close_error)
        self.assert_retained(close_error)
        self.front.close.assert_called_once_with()
        self.control.close.assert_called_once_with()

    def test_control_close_failure_does_not_mask_body(self):
        close_error = OSError("controlled control close")
        self.run_preparation(control_failure=close_error)
        self.assert_retained(close_error)
        self.front.close.assert_called_once_with()
        self.control.close.assert_called_once_with()

    def test_both_distinct_close_failures_retain_order_after_primary(self):
        front_error, control_error = OSError("controlled front close"), OSError("controlled control close")
        self.run_preparation(front_failure=front_error, control_failure=control_error)
        self.assert_retained(front_error, control_error)
        self.front.close.assert_called_once_with()
        self.control.close.assert_called_once_with()

    def test_same_close_exception_object_is_retained_only_once(self):
        close_error = OSError("controlled shared close")
        self.run_preparation(front_failure=close_error, control_failure=close_error)
        self.assert_retained(close_error)
        self.front.close.assert_called_once_with()
        self.control.close.assert_called_once_with()

    def test_unallocated_socket_and_clean_close_preserve_original_error(self):
        for first_failure in (True, False):
            with self.subTest(first_failure=first_failure):
                self.run_preparation(first_failure=first_failure)
                self.assertIs(self.error, self.initiating)
                if first_failure:
                    self.front.close.assert_not_called()
                    self.control.close.assert_not_called()
                else:
                    self.front.close.assert_called_once_with()
                    self.control.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
