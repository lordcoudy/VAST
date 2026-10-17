"""Amendment 8 (F4): Q1 runbook steps refuse to run where bash ignores ``set -e``.

In ``a && b``, ``a || b`` and ``if a`` bash disables errexit inside the step
function, so a refusing helper would not stop the step (attempt 4, steps 14-15).
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNBOOK = ROOT / "docs" / "full-qualification-runbook-commands.sh"
SENTINEL = "sentinel: original evidence of an earlier invocation\n"
GUARDED_FILES = (
    "q1_14_policy_index.launch.txt",
    "q1_14_policy_index.stdout.log",
    "q1_14_policy_index.stderr.log",
    "q1_14_policy_index.rc",
)
CONTEXTS = {
    "plain": 'q1_14_indices; echo "rc=$?"',
    "and": 'q1_14_indices && true; echo "rc=$?"',
    "or": 'q1_14_indices || echo "rc=$?"',
    "if": 'if q1_14_indices; then echo "rc=0"; else echo "rc=$?"; fi',
}


@unittest.skipUnless(shutil.which("bash") and shutil.which("sha256sum"), "bash and coreutils are required")
class RunbookErrexitProbeTests(unittest.TestCase):
    def _invoke(self, context: str) -> tuple[subprocess.CompletedProcess, Path]:
        work = Path(tempfile.mkdtemp(prefix="runbook-errexit-"))
        self.addCleanup(shutil.rmtree, work, True)
        ctrl = work / "ctrl"
        ctrl.mkdir()
        (work / "root").mkdir()
        closure = work / "closure.receipt.json"
        closure.write_text("{}\n", encoding="ascii")
        script = textwrap.dedent(
            f"""
            source "$RUNBOOK"
            ROOT="$WORK/root"; A="$ROOT/artifacts"; CTRL="$WORK/ctrl"
            PY=/bin/true; PYRUN=(/bin/true)
            POLICY_INDEX_DIR="$A/policy-index"; RESOURCE_INDEX="$A/resource-index.json"
            POLICY_INDEX="$POLICY_INDEX_DIR/index.json"
            for step in q1_02_transaction q1_13_execution_closure; do
                sha256sum "$WORK/closure.receipt.json" > "$CTRL/$step.outputs.sha256"
                printf '0\\n' > "$CTRL/$step.rc"
            done
            for name in {" ".join(GUARDED_FILES)}; do printf '%s' "$SENTINEL" > "$CTRL/$name"; done
            {CONTEXTS[context]}
            """
        )
        completed = subprocess.run(
            ["bash", "-c", script],
            cwd=work,
            env={"PATH": "/usr/bin:/bin", "RUNBOOK": str(RUNBOOK), "WORK": str(work), "SENTINEL": SENTINEL},
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        return completed, ctrl

    def _assert_untouched(self, ctrl: Path) -> None:
        for name in GUARDED_FILES:
            self.assertEqual((ctrl / name).read_text(encoding="utf-8"), SENTINEL, name)
        self.assertFalse((ctrl / "q1_14_indices.rc").exists())
        self.assertFalse((ctrl / "q1_14_indices.outputs.sha256").exists())

    def test_plain_invocation_passes_the_probe_and_a_helper_refusal_fails_the_step(self) -> None:
        completed, ctrl = self._invoke("plain")
        self.assertIn("rc=64", completed.stdout, completed.stderr)
        self.assertIn("already exists", completed.stderr)
        self.assertNotIn("errexit disabled", completed.stderr)
        self._assert_untouched(ctrl)

    def test_step_refuses_before_any_write_where_errexit_is_ignored(self) -> None:
        for context in ("and", "or", "if"):
            with self.subTest(context=context):
                completed, ctrl = self._invoke(context)
                self.assertIn("rc=64", completed.stdout, completed.stderr)
                self.assertIn("errexit disabled: run this step as a plain command", completed.stderr)
                self.assertNotIn("already exists", completed.stderr)
                self._assert_untouched(ctrl)

    def test_every_step_function_starts_with_the_errexit_probe(self) -> None:
        text = RUNBOOK.read_text(encoding="utf-8")
        steps = re.findall(r"^(q1_\d\d_[a-z0-9_]+|q1_detach)\(\) \(\n(.*)$", text, flags=re.MULTILINE)
        names = {name for name, _first in steps}
        self.assertEqual(len([name for name in names if name.startswith("q1_")]), 18, sorted(names))
        for name, first in steps:
            with self.subTest(step=name):
                self.assertEqual(first.strip(), "q1__require_errexit")

    def test_probe_is_a_plain_assignment_with_explicit_exit(self) -> None:
        text = RUNBOOK.read_text(encoding="utf-8")
        body = re.search(r"^q1__require_errexit\(\) \{\n(.*?)^\}", text, flags=re.MULTILINE | re.DOTALL)
        self.assertIsNotNone(body)
        self.assertIn("probe=$( (set -e; false; echo x); true )", body.group(1))
        self.assertIn("exit 64", body.group(1))


if __name__ == "__main__":
    unittest.main()
