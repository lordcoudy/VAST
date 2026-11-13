"""Controlled tests for the fresh direct gate-2 operator. No Docker, P0, WSL or native scope is touched."""
import base64
import copy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from tests.fixtures import accepted_policy_fixture_compiler_gate2_c_v1 as gate  # noqa: E402
from tests.fixtures import accepted_policy_fixture_compiler_gate2_fresh_v1 as fresh  # noqa: E402
from tests import test_accepted_policy_fixture_compiler_gate2_c_v1 as gate_tests  # noqa: E402  (module import: no re-discovery)

COMMIT = "e" * 40


def manifest_for(files):
    rows = {rel: fresh.blob(raw) for rel, raw in files.items()}
    return {"schema_version": 1, "commit": COMMIT, "files": rows}


class FreshOperatorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.files = {rel: ("# controlled " + rel + "\n").encode() for rel in fresh.EXPORT_CODE + (fresh.PLAN, fresh.OPERATOR)}
        self.manifest = manifest_for(self.files)
        self.raw = fresh.canonical(self.manifest)

    def test_paths_match_the_gate(self):
        self.assertEqual(fresh.EXPORT_CODE, gate.CODE_PATHS)
        self.assertLessEqual(set(gate.OPTIONAL_CODE_PATHS), set(gate.CODE_PATHS))
        self.assertEqual((fresh.PLAN, fresh.OPERATOR), (gate.FRESH_PLAN_V1, gate.FRESH_OPERATOR_V1))
        self.assertEqual(fresh.ROOT_PREFIX, gate.FRESH_ROOT_PREFIX_V1)
        self.assertEqual(fresh.RESUME_R1, str(gate.RESUME_ROOT_V1))
        self.assertEqual(fresh.INFO_REQUEST, b"GET /v1.55/info HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\nContent-Length: 0\r\n\r\n")

    def test_manifest_shape_and_row_binding(self):
        self.assertEqual(fresh.manifest_v1(self.raw, COMMIT), self.manifest)
        mutations = (lambda m: m.update(commit="f" * 40), lambda m: m.update(extra=0),
            lambda m: m["files"].pop(fresh.OPERATOR), lambda m: m["files"].update({"scripts/extra.py": m["files"][fresh.PLAN]}),
            lambda m: m["files"][fresh.PLAN].update(size_bytes=1.0), lambda m: m["files"][fresh.PLAN].update(git_blob="x"),
            lambda m: m.update(schema_version=True))
        for mutate in mutations:
            value = copy.deepcopy(self.manifest)
            mutate(value)
            with self.subTest(mutation=mutate), self.assertRaises(fresh.FreshRefusal):
                fresh.manifest_v1(fresh.canonical(value), COMMIT)
        with self.assertRaisesRegex(fresh.FreshRefusal, "json_duplicate_key"):
            fresh.manifest_v1(b'{"commit":1,"commit":2}', COMMIT)
        path = self.base / "f.py"
        path.write_bytes(self.files[fresh.PLAN])
        self.assertEqual(fresh.verified(str(path), self.manifest["files"][fresh.PLAN], 1024), self.files[fresh.PLAN])
        path.write_bytes(self.files[fresh.PLAN] + b"x")
        with self.assertRaisesRegex(fresh.FreshRefusal, "manifest_binding"):
            fresh.verified(str(path), self.manifest["files"][fresh.PLAN], 1024)
        link = self.base / "link.py"
        link.symlink_to(path)
        with self.assertRaisesRegex(fresh.FreshRefusal, "read_kind_bound"):
            fresh.read_once(str(link), 1024)

    def test_boot_executes_only_the_verified_bytes(self):
        copy_path = self.base / "operator.py"
        source = Path(fresh.__file__).read_bytes()
        copy_path.write_bytes(source)
        boot = fresh.BOOT.replace(
            "/mnt/c/Users/s-a-balashov/.codex/worktrees/fix-accepted-policy-preprocessing/VAST/tests/fixtures/accepted_policy_fixture_compiler_gate2_fresh_v1.py",
            str(copy_path))
        self.assertNotEqual(boot, fresh.BOOT)
        def run(size, digest):
            return subprocess.run([sys.executable, "-I", "-S", "-B", "-c", boot, "PRE", str(size), digest],
                input=b'{"remaining_ns":0}\n', capture_output=True, timeout=60)
        bad = run(len(source), "0" * 64)
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn(b"fresh_operator_binding", bad.stderr)
        good = run(len(source), hashlib.sha256(source).hexdigest())
        self.assertEqual(good.returncode, 1)
        self.assertEqual(json.loads(good.stderr)["cause"], "native_entry" if os.getuid() != 1000 else "native_budget")
        self.assertEqual(good.stdout, b"")

    def test_terminal_is_bounded_and_keeps_the_failure(self):
        raw = fresh.terminal_v1({"completed": False, "causes": ["x" * 64] * 100, "physical_acceptance": False})
        self.assertLessEqual(len(raw), fresh.TERMINAL_CAP + 1)
        value = json.loads(raw)
        self.assertFalse(value["completed"])
        self.assertTrue(value["causes_truncated"])

    def main_world(self, phases, p0_result=None):
        order, writes = [], []
        def phase(run, name, own, data):
            order.append(name)
            return phases[name](data) if callable(phases[name]) else phases[name]
        def dispatch(p0, output, binding, commit):
            order.append("P0")
            self.assertEqual(output, fresh.UNC + fresh.ROOT_PREFIX + COMMIT + "-01/p0")
            self.assertEqual(binding["provenance"], {"source": "external", "observer": "ordinary_api",
                "engine_id": "1e493309-3767-45fb-9078-05b838bdfd80", "boot_id": "b" * 36})
            return p0_result or {"completion_record": {"relative_path": "p0-completion.v1.json", "encoded_bytes": 2, "sha256": "a" * 64}}
        stack = [patch.object(fresh.os, "name", "nt"), patch.object(fresh, "read_once", return_value=self.raw),
            patch.object(fresh, "verified", return_value=b"# controlled\n"),
            patch.object(fresh, "load_verified_module", return_value=type("P0", (), {"KNOWN_ENGINE_ID": "1e493309-3767-45fb-9078-05b838bdfd80"})),
            patch.object(fresh.Path, "resolve", lambda self, *a, **k: fresh.REPO_WIN / fresh.OPERATOR),
            patch.object(fresh.Run, "phase", phase), patch.object(fresh, "dispatch_p0_v1", side_effect=dispatch),
            patch.object(fresh.os, "write", side_effect=lambda fd, raw: writes.append((fd, raw)) or len(raw))]
        for item in stack:
            item.start()
            self.addCleanup(item.stop)
        return order, writes

    PRE = {"boot_id": "b" * 36, "engine_id": "1e493309-3767-45fb-9078-05b838bdfd80", "counts": [3, 0, 0, 3],
        "measurement": {"c_free_bytes": 1, "ext4_used_bytes": 1}, "request_b64": "", "reply_b64": ""}

    def test_main_runs_pre_export_p0_packet_in_order_with_one_bounded_document(self):
        order, writes = self.main_world({"PRE": self.PRE, "EXPORT": {"files": 15},
            "PACKET": {"packet": {"size_bytes": 20000, "sha256": "d" * 64}, "charge": {"excess_bytes": 0}, "post_ok": True}})
        status = fresh.main(COMMIT, "https://github.com/lordcoudy/VAST/pull/9#issuecomment-1", "m.json", fresh.sha(self.raw),
            _original_start_ns=time.monotonic_ns())
        self.assertEqual(status, 0)
        self.assertEqual(order, ["PRE", "EXPORT", "P0", "PACKET"])
        self.assertEqual([fd for fd, _ in writes], [1])
        value = json.loads(writes[0][1])
        self.assertLessEqual(len(writes[0][1]), 2049)
        self.assertEqual((value["completed"], value["packet"]["sha256"], value["physical_acceptance"]), (True, "d" * 64, False))

    def test_main_reports_a_failed_post_check_as_incomplete(self):
        order, writes = self.main_world({"PRE": self.PRE, "EXPORT": {},
            "PACKET": {"packet": {"size_bytes": 1, "sha256": "d" * 64}, "charge": {}, "post_ok": False}})
        self.assertEqual(fresh.main(COMMIT, "a", "m.json", fresh.sha(self.raw), _original_start_ns=time.monotonic_ns()), 1)
        self.assertIn("fresh_post_check_failed", json.loads(writes[0][1])["causes"])

    def test_main_refuses_before_any_phase_or_after_pre(self):
        order, writes = self.main_world({"PRE": dict(self.PRE, counts=[4, 0, 0, 4]), "EXPORT": {}, "PACKET": {}})
        self.assertEqual(fresh.main(COMMIT, "a", "m.json", "0" * 64, _original_start_ns=time.monotonic_ns()), 1)
        self.assertEqual((order, json.loads(writes[-1][1])["causes"]), ([], ["manifest_hash"]))
        self.assertEqual(fresh.main(COMMIT, "a", "m.json", fresh.sha(self.raw), _original_start_ns=time.monotonic_ns()), 1)
        self.assertEqual((order, json.loads(writes[-1][1])["causes"]), (["PRE"], ["pre_info_refused"]))
        for args in (("x" * 40, "a"), (COMMIT, "")):
            with self.subTest(args=args):
                self.assertEqual(fresh.main(*args, "m.json", fresh.sha(self.raw), _original_start_ns=time.monotonic_ns()), 1)
        self.assertEqual(order, ["PRE"])

    def test_the_linux_phase_gets_less_time_than_windows_waits(self):
        run = fresh.Run(time.monotonic_ns())
        seen = []
        def process(self, argv, data, end, cap):
            seen.append((json.loads(data)["remaining_ns"], end - time.monotonic_ns()))
            return b'{"ok":true}\n', {"returncode": 0}
        with patch.object(fresh.Run, "process", process):
            run.phase("PRE", b"own", {"commit": COMMIT})
        left, window = seen[0]
        self.assertLessEqual(left, window - fresh.LINUX_MARGIN_NS + 50_000_000)
        self.assertLessEqual(left, fresh.PHASE_NS - fresh.LINUX_MARGIN_NS)

    def test_p0_needs_its_own_and_the_packet_budget(self):
        order, writes = self.main_world({"PRE": self.PRE, "EXPORT": {}, "PACKET": {}})
        status = fresh.main(COMMIT, "a", "m.json", fresh.sha(self.raw), _original_start_ns=time.monotonic_ns() - 100 * fresh.NS)
        self.assertEqual((status, order, json.loads(writes[-1][1])["causes"]), (1, ["PRE", "EXPORT"], ["p0_budget"]))

    def test_a_late_child_is_killed_and_waited_for_after_its_facts_are_copied(self):
        run = fresh.Run(time.monotonic_ns())
        with patch.object(fresh, "ENV", dict(os.environ)):
            with self.assertRaises(fresh.FreshRefusal) as caught:
                run.process([sys.executable, "-c", "import time;time.sleep(30)"], b"", time.monotonic_ns() + 300_000_000, 64)
        facts = caught.exception.facts["process"]
        self.assertEqual(caught.exception.cause, "phase_deadline")
        self.assertIsNone(facts["returncode"])
        self.assertTrue(facts["unknown_closure"])
        self.assertTrue(facts["kill"]["kill_called"])
        self.assertIn("wait_returncode", facts["kill"])

    def test_stdout_overflow_refuses(self):
        run = fresh.Run(time.monotonic_ns())
        with patch.object(fresh, "ENV", dict(os.environ)), self.assertRaises(fresh.FreshRefusal) as caught:
            run.process([sys.executable, "-c", "print('x'*100)"], b"", time.monotonic_ns() + 20 * fresh.NS, 64)
        self.assertEqual(caught.exception.cause, "pipe_overflow_or_read")

    def test_native_phases_refuse_an_existing_scope_or_resume_root(self):
        prefix = str(self.base / "vast-fixture-compiler-gate2-")
        root = prefix + COMMIT + "-01"
        with patch.object(fresh, "ROOT_PREFIX", prefix), patch.object(fresh, "RESUME_R1", str(self.base / "r1")), \
             patch.object(fresh, "_boot", return_value="b" * 36), patch.object(fresh, "_info", side_effect=AssertionError("info")):
            for path in (root, root + ".operator-originals", str(self.base / "r1")):
                os.mkdir(path)
                with self.subTest(path=path), self.assertRaisesRegex(fresh.FreshRefusal, "fresh_scope_exists"):
                    fresh.native_pre_v1({"commit": COMMIT}, time.monotonic_ns() + fresh.NS)
                os.rmdir(path)

    def test_native_export_writes_only_verified_bytes_exclusively(self):
        prefix = str(self.base / "vast-fixture-compiler-gate2-")
        root = prefix + COMMIT + "-01"
        repo = self.base / "repo"
        for rel, raw in self.files.items():
            (repo / rel).parent.mkdir(parents=True, exist_ok=True)
            (repo / rel).write_bytes(raw)
        built = []
        class Gate:
            @staticmethod
            def _resume_evidence_paths_v1():
                return {"b1_result": "/b/outputs/B1/probe.result.original.json"}
            @staticmethod
            def build_b2_index_v1(*, b_root, output_path):
                built.append((str(b_root), str(output_path)))
                return {"path": str(output_path), "size_bytes": 2, "sha256": "a" * 64}
        pre = dict(self.PRE, request_b64=base64.b64encode(fresh.INFO_REQUEST).decode(), reply_b64=base64.b64encode(b"HTTP/1.1 200 OK\r\n\r\n{}").decode())
        x = {"commit": COMMIT, "manifest_b64": base64.b64encode(self.raw).decode(), "pre": pre}
        with patch.object(fresh, "ROOT_PREFIX", prefix), patch.object(fresh, "RESUME_R1", str(self.base / "r1")), \
             patch.object(fresh, "REPO_LINUX", PurePosixPath(str(repo))), patch.object(fresh, "_boot", return_value="b" * 36), \
             patch.object(fresh, "_gate", return_value=Gate):
            record = fresh.native_export_v1(x, time.monotonic_ns() + 10 * fresh.NS)
            self.assertEqual(record["files"], len(fresh.EXPORT_CODE) + 1)
            self.assertEqual(built, [("/b", root + ".operator-originals/b2.corrected-index.v1.json")])
            for rel in fresh.EXPORT_CODE + (fresh.PLAN,):
                self.assertEqual(Path(root, rel).read_bytes(), self.files[rel])
                self.assertEqual(Path(root, rel).stat().st_mode & 0o777, 0o600)
            self.assertFalse(Path(root, fresh.OPERATOR).exists())
            self.assertEqual(sorted(os.listdir(root + ".operator-originals")), ["RPC01.reply.original", "RPC01.request.original",
                "manifest.original.json", "phase.export.original.json", "phase.pre.original.json"])
            with self.assertRaisesRegex(fresh.FreshRefusal, "fresh_scope_exists"):
                fresh.native_export_v1(x, time.monotonic_ns() + 10 * fresh.NS)
        (repo / fresh.PLAN).write_bytes(b"# drifted\n")
        root2 = prefix + "f" * 40 + "-01"
        manifest = dict(self.manifest, commit="f" * 40)
        x2 = dict(x, commit="f" * 40, manifest_b64=base64.b64encode(fresh.canonical(manifest)).decode())
        with patch.object(fresh, "ROOT_PREFIX", prefix), patch.object(fresh, "RESUME_R1", str(self.base / "r1")), \
             patch.object(fresh, "REPO_LINUX", PurePosixPath(str(repo))), patch.object(fresh, "_boot", return_value="b" * 36), \
             patch.object(fresh, "_gate", return_value=Gate), self.assertRaisesRegex(fresh.FreshRefusal, "manifest_binding"):
            fresh.native_export_v1(x2, time.monotonic_ns() + 10 * fresh.NS)
        self.assertFalse(Path(root2, fresh.PLAN).exists())

    def test_allocation_counts_every_entry_and_refuses_links(self):
        tree = self.base / "tree"
        (tree / "d").mkdir(parents=True)
        (tree / "d" / "a").write_bytes(b"x" * 5000)
        total = fresh.allocation_v1(str(tree))
        self.assertGreaterEqual(total, 4096 + 4096 + 8192 + 3 * 256)
        (tree / "l").symlink_to(tree / "d" / "a")
        with self.assertRaisesRegex(fresh.FreshRefusal, "allocation_unknown"):
            fresh.allocation_v1(str(tree))

    def test_authority_settles_its_own_allocation_into_the_charge(self):
        root, aux = str(self.base / "root"), str(self.base / "aux")
        os.mkdir(aux)
        Path(aux, "manifest.original.json").write_bytes(self.raw)
        info, facts, request, reply = gate_tests.ResumeInfoTests.native_shaped_info(self)
        pre = dict(self.PRE, measurement={"c_free_bytes": 10**11, "ext4_used_bytes": 3 * 10**11},
            reply_b64=base64.b64encode(reply).decode())
        x = {"commit": COMMIT, "approval": "approval", "pre": pre}
        pre_packet = {"c_free_bytes": 10**11 - 500_000, "ext4_used_bytes": 3 * 10**11 + 500_000}
        context, authority, charge, files = fresh.fresh_authority_v1(gate, root, aux, x, pre_packet, 400_000)
        own = (len(authority) + 4095) // 4096 * 4096 + 256
        self.assertEqual(context["allocation_bytes"], 400_000 + own)
        self.assertEqual(set(context), {"schema_version", "project_root", "consumer_commit", "approval_reference", "manifest",
            "operator", "plan", "f2_producer", "boot_id", "info", "measurements", "allocation_bytes", "noise_bytes", "excess_bytes"})
        self.assertEqual(charge["initial_charged_bytes"], gate.FRESH_BASE_CHARGE_V1 + charge["excess_bytes"])
        self.assertEqual(json.loads(authority)["context_sha256"], fresh.sha(fresh.canonical(context)))
        self.assertEqual(context["info"]["reply"], {"size_bytes": len(reply), "sha256": fresh.sha(reply)})

    def test_native_entry_refuses_bad_budget_without_stdout(self):
        writes = []
        with patch.object(fresh.os, "getuid", return_value=1000, create=True), \
             patch.object(fresh.os, "write", side_effect=lambda fd, raw: writes.append((fd, raw)) or len(raw)):
            for x in ({"remaining_ns": 0}, {"remaining_ns": fresh.PHASE_NS + 1}, {"remaining_ns": 1.0}):
                with self.subTest(x=x):
                    self.assertEqual(fresh.native_entry_v1("PRE", x), 1)
        self.assertEqual({fd for fd, _ in writes}, {2})
        self.assertEqual({json.loads(raw)["cause"] for _, raw in writes}, {"native_budget"})

    def test_info_decodes_the_engines_recorded_chunked_reply(self):
        from tests.fixtures.accepted_policy_change_paths_v1 import change_directory_v1
        outputs = change_directory_v1(ROOT) / "evidence/compiler-component-01/b1-01/outputs"
        request, reply = (outputs / "RPC02.request.original").read_bytes(), (outputs / "RPC02.reply.original").read_bytes()
        self.assertEqual(request, fresh.INFO_REQUEST)
        self.assertIn(b"Transfer-Encoding: chunked", reply)
        self.assertEqual(json.loads(fresh.http_body_v1(reply)), gate._http_json_v1(reply))
        sent = []

        class Socket:
            def __init__(self, *args):
                self.chunks = [reply[i:i + 4096] for i in range(0, len(reply), 4096)] + [b""]

            def settimeout(self, value):
                pass

            def connect(self, path):
                sent.append(path)

            def sendall(self, raw):
                sent.append(raw)

            def recv(self, n):
                return self.chunks.pop(0)

            def close(self):
                sent.append("closed")
        with patch.object(fresh.socket, "socket", Socket):
            raw, info = fresh._info()
        self.assertEqual((raw, info["ServerVersion"], sent), (reply, "29.7.2", [fresh.DOCKER_SOCKET, fresh.INFO_REQUEST, "closed"]))
        for broken in (reply.replace(b"200 OK", b"500 KO", 1), reply[:-5], reply + b"junk",
                       reply.replace(b"Transfer-Encoding: chunked", b"Content-Length: 1", 1)):
            with self.subTest(broken=broken[:20]), self.assertRaises(fresh.FreshRefusal):
                fresh.http_body_v1(broken)

    def test_pre_identity_matches_the_gate_and_refuses_drift(self):
        expected = {"ID": gate.EXPECTED["engine_id"], "ServerVersion": gate.EXPECTED["server_version"],
            "KernelVersion": gate.EXPECTED["kernel"], "Driver": gate.EXPECTED["driver"],
            "CgroupDriver": gate.EXPECTED["cgroup_driver"], "SecurityOptions": gate.EXPECTED["security_options"],
            "DockerRootDir": "/var/lib/docker", "CgroupVersion": "2", "Containers": 3, "ContainersRunning": 0,
            "ContainersPaused": 0, "ContainersStopped": 3}
        self.assertEqual(fresh.PRE_IDENTITY, expected)
        info, _, _, reply = gate_tests.ResumeInfoTests.native_shaped_info(self)
        prefix = str(self.base / "vast-fixture-compiler-gate2-")
        with patch.object(fresh, "ROOT_PREFIX", prefix), patch.object(fresh, "RESUME_R1", str(self.base / "r1")), \
             patch.object(fresh, "_boot", return_value="b" * 36):
            with patch.object(fresh, "_info", return_value=(reply, info)):
                value = fresh.native_pre_v1({"commit": COMMIT}, time.monotonic_ns() + fresh.NS)
            self.assertEqual((value["counts"], base64.b64decode(value["reply_b64"])), ([3, 0, 0, 3], reply))
            for key, wrong in (("KernelVersion", "6.6.99"), ("ContainersRunning", 1), ("SecurityOptions", [])):
                with self.subTest(key=key), patch.object(fresh, "_info", return_value=(reply, dict(info, **{key: wrong}))), \
                     self.assertRaisesRegex(fresh.FreshRefusal, "pre_identity"):
                    fresh.native_pre_v1({"commit": COMMIT}, time.monotonic_ns() + fresh.NS)
        self.assertFalse(Path(prefix + COMMIT + "-01").exists())

    def test_a_failed_phase_keeps_its_facts_and_native_cause(self):
        run = fresh.Run(time.monotonic_ns())
        process = {"returncode": None, "unknown_closure": True, "kill": {"kill_called": True, "wait_timed_out": True}}
        from tests.fixtures.accepted_policy_change_paths_v1 import change_directory_v1
        notice = (change_directory_v1(ROOT) / "evidence/compiler-component-01/gate2-fresh-01/nesting-check/client.err").read_bytes()
        self.assertIn(b"\x00", notice)  # the real UTF-16LE wsl.exe notice, as the operator decodes it
        stderr = (notice + b'{"cause":"manifest_binding","physical_acceptance":false}\n').decode("ascii", "replace")
        error = fresh.FreshRefusal("phase_status_nonzero", {"process": process, "stderr_prefix": stderr})
        with patch.object(fresh.Run, "process", side_effect=error), self.assertRaises(fresh.FreshRefusal) as caught:
            run.phase("EXPORT", b"own", {"commit": COMMIT})
        self.assertEqual(caught.exception.facts["failure"], {"phase": "EXPORT", "cause": "phase_status_nonzero",
            "native_cause": "manifest_binding", "returncode": None, "unknown_closure": True, "kill_called": True,
            "wait_timed_out": True})
        self.assertEqual(run.events[-1]["phase"], "EXPORT")

    def test_stderr_overflow_refuses(self):
        run = fresh.Run(time.monotonic_ns())
        with patch.object(fresh, "ENV", dict(os.environ)), self.assertRaises(fresh.FreshRefusal) as caught:
            run.process([sys.executable, "-c", "import sys;sys.stderr.write('x'*5000)"], b"",
                time.monotonic_ns() + 20 * fresh.NS, 64)
        self.assertEqual(caught.exception.cause, "pipe_overflow_or_read")


class NativePacketTests(unittest.TestCase):
    """native_packet_v1 against the real gate, in the controlled fresh world of the gate2_c tests."""
    COMMIT, BOOT, A = gate_tests.FreshPacketTests.COMMIT, gate_tests.FreshPacketTests.BOOT, gate_tests.FreshPacketTests.A
    setUp = gate_tests.FreshPacketTests.setUp
    write_manifest = gate_tests.FreshPacketTests.write_manifest
    authority_for = gate_tests.FreshPacketTests.authority_for

    def run_packet(self, p0=None):
        (self.aux / "operator.authority.original.json").unlink()
        evidence = {}
        for key in gate.EVIDENCE_NAMES:
            path = self.root.parent / ("evidence-" + key)
            path.write_bytes(b"{}")
            evidence[key] = path
        pre = self.context["measurements"]["pre"]
        near = {"c_free_bytes": pre["c_free_bytes"] - 100_000, "ext4_used_bytes": pre["ext4_used_bytes"] + 100_000}
        x = {"commit": self.COMMIT, "approval": self.review["approval_reference"], "pre": {"boot_id": self.BOOT,
            "measurement": pre, "reply_b64": base64.b64encode((self.aux / "RPC01.reply.original").read_bytes()).decode()},
            "p0": p0 or {"completion_record": {"relative_path": "p0-completion.v1.json", "encoded_bytes": 2,
                "sha256": fresh.sha(b"{}")}}}
        with patch.object(fresh, "_gate", return_value=gate), patch.object(fresh, "_boot", return_value=self.BOOT), \
             patch.object(fresh, "ROOT_PREFIX", gate.FRESH_ROOT_PREFIX_V1), \
             patch.object(fresh, "_measure", side_effect=[near, near]), \
             patch.object(gate, "_fresh_evidence_paths_v1", return_value=evidence):
            return fresh.native_packet_v1(x, time.monotonic_ns() + 10 * fresh.NS), evidence

    def test_native_packet_builds_writes_and_validates_the_fresh_packet(self):
        value, evidence = self.run_packet()
        raw = (self.root / "gate2.packet.original.json").read_bytes()
        self.assertEqual(value["packet"], {"size_bytes": len(raw), "sha256": fresh.sha(raw)})
        self.assertTrue(value["post_ok"])
        packet = json.loads(raw)
        self.assertEqual(packet["initial_charged_bytes"], gate.FRESH_BASE_CHARGE_V1)
        self.assertEqual(packet["fresh_context"]["allocation_bytes"], value["charge"]["allocation_bytes"])
        self.assertEqual(sorted(os.listdir(self.aux)), sorted(["RPC01.reply.original", "RPC01.request.original",
            "manifest.original.json", "operator.authority.original.json", "phase.p0.original.json",
            "measurements.original.json", "phase.packet.original.json"]))
        with patch.object(gate, "_fresh_evidence_paths_v1", return_value=evidence):
            desc = dict(value["packet"], path=str(self.root / "gate2.packet.original.json"))
            self.assertEqual(gate.validate_packet_v1(project_root=self.root, packet_descriptor=desc,
                expected_packet_sha256=desc["sha256"], expected_code_commit=self.COMMIT, _stage="C1"), packet)

    def test_native_packet_refuses_a_p0_completion_that_is_not_the_returned_one(self):
        with self.assertRaisesRegex(fresh.FreshRefusal, "p0_completion_binding"):
            self.run_packet({"completion_record": {"relative_path": "p0-completion.v1.json", "encoded_bytes": 2,
                "sha256": "f" * 64}})
        self.assertFalse((self.root / "gate2.packet.original.json").exists())


if __name__ == "__main__":
    unittest.main()
