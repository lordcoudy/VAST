"""Controlled F2 recovery tests: no Docker, compiler or process action."""
import base64
import hashlib
import importlib
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from tests.fixtures import accepted_policy_fixture_compiler_v1 as compiler
from tests.test_accepted_policy_fixture_compiler_transport_v1 import FakeSocket, FaultFile, reply

LIBC_SCRIPT = (b"/* GNU ld script\n   Use the shared library, but some functions are only in\n"
               b"   the static library, so try that secondarily.  */\nOUTPUT_FORMAT(elf64-x86-64)\n"
               b"GROUP ( /lib/x86_64-linux-gnu/libc.so.6 /usr/lib/x86_64-linux-gnu/libc_nonshared.a  "
               b"AS_NEEDED ( /lib64/ld-linux-x86-64.so.2 ) )\n")
GCC_SCRIPT = (b"/* GNU ld script\n   Use the shared library, but some functions are only in\n"
              b"   the static library.  */\nGROUP ( libgcc_s.so.1 -lgcc )\n")

try:
    recovery = importlib.import_module("tests.fixtures.accepted_policy_fixture_compiler_recovery_v1")
except ModuleNotFoundError:
    recovery = None


def tar_bytes(name, raw, *, kind=tarfile.REGTYPE, extra=None, pax=None):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w", format=tarfile.PAX_FORMAT) as archive:
        info = tarfile.TarInfo(name)
        info.size, info.type = len(raw), kind
        if pax:
            info.pax_headers = pax
        archive.addfile(info, io.BytesIO(raw) if kind == tarfile.REGTYPE else None)
        if extra:
            other = tarfile.TarInfo(extra)
            archive.addfile(other, io.BytesIO())
    return output.getvalue()


def stat_header(name, size, **changed):
    value = {"name": name, "size": size, "mode": 0o644,
             "mtime": "2026-10-16T00:00:00Z", "linkTarget": ""}
    value.update(changed)
    return "X-Docker-Container-Path-Stat: " + base64.b64encode(json.dumps(value).encode()).decode() + "\r\n"


def c75_inspect_reply():
    """Exact observed reply, derived in memory; no second raw fixture/copy."""
    path = ROOT / "openspec/changes/fix-accepted-policy-preprocessing/evidence/compiler-component-01/b1-01/outputs/RPC10.reply.original"
    raw = path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == recovery.B1_ORIGINAL_SHA256["inspect"]
    for old, new in ((b'"Dns":null', b'"Dns":[]'), (b'"DnsOptions":null', b'"DnsOptions":[]'),
                     (b'"DnsSearch":null', b'"DnsSearch":[]'),
                     (b'Date: Fri, 16 Oct 2026 08:38:03 GMT', b'Date: Fri, 16 Oct 2026 17:08:35 GMT'),
                     (b'\r\n\r\n6619\r\n', b'\r\n\r\n6613\r\n')):
        assert raw.count(old) == 1
        raw = raw.replace(old, new)
    assert hashlib.sha256(raw).hexdigest() == "58b2b00a2efb0331e734eb5af5146115f64c6f1a788f0ed48175dd3aab9ef086"
    return raw


def maximal_footer():
    counters = ("retained_elsewhere_upper_bytes", "raw_originals_bytes", "retained_allocated_bytes",
                "physical_charge_bytes", "retained_data_allocated_bytes", "retained_metadata_upper_bytes",
                "reserved_control_bytes", "reserved_raw_bytes", "reserved_rounding_bytes",
                "reserved_metadata_bytes", "retained_elsewhere_lower_bytes")
    account = {key: 2**64-1 for key in counters}
    for phase in ("baseline", "last"):
        account[phase] = {"c_free_bytes": 2**64-1, "ext4_used_bytes": 2**64-1, "fragment_bytes": 4096}
    return {"schema_version": 1, "supplement": {"relative_path": "f2.supplement.v1.json",
            "size_bytes": 262144, "sha256": "f"*64}, "accounting": account}


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(recovery, "fixed F2 recovery helper is absent")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.now = [1_000_000_000]
        self.epoch = ((1, 2, 0, 0, 0o140660, 17),)
        self.baseline = {"c_free_bytes": 100_000_000_000, "ext4_used_bytes": 1000, "fragment_bytes": 4096}

    def client(self, *sockets):
        output = self.root / "http"
        output.mkdir()
        items = iter(sockets)
        value = recovery._ArchiveClientV1(output, 91_000_000_000,
                    socket_factory=lambda: next(items), clock=lambda: self.now[0])
        observe = patch.object(value, "_observe_endpoint", return_value=self.epoch)
        observe.start()
        self.addCleanup(observe.stop)
        return value

    def test_fixed_inventory_and_limits(self):
        self.assertEqual(len(recovery.MEMBERS), 13)
        self.assertEqual(sum(row[1] for row in recovery.MEMBERS), 4_088_780)
        self.assertEqual(sum(row[2] for row in recovery.MEMBERS), 4_226_048)
        self.assertEqual(recovery._ArchiveClientV1.RPC_LIMIT, 19)
        self.assertEqual(compiler._DockerClientV1.LIMIT, 262144)
        self.assertEqual((recovery.TOTAL_LIMIT, recovery.ACTIVE_F2_LIMIT, recovery.RAW_LIMIT,
                          recovery.TAR_LIMIT, recovery._ArchiveClientV1.LIMIT),
                         (8388608, 7995392, 6291456, 4226048, 12582912))
        self.assertEqual(dict(recovery.CONTROL_CAPS), {"f2.originals.v1.json": 262144,
                         "f2.supplement.v1.json": 262144, "f2.failure.v1.json": 262144,
                         "f2.final-accounting.v1.json": 16384})

    def test_tar_single_regular_member_and_bounded_pax(self):
        raw = b"\x7fELF\x02\x01" + b"\0" * 12 + b"\x3e\0" + b"x" * 20
        value = recovery._tar_member(tar_bytes("member.o", raw, pax={"mtime": "1.25"}),
                                     "member.o", len(raw), True)
        self.assertEqual(value["sha256"], hashlib.sha256(raw).hexdigest())
        self.assertTrue(value["elf64_amd64"])

    def test_tar_refuses_other_members_paths_links_and_sparse_metadata(self):
        for payload in (tar_bytes("../member", b"x"), tar_bytes("/member", b"x"),
                        tar_bytes("member", b"x", extra="other"),
                        tar_bytes("member", b"", kind=tarfile.SYMTYPE),
                        tar_bytes("member", b"x", pax={"GNU.sparse.size": "1"})):
            with self.subTest(prefix=payload[:20]), self.assertRaises(compiler.FixtureCompilerError):
                recovery._tar_member(payload, "member", 1, False)

    def test_tar_refuses_truncation_wrong_size_abi_and_trailing_content(self):
        valid = tar_bytes("member", b"x")
        for payload, size, elf in ((valid[:-1], 1, False), (valid, 2, False),
                                  (valid, 1, True), (valid + b"x" + b"\0" * 511, 1, False)):
            with self.subTest(size=size, elf=elf), self.assertRaises(compiler.FixtureCompilerError):
                recovery._tar_member(payload, "member", size, elf)

    def test_stat_uses_go_file_mode_regular_not_posix_type_bits(self):
        for mode in (0o644, 0o755):
            self.assertEqual(recovery._path_stat(stat_header("member", 1, mode=mode), "member", 1)["mode"], mode)
        for flag in (31, 27, 26, 25, 24, 21, 19):
            with self.subTest(flag=flag), self.assertRaises(compiler.FixtureCompilerError):
                recovery._path_stat(stat_header("member", 1, mode=0o644 | (1 << flag)), "member", 1)

    def test_stat_refuses_bad_encoding_duplicates_and_name_size_link_drift(self):
        for header in ("X-Docker-Container-Path-Stat: !!!\r\n", stat_header("other", 1),
                       stat_header("member", 2), stat_header("member", 1, linkTarget="other"),
                       "X-Docker-Container-Path-Stat: " + base64.b64encode(b'{"name":"a","name":"b"}').decode()+"\r\n"):
            with self.subTest(header=header), self.assertRaises(compiler.FixtureCompilerError):
                recovery._path_stat(header, "member", 1)

    def test_archive_refuses_inventory_drift_and_does_not_send_a_mutation(self):
        sock = FakeSocket(reply())
        client = self.client(sock)
        for args in (("POST", "/version"), ("GET", "/info"), ("GET", "/containers/foreign/archive?path=x")):
            with self.assertRaises(compiler.FixtureCompilerError):
                client.request(*args)
        self.assertEqual(sock.sent, b"")

    def test_archive_prebody_cap_keeps_only_header_on_oversized_length(self):
        sockets = [FakeSocket(reply()), FakeSocket(reply()), FakeSocket(reply())]
        name, size, cap, _ = recovery.MEMBERS[0]
        raw = reply(b"x" * (cap+1), headers=stat_header(Path(name).name, size).encode())
        sock = FakeSocket(raw)
        client = self.client(*sockets, sock)
        for path in recovery.IDENTITY_PATHS:
            client.request("GET", path)
        with self.assertRaises(compiler.FixtureCompilerError):
            client.request("GET", recovery.ARCHIVE_PATHS[0])
        original = (client.output / "RPC04.reply.original").read_bytes()
        self.assertTrue(original.endswith(b"\r\n\r\n"))
        self.assertEqual(len(sock.data), cap+1)

    def test_chunk_cap_is_checked_before_chunk_body_and_aggregate_does_not_expand(self):
        name, size, cap, _ = recovery.MEMBERS[0]
        header = b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n" + stat_header(Path(name).name, size).encode() + b"\r\n"
        payload = header + ("%x\r\n" % (cap+1)).encode() + b"held"
        client = self.client(*(FakeSocket(reply()) for _ in range(3)), FakeSocket(payload))
        for path in recovery.IDENTITY_PATHS:
            client.request("GET", path)
        with self.assertRaises(compiler.FixtureCompilerError):
            client.request("GET", recovery.ARCHIVE_PATHS[0])
        self.assertTrue((client.output / "RPC04.reply.original").read_bytes().endswith(("%x\r\n" % (cap+1)).encode()))

    def test_archive_bytes_return_only_with_complete_framing_and_originals(self):
        name, size, _, _ = recovery.MEMBERS[0]
        body = tar_bytes(Path(name).name, b"x"*size)
        client = self.client(*(FakeSocket(reply()) for _ in range(3)),
                             FakeSocket(reply(body, headers=stat_header(Path(name).name, size).encode())))
        for path in recovery.IDENTITY_PATHS:
            client.request("GET", path)
        self.assertEqual(client.request("GET", recovery.ARCHIVE_PATHS[0]), body)
        self.assertEqual(client.decoded_tar_bytes, len(body))
        self.assertTrue(client.facts["rpc"][-1]["complete"])

    def test_five_second_deadline_and_whole_sequence_epoch_drift(self):
        sock = FakeSocket(reply())
        client = self.client(sock, FakeSocket(reply()))
        client.request("GET", "/version")
        self.assertTrue(all(value <= 5 for value in sock.timeouts))
        with patch.object(client, "_observe_endpoint", return_value=((9,),)):
            with self.assertRaises(compiler.FixtureCompilerError):
                client.request("GET", "/info")

    def test_package_reader_labels_metadata_and_rejects_duplicates(self):
        status = b"Package: gcc-11\nStatus: install ok installed\nArchitecture: amd64\nVersion: 11.4\n\n"
        result = recovery._packages(status)
        self.assertEqual(result["gcc-11:amd64"], "11.4")
        self.assertEqual(recovery._packages(status.replace(b"Version: 11.4\n", b"Version: 11.4\nConffiles:\n /etc/controlled 000 obsolete\n")), result)
        with self.assertRaises(compiler.FixtureCompilerError):
            recovery._packages(status + status)
        with self.assertRaises(compiler.FixtureCompilerError):
            recovery._packages(status.replace(b"Version: 11.4", b"Version: 11.4\nVersion: 11.5"))

    def test_md5_reader_refuses_traversal_duplicate_and_invalid_lines(self):
        raw = b"0123456789abcdef0123456789abcdef  usr/lib/member\n"
        self.assertEqual(recovery._md5_associations(raw)["/usr/lib/member"], "0123456789abcdef0123456789abcdef")
        for invalid in (raw+raw, raw.replace(b"usr/lib", b"../lib"), b"invalid\n"):
            with self.assertRaises(compiler.FixtureCompilerError):
                recovery._md5_associations(invalid)

    def test_linker_scripts_must_match_original_hash_before_reference_interpretation(self):
        for path in ("/usr/lib/x86_64-linux-gnu/libc.so", "/usr/lib/gcc/x86_64-linux-gnu/11/libgcc_s.so"):
            with self.assertRaises(compiler.FixtureCompilerError):
                recovery._linker_references(path, b"GROUP ( /foreign )\n")

    def test_preencoding_bound_and_exclusive_persistence_preserve_original(self):
        path = self.root / "record.json"
        with self.assertRaises(compiler.FixtureCompilerError):
            recovery._write_json(path, {"huge": "x" * (262144+1)})
        self.assertFalse(path.exists())
        recovery._write_json(path, {"held": True})
        old = path.read_bytes()
        with self.assertRaises(compiler.FixtureCompilerError):
            recovery._write_json(path, {"held": False})
        self.assertEqual(path.read_bytes(), old)

    def full_fixture(self, *, initial_inspect=None, final_inspect=None):
        old = ROOT / "openspec/changes/fix-accepted-policy-preprocessing/evidence/compiler-component-01/b1-01/outputs"
        identities = [(old/name).read_bytes() for name in ("RPC01.reply.original", "RPC02.reply.original", "RPC10.reply.original")]
        archives = []
        for path, size, cap, elf in recovery.MEMBERS:
            prefix = b"\x7fELF\x02\x01"+b"\0"*12+b"\x3e\0" if elf else b""
            data = prefix+b"x"*(size-len(prefix))
            if path == recovery.MEMBERS[6][0]:
                data = LIBC_SCRIPT
            if path == recovery.MEMBERS[7][0]:
                data = GCC_SCRIPT
            if path == recovery.MEMBERS[8][0]:
                selected = b"".join(("Package: %s\nStatus: install ok installed\nArchitecture: amd64\nVersion: controlled\n\n" % item).encode()
                                    for item in ("gcc-11", "cpp-11", "libc6", "libgcc-s1"))
                data = selected+b" "+b"x"*(size-len(selected)-2)+b"\n"
            if path in {row[0] for row in recovery.MEMBERS[9:12]}:
                blocks, left, number = [], size, 0
                while left:
                    length = min(left, 4096)
                    if 0 < left-length < 64:
                        length -= 64
                    prefix = b"0"*32+("  usr/filler-%d-" % number).encode()
                    blocks.append(prefix+b"x"*(length-len(prefix)-1)+b"\n")
                    left, number = left-length, number+1
                data = b"".join(blocks)
            self.assertEqual(len(data), size)
            body = tar_bytes(Path(path).name, data)[:512+((size+511)//512)*512+1024]
            self.assertLessEqual(len(body), cap)
            archives.append(reply(body, headers=stat_header(Path(path).name, size).encode()))
        first, last = list(identities), list(identities)
        if initial_inspect is not None:
            first[2] = initial_inspect
        if final_inspect is not None:
            last[2] = final_inspect
        sockets = [FakeSocket(raw) for raw in first+archives+last]
        originals = {"report": old/"compiler.stdout.original", "inspect": old/"RPC10.reply.original",
                     "provider": old/"RPC03.reply.original"}
        arguments = {"output_dir": self.root/"f2", "review": {"commit": "a"*40,
                     "approval_reference": "controlled-test-only", "physical_plan_sha256": "b"*64},
                     "b1_originals": originals, "remaining_seal_bytes": recovery.ACTIVE_F2_LIMIT,
                     "clock": lambda: self.now[0], "measure": lambda: dict(self.baseline),
                     "socket_factory": iter(sockets).__next__}
        return sockets, arguments

    def test_all_nineteen_fixed_requests_bind_raw_originals_and_exact_saved_supplement(self):
        sockets, arguments = self.full_fixture()
        with patch.object(recovery._ArchiveClientV1, "_observe_endpoint", return_value=self.epoch):
            result = recovery.recover_stopped_b1_v1(**arguments)
        root = arguments["output_dir"]
        saved = json.loads((root/"f2.supplement.v1.json").read_bytes())
        self.assertEqual(result["supplement"], saved)
        self.assertTrue(saved["complete"])
        self.assertTrue(saved["controlled"])
        self.assertEqual(len(saved["members"]), 13)
        self.assertEqual(saved["transport"]["attempts"], 19)
        self.assertEqual(saved["identity"]["before"], saved["identity"]["after"])
        index = json.loads((root/"f2.originals.v1.json").read_bytes())
        self.assertEqual(len(index["originals"]), 38)
        self.assertTrue(all(row["relative_path"].startswith("RPC") for row in index["originals"]))
        self.assertEqual(len(list(root.iterdir())), 41)
        self.assertTrue(all(sock.closed for sock in sockets))
        self.assertTrue(all(bytes(sock.sent).startswith(b"GET ") for sock in sockets))

    def test_failed_archive_keeps_prefix_and_failure_receipt_without_retry(self):
        sockets, arguments = self.full_fixture()
        sockets[3] = FakeSocket(reply(b"held", headers=stat_header("wrong", 1656).encode()))
        arguments["socket_factory"] = iter(sockets).__next__
        with patch.object(recovery._ArchiveClientV1, "_observe_endpoint", return_value=self.epoch):
            with self.assertRaises(compiler.FixtureCompilerError) as found:
                recovery.recover_stopped_b1_v1(**arguments)
        self.assertFalse(found.exception.facts["complete"])
        root = arguments["output_dir"]
        self.assertTrue((root/"f2.failure.v1.json").exists())
        self.assertTrue((root/"RPC04.reply.original").read_bytes().endswith(b"\r\n\r\n"))
        self.assertFalse((root/"RPC05.request.original").exists())
        self.assertTrue(all(not sock.sent for sock in sockets[4:]))

    def test_no_remaining_seal_or_foreign_original_stops_before_fresh_output(self):
        for changed in ({"remaining_seal_bytes": recovery.ACTIVE_F2_LIMIT-1},
                        {"b1_originals": {"report": __file__, "inspect": __file__, "provider": __file__}},
                        {"measure": lambda: {"ext4_used_bytes": 1000, "c_free_bytes": recovery.FLOOR_BYTES}}):
            sockets, arguments = self.full_fixture()
            arguments.update(changed)
            with self.subTest(changed=list(changed)), self.assertRaises(compiler.FixtureCompilerError):
                recovery.recover_stopped_b1_v1(**arguments)
            self.assertFalse(arguments["output_dir"].exists())
            self.assertTrue(all(not sock.sent for sock in sockets))

    def test_actual_physical_growth_stops_before_next_archive(self):
        sockets, arguments = self.full_fixture()
        calls = [0]
        def measured():
            calls[0] += 1
            return {"ext4_used_bytes": self.baseline["ext4_used_bytes"]+(recovery.TOTAL_LIMIT if calls[0] >= 4 else 0),
                    "c_free_bytes": self.baseline["c_free_bytes"]}
        arguments["measure"] = measured
        with patch.object(recovery._ArchiveClientV1, "_observe_endpoint", return_value=self.epoch):
            with self.assertRaises(compiler.FixtureCompilerError):
                recovery.recover_stopped_b1_v1(**arguments)
        self.assertFalse((arguments["output_dir"]/"f2.failure.v1.json").exists())
        self.assertFalse((arguments["output_dir"]/"RPC05.request.original").exists())

    def test_record_flush_failure_retains_prefix_and_does_not_reopen(self):
        target = self.root/"record.json"
        opened = []
        real = Path.open
        def fault(path, *args, **kwargs):
            file = real(path, *args, **kwargs)
            if path == target:
                opened.append(file)
                return FaultFile(file, flush_fail=True)
            return file
        with patch.object(Path, "open", fault), self.assertRaises(compiler.FixtureCompilerError):
            recovery._write_json(target, {"value": "retained"})
        self.assertEqual(len(opened), 1)
        self.assertTrue(target.read_bytes())

    def test_aggregate_cap_status_and_reply_persistence_fail_before_body_use(self):
        path, size, _, _ = recovery.MEMBERS[0]
        body = tar_bytes(Path(path).name, b"x"*size)
        for mode in ("aggregate", "status", "persistence"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                self.root = Path(tmp).resolve()
                status = b"404 Missing" if mode == "status" else b"200 OK"
                sock = FakeSocket(reply(body, status=status, headers=stat_header(Path(path).name, size).encode()))
                client = self.client(*(FakeSocket(reply()) for _ in range(3)), sock)
                for item in recovery.IDENTITY_PATHS:
                    client.request("GET", item)
                if mode == "aggregate":
                    client.decoded_tar_bytes = recovery.TAR_LIMIT-1
                real = Path.open
                def fault(target, *args, **kwargs):
                    file = real(target, *args, **kwargs)
                    return FaultFile(file, flush_fail=True) if mode == "persistence" and target.name == "RPC04.reply.original" else file
                with patch.object(Path, "open", fault), self.assertRaises(compiler.FixtureCompilerError):
                    client.request("GET", recovery.ARCHIVE_PATHS[0])
                self.assertEqual(client.decoded_tar_bytes, recovery.TAR_LIMIT-1 if mode == "aggregate" else 0)
                self.assertEqual(bytes(sock.data), body)

    def test_package_supplement_keeps_embedded_and_package_versions_separate(self):
        self.assertEqual(hashlib.sha256(LIBC_SCRIPT).hexdigest(), recovery.SCRIPT_SHA256[recovery.MEMBERS[6][0]])
        self.assertEqual(hashlib.sha256(GCC_SCRIPT).hexdigest(), recovery.SCRIPT_SHA256[recovery.MEMBERS[7][0]])
        raws = {row[0]: b"" for row in recovery.MEMBERS}
        raws[recovery.MEMBERS[6][0]], raws[recovery.MEMBERS[7][0]] = LIBC_SCRIPT, GCC_SCRIPT
        raws[recovery.MEMBERS[3][0]] = b"prefix\0GNU C Library controlled banner\0"
        raws[recovery.MEMBERS[8][0]] = b"".join(("Package: %s\nStatus: install ok installed\nArchitecture: amd64\nVersion: controlled\n\n" % name).encode() for name in ("gcc-11", "cpp-11", "libc6", "libgcc-s1"))
        report = {"report": {"toolchain": {"helpers": {}}}}
        facts = recovery._package_facts(raws, report)
        self.assertEqual(facts["libc_banner"]["kind"], "embedded_bytes_not_execution")
        self.assertEqual(facts["installed_versions"]["cpp-11:amd64"], "controlled")
        self.assertNotIn("cc1_version", facts)

    def test_supplement_validator_is_read_only_and_refuses_controlled_qualification(self):
        self.assertTrue(callable(getattr(recovery, "validate_supplement_v1", None)), "independent F2 validator absent")
        sockets, arguments = self.full_fixture()
        with patch.object(recovery._ArchiveClientV1, "_observe_endpoint", return_value=self.epoch), \
                patch.object(recovery, "_package_facts", return_value={"controlled_package_reader": True}):
            result = recovery.recover_stopped_b1_v1(**arguments)
        with patch.object(compiler.socket, "socket", side_effect=AssertionError("validator contacted Docker")):
            with self.assertRaises(compiler.FixtureCompilerError):
                recovery.validate_supplement_v1(output_dir=arguments["output_dir"], supplement=result["supplement"])

    def test_absolute_ninety_second_deadline_has_no_new_window_after_binding(self):
        sockets, arguments = self.full_fixture()
        count = [0]
        def clock():
            count[0] += 1
            return 1_000_000_000 if count[0] == 1 else 91_000_000_000
        arguments["clock"] = clock
        with self.assertRaises(compiler.FixtureCompilerError):
            recovery.recover_stopped_b1_v1(**arguments)
        self.assertTrue(all(not sock.sent for sock in sockets))

    def validator_fixture(self, **kwargs):
        """Construct a physical-shaped record for parser tests, never qualification."""
        sockets, arguments = self.full_fixture(**kwargs)
        with patch.object(recovery._ArchiveClientV1, "_observe_endpoint", return_value=self.epoch):
            result = recovery.recover_stopped_b1_v1(**arguments)
        value = result["supplement"]
        value["controlled"] = False
        value["transport"]["controlled_socket"] = False
        value["transport"]["controlled_clock"] = False
        self.replace_supplement(arguments["output_dir"], value)
        return arguments["output_dir"], value

    def replace_supplement(self, root, value):
        (root/"f2.supplement.v1.json").write_bytes(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())
        footer = json.loads((root/"f2.final-accounting.v1.json").read_bytes())
        footer["supplement"] = recovery._descriptor(root/"f2.supplement.v1.json", root)
        (root/"f2.final-accounting.v1.json").write_bytes(json.dumps(footer, sort_keys=True, separators=(",", ":")).encode())

    def test_validator_rereads_all_originals_and_preserves_their_bytes(self):
        root, value = self.validator_fixture()
        before = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in root.iterdir()}
        with patch.object(compiler.socket, "socket", side_effect=AssertionError("unexpected socket")):
            result = recovery.validate_supplement_v1(output_dir=root, supplement=value)
        self.assertTrue(result["complete"])
        self.assertEqual(result["members"], 13)
        self.assertEqual(before, {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in root.iterdir()})

    def test_validator_refuses_rehashed_member_claim_or_unknown_closure(self):
        for mode in ("member", "closure", "index", "footer", "extra"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                self.root = Path(tmp).resolve()
                root, value = self.validator_fixture()
                if mode == "member":
                    value["members"][0]["sha256"] = "0"*64
                if mode == "closure":
                    value["transport"]["rpc"][4]["reply_eof"] = False
                self.replace_supplement(root, value)
                if mode == "index":
                    (root/"RPC04.reply.original").write_bytes(b"changed")
                if mode == "footer":
                    footer = json.loads((root/"f2.final-accounting.v1.json").read_bytes())
                    footer["supplement"]["sha256"] = "0"*64
                    (root/"f2.final-accounting.v1.json").write_bytes(json.dumps(footer).encode())
                if mode == "extra":
                    (root/"foreign").write_bytes(b"preserve")
                with self.assertRaises(compiler.FixtureCompilerError):
                    recovery.validate_supplement_v1(output_dir=root, supplement=value)

    def test_derived_record_unknown_extent_and_close_failure_are_explicit(self):
        target = self.root/"unknown.json"
        real = Path.open
        def fault(path, *args, **kwargs):
            file = real(path, *args, **kwargs)
            return FaultFile(file, unreturned=True, close_fail=True) if path == target else file
        with patch.object(Path, "open", fault), self.assertRaises(compiler.FixtureCompilerError) as found:
            recovery._write_json(target, {"value": "retained"})
        self.assertTrue(found.exception.facts["write_extent_unknown"])
        self.assertFalse(found.exception.facts["complete"])
        self.assertFalse(found.exception.facts["close_completed"])
        self.assertEqual(found.exception.facts["persisted_bytes"], 0)
        self.assertIn("f2_record_close_OSError", found.exception.causes)
        self.assertTrue(target.read_bytes())

    def test_observed_stopped_source_size_drift_refuses(self):
        sockets, _ = self.full_fixture()
        values = [recovery._http_json(bytes(sock.data)) for sock in sockets[:3]]
        sealed = json.loads(json.dumps(values[2]))
        values[2]["SizeRw"] += 4096
        with self.assertRaises(compiler.FixtureCompilerError):
            recovery._identity(*values, sealed)

    def test_validator_recomputes_largest_physical_charge(self):
        root, value = self.validator_fixture()
        footer = json.loads((root/"f2.final-accounting.v1.json").read_bytes())
        footer["accounting"]["last"]["ext4_used_bytes"] += recovery.TOTAL_LIMIT
        (root/"f2.final-accounting.v1.json").write_bytes(json.dumps(footer).encode())
        with self.assertRaises(compiler.FixtureCompilerError):
            recovery.validate_supplement_v1(output_dir=root, supplement=value)

    def test_control_close_after_original_deadline_cannot_pass_or_start_failure_file(self):
        sockets, arguments = self.full_fixture()
        real = Path.open
        class LateClose(FaultFile):
            def close(inner):
                inner.file.close()
                self.now[0] = 91_000_000_000
        def opened(path, *args, **kwargs):
            file = real(path, *args, **kwargs)
            return LateClose(file) if path.name == "f2.final-accounting.v1.json" and args and args[0] == "xb" else file
        with patch.object(recovery._ArchiveClientV1, "_observe_endpoint", return_value=self.epoch), patch.object(Path, "open", opened):
            with self.assertRaises(compiler.FixtureCompilerError) as found:
                recovery.recover_stopped_b1_v1(**arguments)
        self.assertFalse(found.exception.facts["complete"])
        self.assertFalse((arguments["output_dir"]/"f2.failure.v1.json").exists())
        self.assertTrue((arguments["output_dir"]/"f2.final-accounting.v1.json").read_bytes())

    def test_final_bounded_reread_has_after_read_check_and_no_grace_write(self):
        sockets, arguments = self.full_fixture()
        real, reads = recovery._read_bounded, [0]
        def read(path, *args, **kwargs):
            data = real(path, *args, **kwargs)
            if Path(path).name == "f2.supplement.v1.json":
                reads[0] += 1
                if reads[0] == 2:
                    self.now[0] = 91_000_000_000
            return data
        with patch.object(recovery._ArchiveClientV1, "_observe_endpoint", return_value=self.epoch), patch.object(recovery, "_read_bounded", read):
            with self.assertRaises(compiler.FixtureCompilerError) as found:
                recovery.recover_stopped_b1_v1(**arguments)
        self.assertFalse(found.exception.facts["complete"])
        self.assertEqual(reads[0], 2)
        self.assertFalse((arguments["output_dir"]/"f2.failure.v1.json").exists())

    def test_allocation_lower_bound_includes_file_and_directory_metadata(self):
        sockets, arguments = self.full_fixture()
        with patch.object(recovery._ArchiveClientV1, "_observe_endpoint", return_value=self.epoch):
            result = recovery.recover_stopped_b1_v1(**arguments)
        footer = json.loads((arguments["output_dir"]/"f2.final-accounting.v1.json").read_bytes())
        account = footer["accounting"]
        self.assertGreaterEqual(account["retained_metadata_upper_bytes"], 41*4096)
        self.assertEqual(account["retained_allocated_bytes"],
                         account["retained_data_allocated_bytes"]+account["retained_metadata_upper_bytes"])
        self.assertGreaterEqual(account["physical_charge_bytes"], account["retained_allocated_bytes"])

    def test_internal_native_deadline_guard_does_not_mislabel_real_clock(self):
        sockets, arguments = self.full_fixture()
        arguments["clock"] = None
        with patch.object(recovery._ArchiveClientV1, "_observe_endpoint", return_value=self.epoch):
            result = recovery.recover_stopped_b1_v1(**arguments)
        self.assertFalse(result["supplement"]["transport"]["controlled_clock"])
        self.assertTrue(result["supplement"]["controlled"])

    def test_output_must_share_root_filesystem_and_four_kib_fragment(self):
        self.assertTrue(callable(getattr(recovery, "_output_filesystem_v1", None)), "output filesystem binding absent")
        real = recovery.os.stat
        class ForeignRoot:
            st_dev = -1
        def observed(path, *args, **kwargs):
            return ForeignRoot() if Path(path) == Path("/") else real(path, *args, **kwargs)
        with patch.object(recovery.os, "stat", observed), self.assertRaises(compiler.FixtureCompilerError):
            recovery._output_filesystem_v1(self.root)

    def test_unfunded_report_git_control_forms_refuse_before_directory_or_rpc(self):
        sockets, arguments = self.full_fixture()
        arguments["retained_elsewhere_upper_bytes"] = 0
        with patch.object(recovery._ArchiveClientV1, "_observe_endpoint", return_value=self.epoch), self.assertRaises(compiler.FixtureCompilerError):
            recovery.recover_stopped_b1_v1(**arguments)
        self.assertFalse(arguments["output_dir"].exists())
        self.assertTrue(all(not sock.sent for sock in sockets))

    def test_exact_c75_chunked_dns_reply_and_actual_digest_complete_the_sequence(self):
        raw = c75_inspect_reply()
        sockets, arguments = self.full_fixture(initial_inspect=raw, final_inspect=raw)
        with patch.object(recovery._ArchiveClientV1, "_observe_endpoint", return_value=self.epoch):
            result = recovery.recover_stopped_b1_v1(**arguments)
        identity = result["supplement"]["identity"]
        self.assertEqual(identity["before"], identity["after"])
        self.assertEqual(identity["before"]["source_sha256"], "32c7886c0c8afd213b4e858d1da035cc22d532782bb23019886f71416395fc13")
        self.assertEqual((arguments["output_dir"]/"RPC03.reply.original").read_bytes(), raw)
        self.assertEqual(result["supplement"]["transport"]["attempts"], 19)
        self.assertTrue(all(sock.closed for sock in sockets))

    def test_dns_compatibility_requires_present_sealed_null_typed_empty_and_none_network(self):
        sockets, _ = self.full_fixture()
        values = [recovery._http_json(bytes(sock.data)) for sock in sockets[:3]]
        sealed = values[2]
        for key in ("Dns", "DnsOptions", "DnsSearch"):
            for bad in (False, 0, "", {}, ["foreign"], [None]):
                inspected = json.loads(json.dumps(sealed)); inspected["HostConfig"][key] = bad
                with self.subTest(key=key, bad=bad), self.assertRaises(compiler.FixtureCompilerError):
                    recovery._identity(values[0], values[1], inspected, sealed)
            for mode in ("missing_both", "missing_fresh", "missing_sealed", "sealed_list", "network"):
                old = json.loads(json.dumps(sealed)); inspected = json.loads(json.dumps(sealed))
                if mode.startswith("missing"):
                    if mode in ("missing_both", "missing_sealed"): del old["HostConfig"][key]
                    if mode in ("missing_both", "missing_fresh"): del inspected["HostConfig"][key]
                elif mode == "sealed_list":
                    old["HostConfig"][key] = []; inspected["HostConfig"][key] = []
                else:
                    old["HostConfig"]["NetworkMode"] = "bridge"; inspected["HostConfig"]["NetworkMode"] = "bridge"
                with self.subTest(key=key, mode=mode), self.assertRaises(compiler.FixtureCompilerError):
                    recovery._identity(values[0], values[1], inspected, old)
        for group, key, bad in (("HostConfig", "CapAdd", None), ("HostConfig", "ReadonlyPaths", []),
                                ("Config", "User", "0:0"), ("State", "ExitCode", 1)):
            inspected = recovery._http_json(c75_inspect_reply()); inspected[group][key] = bad
            with self.subTest(group=group, key=key), self.assertRaises(compiler.FixtureCompilerError):
                recovery._identity(values[0], values[1], inspected, sealed)

    def test_fresh_dns_representation_drift_refuses_after_nineteen_requests(self):
        sockets, arguments = self.full_fixture(initial_inspect=c75_inspect_reply())
        with patch.object(recovery._ArchiveClientV1, "_observe_endpoint", return_value=self.epoch), \
                self.assertRaises(compiler.FixtureCompilerError) as caught:
            recovery.recover_stopped_b1_v1(**arguments)
        self.assertIn("f2_final_identity", caught.exception.causes)
        self.assertEqual(caught.exception.facts["transport"]["attempts"], 19)
        self.assertNotEqual(caught.exception.facts["identity"]["before"], caught.exception.facts["identity"]["after"])
        self.assertFalse((arguments["output_dir"]/"f2.supplement.v1.json").exists())

    def test_c75_dns_validator_rereads_actual_raw_digest_without_socket_or_mutation(self):
        raw = c75_inspect_reply()
        root, value = self.validator_fixture(initial_inspect=raw, final_inspect=raw)
        before = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in root.iterdir()}
        with patch.object(compiler.socket, "socket", side_effect=AssertionError("validator contacted engine")):
            self.assertTrue(recovery.validate_supplement_v1(output_dir=root, supplement=value)["complete"])
        self.assertEqual(before, {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in root.iterdir()})

    def test_maximal_closed_footer_canonical_934_is_separate_from_conservative_bound(self):
        value = maximal_footer()
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
        self.assertEqual(len(raw), 934)
        self.assertLessEqual(recovery._record_bound(value), 16384)
        path = self.root/"f2.final-accounting.v1.json"
        descriptor = recovery._write_json(path, value)
        self.assertEqual(path.read_bytes(), raw)
        self.assertEqual(descriptor["size_bytes"], 934)

    def test_malformed_footer_refuses_before_encoding_and_open(self):
        base = maximal_footer()
        cases = []
        for key, bad in (("schema_version", True), ("schema_version", 1.0), ("extra", "x"*16385)):
            value = json.loads(json.dumps(base)); value[key] = bad; cases.append(value)
        for phase in ("baseline", "last"):
            for key, bad in (("fragment_bytes", 4096.0), ("fragment_bytes", True),
                             ("c_free_bytes", -1), ("ext4_used_bytes", 2**64), ("extra", 0)):
                value = json.loads(json.dumps(base)); value["accounting"][phase][key] = bad; cases.append(value)
        for key, bad in (("relative_path", "../f2.supplement.v1.json"), ("size_bytes", True),
                         ("size_bytes", 262145), ("sha256", "A"*64), ("extra", 0)):
            value = json.loads(json.dumps(base)); value["supplement"][key] = bad; cases.append(value)
        for key, bad in (("extra", 0), ("reserved_control_bytes", True), ("raw_originals_bytes", 2**64)):
            value = json.loads(json.dumps(base)); value["accounting"][key] = bad; cases.append(value)
        for location, key in (((), "accounting"), (("supplement",), "sha256"),
                              (("accounting",), "reserved_raw_bytes"), (("accounting", "last"), "fragment_bytes")):
            value = json.loads(json.dumps(base)); parent = value
            for item in location: parent = parent[item]
            del parent[key]; cases.append(value)
        for number, value in enumerate(cases):
            path = self.root/"f2.final-accounting.v1.json"
            with self.subTest(number=number), patch.object(recovery.json, "dumps") as encoded, \
                    patch.object(Path, "open") as opened:
                with self.assertRaises(compiler.FixtureCompilerError):
                    recovery._write_json(path, value)
                encoded.assert_not_called(); opened.assert_not_called()

    def test_footer_validator_rejects_closed_schema_noncanonical_and_duplicate_keys(self):
        root, value = self.validator_fixture()
        path = root/"f2.final-accounting.v1.json"; original = path.read_bytes(); footer = json.loads(original)
        changed = []
        for key, bad in (("schema_version", True), ("schema_version", 1.0), ("extra", 0)):
            row = json.loads(original); row[key] = bad; changed.append(json.dumps(row, sort_keys=True, separators=(",", ":")).encode())
        for group, key, bad in (("last", "fragment_bytes", 4096.0), ("baseline", "extra", 0),
                                 ("last", "c_free_bytes", 2**64)):
            row = json.loads(original); row["accounting"][group][key] = bad
            changed.append(json.dumps(row, sort_keys=True, separators=(",", ":")).encode())
        changed += [json.dumps(footer, indent=1).encode(), original.replace(b'"schema_version":1', b'"schema_version":1,"schema_version":1'),
                    b" "*16385]
        for number, raw in enumerate(changed):
            path.write_bytes(raw)
            with self.subTest(number=number), self.assertRaises(compiler.FixtureCompilerError):
                recovery.validate_supplement_v1(output_dir=root, supplement=value)
            self.assertEqual(path.read_bytes(), raw)

    def test_per_file_entry_geometry_and_full_partial_footer_failure_liability(self):
        sockets, arguments = self.full_fixture()
        arguments["remaining_seal_bytes"] = 7995392
        with patch.object(recovery._ArchiveClientV1, "request", side_effect=compiler.FixtureCompilerError("controlled_stop")), \
                self.assertRaises(compiler.FixtureCompilerError) as stopped:
            recovery.recover_stopped_b1_v1(**arguments)
        account = stopped.exception.facts["accounting"]
        self.assertEqual(account["reserved_control_bytes"], 3*262144+16384)
        self.assertEqual(account["physical_charge_bytes"]+sum(account[key] for key in
            ("reserved_control_bytes", "reserved_raw_bytes", "reserved_rounding_bytes", "reserved_metadata_bytes")), 7970816)

    def test_partial_footer_keeps_prefix_full_failure_reserve_and_distinct_close_cause(self):
        sockets, arguments = self.full_fixture(); real = Path.open
        def opened(path, *args, **kwargs):
            file = real(path, *args, **kwargs)
            return FaultFile(file, short=True, close_fail=True) if path.name == "f2.final-accounting.v1.json" and args and args[0] == "xb" else file
        with patch.object(recovery._ArchiveClientV1, "_observe_endpoint", return_value=self.epoch), patch.object(Path, "open", opened), \
                self.assertRaises(compiler.FixtureCompilerError) as caught:
            recovery.recover_stopped_b1_v1(**arguments)
        root = arguments["output_dir"]
        self.assertEqual((root/"f2.final-accounting.v1.json").read_bytes(), b'{"')
        self.assertTrue((root/"f2.failure.v1.json").exists())
        self.assertEqual(caught.exception.facts["accounting"]["reserved_control_bytes"], 262144)
        self.assertIn("f2_record_short_write", caught.exception.causes)
        self.assertIn("f2_record_close_OSError", caught.exception.causes)

    def test_nonfooter_controls_keep_their_existing_record_cap(self):
        for name in ("f2.originals.v1.json", "f2.supplement.v1.json", "f2.failure.v1.json"):
            value = {"retained": "x"*20000}; path = self.root/name
            recovery._write_json(path, value)
            self.assertGreater(path.stat().st_size, 16384)
            self.assertEqual(json.loads(path.read_bytes()), value)

    def test_other_inspect_json_types_and_selected_fields_remain_exact(self):
        sockets, _ = self.full_fixture()
        version, info, sealed = [recovery._http_json(bytes(sock.data)) for sock in sockets[:3]]
        for group, key, bad in (("State", "ExitCode", False), ("HostConfig", "Memory", 536870912.0),
                                 ("Config", "NetworkDisabled", 1), (None, "RestartCount", False),
                                 (None, "Image", "sha256:"+"0"*64), (None, "Id", "0"*64),
                                 (None, "Mounts", []), (None, "SizeRootFs", sealed["SizeRootFs"]+1)):
            inspected = recovery._http_json(c75_inspect_reply())
            (inspected[group] if group else inspected)[key] = bad
            with self.subTest(group=group, key=key), self.assertRaises(compiler.FixtureCompilerError):
                recovery._identity(version, info, inspected, sealed)

    def test_malformed_state_object_is_a_bounded_source_refusal(self):
        sockets, _ = self.full_fixture()
        version, info, sealed = [recovery._http_json(bytes(sock.data)) for sock in sockets[:3]]
        inspected = recovery._http_json(c75_inspect_reply()); inspected["State"] = ["foreign"]
        with self.assertRaises(compiler.FixtureCompilerError) as caught:
            recovery._identity(version, info, inspected, sealed)
        self.assertIn("f2_source_state", caught.exception.causes)

    def test_each_empty_dns_representation_hashes_actual_values_without_input_mutation(self):
        sockets, _ = self.full_fixture()
        version, info, sealed = [recovery._http_json(bytes(sock.data)) for sock in sockets[:3]]
        original = json.dumps(sealed, sort_keys=True); hashes = set()
        for mask in range(8):
            inspected = json.loads(original)
            for bit, key in enumerate(("Dns", "DnsOptions", "DnsSearch")):
                inspected["HostConfig"][key] = [] if mask & (1 << bit) else None
            before = json.dumps(inspected, sort_keys=True)
            hashes.add(recovery._identity(version, info, inspected, sealed)["source_sha256"])
            self.assertEqual(json.dumps(inspected, sort_keys=True), before)
        self.assertEqual(len(hashes), 8); self.assertEqual(json.dumps(sealed, sort_keys=True), original)
        self.assertIn("32c7886c0c8afd213b4e858d1da035cc22d532782bb23019886f71416395fc13", hashes)

    def test_footer_descriptor_and_copy_quotes_reject_oversized_retained_prefix(self):
        path = self.root/"f2.final-accounting.v1.json"; path.write_bytes(b"x"*16385)
        with self.assertRaises(compiler.FixtureCompilerError): recovery._descriptor(path, self.root)
        with self.assertRaises(compiler.FixtureCompilerError): recovery._outside_copy_lower_bound(self.root)
        self.assertEqual(path.stat().st_size, 16385)

    def test_successor_active_limit_refuses_one_byte_excess_before_rpc_or_failure_write(self):
        sockets, arguments = self.full_fixture(); count = [0]
        def measured():
            count[0] += 1; value = dict(self.baseline)
            # At entry future liability is7438336 and outside524288. A32768
            # byte delta exactly consumes7995392; one byte more must refuse.
            if count[0] >= 2: value["ext4_used_bytes"] += 32769
            return value
        arguments["measure"] = measured
        with patch.object(recovery._ArchiveClientV1, "request") as rpc, self.assertRaises(compiler.FixtureCompilerError) as found:
            recovery.recover_stopped_b1_v1(**arguments)
        rpc.assert_not_called()
        self.assertIn("f2_physical_or_logical_bound", found.exception.causes)
        self.assertFalse((arguments["output_dir"]/"f2.failure.v1.json").exists())

    def test_post_footer_unknown_measurement_does_not_start_failure_persistence(self):
        sockets, arguments = self.full_fixture(); path = arguments["output_dir"]/"f2.final-accounting.v1.json"
        def measured():
            if path.exists(): raise OSError("controlled unavailable final measurement")
            return dict(self.baseline)
        arguments["measure"] = measured
        with patch.object(recovery._ArchiveClientV1, "_observe_endpoint", return_value=self.epoch), \
                self.assertRaises(compiler.FixtureCompilerError) as found:
            recovery.recover_stopped_b1_v1(**arguments)
        self.assertFalse(found.exception.facts["complete"])
        self.assertEqual(found.exception.facts["failure_record_not_started"], "reservation_unavailable")
        self.assertTrue(path.exists()); self.assertFalse((path.parent/"f2.failure.v1.json").exists())

    def test_partial_unknown_footer_then_floor_denial_keeps_prefix_without_fresh_failure_write(self):
        sockets, arguments = self.full_fixture(); real = Path.open
        path = arguments["output_dir"]/"f2.final-accounting.v1.json"
        def measured():
            value = dict(self.baseline)
            if path.exists(): value["c_free_bytes"] = 0
            return value
        def opened(target, *args, **kwargs):
            file = real(target, *args, **kwargs)
            return FaultFile(file, unreturned=True) if target == path and args and args[0] == "xb" else file
        arguments["measure"] = measured
        with patch.object(recovery._ArchiveClientV1, "_observe_endpoint", return_value=self.epoch), \
                patch.object(Path, "open", opened), self.assertRaises(compiler.FixtureCompilerError) as caught:
            recovery.recover_stopped_b1_v1(**arguments)
        self.assertTrue(caught.exception.facts["failed_record"]["write_extent_unknown"])
        self.assertEqual(path.read_bytes(), b'{"')
        self.assertIn("f2_physical_or_logical_bound", caught.exception.causes)
        self.assertEqual(caught.exception.facts["failure_record_not_started"], "reservation_unavailable")
        self.assertFalse((path.parent/"f2.failure.v1.json").exists())

    def test_validator_enforces_active_cap_below_unchanged_combined_total(self):
        root, value = self.validator_fixture(); path = root/"f2.final-accounting.v1.json"
        footer = json.loads(path.read_bytes()); account = footer["accounting"]
        tail = 16384+262144+8192+8192
        self.assertEqual(account["reserved_control_bytes"], 16384+262144)
        charge = 7995392-tail+1
        self.assertLessEqual(charge+tail, 8388608)
        account["physical_charge_bytes"] = charge
        account["last"]["ext4_used_bytes"] = account["baseline"]["ext4_used_bytes"]+charge-account["retained_elsewhere_upper_bytes"]
        path.write_bytes(json.dumps(footer, sort_keys=True, separators=(",", ":")).encode())
        with self.assertRaises(compiler.FixtureCompilerError) as caught:
            recovery.validate_supplement_v1(output_dir=root, supplement=value)
        self.assertIn("f2_validation_accounting", caught.exception.causes)

    def test_footer_fsync_and_close_faults_preserve_original_and_full_failure_path(self):
        sockets, arguments = self.full_fixture(); real_open, real_sync = Path.open, recovery.os.fsync
        path = arguments["output_dir"]/"f2.final-accounting.v1.json"; descriptor = [None]
        def opened(target, *args, **kwargs):
            file = real_open(target, *args, **kwargs)
            if target == path and args and args[0] == "xb":
                descriptor[0] = file.fileno(); return FaultFile(file, close_fail=True)
            return file
        def synced(fd):
            if fd == descriptor[0]:
                descriptor[0] = None; raise OSError("controlled footer fsync")
            return real_sync(fd)
        with patch.object(recovery._ArchiveClientV1, "_observe_endpoint", return_value=self.epoch), \
                patch.object(Path, "open", opened), patch.object(recovery.os, "fsync", synced), \
                self.assertRaises(compiler.FixtureCompilerError) as caught:
            recovery.recover_stopped_b1_v1(**arguments)
        facts = caught.exception.facts
        self.assertTrue(path.read_bytes()); self.assertFalse(facts["failed_record"]["write_extent_unknown"])
        self.assertFalse(facts["failed_record"]["fsync_completed"]); self.assertFalse(facts["failed_record"]["close_completed"])
        self.assertIn("f2_record_OSError", caught.exception.causes); self.assertIn("f2_record_close_OSError", caught.exception.causes)
        self.assertEqual(facts["accounting"]["reserved_control_bytes"], 262144)
        self.assertTrue((path.parent/"f2.failure.v1.json").exists())


if __name__ == "__main__":
    unittest.main()
