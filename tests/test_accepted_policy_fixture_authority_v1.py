"""Pre-allocation authority refusals; no compiler, engine or large fixture runs."""
from contextlib import ExitStack
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from tests.fixtures import accepted_policy_fixture_compiler_v1 as compiler
from tests.fixtures import accepted_policy_original_custody_fixture_v1 as original
from tests.fixtures import accepted_policy_physical_fixture_v1 as physical_v1
from tests.fixtures import accepted_policy_physical_fixture_v2 as physical_v2


class FixtureAuthorityTests(unittest.TestCase):
    def refusal(self, module, *, malformed):
        with tempfile.TemporaryDirectory(prefix="fixture-authority-") as name:
            root = Path(name).resolve(strict=True)
            output = root / "must-stay-absent"
            arguments = dict(project_root=root, output_dir=output,
                             image_inspections={}, device_probes={})
            if malformed:
                arguments.update(compiler_qualification={}, compiler_admission={},
                                 compiler_absolute_deadline_ns=time.monotonic_ns() + 150_000_000_000)
            if module is original:
                prepare = module.prepare_original_fixture_engine_v1
            else:
                prepare = getattr(module, "prepared_complete_fixture_inputs_" +
                                  ("v1" if module is physical_v1 else "v2"))
                arguments.update(identity_patch_path=root / "unused-patch",
                    accepted_model_parity_manifest_path=root / "unused-manifest",
                    accepted_model_parity_assessment_path=root / "unused-assessment",
                    accepted_model_parity_receipt_path=root / "unused-receipt")
            with ExitStack() as stack:
                for owner, attribute in ((shutil, "which"),
                        (subprocess, "run"), (socket, "socket"),
                        (compiler, "_DockerClientV1")):
                    stack.enter_context(patch.object(owner, attribute,
                        side_effect=AssertionError("unadmitted external operation")))
                if module is not original:
                    stack.enter_context(patch.object(module.tempfile, "mkdtemp",
                        side_effect=AssertionError("unadmitted native temporary root")))
                    stack.enter_context(patch.object(module,
                        "materialize_publication_policy_qualification_transaction_v2",
                        side_effect=AssertionError("unadmitted large setup")))
                try:
                    with self.assertRaises((ValueError, compiler.FixtureCompilerError)):
                        with prepare(**arguments):
                            self.fail("unadmitted fixture yielded")
                finally:
                    self.assertFalse(output.exists(), "authority refusal allocated fixture output")

    def test_original_missing_authority_allocates_nothing(self):
        self.refusal(original, malformed=False)

    def test_original_malformed_authority_allocates_nothing(self):
        self.refusal(original, malformed=True)

    def test_outer_v1_missing_authority_allocates_nothing(self):
        self.refusal(physical_v1, malformed=False)

    def test_outer_v1_malformed_authority_allocates_nothing(self):
        self.refusal(physical_v1, malformed=True)

    def test_outer_v2_missing_authority_allocates_nothing(self):
        self.refusal(physical_v2, malformed=False)

    def test_outer_v2_malformed_authority_allocates_nothing(self):
        self.refusal(physical_v2, malformed=True)


if __name__ == "__main__":
    unittest.main()
