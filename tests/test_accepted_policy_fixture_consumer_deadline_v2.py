"""The sealed reader clock must precede consumer materialization; no I/O."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from tests.fixtures import accepted_policy_consumer_fixture_v2 as consumer
from tests.fixtures import accepted_policy_standalone_reader_fixture_v2 as reader


class ChainReached(AssertionError):
    pass


class ConsumerDeadlineTests(unittest.TestCase):
    def setUp(self):
        self.now = 1_000_000_000
        self.deadline = {"absolute_monotonic_ns": self.now + 20_000_000_000,
                         "term_grace_ns": 5_000_000_000, "kill_grace_ns": 5_000_000_000,
                         "final_ns": 5_000_000_000}

    def invoke(self, deadline):
        return consumer.complete_fixture_production_consumers_v2(
            prepared={"root": Path.cwd(), "output_dir": Path.cwd() / "never-created"}, native={},
            approved_guardian_source=b"controlled source; never loaded",
            approved_guardian_commit="a" * 40, standalone_reader_deadline=deadline)

    def refused(self, deadline):
        with patch.object(consumer, "materialize_fixture_completed_execution_v2",
                side_effect=ChainReached("materialization began without an admitted clock")) as chain, \
                patch.object(reader, "_monotonic_ns", return_value=self.now):
            with self.assertRaises(ValueError):
                self.invoke(deadline)
            chain.assert_not_called()

    def test_missing_clock_refuses_before_materialization(self):
        self.refused(None)

    def test_malformed_clock_refuses_before_materialization(self):
        for value in ([], {}, {**self.deadline, "unexpected": 1},
                      {**self.deadline, "final_ns": True},
                      {**self.deadline, "term_grace_ns": 0},
                      {**self.deadline, "absolute_monotonic_ns": "21000000000"}):
            with self.subTest(value=value):
                self.refused(value)

    def test_expired_or_no_observation_budget_refuses_before_materialization(self):
        for absolute in (self.now, self.now + 15_000_000_000):
            with self.subTest(absolute=absolute):
                self.refused({**self.deadline, "absolute_monotonic_ns": absolute})

    def test_valid_supplied_clock_reaches_chain_without_rewrite(self):
        original = dict(self.deadline)
        with patch.object(consumer, "materialize_fixture_completed_execution_v2",
                side_effect=ChainReached("controlled admitted chain")) as chain, \
                patch.object(reader, "_monotonic_ns", return_value=self.now):
            with self.assertRaisesRegex(ChainReached, "admitted chain"):
                self.invoke(self.deadline)
            chain.assert_called_once()
        self.assertEqual(self.deadline, original)


if __name__ == "__main__":
    unittest.main()
