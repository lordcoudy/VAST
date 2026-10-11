"""Run one unchanged declared integration test; a skip is a failed lane."""

import json
import sys
import unittest
from pathlib import Path


class Result(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.successes = []

    def addSuccess(self, test):
        super().addSuccess(test)
        self.successes.append(test.id().removeprefix("tests."))


if __name__ == "__main__":
    name, output = sys.argv[1:]
    target = Path(output)
    if target.exists():
        raise RuntimeError("integration outcome already exists")
    sys.path.insert(0, str(Path.cwd()))
    suite = unittest.defaultTestLoader.loadTestsFromName("tests." + name)
    result = unittest.TextTestRunner(verbosity=2, resultclass=Result).run(suite)
    passed = (result.wasSuccessful() and result.testsRun == 1 and result.successes == [name]
              and not result.skipped and not result.expectedFailures and not result.unexpectedSuccesses)
    target.write_text(json.dumps({"test_id": name, "tests_run": result.testsRun,
        "successful_test_ids": result.successes, "skips": [(test.id(), reason) for test, reason in result.skipped],
        "failures": [(test.id(), trace) for test, trace in result.failures],
        "errors": [(test.id(), trace) for test, trace in result.errors],
        "successful": passed, "new_repair_runtime_authority": False}, indent=2) + "\n", encoding="ascii")
    raise SystemExit(0 if passed else 1)
