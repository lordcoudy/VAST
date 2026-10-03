"""External CI trace observation; no watchdog or thread in the test child."""
from __future__ import annotations

from contextlib import contextmanager
import ctypes
import faulthandler
import json
import os
from pathlib import Path
import selectors
import select
import signal
import stat
import subprocess
import threading
import time


TRACE_LIMIT = 1024 * 1024
CONTROL_LIMIT = 1024 * 1024
NAMESPACE_LIMIT = 8 * 1024 * 1024


def _json(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _owner(pid):
    stat = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
    status = Path(f"/proc/{pid}/status").read_text().splitlines()
    fields = dict(line.split(":", 1) for line in status if ":" in line)
    exe_path = os.readlink(f"/proc/{pid}/exe")
    exe = os.stat(f"/proc/{pid}/exe")
    return {"pid": pid, "startticks": int(stat[19]), "ppid": int(stat[1]),
            "pgid": int(stat[2]), "uid": int(fields["Uid"].split()[0]),
            "gid": int(fields["Gid"].split()[0]),
            "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
            "executable_realpath": exe_path,
            "executable_stat": {name: getattr(exe, name) for name in
                ("st_dev", "st_ino", "st_mode", "st_nlink", "st_size", "st_uid", "st_gid")}}


@contextmanager
def child_trace_handler(trace_fd, event_fd, stop_fd):
    """Install one safe-GIL handler; event writes never block an active test."""
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError("CI trace handler requires the original main thread")
    previous = signal.getsignal(signal.SIGUSR1)
    if previous != signal.SIG_DFL:
        raise RuntimeError("existing SIGUSR1 disposition conflicts with CI observation")
    if len({trace_fd, event_fd, stop_fd}) != 3 or any(
        not stat.S_ISFIFO(os.fstat(fd).st_mode) for fd in (trace_fd, event_fd, stop_fd)
    ):
        raise RuntimeError("CI trace/control/stop require three distinct live pipe FDs")
    os.set_blocking(event_fd, False)
    state = {"response_count": 0, "failure": None}
    # Keep the original Linux sigaction (including mask/restart flags). Python's
    # signal.signal alone cannot expose the previous siginterrupt setting.
    libc = ctypes.CDLL(None, use_errno=True)
    action = ctypes.create_string_buffer(512)
    if libc.sigaction(signal.SIGUSR1, None, ctypes.byref(action)):
        raise OSError(ctypes.get_errno(), "cannot retain original SIGUSR1 sigaction")

    def emit(event, **facts):
        raw = _json({"event": event, "child_monotonic_ns": time.monotonic_ns(), **facts})
        if len(raw) > 4096:
            raise RuntimeError("CI response record exceeds PIPE_BUF")
        if os.write(event_fd, raw) != len(raw):
            raise RuntimeError("incomplete CI response record")

    def handler(signum, frame):
        state["response_count"] += 1
        ordinal = state["response_count"]
        try:
            emit("response_started", response_ordinal=ordinal)
            faulthandler.dump_traceback(file=trace_fd, all_threads=True)
            emit("response_finished", response_ordinal=ordinal, dump_failed=False)
        except BaseException as exc:
            # Never inject an observer exception into the test under observation.
            state["failure"] = f"{type(exc).__name__}: {exc}"[:240]
            try:
                emit("response_failed", response_ordinal=ordinal, failure=state["failure"])
            except BaseException:
                pass

    installed = False
    try:
        signal.signal(signal.SIGUSR1, handler)
        installed = True
        signal.siginterrupt(signal.SIGUSR1, False)
        emit("ready", pid=os.getpid(), native_task_count=len(list(Path("/proc/self/task").iterdir())),
             requested_restart_syscalls=True, handler="python_main_thread_safe_gil")
        yield state
    finally:
        if installed:
            old_mask = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGUSR1})
            try:
                emit("requests_stop")
                if not select.select([stop_fd], [], [], 5)[0] or os.read(stop_fd, 1) != b"1":
                    raise RuntimeError("external parent did not acknowledge stopping requests")
                pending = 0
                while signal.SIGUSR1 in signal.sigpending():
                    signal.sigwait({signal.SIGUSR1})
                    pending += 1
                emit("requests_stopped", pending_teardown_signal_count=pending)
            except BaseException as exc:
                state["failure"] = f"trace teardown failed: {type(exc).__name__}: {exc}"[:240]
                raise
            finally:
                signal.signal(signal.SIGUSR1, previous)
                if libc.sigaction(signal.SIGUSR1, ctypes.byref(action), None):
                    state["failure"] = "cannot restore original SIGUSR1 sigaction"
                    raise OSError(ctypes.get_errno(), state["failure"])
                signal.pthread_sigmask(signal.SIG_SETMASK, old_mask)


def observe_test_child(argv_factory, *, output_dir, absolute_deadline_ns,
                       interval_s=60, ready_timeout_s=30, cleanup_s=15):
    """Launch once, drain original pipes, and retain honest request/response facts.

    argv_factory receives trace/control write FDs and a stop-ACK read FD. The caller owns existing
    suite report/test-log contracts; this fresh observer namespace is <=8 MiB.
    """
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    start = time.monotonic_ns()
    if not (0 < interval_s <= 60 and 0 < cleanup_s <= 15):
        raise ValueError("invalid CI observer interval/cleanup bound")
    if start >= absolute_deadline_ns:
        raise RuntimeError("original CI job deadline already elapsed")
    files = {}
    retained = 0
    failure = None
    process = None
    pidfd = None
    pidfd_acquisition_failed = False
    pidfd_failure = None
    cleanup_deadline = None
    ready = False
    requests_stopped = False
    responses = []
    requests = []
    control_pending = bytearray()
    control_count = 0
    trace_count = 0
    eof = {"trace": False, "control": False}
    sel = selectors.DefaultSelector()
    trace_r, trace_w = os.pipe()
    event_r, event_w = os.pipe()
    stop_r, stop_w = os.pipe()
    opened = [trace_r, trace_w, event_r, event_w, stop_r, stop_w]

    def fail(reason):
        nonlocal failure, cleanup_deadline
        if failure is None:
            failure = reason
        if cleanup_deadline is None:
            cleanup_deadline = min(absolute_deadline_ns, time.monotonic_ns() + int(cleanup_s * 1e9))

    def save(name, raw):
        nonlocal retained
        if retained + len(raw) > NAMESPACE_LIMIT:
            raise RuntimeError("CI observer namespace exceeds 8MiB")
        stream = files.get(name)
        if stream is None:
            stream = (output / name).open("xb")
            files[name] = stream
        if stream.write(raw) != len(raw):
            raise RuntimeError("incomplete observer evidence write")
        stream.flush()
        retained += len(raw)

    def event(value):
        save("events.original.jsonl", _json({"parent_monotonic_ns": time.monotonic_ns(), **value}))

    def send(sig):
        if process is not None and process.poll() is None:
            if pidfd is not None:
                signal.pidfd_send_signal(pidfd, sig)
            elif pidfd_acquisition_failed:
                # This exact Popen child remains unreaped and cannot have a reused
                # PID. Never select another process or retry observation.
                process.send_signal(sig)

    owner = None
    argv = None
    term_sent = False
    kill_sent = False
    next_request = None
    pending_request_sequences = []
    response_candidates = {}
    completed_responses = set()
    try:
        for name in ("trace.original.log", "responses.original.jsonl", "events.original.jsonl"):
            save(name, b"")
        argv = list(argv_factory(trace_w, event_w, stop_r))
        # Preserve the original CI console stdout/stderr contract. Test events
        # still go to the runner's original unittest log, outside this namespace.
        process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, pass_fds=(trace_w, event_w, stop_r),
                                   start_new_session=True)
        try:
            pidfd = os.pidfd_open(process.pid)
        except BaseException as exc:
            pidfd_acquisition_failed = True
            pidfd_failure = f"{type(exc).__name__}: {exc}"[:240]
            fail(pidfd_failure)
            try:
                owner = _owner(process.pid)
            except (OSError, ValueError):
                owner = {"pid": process.pid, "remaining_owner_facts_unavailable": True}
            save("launch.v1.json", _json({"argv": argv, "owner": owner,
                 "started_monotonic_ns": start, "absolute_deadline_ns": absolute_deadline_ns,
                 "interval_s": interval_s, "pidfd_opened": False, "pidfd_failure": pidfd_failure}))
            raise
        owner = _owner(process.pid)
        save("launch.v1.json", _json({"argv": argv, "owner": owner,
             "started_monotonic_ns": start, "absolute_deadline_ns": absolute_deadline_ns,
             "interval_s": interval_s, "pidfd_opened": True}))
        for fd in (trace_w, event_w, stop_r):
            os.close(fd)
            opened.remove(fd)
        for fd, name in ((trace_r, "trace"), (event_r, "control")):
            os.set_blocking(fd, False)
            sel.register(fd, selectors.EVENT_READ, name)
        while True:
            now = time.monotonic_ns()
            if now >= absolute_deadline_ns:
                fail("original whole-job deadline exceeded")
            if not ready and now >= min(absolute_deadline_ns, start + int(ready_timeout_s * 1e9)):
                fail("original child READY missing before bounded startup")
            rc = process.poll()
            if rc is not None and cleanup_deadline is None:
                cleanup_deadline = min(absolute_deadline_ns, now + int(cleanup_s * 1e9))
            if failure and rc is None and not term_sent:
                send(signal.SIGTERM)
                term_sent = True
                event({"event": "owned_child_sigterm"})
            if failure and rc is None and not kill_sent and (
                cleanup_deadline is not None and now >= cleanup_deadline - int(min(2, cleanup_s / 2) * 1e9)
            ):
                send(signal.SIGKILL)
                kill_sent = True
                event({"event": "owned_child_sigkill"})
            if rc is not None and all(eof.values()):
                break
            if cleanup_deadline is not None and now >= cleanup_deadline:
                fail("original child reap/pipe drain deadline exceeded")
                break
            if ready and not requests_stopped and not failure and rc is None and next_request is not None and now >= next_request:
                # Ordinary signals can coalesce; retain sends, never assume dumps.
                seq = len(requests) + 1
                signal.pidfd_send_signal(pidfd, signal.SIGUSR1)
                sent = time.monotonic_ns()
                item = {"event": "request_sent", "request_seq": seq,
                        "scheduled_monotonic_ns": next_request, "sent_monotonic_ns": sent,
                        "responses_started_before_send": len(responses)}
                requests.append(item)
                pending_request_sequences.append(seq)
                event(item)
                next_request += int(interval_s * 1e9)
            for key, _ in sel.select(.02):
                block = os.read(key.fd, 65536)
                name = key.data
                if not block:
                    sel.unregister(key.fd)
                    eof[name] = True
                    event({"event": "pipe_eof", "pipe": name})
                    if not requests_stopped and process.poll() is None:
                        fail("original observer pipe EOF before request-stop/child terminal")
                    continue
                if name == "trace":
                    available = TRACE_LIMIT - trace_count
                    if available > 0:
                        save("trace.original.log", block[:available])
                        trace_count += min(len(block), available)
                    if len(block) > available:
                        fail("original trace exceeds 1MiB; retained prefix only")
                else:
                    if control_count + len(block) > CONTROL_LIMIT:
                        fail("original response channel exceeds 1MiB")
                        continue
                    control_count += len(block)
                    save("responses.original.jsonl", block)
                    control_pending.extend(block)
                    while b"\n" in control_pending:
                        line, _, remainder = control_pending.partition(b"\n")
                        control_pending[:] = remainder
                        if len(line) > 4096:
                            raise RuntimeError("original child response record exceeds bound")
                        value = json.loads(line)
                        if not isinstance(value, dict) or not isinstance(value.get("child_monotonic_ns"), int):
                            raise RuntimeError("invalid original child response")
                        arrival = time.monotonic_ns()
                        event({"event": "response_received", "response": value,
                               "arrival_monotonic_ns": arrival,
                               "clock": "same_kernel_monotonic_ns"})
                        if value.get("event") == "ready":
                            if ready or value.get("pid") != process.pid:
                                raise RuntimeError("duplicate/foreign original child READY")
                            ready = True
                            next_request = arrival + int(interval_s * 1e9)
                        elif value.get("event") == "response_started":
                            ordinal = value.get("response_ordinal")
                            if ordinal != len(responses) + 1:
                                raise RuntimeError("original response ordinal is not contiguous")
                            responses.append(value)
                            candidates = list(pending_request_sequences)
                            pending_request_sequences.clear()
                            response_candidates[ordinal] = candidates
                            sent_times = [requests[index - 1]["sent_monotonic_ns"] for index in candidates]
                            event({"event": "response_timing", "response_ordinal": ordinal,
                                   "candidate_request_sequences": candidates,
                                   "matching_ambiguous": len(candidates) != 1,
                                   "earliest_candidate_to_handler_ns": (
                                       value["child_monotonic_ns"] - min(sent_times) if sent_times else None),
                                   "handler_to_parent_arrival_ns": arrival - value["child_monotonic_ns"],
                                   "clock": "same_kernel_monotonic_ns",
                                   "timely_response_claim": False})
                        elif value.get("event") == "response_finished":
                            ordinal = value.get("response_ordinal")
                            if ordinal not in response_candidates or ordinal in completed_responses or value.get("dump_failed") is not False:
                                raise RuntimeError("invalid original response completion")
                            completed_responses.add(ordinal)
                        elif value.get("event") == "response_failed":
                            fail("original synchronous dump/control failed")
                        elif value.get("event") == "requests_stop":
                            if requests_stopped:
                                raise RuntimeError("duplicate original child stop request")
                            requests_stopped = True
                            os.write(stop_w, b"1")
                            event({"event": "requests_stop_acknowledged"})
                        elif value.get("event") == "requests_stopped":
                            if not requests_stopped or type(value.get("pending_teardown_signal_count")) is not int:
                                raise RuntimeError("invalid original request-stop completion")
                        else:
                            raise RuntimeError("unknown original response event")
                    if len(control_pending) > 4096:
                        raise RuntimeError("unterminated original child response exceeds bound")
        if control_pending:
            fail("truncated original child response prefix")
        if not ready:
            fail("original child never established READY")
        if len(completed_responses) != len(responses):
            fail("original response completion missing")
        if process.returncode != 0:
            fail("original suite child did not exit zero")
    except BaseException as exc:
        fail(f"{type(exc).__name__}: {exc}"[:512])
    finally:
        if cleanup_deadline is None:
            cleanup_deadline = min(absolute_deadline_ns, time.monotonic_ns() + int(cleanup_s * 1e9))
        try:
            if process is not None and process.poll() is None:
                try:
                    send(signal.SIGTERM)
                    term_sent = True
                    remaining = max(0, (cleanup_deadline - time.monotonic_ns()) / 1e9)
                    process.wait(timeout=min(1, remaining))
                except subprocess.TimeoutExpired:
                    send(signal.SIGKILL)
                    kill_sent = True
                    process.wait(timeout=max(0, (cleanup_deadline - time.monotonic_ns()) / 1e9))
        except BaseException as exc:
            fail(f"owned child cleanup failed: {type(exc).__name__}: {exc}"[:512])
        finally:
            sel.close()
            for fd in opened:
                os.close(fd)
            if pidfd is not None:
                os.close(pidfd)
        end = time.monotonic_ns()
        if end >= cleanup_deadline:
            fail("observer finalization exceeded original cleanup/job deadline")
        rc = process.poll() if process is not None else None
        terminal = {"kind": "vast_external_ci_test_observer_v1", "owner": owner, "argv": argv,
                    "returncode": rc, "signal": -rc if rc is not None and rc < 0 else None,
                    "ready": ready, "failure": failure, "successful": failure is None and rc == 0,
                    "requests_stopped_before_disposition_restore": requests_stopped,
                    "pidfd_acquisition_failed": pidfd_acquisition_failed,
                    "pidfd_failure": pidfd_failure,
                    "started_monotonic_ns": start, "finished_monotonic_ns": end,
                    "absolute_deadline_ns": absolute_deadline_ns, "cleanup_deadline_ns": cleanup_deadline,
                    "trace_bytes": trace_count, "response_channel_bytes": control_count, "pipe_eof": eof,
                    "requests_sent": len(requests), "responses_started": len(responses),
                    "responses_completed": len(completed_responses),
                    "clock": "same_kernel_monotonic_ns",
                    "unmatched_or_coalesced_requests_possible": max(0, len(requests) - len(responses)),
                    "response_matching": "ordinary signals may coalesce; no one-to-one or timely claim",
                    "forced_sigterm": term_sent, "forced_sigkill": kill_sent,
                    "descendant_quiescence": "not established by original-child status"}
        try:
            save("terminal.v1.json", _json(terminal))
        finally:
            for stream in files.values():
                stream.close()
        if time.monotonic_ns() >= cleanup_deadline:
            # Preserve the pre-close record, and return failure; no rewritten truth.
            terminal["successful"] = False
            terminal["failure"] = terminal["failure"] or "receipt-close crossed original deadline"
            raw = _json({"successful": False, "failure": terminal["failure"],
                         "observed_monotonic_ns": time.monotonic_ns(),
                         "cleanup_deadline_ns": cleanup_deadline})
            if retained + len(raw) > NAMESPACE_LIMIT:
                raise RuntimeError("late observer failure cannot fit original namespace cap")
            with (output / "late-finalization.failure.json").open("xb") as stream:
                stream.write(raw)
    return terminal
