"""Controlled D15 owner tests; no Docker, compiler, process, proc or ABI action."""
import hashlib
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from tests.fixtures import accepted_policy_fixture_compiler_v1 as compiler


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


class OwnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.source = self.root / "engine.c"
        self.source.write_bytes(b'#define STATE_FILE "/fresh/state"\n#define DAEMON_ID "fixture"\nint main(void){return 0;}\n')
        self.executable = self.root / "engine"
        self.publisher = self.root / "tests" / "fixtures" / "accepted_policy_fixture_compiler_publisher_v1.py"
        self.publisher.parent.mkdir(parents=True)
        self.publisher.write_bytes(b"# controlled publisher source\n")
        self.profile = self.publisher.parent / "accepted_policy_fixture_compiler_seccomp_v1.json"
        self.profile.write_bytes((ROOT / "tests/fixtures/accepted_policy_fixture_compiler_seccomp_v1.json").read_bytes())
        self.now = [1_000_000_000]
        self.mode, self.calls, self.clients = "normal", [], []
        self.image = {"Id": compiler.PROVIDER_ID, "Os": "linux", "Architecture": "amd64", "Size": 123,
            "RepoDigests": [compiler.PROVIDER], "RootFS": {"Type": "layers", "Layers": ["sha256:" + "b" * 64]},
            "Config": {"Volumes": None, "Env": ["PATH=/vendor"], "Labels": {}}}
        self.security = ["name=seccomp,profile=builtin", "name=cgroupns"]
        self.host = {"pid": 9, "start_ticks": 99, "boot_id": "00000000-0000-0000-0000-000000000001",
                     "kernel": "6.6.87.2-microsoft-standard-WSL2", "machine": "x86_64"}
        self.recipe = {"schema_version": 1, "artifact_kind": "vast_fixture_compiler_qualification_v1",
            "review": {"commit": "c" * 40, "approval_reference": "controlled-only", "evidence_sha256": "d" * 64},
            "bindings": self.bindings(), "engine": {"driver": "overlayfs", "cgroup_driver": "systemd",
                "security_options": self.security, "runtimes_sha256": digest(canonical({"runc": {"path": "runc"}}))},
            "provider": {"rootfs_sha256": digest(canonical(self.image["RootFS"])), "size_bytes": 123},
            "environment_keys": ["PATH"], "mounts_sha256": "e" * 64,
            "proofs": dict.fromkeys(("baseline", "toolchain", "abi", "limits", "closure"), "f" * 64)}
        self.qualification = self.seal("qualification.json", self.recipe)
        self.admit = {"schema_version": 1, "artifact_kind": "vast_fixture_compiler_admission_v1",
            "scope": "whole_chain_task1_5", "review": self.recipe["review"],
            "recipe_sha256": self.qualification["sha256"], "component_seed": None,
            "bindings": self.bindings(), "project_root": str(self.root),
            "source": {"relative_path": "engine.c", "size_bytes": self.source.stat().st_size,
                       "sha256": digest(self.source.read_bytes())}, "executable_relative": "engine",
            "physical_plan_sha256": "1" * 64, "whole_chain_admission_sha256": "2" * 64,
            "expires_unix_ns": time.time_ns() + 60_000_000_000, "boot_id": self.host["boot_id"],
            "metadata_upper_bytes": 262144, "retained_upper_bytes": 100_000_000,
            "additional_disk_upper_bytes": 100_000_000,
            "filesystem_floors": {"c_bytes": 42949672960, "project_bytes": 20971520}}
        self.admission = self.seal("admission.json", self.admit)

    def bindings(self):
        return {"host_sha256": digest(Path(compiler.__file__).read_bytes()),
                "publisher_sha256": digest(self.publisher.read_bytes()), "profile_sha256": compiler.PROFILE_SHA256}

    def seal(self, name, value):
        raw = canonical(value)
        path = self.root / name
        path.write_bytes(raw)
        return {"path": str(path), "size_bytes": len(raw), "sha256": digest(raw)}

    def function(self):
        function = getattr(compiler, "compile_fixture_engine_v1", None)
        self.assertTrue(callable(function), "fixed compiler owner is absent")
        return function

    def effects(self):
        case = self
        class Duplex:
            def __init__(self):
                self.facts = {"read_eof": False, "closed": False}
                self.sent = bytearray()
                self.stream = None
            def arm_data_deadline(self, deadline):
                self.deadline = deadline
            def sendall(self, raw):
                self.sent.extend(raw)
            def shutdown_write(self):
                if case.mode == "caller_loss":
                    case.signal_state[0] = "owner_signal_term"
                source = case.source.read_bytes()
                def member(raw):
                    return {"size_bytes": len(raw), "sha256": digest(raw), "eof": True,
                            "observed_bytes": len(raw), "discarded_bytes": 0}
                elf = bytearray(64)
                elf[:7] = b"\x7fELF\x02\x01\x01"
                elf[16:18], elf[18:20], elf[20:24] = (2).to_bytes(2, "little"), (62).to_bytes(2, "little"), (1).to_bytes(4, "little")
                header = {"schema_version": 1, "artifact_kind": "vast_fixture_compiler_export_v1",
                    "source": {"size_bytes": len(source), "sha256": digest(source)},
                    "runtime": {"pid": 1, "core": [1, 1], "fsize": [16777216, 16777216],
                        "interpreter_elf64_amd64": True, "compiler_elf64_amd64": True},
                    "compiler": {"returncode": 1 if case.mode == "compiler_failure" else 0,
                        "started": True, "reaped": True, "stdout": member(b""), "stderr": member(b"original compiler raw")},
                    "elf": {"size_bytes": len(elf), "sha256": digest(elf), "available": True},
                    "causes": [], "descendants_reaped": True}
                raw = canonical(header)
                self.stream = io.BytesIO(b"VASTCE1\n" + struct.pack(">I", len(raw)) + raw + b"original compiler raw" + elf)
            def read(self, count):
                raw = self.stream.read(count)
                self.facts["read_eof"] = not raw
                return raw
            def close(self):
                self.facts["closed"] = True

        class Client:
            def __init__(self, output, deadline):
                self.facts = {"metadata_bytes": 0, "rpc": [], "attempts": 0}
                self.causes = []
                self.config, self.name = None, None
                self.inspect_count = 0
                self.duplex = Duplex()
                case.clients.append(self)
            def _observe_endpoint(self):
                return ((1, 2, 0, 0, 0o140660, 17),)
            def request(self, method, path, body=None, **kwargs):
                case.calls.append((method, path, body, kwargs))
                self.facts["attempts"] += 1
                if case.mode == "metadata_failure" and path == "/info":
                    raise compiler.FixtureCompilerError("docker_metadata_cap")
                if path == "/version":
                    return {"Version": "29.7.2", "ApiVersion": "1.55", "MinAPIVersion": "1.44"}
                if path == "/info":
                    return {"ID": "1e493309-3767-45fb-9078-05b838bdfd80", "DockerRootDir": "/var/lib/docker",
                            "Driver": "overlayfs", "CgroupDriver": "systemd", "CgroupVersion": "2",
                            "SecurityOptions": case.security, "Runtimes": {"runc": {"path": "runc"}}}
                if path.startswith("/images/"):
                    return case.image
                if path.startswith("/containers/create?"):
                    self.name = parse_qs(urlsplit(path).query)["name"][0]
                    self.config = body
                    if case.mode in ("lost_create", "ambiguous_create"):
                        raise compiler.FixtureCompilerError("docker_io_TimeoutError")
                    return {"Id": "a" * 64, "Warnings": []}
                if path.startswith("/containers/json?"):
                    rows = [{"Id": "a" * 64, "ImageID": compiler.PROVIDER_ID,
                             "Names": ["/" + self.name], "Labels": self.config["Labels"]}]
                    return rows * 2 if case.mode == "ambiguous_create" else rows
                if "/attach?" in path:
                    return self.duplex
                if path.endswith("/start"):
                    return None
                if path.endswith("/json"):
                    self.inspect_count += 1
                    active = self.inspect_count == 1 and case.mode not in ("lost_create", "ambiguous_create")
                    return {"Id": "a" * 64, "Name": "/" + self.name, "Image": compiler.PROVIDER_ID,
                        "Config": self.config, "HostConfig": self.config["HostConfig"], "RestartCount": 0,
                        "State": {"Running": active, "Restarting": False, "Paused": False, "Dead": False,
                            "Pid": 42 if active else 0, "ExitCode": 1 if case.mode == "container_failure" else 0,
                            "OOMKilled": case.mode == "oom", "Error": ""}}
                if "/wait?" in path:
                    if case.mode == "source_post_drift":
                        case.source.write_bytes(b"changed after compiler start")
                    return {"StatusCode": 0, "Error": None}
                if "/kill?" in path:
                    return None
                raise AssertionError("unselected endpoint: " + path)
        live = {"pid": 42, "start_ticks": 77, "boot_id": self.host["boot_id"],
                "pid_namespace": [1, 8], "cgroup_path": "/system.slice/docker-" + "a" * 64 + ".scope",
                "mounts_sha256": "e" * 64, "populated": 1, "procs": [42]}
        closed = {"closed": self.mode != "closure_unknown", "populated": 0, "procs": [], "init_absent": True}
        stack = []
        for name, value in (("_DockerClientV1", Client), ("_CompilerAttachV1", lambda duplex, output: duplex),
                            ("_compiler_self_identity_v1", lambda: self.host),
                            ("_compiler_process_facts_v1", lambda pid, cid: live),
                            ("_compiler_closed_facts_v1", lambda row, cid: closed),
                            ("_compiler_source_mount_v1", lambda path: "/qualified/compiler.py"),
                            ("_compiler_directory_sync_v1", lambda path: None),
                            ("_compiler_install_handlers_v1", lambda received, previous: setattr(self, "signal_state", received)),
                            ("_compiler_restore_handlers_v1", lambda previous: []),
                            ("_compiler_floor_facts_v1", lambda project: {"c_free": 1_000_000_000_000, "project_free": 1_000_000_000_000})):
            effect = patch.object(compiler, name, value, create=True)
            effect.start()
            stack.append(effect)
        effect = patch.object(compiler.time, "monotonic_ns", lambda: self.now[0])
        effect.start()
        stack.append(effect)
        for effect in stack:
            self.addCleanup(effect.stop)

    def run_owner(self, **changes):
        options = dict(project_root=self.root, source_path=self.source, executable_path=self.executable,
                       qualification=self.qualification, admission=self.admission)
        options.update(changes)
        return self.function()(**options)

    def test_missing_admission_refuses_before_any_api(self):
        function = self.function()
        with patch.object(compiler, "_DockerClientV1") as api:
            with self.assertRaises(compiler.FixtureCompilerError):
                function(project_root=self.root, source_path=self.source, executable_path=self.executable)
        api.assert_not_called()
        self.assertFalse(self.executable.exists())

    def test_usable_fresh_elf_requires_both_closures_and_receipt(self):
        self.effects()
        result = self.run_owner()
        self.assertTrue(result["accepted"])
        self.assertEqual(self.executable.read_bytes()[:7], b"\x7fELF\x02\x01\x01")
        output = self.executable.parent / (self.executable.name + ".compiler-originals")
        self.assertTrue((output / "engine.unaccepted").is_file())
        receipt = json.loads((output / "owner.result.original.json").read_bytes())
        self.assertTrue(receipt["normal_closed"])
        self.assertIsNone(receipt["own_completion"])
        self.assertTrue(result["receipt_persisted"])
        self.assertLessEqual(len(self.calls), 20)
        self.assertFalse(any(method == "DELETE" for method, *_ in self.calls))

    def test_source_drift_refuses_before_api(self):
        self.effects()
        self.source.write_bytes(b"foreign")
        with self.assertRaises(compiler.FixtureCompilerError):
            self.run_owner()
        self.assertEqual(self.calls, [])

    def test_capability_without_whole_admission_never_promotes(self):
        self.effects()
        self.admit["scope"] = "component_only"
        self.admission = self.seal("admission.json", self.admit)
        with self.assertRaises(compiler.FixtureCompilerError):
            self.run_owner()
        self.assertEqual(self.calls, [])

    def test_unknown_fields_or_bool_size_refuse_before_api(self):
        self.effects()
        self.admission["size_bytes"] = True
        with self.assertRaises(compiler.FixtureCompilerError):
            self.run_owner()
        self.assertEqual(self.calls, [])

    def test_provider_volumes_refuse_before_create(self):
        self.effects()
        self.image["Config"]["Volumes"] = {"/disk": {}}
        with self.assertRaises(compiler.FixtureCompilerError):
            self.run_owner()
        self.assertFalse(any("/create?" in path for _, path, *_ in self.calls))

    def test_lost_create_reconciles_without_start_or_duplicate(self):
        self.mode = "lost_create"
        self.effects()
        with self.assertRaises(compiler.FixtureCompilerError) as found:
            self.run_owner()
        self.assertIn("docker_io_TimeoutError", found.exception.causes)
        self.assertEqual(sum("/create?" in path for _, path, *_ in self.calls), 1)
        self.assertFalse(any(path.endswith("/start") for _, path, *_ in self.calls))
        self.assertFalse(self.executable.exists())

    def test_ambiguous_create_never_guesses_cleanup(self):
        self.mode = "ambiguous_create"
        self.effects()
        with self.assertRaises(compiler.FixtureCompilerError):
            self.run_owner()
        self.assertFalse(any("/kill?" in path or path.endswith("/start") for _, path, *_ in self.calls))

    def test_compiler_original_nonzero_keeps_raw_and_no_accepted_elf(self):
        self.mode = "compiler_failure"
        self.effects()
        with self.assertRaises(compiler.FixtureCompilerError):
            self.run_owner()
        output = self.root / "engine.compiler-originals"
        self.assertEqual((output / "compiler.stderr.original").read_bytes(), b"original compiler raw")
        self.assertFalse(self.executable.exists())

    def test_oom_or_unknown_cgroup_never_accept(self):
        self.mode = "closure_unknown"
        self.effects()
        with self.assertRaises(compiler.FixtureCompilerError):
            self.run_owner()
        self.assertFalse(self.executable.exists())

    def test_deadline_without_full_containment_room_refuses_before_api(self):
        self.effects()
        with self.assertRaises(compiler.FixtureCompilerError):
            self.run_owner(absolute_deadline_ns=self.now[0] + 70_000_000_000)
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
