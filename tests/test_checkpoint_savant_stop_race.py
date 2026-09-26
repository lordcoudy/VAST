"""Savant admission EOF must wait for a real, bounded lifecycle STOP."""
from __future__ import annotations

import os
from pathlib import Path
import sys
import threading
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import checkpoint_savant_sdk_runtime_v3 as sdk


class SavantCoordinatedStopTests(unittest.TestCase):
    def test_eof_before_control_stop_waits_for_validated_timestamp(self):
        admission_read, admission_write = os.pipe()
        control_read, control_write = os.pipe()
        status_read, status_write = os.pipe()
        release_stop = threading.Event()
        stop_event = threading.Event()
        timestamps = []
        errors = []
        lifecycle = sdk.LifecycleChannel(
            worker_id='savant-stop-race', control_fd=control_read,
            status_fd=status_write,
        )

        def receive_stop():
            try:
                release_stop.wait()
                timestamps.append(lifecycle.await_stop())
            except BaseException as exc:
                errors.append(exc)
            finally:
                stop_event.set()

        receiver = threading.Thread(target=receive_stop)
        receiver.start()
        try:
            os.close(admission_write)
            admission_write = -1
            self.assertIsNone(sdk.read_admission_transport_frame(admission_read))
            self.assertFalse(stop_event.is_set())
            os.write(control_write, b'1 STOP 3000\n')

            # Release the real control-channel receiver only when the EOF
            # handler joins it, making the original scheduling race certain.
            class ReceiverJoin:
                def join(self, timeout):
                    release_stop.set()
                    receiver.join(timeout=timeout)

            sdk._await_coordinated_stop_after_admission_eof(
                stop_event=stop_event, stop_thread=ReceiverJoin(),
                stop_timestamp=timestamps,
            )
            self.assertEqual(errors, [])
            self.assertEqual(timestamps, [3000])
            self.assertFalse(receiver.is_alive())
        finally:
            release_stop.set()
            os.close(control_write)
            receiver.join(timeout=2)
            for descriptor in (admission_read, admission_write, control_read,
                               status_read, status_write):
                if descriptor >= 0:
                    os.close(descriptor)

    def test_eof_without_stop_is_rejected_even_after_receiver_failure(self):
        for event_set in (False, True):
            with self.subTest(event_set=event_set):
                stop_event = threading.Event()
                if event_set:
                    stop_event.set()
                receiver = threading.Thread(target=lambda: None)
                receiver.start()
                receiver.join()
                with self.assertRaisesRegex(
                    sdk.SavantSdkRuntimeV3Error, 'admission FD closed before STOP',
                ):
                    sdk._await_coordinated_stop_after_admission_eof(
                        stop_event=stop_event, stop_thread=receiver,
                        stop_timestamp=[], timeout_s=0,
                    )

    def test_timestamp_without_completed_stop_notification_is_rejected(self):
        receiver = threading.Thread(target=lambda: None)
        receiver.start()
        receiver.join()
        with self.assertRaisesRegex(
            sdk.SavantSdkRuntimeV3Error, 'admission FD closed before STOP',
        ):
            sdk._await_coordinated_stop_after_admission_eof(
                stop_event=threading.Event(), stop_thread=receiver,
                stop_timestamp=[3000], timeout_s=0,
            )

    def test_pending_stop_is_bounded_and_cannot_synthesize_success(self):
        release = threading.Event()
        receiver = threading.Thread(target=release.wait)
        receiver.start()
        try:
            with self.assertRaisesRegex(
                sdk.SavantSdkRuntimeV3Error, 'admission FD closed before STOP',
            ):
                sdk._await_coordinated_stop_after_admission_eof(
                    stop_event=threading.Event(), stop_thread=receiver,
                    stop_timestamp=[], timeout_s=0,
                )
            self.assertTrue(receiver.is_alive())
        finally:
            release.set()
            receiver.join(timeout=2)


if __name__ == '__main__':
    unittest.main()
