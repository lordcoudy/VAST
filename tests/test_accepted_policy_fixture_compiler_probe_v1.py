"""2.10 gate-1 probe program and host runner; controlled Docker effects only."""
import hashlib
import io
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from tests.fixtures import accepted_policy_fixture_compiler_component_v1 as component
from tests.fixtures import accepted_policy_fixture_compiler_probe_program_v1 as program
from tests.fixtures import accepted_policy_fixture_compiler_probe_v1 as runner
from tests.fixtures import accepted_policy_fixture_compiler_v1 as compiler

POSIX = os.name == "posix"
COMMITTED = json.dumps({"Kind": "Committed", "Name": runner.EXPECTED["chain_id"],
                        "Parent": "sha256:" + "0" * 64}).encode()


class ProbeProgramTests(unittest.TestCase):
    def test_request_round_trip_and_binding(self):
        sources = {name: component.component_source_v1(name) for name in ("c1", "c2")}
        raw = runner.probe_request_v1("B1", sources)
        probe, parsed, request_raw = program.read_request(io.BytesIO(raw))
        self.assertEqual((probe, parsed), ("B1", sources))
        self.assertEqual(request_raw, raw[12:])
        tampered = raw[:-1] + bytes([raw[-1] ^ 1])
        with self.assertRaisesRegex(ValueError, "binding"):
            program.read_request(io.BytesIO(tampered))
        with self.assertRaisesRegex(ValueError, "trailing"):
            program.read_request(io.BytesIO(raw + b"x"))
        with self.assertRaisesRegex(ValueError, "probe"):
            program.read_request(io.BytesIO(runner.probe_request_v1("B9", {})))

    def test_rw_mount_rows_match_the_owner_rule(self):
        mountinfo = ("1 0 0:1 / / ro,relatime - overlay overlay ro,lowerdir=x\n"
                     "2 1 0:2 / /work rw,nosuid,nodev - tmpfs tmpfs rw,size=131072k,nr_inodes=4096\n"
                     "3 1 0:3 / /dev rw,nosuid - tmpfs tmpfs rw,mode=755\n"
                     "4 1 0:4 / /fixture/compiler.py ro,relatime - ext4 /dev/sde ro\n")
        rows, digest = program.rw_mount_rows(mountinfo)
        self.assertEqual(rows, [["/dev", "tmpfs", "rw,nosuid", "rw,mode=755"],
                                ["/work", "tmpfs", "rw,nosuid,nodev", "rw,size=131072k,nr_inodes=4096"]])
        self.assertEqual(digest, hashlib.sha256(compiler._compiler_json_v1(rows)).hexdigest())
        with self.assertRaises(ValueError):
            program.rw_mount_rows("malformed line\n")

    def test_export_frame_is_accepted_by_the_real_capture(self):
        report = program.canonical({"report": {"probe": "B2"}, "causes": []})
        request = runner.probe_request_v1("B2", {})[12:]
        frame = program.export_frame(report, b"", request, [])
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp).resolve()
            facts = compiler.capture_export_v1(io.BytesIO(frame).read, output)
            self.assertTrue(facts["complete"])
            self.assertEqual((output / "compiler.stdout.original").read_bytes(), report)
            self.assertEqual((output / "engine.unaccepted").read_bytes(), b"")
            self.assertFalse(facts["header"]["elf"]["available"])

    def test_assembly_probes_have_fixed_exit_codes(self):
        self.assertIn("$0x40000027", program.X32_ASM)
        self.assertIn("int $0x80", program.I386_ASM)
        self.assertIn("movl $3, %edi", program.X32_ASM)
        self.assertIn("movl $4, %edi", program.X32_ASM)
        self.assertIn("movl $4, %edi", program.I386_ASM)


class GuardHelperTests(unittest.TestCase):
    def test_p0_requires_the_exact_committed_chain(self):
        self.assertTrue(runner.p0_committed(COMMITTED))
        self.assertFalse(runner.p0_committed(COMMITTED.replace(b"Committed", b"Active")))
        self.assertFalse(runner.p0_committed(COMMITTED.replace(b"583abc", b"583abd")))
        self.assertFalse(runner.p0_committed(b"Kind: Committed"))

    def test_config_diff_records_without_enforcing(self):
        requested = {"Image": "x", "Labels": {"a": "1"}, "Volumes": {}, "HostConfig": {"CapAdd": [], "Memory": 1}}
        actual = {"Config": {"Labels": {"a": "1", "img": "2"}, "Volumes": None},
                  "HostConfig": {"CapAdd": None, "Memory": 1}}
        self.assertEqual(runner.config_diff(requested, actual), [
            ["HostConfig.CapAdd", [], None], ["Labels", {"a": "1"}, {"a": "1", "img": "2"}], ["Volumes", {}, None]])


@unittest.skipUnless(POSIX, "the fixed config requires absolute POSIX bind paths")
class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        fixtures = self.root / "tests" / "fixtures"
        fixtures.mkdir(parents=True)
        for name in ("accepted_policy_fixture_compiler_probe_program_v1.py", "accepted_policy_fixture_compiler_seccomp_v1.json"):
            (fixtures / name).write_bytes((ROOT / "tests/fixtures" / name).read_bytes())
        self.p0 = self.root / "p0.json"
        self.p0.write_bytes(COMMITTED)
        observed = ROOT / "openspec/changes/fix-accepted-policy-preprocessing/evidence/compiler-component-01/observations-01"
        self.info = json.loads((observed / "engine-info.v1_55.original.json").read_bytes())
        self.image = json.loads((observed / "provider-image-manifests.v1_55.original.json").read_bytes())
        self.version = {"Version": "29.7.2", "ApiVersion": "1.55", "MinAPIVersion": "1.40"}
        self.containers, self.calls, self.mode = [], [], "normal"
        self.c_free, self.gpu = 100 << 30, []

    def effects(self):
        case = self

        class Duplex:
            def __init__(self):
                self.facts = {"closed": False}
                self.sent = bytearray()
                self.stream = io.BytesIO()
            def arm_data_deadline(self, deadline):
                self.deadline = deadline
            def sendall(self, raw):
                self.sent.extend(raw)
            def shutdown_write(self):
                probe, sources, request_raw = program.read_request(io.BytesIO(bytes(self.sent)))
                frame = program.export_frame(program.canonical({"report": {"probe": probe}, "causes": []}),
                                             b"", request_raw, [])
                self.stream = io.BytesIO(b"\x01\x00\x00\x00" + struct.pack(">I", len(frame)) + frame)
            def read(self, count):
                if case.mode == "stall":
                    raise compiler.FixtureCompilerError("docker_data_deadline")
                return self.stream.read(count)
            def close(self):
                self.facts["closed"] = True

        class Client:
            def __init__(self, output, deadline):
                self.facts = {"attempts": 0, "metadata_bytes": 0}
                self.causes = []
            def request(self, method, path, body=None, deadline_ns=None, upgrade=False, cleanup=False):
                case.calls.append((method, path, body, deadline_ns))
                self.facts["attempts"] += 1
                if path == "/version":
                    return case.version
                if path == "/info":
                    return case.info
                if path.startswith("/images/"):
                    return case.image
                if path.startswith("/containers/json?"):
                    return case.containers
                if path.startswith("/containers/create?"):
                    case.config = body
                    return {"Id": "a" * 64, "Warnings": []}
                if "/attach?" in path:
                    return Duplex()
                if path.endswith("/start") or "/kill?" in path:
                    return None
                if "/wait?" in path:
                    if case.mode == "stall" and not any("SIGKILL" in p for _, p, *_ in case.calls):
                        raise compiler.FixtureCompilerError("docker_deadline")
                    return {"StatusCode": 137 if case.mode == "stall" else 0, "Error": None}
                if path.endswith("/json"):
                    return {"Config": {**case.config, "Labels": {**case.config["Labels"], "img": "x"}},
                            "HostConfig": case.config["HostConfig"], "State": {"Running": False, "Pid": 0,
                            "ExitCode": 137 if case.mode == "stall" else 0, "OOMKilled": False}}
                raise AssertionError("unselected endpoint " + path)

        live = {"pid": 42, "cgroup_path": "/system.slice/docker-" + "a" * 64 + ".scope", "mounts_sha256": "e" * 64}
        for name, value in (("_DockerClientV1", Client),
                            ("_compiler_process_facts_v1", lambda pid, cid: live),
                            ("_compiler_closed_facts_v1", lambda row, cid: {"closed": True}),
                            ("_compiler_proc_read_v1", lambda path, limit: b"mountinfo")):
            patcher = mock.patch.object(compiler, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        for name, value in (("_c_free_bytes", lambda: self.c_free), ("_gpu_processes", lambda: self.gpu)):
            patcher = mock.patch.object(runner, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_probe(self, probe="B1", **changes):
        options = dict(project_root=self.root, probe=probe, output_dir=self.root / ("out-" + probe),
                       p0_path=self.p0)
        options.update(changes)
        return runner.run_probe_container_v1(**options)

    def creates(self):
        return [path for _, path, *_ in self.calls if "/create?" in path]

    def test_b1_records_export_effective_diff_and_never_signals(self):
        self.effects()
        facts = self.run_probe("B1")
        self.assertEqual(facts["causes"], [])
        self.assertTrue(facts["export"]["complete"])
        self.assertEqual(facts["config_diff"], [["Labels", self.config["Labels"], {**self.config["Labels"], "img": "x"}]])
        self.assertFalse(any("/kill?" in path for _, path, *_ in self.calls))
        self.assertFalse(facts["accepted"])
        self.assertEqual(self.config["Entrypoint"], ["/usr/bin/python3", "-I", "-S", "-B", "/fixture/compiler.py"])
        self.assertEqual(self.config["HostConfig"]["Mounts"][0]["Source"],
                         str(self.root / runner.PROGRAM_RELATIVE))
        self.assertTrue((self.root / "out-B1" / "probe.result.original.json").is_file())

    def test_b3_stall_gets_one_term_then_one_kill_and_records_137(self):
        self.mode = "stall"
        self.effects()
        facts = self.run_probe("B3")
        kills = [path for _, path, *_ in self.calls if "/kill?" in path]
        self.assertEqual([path.rsplit("=", 1)[1] for path in kills], ["SIGTERM", "SIGKILL"])
        self.assertEqual(facts["final_state"]["ExitCode"], 137)
        self.assertIn("docker_deadline", facts["causes"])
        self.assertFalse(facts["accepted"])

    def test_pre_run_guard_drift_refuses_before_create(self):
        cases = {
            "p0": lambda: self.p0.write_bytes(COMMITTED.replace(b"Committed", b"Active")),
            "engine": lambda: self.info.update(ID="other"),
            "runtimes": lambda: self.info.update(Runtimes={}),
            "unpacked": lambda: self.image["Manifests"][0]["ImageData"]["Size"].update(Unpacked=1),
            "containers": lambda: self.containers.append({"Id": "b" * 64, "State": "exited"}),
            "capacity": lambda: setattr(self, "c_free", component.C_BYTES),
            "gpu": lambda: setattr(self, "gpu", ["123"]),
        }
        for label, mutate in cases.items():
            with self.subTest(label=label):
                self.setUp()
                mutate()
                self.effects()
                with self.assertRaises(runner.ProbeRefusal):
                    self.run_probe("B2")
                self.assertEqual(self.creates(), [])
                self.assertTrue((self.root / "out-B2" / "probe.refusal.original.json").is_file())

    def test_own_prior_stopped_containers_are_allowed(self):
        self.containers.append({"Id": "b" * 64, "State": "exited"})
        self.effects()
        facts = self.run_probe("B2", allowed_prior_cids=["b" * 64])
        self.assertEqual(len(self.creates()), 1)
        self.assertEqual(facts["causes"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
