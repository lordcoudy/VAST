"""Controlled socket/file tests only; never contact Docker or qualify a runtime."""
import json
from pathlib import Path
import socket
import struct
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from tests.fixtures import accepted_policy_fixture_compiler_v1 as compiler


def reply(body=b"{}", headers=b"", status=b"200 OK"):
    return (b"HTTP/1.1 " + status + b"\r\nContent-Length: " +
            str(len(body)).encode("ascii") + b"\r\n" + headers + b"\r\n" + body)


class FakeSocket:
    def __init__(self, data, *, uid=0, fail_send=False, fail_close=False):
        self.data = bytearray(data)
        self.uid, self.fail_send, self.fail_close = uid, fail_send, fail_close
        self.sent, self.timeouts = bytearray(), []
        self.connected, self.closed, self.write_shutdown = None, False, False
        self.on_read = None

    def settimeout(self, value):
        self.timeouts.append(value)

    def connect(self, path):
        self.connected = path

    def getsockopt(self, level, option, size):
        return struct.pack("3i", 40, self.uid, 0)

    def sendall(self, data):
        if self.fail_send:
            self.sent.extend(data[:3])
            raise OSError("private fixture detail must not escape")
        self.sent.extend(data)

    def recv(self, count):
        data = bytes(self.data[:count])
        del self.data[:count]
        if self.on_read:
            self.on_read()
        return data

    def shutdown(self, how):
        self.write_shutdown = True

    def close(self):
        self.closed = True
        if self.fail_close:
            raise OSError("private close detail")


class FaultFile:
    """Real owned file with a controlled short/unreturned write or close fault."""
    def __init__(self, file, *, short=False, unreturned=False, close_fail=False, flush_fail=False):
        self.file = file
        self.short, self.unreturned, self.close_fail = short, unreturned, close_fail
        self.flush_fail, self.flush_count = flush_fail, 0

    def write(self, data):
        if len(data) > 1 and (self.short or self.unreturned):
            count = min(2, len(data))
            self.file.write(data[:count])
            if self.unreturned:
                raise OSError("unreturned fixture extent")
            return count
        return self.file.write(data)

    def flush(self):
        self.flush_count += 1
        if self.flush_fail:
            raise OSError("secondary fixture flush")
        return self.file.flush()

    def fileno(self):
        return self.file.fileno()

    def close(self):
        self.file.close()
        if self.close_fail:
            raise OSError("secondary fixture close")


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.output = Path(self.tmp.name).resolve()
        self.now = [1_000_000_000]
        self.epoch = ((1, 2, 0, 0, 0o140660, 17),)

    def client(self, *sockets, deadline=20_000_000_000, cls=None):
        cls = getattr(compiler, "_DockerClientV1", None) if cls is None else cls
        self.assertTrue(callable(cls), "bounded Docker transport is absent")
        items = iter(sockets)
        client = cls(self.output, deadline, socket_factory=lambda: next(items),
                     clock=lambda: self.now[0])
        observe = patch.object(client, "_observe_endpoint", return_value=self.epoch)
        observe.start()
        self.addCleanup(observe.stop)
        return client

    def refused(self, client, *args, cause=None, **kwargs):
        with self.assertRaises(compiler.FixtureCompilerError) as found:
            client.request(*args, **kwargs)
        if cause:
            self.assertIn(cause, found.exception.causes)
        self.assertIs(found.exception.facts, client.facts)
        return found.exception

    def test_transport_exists(self):
        self.assertTrue(callable(getattr(compiler, "_DockerClientV1", None)),
                        "bounded Docker transport is absent")

    def test_fixed_api_request_raw_originals_and_double_charge(self):
        raw = reply(b'{"ID":"held"}')
        sock = FakeSocket(raw)
        client = self.client(sock)
        self.assertEqual(client.request("GET", "/info"), {"ID": "held"})
        request = b"GET /v1.55/info HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\nContent-Length: 0\r\n\r\n"
        self.assertEqual(bytes(sock.sent), request)
        self.assertEqual((self.output / "RPC01.request.original").read_bytes(), request)
        self.assertEqual((self.output / "RPC01.reply.original").read_bytes(), raw)
        self.assertEqual(client.facts["metadata_bytes"], 2 * (len(request) + len(raw)))
        self.assertTrue(client.facts["rpc"][0]["complete"])
        self.assertTrue(sock.closed)
        self.assertEqual(sock.connected, "/run/docker.sock")
        self.assertTrue(all(0 < value <= 19 for value in sock.timeouts))

    def test_request_body_serialization_and_safe_percent_path(self):
        sock = FakeSocket(reply())
        client = self.client(sock)
        client.request("POST", "/containers/create?name=fixture%2D01", {"a": 1})
        self.assertIn(b"Content-Type: application/json\r\n", sock.sent)
        self.assertTrue(sock.sent.endswith(b'{"a":1}'))

    def test_chunked_reply_preserves_chunk_framing(self):
        raw = b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n2\r\n{\"\r\n5\r\nx\":1}\r\n0\r\n\r\n"
        client = self.client(FakeSocket(raw))
        self.assertEqual(client.request("GET", "/info"), {"x": 1})
        self.assertEqual((self.output / "RPC01.reply.original").read_bytes(), raw)

    def test_private_decoder_preserves_the_existing_json_and_null_contract(self):
        client = self.client()
        self.assertIsNone(client._reply_body_limit("GET", "/info", 200, {}))
        for status, raw, expected in ((200, b'{}', {}), (200, b'[]', []),
                                      (200, b'null', None), (204, b'', None)):
            with self.subTest(status=status, raw=raw):
                self.assertEqual(client._decode_reply(status, raw, method="GET", path="/info", fields={}), expected)
        for raw in (b'1', b'true', b'"text"', b'{"x":1,"x":2}', b'{"x":NaN}', b'\xff'):
            with self.subTest(raw=raw):
                with self.assertRaises(compiler.FixtureCompilerError) as found:
                    client._decode_reply(200, raw, method="GET", path="/info", fields={})
                self.assertIn("docker_http_json", found.exception.causes)

    def test_private_archive_decoder_keeps_raw_originals_and_default_metadata_json(self):
        archive_path = "/containers/" + "a" * 64 + "/archive?path=%2Ffixed"
        archive = b"\x00\xfffixed archive bytes"
        class ArchiveClient(compiler._DockerClientV1):
            def _reply_body_limit(self, method, selected_path, status, fields):
                return len(archive) if method == "GET" and selected_path == archive_path else None
            def _decode_reply(self, status, data, *, method, path, fields):
                if method == "GET" and path == archive_path:
                    return data
                return super()._decode_reply(status, data, method=method, path=path, fields=fields)
        raw = reply(archive)
        sock = FakeSocket(raw)
        client = self.client(sock, FakeSocket(reply(b'{"ID":"held"}')), cls=ArchiveClient)
        self.assertEqual(client.request("GET", archive_path), archive)
        self.assertEqual((self.output / "RPC01.reply.original").read_bytes(), raw)
        self.assertEqual(client.facts["metadata_bytes"], 2 * (len(sock.sent) + len(raw)))
        self.assertTrue(client.facts["rpc"][0]["complete"])
        self.assertTrue(client.facts["rpc"][0]["reply_eof"])
        self.assertEqual(client.request("GET", "/info"), {"ID": "held"})

    def test_private_body_limit_refuses_length_and_cumulative_chunk_before_body_read(self):
        class LimitedClient(compiler._DockerClientV1):
            def _reply_body_limit(self, method, path, status, fields):
                return 5
            def _decode_reply(self, status, data, *, method, path, fields):
                raise AssertionError("oversized response reached decoder")
        bodies = (
            (reply(b"123456"), b"123456"),
            (b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n3\r\n123\r\n3\r\n456\r\n0\r\n\r\n",
             b"456\r\n0\r\n\r\n"),
        )
        for raw, unread in bodies:
            with self.subTest(raw=raw), tempfile.TemporaryDirectory() as tmp:
                self.output = Path(tmp).resolve()
                sock = FakeSocket(raw)
                client = self.client(sock, cls=LimitedClient)
                self.refused(client, "GET", "/info", cause="docker_http_body_cap")
                self.assertEqual(bytes(sock.data), unread)
                self.assertEqual((self.output / "RPC01.reply.original").read_bytes(), raw[:-len(unread)])
                self.assertTrue(sock.closed)

    def test_private_raw_decoder_cannot_bypass_http_status_eof_or_persistence(self):
        decoded = []
        class RawClient(compiler._DockerClientV1):
            def _decode_reply(self, status, data, *, method, path, fields):
                decoded.append(data)
                return data
        for raw, cause in ((reply(b"raw", status=b"500 Error"), "docker_http_status"),
                            (reply(b"raw") + b"extra", "docker_http_extra")):
            with self.subTest(cause=cause), tempfile.TemporaryDirectory() as tmp:
                self.output = Path(tmp).resolve()
                self.refused(self.client(FakeSocket(raw), cls=RawClient), "GET", "/info", cause=cause)
                self.assertEqual(decoded, [])
        self.output = Path(self.tmp.name).resolve()
        client = self.client(FakeSocket(reply(b"raw")), cls=RawClient)
        original = Path.open
        def opener(path, *args, **kwargs):
            file = original(path, *args, **kwargs)
            return FaultFile(file, flush_fail=True) if path.name.endswith("reply.original") else file
        with patch.object(Path, "open", opener):
            self.refused(client, "GET", "/info", cause="docker_reply_flush_OSError")
        self.assertEqual(decoded, [])

    def test_bad_headers_protocol_and_framing_refuse(self):
        cases = (
            b"HTTP/1.0 200 OK\r\nContent-Length: 2\r\n\r\n{}",
            reply(headers=b"Content-Length: 2\r\n"),
            reply(headers=b"Transfer-Encoding: chunked\r\n"),
            reply(headers=b"Content-Encoding: gzip\r\n"),
            b"HTTP/1.1 200 OK\r\nBad : value\r\nContent-Length: 2\r\n\r\n{}",
            b"HTTP/1.1 200 OK\r\nTransfer-Encoding: gzip\r\n\r\n",
        )
        for number, raw in enumerate(cases):
            with self.subTest(number=number), tempfile.TemporaryDirectory() as tmp:
                self.output = Path(tmp).resolve()
                client = self.client(FakeSocket(raw))
                self.refused(client, "GET", "/info", cause="docker_http_headers")

    def test_chunk_extensions_trailers_and_excess_body_refuse(self):
        for payload in (b"2;x=1\r\n{}\r\n0\r\n\r\n", b"2\r\n{}\r\n0\r\nX: a\r\n\r\n"):
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as tmp:
                self.output = Path(tmp).resolve()
                client = self.client(FakeSocket(b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n" + payload))
                self.refused(client, "GET", "/info", cause="docker_http_chunk")
        self.output = Path(self.tmp.name).resolve()
        client = self.client(FakeSocket(reply() + b"extra"))
        self.refused(client, "GET", "/info", cause="docker_http_extra")

    def test_error_status_and_invalid_json_keep_exact_original(self):
        raw = reply(b'{"message":"original"}', status=b"500 Error")
        client = self.client(FakeSocket(raw))
        self.refused(client, "GET", "/info", cause="docker_http_status")
        self.assertEqual((self.output / "RPC01.reply.original").read_bytes(), raw)
        self.assertEqual(client.facts["rpc"][0]["status"], 500)

    def test_duplicate_json_and_truncation_fail_without_erasing_prefix(self):
        raw = reply(b'{"x":1,"x":2}')
        client = self.client(FakeSocket(raw))
        self.refused(client, "GET", "/info", cause="docker_http_json")
        self.assertEqual((self.output / "RPC01.reply.original").read_bytes(), raw)
        with tempfile.TemporaryDirectory() as tmp:
            self.output = Path(tmp).resolve()
            raw = reply(b"123")[:-1]
            client = self.client(FakeSocket(raw))
            self.refused(client, "GET", "/info", cause="docker_http_truncated")
            self.assertEqual((self.output / "RPC01.reply.original").read_bytes(), raw)

    def test_header_bound_retains_no_more_than_8192_bytes(self):
        client = self.client(FakeSocket(b"HTTP/1.1 200 OK\r\nX: " + b"a" * 9000))
        self.refused(client, "GET", "/info", cause="docker_http_header_cap")
        self.assertLessEqual((self.output / "RPC01.reply.original").stat().st_size, 8192)

    def test_ordinary_reserve_and_cleanup_hard_limit(self):
        client = self.client(FakeSocket(reply()))
        client.facts["metadata_bytes"] = 192 * 1024
        self.refused(client, "GET", "/info", cause="docker_metadata_cap")
        # A sticky failure allows only explicitly marked containment/inspection.
        self.assertEqual(client.request("GET", "/info", cleanup=True), {})
        client.facts["metadata_bytes"] = 256 * 1024
        self.refused(client, "GET", "/info", cleanup=True, cause="docker_metadata_cap")

    def test_maximum_sealed_twenty_three_calls(self):
        client = self.client(*(FakeSocket(reply()) for _ in range(23)))
        for _ in range(23):
            self.assertEqual(client.request("GET", "/info"), {})
        self.refused(client, "GET", "/info", cause="docker_rpc_cap")
        self.assertEqual(client.facts["attempts"], 23)

    def test_cleanup_does_not_convert_its_own_failure_to_success(self):
        client = self.client(FakeSocket(reply(b'{"x":1,"x":2}')))
        self.refused(client, "GET", "/info", cleanup=True, cause="docker_http_json")

    def test_deadline_before_connect_and_late_reply_refuse(self):
        sock = FakeSocket(reply())
        client = self.client(sock, deadline=self.now[0])
        self.refused(client, "GET", "/info", cause="docker_deadline")
        self.assertIsNone(sock.connected)
        with tempfile.TemporaryDirectory() as tmp:
            self.output = Path(tmp).resolve()
            sock = FakeSocket(reply())
            sock.on_read = lambda: self.now.__setitem__(0, 30_000_000_000)
            client = self.client(sock)
            self.refused(client, "GET", "/info", cause="docker_deadline")

    def test_peer_uid_and_epoch_drift_fail_closed(self):
        client = self.client(FakeSocket(reply(), uid=1000))
        self.refused(client, "GET", "/info", cause="docker_peer")
        with tempfile.TemporaryDirectory() as tmp:
            self.output = Path(tmp).resolve()
            client = self.client(FakeSocket(reply()))
            with patch.object(client, "_observe_endpoint", side_effect=[self.epoch, ((9,),)]):
                self.refused(client, "GET", "/info", cause="docker_socket_drift")

    def test_endpoint_metadata_kind_owner_permissions_and_symlinks(self):
        client = self.client(FakeSocket(reply()))
        metadata = {
            "/": types.SimpleNamespace(st_mode=0o40755, st_uid=0, st_gid=0, st_dev=1, st_ino=1, st_ctime_ns=1),
            "/run": types.SimpleNamespace(st_mode=0o40755, st_uid=0, st_gid=0, st_dev=1, st_ino=2, st_ctime_ns=2),
            "/run/docker.sock": types.SimpleNamespace(st_mode=0o140660, st_uid=0, st_gid=998, st_dev=1, st_ino=3, st_ctime_ns=3),
        }
        observe = type(client)._observe_endpoint
        with patch.object(compiler.os, "lstat", side_effect=lambda path: metadata[path]):
            self.assertEqual(len(observe(client)), 3)
            for path, field, value in (("/run", "st_uid", 1000), ("/run", "st_mode", 0o41777),
                                       ("/run/docker.sock", "st_mode", 0o140666),
                                       ("/run/docker.sock", "st_mode", 0o120777)):
                old = getattr(metadata[path], field)
                setattr(metadata[path], field, value)
                with self.assertRaises(compiler.FixtureCompilerError):
                    observe(client)
                setattr(metadata[path], field, old)

    def test_send_failure_and_close_failure_keep_first_and_secondary(self):
        client = self.client(FakeSocket(reply(), fail_send=True, fail_close=True))
        error = self.refused(client, "GET", "/info")
        self.assertEqual(error.causes[:2], ["docker_io_OSError", "docker_socket_close_OSError"])
        self.assertNotIn("private", str(error))
        self.assertTrue(client.facts["rpc"][0]["request_persisted"])
        self.assertFalse(client.facts["rpc"][0]["request_send_complete"])
        self.assertEqual(client.facts["rpc"][0]["causes"], error.causes)

    def test_exclusive_original_and_invalid_call_refuse_before_socket(self):
        sock = FakeSocket(reply())
        client = self.client(sock)
        (self.output / "RPC01.request.original").write_bytes(b"held")
        self.refused(client, "GET", "/info")
        self.assertEqual((self.output / "RPC01.request.original").read_bytes(), b"held")
        self.assertIsNone(sock.connected)
        for method, path in (("DELETE", "/containers/id"), ("GET", "/info\r\nX: x"),
                             ("GET", "http://foreign/info"), ("GET", "/info bad")):
            with self.subTest(path=path):
                with self.assertRaises(compiler.FixtureCompilerError):
                    client.request(method, path, cleanup=True)

    def test_upgrade_does_not_read_body_and_duplex_is_bounded(self):
        headers = b"HTTP/1.1 101 UPGRADED\r\nConnection: Upgrade\r\nUpgrade: tcp\r\n\r\n"
        sock = FakeSocket(headers + b"frame")
        client = self.client(sock)
        stream = client.request("POST", "/containers/" + "a" * 64 + "/attach?stream=1&stdin=1&stdout=1&stderr=1", upgrade=True)
        self.assertFalse(sock.closed)
        self.assertEqual(bytes(sock.data), b"frame")
        self.assertEqual((self.output / "RPC01.reply.original").read_bytes(), headers)
        stream.arm_data_deadline(client.deadline)
        stream.sendall(b"fixed input")
        stream.shutdown_write()
        self.assertEqual(stream.read(3), b"fra")
        self.assertEqual(stream.read(9), b"me")
        self.assertEqual(stream.read(1), b"")
        self.assertTrue(sock.write_shutdown)
        self.assertEqual(stream.facts["received_bytes"], 5)
        stream.close()
        self.assertTrue(sock.closed)

    def test_upgrade_requires_101_and_valid_upgrade_headers(self):
        client = self.client(FakeSocket(reply()))
        self.refused(client, "POST", "/containers/id/attach", upgrade=True,
                     cause="docker_http_upgrade")

    def test_body_prebound_rejects_huge_scalar_without_sending(self):
        sock = FakeSocket(reply())
        client = self.client(sock)
        self.refused(client, "POST", "/containers/create", {"x": "a" * 150000})
        self.assertIsNone(sock.connected)

    def test_clock_regression_refuses_and_closes_owned_socket(self):
        sock = FakeSocket(reply())
        sock.on_read = lambda: self.now.__setitem__(0, 0)
        client = self.client(sock)
        self.refused(client, "GET", "/info", cause="docker_clock")
        self.assertTrue(sock.closed)
        self.assertEqual((self.output / "RPC01.reply.original").read_bytes(), b"H")

    def test_reply_persistence_failure_never_parses_or_returns_success(self):
        client = self.client(FakeSocket(reply()))
        original = compiler.os.fsync
        calls = [0]
        def failing(fd):
            calls[0] += 1
            if calls[0] == 2:
                raise OSError("private persistence detail")
            return original(fd)
        with patch.object(compiler.os, "fsync", side_effect=failing):
            self.refused(client, "GET", "/info", cause="docker_reply_fsync_OSError")
        self.assertFalse(client.facts["rpc"][0]["complete"])

    def test_attach_close_reports_drift_but_still_closes_its_resource(self):
        raw = b"HTTP/1.1 101 UPGRADED\r\nConnection: Upgrade\r\nUpgrade: tcp\r\n\r\n"
        sock = FakeSocket(raw)
        client = self.client(sock)
        stream = client.request("POST", "/containers/id/attach", upgrade=True)
        with patch.object(client, "_observe_endpoint", return_value=((9,),)):
            with self.assertRaises(compiler.FixtureCompilerError) as found:
                stream.close()
        self.assertIn("docker_socket_drift", found.exception.causes)
        self.assertTrue(sock.closed)

    def fault_open(self, suffix, **options):
        original = Path.open
        def opened(path, *args, **kwargs):
            file = original(path, *args, **kwargs)
            return FaultFile(file, **options) if path.name.endswith(suffix) else file
        return patch.object(Path, "open", opened)

    def test_short_request_reports_confirmed_prefix_and_no_send(self):
        sock = FakeSocket(reply())
        client = self.client(sock)
        with self.fault_open(".request.original", short=True):
            self.refused(client, "GET", "/info", cause="docker_request_short_write")
        row = client.facts["rpc"][0]
        self.assertEqual(row.get("request_written_bytes"), 2)
        self.assertEqual(row.get("request_persisted_bytes"), 2)
        self.assertIs(row.get("request_write_extent_unknown"), False)
        self.assertGreater(row["request_bytes"], 2)
        self.assertIsNone(sock.connected)

    def test_short_reply_reports_observed_written_and_persisted_prefixes(self):
        raw = reply(b'{"x":1}')
        header = raw.index(b"\r\n\r\n") + 4
        client = self.client(FakeSocket(raw))
        with self.fault_open(".reply.original", short=True):
            self.refused(client, "GET", "/info", cause="docker_reply_short_write")
        row = client.facts["rpc"][0]
        self.assertEqual(row["reply_observed_bytes"], len(raw))
        self.assertEqual(row.get("reply_written_bytes"), header + 2)
        self.assertEqual(row.get("reply_persisted_bytes"), header + 2)
        self.assertIs(row.get("reply_write_extent_unknown"), False)
        self.assertEqual((self.output / "RPC01.reply.original").stat().st_size, header + 2)

    def test_unreturned_reply_extent_and_distinct_close_preserve_primary(self):
        raw = reply(b'{"x":1}')
        header = raw.index(b"\r\n\r\n") + 4
        client = self.client(FakeSocket(raw))
        with self.fault_open(".reply.original", unreturned=True, close_fail=True):
            error = self.refused(client, "GET", "/info")
        row = client.facts["rpc"][0]
        self.assertEqual(error.causes[0], "docker_reply_write_OSError")
        self.assertIn("docker_reply_close_OSError", error.causes)
        self.assertIs(row.get("reply_write_extent_unknown"), True)
        self.assertEqual(row.get("reply_written_bytes"), header)
        self.assertEqual(row.get("reply_persisted_bytes"), header)
        self.assertGreater((self.output / "RPC01.reply.original").stat().st_size, header)

    def test_unreturned_request_write_reports_unknown_without_wire_send(self):
        sock = FakeSocket(reply())
        client = self.client(sock)
        with self.fault_open(".request.original", unreturned=True, close_fail=True):
            error = self.refused(client, "GET", "/info")
        row = client.facts["rpc"][0]
        self.assertEqual(error.causes[0], "docker_request_write_OSError")
        self.assertIn("docker_request_close_OSError", error.causes)
        self.assertEqual(row.get("request_written_bytes"), 0)
        self.assertEqual(row.get("request_persisted_bytes"), 0)
        self.assertIs(row.get("request_write_extent_unknown"), True)
        self.assertIsNone(sock.connected)

    def test_attach_data_deadline_is_once_armed_and_may_exceed_handshake(self):
        headers = b"HTTP/1.1 101 UPGRADED\r\nConnection: Upgrade\r\nUpgrade: tcp\r\n\r\n"
        sock = FakeSocket(headers + b"x")
        client = self.client(sock, deadline=150_000_000_000)
        stream = client.request("POST", "/containers/id/attach", deadline_ns=10_000_000_000, upgrade=True)
        arm = getattr(stream, "arm_data_deadline", None)
        self.assertTrue(callable(arm), "attach phase cannot be armed separately")
        arm(70_000_000_000)
        self.now[0] = 11_000_000_000
        self.assertEqual(stream.read(1), b"x")
        self.assertGreater(sock.timeouts[-1], 10)
        with self.assertRaises(compiler.FixtureCompilerError):
            arm(80_000_000_000)
        self.assertEqual(stream.facts["data_deadline_ns"], 70_000_000_000)
        stream.close()

    def test_attach_refuses_unarmed_data_and_owner_deadline_expansion(self):
        headers = b"HTTP/1.1 101 UPGRADED\r\nConnection: Upgrade\r\nUpgrade: tcp\r\n\r\n"
        sock = FakeSocket(headers + b"held")
        client = self.client(sock)
        stream = client.request("POST", "/containers/id/attach", upgrade=True)
        arm = getattr(stream, "arm_data_deadline", None)
        self.assertTrue(callable(arm), "attach phase cannot be armed separately")
        with self.assertRaises(compiler.FixtureCompilerError):
            stream.read(1)
        self.assertEqual(bytes(sock.data), b"held")
        with self.assertRaises(compiler.FixtureCompilerError):
            arm(client.deadline + 1)
        stream.close()

    def test_short_write_flush_and_close_causes_remain_distinct(self):
        client = self.client(FakeSocket(reply()))
        with self.fault_open(".request.original", short=True, flush_fail=True, close_fail=True):
            error = self.refused(client, "GET", "/info")
        self.assertEqual(error.causes, ["docker_request_short_write", "docker_request_flush_OSError",
                                        "docker_request_close_OSError"])
        row = client.facts["rpc"][0]
        self.assertEqual(row["request_written_bytes"], 2)
        self.assertEqual(row["request_persisted_bytes"], 0)
        self.assertTrue(row["request_persistence_failed"])
        self.assertFalse(row["request_persisted"])

    def test_failed_initial_flush_is_not_retried_by_finalization(self):
        client = self.client(FakeSocket(reply()))
        original, files = Path.open, []
        def opened(path, *args, **kwargs):
            file = original(path, *args, **kwargs)
            if path.name.endswith(".request.original"):
                file = FaultFile(file, flush_fail=True)
                files.append(file)
            return file
        with patch.object(Path, "open", opened):
            self.refused(client, "GET", "/info", cause="docker_request_flush_OSError")
        self.assertEqual(files[0].flush_count, 1)
        self.assertEqual(client.facts["rpc"][0]["request_persisted_bytes"], 0)

    def test_attach_armed_deadline_expires_without_consuming_late_data(self):
        headers = b"HTTP/1.1 101 UPGRADED\r\nConnection: Upgrade\r\nUpgrade: tcp\r\n\r\n"
        sock = FakeSocket(headers + b"held")
        client = self.client(sock)
        stream = client.request("POST", "/containers/id/attach", upgrade=True)
        stream.arm_data_deadline(15_000_000_000)
        self.now[0] = 15_000_000_000
        with self.assertRaises(compiler.FixtureCompilerError) as found:
            stream.read(1)
        self.assertIn("docker_deadline", found.exception.causes)
        self.assertEqual(bytes(sock.data), b"held")
        with self.assertRaises(compiler.FixtureCompilerError):
            stream.close()
        self.assertTrue(sock.closed)

    def test_observed_attach_prefix_survives_postrecv_deadline_and_sticks(self):
        headers = b"HTTP/1.1 101 UPGRADED\r\nConnection: Upgrade\r\nUpgrade: tcp\r\n\r\n"
        sock = FakeSocket(headers + b"xyz")
        client = self.client(sock)
        stream = client.request("POST", "/containers/id/attach", upgrade=True)
        stream.arm_data_deadline(15_000_000_000)
        sock.on_read = lambda: self.now.__setitem__(0, 15_000_000_000)
        observed = None
        try:
            observed = stream.read(3)
        except compiler.FixtureCompilerError:
            pass
        with self.assertRaises(compiler.FixtureCompilerError) as next_read:
            stream.read(1)
        with self.assertRaises(compiler.FixtureCompilerError) as closed:
            stream.close()
        self.assertEqual(observed, b"xyz", "already-observed bytes must reach the prefix capture")
        self.assertEqual(stream.facts["received_bytes"], 3)
        self.assertIn("docker_deadline", next_read.exception.causes)
        self.assertIn("docker_deadline", closed.exception.causes)
        self.assertTrue(sock.closed and stream.facts["closed"])

    def test_observed_attach_prefix_cannot_hide_failure_by_closing_without_next_read(self):
        headers = b"HTTP/1.1 101 UPGRADED\r\nConnection: Upgrade\r\nUpgrade: tcp\r\n\r\n"
        sock = FakeSocket(headers + b"held")
        client = self.client(sock)
        stream = client.request("POST", "/containers/id/attach", upgrade=True)
        stream.arm_data_deadline(15_000_000_000)
        sock.on_read = lambda: self.now.__setitem__(0, 15_000_000_000)
        observed = None
        try:
            observed = stream.read(4)
        except compiler.FixtureCompilerError:
            pass
        with self.assertRaises(compiler.FixtureCompilerError) as closed:
            stream.close()
        self.assertEqual(observed, b"held")
        self.assertIn("docker_deadline", closed.exception.causes)
        self.assertTrue(sock.closed)

    def test_rpc_final_flush_fsync_file_and_socket_close_cannot_accept_late_completion(self):
        for phase in ("flush", "fsync", "file_close", "socket_close"):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as tmp:
                self.output = Path(tmp).resolve()
                self.now[0] = 1_000_000_000
                now, deadline = self.now, 20_000_000_000
                class LateSocket(FakeSocket):
                    def close(self):
                        super().close()
                        if phase == "socket_close":
                            now[0] = deadline
                sock = LateSocket(reply())
                client = self.client(sock, deadline=deadline)
                original_open, original_fsync = Path.open, compiler.os.fsync
                syncs = [0]
                class LateFile(FaultFile):
                    def __init__(self, file, role):
                        super().__init__(file)
                        self.role = role
                    def flush(self):
                        result = super().flush()
                        if phase == "flush" and self.role == "request" and self.flush_count == 2:
                            now[0] = deadline
                        return result
                    def close(self):
                        super().close()
                        if phase == "file_close" and self.role == "reply":
                            now[0] = deadline
                def opened(path, *args, **kwargs):
                    file = original_open(path, *args, **kwargs)
                    return LateFile(file, "request" if path.name.endswith(".request.original") else "reply")
                def sync(fd):
                    result = original_fsync(fd)
                    syncs[0] += 1
                    if phase == "fsync" and syncs[0] == 4:
                        now[0] = deadline
                    return result
                with patch.object(Path, "open", opened), patch.object(compiler.os, "fsync", sync):
                    error = self.refused(client, "GET", "/info", cause="docker_deadline")
                row = error.facts["rpc"][0]
                self.assertFalse(row["complete"])
                self.assertTrue(row["request_persisted"] and row["reply_persisted"])
                self.assertTrue(row["request_close_completed"] and row["reply_close_completed"])
                self.assertTrue(sock.closed and row["socket_closed"])

    def test_attach_final_socket_close_keeps_closed_fact_but_refuses_late_completion(self):
        headers = b"HTTP/1.1 101 UPGRADED\r\nConnection: Upgrade\r\nUpgrade: tcp\r\n\r\n"
        now = self.now
        class LateSocket(FakeSocket):
            def close(self):
                super().close()
                now[0] = 15_000_000_000
        sock = LateSocket(headers)
        client = self.client(sock)
        stream = client.request("POST", "/containers/id/attach", upgrade=True)
        stream.arm_data_deadline(15_000_000_000)
        with self.assertRaises(compiler.FixtureCompilerError) as found:
            stream.close()
        self.assertIn("docker_deadline", found.exception.causes)
        self.assertTrue(sock.closed and stream.facts["closed"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
