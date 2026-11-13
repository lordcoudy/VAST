"""R1: retired D22-D27 copies match their README, and the frozen operators stay byte-exact."""
import hashlib
import re
import unittest
from pathlib import Path

from tests.fixtures.accepted_policy_change_paths_v1 import change_directory_v1


ROOT = Path(__file__).resolve().parents[1]
RETIRED = "evidence/retired-development-tests-20261111"
# Byte-exact operators (design.md R1 and the 2026-11-11 setup/capture finding). gate2_c is pinned at its
# reviewed fresh-gate-2 bytes (design.md, "Fresh direct gate 2"); its earlier bytes are a retired copy.
FROZEN = {
    "tests/fixtures/accepted_policy_fixture_compiler_gate2_c_v1.py":
        (141129, "d005a380726e3495ee0558d645b4a385b25aa1b8779f079d6225455be6cc2735"),
    "tests/fixtures/accepted_policy_fixture_compiler_v1.py":
        (103925, "1e40d4786fd03543ac43df7fe0e42a4349d55bad9288ead28f5d2a6ad87bcb03"),
    "tests/fixtures/accepted_policy_fixture_compiler_gate2_setup_v1.py":
        (48892, "807263a7e499a5a4ccbd6d275acf9effa08a2ded35273e5bfbe816f28b527323"),
    "tests/fixtures/accepted_policy_fixture_compiler_gate2_capture_v1.py":
        (45056, "58f33fb1993b83ae40d9f2d9ea39fe21867e5861486a80cbe07fa8b7d0174648"),
}
ROW = re.compile(r"^\| `([^`]+)` \| `([^`]+\.retired)` \| (\d+) \| `([0-9a-f]{64})` \| [^|]+ \|$")


def readme_rows(directory):
    rows = [ROW.match(line) for line in (directory / "README.md").read_text(encoding="utf-8").splitlines()]
    return [(m[1], m[2], int(m[3]), m[4]) for m in rows if m]


class RetiredDevelopmentTestsV1(unittest.TestCase):
    def setUp(self):
        self.directory = change_directory_v1(ROOT) / RETIRED

    def test_every_retired_copy_matches_its_readme_row(self):
        rows = readme_rows(self.directory)
        self.assertEqual(len(rows), 8)
        listed = {name for _, name, _, _ in rows}
        self.assertEqual(listed, {p.name for p in self.directory.glob("*.retired")})
        for original, name, size, digest in rows:
            with self.subTest(copy=name):
                raw = (self.directory / name).read_bytes()
                self.assertEqual(name, Path(original).name + ".retired")
                self.assertEqual((len(raw), hashlib.sha256(raw).hexdigest()), (size, digest))

    def test_retired_tests_are_out_of_discovery(self):
        for original, _, _, _ in readme_rows(self.directory):
            if Path(original).name.startswith("test_accepted_policy_fixture_compiler_gate2_dictionary"):
                self.assertFalse((ROOT / original).exists(), original)
        self.assertFalse((ROOT / "tests/fixtures/gate2/d26-geometry-retained-v1.json").exists())
        for module in ("test_accepted_policy_fixture_compiler_gate2_resume_v1.py",
                       "test_accepted_policy_fixture_compiler_gate2_resume_caller_v1.py"):
            source = (ROOT / "tests" / module).read_text(encoding="utf-8")
            self.assertNotRegex(source, r"\bD2[2-7]|d22_sha|_D22_BROTLI")
            self.assertTrue(source.endswith("\n\nif __name__ == '__main__':\n    unittest.main()\n"))

    def test_frozen_operators_stay_byte_exact(self):
        for relative, (size, digest) in FROZEN.items():
            with self.subTest(path=relative):
                raw = (ROOT / relative).read_bytes()
                self.assertEqual((len(raw), hashlib.sha256(raw).hexdigest()), (size, digest))

    def test_a_changed_copy_is_detected(self):
        rows = readme_rows(self.directory)
        _, name, size, digest = rows[0]
        raw = (self.directory / name).read_bytes()
        self.assertNotEqual(hashlib.sha256(raw + b"\n").hexdigest(), digest)


if __name__ == "__main__":
    unittest.main()
