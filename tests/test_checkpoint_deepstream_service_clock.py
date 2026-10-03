"""Path durations must use elapsed time even when the wall clock changes."""
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'tests'))

from checkpoint_deepstream_protocol_bridge import DeepStreamProtocolBridge, DeepStreamProtocolBridgeError
from test_checkpoint_deepstream_protocol_bridge import (
    FakePolicyExchange, admission, endpoints, nvds_identity, tensor,
)


class DeepStreamServiceClockTests(unittest.TestCase):
    def execute(self, wall_terminal_ns, elapsed_ns):
        run_id = 'run-native-service-clock'
        admitted = admission(run_id)
        identity = nvds_identity(admitted)
        self.policy = FakePolicyExchange({'damage': 'cpu'})
        bridge = DeepStreamProtocolBridge(
            run_id=run_id, arm_id='arm-native-service-clock',
            worker_id='deepstream-stream-0-branch-damage',
            topology_kind='independent_processes', stream_id=0, branch_id='damage',
            event_sink=lambda _: None, policy_exchange=self.policy,
            analytics_endpoints=endpoints(('damage',)),
        )
        spec, payload = tensor('damage')
        bridge.admit_access_unit(json.dumps(admitted), observed_timestamp_ms=1000)
        bridge.observe_decoded_frame(identity, observed_timestamp_ms=1001)
        bridge.observe_preprocessed_frame(identity, tensor_spec=spec, observed_timestamp_ms=1002)
        # Wall-clock observations are 2000 ms, 2001 ms, then an adjusted value.
        # The native worker fixture reports 0.8 ms inference and 1 ms total work.
        with mock.patch('checkpoint_deepstream_protocol_bridge.time.time_ns',
                        side_effect=[2_000_000_000, 2_001_000_000, wall_terminal_ns]), \
             mock.patch('checkpoint_deepstream_protocol_bridge.time.monotonic_ns',
                        side_effect=[10_000_000, 10_000_000 + elapsed_ns]):
            return bridge.execute_branch(
                str(admitted['input_frame_key']), 'damage', tensor_payload=payload,
                queue_depths={'cpu': 0, 'gpu': 0}, deadline_monotonic_ns=10_000_000_000,
            )

    def assert_elapsed_terminal(self):
        terminal = next(row for row in self.policy.messages if row['message_type'] == 'terminal')
        self.assertEqual(terminal['actual_service_ms'], 2.0)
        self.assertEqual(terminal['terminal_timestamp_ms'], 2003.0)

    def test_backward_wall_adjustment_does_not_shorten_native_service(self):
        self.execute(2_001_200_000, 2_000_000)
        self.assert_elapsed_terminal()

    def test_forward_wall_adjustment_does_not_inflate_native_service(self):
        self.execute(2_101_000_000, 2_000_000)
        self.assert_elapsed_terminal()

    def test_inference_longer_than_elapsed_service_still_fails(self):
        with self.assertRaisesRegex(DeepStreamProtocolBridgeError, 'shorter than native inference'):
            self.execute(2_101_000_000, 500_000)
        self.assertFalse(any(row['message_type'] == 'terminal' for row in self.policy.messages))

    def test_postprocess_outside_elapsed_service_still_fails(self):
        with self.assertRaisesRegex(DeepStreamProtocolBridgeError, 'outside its path'):
            self.execute(2_101_000_000, 900_000)
        self.assertFalse(any(row['message_type'] == 'terminal' for row in self.policy.messages))

    def test_regressing_monotonic_clock_is_rejected(self):
        with self.assertRaisesRegex(DeepStreamProtocolBridgeError, 'does not follow path entry'):
            self.execute(2_101_000_000, -1)
        self.assertFalse(any(row['message_type'] == 'terminal' for row in self.policy.messages))


if __name__ == '__main__':
    unittest.main()
